from __future__ import annotations

from collections import Counter

from backend.app.models.document_intake import (
    AssemblyIssue,
    AssemblyIssueScope,
    AssemblyIssueSeverity,
    CompositionLegend,
    CompositionQuantity,
    CompositionQuantityKind,
)


def normalize_legend_code(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def validate_legend(legend: CompositionLegend) -> list[AssemblyIssue]:
    normalized = [normalize_legend_code(entry.code) for entry in legend.entries]
    duplicates = {code for code, count in Counter(normalized).items() if count > 1}
    issues: list[AssemblyIssue] = []
    for code in sorted(duplicates):
        issues.append(AssemblyIssue(
            issue_id=f"legend:{legend.legend_id}:duplicate:{code}",
            code="missing_legend",
            severity=AssemblyIssueSeverity.ERROR,
            scope=AssemblyIssueScope.DOCUMENT,
            message=f"Legend code {code!r} is defined more than once in this document.",
            reviewer_action="Confirm the correct code definition in this supplier document.",
            blocking_for_calculation=True,
            document_ids=[legend.document_id],
            evidence=[evidence for entry in legend.entries for evidence in entry.evidence],
        ))
    return issues


def resolve_coded_quantity(
    quantity: CompositionQuantity,
    legend: CompositionLegend | None,
    *,
    document_id: str,
    material_id: str | None = None,
    constituent_id: str | None = None,
) -> tuple[CompositionQuantity | None, list[AssemblyIssue]]:
    if quantity.kind != CompositionQuantityKind.CODED_RANGE:
        return quantity, []

    target_ids = {
        "document_ids": [document_id],
        "material_ids": [material_id] if material_id else [],
        "constituent_ids": [constituent_id] if constituent_id else [],
    }
    if legend is None or legend.document_id != document_id:
        return None, [AssemblyIssue(
            issue_id=f"legend:{document_id}:{constituent_id or quantity.reported_code}:missing",
            code="missing_legend",
            severity=AssemblyIssueSeverity.REVIEW_REQUIRED,
            scope=AssemblyIssueScope.CONSTITUENT,
            message=f"Code {quantity.reported_code!r} has no verified legend in the same document.",
            reviewer_action="Confirm the code definition from this exact supplier-document revision.",
            blocking_for_calculation=True,
            **target_ids,
        )]

    legend_issues = validate_legend(legend)
    if legend_issues:
        return None, legend_issues

    wanted = normalize_legend_code(quantity.reported_code or "")
    matches = [entry for entry in legend.entries if normalize_legend_code(entry.code) == wanted]
    if len(matches) != 1:
        return None, [AssemblyIssue(
            issue_id=f"legend:{legend.legend_id}:{wanted}:unknown",
            code="unknown_legend_code",
            severity=AssemblyIssueSeverity.REVIEW_REQUIRED,
            scope=AssemblyIssueScope.CONSTITUENT,
            message=f"Code {quantity.reported_code!r} is not uniquely defined by the document legend.",
            reviewer_action="Correct the reported code or confirm the matching legend entry.",
            blocking_for_calculation=True,
            **target_ids,
        )]

    entry = matches[0]
    resolved = entry.normalized_quantity.model_copy(update={
        "raw_text": quantity.raw_text or entry.raw_definition,
        "reported_code": quantity.reported_code,
        "legend_entry_id": entry.entry_id,
    })
    return resolved, []
