"""Environment loading and validation. Fails fast, so a missing value is a startup
error with a clear message rather than an AttributeError twenty minutes later.

Only four values come from the environment. Everything else is a constant here, so the
.env file stays short and there is one obvious place to change a URL or a tunable.
"""

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


DISCORD_TOKEN = _required("DISCORD_TOKEN")
SUPABASE_URL = _required("SUPABASE_URL").rstrip("/")
SUPABASE_SERVICE_KEY = _required("SUPABASE_SERVICE_KEY")
DONATION_URL = _required("DONATION_URL")

WEB_APP_URL = "https://henrusian.uwuapps.org"
REPO_URL = "https://github.com/augy-studios/henrusian-dictionary"
DEFAULT_TIMEZONE = "Asia/Singapore"

SQLITE_PATH = ROOT / "data" / "bot.db"
LOG_PATH = ROOT / "logs" / "bot.log"

# The web app's brand green, used as the stripe on every embed.
EMBED_COLOUR = 0xCCFFCC

# Tunables. Changing these needs no migration.
RESULTS_PER_PAGE = 8
FAVS_PER_PAGE = 8
ENTRY_REFRESH_SECONDS = 1800
DEFAULT_HOUR = 8
# A daily delivery that fails this many times in a row, because the DM is closed or the
# channel is gone, is switched off rather than retried forever.
MAX_DELIVERY_FAILURES = 3


def verify() -> None:
    """Called from bot.py before anything else happens."""
    if not _MISSING:
        return
    print("Cannot start, these environment values are missing:", file=sys.stderr)
    for name in _MISSING:
        print(f"  {name}", file=sys.stderr)
    print("\nCopy .env.example to .env and fill it in.", file=sys.stderr)
    # 2 tells run.sh this is a configuration problem, so it stops instead of restarting.
    sys.exit(2)
