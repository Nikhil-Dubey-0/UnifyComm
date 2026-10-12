from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import BACKEND_DIR, Settings, get_settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    base = get_settings()
    if base.test_database_url == base.database_url:
        pytest.exit("TEST_DATABASE_URL must differ from DATABASE_URL", returncode=2)
    return base.model_copy(
        update={
            "database_url": base.test_database_url,
            "ai_mode": "fake",
            "jwt_secret": SecretStr("test-secret-" + "x" * 32),
            "llm_enabled": False,
            "openai_api_key": SecretStr(""),
            # Tests never reach real channels, whatever .env holds.
            "email_address": "",
            "email_app_password": SecretStr(""),
            "email_allowed_senders": "",
            "twilio_account_sid": "",
            "twilio_auth_token": SecretStr(""),
            "twilio_whatsapp_from": "whatsapp:+14155238886",
            "public_base_url": "",
            "test_contact_name": "",
            "test_contact_phone": "",
            "test_contact_email": "",
        }
    )


@pytest.fixture(scope="session")
def backend_dir() -> Path:
    return BACKEND_DIR
