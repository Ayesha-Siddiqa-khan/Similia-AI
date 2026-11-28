alter table public.user_ai_settings
    add column if not exists daily_analysis_limit integer
        check (daily_analysis_limit >= 0);
