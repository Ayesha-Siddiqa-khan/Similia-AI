-- Additive. New clinical data is accessible only through the authenticated backend.
alter table public.cases add column if not exists clinical_revision bigint not null default 0;
alter table public.patients add column if not exists clinical_erasure_pending boolean
    not null default false;

create table public.clinical_workflow_attempts (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.cases(id) on delete cascade,
    practitioner_id uuid not null references auth.users(id) on delete cascade,
    request_id uuid not null,
    stage text not null check (stage in ('research', 'assessment', 'review', 'sign', 'translation')),
    status text not null default 'running' check (status in ('running', 'done', 'failed')),
    error_stage text,
    created_at timestamptz not null default now(),
    unique (case_id, request_id)
);
create unique index clinical_attempt_one_running
    on public.clinical_workflow_attempts (case_id) where status = 'running';

create table public.clinical_workflow_reports (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.cases(id) on delete cascade,
    practitioner_id uuid not null references auth.users(id) on delete cascade,
    attempt_id uuid not null unique references public.clinical_workflow_attempts(id)
        on delete cascade,
    source_id uuid references public.clinical_workflow_reports(id) on delete cascade,
    case_revision bigint not null,
    stage text not null check (stage in ('research', 'assessment', 'final')),
    locale text not null check (locale in ('en', 'ur')),
    status text not null check (status in ('research', 'draft', 'reviewed', 'signed', 'translation')),
    provider text,
    model text,
    signed_at timestamptz,
    signer_id uuid references auth.users(id) on delete cascade,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    check ((status = 'signed') = (signed_at is not null and signer_id is not null))
);
create index clinical_reports_case on public.clinical_workflow_reports (case_id, created_at desc);

create table public.clinical_guidelines (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    publisher text not null,
    edition text not null,
    section text not null,
    source_url text not null check (source_url like 'https://%'),
    excerpt text not null,
    approved_by uuid not null references auth.users(id),
    approved_at date not null,
    review_due_at date not null check (review_due_at > approved_at),
    retired_at timestamptz,
    search_document tsvector generated always as (
        to_tsvector('english'::regconfig, title || ' ' || section || ' ' || excerpt)
    ) stored
);
create index clinical_guidelines_search on public.clinical_guidelines using gin (search_document);

create table public.clinical_image_consents (
    id uuid primary key default gen_random_uuid(),
    patient_id uuid not null references public.patients(id) on delete cascade,
    practitioner_id uuid not null references auth.users(id) on delete cascade,
    scope text not null check (scope in ('collection', 'gemini')),
    granted boolean not null,
    consent_by text not null check (consent_by in ('patient', 'guardian')),
    text_version text not null default 'clinical-photos-v1',
    created_at timestamptz not null default now()
);
create index clinical_image_consent_latest on public.clinical_image_consents
    (patient_id, scope, created_at desc);

create table public.clinical_images (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.cases(id) on delete cascade,
    practitioner_id uuid not null references auth.users(id) on delete cascade,
    body_site text not null,
    side text not null check (side in ('left', 'right', 'both', 'midline', 'unspecified')),
    complaint text not null,
    captured_on date not null,
    notes text not null default '',
    replaces_id uuid references public.clinical_images(id) on delete set null,
    state text not null default 'uploading' check (state in ('uploading', 'active', 'archived')),
    created_at timestamptz not null default now(),
    archived_at timestamptz
);
create index clinical_images_case on public.clinical_images (case_id, created_at desc);
create unique index clinical_image_replacement on public.clinical_images (replaces_id)
    where replaces_id is not null and state <> 'archived';

create table public.clinical_image_findings (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.cases(id) on delete cascade,
    practitioner_id uuid not null references auth.users(id) on delete cascade,
    image_ids uuid[] not null,
    model text not null,
    consent_id uuid not null references public.clinical_image_consents(id) on delete cascade,
    payload jsonb not null,
    created_at timestamptz not null default now()
);
create index clinical_findings_case on public.clinical_image_findings (case_id);

alter table public.clinical_workflow_attempts enable row level security;
alter table public.clinical_workflow_reports enable row level security;
alter table public.clinical_guidelines enable row level security;
alter table public.clinical_image_consents enable row level security;
alter table public.clinical_images enable row level security;
alter table public.clinical_image_findings enable row level security;
revoke all on public.clinical_workflow_attempts, public.clinical_workflow_reports,
    public.clinical_guidelines, public.clinical_image_consents, public.clinical_images,
    public.clinical_image_findings from public, anon, authenticated;
grant all on public.clinical_workflow_attempts, public.clinical_workflow_reports,
    public.clinical_guidelines, public.clinical_image_consents, public.clinical_images,
    public.clinical_image_findings to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('clinical-images', 'clinical-images', false, 8388608, array['image/jpeg']);

create policy clinical_images_block_direct_access on storage.objects
    as restrictive for all to anon, authenticated
    using (bucket_id <> 'clinical-images') with check (bucket_id <> 'clinical-images');

create function public.clinical_case_revision() returns trigger
language plpgsql set search_path = '' as $$
begin
    if new.chief_complaint is distinct from old.chief_complaint
        or new.language is distinct from old.language then
        new.clinical_revision := old.clinical_revision + 1;
    end if;
    return new;
end;
$$;
create trigger clinical_case_revision before update on public.cases
    for each row execute function public.clinical_case_revision();

create function public.clinical_child_revision() returns trigger
language plpgsql set search_path = '' as $$
begin
    if tg_op = 'DELETE' then
        update public.cases set clinical_revision = clinical_revision + 1 where id = old.case_id;
    else
        update public.cases set clinical_revision = clinical_revision + 1 where id = new.case_id;
    end if;
    return null;
end;
$$;
create trigger clinical_symptom_revision after insert or update or delete on public.case_symptoms
    for each row execute function public.clinical_child_revision();
create trigger clinical_image_revision after update on public.clinical_images
    for each row when (old.state = 'active' or new.state = 'active')
    execute function public.clinical_child_revision();
create trigger clinical_findings_revision after insert or update or delete
    on public.clinical_image_findings for each row execute function public.clinical_child_revision();

create function public.clinical_patient_revision() returns trigger
language plpgsql set search_path = '' as $$
begin
    update public.cases set clinical_revision = clinical_revision + 1 where patient_id = new.id;
    return null;
end;
$$;
create trigger clinical_patient_revision after update on public.patients for each row
    when (old.age_years is distinct from new.age_years
        or old.date_of_birth is distinct from new.date_of_birth
        or old.archived_at is distinct from new.archived_at)
    execute function public.clinical_patient_revision();

create function public.clinical_guideline_search(terms text)
returns setof public.clinical_guidelines language sql stable set search_path = '' as $$
    select g.* from public.clinical_guidelines g
        cross join websearch_to_tsquery('english'::regconfig, terms) as parsed(query)
    where g.search_document @@ parsed.query and g.retired_at is null
        and g.approved_at <= current_date and g.review_due_at >= current_date
    order by ts_rank_cd(g.search_document, parsed.query) desc, g.id limit 8;
$$;
revoke execute on function public.clinical_guideline_search(text) from public, anon, authenticated;
grant execute on function public.clinical_guideline_search(text) to service_role;

create function public.complete_clinical_report(report jsonb)
returns public.clinical_workflow_reports language plpgsql set search_path = '' as $$
declare
    item public.clinical_workflow_reports;
    revision bigint;
    attempt_status text;
begin
    item := jsonb_populate_record(null::public.clinical_workflow_reports, report);
    select c.clinical_revision into revision from public.cases c
        join public.patients p on p.id = c.patient_id
        where c.id = item.case_id and c.practitioner_id = item.practitioner_id
            and p.archived_at is null
            and (item.stage = 'final' or exists (
                select from public.consents consent where consent.patient_id = p.id
                    and consent.practitioner_id = item.practitioner_id
                    and consent.withdrawn_at is null
            )) for update of c, p;
    if not found or (item.status <> 'translation' and revision <> item.case_revision) then
        raise exception using errcode = 'PT409', message = 'The case changed. Refresh and try again.';
    end if;
    select a.status into attempt_status from public.clinical_workflow_attempts a
        where a.id = item.attempt_id and a.case_id = item.case_id
            and a.practitioner_id = item.practitioner_id for update;
    if attempt_status is distinct from 'running' then
        raise exception using errcode = 'PT409', message = 'The report attempt has expired.';
    end if;
    if item.status = 'signed' and not exists (
        select from public.clinical_workflow_attempts a
        where a.id = item.attempt_id and a.stage = 'sign'
    ) then
        raise exception using errcode = 'PT409', message = 'Signing attempt unavailable.';
    end if;
    if item.source_id is not null and not exists (
        select from public.clinical_workflow_reports s
        where s.id = item.source_id and s.case_id = item.case_id
            and s.practitioner_id = item.practitioner_id
    ) then
        raise exception using errcode = 'PT404', message = 'Report source unavailable.';
    end if;
    item.id := gen_random_uuid();
    item.created_at := now();
    if item.status = 'signed' then
        item.signed_at := item.created_at;
        item.signer_id := item.practitioner_id;
    end if;
    insert into public.clinical_workflow_reports select item.*;
    update public.clinical_workflow_attempts set status = 'done' where id = item.attempt_id;
    insert into public.audit_log (practitioner_id, action, entity, entity_id)
        values (item.practitioner_id, 'clinical.report.' || item.stage || '.' || item.status,
            'clinical_report', item.id);
    return item;
end;
$$;
revoke execute on function public.complete_clinical_report(jsonb)
    from public, anon, authenticated;
grant execute on function public.complete_clinical_report(jsonb) to service_role;

create function public.clinical_latest_consent(owner_id uuid, patient_key uuid, consent_scope text)
returns uuid language sql stable set search_path = '' as $$
    select case when granted then id else null end
    from public.clinical_image_consents
    where patient_id = patient_key and practitioner_id = owner_id and scope = consent_scope
    order by created_at desc, id desc limit 1;
$$;

create function public.record_clinical_image_consent(
    owner_id uuid, patient_key uuid, consent_scope text, is_granted boolean, consent_actor text
) returns void language plpgsql set search_path = '' as $$
begin
    perform from public.patients where id = patient_key and practitioner_id = owner_id
        and not clinical_erasure_pending and (not is_granted or archived_at is null) for update;
    if not found then
        raise exception using errcode = 'PT404', message = 'Patient unavailable.';
    end if;
    if is_granted and consent_scope = 'gemini'
        and public.clinical_latest_consent(owner_id, patient_key, 'collection') is null then
        raise exception using errcode = 'PT409', message = 'Collection consent is required.';
    end if;
    insert into public.clinical_image_consents
        (patient_id, practitioner_id, scope, granted, consent_by)
        values (patient_key, owner_id, consent_scope, is_granted, consent_actor);
    if consent_scope = 'collection' and not is_granted then
        insert into public.clinical_image_consents
            (patient_id, practitioner_id, scope, granted, consent_by)
            values (patient_key, owner_id, 'gemini', false, consent_actor);
    end if;
    update public.cases set clinical_revision = clinical_revision + 1
        where patient_id = patient_key and practitioner_id = owner_id;
    insert into public.audit_log (practitioner_id, action, entity, entity_id)
        values (owner_id, 'clinical.photo.consent.' || consent_scope, 'patient', patient_key);
end;
$$;

create function public.reserve_clinical_photo(details jsonb)
returns public.clinical_images language plpgsql set search_path = '' as $$
declare
    photo public.clinical_images;
    patient_key uuid;
begin
    photo := jsonb_populate_record(null::public.clinical_images, details);
    select c.patient_id into patient_key from public.cases c
        join public.patients p on p.id = c.patient_id
        where c.id = photo.case_id and c.practitioner_id = photo.practitioner_id
            and c.status <> 'signed_off' and p.archived_at is null for update of c, p;
    if not found or public.clinical_latest_consent(
        photo.practitioner_id, patient_key, 'collection'
    ) is null then
        raise exception using errcode = 'PT409', message = 'Photo collection unavailable.';
    end if;
    if (select count(*) from public.clinical_images where case_id = photo.case_id
        and state in ('uploading', 'active')) >= 20 and photo.replaces_id is null then
        raise exception using errcode = 'PT422', message = 'Use up to 20 active photos per case.';
    end if;
    photo.id := gen_random_uuid();
    photo.state := 'uploading';
    photo.created_at := now();
    insert into public.clinical_images select photo.*;
    return photo;
end;
$$;

create function public.publish_clinical_photo(
    owner_id uuid, image_key uuid, collection_consent uuid
) returns public.clinical_images language plpgsql set search_path = '' as $$
declare
    photo public.clinical_images;
    patient_key uuid;
begin
    select i.* into photo from public.clinical_images i
        where i.id = image_key and i.practitioner_id = owner_id and i.state = 'uploading';
    select c.patient_id into patient_key from public.cases c
        join public.patients p on p.id = c.patient_id
        where c.id = photo.case_id and c.practitioner_id = owner_id
            and c.status <> 'signed_off' and p.archived_at is null for update of c, p;
    if not found or collection_consent is null
        or public.clinical_latest_consent(owner_id, patient_key, 'collection')
        is distinct from collection_consent then
        raise exception using errcode = 'PT409', message = 'Photo collection consent changed.';
    end if;
    if photo.replaces_id is not null then
        update public.clinical_images set state = 'archived', archived_at = now()
            where id = photo.replaces_id and case_id = photo.case_id
                and practitioner_id = owner_id and body_site = photo.body_site
                and side = photo.side and state = 'active';
        if not found then
            raise exception using errcode = 'PT409', message = 'Replacement photo unavailable.';
        end if;
    end if;
    update public.clinical_images set state = 'active'
        where id = image_key and state = 'uploading' returning * into photo;
    if not found then
        raise exception using errcode = 'PT409', message = 'Photo upload unavailable.';
    end if;
    insert into public.audit_log (practitioner_id, action, entity, entity_id)
        values (owner_id, 'clinical.photo.upload', 'clinical_image', image_key);
    return photo;
end;
$$;

create function public.archive_clinical_photo(owner_id uuid, case_key uuid, image_key uuid)
returns void language plpgsql set search_path = '' as $$
begin
    perform from public.cases c join public.patients p on p.id = c.patient_id
        where c.id = case_key and c.practitioner_id = owner_id
            and c.status <> 'signed_off' and p.archived_at is null for update of c, p;
    if not found then
        raise exception using errcode = 'PT409', message = 'Case is locked.';
    end if;
    update public.clinical_images set state = 'archived', archived_at = now()
        where id = image_key and case_id = case_key and practitioner_id = owner_id
            and state = 'active';
    if not found then
        raise exception using errcode = 'PT404', message = 'Photo unavailable.';
    end if;
    insert into public.audit_log (practitioner_id, action, entity, entity_id)
        values (owner_id, 'clinical.photo.archive', 'clinical_image', image_key);
end;
$$;

create function public.save_clinical_photo_findings(details jsonb, collection_consent uuid)
returns public.clinical_image_findings language plpgsql set search_path = '' as $$
declare
    finding public.clinical_image_findings;
    patient_key uuid;
begin
    finding := jsonb_populate_record(null::public.clinical_image_findings, details);
    select c.patient_id into patient_key from public.cases c
        join public.patients p on p.id = c.patient_id
        where c.id = finding.case_id and c.practitioner_id = finding.practitioner_id
            and p.archived_at is null
            and exists (
                select from public.consents consent where consent.patient_id = p.id
                    and consent.practitioner_id = finding.practitioner_id
                    and consent.withdrawn_at is null
            ) for update of c, p;
    if not found or collection_consent is null or public.clinical_latest_consent(
        finding.practitioner_id, patient_key, 'collection'
    ) is distinct from collection_consent or public.clinical_latest_consent(
        finding.practitioner_id, patient_key, 'gemini'
    ) is distinct from finding.consent_id or (
        select count(*) from public.clinical_images i join public.cases c on i.case_id = c.id
        where i.id = any(finding.image_ids) and i.practitioner_id = finding.practitioner_id
            and c.patient_id = patient_key and i.state = 'active'
    ) <> cardinality(finding.image_ids) then
        raise exception using errcode = 'PT409', message = 'The photos or their consent changed.';
    end if;
    finding.id := gen_random_uuid();
    finding.created_at := now();
    insert into public.clinical_image_findings select finding.*;
    insert into public.audit_log (practitioner_id, action, entity, entity_id)
        values (finding.practitioner_id, 'clinical.photos.observed', 'case', finding.case_id);
    return finding;
end;
$$;

revoke execute on function public.clinical_latest_consent(uuid, uuid, text),
    public.record_clinical_image_consent(uuid, uuid, text, boolean, text),
    public.reserve_clinical_photo(jsonb), public.publish_clinical_photo(uuid, uuid, uuid),
    public.archive_clinical_photo(uuid, uuid, uuid), public.save_clinical_photo_findings(jsonb, uuid)
    from public, anon, authenticated;
grant execute on function public.clinical_latest_consent(uuid, uuid, text),
    public.record_clinical_image_consent(uuid, uuid, text, boolean, text),
    public.reserve_clinical_photo(jsonb), public.publish_clinical_photo(uuid, uuid, uuid),
    public.archive_clinical_photo(uuid, uuid, uuid), public.save_clinical_photo_findings(jsonb, uuid)
    to service_role;

create function public.revoke_photo_ai_with_case_consent() returns trigger
language plpgsql set search_path = '' as $$
begin
    insert into public.clinical_image_consents
        (patient_id, practitioner_id, scope, granted, consent_by)
        select new.patient_id, new.practitioner_id, 'gemini', false, consent_by
        from public.clinical_image_consents
        where id = public.clinical_latest_consent(new.practitioner_id, new.patient_id, 'gemini');
    return null;
end;
$$;
create trigger revoke_photo_ai_with_case_consent after update on public.consents for each row
    when (old.withdrawn_at is null and new.withdrawn_at is not null)
    execute function public.revoke_photo_ai_with_case_consent();

create function public.prevent_reopen_during_clinical_erasure() returns trigger
language plpgsql set search_path = '' as $$
begin
    raise exception using errcode = 'PT409', message = 'Patient erasure is pending.';
end;
$$;
create trigger prevent_reopen_during_clinical_erasure before update on public.patients
    for each row when (old.clinical_erasure_pending and
        (new.archived_at is null or not new.clinical_erasure_pending))
    execute function public.prevent_reopen_during_clinical_erasure();

create function public.begin_clinical_patient_erasure(owner_id uuid, patient_key uuid)
returns void language plpgsql set search_path = '' as $$
begin
    perform from public.patients where id = patient_key and practitioner_id = owner_id
        and archived_at is not null for update;
    if not found or exists (
        select from public.clinical_images i join public.cases c on c.id = i.case_id
        where c.patient_id = patient_key and i.practitioner_id = owner_id
            and i.state = 'uploading'
    ) then
        raise exception using errcode = 'PT409', message = 'Photo erasure cannot start.';
    end if;
    update public.patients set clinical_erasure_pending = true where id = patient_key
        and practitioner_id = owner_id;
end;
$$;
revoke execute on function public.begin_clinical_patient_erasure(uuid, uuid)
    from public, anon, authenticated;
grant execute on function public.begin_clinical_patient_erasure(uuid, uuid) to service_role;
