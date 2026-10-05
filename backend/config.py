import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    frontend_origins: tuple[str, ...]
    session_ttl_hours: int
    stripe_secret_key: str | None
    stripe_publishable_key: str | None
    stripe_webhook_secret: str | None
    stripe_currency: str
    stripe_success_url: str
    stripe_cancel_url: str
    stripe_allowed_countries: tuple[str, ...]

    def __post_init__(self):
        if self.session_ttl_hours < 1:
            raise ValueError("SESSION_TTL_HOURS must be at least 1")
        if not re.fullmatch(r"[a-z]{3}", self.stripe_currency):
            raise ValueError("STRIPE_CURRENCY must be a 3-letter ISO currency code")
        if any(not re.fullmatch(r"[A-Z]{2}", country) for country in self.stripe_allowed_countries):
            raise ValueError("STRIPE_ALLOWED_COUNTRIES must contain 2-letter country codes")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    origins = os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174",
    )
    countries = os.getenv("STRIPE_ALLOWED_COUNTRIES", "US,CA,GB,IN")
    return Settings(
        database_url=os.getenv("DATABASE_URL"),
        frontend_origins=tuple(value.strip() for value in origins.split(",") if value.strip()),
        session_ttl_hours=int(os.getenv("SESSION_TTL_HOURS", "12")),
        stripe_secret_key=os.getenv("STRIPE_SECRET_KEY"),
        stripe_publishable_key=os.getenv("STRIPE_PUBLISHABLE_KEY"),
        stripe_webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET"),
        stripe_currency=os.getenv("STRIPE_CURRENCY", "usd").lower(),
        stripe_success_url=os.getenv(
            "STRIPE_SUCCESS_URL",
            "http://localhost:5173/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
        ),
        stripe_cancel_url=os.getenv(
            "STRIPE_CANCEL_URL", "http://localhost:5173/?checkout=cancelled"
        ),
        stripe_allowed_countries=tuple(
            value.strip().upper() for value in countries.split(",") if value.strip()
        ),
    )
