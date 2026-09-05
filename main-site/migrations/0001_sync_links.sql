-- 0001 Sync links
--
-- There are no accounts here, and no sign in. A link pairs one browser with one Telegram
-- account so that favourites can be shared between them.
--
-- One Telegram account may pair with as many browsers as it likes: a laptop, a phone, a
-- desktop at work. They all share the same collection of favourites. A browser, on the other
-- hand, belongs to at most one Telegram account at a time, which is what the partial unique
-- index below enforces.
--
-- The browser identifies itself with a device id and a device secret it generates and keeps
-- in localStorage. Only the hash of the secret is stored, so a leaked table cannot be used to
-- impersonate a device.
--
-- Apply in the Supabase SQL editor. Safe to run more than once.

create table if not exists henrusian15_sync_links (
    id                 bigint generated always as identity primary key,
    device_id          text   not null,
    device_secret_hash text   not null,
    device_label       text,
    telegram_user_id   bigint not null,
    telegram_username  text,
    linked_at          timestamptz not null default now(),
    last_seen_at       timestamptz,
    revoked_at         timestamptz
);

-- One live link per device. Revoked rows are kept for history, so the index is partial.
create unique index if not exists henrusian15_sync_links_live_device
    on henrusian15_sync_links (device_id)
    where revoked_at is null;

-- Deliberately not unique on telegram_user_id: that is what allows several browsers.
create index if not exists henrusian15_sync_links_telegram
    on henrusian15_sync_links (telegram_user_id)
    where revoked_at is null;


-- Short lived pairing tokens. The website creates one, then sends the visitor to
-- https://t.me/henrusian_bot?start=<token>, and tapping Start hands the token to the bot,
-- which is what completes the pairing.
--
-- The favourites the browser already had travel with the token, so the bot can merge both
-- sides in one go the moment the link is made.
create table if not exists henrusian15_sync_tokens (
    token              text primary key,
    device_id          text not null,
    device_secret_hash text not null,
    device_label       text,
    favourites         jsonb not null default '[]'::jsonb,
    expires_at         timestamptz not null,
    used_at            timestamptz,
    used_by            bigint,
    created_at         timestamptz not null default now()
);

create index if not exists henrusian15_sync_tokens_live
    on henrusian15_sync_tokens (expires_at)
    where used_at is null;

-- Neither table is ever read by the browser directly. Every call goes through the site's own
-- API routes, which hold the service key, so row level security is on with no policies at
-- all: the anon key can see nothing here.
alter table henrusian15_sync_links enable row level security;
alter table henrusian15_sync_tokens enable row level security;
