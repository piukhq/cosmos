from urllib.parse import urlparse

from pydantic import BaseSettings, validator

from cosmos.core.config import CoreSettings, core_settings
from cosmos.core.key_vault import key_vault


class AdminSettings(BaseSettings):
    core: CoreSettings = core_settings

    ENV_NAME: str = ""

    @validator("ENV_NAME", always=True, pre=False)
    @classmethod
    def parse_env_name(cls, v: str, values: dict) -> str:
        if v:
            return v

        sentry_env: str | None = values["core"].SENTRY_ENV
        match (env := sentry_env.lower() if sentry_env else "N/A"):
            case "local" | "develop" | "staging" | "sandbox":
                return env
            case "production" | "prod":
                return "production"

        return "unknown"

    ADMIN_ROUTE_BASE: str = "/admin"
    FLASK_ADMIN_SWATCH: str = "simplex"
    FLASK_DEBUG: bool = False
    ADMIN_QUERY_LOG_LEVEL: str | int = "WARN"
    FLASK_DEV_PORT: int = 5000
    SECRET_KEY: str = ""
    REQUEST_TIMEOUT: int = 2
    ACTIVITY_DB: str = "hubble"
    ACTIVITY_MENU_PREFIX: str = "hubble"

    @validator("SECRET_KEY", always=True, pre=False)
    @classmethod
    def fetch_admin_secret_key(cls, v: str) -> str:
        return v or key_vault.get_secret("bpl-cosmos-admin-secret-key")

    ## AAD SSO
    OAUTH_REDIRECT_URI: str | None = None
    AZURE_TENANT_ID: str = "a6e2367a-92ea-4e5a-b565-723830bcc095"
    OAUTH_SERVER_METADATA_URL: str = (
        f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/v2.0/.well-known/openid-configuration"
    )
    COSMOS_ADMIN_CLIENT_ID: str = ""
    COSMOS_ADMIN_CLIENT_SECRET: str = ""

    @validator("COSMOS_ADMIN_CLIENT_SECRET")
    @classmethod
    def fetch_admin_client_secret(cls, v: str | None) -> str:
        return v or key_vault.get_secret("bpl-cosmos-admin-sso-client-secret")

    ACTIVITY_SQLALCHEMY_URI: str = ""

    @validator("ACTIVITY_SQLALCHEMY_URI", always=True, pre=False)
    @classmethod
    def format_activity_db_uri(cls, v: str, values: dict) -> str:
        return (
            v or urlparse(values["core"].db.SQLALCHEMY_DATABASE_URI)._replace(path=f'/{values["ACTIVITY_DB"]}').geturl()
        )

    ANONYMISE_ACTIVITIES_TASK_NAME: str = "anonymise-activities"

    BPL_USER_NAMES: list[str] = [
        "Alyson",
        "Jess",
        "Francesco",
        "Haffi",
        "Lewis",
        "Stewart",
        "Susanne",
        "Rupal",
        "Bhasker",
    ]

    class Config:
        case_sensitive = True
        env_file = "local.env"
        env_file_encoding = "utf-8"


admin_settings = AdminSettings()
