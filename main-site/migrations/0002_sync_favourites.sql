-- 0002 Shared favourites
--
-- The collection belongs to the Telegram account, not to any one pairing, which is what lets
-- several browsers share it. Linking a second browser adds a link row and merges that
-- browser's favourites into the same collection.
--
-- Favourites only live on the server while at least one link exists. Before that, the browser
-- keeps them in localStorage and the bot keeps them in its own SQLite file. Linking merges
-- both sets by union, so nothing is lost and nothing is duplicated. When the last link goes,
-- these rows are deleted, after each side has taken its own copy.

create table if not exists henrusian15_sync_favourites (
    id               bigint generated always as identity primary key,
    telegram_user_id bigint not null,
    tab              text   not null check (tab in ('dict', 'idioms', 'names')),
    entry_id         text   not null,
    created_at       timestamptz not null default now(),
    unique (telegram_user_id, tab, entry_id)
);

create index if not exists henrusian15_sync_favourites_owner
    on henrusian15_sync_favourites (telegram_user_id);

alter table henrusian15_sync_favourites enable row level security;
-- No policies. Only the service key touches this table.
