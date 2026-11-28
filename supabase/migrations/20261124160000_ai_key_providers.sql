-- Keep existing encrypted Anthropic keys and allow the additional API providers.
alter table public.user_ai_settings
    drop constraint user_ai_settings_provider_check,
    add constraint user_ai_settings_provider_check
        check (provider in ('anthropic', 'openai', 'gemini', 'openrouter'));
