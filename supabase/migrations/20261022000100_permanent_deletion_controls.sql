alter table public.cases
add column if not exists next_formulation_version_number integer;

update public.cases c
set next_formulation_version_number = coalesce((
    select max(fv.version_number) + 1
    from public.formulation_versions fv
    where fv.case_id = c.id
), 1)
where next_formulation_version_number is null;

alter table public.cases
alter column next_formulation_version_number set default 1,
alter column next_formulation_version_number set not null;

alter table public.cases
add constraint cases_next_formulation_version_number_positive
check (next_formulation_version_number > 0);

create or replace function public.touch_case_from_formulation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    update public.cases
    set updated_at = now(),
        next_formulation_version_number = greatest(next_formulation_version_number, new.version_number + 1)
    where id = new.case_id;
    return new;
end;
$$;

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

    v_version := v_case.next_formulation_version_number;
    update public.cases
    set next_formulation_version_number = v_version + 1
    where id = p_case_id;

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

revoke all on function public.create_formulation_version(uuid, uuid, uuid, text, text, jsonb, jsonb)
from public, anon, authenticated;
grant execute on function public.create_formulation_version(uuid, uuid, uuid, text, text, jsonb, jsonb)
to service_role;

create or replace function public.delete_account_domain_data(p_user_id uuid)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
    if exists (
        select 1
        from public.organisation_members own_membership
        where own_membership.user_id = p_user_id
          and (
              own_membership.role <> 'owner'
              or (select count(*) from public.organisation_members all_members
                  where all_members.organisation_id = own_membership.organisation_id) <> 1
          )
    ) then
        raise exception 'account_deletion_blocked_shared_workspace' using errcode = '23514';
    end if;

    delete from public.organisations organisation
    where exists (
        select 1 from public.organisation_members membership
        where membership.organisation_id = organisation.id
          and membership.user_id = p_user_id
          and membership.role = 'owner'
    );

    delete from public.profiles where id = p_user_id;
end;
$$;

revoke all on function public.delete_account_domain_data(uuid) from public, anon, authenticated;
grant execute on function public.delete_account_domain_data(uuid) to service_role;
