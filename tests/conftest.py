from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Generator, NamedTuple
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient
from sqlalchemy_utils import create_database, database_exists, drop_database
from testfixtures import LogCapture

from cosmos.db.base import Base
from cosmos.db.models import (
    AccountHolder,
    AccountHolderProfile,
    Campaign,
    FetchType,
    Retailer,
    RetailerFetchType,
    Reward,
    RewardConfig,
)
from cosmos.db.session import SyncSessionMaker, sync_engine
from cosmos.public_api.api.app import create_app
from cosmos.rewards.enums import RewardTypeStatuses

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class SetupType(NamedTuple):
    db_session: "Session"
    retailer: Retailer
    account_holder: AccountHolder


@pytest.fixture(scope="session")
def test_client() -> TestClient:
    app = create_app()
    return TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def setup_db() -> Generator:
    if sync_engine.url.database != "cosmos_test":
        raise ValueError(f"Unsafe attempt to recreate database: {sync_engine.url.database}")

    if database_exists(sync_engine.url):
        drop_database(sync_engine.url)

    create_database(sync_engine.url)

    yield

    # At end of all tests, drop the test db
    drop_database(sync_engine.url)


@pytest.fixture(scope="function", autouse=True)
def setup_tables() -> Generator:
    """
    autouse set to True so will be run before each test function, to set up tables
    and tear them down after each test runs
    """

    Base.metadata.create_all(bind=sync_engine)

    yield

    # Drop all tables after each test
    Base.metadata.drop_all(bind=sync_engine)


@pytest.fixture(scope="session")
def main_db_session() -> Generator["Session", None, None]:
    with SyncSessionMaker() as session:
        yield session


@pytest.fixture(scope="function")
def db_session(main_db_session: "Session") -> Generator["Session", None, None]:
    yield main_db_session
    main_db_session.rollback()
    main_db_session.expunge_all()


@pytest.fixture(scope="function")
def log_capture() -> Generator:
    with LogCapture() as cpt:
        yield cpt


@pytest.fixture(scope="function")
def test_retailer() -> dict:
    return {
        "name": "Test Retailer",
        "slug": "re-test",
        "status": "TEST",
        "account_number_prefix": "RTST",
        "profile_config": (
            "email:"
            "\n  required: true"
            "\nfirst_name:"
            "\n  required: true"
            "\nlast_name:"
            "\n  required: true"
            "\ndate_of_birth:"
            "\n  required: true"
            "\nphone:"
            "\n  required: true"
            "\naddress_line1:"
            "\n  required: true"
            "\naddress_line2:"
            "\n  required: true"
            "\npostcode:"
            "\n  required: true"
            "\ncity:"
            "\n  required: true"
        ),
        "marketing_preference_config": "marketing_pref:\n  type: boolean\n  label: Sample Question?",
        "loyalty_name": "Test Retailer",
    }


@pytest.fixture(scope="function")
def retailer(db_session: "Session", test_retailer: dict) -> Retailer:
    retailer = Retailer(**test_retailer)
    db_session.add(retailer)
    db_session.commit()

    return retailer


@pytest.fixture(scope="function")
def test_account_holder_activation_data() -> dict:
    return {
        "email": "activate_1@test.user",
        "credentials": {
            "first_name": "Test User",
            "last_name": "Test 1",
            "date_of_birth": datetime.strptime("1970-12-03", "%Y-%m-%d").replace(tzinfo=timezone.utc).date(),
            "phone": "+447968100999",
            "address_line1": "Flat 3, Some Place",
            "address_line2": "Some Street",
            "postcode": "BN77CC",
            "city": "Brighton & Hove",
        },
    }


@pytest.fixture(scope="function")
def account_holder(
    db_session: "Session",
    retailer: Retailer,
    test_account_holder_activation_data: dict,
) -> AccountHolder:
    acc_holder = AccountHolder(email=test_account_holder_activation_data["email"], retailer_id=retailer.id)
    db_session.add(acc_holder)
    db_session.flush()

    profile = AccountHolderProfile(
        account_holder_id=acc_holder.id, **test_account_holder_activation_data["credentials"]
    )
    db_session.add(profile)
    db_session.commit()

    return acc_holder


@pytest.fixture(scope="function")
def setup(db_session: "Session", retailer: Retailer, account_holder: AccountHolder) -> Generator[SetupType, None, None]:
    yield SetupType(db_session, retailer, account_holder)


@pytest.fixture(scope="function")
def pre_loaded_fetch_type(db_session: "Session") -> FetchType:
    ft = FetchType(
        name="PRE_LOADED",
        required_fields="validity_days: integer",
        path="path.to.pre_loaded_agent",
    )
    db_session.add(ft)
    db_session.commit()
    return ft


@pytest.fixture(scope="function")
def jigsaw_fetch_type(db_session: "Session") -> FetchType:
    ft = FetchType(
        name="JIGSAW_EGIFT",
        path="path.to.jigsaw_agent",
        required_fields="transaction_value: integer",
    )
    db_session.add(ft)
    db_session.commit()
    return ft


@pytest.fixture(scope="function")
def reward_config(setup: SetupType, pre_loaded_fetch_type: FetchType) -> RewardConfig:
    db_session, retailer, _ = setup  # pylint: disable=redefined-outer-name
    mock_reward_config = RewardConfig(
        slug="test-reward-slug",
        required_fields_values="validity_days: 15",
        retailer_id=retailer.id,
        fetch_type_id=pre_loaded_fetch_type.id,
        status=RewardTypeStatuses.ACTIVE,
    )
    db_session.add(mock_reward_config)
    db_session.commit()
    return mock_reward_config


@pytest.fixture(scope="function")
def campaign(setup: SetupType) -> Campaign:
    db_session, retailer, _ = setup  # pylint: disable=redefined-outer-name
    mock_campaign = Campaign(
        status="ACTIVE",
        name="test campaign",
        slug="test-campaign",
        retailer_id=retailer.id,
        loyalty_type="ACCUMULATOR",
    )
    db_session.add(mock_campaign)
    db_session.commit()
    return mock_campaign


@pytest.fixture(scope="function")
def user_reward(setup: SetupType, reward_config: RewardConfig, campaign: Campaign) -> Reward:
    now = datetime.now(tz=timezone.utc)
    db_session, retailer, _ = setup  # pylint: disable=redefined-outer-name
    mock_user_reward = Reward(
        reward_uuid=uuid4(),
        code="TSTCD123456",
        reward_config_id=reward_config.id,
        retailer_id=retailer.id,
        campaign_id=campaign.id,
        deleted=False,
        issued_date=now,
        expiry_date=now + timedelta(days=10),
    )
    db_session.add(mock_user_reward)
    db_session.commit()
    return mock_user_reward


@pytest.fixture()
def create_mock_reward(db_session: "Session", reward_config: RewardConfig, campaign: Campaign) -> Callable:
    reward = {
        "reward_uuid": None,
        "reward_config_id": reward_config.id,
        "code": "test_reward_code",
        "deleted": False,
        "issued_date": datetime(2021, 6, 25, 14, 30, 00, tzinfo=timezone.utc),
        "expiry_date": datetime(2121, 6, 25, 14, 30, 00, tzinfo=timezone.utc),
        "redeemed_date": None,
        "cancelled_date": None,
        "account_holder": None,  # Pass this in as an account_holder obj
        "retailer_id": None,
        "campaign_id": campaign.id,
        "created_at": datetime.now(tz=timezone.utc),
        "updated_at": None,
    }

    def _create_mock_reward(**reward_params: dict) -> Reward:
        """
        Create a reward in the test DB
        :param reward_params: override any values for reward
        :return: Callable function
        """
        assert reward_params["account_holder"]
        reward.update(reward_params)
        mock_reward = Reward(**reward)

        db_session.add(mock_reward)
        db_session.commit()

        return mock_reward

    return _create_mock_reward


@pytest.fixture(scope="function")
def create_mock_account_holder(
    db_session: "Session",
    test_account_holder_activation_data: dict,
) -> Callable:
    def _create_mock_account_holder(
        retailer_id: int,
        **account_holder_params: dict,
    ) -> AccountHolder:
        test_account_holder_activation_data.update(account_holder_params)
        acc_holder = AccountHolder(email=test_account_holder_activation_data["email"], retailer_id=retailer_id)
        db_session.add(acc_holder)
        db_session.flush()

        profile = AccountHolderProfile(
            account_holder_id=acc_holder.id, **test_account_holder_activation_data["credentials"]
        )
        db_session.add(profile)
        db_session.commit()

        return acc_holder

    return _create_mock_account_holder


@pytest.fixture(scope="function")
def jigsaw_retailer_fetch_type(
    db_session: "Session", retailer: Retailer, jigsaw_fetch_type: FetchType
) -> RetailerFetchType:
    rft = RetailerFetchType(
        retailer_id=retailer.id,
        fetch_type_id=jigsaw_fetch_type.id,
        agent_config='base_url: "http://test.url"\n' "brand_id: 30\n" "fetch_reward: true\n" 'fetch_balance: false"',
    )
    db_session.add(rft)
    db_session.commit()
    return rft


@pytest.fixture(scope="function")
def pre_loaded_retailer_fetch_type(
    db_session: "Session", retailer: Retailer, pre_loaded_fetch_type: FetchType
) -> RetailerFetchType:
    rft = RetailerFetchType(
        retailer_id=retailer.id,
        fetch_type_id=pre_loaded_fetch_type.id,
    )
    db_session.add(rft)
    db_session.commit()
    return rft


@pytest.fixture(scope="function")
def create_reward_config(db_session: "Session", pre_loaded_retailer_fetch_type: RetailerFetchType) -> Callable:
    def _create_reward_config(**reward_config_params: Any) -> RewardConfig:
        mock_reward_config_params = {
            "slug": "test-reward",
            "required_fields_values": "validity_days: 15",
            "retailer_id": pre_loaded_retailer_fetch_type.retailer_id,
            "fetch_type_id": pre_loaded_retailer_fetch_type.fetch_type_id,
            "status": RewardTypeStatuses.ACTIVE,
        }

        mock_reward_config_params.update(reward_config_params)
        reward_config = RewardConfig(**mock_reward_config_params)
        db_session.add(reward_config)
        db_session.commit()

        return reward_config

    return _create_reward_config


@pytest.fixture(scope="function")
def reward(db_session: "Session", reward_config: RewardConfig) -> Reward:
    rc = Reward(
        code="TSTCD1234",
        retailer_id=reward_config.retailer_id,
        reward_config=reward_config,
    )
    db_session.add(rc)
    db_session.commit()
    return rc