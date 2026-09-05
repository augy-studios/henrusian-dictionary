# Telegram Bot Specification

Working spec for a Telethon bot that fronts the Henrusian Dictionary. This document is the
agreed scope before any code is written. Open questions are collected in
[Questions before implementation](#questions-before-implementation) and should be answered first,
because two of them change the database design.

- **Bot username:** `@henrusian_bot`
- **Target directory:** `telegram-bot/`
- **Runtime host:** Debian 13 (trixie) VPS, launched inside tmux
- **Version control:** GitHub, so a README and a `.gitignore` ship with the bot
- **Delivery:** individual files, never a zip archive

## 1. Context from the existing project

The bot must behave like a Telegram front end for the same data the web app already serves, so it
reuses the site's vocabulary and its table layout rather than inventing new names.

| Piece | Where it lives now | What the bot takes from it |
| --- | --- | --- |
| Entry API | [main-site/api/entries.js](main-site/api/entries.js) | Tab keys `dict`, `idioms`, `names`; row shape `id`, `word`, `definition`, `created_at` |
| Supabase tables | `henrusian15_dict`, `henrusian15_idioms`, `henrusian15_names` | Read directly over PostgREST, same as the API does |
| Tab labels | [main-site/script.js:7-11](main-site/script.js#L7-L11) | "Words", "Idioms", "Names", singularised for entry tags |
| Search and sort | [main-site/script.js:223-241](main-site/script.js#L223-L241) | Case-insensitive substring match over `word` and `definition`; sort modes A to Z, Z to A, newest, oldest |
| Page size | [main-site/script.js:5](main-site/script.js#L5) | 50 on the web, reduced to 8 per message in Telegram |
| Favourites | [main-site/script.js:38](main-site/script.js#L38), `localStorage` key `hd_favourites` | The set of entry ids the `/link` flow has to sync |
| Junk row filter | [main-site/script.js:114-116](main-site/script.js#L114-L116) | Keep skipping the `Zz resume right here` placeholder row |
| Donation link | [main-site/index.html:69](main-site/index.html#L69) | Default value for `DONATION_URL` |

Two facts about the current site shape the design more than anything else:

1. **There is no portal account system yet.** Favourites live only in `localStorage`, per browser.
   `/link` therefore cannot link to something that exists, so this spec proposes the account and
   sync tables it needs. See [Question 1](#question-1-what-is-a-portal-account).
2. **There is no canonical site URL in the repo.** `vercel.json` pins the region but no domain, so
   the web app link needs one more value at deploy time. See
   [Question 2](#question-2-what-is-the-web-app-url).

## 2. Deliverables

```text
telegram-bot/
├── bot.py                     # Entry point: client, handler registration, scheduler start
├── config.py                  # Env var loading and validation, fail fast on missing values
├── db.py                      # SQLite connection, WAL setup, migration runner
├── schema.sql                 # Local SQLite schema, applied idempotently on boot
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md                  # What the bot is and how to use it
├── SETUP.md                   # BotFather setup, VPS install, tmux, updates
├── run.sh                     # tmux-friendly launcher with restart-on-crash loop
├── handlers/
│   ├── start.py               # /start, /help, /about, /donate, /privacy
│   ├── linking.py             # /link, /unlink, /linkstatus, /backupcodes, /recover
│   ├── search.py              # /search, /word, /idiom, /name, /random, /wotd, inline mode
│   ├── favourites.py          # /favourites, /export, star and unstar callbacks
│   ├── knowledge.py           # /quote, /fact
│   ├── subscriptions.py       # /subscribe, /unsubscribe, /settings
│   └── admin.py               # /broadcast, /health, owner only
├── services/
│   ├── supabase.py            # PostgREST client, paged reads, entry cache
│   ├── buttons.py             # Durable callback token store
│   ├── scheduler.py           # SQLite-backed job queue and worker
│   ├── backup_codes.py        # Generation, hashing, single-use redemption
│   └── external.py            # Third-party knowledge APIs with fallbacks
└── utils/
    ├── rich.py                # send_rich_message and edit_rich_message
    ├── text.py                # HTML escaping, dash sanitiser, truncation, pagination
    └── ratelimit.py           # Per-user cooldown, FloodWaitError backoff
```

Plus, in the main site, only if the linking design in this spec is approved:

```text
main-site/migrations/
├── 0001_portal_accounts.sql
├── 0002_favourites.sql
├── 0003_telegram_links.sql
└── 0004_telegram_backup_codes.sql
```

Every new table uses the existing `henrusian15_` prefix.

## 3. Environment variables

| Variable | Required | Notes |
| --- | --- | --- |
| `TELEGRAM_API_ID` | Yes | From my.telegram.org, Telethon needs it even for bot logins |
| `TELEGRAM_API_HASH` | Yes | Same source |
| `TELEGRAM_BOT_TOKEN` | Yes | From BotFather |
| `SUPABASE_URL` | Yes | Needed, because every entry lookup and every link record goes through Supabase |
| `SUPABASE_SERVICE_KEY` | Yes | Service role key, server side only, never logged |
| `DONATION_URL` | Yes | Defaults in docs to `https://donate.stripe.com/28o2akeAr3hv0DK6oo` |

Three more values are unavoidable and are not in the list from the prompt. Flagging them rather
than silently adding them:

| Variable | Why it is needed |
| --- | --- |
| `WEB_APP_URL` | The `/start` button has to point somewhere, and the repo does not record the domain |
| `BOT_OWNER_ID` | Gates `/broadcast` and `/health` so that only I can run them |
| `SQLITE_PATH` | Defaults to `data/bot.db`, overridable so the database can sit outside the repo |

If any of the three should instead be hardcoded, say so and they come out of the environment.

## 4. Command set

### 4.1 Naming rule

No command contains the bot's name, and no command is prefixed or suffixed with any form of
"henrusian", "hrd", or "dict". Commands are plain verbs and nouns. Telegram appends `@henrusian_bot`
to commands sent in groups, so the dispatcher strips a trailing `@username` before matching.

### 4.2 Confirmed commands

| Command | Behaviour |
| --- | --- |
| `/start` | Intro paragraph, the full command list, and a button row linking to the web app and the donation page |
| `/link` | Begin linking this Telegram account to a portal account so favourites sync |
| `/unlink` | Remove the link, with a confirm button, and state clearly what happens to synced favourites |

### 4.3 Suggested commands, for approval

Grouped by theme. Anything rejected simply gets dropped, and nothing else in the spec depends on
the full set surviving.

**Reading the dictionary.** This is the reason someone opens the bot at all.

| Command | Behaviour |
| --- | --- |
| `/search <term>` | Search all three catalogues at once, results paged 8 per message with Prev and Next buttons, plus a filter row for Words, Idioms, Names |
| `/word <term>` | Search the Words catalogue only |
| `/idiom <term>` | Search the Idioms catalogue only |
| `/name <term>` | Search the Names catalogue only |
| `/random` | One random entry, with a Roll again button |
| `/wotd` | Word of the day, deterministic per calendar date so everyone sees the same entry |
| `/stats` | Entry counts per catalogue and the newest addition date |

Bare text sent in a private chat is treated as `/search`, so users can just type a word.
Inline mode (`@henrusian_bot henlo`) is also worth enabling, since it lets people quote entries into
other chats, and it is a small amount of extra code once search exists.

**Favourites.** Only meaningful once linking works.

| Command | Behaviour |
| --- | --- |
| `/favourites` | List the linked account's favourites, paged, each row with an unstar button |
| `/export` | Send favourites back as a JSON file, the same shape the web app stores |

Every entry card also carries a star button, which is the primary way favourites get added.

**Account recovery.** The 2FA backup code feature from the prompt.

| Command | Behaviour |
| --- | --- |
| `/linkstatus` | Show whether this chat is linked, to which account, since when, and how many unused backup codes remain |
| `/backupcodes` | Request ten fresh single-use codes. The bot sends an approval notification first, and only an approval generates them, revokes the previous set, and shows the codes once |
| `/recover <code>` | Redeem a backup code from a different Telegram account to move the link to it |

**Scheduled content.** The reason the job queue exists.

| Command | Behaviour |
| --- | --- |
| `/subscribe` | Opt in to a daily word of the day, with buttons to choose the delivery hour |
| `/unsubscribe` | Stop the daily message |
| `/settings` | Timezone, delivery hour, and whether the daily message includes a quote |

**Knowledge base extras.** These are the commands that call third-party APIs.

| Command | Behaviour |
| --- | --- |
| `/quote` | A random quote, with a New quote button |
| `/fact` | A random trivia fact, with a New fact button |

**Housekeeping.**

| Command | Behaviour |
| --- | --- |
| `/help` | Same command list as `/start`, without the intro |
| `/about` | What the project is, who maintains it, the licence, and a link to the repo |
| `/donate` | The donation link on its own |
| `/privacy` | Exactly what is stored, where, and how to delete it |
| `/cancel` | Abandon any multi-step flow in progress |

**Owner only,** hidden from the BotFather command list.

| Command | Behaviour |
| --- | --- |
| `/broadcast <text>` | Send a message to every subscriber, queued through the scheduler so it paces itself |
| `/health` | Uptime, SQLite size, pending job count, cache age, last Supabase error |

### 4.4 BotFather command list

The list registered with BotFather, in this order, with no branding in any description:

```text
start - What this bot does and everything it can do
search - Search words, idioms and names
word - Look up a word
idiom - Look up an idiom
name - Look up a name
random - Show a random entry
wotd - Word of the day
favourites - Show your saved entries
export - Download your favourites as a file
link - Link this account to sync your favourites
unlink - Remove the link
linkstatus - Check whether this account is linked
backupcodes - Create new single-use recovery codes
recover - Use a recovery code on this account
subscribe - Get a word of the day every morning
unsubscribe - Stop the daily word
settings - Timezone and delivery preferences
quote - A random quote
fact - A random fact
stats - Catalogue sizes and latest additions
help - Show the command list
about - About the project
donate - Support the project
privacy - What data is stored
cancel - Cancel the current step
```

## 5. Message style

The prompt asks for `sendRichMessage`. Telethon has no such method, so the bot gets a helper of
that name in [utils/rich.py](telegram-bot/utils/rich.py) wrapping `client.send_message`, and every
handler uses it instead of calling Telethon directly. The wrapper always applies:

- HTML parse mode, with all interpolated database text escaped first
- A bold title line, then the body, then a muted footer line where one is useful
- Buttons attached from a single builder so callback tokens are always persisted (section 7)
- `link_preview=False` unless a card is genuinely wanted
- Automatic splitting at 4096 characters on a paragraph boundary
- `FloodWaitError` caught, awaited, and retried once

`edit_rich_message` is the same contract for callback edits, so paging never posts a new message.

Copy rules, enforced by a sanitiser in [utils/text.py](telegram-bot/utils/text.py) that runs over
every outbound string:

- No em dashes and no en dashes. Sentences are rephrased with commas, semicolons, parentheses, or
  split into two sentences, so the result reads naturally rather than looking like a dash was
  swapped for a comma.
- Ranges are written with "to", as in "8 to 16 entries".
- British spelling, to match "favourites" in the existing code.
- No emoji in body text. Icons appear on buttons only, sparingly.
- Errors say what happened and what to try next, never a bare stack trace or code.

The sanitiser is a safety net for copy that slips through, not a licence to write dashes and let it
rewrite them. Any replacement it makes is logged at debug level so bad copy gets found and fixed.

## 6. Linking design

Since there is no portal login today, this is the proposal. It assumes Supabase Auth, which is
already available in the project's Supabase instance, becomes the portal account system.

```text
User in Telegram              Bot                    Supabase                 Web app
      |                        |                         |                        |
      | /link                  |                         |                        |
      |----------------------->|                         |                        |
      |                        | insert pairing code     |                        |
      |                        |------------------------>|                        |
      | code + deep link       |                         |                        |
      |<-----------------------|                         |                        |
      |                                                                           |
      | opens link, signs in, confirms the code                                   |
      |-------------------------------------------------------------------------->|
      |                        |                         | link row created       |
      |                        |<------------------------|                        |
      | "Linked" push          |                         |                        |
      |<-----------------------|                         |                        |
```

Details:

1. `/link` mints a six character code, uppercase Crockford base32, stored with the Telegram user id
   and a ten minute expiry. The reply shows the code and a button to `WEB_APP_URL/link?code=XXXXXX`.
2. The web app asks the visitor to sign in, then confirms the code. On confirmation a row appears in
   `henrusian15_telegram_links` and the pairing code is marked used.
3. The bot polls for confirmation through a scheduled job, so the "you are linked" message arrives
   without the user returning to Telegram.
4. First sync merges both sides by union, since a merge cannot lose a favourite. From then on the
   bot writes favourites straight to `henrusian15_favourites` and the web app reads the same table.
5. `/unlink` deletes the link row but keeps the favourites on the account, and the reply says so
   plainly.

One Telegram account maps to at most one portal account, and one portal account to at most one
Telegram account. A second `/link` from an already linked account is refused with an explanation
rather than silently rebinding.

### 2FA backup codes

The purpose is recovery when Telegram itself is unreachable, so the codes cannot live only in the
bot's SQLite file. They go in Supabase, where the web app can verify them too.

- Ten codes per account, format `XXXX-XXXX-XXXX`, Crockford base32, generated with `secrets`.
- **Approval first.** Asking for codes never issues them. The request is recorded, the bot sends its
  own notification with Approve and Reject buttons, and only an approval generates the set, revokes
  the previous one, and reveals the codes. A request expires after ten minutes, asking again
  supersedes the previous request, an approval cannot be replayed, and nobody but the requesting
  Telegram account can act on it. Rejecting changes nothing, which is what makes an unexpected
  request a useful warning rather than a fait accompli.
- Stored as a SHA-256 digest, never in plaintext, and shown exactly once, immediately after
  approval. The message warns that they will not be shown again.
- On hashing, a deviation from the first draft of this spec: a per row salt would make redemption a
  scan across every unused code in the table, since the digest could not be indexed. A code instead
  carries 60 bits of entropy (12 characters) and is stored as a plain digest with a unique index.
  Single use plus the lockout below closes the online path, and 60 bits closes the offline one.
- Single use. Redemption sets `used_at` inside a conditional update so a code cannot be spent twice
  even under a race.
- `/recover <code>` from a new Telegram account moves the link to that account and revokes the old
  one. The old account gets a notice if it is still reachable.
- Generating a new set marks every unused code from the previous set as revoked.
- Five failed redemptions in an hour locks recovery on the account for an hour, and the message says
  when to try again.
- Codes are also redeemable on the web app, which is the whole point: if Telegram is gone, the user
  still needs a way in. That endpoint is a small addition to `main-site/api/` and is listed as
  [Question 4](#question-4-should-the-web-side-endpoints-be-in-scope).

## 7. Persistent interaction buttons

Telegram callback data is capped at 64 bytes, and any scheme that encodes state into that string
breaks as soon as the state grows. The requirement is that buttons keep working forever, including
across restarts, so callback data is a short opaque token and the meaning lives in SQLite.

- Every button is built through `services/buttons.py`, which inserts an `action` plus a JSON
  `params` blob and returns a token of roughly 16 characters. That token is the callback data.
- On callback, the token is looked up, the action is dispatched, and unknown tokens get a friendly
  "this button is no longer available" answer instead of silence.
- Tokens do not expire. A `use_count` and `last_used_at` are recorded so genuinely dead rows can be
  pruned by a maintenance job much later, and pruning is opt in rather than automatic.
- Rows also carry the owning `chat_id` and `user_id`, so a button in someone's private chat cannot be
  actioned by another user who somehow obtains the token.
- Rendered views are recorded in `ui_views`, keyed by chat and message id, holding the view name and
  its parameters. After a restart the bot can re-render or repair a message it no longer holds in
  memory, which is what makes an old paged result still pageable weeks later.

## 8. Local SQLite database

One file, `data/bot.db`, opened with `journal_mode=WAL`, `busy_timeout=5000`, and
`foreign_keys=ON`. Schema applied from `schema.sql` on every boot with `CREATE TABLE IF NOT EXISTS`,
and a `schema_version` row for future migrations.

| Table | Purpose |
| --- | --- |
| `users` | Telegram user id, first seen, last seen, locale, timezone, and cached link state |
| `callbacks` | Durable button tokens: token, action, params JSON, chat id, user id, counters |
| `ui_views` | Rendered message state: chat id, message id, view name, params JSON, updated at |
| `jobs` | Scheduler queue, described below |
| `subscriptions` | Chat id, delivery hour, timezone, whether quotes are included, active flag |
| `entry_cache` | Cached catalogue rows per tab with a fetched-at stamp, so search works during a Supabase outage |
| `api_cache` | Cached third-party responses keyed by endpoint, with a TTL |
| `ratelimits` | Per user and per command counters for cooldowns |
| `link_attempts` | Local record of pairing attempts, for rate limiting and for `/health` |
| `outbox` | Broadcast fan-out rows, so a broadcast survives a restart mid-send |

Nothing sensitive is stored locally. Backup code hashes and link records live in Supabase, and the
local `users` row holds only a cached portal id.

## 9. Scheduling

No APScheduler and no cron. A single asyncio worker polls the `jobs` table, which makes the queue
durable and inspectable with `sqlite3` on the VPS.

```sql
CREATE TABLE IF NOT EXISTS jobs (
  id           INTEGER PRIMARY KEY,
  kind         TEXT    NOT NULL,
  payload      TEXT    NOT NULL DEFAULT '{}',
  run_at       TEXT    NOT NULL,              -- ISO 8601 UTC
  interval_s   INTEGER,                       -- set for repeating jobs
  status       TEXT    NOT NULL DEFAULT 'pending',
  attempts     INTEGER NOT NULL DEFAULT 0,
  locked_at    TEXT,
  last_error   TEXT,
  created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
  dedupe_key   TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs (status, run_at);
```

- The worker wakes every 15 seconds, claims due rows in one transaction by setting `locked_at`, runs
  them, then either reschedules by `interval_s` or marks them done.
- Failures retry with exponential backoff, capped at five attempts, and the last error is kept for
  `/health`.
- `dedupe_key` prevents a duplicate daily job when a restart lands on the same minute.
- A stale lock older than ten minutes is reclaimed, which is how a job interrupted by a crash gets
  picked up again.
- Job kinds: `daily_wotd`, `link_poll`, `refresh_entry_cache`, `broadcast_chunk`, `prune_api_cache`.
- All times are stored UTC. Per-user delivery hours are converted using the subscriber's timezone at
  send time, so daylight saving changes need no migration.

## 10. Third-party knowledge APIs

All open source or openly documented, all free, none needing a key. Every call goes through
`services/external.py`, which caches into `api_cache`, times out at five seconds, and falls back in
order. If everything fails, the command says the source is unavailable and suggests trying later.

| Content | Primary | Fallback | Licence and source |
| --- | --- | --- | --- |
| Quotes | `https://api.quotable.io/random` | `https://zenquotes.io/api/random` | Quotable is MIT, `github.com/lukePeavey/quotable` |
| Facts | `https://uselessfacts.jsph.pl/api/v2/facts/random` | `http://numbersapi.com/random/trivia?json` | Useless Facts is open source, `github.com/Sv443/useless-facts` |
| English glosses | `https://api.dictionaryapi.dev/api/v2/entries/en/<word>` | none, feature degrades quietly | Free Dictionary API, `github.com/meetDeveloper/freeDictionaryAPI` |

The English gloss lookup is optional and only used to enrich a definition when a Henrusian entry
maps to a single English word. Say the word if that is unwanted, and the dependency disappears.

Quotable has had intermittent downtime historically, which is exactly why a fallback and a cache are
specified rather than a single call.

## 11. Supabase migrations

Created in `main-site/migrations/`, for me to apply by hand in the Supabase SQL editor. Each file is
idempotent and carries its own row level security policies. Column lists here are the intent, and
the final SQL lands with the code.

**`0001_portal_accounts.sql`** creates `henrusian15_profiles`, one row per Supabase Auth user,
keyed by `id uuid references auth.users`, with `display_name` and `created_at`. Skipped entirely if
a portal account system already exists somewhere I have not seen.

**`0002_favourites.sql`** creates `henrusian15_favourites` with `user_id`, `entry_id`, `tab`
constrained to `dict`, `idioms`, `names`, and `created_at`. Unique on `(user_id, entry_id, tab)`.
This is the table the web app's `localStorage` favourites migrate into.

**`0003_telegram_links.sql`** creates two tables. `henrusian15_telegram_links` holds `user_id`,
`telegram_user_id` unique, `telegram_username`, `linked_at`, `revoked_at`, and `last_seen_at`.
`henrusian15_telegram_link_codes` holds `code` unique, `telegram_user_id`, `expires_at`, `used_at`,
and `created_at`, with an index on `expires_at` for cleanup.

**`0004_telegram_backup_codes.sql`** creates `henrusian15_telegram_backup_codes` with `user_id`,
`code_hash`, `salt`, `used_at`, `revoked_at`, `created_at`, and a partial index on unused rows, plus
`henrusian15_telegram_recovery_attempts` for the lockout counter.

RLS in every case: the service key bypasses it for the bot, and authenticated users can read and
write only rows where `user_id = auth.uid()`. The anon key gets no access to any of these tables.

## 12. Deployment on Debian 13

Debian 13 ships Python 3.13 and marks the system interpreter as externally managed, so a virtual
environment is mandatory and the README says so up front.

```bash
sudo apt update && sudo apt install -y python3 python3-venv git tmux sqlite3
git clone <repo> && cd henrusian-dictionary/telegram-bot
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env
tmux new -s henrusian-bot
./run.sh
```

Detach with `Ctrl+b` then `d`, reattach with `tmux attach -t henrusian-bot`.

`run.sh` activates the venv, restarts the bot on unexpected exit with a short delay, and logs to
`logs/bot.log` with rotation so a long-lived tmux pane does not become the only record. Because tmux
does not survive a reboot, SETUP.md also documents an optional systemd user unit as an alternative,
clearly marked optional so tmux stays the default path.

Dependencies stay minimal: `telethon`, `python-dotenv`, `httpx`. SQLite comes from the standard
library, and there is no ORM.

`.gitignore` covers `.env`, `*.session`, `*.session-journal`, `data/`, `logs/`, `__pycache__/`,
`.venv/`, and `*.db*`. The Telethon session file and the SQLite database must never reach GitHub.

## 13. Documentation deliverables

**README.md** explains what the bot is, the commands table, how linking and backup codes work from
a user's point of view, the environment variables, the install and tmux steps, the file layout, a
short troubleshooting list, and the licence.

**SETUP.md** covers the operator path end to end:

1. Getting `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from my.telegram.org
2. Creating the bot in BotFather and choosing `henrusian_bot` as the username
3. `/setdescription`, the text shown on an empty chat before the first message
4. `/setabouttext`, the short profile blurb
5. `/setuserpic`, using `main-site/hrd-512.png`
6. `/setcommands`, with the block from section 4.4 ready to paste
7. `/setinline` and the inline placeholder text, if inline mode is approved
8. `/setprivacy`, and why group privacy mode should stay enabled
9. `/setjoingroups`, and whether the bot is allowed into groups at all
10. Applying the four Supabase migrations in order
11. Filling `.env`, first run, verifying with `/health`
12. Updating the bot later, and rotating the token if it leaks

Both documents follow the same copy rules as the bot: no em dashes, no en dashes, British spelling.

## Questions before implementation

### Question 1: what is a "portal account"?

Favourites are `localStorage` only today, and no login exists anywhere in `main-site/`. Options:

- **A. Supabase Auth**, which the migrations above assume. It exists in the project already, and
  email plus magic link needs no extra service. This is my recommendation.
- **B. A portal that already exists elsewhere,** outside this repo. If so, I need its base URL and
  how the bot verifies an account there.
- **C. No portal at all,** in which case `/link` becomes a Telegram-only account: favourites are
  stored against the Telegram user id, and the web app gains a "sign in with a code from the bot"
  affordance later.

### Question 2: what is the web app URL?

Nothing in the repo records the production domain. The `/start` button and the `/link` deep link
both need it. Is it a domain like `henrusian.uwuapps.org`, or the raw Vercel URL?

### Question 3: which suggested commands stay?

Section 4.3 lists 21 commands beyond the three that are confirmed. Trimming now is cheaper than
building all of them. My suggested minimum: `/search`, `/word`, `/idiom`, `/name`, `/random`,
`/wotd`, `/favourites`, `/help`, `/about`, `/donate`, `/privacy`, `/linkstatus`, `/backupcodes`,
`/recover`, `/cancel`. Everything else is a nice extra.

### Question 4: should the web side endpoints be in scope?

Linking and web-side backup code redemption both need a small amount of work in `main-site/api/`,
roughly a `link/confirm` endpoint, a `favourites` endpoint, and a `recover` endpoint. This spec
covers only the bot plus the SQL migrations. Should the serverless functions and the sign-in UI be
part of the same piece of work, or a separate task after the bot is running?

### Question 5: groups, or private chats only?

Private chats only is simpler and safer, since linking involves codes that should not be pasted into
a group. If groups are wanted, the read-only commands work there and the account commands reply with
a nudge to continue in a private chat.

### Question 6: how should the daily word be chosen?

`/wotd` and the daily subscription can share a deterministic pick, seeded by the date so everyone
sees the same entry and the archive is reproducible. The alternative is a per-user rotation that
never repeats a word for that user until the catalogue is exhausted. Deterministic and shared is my
recommendation, since it is simpler and it makes the daily message something people can talk about.

### Question 7: how many backup codes, and where are they shown?

Ten single-use codes is the common default and what this spec assumes. If a printable or
downloadable file is preferred over an on-screen list, the bot can send them as a `.txt` document
instead, though a message that can be forwarded is arguably worse for security than one that has to
be copied.
