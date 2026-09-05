-- Local SQLite schema. Applied on every boot, so every statement is idempotent.
-- Nothing sensitive belongs here. Backup code hashes and link records live in
-- Supabase, and this file holds only a cached copy of the link state.

CREATE TABLE IF NOT EXISTS meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    telegram_user_id INTEGER PRIMARY KEY,
    username         TEXT,
    first_name       TEXT,
    timezone         TEXT,
    linked           INTEGER NOT NULL DEFAULT 0,  -- cached from Supabase
    linked_at        TEXT,
    pending          TEXT,             -- JSON for a multi-step flow in progress
    first_seen_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Durable button tokens. Callback data is capped at 64 bytes by Telegram, so the
-- data is a short opaque token and the meaning lives in this table. Rows are not
-- expired, which is what keeps an old message's buttons working forever.
CREATE TABLE IF NOT EXISTS callbacks (
    token         TEXT PRIMARY KEY,
    action        TEXT NOT NULL,
    params        TEXT NOT NULL DEFAULT '{}',
    chat_id       INTEGER,
    user_id       INTEGER,
    use_count     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at  TEXT
);
CREATE INDEX IF NOT EXISTS callbacks_action ON callbacks (action);
CREATE INDEX IF NOT EXISTS callbacks_chat ON callbacks (chat_id);

-- What is currently rendered in a given message, so a restart can still repair or
-- re-render a view the process no longer remembers.
CREATE TABLE IF NOT EXISTS ui_views (
    chat_id    INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    view       TEXT    NOT NULL,
    params     TEXT    NOT NULL DEFAULT '{}',
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (chat_id, message_id)
);

-- Scheduler queue. Times are ISO 8601 in UTC.
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

CREATE TABLE IF NOT EXISTS subscriptions (
    chat_id       INTEGER PRIMARY KEY,
    user_id       INTEGER NOT NULL,
    hour          INTEGER NOT NULL DEFAULT 8,
    timezone      TEXT    NOT NULL,
    include_quote INTEGER NOT NULL DEFAULT 1,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

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

-- Favourites for anyone who has not linked a device yet. On linking these merge with
-- whatever the browser had, by union, so neither side loses one and none are stored
-- twice. On unlinking the shared set is copied back here before it is deleted.
CREATE TABLE IF NOT EXISTS favourites_local (
    telegram_user_id INTEGER NOT NULL,
    tab              TEXT    NOT NULL,
    entry_id         TEXT    NOT NULL,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (telegram_user_id, tab, entry_id)
);

CREATE TABLE IF NOT EXISTS ratelimits (
    user_id   INTEGER NOT NULL,
    key       TEXT    NOT NULL,
    hits      INTEGER NOT NULL DEFAULT 0,
    window_at TEXT    NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS link_attempts (
    id               INTEGER PRIMARY KEY,
    telegram_user_id INTEGER NOT NULL,
    code             TEXT,
    outcome          TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Broadcast fan-out, so a send that is interrupted resumes instead of restarting.
CREATE TABLE IF NOT EXISTS outbox (
    id         INTEGER PRIMARY KEY,
    batch      TEXT    NOT NULL,
    chat_id    INTEGER NOT NULL,
    body       TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'pending',
    error      TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    sent_at    TEXT
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox (batch, status);
