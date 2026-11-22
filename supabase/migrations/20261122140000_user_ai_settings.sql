-- Per-practitioner AI settings (bring-your-own API key).
-- The key is stored ENCRYPTED by the backend (Fernet, server-side secret). This table has RLS
-- enabled and NO policies, so the browser (anon/authenticated roles) can never read it, not even
-- the ciphertext. Only the FastAPI backend (service role) touches it, always filtered by user.

create table public.user_ai_settings (
    practitioner_id uuid primary key references auth.users (id) on delete cascade,
    provider text not null default 'anthropic' check (provider in ('anthropic')),
    encrypted_api_key text not null,
    key_last4 text not null check (char_length(key_last4) = 4),
    model text not null,
    validated_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.user_ai_settings enable row level security;

revoke all on public.user_ai_settings from anon, authenticated;
