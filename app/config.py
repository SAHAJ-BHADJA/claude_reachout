"""Central configuration. Works locally (SQLite) and on Render/Supabase (Postgres)."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _g(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _norm_db_url(url: str) -> str:
    # Render/Heroku give postgres://; SQLAlchemy + psycopg3 want postgresql+psycopg://
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    # ---- Database ----
    DATABASE_URL = _norm_db_url(_g("DATABASE_URL", f"sqlite:///{ROOT / '.secrets' / 'app.db'}"))

    # ---- Apify (code_crafter/leads-finder) ----
    APIFY_TOKEN = _g("APIFY_TOKEN")
    APIFY_ACTOR_ID = _g("APIFY_ACTOR_ID", "IoSHqwTR9YGhzccez")

    # ---- Apollo ----
    APOLLO_API_KEYS = [k.strip() for k in _g("APOLLO_API_KEYS").split(",") if k.strip()]
    APOLLO_BASE_URL = _g("APOLLO_BASE_URL", "https://api.apollo.io/api/v1")

    # ---- Hunter.io ----
    HUNTER_API_KEY = _g("HUNTER_API_KEY")
    HUNTER_FETCH = int(_g("HUNTER_FETCH", "10"))   # free plan caps domain-search at 10 results

    # ---- Anthropic ----
    ANTHROPIC_API_KEY = _g("ANTHROPIC_API_KEY")
    ANTHROPIC_MODEL_NAME = _g("ANTHROPIC_MODEL_NAME", "claude-opus-4-5-20251101")

    # ---- Gmail ----
    GOOGLE_CLIENT_ID = _g("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = _g("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = _g("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/gmail/oauth/callback")
    GMAIL_SENDER_EMAIL = _g("GMAIL_SENDER_EMAIL")

    # ---- Research ----
    TAVILY_API_KEY = _g("TAVILY_API_KEY")

    # ---- Public URL (Render) — used for the tracking pixel ----
    TRACKING_BASE_URL = _g("TRACKING_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

    # ---- Cron tick protection ----
    CRON_SECRET = _g("CRON_SECRET", "change-me")

    # ---- Sending / deliverability policy ----
    SEND_TIMEZONE = _g("SEND_TIMEZONE", "America/Los_Angeles")
    SEND_DAYS = [int(x) for x in _g("SEND_DAYS", "0,1,2,3,4").split(",") if x != ""]  # Mon=0..Sun=6
    SEND_HOUR_START = int(_g("SEND_HOUR_START", "9"))
    SEND_HOUR_END = int(_g("SEND_HOUR_END", "17"))
    MIN_GAP_SECONDS = int(_g("MIN_GAP_SECONDS", "420"))      # ~7 min between sends
    DAILY_HARD_CAP = int(_g("DAILY_HARD_CAP", "50"))
    # warmup ramp: emails/day by age of sending (days since first send). Short ramp
    # because this is an established, regularly-used inbox; then DAILY_HARD_CAP.
    WARMUP_RAMP = [30, 40, 50]  # then DAILY_HARD_CAP (50)

    # ---- Lead caps + how many to actually email ----
    APIFY_FETCH = int(_g("APIFY_FETCH", "30"))
    APOLLO_FETCH = int(_g("APOLLO_FETCH", "20"))
    EMAIL_TOP_N = int(_g("EMAIL_TOP_N", "20"))               # email the best N per company

    # ---- Follow-up cadence (business days after previous, if no reply) ----
    FOLLOWUP_GAP_DAYS = [int(x) for x in _g("FOLLOWUP_GAP_DAYS", "3,4").split(",")]

    # ---- Files ----
    # On Render, either mount the resume as a Secret File and point MASTER_DATA_PATH at it,
    # or paste the JSON into MASTER_DATA_JSON. Locally it's just the file path.
    MASTER_DATA_PATH = Path(_g("MASTER_DATA_PATH", str(ROOT / "master_resume_data.json")))
    MASTER_DATA_JSON = _g("MASTER_DATA_JSON")
    RESUME_ROOT = Path(_g("RESUME_ROOT", r"E:\Projects\Random\Resume\COMPANY"))

    # ---- App ----
    APP_HOST = _g("APP_HOST", "127.0.0.1")
    APP_PORT = int(_g("APP_PORT", "8000") or "8000")


cfg = Config()
(ROOT / ".secrets").mkdir(exist_ok=True)
(ROOT / "exports").mkdir(exist_ok=True)
