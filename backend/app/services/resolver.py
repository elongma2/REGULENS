from __future__ import annotations

from collections import defaultdict
import re
from typing import Iterable

from data_pipeline.scripts.normalize import cas_is_valid, conservative_text

from backend.app.models.screening import (
    CatalogueIdentity,
    IdentityCandidate,
    IdentityResolution,
    IdentitySourceType,
    IdentityStatus,
    SingaporeLinkageStatus,
)
from backend.app.services.ingredient_catalog import IDENTITY_SOURCE_NAME, IngredientCatalog
from backend.app.services.loader import ACD_SECTIONS, SINGAPORE_SECTIONS, RegulatoryStore


SAFE_BRIDGE_STATUS = "aligned"
CI_IDENTIFIER = re.compile(r"^\s*CI\s*[-:]?\s*(?P<identifier>\d{3,6}[A-Za-z]?)\s*$", re.IGNORECASE)


def _candidate(substance: dict, methods: Iterable[str], statuses: Iterable[str] = ()) -> IdentityCandidate:
    return IdentityCandidate(
        substance_id=substance["substance_id"],
        source_document=substance["source_document"],
        regulatory_section=substance["regulatory_section"],
        reference_number=substance["reference_number"],
        original_substance_name=substance["original_substance_name"],
        normalized_substance_name=substance["normalized_substance_name"],
        cas_numbers=substance["cas_numbers"],
        match_methods=sorted(set(methods)),
        cross_reference_statuses=sorted(set(statuses)),
    )


def _merge(candidates: Iterable[IdentityCandidate]) -> list[IdentityCandidate]:
    merged: dict[str, IdentityCandidate] = {}
    for candidate in candidates:
        current = merged.get(candidate.substance_id)
        if current is None:
            merged[candidate.substance_id] = candidate
            continue
        merged[candidate.substance_id] = current.model_copy(
            update={
                "match_methods": sorted(set(current.match_methods + candidate.match_methods)),
                "cross_reference_statuses": sorted(
                    set(current.cross_reference_statuses + candidate.cross_reference_statuses)
                ),
            }
        )
    return [merged[key] for key in sorted(merged)]


def _matches_for_substances(
    store: RegulatoryStore, substances: Iterable[dict], method: str
) -> tuple[list[IdentityCandidate], list[IdentityCandidate], dict[str, set[str]]]:
    singapore: list[IdentityCandidate] = []
    acd: list[IdentityCandidate] = []
    bridge_statuses: dict[str, set[str]] = defaultdict(set)
    for substance in substances:
        if substance["regulatory_section"] in SINGAPORE_SECTIONS:
            singapore.append(_candidate(substance, [method]))
            continue
        if substance["regulatory_section"] not in ACD_SECTIONS:
            continue
        acd_candidate = _candidate(substance, [method])
        acd.append(acd_candidate)
        for rule in store.rules_by_substance_id.get(substance["substance_id"], ()):
            for cross_reference in store.cross_references_by_rule_id.get(rule["rule_id"], ()):
                status = cross_reference["comparison_status"]
                for rule_id in cross_reference["singapore_rule_ids"]:
                    singapore_rule = store.rules_by_id[rule_id]
                    singapore_id = singapore_rule.get("substance_id")
                    if not singapore_id:
                        continue
                    bridge_statuses[singapore_id].add(status)
                    singapore_substance = store.substances_by_id[singapore_id]
                    singapore.append(_candidate(singapore_substance, [f"{method}_via_acd"], [status]))
    return _merge(singapore), _merge(acd), bridge_statuses


def _resolved_source(candidates: list[IdentityCandidate], substance_id: str) -> tuple[IdentitySourceType, str]:
    candidate = next(item for item in candidates if item.substance_id == substance_id)
    if any(not method.endswith("_via_acd") for method in candidate.match_methods):
        return IdentitySourceType.SINGAPORE_REGULATORY, "Singapore Third Schedule"
    return IdentitySourceType.ACD_REGULATORY, "ASEAN Cosmetic Directive"


def _is_one_chemical_identity(
    store: RegulatoryStore,
    substance_ids: set[str],
    supplied_cas: str | None = None,
) -> bool:
    if not substance_ids:
        return False
    substances = [store.substances_by_id[item] for item in substance_ids]
    names = {item["normalized_substance_name"] for item in substances if item["normalized_substance_name"]}
    if len(names) == 1:
        sections = {item["regulatory_section"] for item in substances}
        if len(sections) == len(substances):
            return True
        # A schedule can repeat one chemical under multiple reference numbers.
        # Merge duplicate entries from the same section only when every entry
        # is independently corroborated by the same CAS through an aligned ACD
        # cross-reference. Exact name equality alone is not enough.
        corroborated_cas_sets: list[set[str]] = []
        for substance in substances:
            cas_numbers = set(substance["cas_numbers"])
            for rule in store.rules_by_substance_id.get(substance["substance_id"], ()):
                for cross_reference in store.cross_references_by_rule_id.get(rule["rule_id"], ()):
                    if cross_reference["comparison_status"] != SAFE_BRIDGE_STATUS:
                        continue
                    for acd_rule_id in cross_reference["acd_rule_ids"]:
                        acd_substance_id = store.rules_by_id[acd_rule_id].get("substance_id")
                        if acd_substance_id:
                            cas_numbers.update(store.substances_by_id[acd_substance_id]["cas_numbers"])
            if not cas_numbers:
                break
            corroborated_cas_sets.append(cas_numbers)
        if (
            len(corroborated_cas_sets) == len(substances)
            and set.intersection(*corroborated_cas_sets)
        ):
            return True
    if supplied_cas and all(
        not item["cas_numbers"] or supplied_cas in item["cas_numbers"] for item in substances
    ):
        return any(supplied_cas in item["cas_numbers"] for item in substances)
    common_cas = set(substances[0]["cas_numbers"])
    for substance in substances[1:]:
        common_cas &= set(substance["cas_numbers"])
    return bool(common_cas)


def _resolved_group(
    candidates: list[IdentityCandidate], substance_ids: set[str]
) -> tuple[IdentitySourceType, str]:
    if any(
        candidate.substance_id in substance_ids
        and any(not method.endswith("_via_acd") for method in candidate.match_methods)
        for candidate in candidates
    ):
        return IdentitySourceType.SINGAPORE_REGULATORY, "Singapore Third Schedule"
    return IdentitySourceType.ACD_REGULATORY, "ASEAN Cosmetic Directive"


def _resolve_regulatory_ingredient(
    store: RegulatoryStore, name: str | None, cas_number: str | None
) -> IdentityResolution:
    name_sg: list[IdentityCandidate] = []
    name_acd: list[IdentityCandidate] = []
    name_statuses: dict[str, set[str]] = {}
    cas_sg: list[IdentityCandidate] = []
    cas_acd: list[IdentityCandidate] = []
    cas_statuses: dict[str, set[str]] = {}
    reasons: list[str] = []

    if name and name.strip():
        name_key = conservative_text(name)
        exact = _matches_for_substances(
            store, store.substances_by_name.get(name_key, ()), "exact_name"
        )
        derived = _matches_for_substances(
            store,
            store.substances_by_derived_search_name.get(name_key, ()),
            "derived_source_name_except_clause",
        )
        ci_match = CI_IDENTIFIER.fullmatch(name)
        ci = (
            _matches_for_substances(
                store,
                store.substances_by_ci.get(conservative_text(ci_match.group("identifier")), ()),
                "exact_ci",
            )
            if ci_match
            else ([], [], {})
        )
        name_sg = _merge([*exact[0], *derived[0], *ci[0]])
        name_acd = _merge([*exact[1], *derived[1], *ci[1]])
        name_statuses = defaultdict(set)
        for statuses in (exact[2], derived[2], ci[2]):
            for substance_id, values in statuses.items():
                name_statuses[substance_id].update(values)

    supplied_cas = cas_number.strip() if cas_number else None
    if supplied_cas:
        if cas_is_valid(supplied_cas):
            cas_sg, cas_acd, cas_statuses = _matches_for_substances(
                store, store.substances_by_cas.get(supplied_cas, ()), "exact_cas"
            )
        else:
            reasons.append("supplied_cas_is_malformed")

    all_sg = _merge([*name_sg, *cas_sg])
    all_acd = _merge([*name_acd, *cas_acd])
    name_ids = {item.substance_id for item in name_sg}
    cas_ids = {item.substance_id for item in cas_sg}

    def safe(candidate_id: str, statuses: dict[str, set[str]], candidates: list[IdentityCandidate]) -> bool:
        candidate = next((item for item in candidates if item.substance_id == candidate_id), None)
        if candidate and any(not method.endswith("_via_acd") for method in candidate.match_methods):
            return True
        values = statuses.get(candidate_id)
        return values is None or values == {SAFE_BRIDGE_STATUS}

    if name and name.strip() and supplied_cas:
        if not name_ids and not cas_ids and not name_acd and not cas_acd:
            return IdentityResolution(
                status=IdentityStatus.UNRESOLVED,
                singapore_candidates=all_sg,
                acd_candidates=all_acd,
                reasons=reasons + ["neither_name_nor_cas_resolved_to_a_source_backed_identity"],
            )
        common = name_ids & cas_ids
        grouped = common or ((name_ids | cas_ids) if name_ids and cas_ids else set())
        if grouped and _is_one_chemical_identity(store, grouped, supplied_cas):
            ordered_ids = sorted(grouped)
            common_id = ordered_ids[0]
            source_type, source_name = _resolved_group(all_sg, grouped)
            return IdentityResolution(
                status=IdentityStatus.RESOLVED,
                match_methods=sorted(
                    {
                        method
                        for candidate in [*name_sg, *cas_sg]
                        for method in candidate.match_methods
                    }
                ),
                singapore_candidates=all_sg,
                acd_candidates=all_acd,
                resolved_singapore_substance_id=common_id,
                resolved_singapore_substance_ids=ordered_ids,
                identity_source_type=source_type,
                identity_source_name=source_name,
            )
        if name_ids and cas_ids and not common:
            reasons.append("supplied_name_and_cas_resolve_to_different_singapore_identities")
        elif len(common) > 1:
            reasons.append("supplied_name_and_cas_have_multiple_common_singapore_identities")
        elif name_ids or cas_ids:
            reasons.append("only_one_supplied_identifier_provides_a_unique_corroborated_identity")
        else:
            reasons.append("supplied_identifiers_do_not_establish_a_unique_singapore_identity")
        return IdentityResolution(
            status=IdentityStatus.AMBIGUOUS if name_ids and cas_ids else IdentityStatus.REVIEW_REQUIRED,
            singapore_candidates=all_sg,
            acd_candidates=all_acd,
            reasons=reasons,
        )

    candidates = name_sg if name and name.strip() else cas_sg
    acd_candidates = name_acd if name and name.strip() else cas_acd
    statuses = name_statuses if name and name.strip() else cas_statuses
    ids = {item.substance_id for item in candidates}
    if ids and _is_one_chemical_identity(store, ids, supplied_cas):
        ordered_ids = sorted(ids)
        candidate_id = ordered_ids[0]
        if all(safe(item, statuses, candidates) for item in ordered_ids):
            source_type, source_name = _resolved_group(candidates, ids)
            return IdentityResolution(
                status=IdentityStatus.RESOLVED,
                match_methods=sorted({method for candidate in candidates for method in candidate.match_methods}),
                singapore_candidates=candidates,
                acd_candidates=acd_candidates,
                resolved_singapore_substance_id=candidate_id,
                resolved_singapore_substance_ids=ordered_ids,
                identity_source_type=source_type,
                identity_source_name=source_name,
            )
        reasons.append("singapore_identity_bridge_is_not_aligned")
        status = IdentityStatus.REVIEW_REQUIRED
    elif len(ids) > 1:
        reasons.append("identifier_matches_multiple_singapore_identities")
        status = IdentityStatus.AMBIGUOUS
    elif acd_candidates:
        reasons.append("exact_identity_exists_only_in_the_acd_snapshot")
        status = IdentityStatus.REVIEW_REQUIRED
    else:
        reasons.append("no_source_backed_identity_match")
        status = IdentityStatus.UNRESOLVED
    return IdentityResolution(
        status=status,
        singapore_candidates=candidates,
        acd_candidates=acd_candidates,
        identity_source_type=(IdentitySourceType.ACD_REGULATORY if acd_candidates else None),
        identity_source_name=("ASEAN Cosmetic Directive" if acd_candidates else None),
        reasons=reasons,
    )


def resolve_ingredient(
    store: RegulatoryStore,
    name: str | None,
    cas_number: str | None,
    ingredient_catalog: IngredientCatalog | None = None,
    catalogue_error: str | None = None,
) -> IdentityResolution:
    regulatory = _resolve_regulatory_ingredient(store, name, cas_number)
    if regulatory.status != IdentityStatus.UNRESOLVED or not (name and name.strip()):
        return regulatory

    if ingredient_catalog is None:
        if not catalogue_error:
            return regulatory
        return regulatory.model_copy(
            update={
                "status": IdentityStatus.REVIEW_REQUIRED,
                "reasons": ["ingredient_catalogue_unavailable_identity_verification_withheld"],
            }
        )

    ingredient = ingredient_catalog.find_exact_name(name)
    if ingredient is None:
        return regulatory
    catalogue_identity = CatalogueIdentity(
        ingredient_id=ingredient["ingredient_id"],
        canonical_name=ingredient["canonical_name"],
        source_name=IDENTITY_SOURCE_NAME,
        source_document=ingredient["source_document"],
        source_version=ingredient["source_version"],
        source_url=ingredient["source_url"],
        source_entries=ingredient["source_entries"],
        source_pages=ingredient["source_pages"],
        raw_record_ids=ingredient["raw_record_ids"],
        identity_dataset_version=ingredient_catalog.dataset_version,
        accepted_baseline_sha256=ingredient_catalog.baseline_manifest_hash,
    )
    reasons: list[str] = []
    if cas_number and cas_number.strip():
        reasons.append("supplied_cas_cannot_be_corroborated_by_catalogue_source")
        return IdentityResolution(
            status=IdentityStatus.REVIEW_REQUIRED,
            match_methods=["exact_catalogue_name"],
            singapore_candidates=regulatory.singapore_candidates,
            acd_candidates=regulatory.acd_candidates,
            identity_source_type=IdentitySourceType.INGREDIENT_CATALOGUE,
            identity_source_name=IDENTITY_SOURCE_NAME,
            singapore_linkage_status=SingaporeLinkageStatus.NOT_APPLICABLE,
            catalogue_identity=catalogue_identity,
            reasons=reasons,
        )
    return IdentityResolution(
        status=IdentityStatus.RESOLVED,
        match_methods=["exact_catalogue_name"],
        singapore_candidates=regulatory.singapore_candidates,
        acd_candidates=regulatory.acd_candidates,
        identity_source_type=IdentitySourceType.INGREDIENT_CATALOGUE,
        identity_source_name=IDENTITY_SOURCE_NAME,
        singapore_linkage_status=SingaporeLinkageStatus.NOT_APPLICABLE,
        catalogue_identity=catalogue_identity,
    )
