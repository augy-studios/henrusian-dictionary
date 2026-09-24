# Henrusian Dictionary for Discord

A slash command bot for the [Henrusian Dictionary](../main-site), the open source dictionary
for the Henrusian constructed language, 15th edition. It reads the same Supabase catalogue as
the web app and the [Telegram bot](../telegram-bot), so every surface agrees about what a word
means and which word is today's.

Built with [discord.py](https://discordpy.readthedocs.io). Runs on a small VPS under tmux,
keeps its state in SQLite, and needs no message broker, no cron, no ORM and no privileged
intents.

## What it does

- **Search** words, idioms and names with `/search`. Results page, filter by catalogue and
  change sort order with buttons, and the query box suggests words as you type.
- **Save entries** to your Discord account and browse them with `/favs`.
- **Word of the day**, on request, or delivered every day at an hour you choose in your own
  timezone, either by DM or in a server channel.
- **Works anywhere.** Add the bot to a server, or add the app to your own account and use the
  commands in any server, group DM or DM, even where the bot is not a member.

Buttons keep working forever. Each button carries a short token, and what the button does
lives in SQLite, so a search from months ago still pages, sorts and saves after any number of
restarts.

## Commands

| Command | What it does |
| --- | --- |
| `/help` | What the project is, every command, and buttons for the web app and the donation link |
| `/search <query> [catalogue] [private]` | Search all three catalogues or one. `private` shows the results only to you |
| `/random [catalogue]` | A random entry, with a button for another |
| `/wotd` | The word of the day, the same one for everybody |
| `/favs` | Your saved entries, paged. Only you see them |
| `/sub [hour] [timezone] [channel]` | Turn the daily word on, by DM or, with `channel`, in a server channel |
| `/unsub [channel]` | Turn it off |
| `/settings [timezone] [hour] [quote] [channel]` | View or change the daily word, your timezone, and whether a quote is attached |
| `/stats` | Catalogue sizes and the newest entry |
| `/privacy` | Exactly what is stored, and a button to erase it |

Personal screens (`/favs`, `/settings`, `/privacy`, and the daily word commands) are only
visible to the person who ran them. Everything else posts normally, unless `/search` is given
`private: True`.

**Who can press what.** Pressing a button on your own message changes it in place. Pressing one
on somebody else's message, or on a channel's daily post, opens a private copy of the next
screen for you instead, so nobody can page through someone else's results for them.

## The daily word

- **By DM.** Run `/sub` anywhere. The bot sends a short DM straight away to prove it can reach
  you, and tells you if your privacy settings block it. You can also run it inside the bot's DM.
- **In a channel.** Run `/sub channel:#words` in the server. You need the **Manage Server**
  permission, and the bot itself has to be in that server, not just installed on someone's
  account. If it is not, the reply includes an invite link. The bot needs View Channel, Send
  Messages and Embed Links in the channel.
- **Time.** Defaults to 08:00 in `Asia/Singapore`. Pick an hour from 0 to 23 and any IANA
  timezone; the option suggests names as you type. Your timezone is remembered for your DM
  subscription, and each channel has its own.
- **Quote.** Each daily post carries a quote from [Quotable](https://github.com/lukePeavey/quotable),
  with [ZenQuotes](https://zenquotes.io) as a fallback. Both are free and keyless. Turn it off
  with `/settings quote: False`, or the button on the settings screen.
- **Failures.** If a DM is closed or a channel is deleted, the bot tries again the next day, and
  after three failed days in a row it turns that subscription off.

The word of the day is chosen from the date, the same way the Telegram bot chooses it, so both
bots show the same word on the same day.

## Setting up the Discord application

1. Open the [Developer Portal](https://discord.com/developers/applications) and create an
   application. Name it and give it an icon there. Command names never include the bot's name.
2. **Bot** page: press **Reset Token** and copy it into `DISCORD_TOKEN`. Leave all three
   Privileged Gateway Intents **off**. The bot does not read messages.
3. **Installation** page: tick both **User Install** and **Guild Install**, then set the default
   install settings:
   - User Install scopes: `applications.commands`
   - Guild Install scopes: `applications.commands` and `bot`, with the permissions **View
     Channels**, **Send Messages** and **Embed Links**
4. Copy the **Install Link** from that page. Anyone can use it to add the bot to a server or to
   their own account.

Commands register themselves on the first start, and again only when a command changes.
New commands can take a minute to appear. If they do not show up, press `Ctrl+R` to reload
Discord.

## Running it on Debian 13

Debian 13 marks the system Python as externally managed, so a virtual environment is not
optional.

```bash
sudo apt update && sudo apt install -y python3 python3-venv git tmux sqlite3
git clone https://github.com/augy-studios/henrusian-dictionary.git
cd henrusian-dictionary/discord-bot

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env

chmod +x run.sh
tmux new -s henrusian-discord
./run.sh
```

Detach from tmux with `Ctrl+b` then `d`. Reattach with `tmux attach -t henrusian-discord`.

`run.sh` restarts the bot if it crashes, backing off up to a minute. It stops for good on
`Ctrl+C`, and also on a configuration problem, such as a missing value or a rejected token, so
a typo in `.env` does not become a restart loop. Logs go to `logs/bot.log`, rotated at 2 MB,
with five files kept.

### Updating

```bash
tmux attach -t henrusian-discord    # then Ctrl+C to stop the bot
git pull
. .venv/bin/activate && pip install -r requirements.txt
./run.sh                            # then Ctrl+b, d to detach
```

### Moving to another server

Copy `data/bot.db` along with the code. It holds every button token, every saved entry and
every subscription. Without it, old messages' buttons go inert and saved entries are gone.
Stop the bot first, or copy the `-wal` and `-shm` files that sit beside it too.

## Environment

| Variable | Required | What it is |
| --- | --- | --- |
| `DISCORD_TOKEN` | yes | The bot token from the Developer Portal |
| `SUPABASE_URL` | yes | The project URL, the same one the web app uses |
| `SUPABASE_SERVICE_KEY` | yes | Service role key. Server side only. Used to read the three catalogue tables, nothing else |
| `DONATION_URL` | yes | Where the donate button on `/help` points |

The bot refuses to start with a clear list if one is missing. The web app URL, the repository
URL, the default timezone and the tunables are constants at the top of `config.py`.

## Layout

```text
discord-bot/
├── bot.py               Entry point: client, command tree, sync, scheduler
├── config.py            Environment loading, constants and tunables
├── db.py                SQLite connection and helpers
├── schema.sql           Local schema, applied on every boot
├── ui.py                Embeds, the durable button class, the click dispatcher
├── views.py             Every screen, as pure functions of their parameters
├── run.sh               tmux launcher with restart on crash
├── commands/
│   ├── __init__.py      The canonical command list, used by /help and for registration
│   ├── general.py       /help /privacy
│   ├── lookup.py        /search /random /wotd /favs /stats
│   └── daily.py         /sub /unsub /settings and the delivery job
├── services/
│   ├── supabase.py      Read only PostgREST client
│   ├── entries.py       Catalogue cache, search, word of the day
│   ├── favourites.py    Saved entries
│   ├── subscriptions.py Daily word targets, times and jobs
│   ├── buttons.py       Button tokens and the action registry
│   ├── scheduler.py     SQLite job queue
│   └── external.py      Quote APIs with a fallback and caching
└── utils/
    └── text.py          Truncation, dates, escaping, the dash sanitiser
```

## How it works

**Catalogue.** Every entry from all three tables is fetched from Supabase, 1000 rows at a time,
and cached both in memory and in SQLite. Search runs locally, which makes it instant and keeps
the bot usable if Supabase has a bad minute. The cache refreshes every thirty minutes.

**Buttons.** Every action button's `custom_id` is `hd:<token>`. The action and its parameters
are rows in the `callbacks` table, along with who the message was made for. One discord.py
`DynamicItem`, registered at startup, matches that pattern, so a click on any message the bot
has ever sent reaches the dispatcher in `ui.py`, whichever process sent it. Tokens are reused
when the same button is drawn again, and never expire.

**Scheduling.** The `jobs` table is the queue. One worker wakes every fifteen seconds, claims
due rows in a single transaction, runs them, and either reschedules or deletes them. Failures
retry with exponential backoff up to five attempts, and locks older than ten minutes are
reclaimed, which is how a job interrupted by a crash gets picked up again. Daily deliveries are
recalculated in the subscriber's timezone each time they fire, so daylight saving needs no
special case. The queue is readable on the VPS:

```bash
sqlite3 data/bot.db "select kind, payload, run_at, attempts, last_error from jobs"
```

**Favourites.** These belong to your Discord account and live only in this bot's SQLite file.
They do not sync with the browser or with the Telegram bot, because the website's pairing flow
and the shared favourites table are built around Telegram accounts.

## Troubleshooting

**It exits straight away with a list of variables.** `.env` is missing or incomplete. Copy
`.env.example` and fill it in.

**"Discord rejected DISCORD_TOKEN".** The token was reset or pasted wrongly. Reset it on the
Bot page and paste it again.

**The commands do not appear.** Give it a minute and reload Discord with `Ctrl+R`. In a server,
check that the install included `applications.commands`, and that the server has not turned
off the bot's commands under Server Settings, Integrations.

**"The catalogue is still loading."** The first fetch has not finished, or Supabase is
unreachable. Check `logs/bot.log`.

**"This button is no longer available."** The token is not in the database, which normally
means `data/bot.db` was replaced or deleted, or the person erased their data. `/help` gives a
fresh screen.

**A channel's daily word stopped.** It failed three days running, usually because the bot lost
permission to post there. Fix the permissions and run `/sub channel:` again. `last_error` in
the jobs table and `logs/bot.log` say what happened.

**The daily word by DM was refused.** Discord only lets a bot DM people who allow it, usually
by sharing a server with the bot and allowing direct messages from that server's members.
Change that in the server's privacy settings and run `/sub` again.

## Licence

MIT, the same as the rest of the project.
