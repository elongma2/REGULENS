create extension if not exists pgcrypto with schema extensions;

create table public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    display_name text not null check (length(trim(display_name)) between 1 and 120),
    created_at timestamptz not null default now()
);

create table public.organisations (
    id uuid primary key default gen_random_uuid(),
    name text not null check (length(trim(name)) between 1 and 160),
    created_at timestamptz not null default now(),
    created_by uuid not null references auth.users(id)
);

create table public.organisation_members (
    organisation_id uuid not null references public.organisations(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null check (role in ('owner', 'member')),
    created_at timestamptz not null default now(),
    primary key (organisation_id, user_id)
);

create table public.cases (
    id uuid primary key default gen_random_uuid(),
    organisation_id uuid not null references public.organisations(id) on delete cascade,
    name text not null check (length(trim(name)) between 1 and 200),
    client_name text check (client_name is null or length(trim(client_name)) between 1 and 200),
    product_type text check (product_type is null or length(trim(product_type)) between 1 and 200),
    status text not null default 'active' check (status in ('active', 'archived')),
    created_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    archived_at timestamptz
);

create table public.formulation_versions (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.cases(id) on delete cascade,
    version_number integer not null check (version_number > 0),
    original_filename text,
    source_storage_path text,
    status text not null default 'uploaded' check (
        status in ('uploaded', 'interpreting', 'clarification_required', 'interpreted', 'ready_to_screen', 'screened', 'failed')
    ),
    revision integer not null default 0 check (revision >= 0),
    raw_extraction jsonb,
    agent_state jsonb,
    canonical_formulation jsonb,
    product_context jsonb,
    created_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (case_id, version_number)
);

create table public.clarifications (
    id uuid primary key default gen_random_uuid(),
    formulation_version_id uuid not null references public.formulation_versions(id) on delete cascade,
    question_key text not null,
    row_id text,
    field_name text not null,
    uncertainty_code text,
    question text not null,
    source_value jsonb,
    proposed_value jsonb,
    resolved_value jsonb,
    status text not null default 'unresolved' check (status in ('unresolved', 'resolved', 'dismissed')),
    created_at timestamptz not null default now(),
    resolved_at timestamptz,
    resolved_by uuid references auth.users(id),
    unique (formulation_version_id, question_key)
);

create table public.screening_runs (
    id uuid primary key default gen_random_uuid(),
    formulation_version_id uuid not null references public.formulation_versions(id) on delete cascade,
    regulatory_dataset_id text not null,
    jurisdiction text not null,
    request_snapshot jsonb not null,
    result_snapshot jsonb not null,
    created_by uuid not null references auth.users(id),
    created_at timestamptz not null default now()
);

create index cases_organisation_updated_idx on public.cases (organisation_id, updated_at desc);
create index formulation_versions_case_version_idx on public.formulation_versions (case_id, version_number desc);
create index clarifications_version_status_idx on public.clarifications (formulation_version_id, status);
create index screening_runs_version_created_idx on public.screening_runs (formulation_version_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger cases_set_updated_at before update on public.cases
for each row execute function public.set_updated_at();

create trigger formulation_versions_set_updated_at before update on public.formulation_versions
for each row execute function public.set_updated_at();

create or replace function public.touch_case_from_formulation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    update public.cases set updated_at = now() where id = new.case_id;
    return new;
end;
$$;

create trigger formulation_versions_touch_case
after insert or update on public.formulation_versions
for each row execute function public.touch_case_from_formulation();

create or replace function public.touch_case_from_screening()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    update public.cases c set updated_at = now()
    from public.formulation_versions fv
    where fv.id = new.formulation_version_id and c.id = fv.case_id;
    return new;
end;
$$;

create trigger screening_runs_touch_case
after insert on public.screening_runs
for each row execute function public.touch_case_from_screening();

create or replace function public.is_organisation_member_for(p_organisation_id uuid, p_user_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1 from public.organisation_members
        where organisation_id = p_organisation_id and user_id = p_user_id
    );
$$;

create or replace function public.is_organisation_member(p_organisation_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select public.is_organisation_member_for(p_organisation_id, auth.uid());
$$;

create or replace function public.is_organisation_owner(p_organisation_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1 from public.organisation_members
        where organisation_id = p_organisation_id and user_id = auth.uid() and role = 'owner'
    );
$$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_display_name text;
    v_organisation_id uuid;
begin
    v_display_name := coalesce(
        nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''),
        nullif(split_part(coalesce(new.email, ''), '@', 1), ''),
        'Regulens User'
    );
    insert into public.profiles (id, display_name) values (new.id, left(v_display_name, 120));
    insert into public.organisations (name, created_by)
    values (left(v_display_name, 140) || '''s Workspace', new.id)
    returning id into v_organisation_id;
    insert into public.organisation_members (organisation_id, user_id, role)
    values (v_organisation_id, new.id, 'owner');
    return new;
end;
$$;

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

create or replace function public.create_formulation_version(
    p_id uuid,
    p_case_id uuid,
    p_user_id uuid,
    p_original_filename text,
    p_source_storage_path text,
    p_raw_extraction jsonb,
    p_agent_state jsonb
)
returns public.formulation_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_case public.cases;
    v_version integer;
    v_result public.formulation_versions;
begin
    select * into v_case from public.cases where id = p_case_id for update;
    if not found or not public.is_organisation_member_for(v_case.organisation_id, p_user_id) then
        raise exception 'case_not_found' using errcode = 'P0002';
    end if;
    select coalesce(max(version_number), 0) + 1 into v_version
    from public.formulation_versions where case_id = p_case_id;
    insert into public.formulation_versions (
        id, case_id, version_number, original_filename, source_storage_path,
        status, raw_extraction, agent_state, created_by
    ) values (
        p_id, p_case_id, v_version, p_original_filename, p_source_storage_path,
        'interpreting', p_raw_extraction, p_agent_state, p_user_id
    ) returning * into v_result;
    return v_result;
end;
$$;

create or replace function public.persist_formulation_state(
    p_formulation_version_id uuid,
    p_user_id uuid,
    p_expected_revision integer,
    p_status text,
    p_agent_state jsonb,
    p_canonical_formulation jsonb,
    p_product_context jsonb,
    p_clarifications jsonb
)
returns public.formulation_versions
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_case_id uuid;
    v_organisation_id uuid;
    v_result public.formulation_versions;
begin
    select fv.case_id, c.organisation_id into v_case_id, v_organisation_id
    from public.formulation_versions fv join public.cases c on c.id = fv.case_id
    where fv.id = p_formulation_version_id;
    if not found or not public.is_organisation_member_for(v_organisation_id, p_user_id) then
        raise exception 'formulation_not_found' using errcode = 'P0002';
    end if;

    update public.formulation_versions
    set status = p_status,
        revision = greatest(p_expected_revision + 1, coalesce((p_agent_state ->> 'revision')::integer, p_expected_revision + 1)),
        agent_state = p_agent_state,
        canonical_formulation = p_canonical_formulation,
        product_context = p_product_context
    where id = p_formulation_version_id and revision = p_expected_revision
    returning * into v_result;
    if not found then
        raise exception 'revision_conflict' using errcode = '40001';
    end if;

    update public.clarifications c
    set status = 'resolved', resolved_at = now(), resolved_by = p_user_id
    where c.formulation_version_id = p_formulation_version_id
      and c.status = 'unresolved'
      and not exists (
          select 1 from jsonb_array_elements(coalesce(p_clarifications, '[]'::jsonb)) item
          where item ->> 'question_key' = c.question_key
      );

    insert into public.clarifications (
        formulation_version_id, question_key, row_id, field_name, uncertainty_code,
        question, source_value, proposed_value, status
    )
    select p_formulation_version_id, item ->> 'question_key', item ->> 'row_id',
           item ->> 'field_name', item ->> 'uncertainty_code', item ->> 'question',
           item -> 'source_value', item -> 'proposed_value', 'unresolved'
    from jsonb_array_elements(coalesce(p_clarifications, '[]'::jsonb)) item
    on conflict (formulation_version_id, question_key) do update
    set row_id = excluded.row_id,
        field_name = excluded.field_name,
        uncertainty_code = excluded.uncertainty_code,
        question = excluded.question,
        source_value = excluded.source_value,
        proposed_value = excluded.proposed_value,
        resolved_value = null,
        status = 'unresolved',
        resolved_at = null,
        resolved_by = null;

    return v_result;
end;
$$;

revoke all on function public.create_formulation_version(uuid, uuid, uuid, text, text, jsonb, jsonb) from public, anon, authenticated;
revoke all on function public.persist_formulation_state(uuid, uuid, integer, text, jsonb, jsonb, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.create_formulation_version(uuid, uuid, uuid, text, text, jsonb, jsonb) to service_role;
grant execute on function public.persist_formulation_state(uuid, uuid, integer, text, jsonb, jsonb, jsonb, jsonb) to service_role;

alter table public.profiles enable row level security;
alter table public.organisations enable row level security;
alter table public.organisation_members enable row level security;
alter table public.cases enable row level security;
alter table public.formulation_versions enable row level security;
alter table public.clarifications enable row level security;
alter table public.screening_runs enable row level security;

create policy profiles_select_self on public.profiles for select to authenticated using (id = auth.uid());
create policy profiles_update_self on public.profiles for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

create policy organisations_select_member on public.organisations for select to authenticated using (public.is_organisation_member(id));
create policy organisations_update_owner on public.organisations for update to authenticated using (public.is_organisation_owner(id)) with check (public.is_organisation_owner(id));
create policy organisations_delete_owner on public.organisations for delete to authenticated using (public.is_organisation_owner(id));

create policy organisation_members_select_member on public.organisation_members for select to authenticated using (public.is_organisation_member(organisation_id));
create policy organisation_members_insert_owner on public.organisation_members for insert to authenticated with check (public.is_organisation_owner(organisation_id));
create policy organisation_members_update_owner on public.organisation_members for update to authenticated using (public.is_organisation_owner(organisation_id)) with check (public.is_organisation_owner(organisation_id));
create policy organisation_members_delete_owner on public.organisation_members for delete to authenticated using (public.is_organisation_owner(organisation_id));

create policy cases_select_member on public.cases for select to authenticated using (public.is_organisation_member(organisation_id));
create policy cases_insert_member on public.cases for insert to authenticated with check (public.is_organisation_member(organisation_id) and created_by = auth.uid());
create policy cases_update_member on public.cases for update to authenticated using (public.is_organisation_member(organisation_id)) with check (public.is_organisation_member(organisation_id));
create policy cases_delete_member on public.cases for delete to authenticated using (public.is_organisation_member(organisation_id));

create policy formulation_versions_select_member on public.formulation_versions for select to authenticated using (
    exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
);
create policy formulation_versions_insert_member on public.formulation_versions for insert to authenticated with check (
    created_by = auth.uid() and exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
);
create policy formulation_versions_update_member on public.formulation_versions for update to authenticated using (
    exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
) with check (
    exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
);
create policy formulation_versions_delete_member on public.formulation_versions for delete to authenticated using (
    exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
);

create policy clarifications_select_member on public.clarifications for select to authenticated using (
    exists (
        select 1 from public.formulation_versions fv join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id and public.is_organisation_member(c.organisation_id)
    )
);
create policy clarifications_insert_member on public.clarifications for insert to authenticated with check (
    exists (
        select 1 from public.formulation_versions fv join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id and public.is_organisation_member(c.organisation_id)
    )
);
create policy clarifications_update_member on public.clarifications for update to authenticated using (
    exists (
        select 1 from public.formulation_versions fv join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id and public.is_organisation_member(c.organisation_id)
    )
) with check (
    exists (
        select 1 from public.formulation_versions fv join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id and public.is_organisation_member(c.organisation_id)
    )
);
create policy clarifications_delete_member on public.clarifications for delete to authenticated using (
    exists (
        select 1 from public.formulation_versions fv join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id and public.is_organisation_member(c.organisation_id)
    )
);

create policy screening_runs_select_member on public.screening_runs for select to authenticated using (
    exists (
        select 1 from public.formulation_versions fv join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id and public.is_organisation_member(c.organisation_id)
    )
);

insert into storage.buckets (id, name, public, file_size_limit)
values ('formulation-files', 'formulation-files', false, 2097152)
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit;

create policy formulation_files_select_member on storage.objects for select to authenticated using (
    bucket_id = 'formulation-files'
    and public.is_organisation_member(((storage.foldername(name))[1])::uuid)
);
create policy formulation_files_insert_member on storage.objects for insert to authenticated with check (
    bucket_id = 'formulation-files'
    and public.is_organisation_member(((storage.foldername(name))[1])::uuid)
);
create policy formulation_files_update_member on storage.objects for update to authenticated using (
    bucket_id = 'formulation-files'
    and public.is_organisation_member(((storage.foldername(name))[1])::uuid)
) with check (
    bucket_id = 'formulation-files'
    and public.is_organisation_member(((storage.foldername(name))[1])::uuid)
);
create policy formulation_files_delete_member on storage.objects for delete to authenticated using (
    bucket_id = 'formulation-files'
    and public.is_organisation_member(((storage.foldername(name))[1])::uuid)
);

