# Henrusian Dictionary bot

A Telegram bot for the [Henrusian Dictionary](../main-site), the open source dictionary for
the Henrusian constructed language, 15th edition. It reads the same Supabase catalogue the
web app reads, so the two never disagree about what a word means.

Built with [Telethon](https://docs.telethon.dev). Runs on a small VPS under tmux, keeps its
state in SQLite, and needs no message broker, no cron and no ORM.

Bot username: `@henrusian_bot`

## What it does

- **Search** by sending a word. There is no command for it: any message in a direct chat is
  searched across Words, Idioms and Names, and the buttons on the results narrow it to one
  catalogue or change the sort order.
- **Save entries**, which are shared with your browser once the two are linked.
- **Word of the day**, on request or delivered daily at an hour you choose, in your own
  timezone.
- **Recovery codes**, so a Telegram account you can no longer reach does not leave a link
  stuck forever.
- **Inline mode**, so you can quote an entry into any chat by typing `@henrusian_bot`
  followed by a word.

Buttons keep working forever. Callback state lives in SQLite rather than in the button
itself, so a search you ran weeks ago still pages, sorts and saves after any number of
restarts.

## Commands

| Command | What it does |
| --- | --- |
| `/start` | What the project is, every command, and buttons for the web app and the donation link |
| `/random` | A random entry, with a button for another |
| `/wotd` | The word of the day, the same one for everybody |
| `/favs` | Your saved entries, paged |
| `/link` | List the browsers sharing your favourites, or learn how to add one |
| `/unlink` | Unpair one browser or all of them, after a confirmation |
| `/code` | Use a code from the website, either to link or to recover |
| `/sub` | Turn on the daily word and pick the hour |
| `/unsub` | Turn it off |
| `/settings` | Timezone, delivery hour, whether a quote is attached |
| `/stats` | Catalogue sizes and the newest entry |
| `/privacy` | Exactly what is stored |
| `/cancel` | Abandon whatever step is in progress |

`/broadcast`, `/health` and `/refresh` exist for the owner and are not registered with
BotFather, so they never appear in anyone's command menu.

## Pairing, and what it is for

There is no account anywhere in this project, and nothing to sign in to. A pairing joins
**one browser** to **one Telegram account**, so that a starred entry shows up in both
places.

One Telegram account can pair with **as many browsers as you like**: a laptop, a phone, a
desktop at work. They all share the same collection. A browser belongs to one Telegram
account at a time, and pairing it somewhere else moves it.

Linking always starts in the browser, because only the browser knows which device is being
paired.

1. Open the dictionary and tap **Sync with Telegram**.
2. The browser sends you to `https://t.me/henrusian_bot?start=<token>`, which opens this
   chat. Tap **Start**.
3. Done. The token is claimed, the pairing is made, and the page notices within a few
   seconds. Repeat on another device to add it to the same collection.

**Merging.** Favourites saved before linking are never lost and never duplicated. The
browser's set travels with the token, the bot has its own set in local SQLite, and both are
merged by union into the shared table. An entry saved on both sides is stored once.

If the deep link cannot open, the page shows the token as an eight character code. Send it
with `/code` and the pairing is made the same way.

**Unpairing** works from either side and needs no cooperation from the other. In Telegram,
`/unlink` lists the browsers and lets you drop one or all of them. On the website, a browser
can unpair itself or the whole set.

Everyone keeps the favourites they have. Each browser keeps its copy in `localStorage`, and
when the last browser goes the bot copies the collection into its own storage before the
shared rows are deleted. An unpairing done on the website is noticed here within a couple of
minutes, and you are told when the last one goes.

## Recovery codes

Recovery codes cover the case where Telegram is out of reach: a lost phone, a number you
cannot get back, an account you can no longer sign in to. With no accounts in the picture,
what a code protects is the collection, and every browser paired with it.

- **Codes are created on the website, never here.** The bot cannot issue one and never shows
  one.
- Asking for a set does not create it. The website records the request, this bot asks you to
  approve it, and only then may the website reveal the codes. Reject it and nothing changes,
  which is your warning if a request appears that you did not make.
- Codes are shown once, on the website, immediately after approval. They are deliberately not
  sent through Telegram, so they never sit in a chat history.
- Ten codes, in the form `ABCD-EFGH-JKMN`. Each works once, and a new set replaces every
  unused old one at the moment the new codes appear.
- **To release everything without Telegram**, enter a code on the website. Every paired
  browser is released, and your favourites stay in the browser you used.
- **To move the collection to a new Telegram account**, send `/code <code>` from that
  account. Every browser comes across with it, along with the remaining codes, and the
  previous holder is told if it can still be reached.
- Five failures in an hour locks recovery for that Telegram account, and also for the
  collection itself, so hopping between Telegram accounts does not reset the limit.
- Only hashes are stored. A lost set cannot be recovered, only replaced.

## Running it

Debian 13 marks the system Python as externally managed, so a virtual environment is not
optional.

```bash
sudo apt update && sudo apt install -y python3 python3-venv git tmux sqlite3
git clone https://github.com/augy-studios/henrusian-dictionary.git
cd henrusian-dictionary/telegram-bot

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env

chmod +x run.sh
tmux new -s henrusian-bot
./run.sh
```

Detach from tmux with `Ctrl+b` then `d`. Reattach with `tmux attach -t henrusian-bot`.

`run.sh` restarts the bot if it exits unexpectedly, backing off up to a minute, and stops
cleanly on `Ctrl+C`. Logs go to `logs/bot.log`, rotated at 2 MB, five files kept.

Full first time setup, including BotFather and the Supabase migrations, is in
[SETUP.md](SETUP.md).

## Environment

| Variable | Required | What it is |
| --- | --- | --- |
| `TELEGRAM_API_ID` | yes | From my.telegram.org. Telethon needs it even for a bot login |
| `TELEGRAM_API_HASH` | yes | Same place |
| `TELEGRAM_BOT_TOKEN` | yes | From BotFather |
| `SUPABASE_URL` | yes | The project URL |
| `SUPABASE_SERVICE_KEY` | yes | Service role key. Server side only |
| `DONATION_URL` | yes | Where the donate button points |
| `WEB_APP_URL` | yes in practice | The site, and the base for the sync page link |
| `BACKUP_CODE_PEPPER` | recommended | Mixed into every code hash. **Must match the value the website uses**, and changing it invalidates every code already issued |
| `BOT_OWNER_ID` | optional | Your Telegram numeric id. Without it, `/broadcast` and `/health` are disabled |
| `SQLITE_PATH` | optional | Defaults to `data/bot.db` |
| `DEFAULT_TIMEZONE` | optional | Defaults to `Asia/Singapore` |

The bot refuses to start with a clear list if a required value is missing.

## Layout

```text
telegram-bot/
├── bot.py               Entry point: client, dispatcher, scheduler
├── config.py            Environment loading and validation
├── db.py                SQLite connection and helpers
├── schema.sql           Local schema, applied on every boot
├── run.sh               tmux launcher with restart on crash
├── handlers/            One module per group of commands
│   ├── common.py        Command patterns, guards, the canonical command list
│   ├── views.py         Every screen, as pure functions of their parameters
│   ├── start.py         /start /privacy /cancel and the home buttons
│   ├── search.py        Plain text search, /random /wotd /stats
│   ├── favourites.py    /favs and the star buttons
│   ├── linking.py       /link /unlink /code, and the code approval prompts
│   ├── subscriptions.py /sub /unsub /settings
│   ├── admin.py         /broadcast /health /refresh
│   └── inline.py        Inline mode
├── services/
│   ├── supabase.py      PostgREST client
│   ├── entries.py       Catalogue cache, search, word of the day
│   ├── favourites.py    Local and shared favourites, and the merge
│   ├── linking.py       Pairing tokens and link records
│   ├── backup_codes.py  Approval requests, hashing, redemption
│   ├── buttons.py       Durable callback tokens
│   ├── scheduler.py     SQLite job queue
│   └── external.py      Third party APIs with fallbacks and caching
├── utils/
│   ├── rich.py          send_rich_message, the one way messages are sent
│   ├── text.py          Escaping, truncation, the dash sanitiser
│   └── ratelimit.py     Per user cooldowns
└── tests/               Offline test suite, no network and no Telegram
```

## How it works

**Catalogue.** Every entry from all three tables is fetched from Supabase, paged 1000 at a
time, and cached both in memory and in SQLite. Search runs locally, which makes it instant
and keeps the bot usable if Supabase has a bad minute. The cache refreshes every thirty
minutes, or on demand with `/refresh`.

**Buttons.** Telegram allows 64 bytes of callback data, which is not enough for real state.
Each button carries an opaque token instead, and the action plus its parameters live in the
`callbacks` table. Tokens are never expired. Every view is a pure function of its parameters,
so any old button can rebuild its screen from scratch.

**Scheduling.** The `jobs` table is the queue. One worker wakes every fifteen seconds, claims
due rows in a single transaction, runs them, and either reschedules or deletes them. Failures
retry with exponential backoff up to five attempts. Locks older than ten minutes are
reclaimed, which is how a job interrupted by a crash gets picked up again. Daily deliveries
are recalculated in the subscriber's timezone each time they fire, so daylight saving needs
no special case.

**Talking to the website.** The website cannot message anybody, so two polls close the loop:
one watches for recovery code requests raised there, the other notices when the last
browser has been unpaired there. Both are ordinary rows in the job queue.

**Third party sources.** The daily word can carry a quote, from
[Quotable](https://github.com/lukePeavey/quotable) with
[ZenQuotes](https://zenquotes.io) as a fallback. Both are free and keyless, responses are
cached, and a failure just means the quote is left out.

**Message style.** Everything goes out through `send_rich_message`: HTML formatting, a bold
title, escaped database text, automatic splitting at the message limit, and one retry after a
flood wait. Em dashes and en dashes are removed from outbound copy.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

210 tests, all offline. Telegram is replaced by small fakes and Supabase by an in-memory
PostgREST stub, so nothing reaches the network and no credentials are needed. One test
shells out to Node, if it is installed, to prove the bot and the website hash a recovery
code identically.

## Troubleshooting

**It exits immediately with a list of variables.** The `.env` file is missing or incomplete.
Copy `.env.example` and fill it in.

**"The catalogue is still loading."** The first fetch has not finished, or Supabase is
unreachable. Check `logs/bot.log`, then run `/health` if you are the owner.

**A recovery code from the website is rejected here.** `BACKUP_CODE_PEPPER` differs between
the bot and the site. They hash codes the same way and must share the value.

**"This button is no longer available."** The token is not in the database, which normally
means the database file was replaced or deleted. `/start` gives a fresh screen.

**Buttons stopped working after a move.** `data/bot.db` holds every button token. Copy it
along with the code, or accept that old messages go inert.

**Nothing happens in a group.** Telegram's group privacy mode hides ordinary messages from
bots, which is the safe default, so searching by sending a word only works in a direct chat.

**A daily word did not arrive.** Check the timezone with `/settings`. The queue is readable
with `sqlite3 data/bot.db "select * from jobs"`.

## Contributing

Keep the dependency list short, keep every outbound string free of em dashes, and put new
screens in `handlers/views.py` as pure functions so the durable buttons keep working. Run the
tests before opening a pull request.

## Licence

MIT, the same as the rest of the project.
