-- Persistent provider stop. The flag used to live in a local file, which a restart or a second
-- server would lose. Run once in the SQL editor of project ivlmduwdkwgrxqxjjuyg only.
--
-- The row below starts PAUSED because the embedding provider last answered HTTP 429. This keeps
-- the current state; nothing is cleared. The app can set the flag (after another provider 429)
-- but only you can clear it, in the SQL editor, after checking the provider account:
--
--   update public.system_flags
--      set paused = false, reason = null, set_at = now(), set_by = 'owner'
--    where key = 'provider_pause';

create table if not exists public.system_flags (
    key text primary key,
    paused boolean not null default false,
    reason text,
    set_at timestamptz not null default now(),
    set_by text not null default 'system'
);

alter table public.system_flags enable row level security;
revoke all on public.system_flags from anon, authenticated;

insert into public.system_flags (key, paused, reason, set_by)
values (
    'provider_pause', true,
    'The embedding provider answered HTTP 429. Check the provider account, then clear this flag.',
    'migration'
)
on conflict (key) do nothing;
