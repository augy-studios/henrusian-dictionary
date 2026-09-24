-- Local SQLite schema. Applied on every boot, so every statement is idempotent.

CREATE TABLE IF NOT EXISTS meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    discord_user_id  INTEGER PRIMARY KEY,
    username         TEXT,
    display_name     TEXT,
    timezone         TEXT,
    first_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Durable button tokens. A button's custom_id is only "hd:<token>", and the action and
-- its parameters live in this table. Rows are not expired, which is what keeps an old
-- message's buttons working forever, across any number of restarts.
--
-- user_id is who the message was rendered for. That person's clicks edit the message in
-- place. Anyone else, or anyone at all when user_id is NULL (a channel post), gets their
-- own private copy of the next screen instead.
CREATE TABLE IF NOT EXISTS callbacks (
    token         TEXT PRIMARY KEY,
    action        TEXT NOT NULL,
    params        TEXT NOT NULL DEFAULT '{}',
    user_id       INTEGER,
    use_count     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at  TEXT
);
CREATE INDEX IF NOT EXISTS callbacks_lookup ON callbacks (action, user_id);

-- Scheduler queue. Times are UTC, formatted YYYY-MM-DD HH:MM:SS.
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY,
    kind        TEXT    NOT NULL,
    payload     TEXT    NOT NULL DEFAULT '{}',
    run_at      TEXT    NOT NULL,
    interval_s  INTEGER,
    status      TEXT    NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    locked_at   TEXT,
    last_error  TEXT,
    dedupe_key  TEXT UNIQUE,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs (status, run_at);

-- Daily word deliveries. A target is either a person, delivered by DM, or a server
-- channel. owner_id is whoever last set it up.
CREATE TABLE IF NOT EXISTS subscriptions (
    target_type   TEXT    NOT NULL CHECK (target_type IN ('user', 'channel')),
    target_id     INTEGER NOT NULL,
    guild_id      INTEGER,
    owner_id      INTEGER NOT NULL,
    hour          INTEGER NOT NULL DEFAULT 8,
    timezone      TEXT    NOT NULL,
    include_quote INTEGER NOT NULL DEFAULT 1,
    active        INTEGER NOT NULL DEFAULT 1,
    failures      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (target_type, target_id)
);
CREATE INDEX IF NOT EXISTS subscriptions_guild ON subscriptions (guild_id);

-- Whole catalogue per tab, so search keeps working through a Supabase outage.
CREATE TABLE IF NOT EXISTS entry_cache (
    tab        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_cache (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- Saved entries. These belong to the Discord account and are not shared with the browser.
CREATE TABLE IF NOT EXISTS favourites (
    discord_user_id  INTEGER NOT NULL,
    tab              TEXT    NOT NULL,
    entry_id         TEXT    NOT NULL,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (discord_user_id, tab, entry_id)
);
