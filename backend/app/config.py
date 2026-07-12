from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PF_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str = ""  # empty -> sqlite file under data_dir

    # If set, the encryption keyring is unlocked at startup so scheduled
    # jobs can run unattended. Otherwise unlock via POST /auth/unlock.
    passphrase: str | None = None

    session_ttl_hours: int = 24
    cors_origins: list[str] = ["http://localhost:5173", "https://localhost"]

    # Base currency for aggregate views. Individual assets keep their own currency.
    base_currency: str = "INR"

    scheduler_enabled: bool = True

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'pf.db'}"


settings = Settings()
