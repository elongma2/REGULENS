-- Keep supplier-document provenance and formulation-local attachment lineage
-- immutable even when an authenticated browser talks to PostgREST directly.

create or replace function public.protect_supplier_document_provenance()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    if new.id is distinct from old.id
       or new.organisation_id is distinct from old.organisation_id
       or new.storage_path is distinct from old.storage_path
       or new.sha256 is distinct from old.sha256
       or new.created_by is distinct from old.created_by
       or new.created_at is distinct from old.created_at then
        raise exception 'supplier_document_provenance_is_immutable'
            using errcode = '23514';
    end if;
    return new;
end;
$$;

revoke all on function public.protect_supplier_document_provenance()
from public, anon, authenticated;

create trigger supplier_documents_protect_provenance
before update on public.supplier_documents
for each row execute function public.protect_supplier_document_provenance();

create or replace function public.validate_formulation_document_provenance()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    version_organisation_id uuid;
    supplier_organisation_id uuid;
begin
    if tg_op = 'UPDATE' and (
        new.id is distinct from old.id
        or new.formulation_version_id is distinct from old.formulation_version_id
        or new.supplier_document_id is distinct from old.supplier_document_id
        or new.storage_path is distinct from old.storage_path
        or new.sha256 is distinct from old.sha256
        or new.created_by is distinct from old.created_by
        or new.created_at is distinct from old.created_at
    ) then
        raise exception 'formulation_document_provenance_is_immutable'
            using errcode = '23514';
    end if;

    select c.organisation_id
      into version_organisation_id
      from public.formulation_versions fv
      join public.cases c on c.id = fv.case_id
     where fv.id = new.formulation_version_id;

    if version_organisation_id is null then
        raise exception 'formulation_document_version_not_found'
            using errcode = '23503';
    end if;

    if new.supplier_document_id is not null then
        select organisation_id
          into supplier_organisation_id
          from public.supplier_documents
         where id = new.supplier_document_id;

        if supplier_organisation_id is null then
            raise exception 'formulation_document_supplier_not_found'
                using errcode = '23503';
        end if;
        if supplier_organisation_id is distinct from version_organisation_id then
            raise exception 'formulation_document_supplier_case_mismatch'
                using errcode = '23514';
        end if;
    end if;

    return new;
end;
$$;

revoke all on function public.validate_formulation_document_provenance()
from public, anon, authenticated;

create trigger formulation_documents_validate_provenance
before insert or update on public.formulation_documents
for each row execute function public.validate_formulation_document_provenance();
