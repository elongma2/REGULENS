from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .config import (
    CANDIDATE_DATASET_VERSION,
    CANDIDATE_PROCESSED_ROOT,
    CANDIDATE_RAW_ROOT,
    DATASET_VERSION,
    PROCESSED_ROOT,
    RAW_ROOT,
)
from .extract import write_json
from .models import CrossReference
from .normalize import conservative_text


RANGE_RE = re.compile(
    r"^A?\d+[a-z]?\s*(?:-|to)\s*A?\d+[a-z]?$", re.IGNORECASE
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _groups(rules: list[dict[str, Any]], section: str) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rule in rules:
        if rule["regulatory_section"] == section:
            output[rule["reference_number"].casefold()].append(rule)
    return dict(output)


def _field_value(group: list[dict[str, Any]], field: str) -> str:
    ordered = sorted(group, key=lambda item: (item.get("case_label") or "", item["rule_id"]))
    def display_value(item: dict[str, Any]) -> str:
        value = item.get(field)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value or "")

    return "\n---\n".join(
        f"[{item.get('case_label') or 'parent'}] {display_value(item)}" for item in ordered
    )


def _candidate_index(groups: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = defaultdict(list)
    for reference, group in groups.items():
        names = {conservative_text(item["substance_name"]) for item in group if item["active"]}
        for name in names:
            if name:
                output[name].append(reference)
    return dict(output)


def compare_mapping(
    rules: list[dict[str, Any]],
    acd_section: str,
    singapore_section: str,
    mapping_name: str,
) -> list[CrossReference]:
    acd = _groups(rules, acd_section)
    singapore = _groups(rules, singapore_section)
    acd_candidates = _candidate_index(acd)
    singapore_candidates = _candidate_index(singapore)
    references = sorted(set(acd) | set(singapore), key=lambda value: (not value[:1].isdigit(), value))
    output: list[CrossReference] = []
    comparable_fields = ["substance_name"]
    if acd_section not in {"Annex II Part 1"}:
        comparable_fields += [
            "product_context",
            "concentration_text",
            "concentration",
            "other_conditions",
            "required_warning",
            "applicability_requirements",
            "combined_limit_requirements",
            "warning_requirements",
        ]
    for reference_key in references:
        acd_group = acd.get(reference_key, [])
        sg_group = singapore.get(reference_key, [])
        display_reference = (acd_group or sg_group)[0]["reference_number"]
        differences: dict[str, dict[str, str | None]] = {}
        reasons: list[str] = []
        candidate_matches: list[str] = []
        is_range = bool(RANGE_RE.fullmatch(display_reference))

        if is_range:
            status = "ambiguous"
            reasons.append("ranged_reference_prevents_unique_entry_correspondence")
        elif acd_group and sg_group:
            acd_cases = sorted(item.get("case_label") or "parent" for item in acd_group)
            sg_cases = sorted(item.get("case_label") or "parent" for item in sg_group)
            if acd_cases != sg_cases:
                status = "ambiguous"
                reasons.append("normalized_case_structure_differs_between_sources")
            else:
                for field in comparable_fields:
                    acd_value = _field_value(acd_group, field)
                    sg_value = _field_value(sg_group, field)
                    if conservative_text(acd_value) != conservative_text(sg_value):
                        differences[field] = {"acd": acd_value, "singapore": sg_value}
                status = "changed" if differences else "aligned"
                if status == "changed":
                    reasons.append("source_wording_or_regulatory_field_differs")
        elif acd_group:
            status = "acd_only"
            reasons.append("no_current_singapore_reference_number_match")
            for name in {conservative_text(item["substance_name"]) for item in acd_group}:
                candidate_matches.extend(
                    f"singapore:{candidate}" for candidate in singapore_candidates.get(name, []) if candidate != reference_key
                )
        else:
            status = "singapore_only"
            reasons.append("no_acd_2026_1_reference_number_match")
            for name in {conservative_text(item["substance_name"]) for item in sg_group}:
                candidate_matches.extend(
                    f"acd:{candidate}" for candidate in acd_candidates.get(name, []) if candidate != reference_key
                )
        if candidate_matches:
            reasons.append("same_normalized_substance_name_found_under_different_reference")
        material_fields = {
            "product_context",
            "concentration_text",
            "concentration",
            "other_conditions",
            "required_warning",
            "applicability_requirements",
            "combined_limit_requirements",
            "warning_requirements",
        }
        material_difference = status in {"acd_only", "singapore_only", "ambiguous"} or bool(
            material_fields & differences.keys()
        )
        output.append(
            CrossReference(
                cross_reference_id=f"xref-{mapping_name}-{reference_key.replace(' ', '-')}",
                regulatory_mapping=mapping_name,
                reference_number=display_reference,
                acd_rule_ids=sorted(item["rule_id"] for item in acd_group),
                singapore_rule_ids=sorted(item["rule_id"] for item in sg_group),
                match_basis="reference_number" if acd_group and sg_group else "unmatched",
                comparison_status=status,
                field_differences=differences,
                candidate_matches=sorted(set(candidate_matches)),
                professional_review_required=status != "aligned",
                material_difference=material_difference,
                review_reasons=sorted(set(reasons)),
            )
        )
    return output


def build_cross_references() -> Path:
    rules = load_json(PROCESSED_ROOT / "rules.json")["rules"]
    manifest = load_json(RAW_ROOT / "source_manifest.json")
    comparisons = compare_mapping(
        rules,
        "Annex II Part 1",
        "Third Schedule Part I",
        "annex-ii-to-third-schedule-part-i",
    ) + compare_mapping(
        rules,
        "Annex III Part 1",
        "Third Schedule Part II",
        "annex-iii-to-third-schedule-part-ii",
    )
    output = PROCESSED_ROOT / "source_cross_references.json"
    write_json(
        output,
        {
            "dataset_version": DATASET_VERSION,
            "structural_relationship": {
                "regulation_6_1": "Third Schedule Part I corresponds structurally to ACD Annex II Part 1.",
                "regulation_6_2": "Third Schedule Part II corresponds structurally to ACD Annex III Part 1.",
                "content_parity_assumption": False,
            },
            "source_snapshots": manifest["documents"],
            "cross_references": [item.model_dump() for item in comparisons],
        },
    )
    return output


def build_candidate_cross_references() -> Path:
    rules = load_json(CANDIDATE_PROCESSED_ROOT / "rules.json")["rules"]
    manifest = load_json(CANDIDATE_RAW_ROOT / "source_manifest.json")
    mappings = (
        ("Annex II Part 1", "Third Schedule Part I", "annex-ii-to-third-schedule-part-i"),
        ("Annex III Part 1", "Third Schedule Part II", "annex-iii-to-third-schedule-part-ii"),
        ("Annex IV Part 1", "Third Schedule Part III", "annex-iv-to-third-schedule-part-iii"),
        ("Annex VI", "Third Schedule Part IV", "annex-vi-to-third-schedule-part-iv"),
        ("Annex VII", "Third Schedule Part V", "annex-vii-to-third-schedule-part-v"),
    )
    comparisons = [
        reference
        for acd, singapore, name in mappings
        for reference in compare_mapping(rules, acd, singapore, name)
    ]
    output = CANDIDATE_PROCESSED_ROOT / "source_cross_references.json"
    write_json(output, {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "structural_relationship": {
            f"regulation_6_{index}": f"{singapore} corresponds structurally to {acd}."
            for index, (acd, singapore, _) in enumerate(mappings, start=1)
        } | {"content_parity_assumption": False},
        "source_snapshots": manifest["documents"],
        "cross_references": [item.model_dump() for item in comparisons],
    })
    return output


if __name__ == "__main__":
    print(build_cross_references())
