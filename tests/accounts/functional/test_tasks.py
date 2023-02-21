import json

from datetime import datetime, timedelta, timezone
from typing import Callable, Generator
from unittest import mock

import httpretty
import pytest
import requests

from pytest_mock import MockerFixture
from retry_tasks_lib.db.models import RetryTask
from retry_tasks_lib.enums import RetryTaskStatuses
from retry_tasks_lib.utils.synchronous import IncorrectRetryTaskStatusError
from sqlalchemy.orm import Session
from testfixtures import LogCapture

from cosmos.accounts.activity.enums import ActivityType as AccountsActivityType
from cosmos.accounts.config import account_settings
from cosmos.accounts.enums import AccountHolderStatuses
from cosmos.accounts.tasks.account_holder import (
    _get_active_campaigns,
    _process_callback,
    account_holder_activation,
    enrolment_callback,
    send_email,
)
from cosmos.db.models import AccountHolder, Campaign, EmailTemplateKey, Retailer
from cosmos.retailers.enums import EmailTemplateKeys, EmailTemplateTypes, RetailerStatuses
from tests.conftest import SetupType


class MockedOauthToken:
    @staticmethod
    def raise_for_status() -> None:
        return

    @staticmethod
    def json() -> dict:
        now = datetime.now(tz=timezone.utc)
        shift = timedelta(seconds=86400)

        return {
            "access_token": "mock-token",
            "refresh_token": "",
            "expires_in": "86400",
            "expires_on": int((now + shift).timestamp()),
            "not_before": int(now.timestamp()),
            "resource": "api://midas-nonprod",
            "token_type": "Bearer",
        }


fake_now = datetime.now(tz=timezone.utc)


@pytest.fixture(autouse=True)
def mock_auth_retry_session() -> Generator:
    with mock.patch(
        "cosmos.core.tasks.auth.retry_session",
        return_value=mock.MagicMock(
            get=mock.Mock(
                return_value=MockedOauthToken(),
            )
        ),
    ) as retry_session:
        yield retry_session


@pytest.fixture(scope="function")
def mock_counter_inc() -> Generator:
    with mock.patch("cosmos.core.prometheus.Counter.inc", autospec=True) as mock_metrics:
        yield mock_metrics


@httpretty.activate
@mock.patch("cosmos.accounts.tasks.account_holder.datetime")
def test__process_callback_ok(
    mock_datetime: mock.MagicMock,
    db_session: "Session",
    account_holder: "AccountHolder",
    enrolment_callback_task: RetryTask,
) -> None:
    mock_datetime.now.return_value = fake_now
    httpretty.register_uri("POST", "http://callback-url/", body="OK", status=200)

    account_holder.account_number = "TEST12345"
    db_session.commit()

    response_data = _process_callback(enrolment_callback_task.get_params(), account_holder)

    last_request = httpretty.last_request()
    assert last_request.method == "POST"
    assert last_request.url == "http://callback-url/"
    assert json.loads(last_request.body) == {
        "UUID": str(account_holder.account_holder_uuid),
        "email": "activate_1@test.user",
        "account_number": "TEST12345",
        "third_party_identifier": "identifier",
    }
    assert response_data == {
        "timestamp": fake_now.isoformat(),
        "request": {"url": "http://callback-url/"},
        "response": {
            "status": 200,
            "body": "OK",
        },
    }


@httpretty.activate
def test__process_callback_http_errors(
    db_session: "Session",
    account_holder: "AccountHolder",
    enrolment_callback_task: RetryTask,
    mock_counter_inc: mock.MagicMock,
    run_task_with_metrics: None,
) -> None:
    assert account_settings.core.ACTIVATE_TASKS_METRICS, "ACTIVATE_TASKS_METRICS must be set to True"

    account_holder.account_number = "TEST12345"
    db_session.commit()

    for status, body, metric_counter_inc in (
        (401, "Unauthorized", 1),
        (500, "Internal Server Error", 2),  # 5xx will be retried immediately
    ):
        httpretty.register_uri("POST", "http://callback-url/", body=body, status=status)

        with pytest.raises(requests.RequestException) as excinfo:
            _process_callback(enrolment_callback_task.get_params(), account_holder)

        assert isinstance(excinfo.value, requests.exceptions.RequestException)
        assert excinfo.value.response.status_code == status

        last_request = httpretty.last_request()
        assert last_request.method == "POST"
        assert json.loads(last_request.body) == {
            "UUID": str(account_holder.account_holder_uuid),
            "email": "activate_1@test.user",
            "account_number": "TEST12345",
            "third_party_identifier": "identifier",
        }
        assert mock_counter_inc.call_count == metric_counter_inc
        assert enrolment_callback_task.audit_data == []  # This is set in the exception handler


@httpretty.activate
@mock.patch("cosmos.accounts.tasks.account_holder.send_request_with_metrics")
def test__process_callback_connection_error(
    mock_send_request_with_metrics: mock.MagicMock,
    db_session: "Session",
    account_holder: "AccountHolder",
    enrolment_callback_task: RetryTask,
) -> None:
    account_holder.account_number = "TEST12345"
    db_session.commit()

    mock_send_request_with_metrics.side_effect = requests.Timeout("Request timed out")

    with pytest.raises(requests.RequestException) as excinfo:
        _process_callback(enrolment_callback_task.get_params(), account_holder)

    assert isinstance(excinfo.value, requests.Timeout)
    assert excinfo.value.response is None
    assert enrolment_callback_task.audit_data == []  # This is set in the exception handler


@httpretty.activate
def test__get_active_campaigns(setup: SetupType) -> None:
    db_session, retailer, campaign = setup
    campaign.slug = "slug1"
    db_session.commit()
    expected_slug = "slug1"
    campaigns = _get_active_campaigns(db_session, retailer)
    for campaign in campaigns:
        assert campaign.slug == expected_slug


@pytest.mark.parametrize("balance_lifespan", [10, 0])
@httpretty.activate
def test_account_holder_activation(
    balance_lifespan: int | None,
    db_session: "Session",
    account_holder: "AccountHolder",
    campaign: "Campaign",
    test_retailer: dict,
    account_holder_activation_task: RetryTask,
    mocker: MockerFixture,
) -> None:
    campaign.retailer_id = account_holder.retailer_id
    account_holder.retailer.balance_lifespan = balance_lifespan
    db_session.commit()

    assert account_holder.status == AccountHolderStatuses.PENDING
    assert account_holder.account_number is None

    mock_get_account_enrolment_activity_data = mocker.patch(
        "cosmos.accounts.activity.enums.ActivityType.get_account_enrolment_activity_data",
        return_value={"mock": "payload"},
    )
    mock_send_activity = mocker.patch("cosmos.accounts.tasks.account_holder.sync_send_activity")

    account_holder_activation(retry_task_id=account_holder_activation_task.retry_task_id)

    db_session.refresh(account_holder_activation_task)
    db_session.refresh(account_holder)

    assert account_holder_activation_task.attempts == 1
    assert account_holder_activation_task.next_attempt_time is None
    assert account_holder_activation_task.status == RetryTaskStatuses.SUCCESS
    assert len(account_holder.current_balances) == 1
    assert account_holder.account_number is not None
    assert account_holder.account_number.startswith(test_retailer["account_number_prefix"])
    assert account_holder.current_balances[0].campaign.slug == "test-campaign"
    assert account_holder.current_balances[0].balance == 0
    # assert account_holder.current_balances[1].campaign_slug == "slug2"
    # assert account_holder.current_balances[1].balance == 0
    if balance_lifespan:
        assert account_holder.current_balances[0].reset_date is not None
        # assert account_holder.current_balances[1].reset_date is not None
    else:
        assert account_holder.current_balances[0].reset_date is None
        # assert account_holder.current_balances[1].reset_date is None
    assert account_holder.status == AccountHolderStatuses.ACTIVE
    mock_get_account_enrolment_activity_data.assert_called_once_with(
        account_holder_uuid=account_holder.account_holder_uuid,
        activity_datetime=account_holder.updated_at.replace(tzinfo=timezone.utc),
        channel="test-channel",
        retailer_slug=account_holder.retailer.slug,
        third_party_identifier="test_3rd_perty_id",
    )
    mock_send_activity.assert_called_once_with(
        {"mock": "payload"}, routing_key=AccountsActivityType.ACCOUNT_ENROLMENT.value
    )


def test_activate_account_holder_wrong_status(
    db_session: "Session",
    account_holder_activation_task: RetryTask,
) -> None:
    account_holder_activation_task.status = RetryTaskStatuses.FAILED
    db_session.commit()

    with pytest.raises(IncorrectRetryTaskStatusError):
        account_holder_activation(retry_task_id=account_holder_activation_task.retry_task_id)

    db_session.refresh(account_holder_activation_task)

    assert account_holder_activation_task.attempts == 0
    assert account_holder_activation_task.next_attempt_time is None
    assert account_holder_activation_task.status == RetryTaskStatuses.FAILED


@httpretty.activate
@pytest.mark.parametrize(
    "retailer_status,expected_task_status,expected_account_holder_status",
    [
        (
            RetailerStatuses.TEST,
            RetryTaskStatuses.SUCCESS,
            AccountHolderStatuses.ACTIVE,
        ),
        (
            RetailerStatuses.ACTIVE,
            RetryTaskStatuses.WAITING,
            AccountHolderStatuses.PENDING,
        ),
    ],
)
def test_account_holder_activation_no_active_campaigns(
    retailer_status: RetailerStatuses,
    expected_task_status: RetryTaskStatuses,
    expected_account_holder_status: AccountHolderStatuses,
    mocker: "MockerFixture",
    db_session: "Session",
    account_holder: "AccountHolder",
    account_holder_activation_task: RetryTask,
) -> None:
    mock_sentry = mocker.patch("cosmos.accounts.tasks.account_holder.sentry_sdk")
    mock_get_account_enrolment_activity_data = mocker.patch.object(
        AccountsActivityType, "get_account_enrolment_activity_data"
    )
    assert account_holder.status == AccountHolderStatuses.PENDING
    assert account_holder.account_number is None

    account_holder.retailer.status = retailer_status
    db_session.commit()

    account_holder_activation(retry_task_id=account_holder_activation_task.retry_task_id)

    db_session.refresh(account_holder_activation_task)
    db_session.refresh(account_holder)

    assert account_holder_activation_task.attempts == 1
    assert account_holder_activation_task.next_attempt_time is None
    assert account_holder_activation_task.status == expected_task_status
    assert account_holder.account_number is not None
    assert account_holder.account_number.startswith(account_holder.retailer.account_number_prefix)
    assert account_holder.status == expected_account_holder_status
    assert len(account_holder.current_balances) == 0

    if retailer_status == RetailerStatuses.TEST:
        mock_get_account_enrolment_activity_data.assert_called_once()

    elif retailer_status == RetailerStatuses.ACTIVE:
        mock_get_account_enrolment_activity_data.assert_not_called()
        assert (
            f"The activation of account holder id: {account_holder.id} could not be completed due to "
            f"there being no active campaigns for the retailer {account_holder.retailer.slug}, or the "
            "account holder not being in PENDING state."
        ) in mock_sentry.capture_message.call_args.args[0]


@mock.patch("cosmos.accounts.tasks.account_holder.datetime")
@httpretty.activate
def test_enrolment_callback(
    mock_datetime: mock.MagicMock,
    db_session: "Session",
    account_holder: "AccountHolder",
    enrolment_callback_task: RetryTask,
) -> None:
    mock_datetime.now.return_value = fake_now
    assert account_holder.account_number is None

    httpretty.register_uri("POST", "http://callback-url/", body="OK", status=200)

    enrolment_callback(retry_task_id=enrolment_callback_task.retry_task_id)

    db_session.refresh(enrolment_callback_task)
    db_session.refresh(account_holder)

    assert enrolment_callback_task.attempts == 1
    assert enrolment_callback_task.next_attempt_time is None
    assert enrolment_callback_task.status == RetryTaskStatuses.SUCCESS
    assert enrolment_callback_task.audit_data == [
        {
            "request": {"url": "http://callback-url/"},
            "response": {"body": "OK", "status": 200},
            "timestamp": fake_now.isoformat(),
        }
    ]


@httpretty.activate
def test_send_email_task(
    db_session: "Session",
    account_holder: "AccountHolder",
    send_welcome_email_task: RetryTask,
    populate_email_template_req_keys: list[EmailTemplateKey],
    create_email_template: Callable,
    retailer: Retailer,
    mocker: MockerFixture,
    capture: LogCapture,
) -> None:
    mock_settings = mocker.patch("cosmos.core.tasks.mailjet.core_settings")
    mock_settings.SEND_EMAIL = True
    mock_settings.MAILJET_API_URL = "http://fake-mailjet.com"
    mock_settings.MAILJET_API_PUBLIC_KEY = "potato"
    mock_settings.MAILJET_API_SECRET_KEY = "sausage"  # noqa: S105
    account_holder.account_number = "TEST1234"
    db_session.commit()
    fake_response_body = json.dumps(
        {
            "Messages": [
                {
                    "Status": "success",
                    "To": [
                        {
                            "Email": "activate_1@test.user",
                            "MessageUUID": "123",
                            "MessageID": 456,
                            "MessageHref": "https://api.mailjet.com/v3/message/456",
                        }
                    ],
                }
            ]
        }
    )
    email_template_req_keys: list[EmailTemplateKey] = populate_email_template_req_keys
    email_template_params = {
        "template_id": "1234",
        "type": EmailTemplateTypes.WELCOME_EMAIL,
        "retailer_id": retailer.id,
        "required_keys": email_template_req_keys,
    }
    create_email_template(**email_template_params)

    httpretty.register_uri(
        "POST",
        mock_settings.MAILJET_API_URL,
        body=fake_response_body,
        status=200,
    )

    send_email(retry_task_id=send_welcome_email_task.retry_task_id)

    db_session.refresh(send_welcome_email_task)
    db_session.refresh(account_holder)

    assert send_welcome_email_task.attempts == 1
    assert send_welcome_email_task.next_attempt_time is None
    assert send_welcome_email_task.status == RetryTaskStatuses.SUCCESS
    assert send_welcome_email_task.audit_data == [
        {
            "request": {"url": account_settings.core.MAILJET_API_URL},
            "response": {
                "body": fake_response_body,
                "status": 200,
            },
            "timestamp": mocker.ANY,
        }
    ]


@httpretty.activate
def test_send_email_task_with_send_email_set_to_false(
    db_session: "Session",
    account_holder: "AccountHolder",
    send_welcome_email_task: RetryTask,
    populate_email_template_req_keys: list[EmailTemplateKey],
    create_email_template: Callable,
    retailer: Retailer,
    mocker: MockerFixture,
    capture: LogCapture,
) -> None:
    mock_settings = mocker.patch("cosmos.core.tasks.mailjet.core_settings")
    mock_settings.SEND_EMAIL = False
    mock_settings.MAILJET_API_URL = "http://fake-mailjet.com"
    mock_settings.MAILJET_API_PUBLIC_KEY = "potato"
    mock_settings.MAILJET_API_SECRET_KEY = "sausage"  # noqa: S105
    account_holder.account_number = "TEST1234"
    db_session.commit()
    fake_response_body = json.dumps(
        {
            "Messages": [
                {
                    "Status": "success",
                    "To": [
                        {
                            "Email": "activate_1@test.user",
                            "MessageUUID": "123",
                            "MessageID": 456,
                            "MessageHref": "https://api.mailjet.com/v3/message/456",
                        }
                    ],
                }
            ]
        }
    )
    email_template_req_keys: list[EmailTemplateKey] = populate_email_template_req_keys
    email_template_params = {
        "template_id": "1234",
        "type": EmailTemplateTypes.WELCOME_EMAIL,
        "retailer_id": retailer.id,
        "required_keys": email_template_req_keys,
    }
    create_email_template(**email_template_params)

    httpretty.register_uri(
        "POST",
        mock_settings.MAILJET_API_URL,
        body=fake_response_body,
        status=200,
    )

    send_email(retry_task_id=send_welcome_email_task.retry_task_id)

    db_session.refresh(send_welcome_email_task)
    db_session.refresh(account_holder)

    assert send_welcome_email_task.attempts == 1
    assert send_welcome_email_task.next_attempt_time is None
    assert send_welcome_email_task.status == RetryTaskStatuses.SUCCESS
    assert send_welcome_email_task.audit_data == ["No mail sent due to SEND_MAIL=False"]


def test_send_email_task_missing_req_fields(
    db_session: "Session",
    account_holder: "AccountHolder",
    send_welcome_email_task: RetryTask,
    populate_email_template_req_keys: list[EmailTemplateKey],
    create_email_template: Callable,
    retailer: Retailer,
    mocker: MockerFixture,
    capture: LogCapture,
) -> None:
    account_holder.email = ""
    db_session.commit()
    email_template_req_keys: list[EmailTemplateKey] = populate_email_template_req_keys
    email_template_params = {
        "template_id": "test1234",
        "type": EmailTemplateTypes.WELCOME_EMAIL,
        "retailer_id": retailer.id,
        "required_keys": email_template_req_keys,
    }
    create_email_template(**email_template_params)

    import cosmos.core.tasks.mailjet as tasks_mailjet

    mock_send_email_to_mailjet = mocker.spy(tasks_mailjet, "send_email_to_mailjet")

    send_email(retry_task_id=send_welcome_email_task.retry_task_id)

    db_session.refresh(send_welcome_email_task)
    db_session.refresh(account_holder)

    assert send_welcome_email_task.attempts == 1
    assert send_welcome_email_task.next_attempt_time is None
    assert send_welcome_email_task.status == RetryTaskStatuses.FAILED
    assert send_welcome_email_task.audit_data == []
    assert any(
        f"Mailjet failure - missing fields: "
        f"['{EmailTemplateKeys.ACCOUNT_NUMBER.value}', '{EmailTemplateKeys.EMAIL.value}']" in str(record.exc_info)
        for record in capture.records
    )
    mock_send_email_to_mailjet.assert_not_called()


# def test_send_email_task_missing_extra_params(
#     db_session: "Session",
#     account_holder: "AccountHolder",
#     send_reward_email_task_no_extra_params: RetryTask,
#     populate_email_template_req_keys: list[EmailTemplateKey],
#     create_email_template: Callable,
#     retailer: Retailer,
#     mocker: MockerFixture,
#     capture: LogCapture,
# ) -> None:
#     account_holder.account_number = "TEST1234"
#     db_session.commit()
#     email_template_req_keys: list[EmailTemplateKey] = populate_email_template_req_keys
#     email_template_params = {
#         "template_id": "test1234",
#         "type": EmailTemplateTypes.REWARD_ISSUANCE,
#         "retailer_id": retailer.id,
#         "required_keys": email_template_req_keys,
#     }
#     create_email_template(**email_template_params)

#     import cosmos.core.tasks.mailjet as tasks_mailjet

#     mock_send_email_to_mailjet = mocker.spy(tasks_mailjet, "send_email_to_mailjet")

#     send_email(
#         retry_task_id=send_reward_email_task_no_extra_params.retry_task_id
#     )

#     db_session.refresh(send_reward_email_task_no_extra_params)
#     db_session.refresh(account_holder)

#     assert send_reward_email_task_no_extra_params.attempts == 1
#     assert send_reward_email_task_no_extra_params.next_attempt_time is None
#     assert send_reward_email_task_no_extra_params.status == RetryTaskStatuses.FAILED
#     assert send_reward_email_task_no_extra_params.audit_data == []
#     assert any("Mailjet failure - missing fields: ['reward_url']"
#     in str(record.exc_info) for record in capture.records)
#     mock_send_email_to_mailjet.assert_not_called()


@httpretty.activate
def test_send_email_task_400(
    db_session: "Session",
    account_holder: "AccountHolder",
    send_welcome_email_task: RetryTask,
    populate_email_template_req_keys: list[EmailTemplateKey],
    create_email_template: Callable,
    retailer: Retailer,
    mocker: "MockerFixture",
    capture: LogCapture,
) -> None:
    mock_sentry = mocker.patch("cosmos.accounts.tasks.account_holder.sentry_sdk")
    mock_settings = mocker.patch("cosmos.core.tasks.mailjet.core_settings")
    mock_settings.SEND_EMAIL = True
    mock_settings.MAILJET_API_URL = "http://fake-mailjet.com"
    mock_settings.MAILJET_API_PUBLIC_KEY = "potato"
    mock_settings.MAILJET_API_SECRET_KEY = "sausage"  # noqa: S105
    account_holder.account_number = "TEST1234"
    db_session.commit()
    fake_response_body = json.dumps(
        {
            "Messages": {
                "Errors": [
                    {
                        "ErrorIdentifier": "88b5ca9f-5f1f-42e7-a45e-9ecbad0c285e",
                        "ErrorCode": "send-0003",
                        "StatusCode": 400,
                        "ErrorMessage": 'At least "HTMLPart", "TextPart" or "TemplateID" must be provided.',
                        "ErrorRelatedTo": ["HTMLPart", "TextPart"],
                    }
                ],
            }
        }
    )
    email_template_req_keys: list[EmailTemplateKey] = populate_email_template_req_keys
    email_template_params = {
        "template_id": "1234",
        "type": EmailTemplateTypes.WELCOME_EMAIL,
        "retailer_id": retailer.id,
        "required_keys": email_template_req_keys,
    }
    create_email_template(**email_template_params)

    httpretty.register_uri(
        "POST",
        mock_settings.MAILJET_API_URL,
        body=fake_response_body,
        status=400,
    )

    with pytest.raises(requests.exceptions.HTTPError) as excinfo:
        send_email(retry_task_id=send_welcome_email_task.retry_task_id)

    db_session.refresh(send_welcome_email_task)
    db_session.refresh(account_holder)

    assert excinfo.value.response.status_code == 400
    assert send_welcome_email_task.attempts == 1
    assert send_welcome_email_task.next_attempt_time is None
    assert send_welcome_email_task.status == RetryTaskStatuses.FAILED
    assert send_welcome_email_task.audit_data == [
        {
            "request": {"url": account_settings.core.MAILJET_API_URL},
            "response": {
                "body": fake_response_body,
                "status": 400,
            },
            "timestamp": mocker.ANY,
        }
    ]
    msg = (
        f"Email error: MailJet HTTP code: 400, retailer slug: {retailer.slug}, "
        f"email type: {EmailTemplateTypes.WELCOME_EMAIL.name}, template id: 1234"
    )
    assert any(msg in record.message for record in capture.records)
    assert msg in mock_sentry.capture_message.call_args.args[0]
