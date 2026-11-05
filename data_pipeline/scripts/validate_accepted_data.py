from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.app.services.ingredient_catalog import load_accepted_ingredient_catalog
from backend.app.services.ingredient_linkage import load_accepted_ingredient_linkages
from backend.app.services.loader import SINGAPORE_SECTIONS, load_accepted_store
from data_pipeline.identity.eu_common_ingredient_glossary.scripts.pipeline import validate as validate_catalogue
from data_pipeline.identity.eu_singapore_linkage.scripts.pipeline import build_review_queue
from data_pipeline.scripts.extract import write_json
from data_pipeline.scripts.normalize import cas_is_valid, conservative_text
from data_pipeline.scripts.validate_rules import validate as validate_rules
from backend.app.services.evaluation_issues import ISSUE_TEMPLATES, unmapped_issue_codes


ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = ROOT / "data_pipeline" / "reports"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_accepted_data() -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    source_verification: list[dict[str, Any]] = []

    accepted_json_roots = [
        ROOT / "data_pipeline" / "raw",
        ROOT / "data_pipeline" / "processed",
        ROOT / "data_pipeline" / "identity" / "eu_common_ingredient_glossary" / "raw",
        ROOT / "data_pipeline" / "identity" / "eu_common_ingredient_glossary" / "processed",
        ROOT / "data_pipeline" / "identity" / "eu_common_ingredient_glossary" / "accepted",
        ROOT / "data_pipeline" / "identity" / "eu_singapore_linkage" / "accepted",
    ]
    json_files = sorted(path for root in accepted_json_roots for path in root.glob("*.json"))
    for path in json_files:
        try:
            _load(path)
        except (OSError, json.JSONDecodeError) as error:
            errors.append({"area": "json", "code": "invalid_json", "path": path.relative_to(ROOT).as_posix(), "message": str(error)})

    regulatory = validate_rules()
    errors.extend({"area": "regulatory", **item} for item in regulatory["errors"])
    warnings.extend({"area": "regulatory", **item} for item in regulatory["warnings"])

    identity_root = ROOT / "data_pipeline" / "identity" / "eu_common_ingredient_glossary"
    catalogue_report = validate_catalogue(
        _load(identity_root / "raw" / "source_manifest.json"),
        _load(identity_root / "raw" / "ingredient_rows.json"),
        _load(identity_root / "processed" / "ingredients.json"),
    )
    errors.extend({"area": "catalogue", "code": "catalogue_validation", "message": value} for value in catalogue_report["errors"])
    warnings.extend({"area": "catalogue", "code": "catalogue_warning", "message": value} for value in catalogue_report["warnings"])

    store = load_accepted_store(ROOT)
    catalogue = load_accepted_ingredient_catalog(ROOT)
    linkages = load_accepted_ingredient_linkages(ROOT)
    queue = build_review_queue(ROOT)

    if missing_templates := sorted(unmapped_issue_codes()):
        errors.append({"area": "explanations", "code": "empty_issue_template", "issue_codes": missing_templates})

    for raw_path in sorted((ROOT / "data_pipeline" / "raw").glob("*_raw.json")):
        document = _load(raw_path)
        if "footnotes" not in document:
            # Older source sections expose other supporting material but do
            # not define a numbered footnote block that can be target-checked.
            continue
        footnotes = {str(item["footnote_number"]): item for item in document.get("footnotes", [])}
        for record in document.get("records", []):
            references = {str(value) for value in record.get("footnote_references", [])}
            missing_targets = sorted(references - set(footnotes))
            if missing_targets:
                errors.append({
                    "area": "regulatory",
                    "code": "footnote_reference_has_no_target",
                    "raw_record_id": record["raw_record_id"],
                    "footnote_numbers": missing_targets,
                })
            linked_rules = [rule for rule in store.rules_by_id.values() if rule["raw_record_id"] == record["raw_record_id"]]
            for rule in linked_rules:
                normalized = {str(item.get("footnote_number")) for item in rule.get("footnotes", [])}
                if references - normalized:
                    errors.append({
                        "area": "regulatory",
                        "code": "runtime_rule_missing_linked_footnote",
                        "rule_id": rule["rule_id"],
                        "footnote_numbers": sorted(references - normalized),
                    })

    for substance in store.substances_by_id.values():
        for cas in substance.get("cas_numbers", []):
            if not cas_is_valid(cas):
                errors.append({"area": "identity", "code": "invalid_indexed_cas", "substance_id": substance["substance_id"], "value": cas})

    for ci, substances in store.substances_by_ci.items():
        if not ci or not ci.replace("-", "").isalnum():
            errors.append({"area": "identity", "code": "invalid_ci_identifier", "value": ci})
        if len({item["substance_id"] for item in substances}) != len(substances):
            errors.append({"area": "identity", "code": "duplicate_ci_index_target", "value": ci})

    names_by_cas: dict[str, set[str]] = defaultdict(set)
    sections_by_cas: dict[str, set[str]] = defaultdict(set)
    for substance in store.substances_by_id.values():
        for cas in substance.get("cas_numbers", []):
            names_by_cas[cas].add(substance["normalized_substance_name"])
            sections_by_cas[cas].add(substance["regulatory_section"])
    for cas, names in sorted(names_by_cas.items()):
        if len(names) > 1:
            warnings.append({
                "area": "identity",
                "code": "cas_has_multiple_source_names",
                "cas": cas,
                "normalized_names": sorted(names),
                "sections": sorted(sections_by_cas[cas]),
            })

    for record in linkages.records_by_catalogue_id.values():
        # Multiple independently evaluated rules may intentionally point to
        # one chemical identity (for example product-specific case branches).
        target_ids = [item["rule_id"] for item in record.get("singapore_targets", [])]
        if len(target_ids) != len(set(target_ids)):
            errors.append({"area": "linkage", "code": "duplicate_identity_group_target", "linkage_id": record["linkage_id"]})
        for target in record.get("singapore_targets", []):
            if target["rule_id"] not in store.rules_by_id:
                errors.append({"area": "linkage", "code": "missing_linkage_rule", "linkage_id": record["linkage_id"], "rule_id": target["rule_id"]})
        for cas in record.get("supported_cas_numbers", []):
            if not cas_is_valid(cas):
                errors.append({"area": "linkage", "code": "invalid_linkage_cas", "linkage_id": record["linkage_id"], "cas": cas})

    for candidate in queue["records"]:
        source_verification.append({
            "area": "identity_linkage",
            "code": "candidate_identity_group_requires_sign_off",
            "catalogue_ingredient_id": candidate["catalogue_ingredient_id"],
            "canonical_name": candidate["catalogue_canonical_name"],
            "proposed_rule_ids": [item["rule_id"] for item in candidate["proposed_singapore_targets"]],
            "supporting_acd_raw_record_ids": [item["raw_record_id"] for item in candidate["supporting_acd_records"]],
        })

    covered_sections = {rule["regulatory_section"] for rule in store.rules_by_id.values()}
    missing_sections = sorted(set(SINGAPORE_SECTIONS) - covered_sections)
    if missing_sections:
        errors.append({"area": "regulatory", "code": "missing_singapore_section", "sections": missing_sections})

    report = {
        "dataset_version": store.dataset_version,
        "validation_status": "ERROR" if errors else ("SOURCE VERIFICATION REQUIRED" if source_verification else "PASS"),
        "classifications": {
            "PASS": 0 if errors else 1,
            "ERROR": len(errors),
            "WARNING": len(warnings),
            "SOURCE VERIFICATION REQUIRED": len(source_verification),
        },
        "counts": {
            "regulatory_rules": len(store.rules_by_id),
            "regulatory_substances": len(store.substances_by_id),
            "cross_references": len(store.cross_references),
            "catalogue_identities": catalogue.ingredient_count,
            "accepted_identity_linkages": linkages.counts["accepted_records"],
            "candidate_identity_linkages": queue["candidate_count"],
            "json_files_checked": len(json_files),
        },
        "errors": errors,
        "warnings": warnings,
        "source_verification_required": source_verification,
        "issue_template_coverage": {
            code: {"message": message, "reviewer_action": action}
            for code, (message, action) in sorted(ISSUE_TEMPLATES.items())
        },
    }
    write_json(REPORT_ROOT / "accepted_data_validation.json", report)
    lines = [
        "# Accepted regulatory and identity data validation",
        "",
        f"Status: **{report['validation_status']}**",
        "",
        *[f"- {key.replace('_', ' ').title()}: {value:,}" for key, value in report["counts"].items()],
        "",
        f"- Errors: {len(errors)}",
        f"- Warnings: {len(warnings)}",
        f"- Source verification required: {len(source_verification)}",
        "",
    ]
    if source_verification:
        lines += ["## Source verification required", ""]
        lines += [f"- {item['canonical_name']}: {', '.join(item['proposed_rule_ids'])}" for item in source_verification]
        lines += ["", "See `data_pipeline/identity/eu_singapore_linkage/reports/review_queue.md` for source text and pages.", ""]
    if errors:
        lines += ["## Errors", ""] + [f"- `{item['code']}`: {item}" for item in errors] + [""]
    if warnings:
        lines += ["## Warnings", ""] + [f"- `{item['code']}`: {item}" for item in warnings] + [""]
    (REPORT_ROOT / "accepted_data_validation.md").write_text("\n".join(lines), encoding="utf-8")
    coverage_lines = [
        "# Screening issue-code explanation coverage",
        "",
        f"Covered issue codes: **{len(ISSUE_TEMPLATES)}**",
        "",
        "| Issue code | Deterministic explanation | Reviewer action |",
        "|---|---|---|",
        *[
            f"| `{code}` | {message.replace('|', '/')} | {action.replace('|', '/')} |"
            for code, (message, action) in sorted(ISSUE_TEMPLATES.items())
        ],
        "",
    ]
    (REPORT_ROOT / "reason_code_coverage.md").write_text(
        "\n".join(coverage_lines), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    result = validate_accepted_data()
    print(json.dumps({"validation_status": result["validation_status"], "counts": result["counts"], "classifications": result["classifications"]}, indent=2))
    raise SystemExit(1 if result["errors"] else 0)
