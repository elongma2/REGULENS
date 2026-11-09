alter table public.formulation_versions
add column if not exists assembly_state jsonb,
add column if not exists assembly_revision integer not null default 0 check (assembly_revision >= 0),
add column if not exists calculation_snapshot jsonb;

create table public.supplier_documents (
    id uuid primary key default gen_random_uuid(),
    organisation_id uuid not null references public.organisations(id) on delete cascade,
    original_filename text not null check (length(trim(original_filename)) between 1 and 500),
    storage_path text not null unique,
    mime_type text not null,
    sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    page_count integer check (page_count is null or page_count > 0),
    supplier_name text,
    trade_name text,
    product_code text,
    document_revision_label text,
    document_date date,
    supersedes_supplier_document_id uuid references public.supplier_documents(id) on delete set null,
    detected_roles jsonb not null default '[]'::jsonb,
    confirmed_roles jsonb not null default '[]'::jsonb,
    parsed_content jsonb,
    extraction_result jsonb,
    extraction_schema_version text,
    model_configuration text,
    processing_status text not null default 'uploaded' check (
        processing_status in (
            'uploaded', 'parsing', 'classifying', 'extracting',
            'needs_confirmation', 'ready', 'interrupted', 'failed'
        )
    ),
    library_status text not null default 'processing' check (
        library_status in ('processing', 'available', 'needs_confirmation', 'archived', 'failed')
    ),
    processing_diagnostics jsonb,
    error jsonb,
    processing_key text,
    processor_run_id uuid,
    processing_started_at timestamptz,
    heartbeat_at timestamptz,
    lease_expires_at timestamptz,
    processing_attempt integer not null default 0 check (processing_attempt >= 0),
    revision integer not null default 0 check (revision >= 0),
    last_used_at timestamptz,
    created_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (organisation_id, sha256),
    check (supersedes_supplier_document_id is null or supersedes_supplier_document_id <> id)
);

create table public.formulation_documents (
    id uuid primary key default gen_random_uuid(),
    formulation_version_id uuid not null references public.formulation_versions(id) on delete cascade,
    supplier_document_id uuid references public.supplier_documents(id) on delete restrict,
    original_filename text not null check (length(trim(original_filename)) between 1 and 500),
    storage_path text unique,
    mime_type text not null,
    sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    page_count integer check (page_count is null or page_count > 0),
    processing_status text not null default 'uploaded' check (
        processing_status in (
            'uploaded', 'parsing', 'classifying', 'extracting',
            'needs_confirmation', 'ready', 'interrupted', 'failed'
        )
    ),
    detected_roles jsonb not null default '[]'::jsonb,
    confirmed_roles jsonb not null default '[]'::jsonb,
    parsed_content jsonb,
    extraction_result jsonb,
    processing_diagnostics jsonb,
    error jsonb,
    processing_key text,
    processor_run_id uuid,
    processing_started_at timestamptz,
    heartbeat_at timestamptz,
    lease_expires_at timestamptz,
    processing_attempt integer not null default 0 check (processing_attempt >= 0),
    supersedes_document_id uuid references public.formulation_documents(id) on delete set null,
    document_revision_label text,
    governing_for_material boolean not null default false,
    attached_extraction_key text,
    revision integer not null default 0 check (revision >= 0),
    created_by uuid not null references auth.users(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (supplier_document_id is not null or storage_path is not null),
    check (supersedes_document_id is null or supersedes_document_id <> id)
);

create unique index formulation_documents_saved_document_unique
on public.formulation_documents (formulation_version_id, supplier_document_id)
where supplier_document_id is not null;

create unique index formulation_documents_direct_hash_unique
on public.formulation_documents (formulation_version_id, sha256)
where supplier_document_id is null;

create index supplier_documents_library_search_idx
on public.supplier_documents (organisation_id, library_status, updated_at desc);

create index supplier_documents_revision_idx
on public.supplier_documents (supersedes_supplier_document_id, created_at desc);

create index formulation_documents_version_idx
on public.formulation_documents (formulation_version_id, created_at);

create index formulation_documents_processing_idx
on public.formulation_documents (processing_status, lease_expires_at)
where processing_status in ('parsing', 'classifying', 'extracting', 'interrupted');

create or replace function public.validate_supplier_document_revision_lineage()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
    predecessor_organisation_id uuid;
begin
    if new.supersedes_supplier_document_id is null then
        return new;
    end if;

    select organisation_id
      into predecessor_organisation_id
      from public.supplier_documents
     where id = new.supersedes_supplier_document_id;

    if predecessor_organisation_id is null
       or predecessor_organisation_id <> new.organisation_id then
        raise exception 'supplier-document revisions must belong to the same organisation'
            using errcode = '23514';
    end if;

    if exists (
        with recursive lineage(id, predecessor_id) as (
            select id, supersedes_supplier_document_id
              from public.supplier_documents
             where id = new.supersedes_supplier_document_id
            union
            select parent.id, parent.supersedes_supplier_document_id
              from public.supplier_documents parent
              join lineage child on parent.id = child.predecessor_id
        )
        select 1 from lineage where id = new.id
    ) then
        raise exception 'supplier-document revision lineage cannot contain a cycle'
            using errcode = '23514';
    end if;

    return new;
end;
$$;

create trigger supplier_documents_validate_revision_lineage
before insert or update of organisation_id, supersedes_supplier_document_id
on public.supplier_documents
for each row execute function public.validate_supplier_document_revision_lineage();

revoke all on function public.validate_supplier_document_revision_lineage()
from public, anon, authenticated;

create trigger supplier_documents_set_updated_at before update on public.supplier_documents
for each row execute function public.set_updated_at();

create trigger formulation_documents_set_updated_at before update on public.formulation_documents
for each row execute function public.set_updated_at();

alter table public.supplier_documents enable row level security;
alter table public.formulation_documents enable row level security;

create policy supplier_documents_select_member on public.supplier_documents
for select to authenticated
using (public.is_organisation_member(organisation_id));

create policy supplier_documents_insert_member on public.supplier_documents
for insert to authenticated
with check (
    created_by = auth.uid()
    and public.is_organisation_member(organisation_id)
);

create policy supplier_documents_update_member on public.supplier_documents
for update to authenticated
using (public.is_organisation_member(organisation_id))
with check (public.is_organisation_member(organisation_id));

create policy supplier_documents_delete_member on public.supplier_documents
for delete to authenticated
using (public.is_organisation_member(organisation_id));

create policy formulation_documents_select_member on public.formulation_documents
for select to authenticated
using (
    exists (
        select 1
        from public.formulation_versions fv
        join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id
          and public.is_organisation_member(c.organisation_id)
    )
);

create policy formulation_documents_insert_member on public.formulation_documents
for insert to authenticated
with check (
    created_by = auth.uid()
    and exists (
        select 1
        from public.formulation_versions fv
        join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id
          and public.is_organisation_member(c.organisation_id)
    )
    and (
        supplier_document_id is null
        or exists (
            select 1
            from public.supplier_documents sd
            join public.formulation_versions fv on fv.id = formulation_version_id
            join public.cases c on c.id = fv.case_id
            where sd.id = supplier_document_id
              and sd.organisation_id = c.organisation_id
        )
    )
);

create policy formulation_documents_update_member on public.formulation_documents
for update to authenticated
using (
    exists (
        select 1
        from public.formulation_versions fv
        join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id
          and public.is_organisation_member(c.organisation_id)
    )
)
with check (
    exists (
        select 1
        from public.formulation_versions fv
        join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id
          and public.is_organisation_member(c.organisation_id)
    )
);

create policy formulation_documents_delete_member on public.formulation_documents
for delete to authenticated
using (
    exists (
        select 1
        from public.formulation_versions fv
        join public.cases c on c.id = fv.case_id
        where fv.id = formulation_version_id
          and public.is_organisation_member(c.organisation_id)
    )
);

create or replace function public.supplier_document_is_referenced(p_supplier_document_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1 from public.formulation_documents
        where supplier_document_id = p_supplier_document_id
    );
$$;

revoke all on function public.supplier_document_is_referenced(uuid)
from public, anon, authenticated;
grant execute on function public.supplier_document_is_referenced(uuid)
to service_role;
