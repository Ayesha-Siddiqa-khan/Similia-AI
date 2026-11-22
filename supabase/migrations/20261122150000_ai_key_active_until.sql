-- Saved AI keys are only ACTIVE for a chosen period (1 day by default). After active_until the
-- key stays stored (encrypted) but is paused until the doctor turns it on again.
-- Run after 20261122140000_user_ai_settings.sql.

alter table public.user_ai_settings
    add column if not exists active_until timestamptz not null default (now() + interval '1 day');
