-- Patient records and homeopathic case-taking (Phase 1: practitioner workspace).
-- Every row is owned by one practitioner (auth.users). RLS is enabled with an
-- owner policy as defence in depth; the FastAPI backend (service role) bypasses
-- RLS and therefore ALWAYS filters on practitioner_id explicitly.

create table public.patients (
    id uuid primary key default gen_random_uuid(),
    practitioner_id uuid not null references auth.users (id) on delete cascade,
    identifier text not null,
    full_name text not null,
    date_of_birth date,
    age_years integer check (age_years between 0 and 130),
    sex text check (sex in ('female', 'male', 'other', 'unspecified')),
    preferred_language text not null default 'en' check (preferred_language in ('en', 'hi', 'ur')),
    contact text,
    notes text,
    archived_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (practitioner_id, identifier)
);
create index patients_practitioner_idx on public.patients (practitioner_id, archived_at);

create table public.consents (
    id uuid primary key default gen_random_uuid(),
    practitioner_id uuid not null references auth.users (id) on delete cascade,
    patient_id uuid not null references public.patients (id) on delete cascade,
    purpose text not null,
    text_version text not null,
    granted_at timestamptz not null default now(),
    withdrawn_at timestamptz
);
create index consents_patient_idx on public.consents (patient_id);
create index consents_practitioner_idx on public.consents (practitioner_id);

create table public.cases (
    id uuid primary key default gen_random_uuid(),
    practitioner_id uuid not null references auth.users (id) on delete cascade,
    patient_id uuid not null references public.patients (id) on delete cascade,
    status text not null default 'draft' check (status in ('draft', 'analyzed', 'signed_off')),
    chief_complaint text not null default '',
    language text not null default 'en' check (language in ('en', 'hi', 'ur')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index cases_patient_idx on public.cases (patient_id);
create index cases_practitioner_idx on public.cases (practitioner_id, updated_at desc);

create table public.case_symptoms (
    id uuid primary key default gen_random_uuid(),
    practitioner_id uuid not null references auth.users (id) on delete cascade,
    case_id uuid not null references public.cases (id) on delete cascade,
    ordinal integer not null,
    kind text not null check (
        kind in ('mental', 'physical_general', 'particular', 'history', 'family', 'medication')
    ),
    label text not null,
    location text,
    sensation text,
    better text,
    worse text,
    concomitants text,
    duration text,
    notes text,
    weight smallint not null default 2 check (weight between 1 and 3),
    unique (case_id, ordinal)
);
create index case_symptoms_case_idx on public.case_symptoms (case_id);
create index case_symptoms_practitioner_idx on public.case_symptoms (practitioner_id);

-- Analyses are immutable snapshots of what the AI returned for a case.
create table public.case_analyses (
    id uuid primary key default gen_random_uuid(),
    practitioner_id uuid not null references auth.users (id) on delete cascade,
    case_id uuid not null references public.cases (id) on delete cascade,
    outcome text not null check (outcome in ('ranked', 'insufficient_sources', 'red_flag')),
    red_flags jsonb not null default '[]'::jsonb,
    remedies jsonb not null default '[]'::jsonb,
    passages jsonb not null default '[]'::jsonb,
    missing_information jsonb not null default '[]'::jsonb,
    queries jsonb not null default '[]'::jsonb,
    model text,
    created_at timestamptz not null default now()
);
create index case_analyses_case_idx on public.case_analyses (case_id, created_at desc);
create index case_analyses_practitioner_idx on public.case_analyses (practitioner_id);

create table public.case_reviews (
    id uuid primary key default gen_random_uuid(),
    practitioner_id uuid not null references auth.users (id) on delete cascade,
    analysis_id uuid not null references public.case_analyses (id) on delete cascade,
    case_id uuid not null references public.cases (id) on delete cascade,
    decision text not null check (decision in ('accepted', 'modified', 'rejected')),
    chosen_remedy text,
    notes text,
    signed_at timestamptz not null default now()
);
create index case_reviews_case_idx on public.case_reviews (case_id);
create index case_reviews_analysis_idx on public.case_reviews (analysis_id);
create index case_reviews_practitioner_idx on public.case_reviews (practitioner_id);

create table public.audit_log (
    id bigint generated always as identity primary key,
    practitioner_id uuid not null references auth.users (id) on delete cascade,
    action text not null,
    entity text not null,
    entity_id uuid,
    created_at timestamptz not null default now()
);
create index audit_log_practitioner_idx on public.audit_log (practitioner_id, created_at desc);

-- Row level security: owners only. Audit log is read-only for owners.
alter table public.patients enable row level security;
alter table public.consents enable row level security;
alter table public.cases enable row level security;
alter table public.case_symptoms enable row level security;
alter table public.case_analyses enable row level security;
alter table public.case_reviews enable row level security;
alter table public.audit_log enable row level security;

create policy patients_owner on public.patients for all to authenticated
    using (practitioner_id = (select auth.uid())) with check (practitioner_id = (select auth.uid()));
create policy consents_owner on public.consents for all to authenticated
    using (practitioner_id = (select auth.uid())) with check (practitioner_id = (select auth.uid()));
create policy cases_owner on public.cases for all to authenticated
    using (practitioner_id = (select auth.uid())) with check (practitioner_id = (select auth.uid()));
create policy case_symptoms_owner on public.case_symptoms for all to authenticated
    using (practitioner_id = (select auth.uid())) with check (practitioner_id = (select auth.uid()));
create policy case_analyses_read on public.case_analyses for select to authenticated
    using (practitioner_id = (select auth.uid()));
create policy case_reviews_owner on public.case_reviews for all to authenticated
    using (practitioner_id = (select auth.uid())) with check (practitioner_id = (select auth.uid()));
create policy audit_log_read on public.audit_log for select to authenticated
    using (practitioner_id = (select auth.uid()));

revoke all on public.patients, public.consents, public.cases, public.case_symptoms,
    public.case_analyses, public.case_reviews, public.audit_log from anon;
