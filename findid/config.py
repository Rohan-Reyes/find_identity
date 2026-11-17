"""Settings, read once from the environment and an optional .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


SERPAPI_API_KEY: str = (os.getenv("SERPAPI_API_KEY") or "").strip()
if SERPAPI_API_KEY.startswith("your_"):  # the untouched .env.example placeholder
    SERPAPI_API_KEY = ""

DATA_DIR = Path(os.getenv("FI_DATA_DIR") or ROOT / "data").resolve()
REPORTS_DIR = DATA_DIR / "reports"
UPLOADS_DIR = DATA_DIR / "uploads"

CONCURRENCY = max(1, _int("FI_CONCURRENCY", 8))
TIMEOUT = max(2.0, _float("FI_TIMEOUT", 12.0))
MAX_IMAGE_MB = max(1, _int("FI_MAX_IMAGE_MB", 15))
MAX_IMAGES = 10
MAX_USERNAMES = 20

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)
TOOL_UA = "find-identity/2.0 (+https://github.com/Rohan-Reyes/find_identity)"


def ensure_dirs() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
