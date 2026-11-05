from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.services.ingredient_catalog import load_accepted_ingredient_catalog
from backend.app.services.loader import SINGAPORE_SECTIONS, load_accepted_store


DATASET_VERSION = "eu-sg-linkage__eu-glossary-2025-1175__acd-2026-1__sg-2025-12-01__parts-i-v-r1"
SINGAPORE_BASELINE = "acd-2026-1__sg-2025-12-01__parts-i-v-r1"
SCREENED_SCOPE = [
    "Third Schedule Part I",
    "Third Schedule Part II",
    "Third Schedule Part III",
    "Third Schedule Part IV",
    "Third Schedule Part V",
]
ROOT = Path(__file__).resolve().parents[4]
LINKAGE_ROOT = ROOT / "data_pipeline" / "identity" / "eu_singapore_linkage"


class LinkageValidationError(ValueError):
    """Raised when human linkage input is not safe to accept."""


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_nonblank(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LinkageValidationError(f"{field} must be a nonblank string")
    return value.strip()


def _validate_reviewed_at(value: Any) -> str:
    text = _require_nonblank(value, "review.reviewed_at")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise LinkageValidationError("review.reviewed_at must be an ISO date or datetime") from error
    return text


def _catalogue_by_id(catalogue) -> dict[str, dict[str, Any]]:
    return {item["ingredient_id"]: item for item in catalogue.ingredients}


def _target_from_rule(store, rule: dict[str, Any]) -> dict[str, Any]:
    substance_id = rule.get("substance_id")
    if not substance_id or substance_id not in store.substances_by_id:
        raise LinkageValidationError(f"Rule {rule['rule_id']} has no accepted Singapore substance identity")
    substance = store.substances_by_id[substance_id]
    return {
        "raw_record_id": rule["raw_record_id"],
        "rule_id": rule["rule_id"],
        "substance_id": substance_id,
        "part": rule["regulatory_section"],
        "reference": rule["reference_number"],
        "source_substance_name": rule["substance_name"],
        "source_document": rule["source_document"],
        "source_hash": substance["source_hash"],
        "source_pages": rule["source_pages"],
        "source_text": rule["source_text"],
    }


def _derive_targets(store, raw_record_ids: list[str]) -> list[dict[str, Any]]:
    if len(raw_record_ids) != len(set(raw_record_ids)):
        raise LinkageValidationError("singapore_raw_record_ids contains duplicates")
    targets: list[dict[str, Any]] = []
    for raw_record_id in raw_record_ids:
        _require_nonblank(raw_record_id, "singapore_raw_record_ids[]")
        rules = store.rules_by_raw_record_id.get(raw_record_id, ())
        scoped = [rule for rule in rules if rule["regulatory_section"] in SINGAPORE_SECTIONS]
        if not scoped:
            raise LinkageValidationError(
                f"Singapore target {raw_record_id} is unknown or outside Third Schedule Parts I-V"
            )
        if any(not rule["active"] for rule in scoped):
            raise LinkageValidationError(f"Singapore target {raw_record_id} contains an inactive rule")
        targets.extend(_target_from_rule(store, rule) for rule in scoped)
    unique = {target["rule_id"]: target for target in targets}
    return sorted(
        unique.values(),
        key=lambda item: (item["part"], item["reference"].casefold(), item["rule_id"]),
    )


def _bindings(catalogue, store) -> dict[str, Any]:
    return {
        "identity_dataset_version": catalogue.dataset_version,
        "identity_dataset_hash": catalogue.baseline_manifest_hash,
        "singapore_regulatory_baseline": SINGAPORE_BASELINE,
        "singapore_regulatory_baseline_hash": store.baseline_manifest_hash,
        "screened_scope": SCREENED_SCOPE,
    }


def build_review_queue(root: Path = ROOT) -> dict[str, Any]:
    catalogue = load_accepted_ingredient_catalog(root)
    store = load_accepted_store(root)
    linkage_root = root / "data_pipeline" / "identity" / "eu_singapore_linkage"
    scope = _load(linkage_root / "inputs" / "review_scope.json")
    by_id = _catalogue_by_id(catalogue)
    requested = scope.get("records", [])
    if not isinstance(requested, list):
        raise LinkageValidationError("Review scope records must be a list")
    requested_ids = [item.get("catalogue_ingredient_id") for item in requested]
    if None in requested_ids or len(requested_ids) != len(set(requested_ids)):
        raise LinkageValidationError("Review scope must contain unique catalogue ingredient IDs")
    accepted_ids: set[str] = set()
    accepted_path = linkage_root / "accepted" / "linkages.json"
    if accepted_path.exists():
        accepted = _load(accepted_path)
        if (
            accepted.get("dataset_version") == DATASET_VERSION
            and accepted.get("singapore_regulatory_baseline") == SINGAPORE_BASELINE
        ):
            accepted_ids = {
                record["catalogue_ingredient_id"]
                for record in accepted.get("records", [])
                if isinstance(record, dict) and record.get("catalogue_ingredient_id")
            }
    requested = [
        record
        for record in requested
        if record.get("catalogue_ingredient_id") not in accepted_ids
    ]
    records = []
    for requested_record in requested:
        ingredient_id = requested_record["catalogue_ingredient_id"]
        ingredient = by_id.get(ingredient_id)
        if ingredient is None:
            raise LinkageValidationError(f"Review scope contains unknown catalogue ID {ingredient_id}")
        exact_substances = [
            substance
            for substance in store.substances_by_name.get(ingredient["search_name"], ())
            if substance["regulatory_section"] in SINGAPORE_SECTIONS
        ]
        candidates: list[dict[str, Any]] = []
        for substance in exact_substances:
            for rule in store.rules_by_substance_id.get(substance["substance_id"], ()):
                if rule["regulatory_section"] in SINGAPORE_SECTIONS and rule["active"]:
                    candidates.append(_target_from_rule(store, rule))
        candidates = sorted(
            {item["rule_id"]: item for item in candidates}.values(),
            key=lambda item: (item["part"], item["reference"].casefold(), item["rule_id"]),
        )
        proposed_targets = _derive_targets(store, requested_record.get("proposed_singapore_raw_record_ids", []))
        supporting_acd_records = []
        for raw_record_id in requested_record.get("supporting_acd_raw_record_ids", []):
            raw = store.raw_by_id.get(raw_record_id)
            if raw is None or not str(raw.get("section", "")).startswith("Annex"):
                raise LinkageValidationError(f"Supporting ACD record {raw_record_id} is unavailable")
            supporting_acd_records.append({
                "raw_record_id": raw_record_id,
                "regulatory_section": raw["section"],
                "reference_number": raw["reference_number"],
                "source_pages": raw["source_pages"],
                "source_text": raw["source_text"],
                "source_document": raw["source_document"],
            })
        records.append(
            {
                "catalogue_ingredient_id": ingredient_id,
                "catalogue_canonical_name": ingredient["canonical_name"],
                "eu_source_entries": ingredient["source_entries"],
                "eu_source_pages": ingredient["source_pages"],
                "eu_raw_record_ids": ingredient["raw_record_ids"],
                "candidate_generation_method": "exact_normalized_name_equality",
                "singapore_candidates": candidates,
                "proposed_singapore_targets": proposed_targets,
                "supporting_acd_records": supporting_acd_records,
                "supported_names": requested_record.get("supported_names", []),
                "supported_cas_numbers": requested_record.get("supported_cas_numbers", []),
                "supported_ci_numbers": requested_record.get("supported_ci_numbers", []),
                "identity_group": requested_record.get("identity_group"),
                "forms": requested_record.get("forms", []),
                "target_relationships": requested_record.get("target_relationships", []),
                "proposed_review_basis": requested_record.get("review_basis"),
                "reason_for_review": (
                    "Exact normalized Singapore candidate identified; professional verification is required."
                    if candidates
                    else "No deterministic Singapore candidate identified."
                ),
                "current_status": "unresolved",
            }
        )
    return {
        "dataset_version": DATASET_VERSION,
        **_bindings(catalogue, store),
        "candidate_count": len(records),
        "records": records,
    }


def _review_queue_markdown(queue: dict[str, Any]) -> str:
    lines = [
        "# EU-to-Singapore identity linkage review queue",
        "",
        f"Dataset: `{queue['dataset_version']}`",
        f"Pending identities: **{queue['candidate_count']}**",
        "Scope: Third Schedule Parts I-V",
        "",
        "Candidate entries are not accepted linkage decisions.",
        "",
    ]
    for item in queue["records"]:
        lines.extend(
            [
                f"## {item['catalogue_canonical_name']}",
                "",
                f"- EU catalogue ID: `{item['catalogue_ingredient_id']}`",
                f"- EU entry: {', '.join(map(str, item['eu_source_entries']))}",
                f"- EU page: {', '.join(map(str, item['eu_source_pages']))}",
                f"- Current status: `{item['current_status']}`",
                f"- Review reason: {item['reason_for_review']}",
                "",
            ]
        )
        if item["singapore_candidates"]:
            for target in item["singapore_candidates"]:
                lines.append(
                    f"  - {target['part']} · Ref {target['reference']} · {target['source_substance_name']}"
                )
            lines.append("")
        if item.get("proposed_singapore_targets"):
            lines.append("Proposed Singapore targets:")
            for target in item["proposed_singapore_targets"]:
                lines.append(f"  - {target['part']} · Ref {target['reference']} · pages {', '.join(map(str, target['source_pages']))} · {target['source_substance_name']}")
                lines.append("")
                lines.append("    Source text:")
                lines.append("")
                lines.append(f"    > {target['source_text'].replace(chr(10), ' ')}")
            lines.append("")
        for source in item.get("supporting_acd_records", []):
            lines.append(f"Supporting ACD source: {source['regulatory_section']} Ref {source['reference_number']} · pages {', '.join(map(str, source['source_pages']))}")
            lines.append("")
            lines.append(f"> {source['source_text'].replace(chr(10), ' ')}")
            lines.append("")
        lines.append(f"Proposed identity evidence: names `{', '.join(item.get('supported_names', []))}`; CAS `{', '.join(item.get('supported_cas_numbers', [])) or 'none'}`; CI `{', '.join(item.get('supported_ci_numbers', [])) or 'none'}`.")
        lines.append("")
        lines.append(f"Review check: {item.get('proposed_review_basis')}")
        lines.append("")
        lines.append("Decision: **PENDING HUMAN SIGN-OFF**")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def validate_review_input(review_input: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    catalogue = load_accepted_ingredient_catalog(root)
    store = load_accepted_store(root)
    expected = _bindings(catalogue, store)
    for field, value in expected.items():
        if review_input.get(field) != value:
            raise LinkageValidationError(
                f"Review input {field} does not match the active accepted baseline"
            )
    decisions = review_input.get("decisions")
    if not isinstance(decisions, list):
        raise LinkageValidationError("decisions must be a list")
    by_id = _catalogue_by_id(catalogue)
    seen_ids: set[str] = set()
    records: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            raise LinkageValidationError("Each review decision must be an object")
        ingredient_id = _require_nonblank(
            decision.get("catalogue_ingredient_id"), "catalogue_ingredient_id"
        )
        if ingredient_id in seen_ids:
            raise LinkageValidationError(f"Duplicate catalogue decision {ingredient_id}")
        seen_ids.add(ingredient_id)
        ingredient = by_id.get(ingredient_id)
        if ingredient is None:
            raise LinkageValidationError(f"Unknown catalogue ingredient {ingredient_id}")
        supplied_name = _require_nonblank(
            decision.get("catalogue_canonical_name"), "catalogue_canonical_name"
        )
        if supplied_name != ingredient["canonical_name"]:
            raise LinkageValidationError(
                f"Catalogue name for {ingredient_id} does not match the accepted identity source"
            )
        status = decision.get("status")
        if status not in {"linked", "verified_not_represented", "unresolved"}:
            raise LinkageValidationError(f"Unsupported linkage status {status!r}")
        raw_ids = decision.get("singapore_raw_record_ids", [])
        if not isinstance(raw_ids, list) or not all(isinstance(value, str) for value in raw_ids):
            raise LinkageValidationError("singapore_raw_record_ids must be a list of strings")
        if status == "linked" and not raw_ids:
            raise LinkageValidationError("linked decisions require at least one Singapore raw record")
        if status != "linked" and raw_ids:
            raise LinkageValidationError(f"{status} decisions cannot contain accepted Singapore targets")
        targets = _derive_targets(store, raw_ids)
        supported_names = decision.get("supported_names", [])
        supported_cas = decision.get("supported_cas_numbers", [])
        supported_ci = decision.get("supported_ci_numbers", [])
        if not all(isinstance(value, str) and value.strip() for values in (supported_names, supported_cas, supported_ci) for value in values):
            raise LinkageValidationError("Supported identity values must be nonblank strings")
        for cas in supported_cas:
            from data_pipeline.scripts.normalize import cas_is_valid
            if not cas_is_valid(cas):
                raise LinkageValidationError(f"Invalid supported CAS {cas}")
        supporting_acd_records = []
        for raw_record_id in decision.get("supporting_acd_raw_record_ids", []):
            raw = store.raw_by_id.get(raw_record_id)
            if raw is None or not str(raw.get("section", "")).startswith("Annex"):
                raise LinkageValidationError(f"Supporting ACD record {raw_record_id} is unavailable")
            supporting_acd_records.append({
                "raw_record_id": raw_record_id,
                "regulatory_section": raw["section"],
                "reference_number": raw["reference_number"],
                "source_pages": raw["source_pages"],
                "source_text": raw["source_text"],
                "source_document": raw["source_document"],
            })
        review = decision.get("review")
        if not isinstance(review, dict) or review.get("reviewed") is not True:
            raise LinkageValidationError("Every accepted decision must have review.reviewed=true")
        reviewed_at = _validate_reviewed_at(review.get("reviewed_at"))
        reviewer = _require_nonblank(review.get("reviewer"), "review.reviewer")
        review_basis = _require_nonblank(review.get("review_basis"), "review.review_basis")
        notes = review.get("notes", "")
        if not isinstance(notes, str):
            raise LinkageValidationError("review.notes must be a string")
        linkage_id = f"eu-sg-link-{ingredient_id}-{SINGAPORE_BASELINE}"
        records.append(
            {
                "linkage_id": linkage_id,
                "catalogue_ingredient_id": ingredient_id,
                "catalogue_canonical_name": ingredient["canonical_name"],
                **expected,
                "status": status,
                "singapore_targets": targets,
                "supported_names": sorted(set(supported_names), key=str.casefold),
                "supported_cas_numbers": sorted(set(supported_cas)),
                "supported_ci_numbers": sorted(set(supported_ci), key=str.casefold),
                "supporting_acd_records": supporting_acd_records,
                "identity_group": decision.get("identity_group"),
                "forms": decision.get("forms", []),
                "target_relationships": decision.get("target_relationships", []),
                "review": {
                    "reviewed": True,
                    "reviewed_at": reviewed_at,
                    "reviewer": reviewer,
                    "review_basis": review_basis,
                    "notes": notes,
                },
            }
        )
    records.sort(key=lambda item: item["catalogue_ingredient_id"])
    counts = Counter(record["status"] for record in records)
    return {
        "dataset_version": DATASET_VERSION,
        **expected,
        "counts": {
            "accepted_records": len(records),
            "linked": counts["linked"],
            "verified_not_represented": counts["verified_not_represented"],
            "unresolved": counts["unresolved"],
        },
        "records": records,
    }


def build_accepted(root: Path = ROOT) -> dict[str, Any]:
    linkage_root = root / "data_pipeline" / "identity" / "eu_singapore_linkage"
    input_path = linkage_root / "inputs" / "review_decisions.json"
    accepted = validate_review_input(_load(input_path), root)
    accepted_path = linkage_root / "accepted" / "linkages.json"
    _write(accepted_path, accepted)
    manifest = {
        "dataset_version": DATASET_VERSION,
        "identity_dataset_version": accepted["identity_dataset_version"],
        "identity_dataset_hash": accepted["identity_dataset_hash"],
        "singapore_regulatory_baseline": accepted["singapore_regulatory_baseline"],
        "singapore_regulatory_baseline_hash": accepted["singapore_regulatory_baseline_hash"],
        "screened_scope": accepted["screened_scope"],
        "counts": accepted["counts"],
        "review_input_sha256": _sha256(input_path),
        "generated_output_hashes": {
            "data_pipeline/identity/eu_singapore_linkage/accepted/linkages.json": _sha256(
                accepted_path
            )
        },
    }
    _write(linkage_root / "accepted" / "accepted_linkage_hashes.json", manifest)
    report = {
        "dataset_version": DATASET_VERSION,
        "status": "PASS",
        "errors": [],
        "counts": accepted["counts"],
        "review_input_sha256": manifest["review_input_sha256"],
    }
    _write(linkage_root / "reports" / "validation_report.json", report)
    (linkage_root / "reports").mkdir(parents=True, exist_ok=True)
    (linkage_root / "reports" / "validation_summary.md").write_text(
        "# Linkage validation\n\n"
        "**PASS** — accepted decisions are structurally valid and bound to the accepted source baselines.\n\n"
        f"Accepted records: **{accepted['counts']['accepted_records']}**\n"
        f"Linked: **{accepted['counts']['linked']}**\n"
        f"Verified not represented: **{accepted['counts']['verified_not_represented']}**\n"
        f"Unresolved reviewed decisions: **{accepted['counts']['unresolved']}**\n",
        encoding="utf-8",
    )
    return accepted


def write_candidates(root: Path = ROOT) -> dict[str, Any]:
    linkage_root = root / "data_pipeline" / "identity" / "eu_singapore_linkage"
    queue = build_review_queue(root)
    _write(linkage_root / "candidate" / "review_queue.json", queue)
    (linkage_root / "reports").mkdir(parents=True, exist_ok=True)
    (linkage_root / "reports" / "review_queue.md").write_text(
        _review_queue_markdown(queue), encoding="utf-8"
    )
    return queue


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the accepted EU-to-Singapore linkage layer")
    parser.add_argument(
        "command", choices=("candidates", "validate-review", "build-accepted")
    )
    args = parser.parse_args()
    if args.command == "candidates":
        queue = write_candidates()
        print(f"Generated {queue['candidate_count']} review-queue records")
    if args.command == "validate-review":
        document = _load(LINKAGE_ROOT / "inputs" / "review_decisions.json")
        accepted = validate_review_input(document)
        print(json.dumps(accepted["counts"], sort_keys=True))
    if args.command == "build-accepted":
        accepted = build_accepted()
        print(f"Built {accepted['counts']['accepted_records']} accepted linkage records")


if __name__ == "__main__":
    main()
