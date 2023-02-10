from typing import Literal

from pydantic import BaseSettings, validator

from cosmos.core.config import CoreSettings, core_settings
from cosmos.core.key_vault import key_vault


class AdminSettings(BaseSettings):
    core: CoreSettings = core_settings

    ADMIN_PROJECT_NAME: str = "cosmos-admin"
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
        return v or key_vault.get_secret("bpl-event-horizon-secret-key")

    ## AAD SSO
    OAUTH_REDIRECT_URI: str | None = None
    AZURE_TENANT_ID: str = "a6e2367a-92ea-4e5a-b565-723830bcc095"
    OAUTH_SERVER_METADATA_URL: str = (
        f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/v2.0/.well-known/openid-configuration"
    )
    EVENT_HORIZON_CLIENT_ID: str = ""
    EVENT_HORIZON_CLIENT_SECRET: str = ""

    @validator("EVENT_HORIZON_CLIENT_SECRET")
    @classmethod
    def fetch_admin_client_secret(cls, v: str | None) -> str:
        return v or key_vault.get_secret("bpl-event-horizon-sso-client-secret")

    class Config:
        case_sensitive = True
        env_file = "local.env"
        env_file_encoding = "utf-8"


admin_settings = AdminSettings()
