import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
)


def get_cors_origins() -> list[str]:
    configured_origins = os.getenv("CLUSTERDRIVE_CORS_ORIGINS")
    if not configured_origins:
        return list(DEFAULT_CORS_ORIGINS)

    origins = [origin.strip().rstrip("/") for origin in configured_origins.split(",")]
    return [origin for origin in origins if origin]
