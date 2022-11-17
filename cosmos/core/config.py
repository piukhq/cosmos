import logging
import os
import sys

from logging.config import dictConfig
from typing import TYPE_CHECKING, Any, Literal

import sentry_sdk

from pydantic import BaseSettings, HttpUrl, PostgresDsn, validator
from pydantic.validators import str_validator
from redis import Redis
from retry_tasks_lib.settings import load_settings
from sentry_sdk.integrations.redis import RedisIntegration
from sentry_sdk.integrations.rq import RqIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from cosmos.core.key_vault import KeyVault
from cosmos.version import __version__

if TYPE_CHECKING:  # pragma: no cover
    from pydantic.typing import CallableGenerator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LogLevel(str):
    @classmethod
    def __modify_schema__(cls, field_schema: dict[str, Any]) -> None:
        field_schema.update(type="string", format="log_level")

    @classmethod
    def __get_validators__(cls) -> "CallableGenerator":
        yield str_validator
        yield cls.validate

    @classmethod
    def validate(cls, value: str) -> str:
        v = value.upper()
        if v not in ["CRITICAL", "FATAL", "ERROR", "WARN", "WARNING", "INFO", "DEBUG", "NOTSET"]:
            raise ValueError(f"{value} is not a valid LOG_LEVEL value")
        return v


class Settings(BaseSettings):
    API_PREFIX: str = "/loyalty"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    TESTING: bool = False
    SQL_DEBUG: bool = False

    @validator("TESTING")
    @classmethod
    def is_test(cls, v: bool) -> bool:
        command = sys.argv[0]
        args = sys.argv[1:] if len(sys.argv) > 1 else []

        if "pytest" in command or any("test" in arg for arg in args):
            return True
        return v

    MIGRATING: bool = False

    @validator("MIGRATING")
    @classmethod
    def is_migration(cls, v: bool) -> bool:
        command = sys.argv[0]

        if "alembic" in command:
            return True
        return v

    PROJECT_NAME: str = "cosmos"
    ROOT_LOG_LEVEL: LogLevel | None = None
    QUERY_LOG_LEVEL: LogLevel | None = None
    PROMETHEUS_LOG_LEVEL: LogLevel | None = None
    LOG_FORMATTER: Literal["json", "brief", "console"] = "json"

    @validator("LOG_FORMATTER")
    @classmethod
    def validate_formatter(cls, v: str) -> str | None:
        if v not in ["json", "brief", "detailed"]:
            raise ValueError(f'"{v}" is not a valid LOG_FORMATTER value, choices are [json, brief, detailed]')
        return v

    SENTRY_DSN: HttpUrl | None = None
    SENTRY_ENV: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    @validator("SENTRY_DSN", pre=True)
    @classmethod
    def sentry_dsn_can_be_blank(cls, v: str) -> str | None:
        if v is not None and len(v) == 0:
            return None
        return v

    @validator("SENTRY_TRACES_SAMPLE_RATE")
    @classmethod
    def validate_sentry_traces_sample_rate(cls, v: float) -> float:
        if not 0 <= v <= 1:
            raise ValueError("SENTRY_TRACES_SAMPLE_RATE must be between 0.0 and 1.0")
        return v

    USE_NULL_POOL: bool = False
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "cosmos"
    SQLALCHEMY_DATABASE_URI: str = ""
    SQLALCHEMY_DATABASE_URI_ASYNC: str = ""
    DB_CONNECTION_RETRY_TIMES: int = 3

    @validator("SQLALCHEMY_DATABASE_URI", pre=True)
    @classmethod
    def assemble_db_connection(cls, v: str, values: dict[str, Any]) -> Any:
        if v != "":
            db_uri = v.format(values["POSTGRES_DB"])
        else:
            db_uri = PostgresDsn.build(
                scheme="postgresql",
                user=values.get("POSTGRES_USER"),
                password=values.get("POSTGRES_PASSWORD"),
                host=values.get("POSTGRES_HOST"),
                port=values.get("POSTGRES_PORT"),
                path="/" + values.get("POSTGRES_DB", ""),
            )

        if values["TESTING"]:
            db_uri += "_test"

        return db_uri

    @validator("SQLALCHEMY_DATABASE_URI_ASYNC", pre=True)
    @classmethod
    def adapt_db_connection_to_async(cls, v: str, values: dict[str, Any]) -> Any:
        if v != "":
            db_uri = v.format(values["POSTGRES_DB"])
        else:
            db_uri = (
                values["SQLALCHEMY_DATABASE_URI"]
                .replace("postgresql://", "postgresql+asyncpg://")
                .replace("sslmode=", "ssl=")
            )
        return db_uri

    JWT_ALGORITHM: str = "HS512"
    KEY_VAULT_URI: str = "https://bink-uksouth-dev-com.vault.azure.net/"

    HTTP_REQUEST_RETRY_TIMES: int = 3

    CALLBACK_OAUTH2_RESOURCE: str = "api://midas-nonprod"
    USE_CALLBACK_OAUTH2: bool = True
    AZURE_OAUTH2_TOKEN_URL: str = "http://169.254.169.254"

    REDIS_URL: str

    @validator("REDIS_URL")
    @classmethod
    def assemble_redis_url(cls, v: str, values: dict[str, Any]) -> str:
        if values["TESTING"]:
            base_url, db_n = v.rsplit("/", 1)
            return f"{base_url}/{int(db_n) + 1}"
        return v

    REDIS_KEY_PREFIX: str = "polaris:"

    ACCOUNT_HOLDER_ACTIVATION_TASK_NAME: str = "account-holder-activation"
    ENROLMENT_CALLBACK_TASK_NAME: str = "enrolment-callback"
    SEND_EMAIL_TASK_NAME: str = "send-email"
    SEND_EMAIL_TASK_RETRY_BACKOFF_BASE: float = 1
    CREATE_CAMPAIGN_BALANCES_TASK_NAME: str = "create-campaign-balances"
    DELETE_CAMPAIGN_BALANCES_TASK_NAME: str = "delete-campaign-balances"
    PENDING_ACCOUNTS_ACTIVATION_TASK_NAME: str = "pending-accounts-activation"
    CANCEL_REWARDS_TASK_NAME: str = "cancel-rewards"
    PROCESS_PENDING_REWARD_TASK_NAME: str = "pending-reward-allocation"
    CONVERT_PENDING_REWARDS_TASK_NAME: str = "convert-pending-rewards"
    DELETE_PENDING_REWARDS_TASK_NAME: str = "delete-pending-rewards"
    ANONYMISE_ACCOUNT_HOLDER_TASK_NAME: str = "anonymise-account-holder"
    TASK_QUEUE_PREFIX: str = "cosmos:"
    TASK_QUEUES: list[str] | None = None
    PENDING_REWARDS_SCHEDULE: str = "0 2 * * *"
    REPORT_ANOMALOUS_TASKS_SCHEDULE: str = "*/10 * * * *"
    REPORT_TASKS_SUMMARY_SCHEDULE: str = "5,20,35,50 */1 * * *"
    REPORT_JOB_QUEUE_LENGTH_SCHEDULE: str = "*/10 * * * *"

    @validator("TASK_QUEUES")
    @classmethod
    def task_queues(cls, v: list[str] | None, values: dict[str, Any]) -> list[str]:
        if v and isinstance(v, list):
            return v
        return [values["TASK_QUEUE_PREFIX"] + name for name in ("high", "default", "low")]

    TASK_MAX_RETRIES: int = 6
    TASK_RETRY_BACKOFF_BASE: float = 3
    PROMETHEUS_HTTP_SERVER_PORT: int = 9100
    SEND_EMAIL: bool = False
    MAILJET_API_URL: str | None = "https://api.mailjet.com/v3.1/send"  # Set in the env
    MAILJET_API_PUBLIC_KEY: str = ""
    MAILJET_API_SECRET_KEY: str | None = None

    @validator("MAILJET_API_PUBLIC_KEY")
    @classmethod
    def fetch_mailjet_api_public_key(cls, v: str | None, values: dict[str, Any]) -> Any:
        if v and isinstance(v, str):
            return v

        if "KEY_VAULT_URI" in values:
            return KeyVault(
                values["KEY_VAULT_URI"],
                values["TESTING"] or values["MIGRATING"],
            ).get_secret("bpl-mailjet-api-public-key")
        raise KeyError("required var KEY_VAULT_URI is not set.")

    @validator("MAILJET_API_SECRET_KEY")
    @classmethod
    def fetch_mailjet_api_secret_key(cls, v: str | None, values: dict[str, Any]) -> Any:
        if v and isinstance(v, str):
            return v

        if "KEY_VAULT_URI" in values:
            return KeyVault(
                values["KEY_VAULT_URI"],
                values["TESTING"] or values["MIGRATING"],
            ).get_secret("bpl-mailjet-api-secret-key")
        raise KeyError("required var KEY_VAULT_URI is not set.")

    ACTIVATE_TASKS_METRICS: bool = True  # pylint: disable=invalid-name

    RABBITMQ_DSN: str = "amqp://guest:guest@localhost:5672//"
    MESSAGE_EXCHANGE_NAME: str = "hubble-activities"
    TX_HISTORY_ROUTING_KEY: str = "activity.vela.tx.processed"
    MESSAGE_QUEUE_NAME: str = "polaris-transaction-history"

    class Config:
        case_sensitive = True
        # env var settings priority ie priority 1 will override priority 2:
        # 1 - env vars already loaded (ie the one passed in by kubernetes)
        # 2 - env vars read from *local.env file
        # 3 - values assigned directly in the Settings class
        env_file = os.path.join(BASE_DIR, "local.env")
        env_file_encoding = "utf-8"


settings = Settings()
load_settings(settings)

dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "brief": {"format": "%(levelname)s:     %(asctime)s - %(message)s"},
            "console": {"()": "cosmos.core.reporting.ConsoleFormatter"},
            "detailed": {"()": "cosmos.core.reporting.ConsoleFormatter"},
            "json": {"()": "cosmos.core.reporting.JSONFormatter"},
        },
        "handlers": {
            "stderr": {
                "level": logging.NOTSET,
                "class": "logging.StreamHandler",
                "stream": sys.stderr,
                "formatter": settings.LOG_FORMATTER,
            },
            "stdout": {
                "level": logging.NOTSET,
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": settings.LOG_FORMATTER,
            },
        },
        "loggers": {
            "root": {
                "level": settings.ROOT_LOG_LEVEL or logging.INFO,
                "handlers": ["stdout"],
            },
            "prometheus": {
                "propagate": False,
                "level": settings.PROMETHEUS_LOG_LEVEL or logging.INFO,
                "handlers": ["stderr"],
            },
            "uvicorn": {
                "propagate": False,
                "handlers": ["stdout"],
            },
            "enrol-callback": {
                "propagate": False,
                "handlers": ["stdout"],
            },
            "sqlalchemy.engine": {
                "level": settings.QUERY_LOG_LEVEL or logging.WARN,
            },
            "alembic": {
                "level": "INFO",
                "handlers": ["stderr"],
                "propagate": False,
            },
        },
    }
)

# this will decode responses:
# >>> redis.set('test', 'hello')
# True
# >>> redis.get('test')
# 'hello'
redis = Redis.from_url(
    settings.REDIS_URL,
    socket_connect_timeout=3,
    socket_keepalive=True,
    retry_on_timeout=False,
    decode_responses=True,
)

# used for RQ:
# this will not decode responses:
# >>> redis.set('test', 'hello')
# True
# >>> redis.get('test')
# b'hello'
redis_raw = Redis.from_url(
    settings.REDIS_URL,
    socket_connect_timeout=3,
    socket_keepalive=True,
    retry_on_timeout=False,
)

if settings.SENTRY_DSN:  # pragma: no cover
    sentry_sdk.init(  # pylint: disable=abstract-class-instantiated
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENV,
        integrations=[
            RedisIntegration(),
            RqIntegration(),
            SqlalchemyIntegration(),
        ],
        release=__version__,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
    )
