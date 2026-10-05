from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv_file(path: Path) -> bool:
    """Minimal .env reader (KEY=VALUE, # comments). Real environment variables always win.

    The previous version of this project NEVER read backend/.env, so every setting in it
    (contact e-mail, Google key, limits) was silently ignored."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
    return True


_BACKEND_DIR = Path(__file__).resolve().parent.parent
for _candidate in (_BACKEND_DIR / ".env", Path.cwd() / ".env"):
    load_dotenv_file(_candidate)


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("LEADX_DB", "leadx.db")
    allowed_origins: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    locations_db: str = os.getenv("LEADX_LOCATIONS_DB", str(_BACKEND_DIR / "leadx" / "data" / "locations.db"))
    max_concurrent: int = _int("LEADX_MAX_CONCURRENT", 1)
    max_tiles: int = _int("LEADX_MAX_TILES", 400)
    contact_email: str = "" if any(t in os.getenv("CONTACT_EMAIL", "").lower() for t in ("example.com", "your-real-email", "your-email")) else os.getenv("CONTACT_EMAIL", "").strip()
    nominatim_user_agent: str = os.getenv("NOMINATIM_USER_AGENT", "LeadExtractor/1.0")
    nominatim_referer: str = os.getenv("NOMINATIM_REFERER", "http://localhost:3000/")
    nominatim_min_interval: float = _float("NOMINATIM_MIN_INTERVAL", 1.1)
    google_places_api_key: str = os.getenv("GOOGLE_PLACES_API_KEY", "")
    google_text_search_free_cap: int = _int("GOOGLE_TEXT_SEARCH_FREE_CAP", 35000)
    google_text_search_price_per_1000: float = _float("GOOGLE_TEXT_SEARCH_PRICE_PER_1000", 9.60)
    google_detail_free_cap: int = _int("GOOGLE_PLACE_DETAILS_FREE_CAP", 35000)
    google_detail_price_per_1000: float = _float("GOOGLE_PLACE_DETAILS_PRICE_PER_1000", 5.10)
    google_region: str = os.getenv("GOOGLE_PRICING_REGION", "IN")
    public_app_base_url: str = os.getenv("PUBLIC_APP_BASE_URL", "http://localhost:3000")
    email_enabled: bool = _bool("EMAIL_ENRICHMENT_ENABLED", True)
    email_timeout: float = _float("EMAIL_TIMEOUT_SECONDS", 15.0)
    email_per_domain_delay: float = _float("EMAIL_PER_DOMAIN_DELAY", 0.75)
    email_max_concurrency: int = _int("EMAIL_MAX_CONCURRENCY", 4)


settings = Settings()
