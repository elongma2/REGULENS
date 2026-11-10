from __future__ import annotations

import re
from collections.abc import Callable

from data_pipeline.scripts.normalize import CAS_STRUCTURE_RE, cas_is_valid

from backend.app.models.document_intake import (
    CompositionLegend,
    CompositionLegendEntry,
    CompositionQuantity,
    CompositionQuantityKind,
    DirectIngredient,
    DisclosureStatus,
    DocumentClassification,
    DocumentExtraction,
    DocumentSourceEvidence,
    MaterialConstituent,
    SupplierMaterial,
)
from backend.app.models.formulation import (
    ConcentrationUnit,
    FormulationConcentration,
    FormulationIngredientRequest,
    PreparationStage,
)
from backend.app.models.screening import ConcentrationType
from backend.app.services.agent_csv import ParsedCSV
from backend.app.services.concentration import parse_concentration_text
from backend.app.services.document_classifier import classify_document


EXTRACTION_SCHEMA_VERSION = "trade-document-v4"
_CAS_IN_TEXT_RE = re.compile(r"(?<!\d)(\d{2,7}-\d{2}-\d)(?!\d)")
_LEGEND_RE = re.compile(
    r"\b([A-Z])\s*(?:=|:)?\s*"
    r"((?:[<>]=?|[≤≥])?\s*\d+(?:\.\d+)?\s*(?:[-–—]|to)?\s*\d*(?:\.\d+)?\s*%?)",
    re.I,
)
_QSP_RE = re.compile(r"\bq\.?\s*s\.?\s*p?\.?\s*(?:to)?\s*(\d+(?:\.\d+)?)\s*%?", re.I)
_QS_ONLY_RE = re.compile(r"^\s*(?:q\.?\s*s\.?\s*p?\.?|balance)\s*$", re.I)
_MAX_RE = re.compile(r"\bmax(?:imum)?\.?\s*(\d+(?:\.\d+)?)\s*(%|percent)?", re.I)
_APPROX_RE = re.compile(r"(?:~|approximately|approx\.?)\s*(\d+(?:\.\d+)?)\s*(%|percent)?", re.I)
_FOLLOWING_SDS_SECTION_RE = re.compile(r"\bsection\s*(?:4|5|6|7|8|9|1[0-6])\b", re.I)
_LEGEND_START_RE = re.compile(r"\b(?:where\s+)?(?:fda|range|concentration)\s+codes?\b", re.I)
_NO_CAS_DISCLOSURE_ROW_RE = re.compile(
    r"^(.+?)\s+(?:not\s+disclosed|not\s+available|n/?a|-)\s+(.+?)\s*$",
    re.I,
)
_PARTIAL_DISCLOSURE_RE = re.compile(
    r"\b(?:partial(?:ly)?\s+(?:composition|disclosure)|"
    r"disclosure\s*(?:status\s*)?[:\-]?\s*partial|"
    r"not\s+all\s+constituents?\s+(?:are\s+)?disclosed|"
    r"remaining\s+(?:ingredients?|constituents?|carrier)\s+not\s+disclosed)\b",
    re.I,
)
_COMPLETE_DISCLOSURE_RE = re.compile(
    r"\b(?:complete\s+(?:supplier\s+)?disclosure|"
    r"disclosure\s*(?:status\s*)?[:\-]?\s*complete|"
    r"complete\s*[-:]?\s*totals?\s+100\s*%)\b",
    re.I,
)
_PERCENT_RANGE_TEXT_RE = re.compile(
    r"^\s*(?P<lower>\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*"
    r"(?P<upper>\d+(?:\.\d+)?)\s*(?:%\s*(?:w/w)?|w/w\s*%|percent)?"
    r"(?:\s*\([^)]*\))?\s*$",
    re.I,
)


IdentityResolver = Callable[[str, str | None], str | None]


def _disclosure_status(parsed: ParsedCSV) -> DisclosureStatus:
    text = "\n".join(" | ".join(row) for row in parsed.rows)
    if _PARTIAL_DISCLOSURE_RE.search(text):
        return DisclosureStatus.PARTIAL
    if _COMPLETE_DISCLOSURE_RE.search(text):
        return DisclosureStatus.COMPLETE
    return DisclosureStatus.UNKNOWN


def _evidence(parsed: ParsedCSV, document_id: str, row_number: int, raw: str) -> DocumentSourceEvidence:
    return DocumentSourceEvidence(
        document_id=document_id,
        page=parsed.row_pages[row_number - 1] if parsed.row_pages else None,
        source_row=row_number,
        source_snippet=parsed.snippet_for_row(row_number),
        raw_value=raw,
    )


def _supplier_quantity(raw: str, *, default_percent: bool = False) -> CompositionQuantity | None:
    value = raw.strip()
    if not value:
        return None
    if match := _QSP_RE.search(value):
        return CompositionQuantity(
            kind=CompositionQuantityKind.REMAINDER_TO_TOTAL,
            value=float(match.group(1)),
            unit="percent",
            quantity_scope="supplier_material",
            raw_text=value,
        )
    if _QS_ONLY_RE.fullmatch(value):
        return CompositionQuantity(
            kind=CompositionQuantityKind.UNKNOWN,
            unit="percent" if default_percent else None,
            quantity_scope="supplier_material",
            raw_text=value,
        )
    if match := _MAX_RE.search(value):
        return CompositionQuantity(
            kind=CompositionQuantityKind.UPPER_BOUND,
            upper=float(match.group(1)),
            upper_inclusive=True,
            unit="percent" if match.group(2) or default_percent else None,
            quantity_scope="supplier_material",
            raw_text=value,
        )
    if match := _APPROX_RE.search(value):
        return CompositionQuantity(
            kind=CompositionQuantityKind.APPROXIMATE,
            value=float(match.group(1)),
            unit="percent" if match.group(2) or default_percent else None,
            quantity_scope="supplier_material",
            raw_text=value,
            approximate=True,
        )
    parsed = parse_concentration_text(value)
    if parsed:
        unit = parsed.unit or ("percent" if default_percent else None)
        return CompositionQuantity(
            kind=CompositionQuantityKind(parsed.concentration_type.value),
            value=parsed.value,
            lower=parsed.lower_bound,
            upper=parsed.upper_bound,
            lower_inclusive=parsed.lower_inclusive,
            upper_inclusive=parsed.upper_inclusive,
            unit=unit,
            quantity_scope="supplier_material",
            raw_text=value,
            approximate=parsed.concentration_type == ConcentrationType.APPROXIMATE,
        )
    if match := re.fullmatch(r"(?:code\s+)?([A-Za-z])", value, re.I):
        return CompositionQuantity(
            kind=CompositionQuantityKind.CODED_RANGE,
            reported_code=match.group(1).upper(),
            quantity_scope="supplier_material",
            raw_text=value,
        )
    return None


def _supplier_quantity_preserving_invalid(
    raw: str,
    *,
    default_percent: bool = False,
) -> CompositionQuantity | None:
    """Preserve a malformed numeric range without normalising its endpoints.

    ``CompositionQuantity`` intentionally rejects reversed ranges, so a source
    such as ``70-40%`` cannot be represented as a RANGE. Keeping it as UNKNOWN
    with the exact source text lets the assembly validator raise a focused
    invalid-bound issue while retaining the ingredient identity and evidence.
    """
    quantity = _supplier_quantity(raw, default_percent=default_percent)
    if quantity is not None:
        return quantity
    match = _PERCENT_RANGE_TEXT_RE.fullmatch(raw.strip())
    if match and float(match.group("lower")) > float(match.group("upper")):
        return CompositionQuantity(
            kind=CompositionQuantityKind.UNKNOWN,
            unit="percent" if default_percent or "%" in raw or "percent" in raw.casefold() else None,
            quantity_scope="supplier_material",
            raw_text=raw.strip(),
        )
    return None


def _formulation_concentration(quantity: CompositionQuantity | None) -> FormulationConcentration | None:
    if quantity is None or quantity.kind == CompositionQuantityKind.CODED_RANGE:
        return None
    unit = None
    if quantity.unit in {item.value for item in ConcentrationUnit}:
        unit = ConcentrationUnit(quantity.unit)
    return FormulationConcentration(
        concentration_type=(
            ConcentrationType.UNKNOWN
            if quantity.kind == CompositionQuantityKind.REMAINDER_TO_TOTAL
            else ConcentrationType(quantity.kind.value)
        ),
        value=quantity.value,
        lower_bound=quantity.lower,
        upper_bound=quantity.upper,
        lower_inclusive=quantity.lower_inclusive,
        upper_inclusive=quantity.upper_inclusive,
        original_text=quantity.raw_text,
        unit=unit,
        basis=None,
        # Rows extracted from a finished formulation or ordinary ingredient
        # list describe amounts in the finished product. Keeping that scope
        # explicit allows a direct addition and a supplier-derived contribution
        # for the same verified ingredient to be aggregated safely.
        preparation_stage=PreparationStage.FINISHED_PRODUCT,
    )


def _legends(parsed: ParsedCSV, document_id: str) -> list[CompositionLegend]:
    entries: list[CompositionLegendEntry] = []
    for row_number, row in enumerate(parsed.rows, start=1):
        raw = " | ".join(row)
        for match in _LEGEND_RE.finditer(raw):
            code = match.group(1).upper()
            separator = raw[match.end(1):match.start(2)]
            # Legacy FDA legends commonly omit '=' for codes A-H. Wider
            # alphabetic codes are accepted only with an explicit separator,
            # so product labels such as "P30" cannot become legend entries.
            if code not in set("ABCDEFGH") and not re.search(r"[=:]", separator):
                continue
            definition = match.group(2).strip()
            quantity = _supplier_quantity(definition, default_percent=True)
            if quantity is None or quantity.kind == CompositionQuantityKind.CODED_RANGE:
                continue
            entries.append(CompositionLegendEntry(
                entry_id=f"{document_id}:legend:{row_number}:{code}",
                code=code,
                raw_definition=definition,
                normalized_quantity=quantity,
                evidence=[_evidence(parsed, document_id, row_number, raw)],
            ))
    if not entries:
        return []
    return [CompositionLegend(
        legend_id=f"{document_id}:legend:1",
        document_id=document_id,
        name="Document concentration legend",
        entries=entries,
    )]


def _header_map(parsed: ParsedCSV) -> tuple[int | None, dict[str, int]]:
    for row_number, row in enumerate(parsed.rows, start=1):
        normalized = [" ".join(cell.casefold().split()) for cell in row]
        mapping: dict[str, int] = {}
        for index, cell in enumerate(normalized):
            if any(token in cell for token in ("inci", "ingredient", "chemical name")):
                mapping.setdefault("name", index)
            if "cas" in cell:
                mapping.setdefault("cas", index)
            if "lower" in cell and any(token in cell for token in ("limit", "bound", "%", "percent")):
                mapping.setdefault("lower", index)
            elif "upper" in cell and any(token in cell for token in ("limit", "bound", "%", "percent")):
                mapping.setdefault("upper", index)
            elif any(token in cell for token in ("unit", "uom")):
                mapping.setdefault("unit", index)
            elif any(token in cell for token in ("code", "fda code", "range code")):
                mapping.setdefault("code", index)
            elif any(token in cell for token in (
                "concentration", "composition", "percentage", "range", "% w/w",
                "usage", "amount",
            )):
                mapping.setdefault("quantity", index)
        # A selectable-text PDF is represented as one cell per line. A line such
        # as "INCI / CAS / concentration" is not a real multi-column header and
        # must be handled by the line parser instead of treating every value as
        # the ingredient name and quantity simultaneously.
        if len(set(mapping.values())) < len(mapping):
            continue
        if "name" in mapping and (
            "cas" in mapping
            or "quantity" in mapping
            or "code" in mapping
            or {"lower", "upper"}.issubset(mapping)
        ):
            return row_number, mapping
    return None, {}


def _range_from_columns(
    row: tuple[str, ...],
    mapping: dict[str, int],
    *,
    default_percent: bool,
) -> CompositionQuantity | None:
    if not {"lower", "upper"}.issubset(mapping):
        return None
    lower_raw = row[mapping["lower"]].strip() if mapping["lower"] < len(row) else ""
    upper_raw = row[mapping["upper"]].strip() if mapping["upper"] < len(row) else ""
    if not lower_raw and not upper_raw:
        return None
    try:
        lower = float(lower_raw) if lower_raw else None
        upper = float(upper_raw) if upper_raw else None
    except ValueError:
        return None
    unit_raw = row[mapping["unit"]].strip() if "unit" in mapping and mapping["unit"] < len(row) else ""
    unit = "percent" if default_percent or "%" in unit_raw or "percent" in unit_raw.casefold() else unit_raw or None
    raw_text = " - ".join(value for value in (lower_raw, upper_raw) if value)
    if unit_raw:
        raw_text = f"{raw_text} {unit_raw}"
    if lower is not None and upper is not None:
        if lower > upper:
            return CompositionQuantity(
                kind=CompositionQuantityKind.UNKNOWN,
                unit=unit,
                quantity_scope="supplier_material",
                raw_text=raw_text,
            )
        return CompositionQuantity(
            kind=CompositionQuantityKind.RANGE,
            lower=lower,
            upper=upper,
            lower_inclusive=None,
            upper_inclusive=None,
            unit=unit,
            quantity_scope="supplier_material",
            raw_text=raw_text,
        )
    if upper is not None:
        return CompositionQuantity(
            kind=CompositionQuantityKind.UPPER_BOUND,
            upper=upper,
            upper_inclusive=None,
            unit=unit,
            quantity_scope="supplier_material",
            raw_text=raw_text,
        )
    return CompositionQuantity(
        kind=CompositionQuantityKind.LOWER_BOUND,
        lower=lower,
        lower_inclusive=None,
        unit=unit,
        quantity_scope="supplier_material",
        raw_text=raw_text,
    )


def _structured_rows(
    parsed: ParsedCSV,
    document_id: str,
) -> list[tuple[str, str | None, CompositionQuantity | None, DocumentSourceEvidence]]:
    header_row, mapping = _header_map(parsed)
    if header_row is None:
        return []
    rows = []
    for row_number, row in enumerate(parsed.rows[header_row:], start=header_row + 1):
        raw = " | ".join(row).strip()
        # A structured export may retain the rows following a composition
        # table. Stop at an SDS section boundary or a document-local legend;
        # neither is an ingredient row.
        if _FOLLOWING_SDS_SECTION_RE.search(raw) or _LEGEND_START_RE.search(raw):
            break
        name = row[mapping["name"]].strip() if mapping["name"] < len(row) else ""
        if not name:
            continue
        cas = row[mapping["cas"]].strip() if "cas" in mapping and mapping["cas"] < len(row) else None
        cas = cas or None
        raw_quantity = row[mapping["quantity"]].strip() if "quantity" in mapping and mapping["quantity"] < len(row) else ""
        if "code" in mapping and mapping["code"] < len(row):
            raw_quantity = row[mapping["code"]].strip() or raw_quantity
        # Repeated headings occur on multi-page tables and must not become a
        # constituent with a missing concentration.
        if re.search(r"\b(?:inci|ingredient|chemical name)\b", name, re.I) and (
            (cas and "cas" in cas.casefold())
            or re.search(r"\b(?:concentration|composition|percentage|code)\b", raw, re.I)
        ):
            continue
        header_text = " | ".join(parsed.rows[header_row - 1])
        quantity = _range_from_columns(
            row,
            mapping,
            default_percent="%" in header_text or "percent" in header_text.casefold(),
        ) or _supplier_quantity_preserving_invalid(
            raw_quantity,
            default_percent="%" in header_text or "percent" in header_text.casefold(),
        )
        rows.append((
            name,
            cas,
            quantity,
            _evidence(parsed, document_id, row_number, raw),
        ))
    return rows


def _text_rows(
    parsed: ParsedCSV,
    document_id: str,
) -> list[tuple[str, str | None, CompositionQuantity | None, DocumentSourceEvidence]]:
    rows = []
    start_row = 1
    end_row = len(parsed.rows)
    section_three = next((
        index for index, row in enumerate(parsed.rows, start=1)
        if re.search(r"\bsection\s*3\b.*\b(?:composition|ingredients?)\b", " | ".join(row), re.I)
    ), None)
    if section_three is not None:
        start_row = section_three + 1
        following_section = next((
            index for index, row in enumerate(parsed.rows[start_row:], start=start_row + 1)
            if re.search(r"\bsection\s*(?:4|5|6|7|8|9|1[0-6])\b", " | ".join(row), re.I)
        ), None)
        if following_section is not None:
            end_row = following_section - 1
    for row_number, row in enumerate(parsed.rows, start=1):
        if row_number < start_row or row_number > end_row:
            continue
        raw = " | ".join(row).strip()
        cas_match = _CAS_IN_TEXT_RE.search(raw)
        if not cas_match:
            continue
        cas = cas_match.group(1)
        before = raw[:cas_match.start()].strip(" |:-")
        after = raw[cas_match.end():].strip(" |:-")
        if not before or re.search(r"\b(?:emergency|telephone|revision|date)\b", before, re.I):
            continue
        quantity = _supplier_quantity_preserving_invalid(after, default_percent="%" in after)
        if quantity is None:
            code_match = re.search(r"(?:^|\s)([A-H])\s*$", after, re.I)
            if code_match:
                quantity = CompositionQuantity(
                    kind=CompositionQuantityKind.CODED_RANGE,
                    reported_code=code_match.group(1).upper(),
                    quantity_scope="supplier_material",
                    raw_text=code_match.group(1),
                )
        rows.append((before, cas, quantity, _evidence(parsed, document_id, row_number, raw)))
    return rows


def _vertical_supplier_rows(
    parsed: ParsedCSV,
    document_id: str,
) -> list[tuple[str, str | None, CompositionQuantity | None, DocumentSourceEvidence]]:
    """Extract supplier tables flattened by PDF text extraction into vertical cells.

    Common composition PDFs render one visual table row as three text lines:
    ingredient name, CAS number, then percentage/range. This remains fully
    deterministic because every value is copied from adjacent source lines.
    """
    values = [(index, " | ".join(row).strip()) for index, row in enumerate(parsed.rows, start=1)]
    start = next((index for index, text in values if re.search(r"\bconstituent\s+composition\b", text, re.I)), None)
    if start is None:
        return []
    end = next((index for index, text in values if index > start and re.search(
        r"^(?:interpretation\s+note|declaration|disclaimer|section\s+4)\b", text, re.I
    )), len(values) + 1)
    by_index = {index: text for index, text in values}
    output = []
    for index in range(start + 1, end):
        raw_cas = by_index.get(index, "")
        cas_match = _CAS_IN_TEXT_RE.fullmatch(raw_cas)
        if not cas_match:
            continue
        name = by_index.get(index - 1, "").strip()
        raw_quantity = by_index.get(index + 1, "").strip()
        if not name or re.search(r"\b(?:inci name|cas number|content|composition)\b", name, re.I):
            continue
        quantity = _supplier_quantity_preserving_invalid(raw_quantity, default_percent=True)
        if quantity is None:
            continue
        combined = f"{name} | {cas_match.group(1)} | {raw_quantity}"
        output.append((
            name,
            cas_match.group(1),
            quantity,
            _evidence(parsed, document_id, index - 1, combined),
        ))
    return output


def _one_cell_supplier_rows(
    parsed: ParsedCSV,
    document_id: str,
) -> list[tuple[str, str | None, CompositionQuantity | None, DocumentSourceEvidence]]:
    """Parse common selectable-text supplier tables flattened to one line per row."""
    header_index = next((
        index for index, row in enumerate(parsed.rows, start=1)
        if len(row) == 1
        and (
            (
                "inci" in row[0].casefold()
                and any(token in row[0].casefold() for token in (
                    "composition", "content", "lower limit", "cas"
                ))
            )
            or (
                "submitted material" in row[0].casefold()
                and "finished product" in row[0].casefold()
            )
        )
    ), None)
    if header_index is None:
        return []
    header = parsed.rows[header_index - 1][0].casefold()
    output: list[tuple[str, str | None, CompositionQuantity | None, DocumentSourceEvidence]] = []

    if "submitted material" in header and "finished product" in header:
        finished_row_re = re.compile(
            r"^(.+?)\s+(?:(\d{2,7}-\d{2}-\d)|-)\s+"
            r"((?:q\.?s\.?\s*to\s*100|[<>≤≥~≈]?\s*\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?)\s*%)"
            r"(?:\s+(?:direct\s+inci|supplier\s+trade))?\s*$",
            re.I,
        )
        for row_number, row in enumerate(parsed.rows[header_index:], start=header_index + 1):
            raw = " | ".join(row).strip()
            match = finished_row_re.match(raw)
            if not match:
                continue
            output.append((
                match.group(1).strip(),
                match.group(2),
                _supplier_quantity_preserving_invalid(match.group(3), default_percent=True),
                _evidence(parsed, document_id, row_number, raw),
            ))
        return output

    if "lower limit" in header and "upper limit" in header:
        range_re = re.compile(
            r"^(.+?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*(%|percent)\s*$",
            re.I,
        )
        for row_number, row in enumerate(parsed.rows[header_index:], start=header_index + 1):
            raw = " | ".join(row).strip()
            if re.search(r"\b(?:non-warranty|disclaimer)\b", raw, re.I):
                break
            match = range_re.match(raw)
            if match:
                quantity = _supplier_quantity_preserving_invalid(
                    f"{match.group(2)}-{match.group(3)}%",
                    default_percent=True,
                )
                output.append((
                    match.group(1).strip(), None, quantity,
                    _evidence(parsed, document_id, row_number, raw),
                ))
            elif output and raw and len(raw) <= 80 and not re.search(r"\d", raw):
                name, cas, quantity, evidence = output[-1]
                output[-1] = (f"{name} {raw}".strip(), cas, quantity, evidence.model_copy(
                    update={"source_snippet": f"{evidence.source_snippet or ''} {raw}".strip()}
                ))
        return output

    if "fda code" in header or "content" in header and "code" in header:
        code_re = re.compile(r"^(.+?)\s+([A-H])\s*$", re.I)
        for row_number, row in enumerate(parsed.rows[header_index:], start=header_index + 1):
            raw = " | ".join(row).strip()
            if re.search(r"\bwhere\s+fda\s+codes?\b", raw, re.I):
                break
            match = code_re.match(raw)
            if not match:
                continue
            output.append((
                match.group(1).strip(), None,
                CompositionQuantity(
                    kind=CompositionQuantityKind.CODED_RANGE,
                    reported_code=match.group(2).upper(),
                    quantity_scope="supplier_material",
                    raw_text=match.group(2).upper(),
                ),
                _evidence(parsed, document_id, row_number, raw),
            ))
        return output

    if "cas" in header:
        quantity_re = re.compile(
            r"^(.*?)\s+((?:q\.?s\.?p\.?\s*(?:to\s*)?\d+(?:\.\d+)?)|"
            r"(?:max(?:imum)?\.?\s*\d+(?:\.\d+)?)|"
            r"(?:(?:~|≈|approx(?:imately)?\.?|\uf0bb)\s*)?\d+(?:\.\d+)?)\s*%?$",
            re.I,
        )
        for row_number, row in enumerate(parsed.rows[header_index:], start=header_index + 1):
            raw = " | ".join(row).strip()
            if re.search(
                r"^(?:disclosure\s+and\s+interpretation|interpretation\s+note|"
                r"declaration|disclaimer|non-warranty)\b",
                raw,
                re.I,
            ):
                break
            cas_match = _CAS_IN_TEXT_RE.search(raw)
            if cas_match:
                before = raw[:cas_match.start()].strip(" |:-")
                after = raw[cas_match.end():].strip(" |:-")
                after_quantity = _supplier_quantity_preserving_invalid(after, default_percent=True)
                if before and after_quantity is not None:
                    output.append((
                        before,
                        cas_match.group(1),
                        after_quantity,
                        _evidence(parsed, document_id, row_number, raw),
                    ))
                    continue
                match = quantity_re.match(before)
                if not match:
                    continue
                name = match.group(1).strip()
                quantity_raw = match.group(2).replace("\uf0bb", "approx. ")
                output.append((
                    name,
                    cas_match.group(1),
                    _supplier_quantity_preserving_invalid(quantity_raw, default_percent=True),
                    _evidence(parsed, document_id, row_number, raw),
                ))
                continue

            missing_cas = _NO_CAS_DISCLOSURE_ROW_RE.match(raw)
            if not missing_cas:
                continue
            output.append((
                missing_cas.group(1).strip(),
                None,
                _supplier_quantity_preserving_invalid(missing_cas.group(2), default_percent=True),
                _evidence(parsed, document_id, row_number, raw),
            ))
        return output
    return []


def extract_document(
    parsed: ParsedCSV,
    *,
    document_id: str,
    classification: DocumentClassification | None = None,
    identity_resolver: IdentityResolver | None = None,
) -> DocumentExtraction:
    classification = classification or classify_document(parsed)
    extracted_rows = (
        _structured_rows(parsed, document_id)
        or _one_cell_supplier_rows(parsed, document_id)
        or _vertical_supplier_rows(parsed, document_id)
        or _text_rows(parsed, document_id)
    )
    legends = _legends(parsed, document_id)
    roles = {item.role.value for item in classification.proposed_roles}
    supplier_mode = (
        classification.recommended_extraction_schema != "finished_product_formulation"
        and bool(roles & {"supplier_composition", "sds_msds", "technical_document"})
    )

    if supplier_mode:
        constituents = []
        for index, (name, cas, quantity, evidence) in enumerate(extracted_rows, start=1):
            constituents.append(MaterialConstituent(
                constituent_id=f"{document_id}:constituent:{index}",
                submitted_name=name,
                cas_number=cas,
                composition_quantity=quantity,
                source_evidence=[evidence],
                verified_identity_group=identity_resolver(name, cas) if identity_resolver else None,
            ))
        fallback_trade_name = re.sub(r"\.(?:pdf|xlsx?|csv)$", "", parsed.filename, flags=re.I)
        fallback_trade_name = re.sub(r"[_]+", " ", fallback_trade_name)
        fallback_trade_name = re.sub(r"^\s*\d+[\s._-]+", "", fallback_trade_name)
        fallback_trade_name = re.sub(
            r"\s+(?:supplier\s+)?composition(?:\s+statement)?"
            r"(?:\s+(?:rev(?:ision)?|version)\s*[a-z0-9._-]+)?$",
            "",
            fallback_trade_name,
            flags=re.I,
        ).strip()
        material = SupplierMaterial(
            material_id=f"{document_id}:material:1",
            trade_name=classification.trade_name or fallback_trade_name or parsed.filename,
            supplier_name=classification.supplier_name,
            product_code=classification.product_code,
            attached_document_ids=[document_id],
            governing_document_id=document_id,
            constituents=constituents,
            disclosure_status=_disclosure_status(parsed),
        )
        return DocumentExtraction(
            document_id=document_id,
            classification=classification,
            supplier_materials=[material],
            legends=legends,
            unresolved_source_rows=[
                evidence for _, _, quantity, evidence in extracted_rows
                if quantity is None or quantity.kind == CompositionQuantityKind.UNKNOWN
            ],
            extraction_schema_version=EXTRACTION_SCHEMA_VERSION,
        )

    direct_rows = []
    unresolved = []
    for index, (name, cas, quantity, evidence) in enumerate(extracted_rows, start=1):
        valid_cas = cas if cas and CAS_STRUCTURE_RE.fullmatch(cas) and cas_is_valid(cas) else None
        direct_rows.append(DirectIngredient(
            ingredient_id=f"{document_id}:ingredient:{index}",
            ingredient=FormulationIngredientRequest(
                name=name,
                cas_number=valid_cas,
                concentration=_formulation_concentration(quantity),
            ),
            source_document_id=document_id,
            source_evidence=[evidence],
            verified_identity_group=identity_resolver(name, valid_cas) if identity_resolver else None,
        ))
        if quantity is None or quantity.kind == CompositionQuantityKind.UNKNOWN or (cas and not valid_cas):
            unresolved.append(evidence)
    return DocumentExtraction(
        document_id=document_id,
        classification=classification,
        direct_ingredients=direct_rows,
        legends=legends,
        unresolved_source_rows=unresolved,
        extraction_schema_version=EXTRACTION_SCHEMA_VERSION,
    )
