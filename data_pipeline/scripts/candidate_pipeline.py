from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from .config import (
    ACCEPTED_BASELINE_PATH,
    CANDIDATE_BASELINE_PATH,
    CANDIDATE_DATASET_VERSION,
    CANDIDATE_PROCESSED_ROOT,
    CANDIDATE_RAW_ROOT,
    CANDIDATE_REPORT_ROOT,
    CANDIDATE_ROOT,
    PIPELINE_ROOT,
    PROCESSED_ROOT,
    RAW_ROOT,
    REPORT_ROOT,
    ensure_candidate_directories,
)
from .cross_reference import build_candidate_cross_references
from .extract import extract_candidate_all, write_json
from .normalize import RAW_FILES, normalize_candidate_all


REQUIRED_SECTIONS = tuple(RAW_FILES)
REQUIRED_REGULATION_PROVISIONS = tuple(f"sg-regulation-6-{number}" for number in (1, 2, 3, 4, 5, 7))
PROMOTED_REPORTS = (
    "validation_report.json",
    "validation_summary.md",
    "manual_review_queue.json",
    "manual_spot_check_checklist.json",
    "manual_spot_check_results.json",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target_path(path: Path) -> str:
    relative = path.relative_to(CANDIDATE_ROOT)
    if relative.parts[0] not in {"raw", "processed"}:
        raise ValueError(f"Candidate output is not promotable: {path}")
    return (Path("data_pipeline") / relative).as_posix()


def _spot_checks(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requested = (
        ("Third Schedule Part III", "12085", "colourant concentration and # qualification"),
        ("Annex IV Part 1", "12085", "ACD colourant field-of-application mapping"),
        ("Third Schedule Part III", "10316", "eye-area colourant restriction"),
        ("Third Schedule Part IV", "1", "preservative multi-product concentration cases"),
        ("Annex VI", "1", "ACD preservative comparison and acid basis"),
        ("Third Schedule Part IV", "12", "combined paraben limits"),
        ("Annex VI", "20", "formaldehyde warning and preamble interaction"),
        ("Third Schedule Part IV", "2", "preservative qualification and salts"),
        ("Third Schedule Part V", "3", "UV-filter concentration"),
        ("Annex VII", "A29a", "nano zinc oxide conditions"),
        ("Third Schedule Part V", "A29a", "Singapore nano UV-filter conditions"),
        ("Annex VII", "A28", "section-specific Annex VII version"),
    )
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rule in rules:
        by_key.setdefault((rule["regulatory_section"], rule["reference_number"]), []).append(rule)
    checks: list[dict[str, Any]] = []
    for index, (section, reference, purpose) in enumerate(requested, start=1):
        matches = by_key.get((section, reference), [])
        checks.append({
            "check_id": f"parts-i-v-{index:02d}",
            "regulatory_section": section,
            "reference_number": reference,
            "purpose": purpose,
            "rule_ids": [item["rule_id"] for item in matches],
            "source_pages": sorted({page for item in matches for page in item["source_pages"]}),
            "required": True,
        })
    for number in (3, 4, 5):
        checks.append({
            "check_id": f"parts-i-v-regulation-6-{number}",
            "regulatory_section": "Regulation 6",
            "reference_number": f"6({number})",
            "purpose": "Singapore positive-list legal semantics",
            "rule_ids": [f"sg-regulation-6-{number}"],
            "source_pages": [],
            "required": True,
        })
    return checks


def validate_candidate() -> dict[str, Any]:
    ensure_candidate_directories()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    raw_documents = {
        section: _load(CANDIDATE_RAW_ROOT / filename)
        for section, filename in RAW_FILES.items()
    }
    rules_document = _load(CANDIDATE_PROCESSED_ROOT / "rules.json")
    substances_document = _load(CANDIDATE_PROCESSED_ROOT / "substances.json")
    provisions_document = _load(CANDIDATE_PROCESSED_ROOT / "singapore_provisions.json")
    cross_reference_document = _load(CANDIDATE_PROCESSED_ROOT / "source_cross_references.json")
    versioned = [
        *raw_documents.values(),
        rules_document,
        substances_document,
        provisions_document,
        cross_reference_document,
        _load(CANDIDATE_RAW_ROOT / "source_manifest.json"),
        _load(CANDIDATE_PROCESSED_ROOT / "product_context.json"),
    ]
    for document in versioned:
        if document.get("dataset_version") != CANDIDATE_DATASET_VERSION:
            errors.append({"code": "dataset_version_mismatch", "actual": document.get("dataset_version")})

    rules = rules_document["rules"]
    substances = substances_document["substances"]
    rule_ids = [item["rule_id"] for item in rules]
    raw_ids = [item["raw_record_id"] for document in raw_documents.values() for item in document["records"]]
    duplicate_rule_ids = [key for key, count in Counter(rule_ids).items() if count > 1]
    duplicate_raw_ids = [key for key, count in Counter(raw_ids).items() if count > 1]
    if duplicate_rule_ids:
        errors.append({"code": "duplicate_rule_ids", "values": duplicate_rule_ids[:20]})
    if duplicate_raw_ids:
        errors.append({"code": "duplicate_raw_record_ids", "values": duplicate_raw_ids[:20]})
    for section in REQUIRED_SECTIONS:
        if not raw_documents[section]["records"]:
            errors.append({"code": "empty_required_section", "section": section})
    provision_ids = {item["provision_id"] for item in provisions_document["provisions"]}
    missing_provisions = sorted(set(REQUIRED_REGULATION_PROVISIONS) - provision_ids)
    if missing_provisions:
        errors.append({"code": "missing_regulation_6_provisions", "values": missing_provisions})
    mappings = {item["regulatory_mapping"] for item in cross_reference_document["cross_references"]}
    expected_mappings = {
        "annex-ii-to-third-schedule-part-i",
        "annex-iii-to-third-schedule-part-ii",
        "annex-iv-to-third-schedule-part-iii",
        "annex-vi-to-third-schedule-part-iv",
        "annex-vii-to-third-schedule-part-v",
    }
    if missing := sorted(expected_mappings - mappings):
        errors.append({"code": "missing_cross_reference_mappings", "values": missing})
    for section, document in raw_documents.items():
        unassigned = [
            {"page": page["source_page"], "fragments": page.get("unassigned_fragments", [])}
            for page in document.get("page_diagnostics", [])
            if page.get("unassigned_fragments")
        ]
        if unassigned:
            warnings.append({"code": "unassigned_table_fragments", "section": section, "pages": unassigned})
    expected_footnotes = {
        "Annex III Part 1": 23,
        "Third Schedule Part II": 11,
    }
    for section, expected in expected_footnotes.items():
        actual = len(raw_documents[section].get("footnotes", []))
        if actual != expected:
            errors.append({
                "code": "lost_existing_footnotes",
                "section": section,
                "expected": expected,
                "actual": actual,
            })
    for rule in rules:
        if not rule.get("source_text") or not rule.get("source_pages") or not rule.get("source_url"):
            errors.append({"code": "missing_rule_provenance", "rule_id": rule["rule_id"]})
        if rule["list_semantics"] == "positive_list" and not rule.get("permitted_function"):
            errors.append({"code": "positive_list_missing_function", "rule_id": rule["rule_id"]})

    checklist = _spot_checks(rules)
    if any(not item["rule_ids"] for item in checklist if item["regulatory_section"] != "Regulation 6"):
        errors.append({
            "code": "spot_check_target_missing",
            "check_ids": [item["check_id"] for item in checklist if not item["rule_ids"]],
        })
    checklist_path = CANDIDATE_REPORT_ROOT / "manual_spot_check_checklist.json"
    write_json(checklist_path, {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "check_count": len(checklist),
        "checks": checklist,
    })
    results_path = CANDIDATE_REPORT_ROOT / "manual_spot_check_results.json"
    if not results_path.exists():
        write_json(results_path, {
            "dataset_version": CANDIDATE_DATASET_VERSION,
            "completed_date": None,
            "method": "Rendered-page comparison against the immutable source PDFs and normalized candidate JSON.",
            "summary": {"total": len(checklist), "passed": 0, "failed": 0, "pending": len(checklist)},
            "results": [
                {"check_id": item["check_id"], "result": "PENDING", "evidence_checked": "", "notes": ""}
                for item in checklist
            ],
        })

    output_paths = sorted(CANDIDATE_RAW_ROOT.glob("*.json")) + sorted(CANDIDATE_PROCESSED_ROOT.glob("*.json"))
    hashes = {_target_path(path): _sha256(path) for path in output_paths}
    write_json(CANDIDATE_BASELINE_PATH, {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "candidate_only": True,
        "generated_output_hashes": hashes,
    })
    counts_by_section = Counter(item["regulatory_section"] for item in rules)
    manual_by_section = Counter(
        item["regulatory_section"] for item in rules if item["normalization_status"] == "manual_review_required"
    )
    xref_status = Counter(item["comparison_status"] for item in cross_reference_document["cross_references"])
    recorded_results = _load(results_path).get("results", [])
    result_by_id = {item.get("check_id"): item.get("result") for item in recorded_results}
    all_spot_checks_pass = bool(checklist) and all(
        result_by_id.get(item["check_id"]) == "PASS" for item in checklist
    )
    accepted_baseline = _load(ACCEPTED_BASELINE_PATH)
    matches_accepted = (
        accepted_baseline.get("dataset_version") == CANDIDATE_DATASET_VERSION
        and accepted_baseline.get("generated_output_hashes") == hashes
    )
    promotion_status = (
        "promoted"
        if matches_accepted
        else "ready_for_promotion"
        if all_spot_checks_pass
        else "awaiting_human_spot_checks"
    )
    report = {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "validation_status": "passed" if not errors else "failed",
        "promotion_status": promotion_status,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "raw_records_by_section": {section: len(document["records"]) for section, document in raw_documents.items()},
            "normalized_rules_by_section": dict(sorted(counts_by_section.items())),
            "manual_review_rules_by_section": dict(sorted(manual_by_section.items())),
            "substances": len(substances),
            "cross_references": len(cross_reference_document["cross_references"]),
            "cross_reference_statuses": dict(sorted(xref_status.items())),
            "spot_checks": len(checklist),
        },
        "generated_output_hashes": hashes,
    }
    write_json(CANDIDATE_REPORT_ROOT / "validation_report.json", report)
    summary = [
        "# Parts I-V candidate validation",
        "",
        f"- Dataset: `{CANDIDATE_DATASET_VERSION}`",
        f"- Structural validation: **{report['validation_status']}**",
        f"- Promotion: **{promotion_status.replace('_', ' ')}**",
        "",
        (
            "This candidate matches the active accepted baseline."
            if matches_accepted
            else "The active accepted baseline is unchanged."
        ),
    ]
    (CANDIDATE_REPORT_ROOT / "validation_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    write_json(CANDIDATE_REPORT_ROOT / "manual_review_queue.json", {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "count": sum(manual_by_section.values()),
        "rules": [item for item in rules if item["normalization_status"] == "manual_review_required"],
    })
    return report


def build_candidate() -> dict[str, Any]:
    ensure_candidate_directories()
    extract_candidate_all()
    normalize_candidate_all()
    build_candidate_cross_references()
    return validate_candidate()


def promote_candidate() -> None:
    previous_checklist = _load(REPORT_ROOT / "manual_spot_check_checklist.json") if (REPORT_ROOT / "manual_spot_check_checklist.json").exists() else {"checks": []}
    previous_results = _load(REPORT_ROOT / "manual_spot_check_results.json") if (REPORT_ROOT / "manual_spot_check_results.json").exists() else {"results": []}
    report = validate_candidate()
    if report["validation_status"] != "passed":
        raise RuntimeError("Candidate validation has errors and cannot be promoted")
    results = _load(CANDIDATE_REPORT_ROOT / "manual_spot_check_results.json")
    checklist = _load(CANDIDATE_REPORT_ROOT / "manual_spot_check_checklist.json")
    required_ids = {item["check_id"] for item in checklist["checks"] if item["required"]}
    passed_ids = {
        item["check_id"] for item in results.get("results", []) if item.get("result") == "PASS"
    }
    if required_ids != passed_ids:
        raise RuntimeError("Every required candidate spot check must have a recorded PASS before promotion")
    baseline = _load(CANDIDATE_BASELINE_PATH)
    for target, expected in baseline["generated_output_hashes"].items():
        candidate = CANDIDATE_ROOT / Path(target).relative_to("data_pipeline")
        if _sha256(candidate) != expected:
            raise RuntimeError(f"Candidate hash changed after validation: {target}")
    for source_root, target_root in ((CANDIDATE_RAW_ROOT, RAW_ROOT), (CANDIDATE_PROCESSED_ROOT, PROCESSED_ROOT)):
        for source in source_root.glob("*.json"):
            shutil.copy2(source, target_root / source.name)
    for name in PROMOTED_REPORTS:
        source = CANDIDATE_REPORT_ROOT / name
        if source.exists():
            shutil.copy2(source, REPORT_ROOT / name)
    accepted = {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "accepted_after": "Parts I-V source validation and recorded human spot-check sign-off",
        "generated_output_hashes": {
            target: _sha256(PIPELINE_ROOT.parent / target)
            for target in baseline["generated_output_hashes"]
        },
    }
    write_json(ACCEPTED_BASELINE_PATH, accepted)
    accepted_hash = _sha256(ACCEPTED_BASELINE_PATH)
    candidate_checklist = _load(CANDIDATE_REPORT_ROOT / "manual_spot_check_checklist.json")
    candidate_results = _load(CANDIDATE_REPORT_ROOT / "manual_spot_check_results.json")
    retained_checks = [item for item in previous_checklist.get("checks", []) if item.get("check_id", "").startswith("spot-")]
    retained_results = [item for item in previous_results.get("results", []) if item.get("check_id", "").startswith("spot-")]
    merged_checks = [*retained_checks, *candidate_checklist["checks"]]
    merged_results = [*retained_results, *candidate_results["results"]]
    write_json(REPORT_ROOT / "manual_spot_check_checklist.json", {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "check_count": len(merged_checks),
        "checks": merged_checks,
    })
    write_json(REPORT_ROOT / "manual_spot_check_results.json", {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "completed_date": candidate_results.get("completed_date") or date.today().isoformat(),
        "method": "Rendered-page comparison against the immutable source PDFs and normalized accepted JSON.",
        "accepted_baseline_sha256": accepted_hash,
        "summary": {
            "total": len(merged_results),
            "passed": sum(item.get("result") == "PASS" for item in merged_results),
            "failed": sum(item.get("result") == "FAIL" for item in merged_results),
            "pending": sum(item.get("result") == "PENDING" for item in merged_results),
        },
        "results": merged_results,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or promote the isolated Parts I-V regulatory candidate")
    parser.add_argument("command", choices=("build", "validate", "promote"), nargs="?", default="build")
    args = parser.parse_args()
    if args.command == "build":
        report = build_candidate()
    elif args.command == "validate":
        report = validate_candidate()
    else:
        promote_candidate()
        print(f"promoted={CANDIDATE_DATASET_VERSION}")
        return 0
    print(f"validation_status={report['validation_status']}")
    print(f"promotion_status={report['promotion_status']}")
    return 0 if report["validation_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
