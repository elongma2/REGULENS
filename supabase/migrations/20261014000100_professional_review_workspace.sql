create table public.review_items (
    id uuid primary key default gen_random_uuid(),
    screening_run_id uuid not null references public.screening_runs(id) on delete cascade,
    subject_type text not null default 'formulation_ingredient_result',
    subject_key text not null,
    submitted_row_number integer not null check (submitted_row_number > 0),
    engine_finding text not null,
    requires_attention boolean not null,
    review_status text check (review_status in ('not_reviewed', 'in_review', 'awaiting_information', 'reviewed')),
    updated_by uuid references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    reviewed_at timestamptz,
    unique (screening_run_id, subject_type, subject_key),
    check (
        (requires_attention and review_status is not null)
        or (not requires_attention and review_status is null)
    ),
    check (
        (review_status = 'reviewed' and reviewed_at is not null)
        or (review_status is distinct from 'reviewed' and reviewed_at is null)
    )
);

create table public.reviewer_notes (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.cases(id) on delete cascade,
    formulation_version_id uuid references public.formulation_versions(id) on delete cascade,
    clarification_id uuid references public.clarifications(id) on delete cascade,
    review_item_id uuid references public.review_items(id) on delete cascade,
    body text not null check (length(trim(body)) between 1 and 4000),
    created_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    check (num_nonnulls(formulation_version_id, clarification_id, review_item_id) <= 1)
);

create table public.follow_up_actions (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references public.cases(id) on delete cascade,
    formulation_version_id uuid references public.formulation_versions(id) on delete cascade,
    clarification_id uuid references public.clarifications(id) on delete cascade,
    review_item_id uuid references public.review_items(id) on delete cascade,
    action_text text not null check (length(trim(action_text)) between 1 and 1000),
    details text check (details is null or length(trim(details)) between 1 and 4000),
    status text not null default 'open' check (status in ('open', 'resolved')),
    created_by uuid not null references auth.users(id),
    resolved_by uuid references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    resolved_at timestamptz,
    check (num_nonnulls(formulation_version_id, clarification_id, review_item_id) <= 1),
    check (
        (status = 'open' and resolved_by is null and resolved_at is null)
        or (status = 'resolved' and resolved_by is not null and resolved_at is not null)
    )
);

create index review_items_screening_status_idx on public.review_items (screening_run_id, review_status);
create index reviewer_notes_case_created_idx on public.reviewer_notes (case_id, created_at desc);
create index follow_up_actions_case_status_idx on public.follow_up_actions (case_id, status, updated_at desc);

create trigger review_items_set_updated_at before update on public.review_items
for each row execute function public.set_updated_at();

create trigger follow_up_actions_set_updated_at before update on public.follow_up_actions
for each row execute function public.set_updated_at();

create or replace function public.protect_review_item_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if new.screening_run_id is distinct from old.screening_run_id
        or new.subject_type is distinct from old.subject_type
        or new.subject_key is distinct from old.subject_key
        or new.submitted_row_number is distinct from old.submitted_row_number
        or new.engine_finding is distinct from old.engine_finding
        or new.requires_attention is distinct from old.requires_attention
        or new.created_at is distinct from old.created_at then
        raise exception 'review_item_engine_fields_are_immutable' using errcode = '23514';
    end if;

    if auth.uid() is not null then
        new.updated_by := auth.uid();
        new.reviewed_at := case when new.review_status = 'reviewed' then now() else null end;
    end if;
    return new;
end;
$$;

create trigger review_items_protect_engine_fields before update on public.review_items
for each row execute function public.protect_review_item_update();

create or replace function public.maintain_follow_up_state()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    if tg_op = 'UPDATE' and (
        new.case_id is distinct from old.case_id
        or new.formulation_version_id is distinct from old.formulation_version_id
        or new.clarification_id is distinct from old.clarification_id
        or new.review_item_id is distinct from old.review_item_id
        or new.created_by is distinct from old.created_by
        or new.created_at is distinct from old.created_at
    ) then
        raise exception 'follow_up_target_and_creator_are_immutable' using errcode = '23514';
    end if;

    if auth.uid() is not null then
        if tg_op = 'INSERT' then
            new.created_by := auth.uid();
            new.status := 'open';
            new.resolved_by := null;
            new.resolved_at := null;
        elsif new.status is distinct from old.status then
            if new.status = 'resolved' then
                new.resolved_by := auth.uid();
                new.resolved_at := now();
            else
                new.resolved_by := null;
                new.resolved_at := null;
            end if;
        else
            new.resolved_by := old.resolved_by;
            new.resolved_at := old.resolved_at;
        end if;
    end if;
    return new;
end;
$$;

create trigger follow_up_actions_maintain_state before insert or update on public.follow_up_actions
for each row execute function public.maintain_follow_up_state();

create or replace function public.touch_case_from_review_item()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    update public.cases c set updated_at = now()
    from public.screening_runs sr
    join public.formulation_versions fv on fv.id = sr.formulation_version_id
    where sr.id = new.screening_run_id and c.id = fv.case_id;
    return new;
end;
$$;

create or replace function public.touch_review_case()
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

create trigger review_items_touch_case after update on public.review_items
for each row execute function public.touch_case_from_review_item();
create trigger reviewer_notes_touch_case after insert on public.reviewer_notes
for each row execute function public.touch_review_case();
create trigger follow_up_actions_touch_case after insert or update on public.follow_up_actions
for each row execute function public.touch_review_case();

create or replace function public.validate_review_target()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_case_id uuid;
begin
    if new.formulation_version_id is not null then
        select case_id into v_case_id from public.formulation_versions where id = new.formulation_version_id;
    elsif new.clarification_id is not null then
        select fv.case_id into v_case_id
        from public.clarifications c
        join public.formulation_versions fv on fv.id = c.formulation_version_id
        where c.id = new.clarification_id;
    elsif new.review_item_id is not null then
        select fv.case_id into v_case_id
        from public.review_items ri
        join public.screening_runs sr on sr.id = ri.screening_run_id
        join public.formulation_versions fv on fv.id = sr.formulation_version_id
        where ri.id = new.review_item_id;
    else
        v_case_id := new.case_id;
    end if;

    if v_case_id is null or v_case_id <> new.case_id then
        raise exception 'review_target_case_mismatch' using errcode = '23514';
    end if;
    return new;
end;
$$;

create trigger reviewer_notes_validate_target before insert on public.reviewer_notes
for each row execute function public.validate_review_target();

create trigger follow_up_actions_validate_target before insert or update on public.follow_up_actions
for each row execute function public.validate_review_target();

create or replace function public.create_screening_run_with_review_items(
    p_formulation_version_id uuid,
    p_user_id uuid,
    p_regulatory_dataset_id text,
    p_jurisdiction text,
    p_request_snapshot jsonb,
    p_result_snapshot jsonb
)
returns public.screening_runs
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_case_id uuid;
    v_organisation_id uuid;
    v_run public.screening_runs;
begin
    select fv.case_id, c.organisation_id into v_case_id, v_organisation_id
    from public.formulation_versions fv
    join public.cases c on c.id = fv.case_id
    where fv.id = p_formulation_version_id;

    if not found or not public.is_organisation_member_for(v_organisation_id, p_user_id) then
        raise exception 'formulation_not_found' using errcode = 'P0002';
    end if;

    insert into public.screening_runs (
        formulation_version_id, regulatory_dataset_id, jurisdiction,
        request_snapshot, result_snapshot, created_by
    ) values (
        p_formulation_version_id, p_regulatory_dataset_id, p_jurisdiction,
        p_request_snapshot, p_result_snapshot, p_user_id
    ) returning * into v_run;

    insert into public.review_items (
        screening_run_id, subject_type, subject_key, submitted_row_number,
        engine_finding, requires_attention, review_status, updated_by
    )
    select
        v_run.id,
        'formulation_ingredient_result',
        'ingredient:' || (item ->> 'submitted_row_number'),
        (item ->> 'submitted_row_number')::integer,
        item ->> 'primary_finding',
        (
            coalesce((item ->> 'review_required')::boolean, false)
            or item ->> 'primary_finding' in (
                'prohibited_substance_identified', 'restriction_exceeded',
                'professional_review_required', 'information_missing', 'identity_unresolved'
            )
        ),
        case when (
            coalesce((item ->> 'review_required')::boolean, false)
            or item ->> 'primary_finding' in (
                'prohibited_substance_identified', 'restriction_exceeded',
                'professional_review_required', 'information_missing', 'identity_unresolved'
            )
        ) then 'not_reviewed' else null end,
        p_user_id
    from jsonb_array_elements(coalesce(p_result_snapshot -> 'ingredient_results', '[]'::jsonb)) item;

    update public.formulation_versions set status = 'screened' where id = p_formulation_version_id;
    return v_run;
end;
$$;

revoke all on function public.create_screening_run_with_review_items(uuid, uuid, text, text, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.create_screening_run_with_review_items(uuid, uuid, text, text, jsonb, jsonb) to service_role;

insert into public.review_items (
    screening_run_id, subject_type, subject_key, submitted_row_number,
    engine_finding, requires_attention, review_status, updated_by
)
select
    sr.id,
    'formulation_ingredient_result',
    'ingredient:' || (item ->> 'submitted_row_number'),
    (item ->> 'submitted_row_number')::integer,
    item ->> 'primary_finding',
    (
        coalesce((item ->> 'review_required')::boolean, false)
        or item ->> 'primary_finding' in (
            'prohibited_substance_identified', 'restriction_exceeded',
            'professional_review_required', 'information_missing', 'identity_unresolved'
        )
    ),
    case when (
        coalesce((item ->> 'review_required')::boolean, false)
        or item ->> 'primary_finding' in (
            'prohibited_substance_identified', 'restriction_exceeded',
            'professional_review_required', 'information_missing', 'identity_unresolved'
        )
    ) then 'not_reviewed' else null end,
    sr.created_by
from public.screening_runs sr
cross join lateral jsonb_array_elements(coalesce(sr.result_snapshot -> 'ingredient_results', '[]'::jsonb)) item
on conflict (screening_run_id, subject_type, subject_key) do nothing;

alter table public.review_items enable row level security;
alter table public.reviewer_notes enable row level security;
alter table public.follow_up_actions enable row level security;

create policy review_items_select_member on public.review_items for select to authenticated using (
    exists (
        select 1 from public.screening_runs sr
        join public.formulation_versions fv on fv.id = sr.formulation_version_id
        join public.cases c on c.id = fv.case_id
        where sr.id = screening_run_id and public.is_organisation_member(c.organisation_id)
    )
);
create policy review_items_update_member on public.review_items for update to authenticated using (
    exists (
        select 1 from public.screening_runs sr
        join public.formulation_versions fv on fv.id = sr.formulation_version_id
        join public.cases c on c.id = fv.case_id
        where sr.id = screening_run_id and public.is_organisation_member(c.organisation_id)
    )
) with check (
    updated_by = auth.uid()
    and
    exists (
        select 1 from public.screening_runs sr
        join public.formulation_versions fv on fv.id = sr.formulation_version_id
        join public.cases c on c.id = fv.case_id
        where sr.id = screening_run_id and public.is_organisation_member(c.organisation_id)
    )
);

create policy reviewer_notes_select_member on public.reviewer_notes for select to authenticated using (
    exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
);
create policy reviewer_notes_insert_member on public.reviewer_notes for insert to authenticated with check (
    created_by = auth.uid()
    and exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
);

create policy follow_up_actions_select_member on public.follow_up_actions for select to authenticated using (
    exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
);
create policy follow_up_actions_insert_member on public.follow_up_actions for insert to authenticated with check (
    created_by = auth.uid()
    and status = 'open'
    and resolved_by is null
    and resolved_at is null
    and exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
);
create policy follow_up_actions_update_member on public.follow_up_actions for update to authenticated using (
    exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
) with check (
    (resolved_by is null or resolved_by = auth.uid())
    and
    exists (select 1 from public.cases c where c.id = case_id and public.is_organisation_member(c.organisation_id))
);
