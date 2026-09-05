#!/usr/bin/env bash
# Launcher for tmux. Restarts the bot if it exits unexpectedly, and stops cleanly on
# Ctrl+C so a deliberate stop does not turn into a restart loop.
#
#   tmux new -s henrusian-bot
#   ./run.sh
#   detach with Ctrl+b then d, reattach with tmux attach -t henrusian-bot

set -u

cd "$(dirname "$0")" || exit 1

if [ -d .venv ]; then
    # shellcheck disable=SC1091
    . .venv/bin/activate
else
    echo "No .venv found. Create one with: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

if [ ! -f .env ]; then
    echo "No .env found. Copy .env.example to .env and fill it in."
    exit 1
fi

mkdir -p data logs

stop() {
    echo ""
    echo "Stopping."
    exit 0
}
trap stop INT TERM

backoff=2
while true; do
    echo "Starting the bot at $(date '+%Y-%m-%d %H:%M:%S')"
    python bot.py
    code=$?

    if [ "$code" -eq 0 ]; then
        echo "The bot exited normally."
        exit 0
    fi

    echo "The bot exited with code $code. Restarting in ${backoff}s."
    sleep "$backoff"
    backoff=$(( backoff * 2 ))
    [ "$backoff" -gt 60 ] && backoff=60
done
