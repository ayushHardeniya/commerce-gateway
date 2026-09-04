from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration sourced from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "commerce-gateway"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/commerce_gateway"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"

    # Test Mode credentials for the Razorpay adapter
    # (app.commerce.payment.razorpay). Payment is unavailable (503) without
    # them; the rest of the app works without them, same as Gemini above.
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None

    # Comma-separated browser origins allowed to call this API (see
    # app.main's CORSMiddleware setup). Defaults to the local Next.js dev
    # server on both hostnames a browser may use for it.
    cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
