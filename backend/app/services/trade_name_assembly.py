from __future__ import annotations

from collections.abc import Iterable
import hashlib
import re
from typing import Any

from backend.app.models.agent import AgentSessionView
from backend.app.models.document_intake import (
    CompositionQuantity,
    CompositionQuantityKind,
    ConfirmationStatus,
    DirectIngredient,
    DisclosureStatus,
    DocumentExtraction,
    DocumentRole,
    DocumentSourceEvidence,
    FormulationAssemblyState,
    FormulationRowOwnership,
    FormulationRowOwnerType,
    MaterialConstituent,
    PreparedAssembly,
    SupplierMaterial,
)
from backend.app.models.formulation import (
    ConcentrationBasis,
    ConcentrationUnit,
    FormulationConcentration,
    FormulationIngredientRequest,
    PreparationStage,
)
from backend.app.models.screening import ConcentrationType, IdentityOutcome, IdentityStatus
from backend.app.services.composition_legends import resolve_coded_quantity
from backend.app.services.formulation_assembly import prepare_assembly
from backend.app.services.ingredient_catalog import IngredientCatalog
from backend.app.services.ingredient_linkage import IngredientLinkageStore
from backend.app.services.loader import RegulatoryStore
from backend.app.services.resolver import resolve_ingredient


ASSEMBLY_DERIVATION_VERSION = "assembly-v6"


_DOCUMENT_SUFFIX_RE = re.compile(
    r"(?:\s+(?:supplier\s+)?composition(?:\s+statement)?|\s+(?:sds|msds))"
    r"(?:\s+(?:rev(?:ision)?|version)\s*[a-z0-9._-]+)?$",
    re.I,
)


def _commercial_aliases(value: str | None) -> set[str]:
    """Return conservative exact aliases for a commercial material label.

    Supplier files often use a filename such as
    ``01_ClariPreserve_P70_Supplier_Composition.pdf`` while the finished
    formulation contains ``ClariPreserve P70``.  These are the same explicit
    commercial label, not a fuzzy chemical-name match.  Normalisation is kept
    deliberately narrow so similar trade names are never merged implicitly.
    """
    if not value or not value.strip():
        return set()
    text = value.strip()
    text = re.sub(r"\.(?:pdf|xlsx?|csv)$", "", text, flags=re.I)
    text = re.sub(r"[_]+", " ", text)
    text = re.sub(r"^\s*\d+[\s._-]+", "", text)
    base = " ".join(text.casefold().split())
    cleaned = _DOCUMENT_SUFFIX_RE.sub("", base).strip(" ._-")

    def compact(candidate: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", candidate.casefold()))

    return {alias for alias in {compact(base), compact(cleaned)} if alias}


def _material_aliases(material: SupplierMaterial) -> set[str]:
    return {
        alias
        for value in (material.trade_name, material.product_code)
        for alias in _commercial_aliases(value)
    }


def _identity_group(
    store: RegulatoryStore,
    catalogue: IngredientCatalog | None,
    linkages: IngredientLinkageStore | None,
    name: str,
    cas_number: str | None,
) -> str | None:
    resolution = resolve_ingredient(
        store,
        name,
        cas_number,
        ingredient_catalog=catalogue,
        linkage_store=linkages,
    )
    safe_review_outcomes = {
        IdentityOutcome.VERIFIED,
        IdentityOutcome.NAME_RECOGNISED_CAS_UNVERIFIED,
        IdentityOutcome.CAS_RECOGNISED_NAME_UNVERIFIED,
        IdentityOutcome.SAME_IDENTITY_MULTIPLE_REGULATORY_RECORDS,
    }
    if resolution.status == IdentityStatus.REVIEW_REQUIRED and resolution.identity_outcome not in safe_review_outcomes:
        return None
    if resolution.status not in {IdentityStatus.RESOLVED, IdentityStatus.REVIEW_REQUIRED}:
        return None
    ids = resolution.resolved_singapore_substance_ids or (
        [resolution.resolved_singapore_substance_id]
        if resolution.resolved_singapore_substance_id else []
    )
    if resolution.catalogue_identity is not None:
        return f"catalogue:{resolution.catalogue_identity.ingredient_id}"
    # A Singapore source name can be an accepted exact alias of a catalogue
    # identity without itself being a catalogue name (for example,
    # ``2-Phenoxyethanol`` and INCI ``PHENOXYETHANOL``). Reuse the accepted
    # linkage's catalogue key only when the submitted name/CAS and the exact
    # resolved Singapore target both agree. This unifies verified identities
    # without introducing name-similarity matching or merging distinct forms.
    if linkages is not None and ids:
        normalized_name = " ".join(name.strip().casefold().split())
        accepted_matches = []
        for catalogue_id, record in linkages.records_by_catalogue_id.items():
            if record.get("status") != "linked":
                continue
            supported_names = {
                " ".join(str(value).strip().casefold().split())
                for value in record.get("supported_names") or []
            }
            supported_cas = {
                str(value).strip() for value in record.get("supported_cas_numbers") or []
            }
            target_ids = {
                str(target.get("substance_id"))
                for target in record.get("singapore_targets") or []
                if target.get("substance_id")
            }
            submitted_identifier_matches = (
                normalized_name in supported_names
                or bool(cas_number and cas_number.strip() in supported_cas)
            )
            if submitted_identifier_matches and set(ids) == target_ids:
                accepted_matches.append(catalogue_id)
        if len(accepted_matches) == 1:
            return f"catalogue:{accepted_matches[0]}"
    return f"singapore:{','.join(sorted(ids))}" if ids else None


def _resolve_constituent(
    constituent: MaterialConstituent,
    *,
    document_id: str,
    extraction: DocumentExtraction,
    store: RegulatoryStore,
    catalogue: IngredientCatalog | None,
    linkages: IngredientLinkageStore | None,
) -> MaterialConstituent:
    quantity = constituent.composition_quantity
    if quantity and quantity.kind == CompositionQuantityKind.CODED_RANGE:
        legend = next(
            (item for item in extraction.legends if item.document_id == document_id),
            None,
        )
        resolved, _ = resolve_coded_quantity(
            quantity,
            legend,
            document_id=document_id,
            material_id=None,
            constituent_id=constituent.constituent_id,
        )
        if resolved is not None:
            quantity = resolved
    return constituent.model_copy(update={
        "composition_quantity": quantity,
        "verified_identity_group": _identity_group(
            store,
            catalogue,
            linkages,
            constituent.submitted_name,
            constituent.cas_number,
        ),
    })


def _resolved_direct(
    row: DirectIngredient,
    *,
    store: RegulatoryStore,
    catalogue: IngredientCatalog | None,
    linkages: IngredientLinkageStore | None,
) -> DirectIngredient:
    return row.model_copy(update={
        "verified_identity_group": _identity_group(
            store,
            catalogue,
            linkages,
            row.ingredient.name,
            row.ingredient.cas_number,
        ),
    })


def _enum_value(enum_type, value: Any):
    if value is None:
        return None
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        return None


def _agent_concentration(payload: dict[str, Any] | None) -> FormulationConcentration | None:
    if not payload:
        return None

    def field_value(field: str) -> Any:
        candidate = payload.get(field)
        return candidate.get("value") if isinstance(candidate, dict) else None

    concentration_type = _enum_value(ConcentrationType, field_value("concentration_type"))
    value = field_value("value")
    lower = field_value("lower_bound")
    upper = field_value("upper_bound")
    original = payload.get("original_text")
    if concentration_type is None:
        if value is not None:
            concentration_type = ConcentrationType.EXACT
        elif lower is not None or upper is not None:
            concentration_type = (
                ConcentrationType.RANGE if lower is not None and upper is not None
                else ConcentrationType.LOWER_BOUND if lower is not None
                else ConcentrationType.UPPER_BOUND
            )
        elif original:
            concentration_type = ConcentrationType.UNKNOWN
        else:
            return None
    return FormulationConcentration(
        concentration_type=concentration_type,
        value=value,
        lower_bound=lower,
        upper_bound=upper,
        lower_inclusive=payload.get("lower_inclusive"),
        upper_inclusive=payload.get("upper_inclusive"),
        original_text=original,
        unit=_enum_value(ConcentrationUnit, field_value("unit")),
        basis=_enum_value(ConcentrationBasis, field_value("basis")),
        preparation_stage=_enum_value(PreparationStage, field_value("preparation_stage")),
    )


def _material_usage_from_agent_row(row: Any) -> CompositionQuantity | None:
    concentration = _agent_concentration(
        row.concentration.model_dump(mode="json") if row.concentration else None
    )
    if concentration is None:
        return None
    kind = CompositionQuantityKind(concentration.concentration_type.value)
    return CompositionQuantity(
        kind=kind,
        value=concentration.value,
        lower=concentration.lower_bound,
        upper=concentration.upper_bound,
        lower_inclusive=concentration.lower_inclusive,
        upper_inclusive=concentration.upper_inclusive,
        unit=concentration.unit.value if concentration.unit else None,
        basis=concentration.basis.value if concentration.basis else None,
        preparation_stage=(
            concentration.preparation_stage.value
            if concentration.preparation_stage else "finished_product"
        ),
        quantity_scope="finished_product",
        raw_text=concentration.original_text,
        approximate=concentration.concentration_type == ConcentrationType.APPROXIMATE,
    )


def _agent_material_usage_by_row_id(
    agent_state: dict[str, Any] | None,
) -> dict[str, CompositionQuantity]:
    if not agent_state:
        return {}
    try:
        session = AgentSessionView.model_validate(agent_state)
    except ValueError:
        return {}
    output: dict[str, CompositionQuantity] = {}
    for row in session.interpreted_rows:
        usage = _material_usage_from_agent_row(row)
        if usage is not None:
            output[row.row_id] = usage
    return output


def formulation_row_ownership(
    agent_state: dict[str, Any] | AgentSessionView | None,
    materials: Iterable[SupplierMaterial],
) -> list[FormulationRowOwnership]:
    """Assign every primary-formulation row to a stable workflow owner.

    Exact commercial aliases may identify one or more supplier-material
    candidates. Ambiguous exact matches remain supplier-owned so the parent row
    cannot leak into chemical identity screening, but no material is selected
    until the association is unambiguous.
    """
    if agent_state is None:
        return []
    try:
        session = (
            agent_state
            if isinstance(agent_state, AgentSessionView)
            else AgentSessionView.model_validate(agent_state)
        )
    except ValueError:
        return []
    material_list = list(materials)
    ownership: list[FormulationRowOwnership] = []
    for row in session.interpreted_rows:
        row_aliases = {
            alias
            for value in (row.name.value, row.name.source_value)
            for alias in _commercial_aliases(str(value or ""))
        }
        candidates = sorted({
            material.material_id
            for material in material_list
            if row_aliases & _material_aliases(material)
        })
        if candidates:
            ownership.append(FormulationRowOwnership(
                row_id=row.row_id,
                owner_type=FormulationRowOwnerType.SUPPLIER_MATERIAL,
                material_id=candidates[0] if len(candidates) == 1 else None,
                candidate_material_ids=candidates,
            ))
        else:
            ownership.append(FormulationRowOwnership(
                row_id=row.row_id,
                owner_type=FormulationRowOwnerType.DIRECT_INGREDIENT,
            ))
    return ownership


def matched_trade_material_row_ids(
    agent_state: dict[str, Any] | AgentSessionView | None,
    materials: Iterable[SupplierMaterial],
) -> set[str]:
    """Return primary-formulation rows owned by the supplier-material workflow.

    A trade name in the finished formula is a parent raw material, not a direct
    cosmetic ingredient. Once a supplier document identifies that material,
    its row must be expanded by the assembly layer and must not also be sent
    through the ordinary ingredient-confirmation path.
    """
    if agent_state is None:
        return set()
    try:
        session = (
            agent_state
            if isinstance(agent_state, AgentSessionView)
            else AgentSessionView.model_validate(agent_state)
        )
    except ValueError:
        return set()
    return {
        item.row_id
        for item in formulation_row_ownership(session, materials)
        if item.owner_type == FormulationRowOwnerType.SUPPLIER_MATERIAL
    }


def _direct_rows_from_agent(
    version_id: str,
    agent_state: dict[str, Any] | None,
    *,
    excluded_row_ids: set[str],
    store: RegulatoryStore,
    catalogue: IngredientCatalog | None,
    linkages: IngredientLinkageStore | None,
) -> list[DirectIngredient]:
    if not agent_state:
        return []
    try:
        session = AgentSessionView.model_validate(agent_state)
    except ValueError:
        return []
    output: list[DirectIngredient] = []
    for row in session.interpreted_rows:
        name = str(row.name.value or "").strip()
        if not name or row.row_id in excluded_row_ids:
            continue
        cas_number = str(row.cas_number.value).strip() if row.cas_number and row.cas_number.value else None
        ingredient = FormulationIngredientRequest(
            name=name,
            cas_number=cas_number,
            concentration=_agent_concentration(
                row.concentration.model_dump(mode="json") if row.concentration else None
            ),
            regulated_functions=row.regulated_functions,
        )
        evidence = [DocumentSourceEvidence(
            document_id=f"primary:{version_id}",
            page=(row.source_pages[0] if row.source_pages else None),
            source_row=row.source_row,
            source_snippet=(row.name.source_references[0].source_snippet
                            if row.name.source_references else None),
            raw_value=row.name.source_value,
        )]
        output.append(_resolved_direct(
            DirectIngredient(
                ingredient_id=f"agent:{row.row_id}",
                ingredient=ingredient,
                source_document_id=f"primary:{version_id}",
                source_evidence=evidence,
            ),
            store=store,
            catalogue=catalogue,
            linkages=linkages,
        ))
    return output


def derive_assembly_state(
    *,
    version_id: str,
    formulation_name: str | None,
    agent_state: dict[str, Any] | None,
    documents: Iterable[dict[str, Any]],
    store: RegulatoryStore,
    catalogue: IngredientCatalog | None,
    linkages: IngredientLinkageStore | None,
) -> FormulationAssemblyState:
    source_document_ids: list[str] = []
    source_document_snapshots: dict[str, str] = {}
    source_document_metadata: dict[str, dict[str, str | None]] = {}
    material_candidates: dict[str, list[tuple[str, SupplierMaterial, bool, set[DocumentRole]]]] = {}
    direct_ingredients: list[DirectIngredient] = []

    for document in documents:
        extraction_payload = document.get("extraction_result")
        if not extraction_payload:
            continue
        extraction = DocumentExtraction.model_validate(extraction_payload)
        document_id = str(document["id"])
        source_document_ids.append(document_id)
        source_document_metadata[document_id] = {
            "original_filename": str(document.get("original_filename") or "") or None,
            "supplier_name": str(document.get("supplier_name") or "") or None,
            "trade_name": str(document.get("trade_name") or "") or None,
            "product_code": str(document.get("product_code") or "") or None,
        }
        extraction_key = str(
            document.get("attached_extraction_key")
            or document.get("processing_key")
            or f"revision:{document.get('revision', 0)}"
        )
        role_key = ",".join(sorted(str(value) for value in document.get("confirmed_roles") or []))
        source_document_snapshots[document_id] = (
            f"{ASSEMBLY_DERIVATION_VERSION}|{extraction_key}|revision:{document.get('revision', 0)}|"
            f"governing:{bool(document.get('governing_for_material'))}|roles:{role_key}"
        )
        confirmed_roles = {DocumentRole(item) for item in document.get("confirmed_roles") or []}
        # Older retained supplier documents may have a detected high-confidence
        # role but no confirmed role because role confirmation used to be a
        # separate UI step.  Treat the source-backed extraction schema as the
        # effective role so those documents calculate without being re-uploaded.
        recommended_role = {
            "supplier_composition": DocumentRole.SUPPLIER_COMPOSITION,
            "sds_composition": DocumentRole.SDS_MSDS,
        }.get(extraction.classification.recommended_extraction_schema)
        recommended_evidence = next(
            (
                item for item in extraction.classification.proposed_roles
                if item.role == recommended_role
            ),
            None,
        )
        inferred_supplier_role = bool(
            not (confirmed_roles & {DocumentRole.SUPPLIER_COMPOSITION, DocumentRole.SDS_MSDS})
            and
            extraction.supplier_materials
            and recommended_role
            and recommended_evidence
            and recommended_evidence.confidence in {"confirmed", "high"}
        )
        if inferred_supplier_role and recommended_role is not None:
            confirmed_roles = {recommended_role}
        is_supplier_document = bool(
            confirmed_roles & {DocumentRole.SUPPLIER_COMPOSITION, DocumentRole.SDS_MSDS}
            or extraction.supplier_materials
            and recommended_role in {DocumentRole.SUPPLIER_COMPOSITION, DocumentRole.SDS_MSDS}
        )
        for material in extraction.supplier_materials:
            resolved_rows = [
                _resolve_constituent(
                    constituent,
                    document_id=document_id,
                    extraction=extraction,
                    store=store,
                    catalogue=catalogue,
                    linkages=linkages,
                )
                for constituent in material.constituents
            ]
            # Automatic role recognition means "this is a supplier file"; it
            # does not mean every revision of the same material is current.
            # Only an explicit choice governs a multi-revision group. A lone
            # recognised supplier file is selected automatically below.
            governing = bool(document.get("governing_for_material"))
            disclosure = (
                DisclosureStatus.PARTIAL
                if DocumentRole.SDS_MSDS in confirmed_roles
                else material.disclosure_status
            )
            normalized = material.model_copy(update={
                "attached_document_ids": [document_id],
                "governing_document_id": document_id if governing else None,
                "constituents": resolved_rows,
                "disclosure_status": disclosure,
                "confirmation_status": (
                    ConfirmationStatus.CONFIRMED if governing
                    else ConfirmationStatus.NEEDS_CONFIRMATION
                ),
            })
            normalized_supplier = " ".join((normalized.supplier_name or "").casefold().split())
            normalized_trade = sorted(_commercial_aliases(normalized.trade_name))[0]
            normalized_codes = sorted(_commercial_aliases(normalized.product_code))
            normalized_code = normalized_codes[0] if normalized_codes else ""
            material_key = (
                f"code:{normalized_code}"
                if normalized_code else f"supplier:{normalized_supplier}|trade:{normalized_trade}"
            )
            material_candidates.setdefault(material_key, []).append(
                (document_id, normalized, governing, confirmed_roles)
            )
        # A supplier composition describes constituents inside a commercial
        # parent material. Its rows must never also be treated as direct
        # finished-product additions, even when an older extraction snapshot
        # retained both representations.
        if not is_supplier_document:
            direct_ingredients.extend(
                _resolved_direct(
                    row,
                    store=store,
                    catalogue=catalogue,
                    linkages=linkages,
                )
                for row in extraction.direct_ingredients
            )

    agent_usage = _agent_material_usage_by_row_id(agent_state)
    materials: list[SupplierMaterial] = []
    for material_key, candidates in material_candidates.items():
        ordered = sorted(candidates, key=lambda item: item[0])
        governing_candidates = [item for item in ordered if item[2]]
        if (
            not governing_candidates
            and len(ordered) == 1
            and ordered[0][3] & {DocumentRole.SUPPLIER_COMPOSITION, DocumentRole.SDS_MSDS}
        ):
            governing_candidates = [ordered[0]]
        selected = governing_candidates[0] if len(governing_candidates) == 1 else ordered[0]
        selected_document_id, selected_material, _, selected_roles = selected
        attached_document_ids = [item[0] for item in ordered]
        conflict_ids = (
            attached_document_ids
            if len(ordered) > 1 and len(governing_candidates) != 1
            else []
        )
        stable_id = selected_material.material_id
        if len(ordered) > 1:
            digest = hashlib.sha256(material_key.encode("utf-8")).hexdigest()[:16]
            stable_id = f"material-group:{digest}"
        disclosure = (
            DisclosureStatus.PARTIAL
            if DocumentRole.SDS_MSDS in selected_roles
            else selected_material.disclosure_status
        )
        materials.append(selected_material.model_copy(update={
            "material_id": stable_id,
            "attached_document_ids": attached_document_ids,
            "governing_document_id": (
                selected_document_id if len(governing_candidates) == 1 else None
            ),
            "conflicting_document_ids": conflict_ids,
            "finished_product_usage": None,
            "disclosure_status": disclosure,
            "confirmation_status": (
                ConfirmationStatus.CONFIRMED
                if len(governing_candidates) == 1 and not conflict_ids
                else ConfirmationStatus.NEEDS_CONFIRMATION
            ),
        }))

    row_ownership = formulation_row_ownership(agent_state, materials)
    usage_by_material: dict[str, dict[str, CompositionQuantity]] = {}
    for owner in row_ownership:
        usage = agent_usage.get(owner.row_id)
        if (
            usage is not None
            and owner.owner_type == FormulationRowOwnerType.SUPPLIER_MATERIAL
            and owner.material_id is not None
        ):
            usage_by_material.setdefault(owner.material_id, {})[owner.row_id] = usage
    materials = [
        material.model_copy(update={
            "finished_product_usage": (
                next(iter(candidates.values())) if len(candidates) == 1 else None
            ),
        })
        for material in materials
        for candidates in [usage_by_material.get(material.material_id, {})]
    ]

    excluded_row_ids = {
        item.row_id for item in row_ownership
        if item.owner_type == FormulationRowOwnerType.SUPPLIER_MATERIAL
    }

    direct_ingredients.extend(_direct_rows_from_agent(
        version_id,
        agent_state,
        excluded_row_ids=excluded_row_ids,
        store=store,
        catalogue=catalogue,
        linkages=linkages,
    ))
    unique_direct: dict[str, DirectIngredient] = {
        row.ingredient_id: row for row in direct_ingredients
    }
    return FormulationAssemblyState(
        direct_ingredients=list(unique_direct.values()),
        materials=materials,
        formulation_row_ownership=row_ownership,
        source_document_ids=sorted(set(source_document_ids + [f"primary:{version_id}"])),
        source_document_snapshots=source_document_snapshots,
        source_document_metadata=source_document_metadata,
        formulation_name=formulation_name,
    )


def prepare_trade_name_assembly(
    *,
    assembly_revision: int,
    state: FormulationAssemblyState,
    formulation_id: str | None,
    source_filename: str | None,
    store: RegulatoryStore,
    catalogue: IngredientCatalog | None,
    linkages: IngredientLinkageStore | None,
) -> tuple[FormulationAssemblyState, PreparedAssembly]:
    direct = [
        _resolved_direct(row, store=store, catalogue=catalogue, linkages=linkages)
        for row in state.direct_ingredients
    ]
    materials = [
        material.model_copy(update={
            "constituents": [
                constituent.model_copy(update={
                    "verified_identity_group": _identity_group(
                        store,
                        catalogue,
                        linkages,
                        constituent.submitted_name,
                        constituent.cas_number,
                    ),
                })
                for constituent in material.constituents
            ],
        })
        for material in state.materials
    ]
    normalized_state = state.model_copy(update={
        "direct_ingredients": direct,
        "materials": materials,
    })
    prepared = prepare_assembly(
        assembly_revision=assembly_revision,
        direct_ingredients=direct,
        materials=materials,
        formulation_id=formulation_id,
        formulation_name=state.formulation_name,
        product_context=state.product_context,
        product_applicability=state.product_applicability,
        source_filename=source_filename,
        source_document_ids=state.source_document_ids,
        source_document_metadata=state.source_document_metadata,
    )
    return normalized_state, prepared
