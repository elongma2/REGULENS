from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from .config import (
    CANDIDATE_DATASET_VERSION,
    CANDIDATE_PROCESSED_ROOT,
    CANDIDATE_RAW_ROOT,
    DATASET_VERSION,
    PROCESSED_ROOT,
    RAW_ROOT,
    ensure_output_directories,
)
from .extract import write_json
from .models import ConcentrationConstraint, NormalizedRule, SubstanceRecord


CAS_STRUCTURE_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")
CAS_LIKE_RE = re.compile(
    r"(?<!\d)(\d{2,7})\s*-\s*(\d{1,3})\s*-\s*(\d?)(?!\d)"
)
CASE_RE = re.compile(r"(?m)^\s*(?:\(([a-z])\)|([a-z])\))\s*", re.IGNORECASE)
CASE_MARKER_RE = re.compile(r"(?m)^\s*(?:\(([a-z])\)|([a-z])\))", re.IGNORECASE)
PERCENT_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%")
CONCENTRATION_RE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(%|mg\s*/\s*kg|ppm)", re.IGNORECASE
)
UNSTRUCTURED_NUMERIC_CONDITION_RE = re.compile(
    r"(?<![\d.])\d+(?:[.,]\d+)?\s*(?:[μµ]g\s*/\s*kg|kda)\b",
    re.IGNORECASE,
)
RANGE_RE = re.compile(
    r"^A?\d+[a-z]?\s*(?:-|to)\s*A?\d+[a-z]?$", re.IGNORECASE
)

RAW_FILES = {
    "Annex II Part 1": "annex_ii_raw.json",
    "Annex III Part 1": "annex_iii_raw.json",
    "Third Schedule Part I": "singapore_third_schedule_part_i_raw.json",
    "Third Schedule Part II": "singapore_third_schedule_part_ii_raw.json",
    "Annex IV Part 1": "annex_iv_raw.json",
    "Annex VI": "annex_vi_raw.json",
    "Annex VII": "annex_vii_raw.json",
    "Third Schedule Part III": "singapore_third_schedule_part_iii_raw.json",
    "Third Schedule Part IV": "singapore_third_schedule_part_iv_raw.json",
    "Third Schedule Part V": "singapore_third_schedule_part_v_raw.json",
}

SECTION_METADATA = {
    "Annex II Part 1": ("acd-ii", "prohibited", "prohibited", "prohibited", None),
    "Annex III Part 1": ("acd-iii", "restricted", "restricted", "restricted", None),
    "Third Schedule Part I": ("sg-third-schedule-i", "prohibited", "prohibited", "prohibited", None),
    "Third Schedule Part II": ("sg-third-schedule-ii", "restricted", "restricted", "restricted", None),
    "Annex IV Part 1": ("acd-iv", "permitted", "colourant", "positive_list", "colourant"),
    "Annex VI": ("acd-vi", "permitted", "preservative", "positive_list", "preservative"),
    "Annex VII": ("acd-vii", "permitted", "uv_filter", "positive_list", "uv_filter"),
    "Third Schedule Part III": ("sg-third-schedule-iii", "permitted", "colourant", "positive_list", "colourant"),
    "Third Schedule Part IV": ("sg-third-schedule-iv", "permitted", "preservative", "positive_list", "preservative"),
    "Third Schedule Part V": ("sg-third-schedule-v", "permitted", "uv_filter", "positive_list", "uv_filter"),
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def conservative_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("�", "")
    value = re.sub(r"[‐‑‒–—−]", "-", value)
    return re.sub(r"\s+", " ", value).strip()


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def cas_is_valid(value: str) -> bool:
    parts = value.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return False
    body = "".join(parts[:2])
    checksum = sum(int(digit) * multiplier for multiplier, digit in enumerate(reversed(body), 1)) % 10
    return checksum == int(parts[2])


def extract_identifiers(raw_value: str | None) -> tuple[list[str], list[str]]:
    if not raw_value:
        return [], []
    candidates = {
        "-".join(match.groups())
        for match in CAS_LIKE_RE.finditer(raw_value)
    }
    valid = sorted(
        candidate
        for candidate in candidates
        if CAS_STRUCTURE_RE.fullmatch(candidate) and cas_is_valid(candidate)
    )
    malformed = sorted(candidates - set(valid))
    return valid, malformed


def has_conditional_prohibition_wording(value: str | None) -> bool:
    folded = conservative_text(value)
    indicators = (
        "except",
        "exception",
        "unless",
        "when used",
        "if they contain",
        "provided that",
        "provided the",
        "shall be below",
        "does not exceed",
        "trace limit",
    )
    return any(indicator in folded for indicator in indicators)


def has_non_exhaustive_identifier_scope(value: str | None) -> bool:
    return "not limited to the specified cas" in conservative_text(value)


def split_cases(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    matches = list(CASE_RE.finditer(value))
    if len(matches) < 2 or value[: matches[0].start()].strip():
        return None
    output: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = (match.group(1) or match.group(2)).casefold()
        if label in output:
            return None
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        output[label] = value[match.end() : end].strip()
    return output


def parse_concentration(
    text: str | None,
    source_field: str,
    *,
    default_stage: str = "unspecified",
) -> ConcentrationConstraint | None:
    if not text:
        return None
    matches = CONCENTRATION_RE.findall(text)
    if len(matches) != 1:
        return None
    value = float(matches[0][0])
    source_unit = re.sub(r"\s+", "", matches[0][1].casefold())
    unit = "percent" if source_unit == "%" else source_unit
    folded = conservative_text(text)
    if "less than" in folded and "or equal" not in folded:
        comparator = "less_than"
    elif "greater than" in folded and "or equal" not in folded:
        comparator = "greater_than"
    else:
        comparator = "less_than_or_equal"
    if "after mixing" in folded:
        stage = "after_mixing"
    elif "ready for use" in folded:
        stage = "ready_for_use"
    elif "finished product" in folded:
        stage = "finished_product"
    elif "ingredient" in folded or "impurit" in folded:
        stage = "ingredient"
    else:
        stage = default_stage
    basis_match = re.search(
        r"(?i)\b(?:calculated|expressed)\s+as\s+([^\n.;]+)", text
    )
    if not basis_match:
        basis_match = re.search(r"(?i)\(\s*as\s+([^)]+)\)", text)
    basis = basis_match.group(1).strip() if basis_match else None
    return ConcentrationConstraint(
        value=value,
        unit=unit,
        comparator=comparator,
        basis=basis,
        preparation_stage=stage,
        source_field=source_field,
        source_text=text,
    )


def _source_lookup(raw_root: Path = RAW_ROOT) -> dict[str, dict[str, Any]]:
    manifest = load_json(raw_root / "source_manifest.json")
    return {document["source_document"]: document for document in manifest["documents"]}


def _footnote_lookup(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for note in raw.get("footnotes", []):
        output.setdefault(note["footnote_number"], []).append(note)
    return output


def _active(record: dict[str, Any]) -> bool:
    name = conservative_text(record["original_substance_name"])
    inactive_wording = (
        name in {"deleted", "entry deleted", "entry left intentionally blank", "entry intentionally left blank", "entries left intentionally blank"}
        or name.startswith("moved or deleted")
    )
    return bool(name) and not RANGE_RE.fullmatch(record["reference_number"]) and not inactive_wording


def _case_maps(record: dict[str, Any]) -> tuple[list[str] | None, dict[str, dict[str, str]]]:
    fields = {
        "product_context": record.get("original_field_of_use_text"),
        "concentration_text": record.get("original_concentration_text"),
        "other_conditions": record.get("original_conditions_text"),
        "required_warning": record.get("original_warning_text"),
    }
    maps = {name: split_cases(value) for name, value in fields.items()}
    labelled = [value for value in maps.values() if value]
    if not labelled:
        return None, {}
    labels = list(labelled[0])
    if labels != [chr(ord("a") + index) for index in range(len(labels))]:
        return None, {}
    if any(list(value) != labels for value in labelled[1:]):
        return None, {}
    if not maps["product_context"] or not maps["concentration_text"]:
        return None, {}
    return labels, {name: value or {} for name, value in maps.items()}


def _applicability_requirements(text: str | None) -> list[dict[str, Any]]:
    folded = conservative_text(text)
    requirements: list[dict[str, Any]] = []
    patterns = (
        ("rinse_off", "rinse-off", True),
        ("leave_on", "leave-on", True),
        ("oral_care", "oral care", True),
        ("eye_area", "vicinity of eyes", True),
        ("mucous_membrane_contact", "not intended to come into contact with the mucous", False),
        ("brief_skin_contact", "come into contact only briefly with the skin", True),
        ("spray_or_aerosol", "spray", True),
        ("powder_form", "powder", True),
        ("child_use", "children", True),
        ("sun_protection_purpose", "sunscreen", True),
    )
    for fact, marker, expected in patterns:
        if marker in folded:
            requirements.append({"fact": fact, "expected": expected, "source_text": text or ""})
    if "except those intended to be applied in the vicinity of eyes" in folded:
        requirements = [item for item in requirements if item["fact"] != "eye_area"]
        requirements.append({"fact": "eye_area", "expected": False, "source_text": text or ""})
    return requirements


def _warning_requirements(warning: str | None) -> list[dict[str, Any]]:
    if not warning or not warning.strip() or warning.strip() in {".", "-"}:
        return []
    return [{
        "warning_text": warning.strip(),
        "trigger_text": None,
        "applicability": "professional_review",
    }]


def _preamble_warning_requirements(
    section: str,
    reference_number: str,
    preamble: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Link source-wide warning rules to the entries named by the source."""
    if section not in {"Annex VI", "Third Schedule Part IV"}:
        return []
    for item in preamble:
        text = item.get("source_text") or ""
        match = re.search(
            r"(?is)(?:Entries|entries)\s+([0-9,\s]+(?:and\s+\d+)?)\)?\s+must\s+be\s+labelled\s+"
            r"with\s+the\s+warning\s+[“\"]([^”\"]+)[”\"]\.?\s+where\s+(.+?0\.05%)",
            text,
        )
        if not match:
            continue
        named_references = set(re.findall(r"\d+", match.group(1)))
        if reference_number not in named_references:
            continue
        return [{
            "warning_text": match.group(2).strip(),
            "trigger_text": match.group(3).strip(),
            "applicability": "professional_review",
        }]
    return []


def _preamble_uv_warning_requirements(
    section: str,
    preamble: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if section not in {"Annex VII", "Third Schedule Part V"}:
        return []
    for item in preamble:
        text = item.get("source_text") or ""
        match = re.search(
            r"(?is)(Do not stay too long in the sun, even while using a sunscreen product)",
            text,
        )
        if match:
            return [{
                "warning_text": match.group(1),
                "trigger_text": "Applies to a primary sunscreen product.",
                "applicability": "professional_review",
            }]
    return []


def _combined_limit_requirements(
    footnotes: list[dict[str, Any]],
    concentration: ConcentrationConstraint | None,
) -> list[dict[str, Any]]:
    if concentration is None:
        return []
    requirements: list[dict[str, Any]] = []
    known_groups = (
        ("zinc oxide", "zinc-oxide-and-zinc-oxide-nano", ["A29", "A29a"]),
        ("titanium dioxide", "titanium-dioxide-and-titanium-dioxide-nano", ["27", "27a"]),
        (
            "methylene bis-benzotriazolyl tetramethylbutylphenol",
            "mbbt-and-mbbt-nano",
            ["23", "23a"],
        ),
        (
            "bis-(diethylaminohydroxybenzoyl benzoyl) piperazine",
            "piperazine-and-piperazine-nano",
            ["32", "33"],
        ),
    )
    for note in footnotes:
        source_text = note.get("source_text") or ""
        folded = conservative_text(source_text)
        if "combined use" not in folded or "sum" not in folded:
            continue
        for marker, group_key, references in known_groups:
            if marker not in folded:
                continue
            requirements.append({
                "group_key": group_key,
                "maximum": concentration.model_dump(),
                "constituent_references": references,
                "source_text": source_text,
            })
            break
    return requirements


def normalize_rule_source(
    raw: dict[str, Any], source: dict[str, Any], *, raw_file_prefix: str = "data_pipeline/raw"
) -> tuple[list[NormalizedRule], list[SubstanceRecord]]:
    section = raw["section"]
    prefix, restriction_type, regulatory_category, list_semantics, permitted_function = SECTION_METADATA[section]
    rules: list[NormalizedRule] = []
    substances: list[SubstanceRecord] = []
    note_lookup = _footnote_lookup(raw)
    for record in raw["records"]:
        active = _active(record)
        ref_slug = slug(record["reference_number"])
        base_rule_id = f"{prefix}-{ref_slug}"
        substance_id = f"substance-{base_rule_id}" if active else None
        cas_numbers, malformed = extract_identifiers(record.get("cas_number_raw"))
        if active:
            substances.append(
                SubstanceRecord(
                    substance_id=substance_id,
                    source_document=source["source_document"],
                    source_version=source["document_revision"],
                    source_hash=source["sha256"],
                    source_snapshot_generated_at=source["snapshot_generated_at"],
                    regulatory_section=section,
                    reference_number=record["reference_number"],
                    original_substance_name=record["original_substance_name"],
                    normalized_substance_name=conservative_text(record["original_substance_name"]),
                    cas_numbers=cas_numbers,
                    identifiers_raw=record.get("cas_number_raw"),
                    malformed_identifiers=malformed,
                    source_pages=record["source_pages"],
                    raw_record_id=record["raw_record_id"],
                    active=True,
                )
            )
        footnotes = [note for number in record.get("footnote_references", []) for note in note_lookup.get(number, [])]
        supporting_source_texts: list[dict[str, Any]] = []
        if raw.get("preamble"):
            supporting_source_texts.extend(
                {
                    "source_page": int(item["source_page"]),
                    "relationship": "schedule or annex preamble",
                    "source_text": item["source_text"],
                }
                for item in raw["preamble"]
            )
        if section == "Annex II Part 1" and record["reference_number"] == "419":
            supporting_source_texts.extend([
                {
                    "source_page": int(page_number),
                    "relationship": "supporting definition for reference 419",
                    "source_text": text,
                }
                for page_number, text in raw.get("supporting_definitions", {}).items()
            ])
        contributing_pages = sorted(
            {
                *record["source_pages"],
                *(note["source_page"] for note in footnotes),
                *(item["source_page"] for item in supporting_source_texts),
            }
        )
        base_reasons: list[str] = []
        if malformed:
            base_reasons.append("malformed_cas_identifier_preserved")
        if any(
            flag != "entry_spans_multiple_pages" and not flag.startswith("reference_qualification:")
            for flag in record["extraction_flags"]
        ):
            base_reasons.append("nonstandard_extraction_fragment")
        if record.get("jurisdiction_notes"):
            base_reasons.append("jurisdiction_specific_source_wording")
        labels, maps = _case_maps(record) if restriction_type in {"restricted", "permitted"} and active else (None, {})
        case_fields = (
            "original_field_of_use_text",
            "original_concentration_text",
            "original_conditions_text",
            "original_warning_text",
        )
        case_markers = {
            (match.group(1) or match.group(2)).casefold()
            for field in case_fields
            for match in CASE_MARKER_RE.finditer(record.get(field) or "")
        }
        multi_case_present = len(case_markers) >= 2 or any(
            split_cases(record.get(field)) for field in case_fields
        )
        if multi_case_present and labels is None:
            base_reasons.append("multi_case_mapping_not_unambiguous")
        if (
            restriction_type == "prohibited"
            and active
            and has_conditional_prohibition_wording(record["original_substance_name"])
        ):
            base_reasons.append("conditional_prohibition_wording_not_structured")
        if restriction_type == "prohibited" and active and has_non_exhaustive_identifier_scope(record["original_substance_name"]):
            base_reasons.append("non_exhaustive_identifier_scope_not_structured")
        if not active:
            status = "inactive_source_entry"
            base_reasons.append("blank_deleted_or_ranged_source_entry")
        elif base_reasons:
            status = "manual_review_required"
        else:
            status = "normalized"

        cases = labels or [None]
        for case_label in cases:
            def case_value(raw_key: str, normalized_key: str) -> str | None:
                raw_value = record.get(raw_key)
                if case_label is None:
                    return raw_value
                return maps[normalized_key].get(case_label) or raw_value

            product_context = case_value("original_field_of_use_text", "product_context")
            concentration_text = case_value("original_concentration_text", "concentration_text")
            other_conditions = case_value("original_conditions_text", "other_conditions")
            warning = case_value("original_warning_text", "required_warning")
            default_stage = "ready_for_use" if section == "Annex III Part 1" else "finished_product"
            concentration = parse_concentration(
                concentration_text,
                "maximum_concentration",
                default_stage=default_stage,
            )
            combined_limit_requirements = _combined_limit_requirements(footnotes, concentration)
            warning_requirements = [
                *_warning_requirements(warning),
                *_preamble_warning_requirements(
                    section,
                    record["reference_number"],
                    raw.get("preamble", []),
                ),
                *_preamble_uv_warning_requirements(section, raw.get("preamble", [])),
            ]
            reasons = list(base_reasons)
            if restriction_type in {"restricted", "permitted"} and active and concentration_text and concentration is None:
                if CONCENTRATION_RE.search(concentration_text):
                    reasons.append("concentration_contains_multiple_or_ambiguous_values")
            if restriction_type in {"restricted", "permitted"} and active and not concentration_text:
                condition_limit = parse_concentration(other_conditions, "other_conditions")
                if condition_limit:
                    concentration = condition_limit
                elif other_conditions and CONCENTRATION_RE.search(other_conditions):
                    reasons.append("concentration_condition_not_normalized")
            if other_conditions and UNSTRUCTURED_NUMERIC_CONDITION_RE.search(other_conditions):
                reasons.append("additional_numeric_condition_not_structured")
            if "multi_case_mapping_not_unambiguous" in reasons:
                # Retain every original field, but do not expose one case's
                # number as an actionable rule for the whole parent entry.
                concentration = None
                if any(
                    pattern.search((concentration_text or "") + "\n" + (other_conditions or ""))
                    for pattern in (CONCENTRATION_RE, UNSTRUCTURED_NUMERIC_CONDITION_RE)
                ):
                    reasons.append("ambiguous_multi_case_concentration_not_normalized")
            case_status = status
            if reasons and case_status == "normalized":
                case_status = "manual_review_required"
            rule_id = base_rule_id if case_label is None else f"{base_rule_id}-case-{case_label}"
            rules.append(
                NormalizedRule(
                    rule_id=rule_id,
                    parent_rule_id=base_rule_id if case_label is not None else None,
                    case_label=case_label,
                    source_document=source["source_document"],
                    source_version=source["document_revision"],
                    source_bundle_version=source["document_revision"],
                    source_section_version=raw.get("section_version") or source["document_revision"],
                    source_hash=source["sha256"],
                    effective_date=source["effective_date"],
                    source_snapshot_generated_at=source["snapshot_generated_at"],
                    regulatory_section=section,
                    reference_number=record["reference_number"],
                    substance_id=substance_id,
                    substance_name=record["original_substance_name"],
                    cas_numbers=cas_numbers,
                    restriction_type=restriction_type,
                    regulatory_category=regulatory_category,
                    list_semantics=list_semantics,
                    permitted_function=permitted_function,
                    regulatory_identifiers={
                        "cas": cas_numbers,
                        "reference": [record["reference_number"]],
                        "ci": [record["reference_number"]] if regulatory_category == "colourant" else [],
                        "qualifications": sorted(
                            flag.split(":", 1)[1]
                            for flag in record["extraction_flags"]
                            if flag.startswith("reference_qualification:")
                        ),
                    },
                    product_context=product_context,
                    concentration=concentration,
                    concentration_text=concentration_text,
                    other_conditions=other_conditions,
                    required_warning=warning,
                    applicability_requirements=_applicability_requirements(
                        "\n".join(filter(None, (product_context, other_conditions)))
                    ),
                    combined_limit_requirements=combined_limit_requirements,
                    warning_requirements=warning_requirements,
                    footnotes=footnotes,
                    supporting_source_texts=supporting_source_texts,
                    jurisdiction_notes=record.get("jurisdiction_notes", []),
                    source_text=record["source_text"],
                    source_pages=contributing_pages,
                    source_url=source["source_url"],
                    document_revision=source["document_revision"],
                    retrieval_date=source["retrieval_date"],
                    raw_record_id=record["raw_record_id"],
                    raw_file=f"{raw_file_prefix}/{RAW_FILES[section]}",
                    active=active,
                    normalization_status=case_status,
                    review_reasons=sorted(set(reasons)),
                )
            )
    return rules, substances


def build_product_context(appendix: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    definition = appendix["definition_and_background_text"]
    exclusions = [
        {
            "category_id": category["category_id"],
            "source_page": category["source_page"],
            "source_text": category["original_text"],
            "excluded_product_text": match.group(1).strip(),
        }
        for category in appendix["categories"]
        if (match := re.search(r"(?i)with the exception of ([^)]+)", category["original_text"]))
    ]
    return {
        "dataset_version": DATASET_VERSION,
        "source_document": source["source_document"],
        "source_version": source["document_revision"],
        "source_hash": source["sha256"],
        "source_url": source["source_url"],
        "retrieval_date": source["retrieval_date"],
        "source_snapshot_generated_at": source["snapshot_generated_at"],
        "regulatory_section": "Appendix I",
        "definition_text": definition,
        "explicit_exclusions": exclusions,
        "list_is_explicitly_non_exhaustive": appendix["list_is_explicitly_non_exhaustive"],
        "categories": appendix["categories"],
        "model_notes": [
            "Categories and subcategories reproduce only hierarchy explicitly present in Appendix I.",
            "Product form, application area, rinse-off status, and user population remain source text unless explicitly named by a category.",
        ],
    }


def normalize_all() -> dict[str, Path]:
    ensure_output_directories()
    sources = _source_lookup()
    inputs = [
        load_json(RAW_ROOT / "annex_ii_raw.json"),
        load_json(RAW_ROOT / "annex_iii_raw.json"),
        load_json(RAW_ROOT / "singapore_third_schedule_part_i_raw.json"),
        load_json(RAW_ROOT / "singapore_third_schedule_part_ii_raw.json"),
    ]
    rules: list[NormalizedRule] = []
    substances: list[SubstanceRecord] = []
    for raw in inputs:
        source_rules, source_substances = normalize_rule_source(raw, sources[raw["source_document"]])
        rules.extend(source_rules)
        substances.extend(source_substances)

    appendix = load_json(RAW_ROOT / "appendix_i_raw.json")
    regulation = load_json(RAW_ROOT / "singapore_regulation_6_raw.json")
    regulation_source = sources[regulation["source_document"]]
    provisions = {
        "dataset_version": DATASET_VERSION,
        "source_document": regulation["source_document"],
        "source_version": regulation_source["document_revision"],
        "source_hash": regulation_source["sha256"],
        "source_url": regulation_source["source_url"],
        "effective_date": regulation_source["effective_date"],
        "retrieval_date": regulation_source["retrieval_date"],
        "source_snapshot_generated_at": regulation_source["snapshot_generated_at"],
        "regulatory_section": "Regulation 6",
        "provisions": regulation["provisions"],
        "structural_mappings": regulation["structural_mappings"],
        "parity_note": "Structural correspondence does not establish entry-by-entry or version parity between the separately versioned sources.",
    }
    outputs = {
        "product_context": PROCESSED_ROOT / "product_context.json",
        "substances": PROCESSED_ROOT / "substances.json",
        "rules": PROCESSED_ROOT / "rules.json",
        "singapore_provisions": PROCESSED_ROOT / "singapore_provisions.json",
    }
    write_json(outputs["product_context"], build_product_context(appendix, sources[appendix["source_document"]]))
    write_json(outputs["substances"], {"dataset_version": DATASET_VERSION, "substances": [item.model_dump() for item in substances]})
    source_footnotes = [
        {
            "source_document": raw["source_document"],
            "regulatory_section": raw["section"],
            "footnotes": raw.get("footnotes", []),
        }
        for raw in inputs
        if raw.get("footnotes")
    ]
    write_json(
        outputs["rules"],
        {
            "dataset_version": DATASET_VERSION,
            "source_footnotes": source_footnotes,
            "rules": [item.model_dump() for item in rules],
        },
    )
    write_json(outputs["singapore_provisions"], provisions)
    return outputs


def normalize_candidate_all() -> dict[str, Path]:
    CANDIDATE_PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
    sources = _source_lookup(CANDIDATE_RAW_ROOT)
    sections = list(RAW_FILES)
    inputs = [load_json(CANDIDATE_RAW_ROOT / RAW_FILES[section]) for section in sections]
    rules: list[NormalizedRule] = []
    substances: list[SubstanceRecord] = []
    for raw in inputs:
        source_rules, source_substances = normalize_rule_source(
            raw,
            sources[raw["source_document"]],
            raw_file_prefix="data_pipeline/candidate/raw",
        )
        rules.extend(source_rules)
        substances.extend(source_substances)

    appendix = load_json(CANDIDATE_RAW_ROOT / "appendix_i_raw.json")
    regulation = load_json(CANDIDATE_RAW_ROOT / "singapore_regulation_6_raw.json")
    regulation_source = sources[regulation["source_document"]]
    product_context = build_product_context(appendix, sources[appendix["source_document"]])
    product_context["dataset_version"] = CANDIDATE_DATASET_VERSION
    provisions = {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "source_document": regulation["source_document"],
        "source_version": regulation_source["document_revision"],
        "source_hash": regulation_source["sha256"],
        "source_url": regulation_source["source_url"],
        "effective_date": regulation_source["effective_date"],
        "retrieval_date": regulation_source["retrieval_date"],
        "source_snapshot_generated_at": regulation_source["snapshot_generated_at"],
        "regulatory_section": "Regulation 6",
        "provisions": regulation["provisions"],
        "structural_mappings": regulation["structural_mappings"],
        "parity_note": "Structural correspondence does not establish entry-by-entry or version parity between the separately versioned sources.",
    }
    outputs = {
        "product_context": CANDIDATE_PROCESSED_ROOT / "product_context.json",
        "substances": CANDIDATE_PROCESSED_ROOT / "substances.json",
        "rules": CANDIDATE_PROCESSED_ROOT / "rules.json",
        "singapore_provisions": CANDIDATE_PROCESSED_ROOT / "singapore_provisions.json",
    }
    write_json(outputs["product_context"], product_context)
    write_json(outputs["substances"], {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "substances": [item.model_dump() for item in substances],
    })
    source_footnotes = [
        {
            "source_document": raw["source_document"],
            "regulatory_section": raw["section"],
            "preamble": raw.get("preamble", []),
            "footnotes": raw.get("footnotes", []),
        }
        for raw in inputs
        if raw.get("footnotes") or raw.get("preamble")
    ]
    write_json(outputs["rules"], {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "source_footnotes": source_footnotes,
        "rules": [item.model_dump() for item in rules],
    })
    write_json(outputs["singapore_provisions"], provisions)
    return outputs


if __name__ == "__main__":
    for name, path in normalize_all().items():
        print(f"{name}: {path}")
