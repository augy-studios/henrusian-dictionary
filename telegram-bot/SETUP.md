# Setup

Everything needed to take the bot from nothing to running, in order. Budget about thirty
minutes the first time.

The bot username used throughout is `@henrusian_bot`.

## 1. Telegram API credentials

Telethon speaks the full MTProto protocol, so it needs an API id and hash even when it is
signing in as a bot.

1. Go to [my.telegram.org](https://my.telegram.org) and sign in with your phone number.
2. Open **API development tools**.
3. Fill in any app title and short name. The platform can be Other.
4. Copy **App api_id** and **App api_hash**.

These identify the application, not the bot. Keep them private, and never commit them.

## 2. Create the bot in BotFather

Open [@BotFather](https://t.me/BotFather) in Telegram and send each command in turn.

### Create it

```text
/newbot
```

- Name, shown as the display name: `Henrusian Dictionary`
- Username, must end in `bot`: `henrusian_bot`

BotFather replies with the token. That single string is full control of the bot, so treat
it as a password. If it ever leaks, use `/revoke` and put the new one in `.env`.

### About text

Shown on the bot's profile, 120 characters maximum.

```text
/setabouttext
```

Then pick `@henrusian_bot` and send:

```text
Search the Henrusian dictionary, save what you like, and share it with your browser. Words, idioms and names in one place.
```

### Description

Shown on an empty chat, before anyone sends a message, 512 characters maximum.

```text
/setdescription
```

Then send:

```text
The Henrusian Dictionary, 15th edition, in Telegram. Just send a word to look it up, open any entry for the full definition, and save the ones you want to keep. Link the web app and your saved entries are shared between the two, with no account and nothing to sign in to. Turn on the word of the day and a new entry arrives each morning at an hour you choose. Send /start to see everything it can do.
```

### Profile picture

```text
/setuserpic
```

Upload `main-site/hrd-512.png` from this repository.

### Commands

```text
/setcommands
```

Then paste this block exactly. No entry names the bot, which keeps the menu readable and
means the commands read the same way if the bot is ever renamed.

```text
start - What this bot does and everything it can do
random - Show a random entry
wotd - Word of the day
favs - Show your saved entries
link - List the browsers sharing your favourites
unlink - Unpair a browser, or all of them
code - Use a code from the website, to link or to recover
sub - Get a word of the day every morning
unsub - Stop the daily word
settings - Timezone and delivery preferences
stats - Catalogue sizes and latest additions
privacy - What data is stored
cancel - Cancel the current step
```

`/broadcast`, `/health` and `/refresh` are left out on purpose. They check the owner id
before doing anything, and keeping them out of the menu means nobody is tempted.

Note there is no `search` command. Any plain message in a direct chat is searched, which is
one fewer thing to remember, and the filter buttons on the results cover the individual
catalogues.

### Inline mode

Lets people type `@henrusian_bot water` in any chat and pick an entry to send.

```text
/setinline
```

Placeholder text:

```text
Search the dictionary
```

To turn it off later, send `/setinline` and then `-`.

### Group privacy

```text
/setprivacy
```

Choose **Enable**. With privacy mode on, the bot sees commands addressed to it and
nothing else. It is the right default: the bot has no reason to read group conversation,
and leaving it off would mean every message in every group reaches your VPS.

The consequence is that searching by sending a word only works in a direct chat, since that
is the only place the bot can see an ordinary message. Group members can still use the
commands.

### Joining groups

```text
/setjoingroups
```

Enable if you want the bot usable in group chats, disable to keep it to direct chats only.
The reading commands work fine in groups. Linking and recovery ask the person to continue in
a direct chat, since a code should never be pasted where others can see it.

## 3. Supabase migrations

The bot reads the three catalogue tables that already exist, and needs six new ones for
links, pairing tokens, shared favourites, backup codes, approval requests and the attempt log.

1. Open the Supabase dashboard for the project, then **SQL Editor**.
2. Run each file from [main-site/migrations/](../main-site/migrations/) in order:
   `0001_sync_links.sql`, `0002_sync_favourites.sql`, `0003_backup_codes.sql`.
3. Check under **Table Editor** that the tables appear with row level security on. None of
   them has a policy, on purpose: only the service key touches them, and the anon key the
   browser holds can see nothing.

Read [main-site/migrations/README.md](../main-site/migrations/README.md) as well.

Copy the project URL and the **service role** key from Project Settings, API. The service
role key bypasses row level security, so it lives only on the VPS and never in the
browser.

## 4. Install on the VPS

Debian 13 ships Python 3.13 and marks the system interpreter as externally managed, so
`pip install` outside a virtual environment is refused. That is expected.

```bash
sudo apt update
sudo apt install -y python3 python3-venv git tmux sqlite3

git clone https://github.com/augy-studios/henrusian-dictionary.git
cd henrusian-dictionary/telegram-bot

python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Consider a dedicated user rather than root:

```bash
sudo adduser --disabled-password --gecos "" henrusian
sudo -u henrusian -i
```

## 5. Configure

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

| Variable | Where it comes from |
| --- | --- |
| `TELEGRAM_API_ID` | Step 1 |
| `TELEGRAM_API_HASH` | Step 1 |
| `TELEGRAM_BOT_TOKEN` | Step 2 |
| `SUPABASE_URL` | Step 3 |
| `SUPABASE_SERVICE_KEY` | Step 3, the service role key |
| `DONATION_URL` | `https://donate.stripe.com/28o2akeAr3hv0DK6oo` |
| `WEB_APP_URL` | The production site, with no trailing slash |
| `BACKUP_CODE_PEPPER` | Any long random string, for instance from `openssl rand -hex 32` |
| `BOT_OWNER_ID` | Your Telegram numeric id, from [@userinfobot](https://t.me/userinfobot) |

`SQLITE_PATH` and `DEFAULT_TIMEZONE` can stay as they are.

**`BACKUP_CODE_PEPPER` has to match on both sides.** The bot and the site hash recovery codes
the same way, so set the identical value in the Vercel project environment as well. Leaving it
empty works, but a leaked database would then be easier to test guesses against. Changing it
later invalidates every code already issued.

The web app needs its own environment entries in Vercel: `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, the same `BACKUP_CODE_PEPPER`, `WEB_APP_URL`, and
`TELEGRAM_BOT_USERNAME` set to `henrusian_bot`, which is what builds the `t.me` link.

## 6. First run

```bash
chmod +x run.sh
tmux new -s henrusian-bot
./run.sh
```

The log should show the schema applied, the sign in as `@henrusian_bot`, the scheduler
starting, and a catalogue line with three counts. Message the bot with `/start`, then send a
word you know is in the dictionary.

Then check the pairing end to end: open the site, tap **Sync with Telegram**, tap Start in
Telegram, and confirm the page moves to Paired on its own. Doing the same in a second
browser should add it alongside the first rather than replacing it.

Detach with `Ctrl+b` then `d`. The bot keeps running.

```bash
tmux ls                          # list sessions
tmux attach -t henrusian-bot     # come back
tail -f logs/bot.log             # follow the log without attaching
```

If you are the owner, `/health` reports catalogue sizes, cache age, pending jobs and the
last database error.

## 7. Keeping it running

tmux does not survive a reboot. Either reattach and start it again by hand, or install
the optional user unit below, which starts the bot on boot and restarts it on failure.
tmux stays the documented default; this is only for unattended machines.

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/henrusian-bot.service <<'UNIT'
[Unit]
Description=Henrusian Dictionary Telegram bot
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/henrusian-dictionary/telegram-bot
ExecStart=%h/henrusian-dictionary/telegram-bot/.venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now henrusian-bot
sudo loginctl enable-linger "$USER"     # so it starts without a login session
journalctl --user -u henrusian-bot -f
```

Do not run both at once. Pick tmux or systemd, since two processes on the same bot token
will fight over updates.

## 8. Updating

```bash
tmux attach -t henrusian-bot
# Ctrl+C to stop
git pull
. .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

Schema changes are applied automatically at boot. `data/bot.db` is never overwritten by an
update, so subscriptions, favourites saved before linking, and every live button survive.

Run the tests after pulling, since they need no credentials and take a few seconds:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## 9. Backups

Two files matter:

- `data/bot.db`, which holds button tokens, subscriptions, jobs and unlinked favourites.
- `.env`, which holds every secret.

```bash
sqlite3 data/bot.db ".backup '/home/henrusian/backups/bot-$(date +%F).db'"
```

Use `.backup` rather than copying the file. A plain copy taken while the bot is writing
can be inconsistent, since the database runs in WAL mode.

`data/bot.session` is the Telethon login. Losing it is harmless, as the bot signs in
again from the token, but it is a credential, so keep it off GitHub. The supplied
`.gitignore` already excludes all of these.

## 10. If the token leaks

1. `/revoke` in BotFather, and pick `@henrusian_bot`.
2. Put the new token in `.env`.
3. Delete `data/bot.session`.
4. Restart.

Nothing else is affected. Links, favourites and recovery codes live in Supabase, keyed by
Telegram user id rather than by the token.
