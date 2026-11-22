-- Phase 4: guardian details for minors. Nothing is deleted; two nullable columns are added.
-- Run once in the SQL editor of project ivlmduwdkwgrxqxjjuyg only.

alter table public.patients
    add column if not exists guardian_name text,
    add column if not exists guardian_relationship text;

-- Erasing a patient removes their consents, cases, symptoms, analyses and reviews (existing
-- ON DELETE CASCADE). The audit log keeps only the action and the id, never clinical content.
