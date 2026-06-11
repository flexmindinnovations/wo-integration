from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Odoo
    ODOO_URL: str = ""
    ODOO_DB: str = ""
    ODOO_USERNAME: str = ""
    ODOO_PASSWORD: Optional[str] = None
    ODOO_API_KEY: Optional[str] = None

    # Meta WhatsApp Cloud API
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = "whatsapp_verify_token"

    # Google Gemini AI
    GOOGLE_GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # PostgreSQL
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/whatsapp_campaigns"

    # CORS
    FRONTEND_ORIGINS: str = (
        "http://localhost:3000,"
        "http://localhost:5173,"
        "http://127.0.0.1:3000,"
        "http://127.0.0.1:5173,"
        "https://campaign-desk.vercel.app"
    )

    # Campaign execution
    CAMPAIGN_BATCH_SIZE: int = 50
    MESSAGE_DELAY_SECONDS: float = 1.0
    MAX_RETRY_ATTEMPTS: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
