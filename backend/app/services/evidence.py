from __future__ import annotations

from typing import Any

from backend.app.models.screening import RuleEvidence
from backend.app.services.loader import RegulatoryStore


def _raw_fragments(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    if raw.get("fragments"):
        return [
            {"raw_record_id": raw["raw_record_id"], **fragment}
            for fragment in raw["fragments"]
        ]
    fields = (
        "raw_record_id",
        "page",
        "pages",
        "row_bbox",
        "cell_bboxes",
        "row_fragments",
        "original_cells",
        "source_text",
        "original_row_text",
    )
    return [{field: raw[field] for field in fields if field in raw}]


def build_rule_evidence(store: RegulatoryStore, rule: dict[str, Any]) -> RuleEvidence:
    provisions: list[dict[str, Any]] = []
    if rule["regulatory_section"] == "Third Schedule Part I":
        provision_ids = ("sg-regulation-6-1", "sg-regulation-6-7")
    elif rule["regulatory_section"] == "Third Schedule Part II":
        provision_ids = ("sg-regulation-6-2", "sg-regulation-6-7")
    elif rule["regulatory_section"] == "Third Schedule Part III":
        provision_ids = ("sg-regulation-6-3", "sg-regulation-6-7")
    elif rule["regulatory_section"] == "Third Schedule Part IV":
        provision_ids = ("sg-regulation-6-4", "sg-regulation-6-7")
    elif rule["regulatory_section"] == "Third Schedule Part V":
        provision_ids = ("sg-regulation-6-5", "sg-regulation-6-7")
    else:
        provision_ids = ()
    for provision_id in provision_ids:
        if provision_id in store.provisions_by_id:
            provisions.append(
                {
                    **store.provisions_by_id[provision_id],
                    "source_version": store.provisions_document["source_version"],
                    "effective_date": store.provisions_document["effective_date"],
                    "retrieval_date": store.provisions_document["retrieval_date"],
                    "source_url": store.provisions_document["source_url"],
                    "source_hash": store.provisions_document["source_hash"],
                }
            )

    cross_references = list(store.cross_references_by_rule_id.get(rule["rule_id"], ()))
    counterpart_ids = {
        rule_id
        for cross_reference in cross_references
        for rule_id in cross_reference["acd_rule_ids"]
        if rule_id != rule["rule_id"]
    }
    counterparts = []
    for rule_id in sorted(counterpart_ids):
        counterpart = store.rules_by_id[rule_id]
        counterparts.append(
            {
                **counterpart,
                "raw_fragments": _raw_fragments(store.raw_by_id.get(counterpart["raw_record_id"])),
            }
        )
    raw = store.raw_by_id.get(rule["raw_record_id"])
    return RuleEvidence(
        dataset_version=store.dataset_version,
        rule_id=rule["rule_id"],
        source_document=rule["source_document"],
        source_version=rule.get("source_version"),
        effective_date=rule.get("effective_date"),
        document_revision=rule.get("document_revision"),
        retrieval_date=rule["retrieval_date"],
        source_url=rule["source_url"],
        regulatory_section=rule["regulatory_section"],
        reference_number=rule["reference_number"],
        substance_name=rule["substance_name"],
        product_context=rule.get("product_context"),
        concentration=rule.get("concentration"),
        other_conditions=rule.get("other_conditions"),
        required_warning=rule.get("required_warning"),
        source_text=rule["source_text"],
        source_pages=rule["source_pages"],
        normalization_status=rule["normalization_status"],
        review_reasons=rule["review_reasons"],
        raw_record_id=rule["raw_record_id"],
        raw_fragments=_raw_fragments(raw),
        regulation_6_provisions=provisions,
        cross_references=cross_references,
        acd_counterpart_rules=counterparts,
        regulatory_category=rule.get("regulatory_category"),
        list_semantics=rule.get("list_semantics"),
        permitted_function=rule.get("permitted_function"),
        applicability_requirements=rule.get("applicability_requirements", []),
        combined_limit_requirements=rule.get("combined_limit_requirements", []),
        warning_requirements=rule.get("warning_requirements", []),
        source_bundle_version=rule.get("source_bundle_version"),
        source_section_version=rule.get("source_section_version"),
    )
