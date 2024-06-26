from collections.abc import AsyncGenerator, Callable, Generator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple
from uuid import uuid4

import pytest
import pytest_asyncio
import yaml

from psycopg import OperationalError, ProgrammingError
from pytest_mock import MockerFixture
from retry_tasks_lib.db.models import TaskType, TaskTypeKey
from sqlalchemy import URL, Engine, TextClause, create_engine, make_url, text
from testfixtures import LogCapture

from cosmos.accounts.config import account_settings
from cosmos.accounts.enums import AccountHolderStatuses
from cosmos.campaigns.enums import LoyaltyTypes
from cosmos.core.api.service import Service
from cosmos.core.config import redis
from cosmos.db.base import Base
from cosmos.db.models import (
    AccountHolder,
    AccountHolderProfile,
    Campaign,
    CampaignBalance,
    EarnRule,
    EmailTemplate,
    EmailType,
    FetchType,
    PendingReward,
    Retailer,
    RetailerFetchType,
    RetailerStore,
    Reward,
    RewardConfig,
    RewardRule,
    Transaction,
    TransactionEarn,
)
from cosmos.db.session import AsyncSessionMaker, SyncSessionMaker, sync_engine
from cosmos.retailers.enums import RetailerStatuses
from cosmos.rewards.config import reward_settings

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session


def get_postgres_db_url_from_db_url(db_url: str | URL) -> URL:
    return make_url(db_url)._replace(database="postgres")


def _get_scalar_result(engine: Engine, sql: TextClause) -> Any:  # noqa: ANN401
    with engine.connect() as conn:
        return conn.scalar(sql)


def database_exists(url: str | URL) -> bool:
    url = make_url(url)
    database = url.database
    if not database:
        raise ValueError("No database found in URL")
    postgres_url = get_postgres_db_url_from_db_url(url)
    engine = create_engine(postgres_url)
    dialect = engine.dialect
    quoted_database = dialect.preparer(dialect).quote(database)
    try:
        return bool(
            _get_scalar_result(
                engine,
                text("SELECT 1 FROM pg_database WHERE datname = :quoted_database").bindparams(
                    quoted_database=quoted_database
                ),
            )
        )
    except (ProgrammingError, OperationalError):
        return False
    finally:
        if engine:
            engine.dispose()


def drop_database(url: str | URL) -> None:
    url = make_url(url)
    database = url.database
    if not database:
        raise ValueError("No database found in URL")
    postgres_url = get_postgres_db_url_from_db_url(url)
    engine = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    dialect = engine.dialect
    quoted_database = dialect.preparer(dialect).quote(database)
    with engine.begin() as conn:
        # Disconnect all users from the database we are dropping.
        stmt = """
        SELECT pg_terminate_backend(pg_stat_activity.pid)
        FROM pg_stat_activity
        WHERE pg_stat_activity.datname = :quoted_database
        AND pid <> pg_backend_pid();
        """
        conn.execute(text(stmt).bindparams(quoted_database=quoted_database))
        # Drop the database.
        stmt = f"DROP DATABASE {quoted_database}"
        conn.execute(text(stmt))


def create_database(url: str | URL) -> None:
    url = make_url(url)
    database = url.database
    if not database:
        raise ValueError("No database found in URL")
    postgres_url = get_postgres_db_url_from_db_url(url)
    engine = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    dialect = engine.dialect
    quoter = dialect.preparer(dialect)
    with engine.begin() as conn:
        stmt = f"CREATE DATABASE {quoter.quote(database)} ENCODING 'utf8' TEMPLATE template1"
        conn.execute(text(stmt))


class SetupType(NamedTuple):
    db_session: "Session"
    retailer: Retailer
    account_holder: AccountHolder


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


@pytest_asyncio.fixture(scope="function", name="async_db_session")
async def async_session() -> AsyncGenerator["AsyncSession", None]:
    async with AsyncSessionMaker() as db_session:
        yield db_session


@pytest.fixture(scope="session", autouse=True)
def setup_redis() -> Generator:
    yield

    # At end of all tests, delete the tasks from the queue
    redis.flushdb()


@pytest.fixture(scope="function")
def mock_activity(mocker: MockerFixture) -> "MagicMock":
    return mocker.patch.object(Service, "_format_and_send_activity_in_background")


@pytest.fixture(scope="function")
def log_capture() -> Generator:
    with LogCapture() as cpt:
        yield cpt


@pytest.fixture(scope="function")
def test_retailer() -> dict:
    return {
        "name": "Test Retailer",
        "slug": "re-test",
        "status": RetailerStatuses.TEST,
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
def create_retailer(
    db_session: "Session",
    test_retailer: dict,
) -> Callable[..., Retailer]:
    def _create_retailer(**params: str | int) -> Retailer:
        test_retailer.update(params)
        retailer = Retailer(**test_retailer)
        db_session.add(retailer)
        db_session.commit()

        return retailer

    return _create_retailer


@pytest.fixture(scope="function")
def test_account_holder_activation_data() -> dict:
    return {
        "email": "activate_1@test.user",
        "credentials": {
            "first_name": "Test User",
            "last_name": "Test 1",
            "date_of_birth": datetime.strptime("1970-12-03", "%Y-%m-%d").replace(tzinfo=UTC).date(),
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
    acc_holder = AccountHolder(
        email=test_account_holder_activation_data["email"],
        account_number=None,
        retailer_id=retailer.id,
        status=AccountHolderStatuses.PENDING,
    )
    db_session.add(acc_holder)
    db_session.flush()
    acc_holder.created_at -= timedelta(days=10)

    profile = AccountHolderProfile(
        account_holder_id=acc_holder.id, **test_account_holder_activation_data["credentials"]
    )
    db_session.add(profile)
    db_session.commit()

    return acc_holder


@pytest.fixture(scope="function")
def create_account_holder(
    db_session: "Session", retailer: Retailer, test_account_holder_activation_data: dict
) -> Callable[..., AccountHolder]:
    data = {
        "email": test_account_holder_activation_data["email"],
        "retailer_id": retailer.id,
        "status": "ACTIVE",
    }

    def _create_account_holder(**params: str | int) -> AccountHolder:
        data.update(params)
        acc_holder = AccountHolder(**data)
        db_session.add(acc_holder)
        db_session.flush()

        profile = AccountHolderProfile(
            account_holder_id=acc_holder.id, **test_account_holder_activation_data["credentials"]
        )
        db_session.add(profile)
        db_session.commit()

        return acc_holder

    return _create_account_holder


@pytest.fixture(scope="function")
def setup(db_session: "Session", retailer: Retailer, account_holder: AccountHolder) -> Generator[SetupType, None, None]:
    yield SetupType(db_session, retailer, account_holder)


@pytest.fixture(scope="function")
def pre_loaded_fetch_type(db_session: "Session") -> FetchType:
    ft = FetchType(
        name="PRE_LOADED",
        required_fields="validity_days: integer",
        path="cosmos.rewards.fetch_reward.pre_loaded.PreLoaded",
    )
    db_session.add(ft)
    db_session.commit()
    return ft


@pytest.fixture(scope="function")
def jigsaw_fetch_type(db_session: "Session") -> FetchType:
    ft = FetchType(
        name="JIGSAW_EGIFT",
        path="cosmos.rewards.fetch_reward.jigsaw.Jigsaw",
        required_fields="transaction_value: integer",
    )
    db_session.add(ft)
    db_session.commit()
    return ft


@pytest.fixture(scope="function")
def reward_config(setup: SetupType, pre_loaded_fetch_type: FetchType) -> RewardConfig:
    db_session, retailer, _ = setup
    mock_reward_config = RewardConfig(
        slug="test-reward-slug",
        required_fields_values="validity_days: 15",
        retailer_id=retailer.id,
        fetch_type_id=pre_loaded_fetch_type.id,
        active=True,
    )
    db_session.add(mock_reward_config)
    db_session.commit()
    return mock_reward_config


@pytest.fixture()
def mock_campaign_balance_data() -> list[dict]:
    return [
        {"value": 0.0, "campaign_slug": "test-campaign"},
    ]


@pytest.fixture(scope="function")
def campaigns(setup: SetupType, mock_campaign_balance_data: dict) -> list[Campaign]:
    db_session, retailer, _ = setup
    campaigns = []
    for balance_data in mock_campaign_balance_data:
        mock_campaign = Campaign(
            status="ACTIVE",
            name=balance_data["campaign_slug"],
            slug=balance_data["campaign_slug"],
            retailer_id=retailer.id,
            loyalty_type="ACCUMULATOR",
        )
        db_session.add(mock_campaign)
        campaigns.append(mock_campaign)
    db_session.commit()
    return campaigns


@pytest.fixture(scope="function")
def campaign(campaigns: list[Campaign]) -> Campaign:
    return campaigns[0]


@pytest.fixture(scope="function")
def create_campaign(setup: SetupType, reward_config: RewardConfig) -> Callable[..., Campaign]:
    db_session, retailer, _ = setup
    data = {
        "status": "ACTIVE",
        "name": "test campaign",
        "slug": "test-campaign",
        "retailer_id": retailer.id,
        "loyalty_type": "ACCUMULATOR",
    }

    def _create_campaign(**params: Any) -> Campaign:  # noqa: ANN401
        """
        Create a campaign in the test DB
        :param params: override any values for campaign
        :return: Campaign
        """
        data.update(params)
        new_campaign = Campaign(**data)

        db_session.add(new_campaign)
        db_session.flush()
        db_session.add(
            RewardRule(
                reward_goal=500,
                campaign_id=new_campaign.id,
                reward_config_id=reward_config.id,
            )
        )
        db_session.add(
            EarnRule(
                threshold=100,
                increment=1,
                campaign_id=new_campaign.id,
            )
        )
        db_session.commit()
        db_session.refresh(new_campaign)

        return new_campaign

    return _create_campaign


@pytest.fixture(scope="function")
def campaign_with_rules(setup: SetupType, campaign: Campaign, reward_config: RewardConfig) -> Campaign:
    db_session = setup.db_session
    campaign.start_date = datetime.now(UTC) - timedelta(days=20)
    db_session.add(
        RewardRule(
            reward_goal=500,
            campaign_id=campaign.id,
            reward_config_id=reward_config.id,
        )
    )
    db_session.add(
        EarnRule(
            threshold=100,
            increment=1,
            campaign_id=campaign.id,
        )
    )
    db_session.commit()
    db_session.refresh(campaign)
    return campaign


@pytest.fixture(scope="function")
def account_holder_campaign_balances(setup: SetupType, campaigns: list[Campaign]) -> None:
    db_session, _, account_holder = setup
    for campaign in campaigns:
        db_session.add(
            CampaignBalance(
                account_holder_id=account_holder.id,
                campaign_id=campaign.id,
                balance=0,
            )
        )
    db_session.commit()


@pytest.fixture(scope="function")
def user_reward(setup: SetupType, reward_config: RewardConfig, campaign: Campaign) -> Reward:
    now = datetime.now(tz=UTC)
    db_session, retailer, _ = setup
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


@pytest.fixture(scope="function")
def create_mock_reward(db_session: "Session", reward_config: RewardConfig, campaign: Campaign) -> Callable:
    reward = {
        "reward_uuid": None,
        "account_holder_id": None,
        "reward_config_id": reward_config.id,
        "code": "test_reward_code",
        "deleted": False,
        "issued_date": datetime(2021, 6, 25, 14, 30, 00, tzinfo=UTC),
        "expiry_date": datetime(2121, 6, 25, 14, 30, 00, tzinfo=UTC),
        "redeemed_date": None,
        "cancelled_date": None,
        "retailer_id": None,
        "campaign_id": None,
        "created_at": datetime.now(tz=UTC),
        "updated_at": None,
    }

    def _create_mock_reward(**reward_params: Any) -> Reward:  # noqa: ANN401
        """
        Create a reward in the test DB
        :param reward_params: override any values for reward
        :return: Callable function
        """
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
    def _create_reward_config(**reward_config_params: Any) -> RewardConfig:  # noqa: ANN401
        mock_reward_config_params = {
            "slug": "test-reward",
            "required_fields_values": "validity_days: 15",
            "retailer_id": pre_loaded_retailer_fetch_type.retailer_id,
            "fetch_type_id": pre_loaded_retailer_fetch_type.fetch_type_id,
            "active": True,
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


@pytest.fixture(scope="function")
def create_mock_retailer(db_session: "Session", test_retailer: dict) -> Callable[..., Retailer]:
    def _create_mock_retailer(**retailer_params: Any) -> Retailer:  # noqa: ANN401
        """
        Create a retailer in the test DB
        :param retailer_params: override any values for the retailer, from what the mock_retailer fixture provides
        :return: Callable function
        """
        mock_retailer_params = deepcopy(test_retailer)

        mock_retailer_params.update(retailer_params)
        rtl = Retailer(**mock_retailer_params)
        db_session.add(rtl)
        db_session.commit()

        return rtl

    return _create_mock_retailer


@pytest.fixture(scope="function")
def campaign_balance(setup: SetupType, campaign: Campaign) -> CampaignBalance:
    db_session, _, account_holder = setup
    cmp_bal = CampaignBalance(
        account_holder_id=account_holder.id,
        campaign_id=campaign.id,
        balance=300,
    )
    db_session.add(cmp_bal)
    db_session.commit()
    return cmp_bal


@pytest.fixture(scope="function")
def create_balance(setup: SetupType, campaign: Campaign) -> Callable[..., CampaignBalance]:
    db_session, _, account_holder = setup
    data = {
        "account_holder_id": account_holder.id,
        "campaign_id": campaign.id,
        "balance": 300,
    }

    def _create_balance(**params: Any) -> CampaignBalance:  # noqa: ANN401
        data.update(params)
        cmp_bal = CampaignBalance(**data)
        db_session.add(cmp_bal)
        db_session.commit()
        return cmp_bal

    return _create_balance


@pytest.fixture(scope="function")
def pending_reward(setup: SetupType, campaign: Campaign) -> PendingReward:
    db_session, _, account_holder = setup
    pending_rwd = PendingReward(
        account_holder_id=account_holder.id,
        campaign_id=campaign.id,
        pending_reward_uuid=uuid4(),
        created_date=datetime(2022, 1, 1, 5, 0, tzinfo=UTC),
        conversion_date=datetime.now(tz=UTC) + timedelta(days=15),
        value=100,
        count=2,
        total_cost_to_user=300,
    )
    db_session.add(pending_rwd)
    db_session.commit()
    return pending_rwd


@pytest.fixture(scope="function")
def create_pending_reward(setup: SetupType, campaign: Campaign) -> Callable[..., PendingReward]:
    db_session, _, account_holder = setup
    data = {
        "account_holder_id": account_holder.id,
        "campaign_id": campaign.id,
        "pending_reward_uuid": uuid4(),
        "created_date": datetime(2022, 1, 1, 5, 0, tzinfo=UTC),
        "conversion_date": datetime.now(tz=UTC) + timedelta(days=15),
        "value": 100,
        "count": 2,
        "total_cost_to_user": 300,
    }

    def _create_pending_reward(**params: Any) -> PendingReward:  # noqa: ANN401
        data.update(params)
        pending_reward = PendingReward(**data)
        db_session.add(pending_reward)
        db_session.commit()

        return pending_reward

    return _create_pending_reward


@pytest.fixture(scope="function")
def create_mock_campaign(db_session: "Session", retailer: Retailer, mock_campaign: dict) -> Callable[..., Campaign]:
    def _create_mock_campaign(**campaign_params: dict) -> Campaign:
        """
        Create a campaign in the test DB
        :param campaign_params: override any values for the campaign, from what the mock_campaign fixture provides
        :return: Callable function
        """
        mock_campaign_params = deepcopy(mock_campaign)
        mock_campaign_params["retailer_id"] = retailer.id

        mock_campaign_params.update(campaign_params)
        cpn = Campaign(**mock_campaign_params)
        db_session.add(cpn)
        db_session.commit()

        return cpn

    return _create_mock_campaign


@pytest.fixture
def create_retailer_store(db_session: "Session") -> Callable:
    def _create_retailer_store(retailer_id: int, mid: str, store_name: str) -> RetailerStore:
        store = RetailerStore(retailer_id=retailer_id, mid=mid, store_name=store_name)
        db_session.add(store)
        db_session.commit()
        return store

    return _create_retailer_store


@pytest.fixture()
def create_transaction(db_session: "Session") -> Callable:
    def _create_transaction(account_holder: AccountHolder, **transaction_params: dict) -> Transaction:
        """
        :param transaction_params: transaction object values
        :return: Callable function
        """
        assert transaction_params["transaction_id"]
        transaction_data = {
            "account_holder_id": account_holder.id,
            "retailer_id": account_holder.retailer_id,
            "datetime": transaction_params.get("datetime", datetime(2022, 6, 1, 14, 30, 00, tzinfo=UTC)),
            "transaction_id": transaction_params["transaction_id"],
            "amount": 1000,
            "processed": True,
        }
        transaction_data.update(transaction_params)
        transaction = Transaction(**transaction_data)
        db_session.add(transaction)
        db_session.commit()

        return transaction

    return _create_transaction


@pytest.fixture
def create_transaction_earn(db_session: "Session") -> Callable:
    def _create_transaction_earn(
        transaction: Transaction, earn_amount: str, loyalty_type: LoyaltyTypes
    ) -> TransactionEarn:
        te = TransactionEarn(transaction_id=transaction.id, earn_amount=earn_amount, loyalty_type=loyalty_type)
        db_session.add(te)
        db_session.commit()
        return te

    return _create_transaction_earn


@pytest.fixture(scope="function")
def reward_issuance_task_type(db_session: "Session") -> TaskType:
    tt = TaskType(
        name=reward_settings.REWARD_ISSUANCE_TASK_NAME,
        path="cosmos.rewards.tasks.issuance.issue_reward",
        error_handler_path="cosmos.core.tasks.error_handlers.default_handler",
        queue_name="cosmos:default",
    )
    db_session.add(tt)
    db_session.flush()
    db_session.bulk_save_objects(
        [
            TaskTypeKey(task_type_id=tt.task_type_id, name=key_name, type=key_type)
            for key_name, key_type in (
                ("campaign_id", "INTEGER"),
                ("account_holder_id", "INTEGER"),
                ("reward_config_id", "INTEGER"),
                ("pending_reward_uuid", "STRING"),
                ("reason", "STRING"),
                ("agent_state_params_raw", "STRING"),
            )
        ]
    )
    db_session.commit()
    return tt


@pytest.fixture(scope="function")
def send_email_task_type(db_session: "Session") -> TaskType:
    task_type = TaskType(
        name=reward_settings.core.SEND_EMAIL_TASK_NAME,
        path="path.to.func",
        error_handler_path="path.to.error_handler",
        queue_name="queue-name",
    )
    db_session.add(task_type)
    db_session.flush()
    db_session.add_all(
        [
            TaskTypeKey(task_type_id=task_type.task_type_id, name=key_name, type=key_type)
            for key_name, key_type in (
                ("retailer_id", "INTEGER"),
                ("template_type", "STRING"),
                ("account_holder_id", "INTEGER"),
                ("extra_params", "JSON"),
            )
        ]
    )

    db_session.commit()
    return task_type


@pytest.fixture(scope="function")
def balance_reset_email_type(db_session: "Session") -> EmailType:
    email_type = EmailType(
        slug="BALANCE_RESET",
        send_email_params_fn="cosmos.accounts.send_email_params_gen.get_balance_reset_nudge_params",
    )
    db_session.add(email_type)
    db_session.commit()
    return email_type


@pytest.fixture(scope="function")
def balance_reset_email_template(setup: SetupType, balance_reset_email_type: EmailType) -> EmailTemplate:
    db_session, retailer, _ = setup

    template = EmailTemplate(
        template_id="12345",
        email_type_id=balance_reset_email_type.id,
        retailer_id=retailer.id,
    )
    db_session.add(template)
    db_session.commit()
    return template


@pytest.fixture(scope="function")
def purchase_prompt_email_type(db_session: "Session") -> EmailType:
    email_type = EmailType(
        slug="PURCHASE_PROMPT",
        send_email_params_fn="cosmos.accounts.send_email_params_gen.get_purchase_prompt_params",
        required_fields=yaml.safe_dump({"purchase_prompt_days": "integer"}),
    )
    db_session.add(email_type)
    db_session.commit()
    return email_type


@pytest.fixture(scope="function")
def purchase_prompt_email_template(setup: SetupType, purchase_prompt_email_type: EmailType) -> EmailTemplate:
    db_session, retailer, _ = setup

    template = EmailTemplate(
        template_id="54321",
        email_type_id=purchase_prompt_email_type.id,
        retailer_id=retailer.id,
        required_fields_values=yaml.safe_dump({"purchase_prompt_days": 10}),
    )
    db_session.add(template)
    db_session.commit()
    return template


@pytest.fixture(scope="function")
def account_holder_activation_task_type(db_session: "Session") -> TaskType:
    task_type = TaskType(
        name=account_settings.ACCOUNT_HOLDER_ACTIVATION_TASK_NAME,
        path="path.to.func",
        error_handler_path="path.to.error_handler",
        queue_name="queue-name",
    )
    db_session.add(task_type)
    db_session.flush()

    db_session.add_all(
        [
            TaskTypeKey(task_type_id=task_type.task_type_id, name=key_name, type=key_type)
            for key_name, key_type in (
                ("account_holder_id", "INTEGER"),
                ("callback_retry_task_id", "INTEGER"),
                ("welcome_email_retry_task_id", "INTEGER"),
                ("channel", "STRING"),
                ("third_party_identifier", "STRING"),
            )
        ]
    )

    db_session.commit()
    return task_type
