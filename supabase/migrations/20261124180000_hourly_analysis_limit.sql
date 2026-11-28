alter table public.user_ai_settings
    add column if not exists hourly_analysis_limit integer
        check (hourly_analysis_limit >= 0);
