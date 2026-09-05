-- 0003 Backup codes
--
-- Two factor backup codes, for the case where Telegram is unreachable. With no accounts in
-- the picture, what a code protects is the collection: it releases every browser paired with
-- a Telegram account that can no longer be reached, and it can move that collection onto a
-- new Telegram account from the bot.
--
-- Codes are created on the website, never in Telegram, and creation is never immediate. A
-- request lands as pending, the bot asks the Telegram account to approve it, and only then may
-- the website reveal the set. Nothing is revoked until the new codes are shown.
--
-- On hashing: a code carries 60 bits of entropy (12 Crockford base32 characters) and is stored
-- as a SHA-256 digest of `pepper:code`, so it can be looked up by index. A per row salt would
-- force a scan across every unused code on every redemption. Single use, the pepper, and the
-- attempt log below cover the rest.

create table if not exists henrusian15_sync_backup_codes (
    id                  bigint generated always as identity primary key,
    telegram_user_id    bigint not null,
    code_hash           text   not null unique,
    used_at             timestamptz,
    used_by_telegram_id bigint,
    revoked_at          timestamptz,
    created_at          timestamptz not null default now()
);

create index if not exists henrusian15_sync_backup_codes_live
    on henrusian15_sync_backup_codes (telegram_user_id)
    where used_at is null and revoked_at is null;


-- Approval requests. Lifecycle: pending, then approved, consumed, rejected, expired, or
-- superseded. device_id records which browser asked, which is worth showing in the prompt
-- when several are paired.
create table if not exists henrusian15_sync_code_requests (
    id               bigint generated always as identity primary key,
    telegram_user_id bigint not null,
    device_id        text,
    device_label     text,
    status           text   not null default 'pending',
    requested_at     timestamptz not null default now(),
    expires_at       timestamptz not null,
    notified_at      timestamptz,
    resolved_at      timestamptz,
    consumed_at      timestamptz
);

create index if not exists henrusian15_sync_code_requests_pending
    on henrusian15_sync_code_requests (status, requested_at)
    where status = 'pending';

create index if not exists henrusian15_sync_code_requests_owner
    on henrusian15_sync_code_requests (telegram_user_id, requested_at desc);


-- Every redemption attempt, from the bot and from the website alike, so a lockout cannot be
-- sidestepped by switching Telegram account or client.
--
-- telegram_user_id is the collection the attempt was aimed at, and is null when the attempt
-- cannot be attributed, which is the case for a code that matches nothing at all. Attempts on
-- a code that exists but is spent or revoked, and every attempt made from the website, do
-- carry it.
create table if not exists henrusian15_sync_recovery_attempts (
    id                 bigint generated always as identity primary key,
    telegram_user_id   bigint,
    by_telegram_user_id bigint,
    device_id          text,
    source             text not null default 'bot',
    succeeded          boolean not null default false,
    created_at         timestamptz not null default now()
);

create index if not exists henrusian15_sync_attempts_owner
    on henrusian15_sync_recovery_attempts (telegram_user_id, created_at desc);

create index if not exists henrusian15_sync_attempts_device
    on henrusian15_sync_recovery_attempts (device_id, created_at desc);

alter table henrusian15_sync_backup_codes enable row level security;
alter table henrusian15_sync_code_requests enable row level security;
alter table henrusian15_sync_recovery_attempts enable row level security;
-- No policies on any of the three. Only the service key touches them.
