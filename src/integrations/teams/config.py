"""Teams settings are validated only when the integration is enabled."""
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TeamsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEAMS_", extra="ignore")

    tenant_id: str
    client_id: str
    client_secret: SecretStr
    allowed_group_ids: str
    session_retention_hours: int = Field(default=24, ge=1, le=8760)

    @field_validator("tenant_id", "client_id")
    @classmethod
    def guid(cls, value: str) -> str:
        return str(UUID(value.strip()))

    @field_validator("client_secret")
    @classmethod
    def secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Teams client secret is required")
        return value

    @field_validator("allowed_group_ids")
    @classmethod
    def groups(cls, value: str) -> str:
        # Empty entries must not silently turn a malformed access policy into another one.
        return ",".join(dict.fromkeys(str(UUID(item.strip())) for item in value.split(",")))

    @property
    def group_ids(self) -> list[str]:
        return self.allowed_group_ids.split(",")
