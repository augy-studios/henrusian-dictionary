"""Environment loading and validation. Fails fast, so a missing value is a startup
error with a clear message rather than an AttributeError twenty minutes later."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

_MISSING = []


def _required(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        _MISSING.append(name)
    return value


def _optional(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None or not value.strip() else value.strip()


TELEGRAM_API_ID_RAW = _required("TELEGRAM_API_ID")
TELEGRAM_API_HASH = _required("TELEGRAM_API_HASH")
TELEGRAM_BOT_TOKEN = _required("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = _required("SUPABASE_URL").rstrip("/")
SUPABASE_SERVICE_KEY = _required("SUPABASE_SERVICE_KEY")
DONATION_URL = _required("DONATION_URL")

WEB_APP_URL = _optional("WEB_APP_URL", "https://henrusian.uwuapps.org").rstrip("/")
DEFAULT_TIMEZONE = _optional("DEFAULT_TIMEZONE", "Asia/Singapore")
REPO_URL = _optional("REPO_URL", "https://github.com/augy-studios/henrusian-dictionary")

# Mixed into every backup code digest. Optional, but recommended: with it, a leaked
# database alone is not enough to test a guessed code offline. It must match the value the
# web app uses, and changing it invalidates every code already issued.
BACKUP_CODE_PEPPER = _optional("BACKUP_CODE_PEPPER", "")

_owner = _optional("BOT_OWNER_ID", "0")
BOT_OWNER_ID = int(_owner) if _owner.isdigit() else 0

SQLITE_PATH = Path(_optional("SQLITE_PATH", "data/bot.db"))
if not SQLITE_PATH.is_absolute():
    SQLITE_PATH = ROOT / SQLITE_PATH

SESSION_PATH = ROOT / "data" / "bot"
LOG_PATH = ROOT / "logs" / "bot.log"

# Tunables. Changing these needs no migration.
RESULTS_PER_PAGE = 8
# How often to look for a recovery code request raised on the website. The website cannot
# message anybody, so this poll is what turns a request into an approval prompt.
CODE_POLL_SECONDS = 10
# How often to check whether a link was removed from the browser side.
LINK_SWEEP_SECONDS = 120
ENTRY_REFRESH_SECONDS = 1800
API_CACHE_SECONDS = 300
BACKUP_CODE_COUNT = 10
RECOVERY_LOCKOUT_ATTEMPTS = 5
RECOVERY_LOCKOUT_MINUTES = 60
BROADCAST_CHUNK = 20
BROADCAST_CHUNK_DELAY = 30

TELEGRAM_API_ID = 0
if TELEGRAM_API_ID_RAW:
    if TELEGRAM_API_ID_RAW.isdigit():
        TELEGRAM_API_ID = int(TELEGRAM_API_ID_RAW)
    else:
        _MISSING.append("TELEGRAM_API_ID (must be a number)")


def verify() -> None:
    """Called from bot.py before anything else happens."""
    if not _MISSING:
        return
    print("Cannot start, these environment values are missing or invalid:", file=sys.stderr)
    for name in _MISSING:
        print(f"  {name}", file=sys.stderr)
    print("\nCopy .env.example to .env and fill it in.", file=sys.stderr)
    sys.exit(1)
