from __future__ import annotations

import re

from backend.app.models.document_intake import (
    DocumentClassification,
    DocumentRole,
    DocumentRoleEvidence,
)
from backend.app.services.agent_csv import ParsedCSV


_SDS_RE = re.compile(r"\b(?:safety data sheet|material safety data sheet|sds|msds)\b", re.I)
_SECTION_THREE_RE = re.compile(r"\bsection\s*3\b.*\b(?:composition|ingredients?)\b", re.I)
_IDENTITY_HEADER_RE = re.compile(r"\b(?:inci|ingredient|chemical name|cas(?:\s+no\.?)?)\b", re.I)
_QUANTITY_HEADER_RE = re.compile(
    r"\b(?:concentration|composition|percentage|lower limit|upper limit|"
    r"%\s*w/w|supplier[- ]material|fda code|range code)\b",
    re.I,
)
_COMPOSITION_STATEMENT_RE = re.compile(
    r"\b(?:percentage\s+composition\s+statement\s+for|"
    r"statement\s+regarding\s+the\s+composition\s+of\s+product\s*:?)\s*(.+)$",
    re.I,
)
_PRODUCT_INFORMATION_RE = re.compile(r"^\s*product\s+information\s*$", re.I)
_ITEM_CODE_RE = re.compile(r"\bitem\s+code\s*:\s*([A-Za-z0-9._\-/]+)", re.I)
_KNOWN_PRODUCT_CODE_RE = re.compile(r"\b((?:EN|SE)\d{5})\b", re.I)
_FORMULATION_RE = re.compile(r"\b(?:finished[- ]product formulation|formulation|formula)\b", re.I)
_USAGE_RE = re.compile(r"\b(?:use level|dosage|addition|finished product|amount used)\b", re.I)
_PRODUCT_RE = re.compile(
    r"^\s*(?:product|trade)\s*(?:name|designation)?\s*[:\-]\s*(.+)$",
    re.I,
)
_SUPPLIER_RE = re.compile(
    r"^\s*(?:supplier|manufacturer)(?:\s*:\s*|\s+-\s+)(.+)$",
    re.I,
)
_PRODUCT_CODE_RE = re.compile(r"\b(?:product|item|material)\s*(?:code|no\.?|number)\s*[:\-]\s*(.+)$", re.I)
_REVISION_RE = re.compile(r"\b(?:revision|rev\.?|version)\s*[:\-]?\s*([A-Za-z0-9._\-/]+)", re.I)
_MULTIPLE_PRODUCTS_RE = re.compile(r"\bdocument contains multiple products\s*:\s*yes\b", re.I)
_SUPPLIER_COMPOSITION_TITLE_RE = re.compile(
    r"^\s*(.+?)\s*(?:[—–-])\s*supplier\s+composition\s+statement\s*$",
    re.I,
)
_SUPPLIER_COMPOSITION_SIGNAL_RE = re.compile(r"\bsupplier\s+composition\s+statement\b", re.I)


def _source_lines(parsed: ParsedCSV) -> list[tuple[int, int | None, str]]:
    return [
        (index, parsed.row_pages[index - 1] if parsed.row_pages else None, " | ".join(row))
        for index, row in enumerate(parsed.rows, start=1)
    ]


def _first_match(pattern: re.Pattern[str], lines: list[tuple[int, int | None, str]]) -> str | None:
    for _, _, line in lines:
        match = pattern.search(line)
        if match:
            return match.group(1).strip(" |")
    return None


def _value_after_label(
    label: str,
    lines: list[tuple[int, int | None, str]],
) -> str | None:
    label_pattern = re.compile(rf"^\s*{re.escape(label)}\s*:?\s*$", re.I)
    for index, (_, _, line) in enumerate(lines[:-1]):
        if label_pattern.match(line):
            value = lines[index + 1][2].strip(" |")
            return value or None
    return None


def _inline_value_after_label(
    label: str,
    lines: list[tuple[int, int | None, str]],
) -> str | None:
    pattern = re.compile(rf"^\s*{re.escape(label)}\s+(.+?)\s*$", re.I)
    for _, _, line in lines:
        match = pattern.match(line)
        if match:
            return match.group(1).strip(" |") or None
    return None


def classify_document(parsed: ParsedCSV) -> DocumentClassification:
    lines = _source_lines(parsed)
    text = "\n".join(line for _, _, line in lines)
    roles: list[DocumentRoleEvidence] = []

    def evidence(role: DocumentRole, pattern: re.Pattern[str], confidence: str, reason: str) -> None:
        match = next(((page, line) for _, page, line in lines if pattern.search(line)), None)
        if match:
            roles.append(DocumentRoleEvidence(
                role=role,
                confidence=confidence,
                page=match[0],
                source_snippet=match[1][:500],
                reasons=[reason],
            ))

    if _SDS_RE.search(text):
        evidence(DocumentRole.SDS_MSDS, _SDS_RE, "high", "The document identifies itself as an SDS/MSDS.")
    elif _SECTION_THREE_RE.search(text):
        evidence(DocumentRole.SDS_MSDS, _SECTION_THREE_RE, "medium", "The document contains an SDS-style composition section.")

    identity_rows = sum(bool(_IDENTITY_HEADER_RE.search(line)) for _, _, line in lines)
    quantity_rows = sum(bool(_QUANTITY_HEADER_RE.search(line)) for _, _, line in lines)
    has_supplier_identity = any(_SUPPLIER_RE.search(line) for _, _, line in lines)
    has_product_identity = any(_PRODUCT_RE.search(line) for _, _, line in lines)
    vertical_supplier = (
        _value_after_label("Supplier", lines)
        or _inline_value_after_label("Supplier", lines)
    )
    vertical_trade_name = (
        _value_after_label("Trade name", lines)
        or _inline_value_after_label("Trade name", lines)
    )
    has_supplier_composition_signal = bool(_SUPPLIER_COMPOSITION_SIGNAL_RE.search(text))
    has_supplier_identity = has_supplier_identity or vertical_supplier is not None
    has_product_identity = has_product_identity or vertical_trade_name is not None
    formulation_match = next(((page, line) for _, page, line in lines if _FORMULATION_RE.search(line)), None)
    usage_match = next(((page, line) for _, page, line in lines if _USAGE_RE.search(line)), None)

    composition_statement = next((
        (page, line) for _, page, line in lines
        if _COMPOSITION_STATEMENT_RE.search(line)
    ), None)
    product_information = any(_PRODUCT_INFORMATION_RE.search(line) for _, _, line in lines)

    if identity_rows and quantity_rows:
        role = DocumentRole.SUPPLIER_COMPOSITION if (
            _SDS_RE.search(text)
            or _SECTION_THREE_RE.search(text)
            or has_product_identity
            or has_supplier_identity
            or composition_statement
            or product_information
            or has_supplier_composition_signal
        ) else DocumentRole.INGREDIENT_LIST
        sample = next(line for _, _, line in lines if _IDENTITY_HEADER_RE.search(line))
        page = next(page for _, page, line in lines if line == sample)
        roles.append(DocumentRoleEvidence(
            role=role,
            confidence="high" if role == DocumentRole.SUPPLIER_COMPOSITION else "medium",
            page=page,
            source_snippet=sample[:500],
            reasons=["Ingredient identity and composition columns are present."],
        ))

    if formulation_match and usage_match:
        roles.append(DocumentRoleEvidence(
            role=DocumentRole.FINISHED_PRODUCT_FORMULATION,
            confidence="high",
            page=formulation_match[0],
            source_snippet=formulation_match[1][:500],
            reasons=["Formulation context and finished-product usage language are both present."],
        ))

    if not roles and identity_rows:
        roles.append(DocumentRoleEvidence(
            role=DocumentRole.INGREDIENT_LIST,
            confidence="medium",
            source_snippet=next(line for _, _, line in lines if _IDENTITY_HEADER_RE.search(line))[:500],
            reasons=["Ingredient identities are present without enough evidence for a narrower role."],
        ))
    if not roles:
        roles.append(DocumentRoleEvidence(
            role=DocumentRole.UNKNOWN,
            confidence="low",
            reasons=["No deterministic document-role signal was strong enough."],
        ))

    product_values = {
        match.group(1).strip(" |")
        for _, _, line in lines
        if (match := _PRODUCT_RE.search(line))
    }
    for _, _, line in lines:
        match = _COMPOSITION_STATEMENT_RE.search(line)
        if match:
            product_values.add(match.group(1).strip(" |"))
        title_match = _SUPPLIER_COMPOSITION_TITLE_RE.search(line)
        if title_match:
            product_values.add(title_match.group(1).strip(" |"))
    if vertical_trade_name:
        product_values.add(vertical_trade_name)
    if not product_values and product_information:
        for index, (_, _, line) in enumerate(lines):
            if _ITEM_CODE_RE.search(line) and index:
                candidate = lines[index - 1][2].strip(" |")
                if candidate and not re.search(r"\b(?:date|september|page)\b", candidate, re.I):
                    product_values.add(candidate)
                    break
    product_code = _first_match(_PRODUCT_CODE_RE, lines)
    if product_code is None:
        product_code = (
            _value_after_label("Product code", lines)
            or _inline_value_after_label("Product code", lines)
        )
    if product_code is None:
        code_match = _KNOWN_PRODUCT_CODE_RE.search(text)
        product_code = code_match.group(1).upper() if code_match else None
    primary_roles = {item.role for item in roles}
    if DocumentRole.FINISHED_PRODUCT_FORMULATION in primary_roles:
        schema = "finished_product_formulation"
    elif DocumentRole.SDS_MSDS in primary_roles:
        schema = "sds_composition"
    elif DocumentRole.SUPPLIER_COMPOSITION in primary_roles:
        schema = "supplier_composition"
    elif DocumentRole.INGREDIENT_LIST in primary_roles:
        schema = "ingredient_list"
    else:
        schema = "unknown"
    if len(primary_roles - {DocumentRole.UNKNOWN}) > 1 and schema not in {
        "sds_composition", "finished_product_formulation"
    }:
        schema = "mixed"

    multiple_products = len(product_values) > 1 or bool(_MULTIPLE_PRODUCTS_RE.search(text))
    return DocumentClassification(
        proposed_roles=roles,
        supplier_name=_first_match(_SUPPLIER_RE, lines) or vertical_supplier,
        trade_name=next(iter(product_values), None) if len(product_values) == 1 else None,
        product_code=product_code,
        document_revision_label=(
            _value_after_label("Document revision", lines)
            or _inline_value_after_label("Document revision", lines)
            or _first_match(_REVISION_RE, lines)
        ),
        possible_formulation_ids=sorted(product_values) if multiple_products else [],
        multiple_products_detected=multiple_products,
        recommended_extraction_schema=schema,
        questions=(
            ["This document appears to describe more than one product. Select or split the applicable product."]
            if multiple_products else []
        ),
    )
