"""Application settings. The only place that reads the environment (CLAUDE.md)."""

import logging
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.enums import Channel, Provider

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
CONFIG_DIR = BACKEND_DIR / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://unifycomm:unifycomm@localhost:5432/unifycomm"
    test_database_url: str = (
        "postgresql+asyncpg://unifycomm:unifycomm@localhost:5432/unifycomm_test"
    )

    jwt_secret: SecretStr = SecretStr("change-me")
    jwt_expires_minutes: int = 720
    seed_agent_password: SecretStr = SecretStr("demo1234")
    cors_origins: str = "http://localhost:3000"

    ai_mode: Literal["fake", "real"] = "fake"
    models_dir: Path = Path("./models")
    intent_model_dir: Path = Path("./models/intent/repro-v1")
    intent_confidence_floor: float = 0.50
    sentiment_model_id: str = "cardiffnlp/twitter-roberta-base-sentiment-latest"
    sentiment_model_revision: str = "3216a57f2a0d9c45a2e6c20157c20c49fb4bf9c7"
    torch_num_threads: int = 4

    openai_api_key: SecretStr = SecretStr("")
    openai_model_draft: str = "gpt-6-luna"
    openai_model_summary: str = "gpt-6-luna"
    openai_timeout_seconds: float = 20
    llm_enabled: bool = True

    conversation_reopen_days: int = 7
    summary_every_n_messages: int = 10
    business_timezone: str = "Asia/Kolkata"
    promo_window_start: time = time(9, 0)
    promo_window_end: time = time(21, 0)

    default_provider_whatsapp: Provider = Provider.simulator
    default_provider_sms: Provider = Provider.simulator
    default_provider_email: Provider = Provider.simulator

    public_base_url: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: SecretStr = SecretStr("")
    twilio_whatsapp_from: str = "whatsapp:+14155238886"

    email_address: str = ""
    email_app_password: SecretStr = SecretStr("")
    imap_host: str = "imap.gmail.com"
    smtp_host: str = "smtp.gmail.com"
    email_poll_seconds: int = 20

    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        return self.llm_enabled and bool(self.openai_api_key.get_secret_value())

    def resolve_path(self, path: Path) -> Path:
        """Paths in .env are relative to the repo root, not the working directory."""
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    @property
    def sentiment_model_dir(self) -> Path:
        """Where scripts/download_models.py puts the pinned sentiment model."""
        return self.resolve_path(self.models_dir) / "sentiment" / "hf"

    def default_provider(self, channel: Channel) -> Provider:
        return {
            Channel.whatsapp: self.default_provider_whatsapp,
            Channel.sms: self.default_provider_sms,
            Channel.email: self.default_provider_email,
        }[channel]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def setup_process(settings: Settings) -> None:
    """Call once at the start of the api and the worker.

    This machine's network re-signs TLS, so Python HTTPS must trust the OS certificate
    store (CLAUDE.md). truststore is torch-free and safe for both processes.
    """
    import truststore

    from app.log import configure_logging

    truststore.inject_into_ssl()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).debug("process configured")
