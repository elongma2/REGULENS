from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "data_pipeline" / "candidate"
OUTPUT_ROOT = ROOT / "docs" / "parts-i-v-verification"


EXPECTED_SOURCE_INFORMATION = {
    "parts-i-v-01": "CI 12085#, Red; allowed in all cosmetic products; 3% maximum concentration in the finished product.",
    "parts-i-v-02": "CI 12085 (2), Red; X in field-of-application column 1 (all cosmetic products); 3% maximum in finished products; footnote (2) covers specified insoluble lakes, salts and pigments and the insolubility test.",
    "parts-i-v-03": "CI 10316#, Yellow; allowed except for products applied near the eyes, especially eye make-up and eye make-up remover.",
    "parts-i-v-04": "Benzoic acid and sodium salt: 2.5% (acid) for rinse-off except oral care, 1.7% (acid) for oral care, and 0.5% (acid) for leave-on products.",
    "parts-i-v-05": "Benzoic acid CAS 65-85-0 and sodium salt CAS 532-32-1 with the same 2.5%, 1.7%, and 0.5% product-specific limits, all expressed as acid.",
    "parts-i-v-06": "Reference 12 lists the named methyl/ethyl parabens and salts; 0.4% as acid for one ester and 0.8% as acid for mixtures of esters.",
    "parts-i-v-07": "Reference 20 is 5-Bromo-5-nitro-1,3 dioxane, CAS 30007-47-7, 0.1%, rinse-off only, avoid nitrosamines. Annex VI preamble requires 'contains formaldehyde' when released formaldehyde exceeds 0.05% for named entries including 20.",
    "parts-i-v-08": "Reference 2 is Propionic acid and its salts with a 2% maximum expressed as acid.",
    "parts-i-v-09": "Singapore Part V reference 3 is Homosalate with a 10% maximum authorised concentration.",
    "parts-i-v-10": "ACD Annex VII A29a is Zinc Oxide (nano), CAS 1314-13-2, 25%; no inhalation exposure; listed purity, particle-size, solubility and coating conditions; footnote 2 requires combined zinc oxide and nano zinc oxide to remain within the column-c limit; Annex VII version 2025-2, 12 December 2025.",
    "parts-i-v-11": "Singapore Part V A29a is Zinc oxide (nano), 25%; no inhalation exposure; listed purity, particle-size, solubility and coating conditions continue across pages 193-194; footnote 4 on page 195 applies the combined zinc-oxide limit.",
    "parts-i-v-12": "ACD Annex VII A28 is Menthyl anthranilate at 5%; the section is version 2025-2, 12 December 2025 even though the bundle is 2026-1.",
    "parts-i-v-regulation-6-3": "Regulation 6(3): except for products intended solely to colour hair, a colouring agent must be in Part III and used according to Part III requirements.",
    "parts-i-v-regulation-6-4": "Regulation 6(4): a preservative must be listed in Part IV, stay within the Part IV limit, and meet the other Part IV requirements.",
    "parts-i-v-regulation-6-5": "Regulation 6(5): a UV filter must be listed in Part V, stay within the Part V limit, and meet the other Part V requirements.",
}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compact_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule["rule_id"],
        "substance_name": rule["substance_name"],
        "cas_numbers": rule.get("cas_numbers", []),
        "regulatory_identifiers": rule.get("regulatory_identifiers", {}),
        "concentration_text": rule.get("concentration_text"),
        "concentration": rule.get("concentration"),
        "product_context": rule.get("product_context"),
        "other_conditions": rule.get("other_conditions"),
        "required_warning": rule.get("required_warning"),
        "warning_requirements": rule.get("warning_requirements", []),
        "combined_limit_requirements": rule.get("combined_limit_requirements", []),
        "footnotes": rule.get("footnotes", []),
        "source_text": rule["source_text"],
        "source_pages": rule["source_pages"],
        "source_bundle_version": rule.get("source_bundle_version"),
        "source_section_version": rule.get("source_section_version"),
        "normalization_status": rule["normalization_status"],
        "review_reasons": rule.get("review_reasons", []),
    }


def build() -> dict[str, Any]:
    checklist = load(CANDIDATE / "reports" / "manual_spot_check_checklist.json")
    results_document = load(CANDIDATE / "reports" / "manual_spot_check_results.json")
    results = {item["check_id"]: item for item in results_document["results"]}
    rules_document = load(CANDIDATE / "processed" / "rules.json")
    provisions_document = load(CANDIDATE / "processed" / "singapore_provisions.json")
    manifest = load(CANDIDATE / "raw" / "source_manifest.json")
    rules = {rule["rule_id"]: rule for rule in rules_document["rules"]}
    provisions = {item["provision_id"]: item for item in provisions_document["provisions"]}
    documents = {item["source_document"]: item for item in manifest["documents"]}
    checks: list[dict[str, Any]] = []
    for item in checklist["checks"]:
        recorded_result = results[item["check_id"]]
        if item["regulatory_section"] == "Regulation 6":
            provision = provisions[item["rule_ids"][0]]
            source_document = "singapore_regulation_6_excerpt"
            extracted = {
                "provision_id": provision["provision_id"],
                "source_pages": provision["source_pages"],
                "source_text": provision["source_text"],
            }
            pages = provision["source_pages"]
        else:
            selected = [compact_rule(rules[rule_id]) for rule_id in item["rule_ids"]]
            source_document = rules[item["rule_ids"][0]]["source_document"]
            extracted = selected[0] if len(selected) == 1 else selected
            pages = item["source_pages"]
        document = documents[source_document]
        checks.append({
            **item,
            "source_document": source_document,
            "source_pdf": f"data_pipeline/Sources/{document['filename']}",
            "source_sha256": document["sha256"],
            "source_revision": document.get("document_revision"),
            "source_url": document["source_url"],
            "pages_to_open": pages,
            "expected_source_information": EXPECTED_SOURCE_INFORMATION[item["check_id"]],
            "extracted_json_values": extracted,
            "automated_checks": "Source hash, required record, provenance, identifier uniqueness, candidate structure and reproducible output hashes.",
            "manual_checks": "Compare the rendered page with every displayed name, identifier, limit, basis, use condition, warning, continuation row, footnote and version. Confirm conservative manual-review status where the source is not safely executable.",
            "result": recorded_result["result"],
            "reviewer_evidence": recorded_result.get("evidence_checked", ""),
            "reviewer_notes": recorded_result.get("notes", ""),
        })
    output = {
        "dataset_version": checklist["dataset_version"],
        "instructions": [
            "Open each listed PDF page or its rendered PNG in source-pages/.",
            "Compare the page with expected_source_information and extracted_json_values.",
            "Use PASS only when every relevant value and qualifier agrees with the source.",
            "Use FAIL for any mismatch and describe it; do not promote while any check is FAIL or PENDING.",
            "After all checks pass, run candidate validation and the full regression suite before promotion.",
        ],
        "checks": checks,
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "verification_checklist.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Parts III-V regulatory source verification",
        "",
        f"Candidate: `{checklist['dataset_version']}`",
        "",
        "## How to review",
        "",
        "1. Open the page image in `source-pages/` and the corresponding immutable PDF.",
        "2. Confirm the reference, name/CAS/CI, limit and basis, product-use conditions, warning, footnote, continuation rows, and document version.",
        "3. Compare those facts with the extracted JSON values in `verification_checklist.json` or the workbook.",
        "4. Record `PASS` only when all relevant facts match. Record `FAIL` and the mismatch otherwise.",
        "5. Promotion remains blocked until all 15 required checks are recorded as `PASS` and regression tests succeed.",
        "",
        "## Automated versus manual",
        "",
        "Automated checks cover source hashes, record presence, provenance, schema validity, duplicate IDs, required sections, reproducible candidate hashes, and test expectations. Manual review covers visual row alignment, continuation text, column meaning, footnote/preamble attachment, warning scope, and Regulation 6 meaning.",
        "",
        "## Verification cases",
        "",
    ]
    for index, check in enumerate(checks, 1):
        lines.extend([
            f"### {index}. {check['check_id']} — {check['regulatory_section']} {check['reference_number']}",
            "",
            f"- Purpose: {check['purpose']}",
            f"- PDF: `{check['source_pdf']}`",
            f"- Pages: {', '.join(map(str, check['pages_to_open']))}",
            f"- Expected on source: {check['expected_source_information']}",
            f"- Rule/provision: `{', '.join(check['rule_ids'])}`",
            f"- Result: **{check['result']}**",
            f"- Evidence checked: {check['reviewer_evidence'] or 'Not yet recorded'}",
            f"- Notes: {check['reviewer_notes'] or 'None'}",
            "",
        ])
    (OUTPUT_ROOT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    return output


if __name__ == "__main__":
    document = build()
    print(f"checks={len(document['checks'])}")
