from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .config import (
    ACCEPTED_BASELINE_PATH,
    DATASET_VERSION,
    EXPECTED_SOURCE_HASHES,
    PROCESSED_ROOT,
    RAW_ROOT,
    REPORT_ROOT,
    SOURCE_DEFINITIONS,
    ensure_output_directories,
)
from .extract import sha256, write_json
from .normalize import cas_is_valid, extract_identifiers


ALLOWED_SECTIONS = {
    "Appendix I",
    "Annex II Part 1",
    "Annex III Part 1",
    "Regulation 6",
    "Third Schedule Part I",
    "Third Schedule Part II",
    "Annex IV Part 1",
    "Annex VI",
    "Annex VII",
    "Third Schedule Part III",
    "Third Schedule Part IV",
    "Third Schedule Part V",
}
ALLOWED_XREF_STATUSES = {"aligned", "changed", "acd_only", "singapore_only", "ambiguous"}
SUPPORTED_CONCENTRATION_UNITS = {"percent", "mg/kg", "ppm"}
RAW_TABLE_FILES = [
    "annex_ii_raw.json",
    "annex_iii_raw.json",
    "singapore_third_schedule_part_i_raw.json",
    "singapore_third_schedule_part_ii_raw.json",
    "annex_iv_raw.json",
    "annex_vi_raw.json",
    "annex_vii_raw.json",
    "singapore_third_schedule_part_iii_raw.json",
    "singapore_third_schedule_part_iv_raw.json",
    "singapore_third_schedule_part_v_raw.json",
]
EXPECTED_RAW_COUNTS = {
    "annex_ii_raw.json": 1729,
    "annex_iii_raw.json": 249,
    "singapore_third_schedule_part_i_raw.json": 1709,
    "singapore_third_schedule_part_ii_raw.json": 221,
    "annex_iv_raw.json": 145,
    "annex_vi_raw.json": 62,
    "annex_vii_raw.json": 38,
    "singapore_third_schedule_part_iii_raw.json": 145,
    "singapore_third_schedule_part_iv_raw.json": 56,
    "singapore_third_schedule_part_v_raw.json": 35,
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _duplicates(values: list[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def _lookup(records: list[dict[str, Any]], section: str, reference: str) -> dict[str, Any] | None:
    return next(
        (record for record in records if record["section"] == section and record["reference_number"].casefold() == reference.casefold()),
        None,
    )


def build_spot_checks(
    raw_records: list[dict[str, Any]],
    appendix: dict[str, Any],
    provisions: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.append({
        "check_id": "spot-01",
        "source_document": "acd_appendix_i",
        "regulatory_section": "Appendix I",
        "reference_number": appendix["categories"][0]["category_id"],
        "source_pages": [appendix["categories"][0]["source_page"]],
        "source_text": appendix["categories"][0]["original_text"],
        "verification_focus": "definition/category wording and bullet hierarchy",
    })
    hair = next(category for category in appendix["categories"] if category["subcategories"])
    checks.append({
        "check_id": "spot-02",
        "source_document": "acd_appendix_i",
        "regulatory_section": "Appendix I",
        "reference_number": hair["category_id"],
        "source_pages": [hair["source_page"]],
        "source_text": hair["original_text"] + " | " + " | ".join(hair["subcategories"]),
        "verification_focus": "nested hair-care subcategories",
    })
    for provision_id, focus in [
        ("sg-regulation-6-1", "Part I prohibition and trace/GMP conditions"),
        ("sg-regulation-6-2", "Part II product type, limit, and other requirements"),
        ("sg-regulation-6-7", "unwholesome-product legal effect"),
    ]:
        provision = next(item for item in provisions["provisions"] if item["provision_id"] == provision_id)
        checks.append({
            "check_id": f"spot-{len(checks)+1:02d}",
            "source_document": provision["source_document"],
            "regulatory_section": "Regulation 6",
            "reference_number": provision_id.rsplit("-", 1)[-1],
            "source_pages": provision["source_pages"],
            "source_text": provision["source_text"],
            "verification_focus": focus,
        })
    samples = [
        ("Annex II Part 1", "A1140", "prohibited entry containing an explicit trace exception"),
        ("Annex II Part 1", "391", "entry continued across a page boundary"),
        ("Annex II Part 1", "419", "entry linked to supporting animal definitions"),
        ("Annex II Part 1", "1539", "very long entry spanning nine pages"),
        ("Annex II Part 1", "1711", "late-table entry and CAS extraction"),
        ("Annex III Part 1", "6", "clear multi-case split"),
        ("Annex III Part 1", "8a", "limit stated in other requirements after mixing"),
        ("Annex III Part 1", "12", "complex nested cases retained for review"),
        ("Annex III Part 1", "13", "warning/condition extraction"),
        ("Annex III Part 1", "250", "headerless page and continued row"),
        ("Annex III Part 1", "288", "Singapore-specific source wording"),
        ("Annex III Part 1", "339", "six-column extraction on page 252"),
        ("Annex III Part 1", "342", "three clearly mapped cases"),
        ("Third Schedule Part I", "A1140", "Singapore wording compared with ACD source"),
        ("Third Schedule Part II", "339", "Singapore restricted entry continued across pages"),
    ]
    for section, reference, focus in samples:
        record = _lookup(raw_records, section, reference)
        if record is None:
            checks.append({
                "check_id": f"spot-{len(checks)+1:02d}",
                "regulatory_section": section,
                "reference_number": reference,
                "missing": True,
                "verification_focus": focus,
            })
            continue
        checks.append({
            "check_id": f"spot-{len(checks)+1:02d}",
            "source_document": record["source_document"],
            "regulatory_section": section,
            "reference_number": reference,
            "source_pages": record["source_pages"],
            "raw_record_id": record["raw_record_id"],
            "source_text": record["source_text"],
            "verification_focus": focus,
        })
    expanded_samples = [
        ("parts-i-v-01", "Third Schedule Part III", "12085", "colourant concentration and # qualification"),
        ("parts-i-v-02", "Annex IV Part 1", "12085", "ACD colourant field-of-application mapping"),
        ("parts-i-v-03", "Third Schedule Part III", "10316", "eye-area colourant restriction"),
        ("parts-i-v-04", "Third Schedule Part IV", "1", "preservative multi-product concentration cases"),
        ("parts-i-v-05", "Annex VI", "1", "ACD preservative comparison and acid basis"),
        ("parts-i-v-06", "Third Schedule Part IV", "12", "combined paraben limits"),
        ("parts-i-v-07", "Annex VI", "20", "formaldehyde warning and preamble interaction"),
        ("parts-i-v-08", "Third Schedule Part IV", "2", "preservative qualification and salts"),
        ("parts-i-v-09", "Third Schedule Part V", "3", "UV-filter concentration"),
        ("parts-i-v-10", "Annex VII", "A29a", "nano zinc oxide conditions"),
        ("parts-i-v-11", "Third Schedule Part V", "A29a", "Singapore nano UV-filter conditions"),
        ("parts-i-v-12", "Annex VII", "A28", "section-specific Annex VII version"),
    ]
    for check_id, section, reference, focus in expanded_samples:
        record = _lookup(raw_records, section, reference)
        checks.append({
            "check_id": check_id,
            "source_document": record["source_document"] if record else None,
            "regulatory_section": section,
            "reference_number": reference,
            "source_pages": record["source_pages"] if record else [],
            "raw_record_id": record["raw_record_id"] if record else None,
            "source_text": record["source_text"] if record else None,
            "missing": record is None,
            "verification_focus": focus,
        })
    for number in (3, 4, 5):
        provision = next(item for item in provisions["provisions"] if item["provision_id"] == f"sg-regulation-6-{number}")
        checks.append({
            "check_id": f"parts-i-v-regulation-6-{number}",
            "source_document": provision["source_document"],
            "regulatory_section": "Regulation 6",
            "reference_number": f"6({number})",
            "source_pages": provision["source_pages"],
            "source_text": provision["source_text"],
            "verification_focus": "Singapore positive-list legal semantics",
        })
    return checks


def validate() -> dict[str, Any]:
    ensure_output_directories()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    manifest = load_json(RAW_ROOT / "source_manifest.json")
    manifest_sources = {item["source_document"]: item for item in manifest["documents"]}
    raw_sets = [load_json(RAW_ROOT / filename) for filename in RAW_TABLE_FILES]
    raw_records = [record for raw in raw_sets for record in raw["records"]]
    rules = load_json(PROCESSED_ROOT / "rules.json")["rules"]
    substances = load_json(PROCESSED_ROOT / "substances.json")["substances"]
    xrefs = load_json(PROCESSED_ROOT / "source_cross_references.json")["cross_references"]
    appendix = load_json(RAW_ROOT / "appendix_i_raw.json")
    provisions = load_json(RAW_ROOT / "singapore_regulation_6_raw.json")

    for source_id, definition in SOURCE_DEFINITIONS.items():
        actual = sha256(definition["path"])
        expected = EXPECTED_SOURCE_HASHES[source_id]
        if actual != expected or manifest_sources[source_id]["sha256"] != expected:
            errors.append({"code": "source_hash_changed", "source_document": source_id, "expected": expected, "actual": actual})
    full_snapshot = manifest_sources["singapore_regulations_2025_12_01"]
    for field in ("effective_date", "retrieval_date", "source_url", "sha256", "snapshot_generated_at"):
        if not full_snapshot.get(field):
            errors.append({"code": "missing_singapore_snapshot_metadata", "field": field})

    duplicate_raw = _duplicates([record["raw_record_id"] for record in raw_records])
    duplicate_rules = _duplicates([rule["rule_id"] for rule in rules])
    duplicate_substances = _duplicates([item["substance_id"] for item in substances])
    duplicate_xrefs = _duplicates([item["cross_reference_id"] for item in xrefs])
    for code, values in [
        ("duplicate_raw_record_id", duplicate_raw),
        ("duplicate_rule_id", duplicate_rules),
        ("duplicate_substance_id", duplicate_substances),
        ("duplicate_cross_reference_id", duplicate_xrefs),
    ]:
        for value in values:
            errors.append({"code": code, "value": value})

    raw_by_id = {record["raw_record_id"]: record for record in raw_records}
    for raw, filename in zip(raw_sets, RAW_TABLE_FILES, strict=True):
        if len(raw["records"]) != EXPECTED_RAW_COUNTS[filename]:
            errors.append({"code": "unexpected_raw_record_count", "file": filename, "expected": EXPECTED_RAW_COUNTS[filename], "actual": len(raw["records"])})
        is_expanded_section = filename not in {
            "annex_ii_raw.json",
            "annex_iii_raw.json",
            "singapore_third_schedule_part_i_raw.json",
            "singapore_third_schedule_part_ii_raw.json",
        }
        for page in raw["page_diagnostics"]:
            if (not is_expanded_section and page["table_count"] != 1) or page["table_count"] not in {0, 1}:
                errors.append({"code": "column_or_table_count_error", "file": filename, "page": page})
            for fragment in page.get("unassigned_fragments", []):
                target = warnings if is_expanded_section else errors
                target.append({"code": "unassigned_continuation_fragment", "file": filename, "page": page["source_page"], "fragment": fragment})
        if not raw.get("page_texts"):
            errors.append({"code": "missing_page_text", "file": filename})
        if filename == "annex_iii_raw.json" and len(raw.get("footnotes", [])) != 23:
            errors.append({"code": "lost_footnotes", "file": filename, "expected": 23, "actual": len(raw.get("footnotes", []))})
        if filename == "singapore_third_schedule_part_ii_raw.json" and len(raw.get("footnotes", [])) != 11:
            errors.append({"code": "lost_footnotes", "file": filename, "expected": 11, "actual": len(raw.get("footnotes", []))})

    for record in raw_records:
        if not record["reference_number"]:
            errors.append({"code": "missing_reference_number", "raw_record_id": record["raw_record_id"]})
        if not record["source_pages"] or not record["source_text"] or not record["fragments"]:
            errors.append({"code": "missing_raw_provenance", "raw_record_id": record["raw_record_id"]})

    for rule in rules:
        required = ["source_hash", "source_url", "source_version", "source_text", "source_pages", "raw_record_id", "raw_file"]
        missing = [field for field in required if not rule.get(field)]
        if missing:
            errors.append({"code": "missing_rule_provenance", "rule_id": rule["rule_id"], "fields": missing})
        if rule["regulatory_section"] not in ALLOWED_SECTIONS:
            errors.append({"code": "out_of_scope_section", "rule_id": rule["rule_id"], "section": rule["regulatory_section"]})
        raw_record = raw_by_id.get(rule["raw_record_id"])
        if not raw_record:
            errors.append({"code": "broken_raw_link", "rule_id": rule["rule_id"]})
        elif rule["source_text"] != raw_record["source_text"]:
            errors.append({"code": "source_text_loss", "rule_id": rule["rule_id"]})
        for cas in rule["cas_numbers"]:
            if not cas_is_valid(cas):
                errors.append({"code": "malformed_normalized_cas", "rule_id": rule["rule_id"], "value": cas})
        constraint = rule.get("concentration")
        if constraint and (
            constraint["value"] < 0
            or constraint["unit"] not in SUPPORTED_CONCENTRATION_UNITS
            or (constraint["unit"] == "percent" and constraint["value"] > 100)
        ):
            errors.append({"code": "invalid_parsed_concentration", "rule_id": rule["rule_id"], "constraint": constraint})

    for substance in substances:
        if substance["malformed_identifiers"]:
            warnings.append({"code": "malformed_source_identifier_preserved", "substance_id": substance["substance_id"], "values": substance["malformed_identifiers"]})

    substances_by_raw_id = {item["raw_record_id"]: item for item in substances}
    for record in raw_records:
        substance = substances_by_raw_id.get(record["raw_record_id"])
        if substance is None:
            continue
        expected_valid, expected_malformed = extract_identifiers(record.get("cas_number_raw"))
        if substance["cas_numbers"] != expected_valid:
            errors.append({
                "code": "lost_or_changed_valid_cas_identifier",
                "raw_record_id": record["raw_record_id"],
                "expected": expected_valid,
                "actual": substance["cas_numbers"],
            })
        if substance["malformed_identifiers"] != expected_malformed:
            errors.append({
                "code": "lost_or_changed_malformed_cas_identifier",
                "raw_record_id": record["raw_record_id"],
                "expected": expected_malformed,
                "actual": substance["malformed_identifiers"],
            })

    for xref in xrefs:
        status = xref["comparison_status"]
        if status not in ALLOWED_XREF_STATUSES:
            errors.append({"code": "unrecognized_comparison_status", "cross_reference_id": xref["cross_reference_id"], "status": status})
        if xref["regulatory_mapping"].startswith("annex-ii-to"):
            expected_acd, expected_sg = "acd-ii-", "sg-third-schedule-i-"
        elif xref["regulatory_mapping"].startswith("annex-iii-to"):
            expected_acd, expected_sg = "acd-iii-", "sg-third-schedule-ii-"
        elif xref["regulatory_mapping"].startswith("annex-iv-to"):
            expected_acd, expected_sg = "acd-iv-", "sg-third-schedule-iii-"
        elif xref["regulatory_mapping"].startswith("annex-vi-to"):
            expected_acd, expected_sg = "acd-vi-", "sg-third-schedule-iv-"
        elif xref["regulatory_mapping"].startswith("annex-vii-to"):
            expected_acd, expected_sg = "acd-vii-", "sg-third-schedule-v-"
        else:
            errors.append({"code": "incorrect_cross_reference_direction", "cross_reference_id": xref["cross_reference_id"]})
            continue
        if any(not rule_id.startswith(expected_acd) for rule_id in xref["acd_rule_ids"]) or any(not rule_id.startswith(expected_sg) for rule_id in xref["singapore_rule_ids"]):
            errors.append({"code": "incorrect_cross_reference_direction", "cross_reference_id": xref["cross_reference_id"]})

    required_samples = {
        "Annex II Part 1": ["A1140", "391", "419", "1539", "1711"],
        "Annex III Part 1": ["6", "8a", "12", "13", "250", "288", "339", "342"],
    }
    for section, references in required_samples.items():
        for reference in references:
            if _lookup(raw_records, section, reference) is None:
                errors.append({"code": "missing_regression_reference", "section": section, "reference": reference})
    provision_ids = {item["provision_id"] for item in provisions["provisions"]}
    for expected in {
        "sg-regulation-6-1", "sg-regulation-6-2", "sg-regulation-6-3",
        "sg-regulation-6-4", "sg-regulation-6-5", "sg-regulation-6-7",
    } - provision_ids:
        errors.append({"code": "missing_regulation_6_provision", "provision_id": expected})

    obsolete_hits: list[str] = []
    obsolete_term = "chapter" + " 6"
    for path in [*RAW_ROOT.glob("*.json"), *PROCESSED_ROOT.glob("*.json"), Path("README.md"), Path("STATUS.md")]:
        if path.exists() and obsolete_term in path.read_text(encoding="utf-8").casefold():
            obsolete_hits.append(path.as_posix())
    if obsolete_hits:
        errors.append({"code": "obsolete_regulation_terminology", "files": obsolete_hits})

    review_rules = [
        {"item_type": "normalized_rule", "item_id": rule["rule_id"], "reference_number": rule["reference_number"], "regulatory_section": rule["regulatory_section"], "source_pages": rule["source_pages"], "review_reasons": rule["review_reasons"], "raw_record_id": rule["raw_record_id"]}
        for rule in rules if rule["normalization_status"] != "normalized"
    ]
    review_xrefs = [
        {"item_type": "cross_reference", "item_id": item["cross_reference_id"], "reference_number": item["reference_number"], "regulatory_mapping": item["regulatory_mapping"], "comparison_status": item["comparison_status"], "review_reasons": item["review_reasons"], "acd_rule_ids": item["acd_rule_ids"], "singapore_rule_ids": item["singapore_rule_ids"]}
        for item in xrefs if item["professional_review_required"]
    ]
    review_queue = {
        "dataset_version": DATASET_VERSION,
        "summary": {"normalized_rule_items": len(review_rules), "cross_reference_items": len(review_xrefs), "total": len(review_rules) + len(review_xrefs)},
        "items": review_rules + review_xrefs,
    }
    write_json(REPORT_ROOT / "manual_review_queue.json", review_queue)
    spot_checks = build_spot_checks(raw_records, appendix, provisions)
    write_json(REPORT_ROOT / "manual_spot_check_checklist.json", {"dataset_version": DATASET_VERSION, "check_count": len(spot_checks), "checks": spot_checks})

    spot_check_results_path = REPORT_ROOT / "manual_spot_check_results.json"
    completed_spot_checks = 0
    if not spot_check_results_path.exists():
        errors.append({"code": "missing_manual_spot_check_results", "path": spot_check_results_path.as_posix()})
    else:
        spot_check_results = load_json(spot_check_results_path)
        expected_check_ids = {item["check_id"] for item in spot_checks}
        results = spot_check_results.get("results", [])
        result_ids = [item.get("check_id") for item in results]
        if spot_check_results.get("dataset_version") != DATASET_VERSION:
            errors.append({"code": "spot_check_dataset_version_mismatch"})
        if set(result_ids) != expected_check_ids or len(result_ids) != len(expected_check_ids):
            errors.append({
                "code": "spot_check_result_set_mismatch",
                "expected": sorted(expected_check_ids),
                "actual": sorted(value for value in result_ids if value),
            })
        accepted_baseline_hash = file_hash(ACCEPTED_BASELINE_PATH) if ACCEPTED_BASELINE_PATH.exists() else None
        if spot_check_results.get("accepted_baseline_sha256", "").casefold() != (accepted_baseline_hash or "").casefold():
            errors.append({"code": "spot_check_baseline_hash_mismatch"})
        invalid_results = [
            item for item in results
            if item.get("result") != "PASS" or not item.get("evidence_checked") or not item.get("notes")
        ]
        if invalid_results:
            errors.append({"code": "incomplete_or_failed_manual_spot_checks", "check_ids": [item.get("check_id") for item in invalid_results]})
        completed_spot_checks = sum(item.get("result") == "PASS" for item in results)

    generated_files = [*sorted(RAW_ROOT.glob("*.json")), *sorted(PROCESSED_ROOT.glob("*.json"))]
    generated_output_hashes = {path.relative_to(Path.cwd()).as_posix(): file_hash(path) for path in generated_files}
    baseline_validation_status = "missing"
    if ACCEPTED_BASELINE_PATH.exists():
        accepted_baseline = load_json(ACCEPTED_BASELINE_PATH)
        accepted_hashes = accepted_baseline.get("generated_output_hashes", {})
        if accepted_baseline.get("dataset_version") != DATASET_VERSION:
            errors.append({
                "code": "accepted_baseline_dataset_version_mismatch",
                "expected": DATASET_VERSION,
                "actual": accepted_baseline.get("dataset_version"),
            })
            baseline_validation_status = "mismatched"
        elif accepted_hashes != generated_output_hashes:
            changed_paths = sorted(
                path
                for path in set(accepted_hashes) | set(generated_output_hashes)
                if accepted_hashes.get(path) != generated_output_hashes.get(path)
            )
            errors.append({
                "code": "accepted_output_baseline_mismatch",
                "changed_paths": changed_paths,
            })
            baseline_validation_status = "mismatched"
        else:
            baseline_validation_status = "matched"
    else:
        errors.append({
            "code": "missing_accepted_output_baseline",
            "path": ACCEPTED_BASELINE_PATH.as_posix(),
        })
    previous_hashes: dict[str, str] | None = None
    previous_report_path = REPORT_ROOT / "validation_report.json"
    if previous_report_path.exists():
        previous_hashes = load_json(previous_report_path).get("generated_output_hashes")
    reproducibility_status = (
        "matched_previous_run"
        if previous_hashes == generated_output_hashes
        else "baseline_created_or_outputs_changed"
    )
    report = {
        "dataset_version": DATASET_VERSION,
        "validation_status": "passed" if not errors else "failed",
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "raw_records": len(raw_records),
            "normalized_rules": len(rules),
            "substances": len(substances),
            "rules_by_status": dict(sorted(Counter(rule["normalization_status"] for rule in rules).items())),
            "cross_references": len(xrefs),
            "cross_references_by_status": dict(sorted(Counter(item["comparison_status"] for item in xrefs).items())),
            "manual_review_queue": review_queue["summary"]["total"],
            "spot_checks": len(spot_checks),
            "completed_spot_checks": completed_spot_checks,
        },
        "reproducibility_status": reproducibility_status,
        "accepted_baseline_status": baseline_validation_status,
        "generated_output_hashes": generated_output_hashes,
    }
    write_json(REPORT_ROOT / "validation_report.json", report)
    lines = [
        "# Regulatory data validation",
        "",
        f"Status: **{report['validation_status']}**",
        "",
        f"- Raw records: {len(raw_records)}",
        f"- Normalized rules: {len(rules)}",
        f"- Cross-references: {len(xrefs)}",
        f"- Structural errors: {len(errors)}",
        f"- Professional-review items: {review_queue['summary']['total']}",
        f"- Manual spot checks: {len(spot_checks)}",
        f"- Completed spot checks: {completed_spot_checks}",
        f"- Reproducibility: `{reproducibility_status}`",
        f"- Accepted baseline: `{baseline_validation_status}`",
        "",
        "Cross-reference status counts:",
        "",
    ]
    for status, count in report["counts"]["cross_references_by_status"].items():
        lines.append(f"- `{status}`: {count}")
    if errors:
        lines += ["", "Structural errors:", ""] + [f"- `{item['code']}`: {item}" for item in errors]
    lines += [
        "",
        "Professional-review findings are reported separately and do not make the structural validation fail.",
        "See `manual_review_queue.json`, `manual_spot_check_checklist.json`, and `manual_spot_check_results.json`.",
        "",
    ]
    (REPORT_ROOT / "validation_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = validate()
    print(json.dumps({"validation_status": result["validation_status"], "counts": result["counts"]}, indent=2))
    raise SystemExit(0 if result["validation_status"] == "passed" else 1)
