-- Keep professional-review workflow status separate from the immutable engine
-- finding while recognising the adverse Parts III-V findings.
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
                'prohibited_substance_identified',
                'restriction_exceeded',
                'permitted_use_condition_not_met',
                'regulated_function_not_permitted',
                'professional_review_required',
                'information_missing',
                'identity_unresolved'
            )
        ),
        case when (
            coalesce((item ->> 'review_required')::boolean, false)
            or item ->> 'primary_finding' in (
                'prohibited_substance_identified',
                'restriction_exceeded',
                'permitted_use_condition_not_met',
                'regulated_function_not_permitted',
                'professional_review_required',
                'information_missing',
                'identity_unresolved'
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
