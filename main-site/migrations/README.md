# Migrations

SQL for the Supabase project behind the Henrusian Dictionary. Paste each file into the
Supabase SQL editor and run them in order. Every file is idempotent, so running one twice is
harmless.

| File | What it adds |
| --- | --- |
| `0001_sync_links.sql` | `henrusian15_sync_links` and `henrusian15_sync_tokens`, the pairings between browsers and a Telegram account |
| `0002_sync_favourites.sql` | `henrusian15_sync_favourites`, the collection every paired browser shares |
| `0003_backup_codes.sql` | `henrusian15_sync_backup_codes`, `henrusian15_sync_code_requests` and `henrusian15_sync_recovery_attempts` |

Every table uses the existing `henrusian15_` prefix, matching `henrusian15_dict`,
`henrusian15_idioms` and `henrusian15_names`.

## What these are for

The Telegram bot exists to share favourites between a browser and a Telegram account. There
are no accounts, no email addresses and no sessions anywhere in this design.

- A **browser** identifies itself with a device id and a device secret that it generates and
  keeps in `localStorage`. Only the hash of the secret is stored.
- A **link** pairs one device with one Telegram account. A browser has one live pairing at a
  time, while a Telegram account may have as many as it likes, which is what lets a laptop,
  a phone and a desktop share one collection.
- **Favourites** belong to the Telegram account, not to any one pairing, and live on the
  server only while at least one pairing exists. Before that the browser keeps them in
  `localStorage` and the bot keeps its own in SQLite. Pairing merges both by union, so
  nothing is lost and nothing is duplicated. When the last pairing goes, each side keeps its
  own copy and the shared rows are deleted.
- **Backup codes** protect the collection, for the case where Telegram cannot be reached.

## Row level security

Every table has row level security enabled and **no policies at all**. That is deliberate:
none of this is ever read from the browser. The site's own API routes hold the service key,
which bypasses row level security, and the anon key a visitor holds can see nothing here.

## How linking flows

```text
Browser                    Site API                 Supabase                 Bot
   |                          |                        |                       |
   | Sync with Telegram       |                        |                       |
   |------------------------->|  insert sync_tokens    |                       |
   |                          |----------------------->|                       |
   |  token + t.me link       |                        |                       |
   |<-------------------------|                        |                       |
   |                                                                           |
   | opens https://t.me/henrusian_bot?start=<token>, taps Start                |
   |-------------------------------------------------------------------------->|
   |                          |                        |  claim token, insert  |
   |                          |                        |  link, merge          |
   |                          |                        |<----------------------|
   | GET /api/link (poll)     |                        |                       |
   |------------------------->|  linked, favourites    |                       |
   |<-------------------------|                        |                       |
```

The bot never mints a pairing token, because only the browser knows which device is being
paired. The token carries the browser's existing favourites so the merge happens in one step.

Pairing a second browser runs exactly the same flow. It adds a row to
`henrusian15_sync_links` and merges that browser's favourites into the collection the first
one already shares.

## How recovery codes flow

Creating codes is a website action and is never immediate.

1. Any paired browser asks for a set. A row lands in `henrusian15_sync_code_requests` as
   `pending`, recording which browser asked.
2. The bot polls for pending rows and asks the linked Telegram account to approve.
3. Approving sets the row to `approved`. Rejecting or ignoring it changes nothing at all.
4. The next poll from the browser claims the reveal, generates ten codes, revokes any unused
   older ones, and shows the new set once.

The codes are shown on the website rather than in Telegram, so they never sit in a chat
history. The bot cannot generate or display one.

## Hashing

Codes are stored as `sha256(pepper + ":" + normalised_code)`. Both the bot and the site
implement this identically, so `BACKUP_CODE_PEPPER` **must be the same value in both
environments**. Normalising uppercases the code, strips anything that is not a letter or
digit, and maps the ambiguous characters `I` and `L` to `1`, `O` to `0`, and `U` to `1`.

A per row salt was considered and rejected: it would make redemption a scan across every
unused code, since the digest could not be indexed. A code carries 60 bits of entropy instead,
and single use plus the attempt log covers online guessing.

## Environment

The site needs these in the Vercel project:

| Variable | Why |
| --- | --- |
| `SUPABASE_URL` | Already needed by `/api/entries` |
| `SUPABASE_SERVICE_KEY` | Already needed by `/api/entries`. Server side only |
| `BACKUP_CODE_PEPPER` | Must match the bot |
| `TELEGRAM_BOT_USERNAME` | Builds the `t.me` link. Defaults to `henrusian_bot` |
| `WEB_APP_URL` | Optional, used when building absolute links |

## Cleaning up

Nothing here grows without bound, but two tables accumulate rows that stop mattering:

```sql
-- Pairing tokens that were never used
delete from henrusian15_sync_tokens where expires_at < now() - interval '7 days';

-- Settled code requests
delete from henrusian15_sync_code_requests
where status <> 'pending' and requested_at < now() - interval '90 days';

-- Old attempt log entries, kept long enough to be useful for the lockout
delete from henrusian15_sync_recovery_attempts where created_at < now() - interval '90 days';
```

Revoked rows in `henrusian15_sync_links` are worth keeping: the bot reads them to work out who
held a pairing before a recovery code moved it.
