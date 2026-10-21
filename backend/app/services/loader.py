from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_pipeline.scripts.normalize import cas_is_valid, conservative_text
from backend.app.services.search_names import derived_except_search_name


SINGAPORE_SECTIONS = {
    "Third Schedule Part I",
    "Third Schedule Part II",
    "Third Schedule Part III",
    "Third Schedule Part IV",
    "Third Schedule Part V",
}
ACD_SECTIONS = {"Annex II Part 1", "Annex III Part 1", "Annex IV Part 1", "Annex VI", "Annex VII"}
REGULATORY_SEARCH_SCOPE = (
    "Third Schedule Part I",
    "Third Schedule Part II",
    "Annex II Part 1",
    "Annex III Part 1",
)
ALL_REGULATORY_SEARCH_SCOPE = (
    *REGULATORY_SEARCH_SCOPE,
    "Third Schedule Part III",
    "Third Schedule Part IV",
    "Third Schedule Part V",
    "Annex IV Part 1",
    "Annex VI",
    "Annex VII",
)


class AcceptedBaselineError(RuntimeError):
    """Raised when runtime data does not match the reviewed baseline."""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tuples(mapping: dict[Any, list[dict[str, Any]]]) -> dict[Any, tuple[dict[str, Any], ...]]:
    return {key: tuple(value) for key, value in mapping.items()}


@dataclass(frozen=True)
class RegulatoryStore:
    root: Path
    dataset_version: str
    baseline_manifest_hash: str
    product_context: dict[str, Any]
    provisions_document: dict[str, Any]
    rules_by_id: dict[str, dict[str, Any]]
    substances_by_id: dict[str, dict[str, Any]]
    raw_by_id: dict[str, dict[str, Any]]
    source_manifest_document: dict[str, Any]
    source_documents_by_id: dict[str, dict[str, Any]]
    source_snapshots: tuple[dict[str, Any], ...]
    cross_references: tuple[dict[str, Any], ...]
    rules_by_substance_id: dict[str, tuple[dict[str, Any], ...]]
    executable_singapore_rules_by_substance_id: dict[str, tuple[dict[str, Any], ...]]
    inactive_rules_by_substance_id: dict[str, tuple[dict[str, Any], ...]]
    substances_by_name: dict[str, tuple[dict[str, Any], ...]]
    substances_by_derived_search_name: dict[str, tuple[dict[str, Any], ...]]
    substances_by_cas: dict[str, tuple[dict[str, Any], ...]]
    substances_by_ci: dict[str, tuple[dict[str, Any], ...]]
    singapore_rules_by_reference: dict[str, tuple[dict[str, Any], ...]]
    singapore_rules_by_schedule_reference: dict[tuple[str, str], tuple[dict[str, Any], ...]]
    rules_by_raw_record_id: dict[str, tuple[dict[str, Any], ...]]
    cross_references_by_id: dict[str, dict[str, Any]]
    cross_references_by_rule_id: dict[str, tuple[dict[str, Any], ...]]
    provisions_by_id: dict[str, dict[str, Any]]
    source_backed_contexts: dict[str, str]
    singapore_rules_by_function: dict[str, tuple[dict[str, Any], ...]]
    positive_list_functions: frozenset[str]
    regulatory_search_scope: tuple[str, ...]

    def linked_singapore_substances(self, acd_substance_id: str) -> tuple[dict[str, Any], ...]:
        linked: dict[str, dict[str, Any]] = {}
        for rule in self.rules_by_substance_id.get(acd_substance_id, ()):
            for cross_reference in self.cross_references_by_rule_id.get(rule["rule_id"], ()):
                for singapore_rule_id in cross_reference["singapore_rule_ids"]:
                    singapore_rule = self.rules_by_id[singapore_rule_id]
                    substance_id = singapore_rule.get("substance_id")
                    if substance_id:
                        linked[substance_id] = self.substances_by_id[substance_id]
        return tuple(linked[key] for key in sorted(linked))


def load_accepted_store(root: Path | None = None) -> RegulatoryStore:
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    baseline_path = root / "data_pipeline" / "accepted_output_hashes.json"
    spot_check_path = root / "data_pipeline" / "reports" / "manual_spot_check_results.json"
    if not baseline_path.exists() or not spot_check_path.exists():
        raise AcceptedBaselineError("Accepted baseline or completed spot-check record is missing")

    baseline_hash = _sha256(baseline_path)
    spot_checks = _load_json(spot_check_path)
    if baseline_hash.casefold() != spot_checks.get("accepted_baseline_sha256", "").casefold():
        raise AcceptedBaselineError("Accepted baseline manifest does not match the reviewed spot-check baseline")

    baseline = _load_json(baseline_path)
    expected_hashes = baseline.get("generated_output_hashes", {})
    if not expected_hashes:
        raise AcceptedBaselineError("Accepted baseline contains no generated output hashes")
    for relative_path, expected_hash in expected_hashes.items():
        path = root / relative_path
        if not path.exists():
            raise AcceptedBaselineError(f"Accepted runtime file is missing: {relative_path}")
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise AcceptedBaselineError(f"Accepted runtime file hash mismatch: {relative_path}")

    processed_root = root / "data_pipeline" / "processed"
    raw_root = root / "data_pipeline" / "raw"
    product_context = _load_json(processed_root / "product_context.json")
    rules_document = _load_json(processed_root / "rules.json")
    substances_document = _load_json(processed_root / "substances.json")
    provisions_document = _load_json(processed_root / "singapore_provisions.json")
    cross_reference_document = _load_json(processed_root / "source_cross_references.json")
    source_manifest_document = _load_json(raw_root / "source_manifest.json")
    raw_names = (
            "annex_ii_raw.json",
            "annex_iii_raw.json",
            "annex_iv_raw.json",
            "annex_vi_raw.json",
            "annex_vii_raw.json",
            "singapore_third_schedule_part_i_raw.json",
            "singapore_third_schedule_part_ii_raw.json",
            "singapore_third_schedule_part_iii_raw.json",
            "singapore_third_schedule_part_iv_raw.json",
            "singapore_third_schedule_part_v_raw.json",
        )
    raw_documents = [_load_json(raw_root / name) for name in raw_names if (raw_root / name).exists()]

    dataset_version = baseline["dataset_version"]
    versioned_documents = [
        product_context,
        rules_document,
        substances_document,
        provisions_document,
        cross_reference_document,
        source_manifest_document,
        *raw_documents,
    ]
    mismatched = [document.get("dataset_version") for document in versioned_documents if document.get("dataset_version") != dataset_version]
    if mismatched:
        raise AcceptedBaselineError(f"Dataset version mismatch in accepted runtime files: {mismatched}")

    rules = rules_document["rules"]
    substances = substances_document["substances"]
    cross_references = tuple(cross_reference_document["cross_references"])
    rules_by_id = {rule["rule_id"]: rule for rule in rules}
    substances_by_id = {substance["substance_id"]: substance for substance in substances}
    raw_by_id = {
        record["raw_record_id"]: record
        for document in raw_documents
        for record in document["records"]
    }

    rules_by_substance: dict[str, list[dict[str, Any]]] = defaultdict(list)
    executable_rules: dict[str, list[dict[str, Any]]] = defaultdict(list)
    inactive_rules: dict[str, list[dict[str, Any]]] = defaultdict(list)
    singapore_by_reference: dict[str, list[dict[str, Any]]] = defaultdict(list)
    singapore_by_schedule_reference: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    rules_by_raw_record: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rules_by_function: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rule in rules:
        substance_id = rule.get("substance_id")
        if substance_id:
            rules_by_substance[substance_id].append(rule)
            if rule["regulatory_section"] in SINGAPORE_SECTIONS:
                if rule["active"] and rule["normalization_status"] == "normalized":
                    executable_rules[substance_id].append(rule)
                elif not rule["active"] or rule["normalization_status"] == "inactive_source_entry":
                    inactive_rules[substance_id].append(rule)
        if rule["regulatory_section"] in SINGAPORE_SECTIONS:
            singapore_by_reference[rule["reference_number"].casefold()].append(rule)
            singapore_by_schedule_reference[
                (rule["regulatory_section"], rule["reference_number"].casefold())
            ].append(rule)
        rules_by_raw_record[rule["raw_record_id"]].append(rule)
        if rule["regulatory_section"] in SINGAPORE_SECTIONS and rule.get("permitted_function"):
            rules_by_function[rule["permitted_function"]].append(rule)

    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_derived_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_cas: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_ci: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for substance in substances:
        if not substance["active"]:
            continue
        by_name[substance["normalized_substance_name"]].append(substance)
        derived_name = derived_except_search_name(substance["original_substance_name"])
        if derived_name:
            by_derived_name[conservative_text(derived_name)].append(substance)
        for cas_number in substance["cas_numbers"]:
            if cas_is_valid(cas_number):
                by_cas[cas_number].append(substance)

    for rule in rules:
        substance_id = rule.get("substance_id")
        substance = substances_by_id.get(substance_id) if substance_id else None
        if substance is None or not substance.get("active"):
            continue
        for ci_identifier in (rule.get("regulatory_identifiers") or {}).get("ci", []):
            key = conservative_text(str(ci_identifier))
            if key:
                by_ci[key][substance_id] = substance

    by_rule_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cross_reference in cross_references:
        for rule_id in cross_reference["acd_rule_ids"] + cross_reference["singapore_rule_ids"]:
            by_rule_id[rule_id].append(cross_reference)

    provisions_by_id = {item["provision_id"]: item for item in provisions_document["provisions"]}
    contexts: dict[str, str] = {}
    for rule in rules:
        if rule["regulatory_section"] in SINGAPORE_SECTIONS and rule.get("product_context"):
            contexts.setdefault(conservative_text(rule["product_context"]), rule["product_context"])

    return RegulatoryStore(
        root=root,
        dataset_version=dataset_version,
        baseline_manifest_hash=baseline_hash,
        product_context=product_context,
        provisions_document=provisions_document,
        rules_by_id=rules_by_id,
        substances_by_id=substances_by_id,
        raw_by_id=raw_by_id,
        source_manifest_document=source_manifest_document,
        source_documents_by_id={
            document["source_document"]: document
            for document in source_manifest_document["documents"]
        },
        source_snapshots=tuple(cross_reference_document["source_snapshots"]),
        cross_references=cross_references,
        rules_by_substance_id=_tuples(rules_by_substance),
        executable_singapore_rules_by_substance_id=_tuples(executable_rules),
        inactive_rules_by_substance_id=_tuples(inactive_rules),
        substances_by_name=_tuples(by_name),
        substances_by_derived_search_name=_tuples(by_derived_name),
        substances_by_cas=_tuples(by_cas),
        substances_by_ci={key: tuple(values[item] for item in sorted(values)) for key, values in by_ci.items()},
        singapore_rules_by_reference=_tuples(singapore_by_reference),
        singapore_rules_by_schedule_reference=_tuples(singapore_by_schedule_reference),
        rules_by_raw_record_id=_tuples(rules_by_raw_record),
        cross_references_by_id={item["cross_reference_id"]: item for item in cross_references},
        cross_references_by_rule_id=_tuples(by_rule_id),
        provisions_by_id=provisions_by_id,
        source_backed_contexts=contexts,
        singapore_rules_by_function=_tuples(rules_by_function),
        positive_list_functions=frozenset(rules_by_function),
        regulatory_search_scope=tuple(
            section for section in ALL_REGULATORY_SEARCH_SCOPE
            if any(rule["regulatory_section"] == section for rule in rules)
        ),
    )
