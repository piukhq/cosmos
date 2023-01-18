from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable
from unittest import mock

import pytest

from fastapi import status as fastapi_http_status
from pytest_mock import MockerFixture
from sqlalchemy.future import select

from cosmos.accounts.enums import AccountHolderStatuses
from cosmos.campaigns.enums import CampaignStatuses
from cosmos.core.config import settings
from cosmos.core.error_codes import ErrorCode
from cosmos.db.models import CampaignBalance, PendingReward, Reward
from cosmos.retailers.enums import RetailerStatuses
from tests.conftest import SetupType

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from requests import Response

    from cosmos.db.models import Campaign, Retailer


auth_headers = {"Authorization": f"Token {settings.VELA_API_AUTH_TOKEN}", "Bpl-User-Channel": "channel"}


@pytest.fixture(scope="function")
def mock_activity(mocker: MockerFixture) -> mock.MagicMock:
    return mocker.patch("cosmos.campaigns.api.service.format_and_send_activity_in_background")


def validate_error_response(response: "Response", error: ErrorCode) -> None:
    resp_json: dict = response.json()
    error_detail: dict = error.value.detail.dict(exclude_unset=True)

    assert response.status_code == error.value.status_code
    assert resp_json["display_message"] == error_detail["display_message"]
    assert resp_json["code"] == error_detail["code"]


def test_status_change_mangled_json(test_client: "TestClient", setup: SetupType) -> None:
    retailer = setup.retailer

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        data=b"{",
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_400_BAD_REQUEST
    assert resp.json() == {
        "display_message": "Malformed request.",
        "code": "MALFORMED_REQUEST",
    }


def test_status_change_invalid_token(test_client: "TestClient", setup: SetupType, campaign: "Campaign") -> None:
    retailer = setup.retailer
    payload = {
        "requested_status": "ended",
        "campaign_slugs": [campaign.slug],
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers={"Authorization": "Token wrong token"},
    )

    assert resp.status_code == fastapi_http_status.HTTP_401_UNAUTHORIZED
    assert resp.json() == {
        "display_message": "Supplied token is invalid.",
        "code": "INVALID_TOKEN",
    }


def test_status_change_invalid_retailer(test_client: "TestClient", campaign: "Campaign") -> None:

    payload = {
        "requested_status": "ended",
        "campaign_slug": campaign.slug,
    }
    bad_retailer = "WRONG_RETAILER"

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{bad_retailer}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, ErrorCode.INVALID_RETAILER)


def test_status_change_campaign_not_found(test_client: "TestClient", setup: SetupType) -> None:
    retailer = setup.retailer
    payload = {
        "requested_status": "ended",
        "campaign_slug": "WRONG_CAMPAIGN_SLUG_1",
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_404_NOT_FOUND
    validate_error_response(resp, ErrorCode.NO_CAMPAIGN_FOUND)


def test_status_change_campaign_does_not_belong_to_retailer(
    test_client: "TestClient",
    setup: SetupType,
    campaign: "Campaign",
    create_mock_retailer: Callable[..., "Retailer"],
    mock_activity: mock.MagicMock,
) -> None:
    db_session = setup.db_session
    campaign.status = CampaignStatuses.DRAFT  # Set to DRAFT just so the status transition requested won't trigger 409
    db_session.commit()
    payload = {
        "requested_status": "active",
        "campaign_slug": campaign.slug,  # legitimate slug
        "activity_metadata": {"sso_username": "Jane Doe"},
    }
    # Create a second retailer who should not be able to change status of the campaign above
    second_retailer = create_mock_retailer(slug="second-retailer")

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{second_retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, ErrorCode.NO_CAMPAIGN_FOUND)
    mock_activity.assert_not_called()


@pytest.mark.parametrize(
    "campaign_slug",
    [
        pytest.param("    ", id="spaces string"),
        pytest.param("\t\t\t\r", id="tabs and return string"),
        pytest.param("\t\t\t\n", id="tabs and new line string"),
        pytest.param("", id="empty string"),
    ],
)
def test_status_change_whitespace_validation_fail_is_422(
    campaign_slug: str, setup: SetupType, mock_activity: mock.MagicMock, test_client: "TestClient"
) -> None:
    retailer = setup.retailer

    payload = {
        "requested_status": "ended",
        "campaign_slug": campaign_slug,
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json() == {
        "display_message": "Submitted fields are missing or invalid.",
        "code": "FIELD_VALIDATION_ERROR",
        "fields": ["campaign_slug"],
    }
    mock_activity.assert_not_called()


def test_status_change_fields_fail_validation(
    test_client: "TestClient", setup: SetupType, campaign: "Campaign", mock_activity: mock.MagicMock
) -> None:
    db_session, retailer, _ = setup

    payload = {
        "requested_status": "BAD_ACTION_TYPE",
        "campaign_slug": campaign.slug,
    }

    campaign.status = CampaignStatuses.ACTIVE
    db_session.commit()

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json() == {
        "display_message": "Submitted fields are missing or invalid.",
        "code": "FIELD_VALIDATION_ERROR",
        "fields": ["requested_status", "activity_metadata"],
    }

    mock_activity.assert_not_called()


def test_status_change_illegal_state(
    test_client: "TestClient", setup: SetupType, campaign: "Campaign", mock_activity: mock.MagicMock
) -> None:
    db_session, retailer, _ = setup
    campaign.status = CampaignStatuses.DRAFT
    db_session.commit()
    payload = {
        "requested_status": "ended",
        "campaign_slug": campaign.slug,
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, ErrorCode.INVALID_STATUS_REQUESTED)

    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.DRAFT

    mock_activity.assert_not_called()


def test_status_change_no_active_campaign_left_error_for_active_retailer(
    test_client: "TestClient", setup: SetupType, campaign: "Campaign"
) -> None:

    db_session, retailer, _ = setup

    campaign.status = CampaignStatuses.ACTIVE
    retailer.status = RetailerStatuses.ACTIVE
    db_session.commit()

    payload = {
        "requested_status": "ended",
        "campaign_slug": campaign.slug,
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, ErrorCode.INVALID_STATUS_REQUESTED)
    db_session.refresh(campaign)
    assert campaign.status == CampaignStatuses.ACTIVE


@pytest.mark.parametrize(
    "campaign_status",
    [
        CampaignStatuses.ENDED,
        CampaignStatuses.CANCELLED,
    ],
)
def test_status_change_no_active_campaign_left_ok_for_test_retailer(
    campaign_status: CampaignStatuses,
    test_client: "TestClient",
    setup: SetupType,
    campaign_with_rules: "Campaign",
    mock_activity: mock.MagicMock,
) -> None:

    db_session, retailer, _ = setup

    campaign_with_rules.status = CampaignStatuses.ACTIVE
    retailer.status = RetailerStatuses.TEST
    db_session.commit()

    payload = {
        "requested_status": campaign_status.value,
        "campaign_slug": campaign_with_rules.slug,
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    assert resp.json() == {}
    db_session.refresh(campaign_with_rules)
    assert campaign_with_rules.status == campaign_status

    mock_activity.assert_called()


def test_status_change_activating_a_campaign_ok(
    test_client: "TestClient",
    setup: SetupType,
    campaign_with_rules: "Campaign",
    mock_activity: mock.MagicMock,
    mocker: MockerFixture,
) -> None:
    now = datetime.now(tz=timezone.utc)
    db_session, retailer, account_holder = setup

    def get_balances() -> CampaignBalance:
        return db_session.scalars(
            select(CampaignBalance).where(
                CampaignBalance.account_holder_id == account_holder.id,
                CampaignBalance.campaign_id == campaign_with_rules.id,
            )
        ).all()

    assert get_balances() == []
    assert retailer.balance_lifespan == 0

    account_holder.status = AccountHolderStatuses.ACTIVE
    campaign_with_rules.start_date = None
    campaign_with_rules.end_date = None
    campaign_with_rules.status = CampaignStatuses.DRAFT
    db_session.commit()

    mock_datetime = mocker.patch("cosmos.campaigns.api.crud.datetime")
    mock_datetime.now.return_value = now

    payload = {
        "requested_status": "active",
        "campaign_slug": campaign_with_rules.slug,
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    assert resp.json() == {}
    mock_datetime.now.assert_called_once()

    db_session.refresh(campaign_with_rules)
    assert campaign_with_rules.status == CampaignStatuses.ACTIVE
    assert campaign_with_rules.end_date is None
    assert campaign_with_rules.start_date == now.replace(tzinfo=None)

    assert (balances := get_balances()), "No balance was created"
    new_balance, *other = balances
    assert not other
    assert new_balance.campaign_id == campaign_with_rules.id
    assert new_balance.balance == 0
    assert new_balance.reset_date is None

    mock_activity.assert_called_once()


@pytest.mark.parametrize("missing_rule", ["earn_rule", "reward_rule"])
def test_activating_a_campaign_with_missing_rule(
    missing_rule: str, test_client: "TestClient", setup: SetupType, campaign_with_rules: "Campaign"
) -> None:
    db_session, retailer, _ = setup

    campaign_with_rules.status = CampaignStatuses.DRAFT
    db_session.delete(getattr(campaign_with_rules, missing_rule))
    db_session.commit()

    payload = {
        "requested_status": "active",
        "campaign_slug": campaign_with_rules.slug,
        "activity_metadata": {"sso_username": "Jane Doe"},
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    validate_error_response(resp, ErrorCode.MISSING_CAMPAIGN_COMPONENTS)

    db_session.refresh(campaign_with_rules)
    assert campaign_with_rules.status == CampaignStatuses.DRAFT


@pytest.mark.parametrize("pending_rewards_action", ["remove", "convert"])
def test_status_change_ending_campaign_ok(
    pending_rewards_action: str,
    test_client: "TestClient",
    setup: SetupType,
    campaign_with_rules: "Campaign",
    campaign_balance: CampaignBalance,
    pending_reward: PendingReward,
    mock_activity: mock.MagicMock,
    mocker: MockerFixture,
) -> None:
    db_session, retailer, _ = setup

    retailer.status = RetailerStatuses.TEST
    campaign_with_rules.status = CampaignStatuses.ACTIVE
    campaign_with_rules.reward_rule.allocation_window = 15
    db_session.commit()

    mock_convert_pr = mocker.patch("cosmos.campaigns.api.service.convert_pending_rewards_placeholder")

    payload = {
        "requested_status": "ended",
        "campaign_slug": campaign_with_rules.slug,
        "activity_metadata": {"sso_username": "Jane Doe"},
        "pending_rewards_action": pending_rewards_action,
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    assert resp.json() == {}

    def pending_reward_exists() -> bool:
        return db_session.scalar(select(PendingReward).where(PendingReward.id == pending_reward.id)) is not None

    match pending_rewards_action:  # noqa: E999
        case "remove":
            mock_convert_pr.assert_not_called()
            assert not pending_reward_exists()
        case "convert":
            # TODO: update this once carina logic is implemented
            mock_convert_pr.assert_called_once()
            assert pending_reward_exists()

    assert db_session.scalar(select(CampaignBalance).where(CampaignBalance.id == campaign_balance.id)) is None
    mock_activity.assert_called()


@pytest.mark.parametrize("pending_rewards_action", ["remove", "convert"])
def test_status_change_cancel_campaign_ok(
    pending_rewards_action: str,
    test_client: "TestClient",
    setup: SetupType,
    campaign_with_rules: "Campaign",
    campaign_balance: CampaignBalance,
    pending_reward: PendingReward,
    mock_activity: mock.MagicMock,
    user_reward: Reward,
    mocker: MockerFixture,
) -> None:
    db_session, retailer, account_holder = setup

    user_reward.cancelled_date = None
    user_reward.account_holder_id = account_holder.id
    retailer.status = RetailerStatuses.TEST
    campaign_with_rules.status = CampaignStatuses.ACTIVE
    campaign_with_rules.reward_rule.allocation_window = 15
    db_session.commit()

    mock_now = datetime.now(tz=timezone.utc)
    mock_convert_pr = mocker.patch("cosmos.campaigns.api.service.convert_pending_rewards_placeholder")
    mock_datetime = mocker.patch("cosmos.rewards.crud.datetime")
    mock_datetime.now.return_value = mock_now

    payload = {
        "requested_status": "cancelled",
        "campaign_slug": campaign_with_rules.slug,
        "activity_metadata": {"sso_username": "Jane Doe"},
        # when cancelling a campaign pending_rewards_action should be ignored and the rewards should always be deleted
        "pending_rewards_action": pending_rewards_action,
    }

    resp = test_client.post(
        f"{settings.API_PREFIX}/campaigns/{retailer.slug}/campaigns/status_change",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == fastapi_http_status.HTTP_200_OK
    assert resp.json() == {}

    mock_convert_pr.assert_not_called()
    assert db_session.scalar(select(PendingReward).where(PendingReward.id == pending_reward.id)) is None
    assert db_session.scalar(select(CampaignBalance).where(CampaignBalance.id == campaign_balance.id)) is None

    db_session.refresh(user_reward)
    assert user_reward.cancelled_date == mock_now.replace(tzinfo=None)
    mock_activity.assert_called()