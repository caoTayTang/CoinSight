-- Signed-in users (Supabase: Google or GitHub), so owners can see who uses the app in the admin console.
-- The run log still keys everything by user_key; this is the only table that maps a key to an email.
-- Read only through /v1/admin/* (owners). Anonymous visitors are never stored here.
create table if not exists meta.app_user (
    user_key text primary key,
    email text not null,
    provider text,
    first_seen timestamptz not null default now(),
    last_seen timestamptz not null default now()
);
