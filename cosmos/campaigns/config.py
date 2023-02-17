from pydantic import BaseSettings, validator

from cosmos.core.config import CoreSettings, core_settings
from cosmos.core.key_vault import key_vault


class CampaignSettings(BaseSettings):
    core: CoreSettings = core_settings
    CAMPAIGN_API_PREFIX: str = f"{core.API_PREFIX}/campaigns"

    # duplicating this here and in transactions as we might want to change the token name once we fully deploy cosmos,
    # can be moved to core otherwise
    VELA_API_AUTH_TOKEN: str = ""

    @validator("VELA_API_AUTH_TOKEN")
    @classmethod
    def fetch_vela_api_auth_token(cls, v: str | None) -> str:
        return v or key_vault.get_secret("bpl-vela-api-auth-token")

    class Config:
        case_sensitive = True
        env_file = "local.env"
        env_file_encoding = "utf-8"


campaign_settings = CampaignSettings()
