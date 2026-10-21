from __future__ import annotations

import hashlib
import json
import re
import statistics
from pathlib import Path
from typing import Any, Iterable

import pdfplumber
from pypdf import PdfReader

from .config import (
    ACD_PDF,
    APPENDIX_I_PDF,
    DATASET_VERSION,
    CANDIDATE_DATASET_VERSION,
    CANDIDATE_RAW_ROOT,
    RAW_ROOT,
    SINGAPORE_FULL_PDF,
    SINGAPORE_REGULATION_6_PDF,
    SOURCE_DEFINITIONS,
    ensure_output_directories,
)
from .models import RawFragment, RawRecord, SourceDocument


ACD_ANNEX_II_VERTICAL_LINES = [86.744, 404.0, 481.0, 548.3]
ACD_ANNEX_III_VERTICAL_LINES = [55.224, 122.69, 292.66, 418.68, 540.17, 660.43, 819.36]
ACD_ANNEX_VI_VERTICAL_LINES = [62.304, 112.952, 321.1, 449.06, 577.27, 705.46]
ACD_ANNEX_VII_VERTICAL_LINES = [73.704, 126.05, 373.56, 450.14, 616.75, 747.34]
REFERENCE_RE = re.compile(
    r"^(?:A?\d+[a-z]?)(?:\s*(?:-|to)\s*(?:A?\d+[a-z]?))?$", re.IGNORECASE
)
CAS_LIKE_RE = re.compile(
    r"(?<!\d)\d{2,7}\s*-\s*\d{1,3}\s*-\s*\d?(?!\d)"
)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_cell(value: str | None) -> str:
    return (value or "").replace("\x00", "").strip()


def join_cell_fragments(values: Iterable[str]) -> str:
    return "\n".join(value for value in values if value).strip()


def source_manifest() -> dict[str, Any]:
    documents: list[dict[str, Any]] = []
    for source_document, definition in SOURCE_DEFINITIONS.items():
        path = definition["path"]
        if not path.exists():
            raise FileNotFoundError(f"Required source is missing: {path}")
        reader = PdfReader(path)
        metadata = {
            str(key).removeprefix("/"): str(value)
            for key, value in (reader.metadata or {}).items()
        }
        document = SourceDocument(
            source_document=source_document,
            title=definition["title"],
            authority=definition["authority"],
            filename=path.name,
            sha256=sha256(path),
            page_count=len(reader.pages),
            source_url=definition["source_url"],
            document_revision=definition["document_revision"],
            effective_date=definition["effective_date"],
            retrieval_date=definition["retrieval_date"],
            snapshot_generated_at=definition["snapshot_generated_at"],
            pdf_metadata=metadata,
        )
        documents.append(document.model_dump())
    return {"dataset_version": DATASET_VERSION, "documents": documents}


def _fragment(
    page_number: int,
    table_bbox: tuple[float, float, float, float] | None,
    row_bbox: tuple[float, float, float, float] | None,
    cells: list[str | None],
    *,
    is_continuation: bool,
) -> RawFragment:
    clean_cells = [clean_cell(cell) for cell in cells]
    return RawFragment(
        source_page=page_number,
        table_bbox=[round(value, 3) for value in table_bbox] if table_bbox else None,
        row_bbox=[round(value, 3) for value in row_bbox] if row_bbox else None,
        cells=clean_cells,
        original_row_text=" | ".join(clean_cells),
        is_continuation=is_continuation,
    )


def _finalize_record(
    record: dict[str, Any],
    column_count: int,
    *,
    reference_index: int,
    substance_index: int,
    cas_index: int | None,
    field_of_use_index: int | None = None,
    concentration_index: int | None = None,
    conditions_index: int | None = None,
    warning_index: int | None = None,
) -> RawRecord:
    fragments: list[RawFragment] = record["fragments"]
    combined = [join_cell_fragments(fragment.cells[index] for fragment in fragments) for index in range(column_count)]
    flags = list(record["extraction_flags"])
    if len({fragment.source_page for fragment in fragments}) > 1:
        flags.append("entry_spans_multiple_pages")
    source_text = "\n".join(fragment.original_row_text for fragment in fragments).strip()
    jurisdiction_notes = sorted(
        {
            line.strip()
            for line in source_text.splitlines()
            if any(country in line.casefold() for country in ("singapore", "indonesia", "malaysia", "thailand", "lao pdr"))
        }
    )
    cas_number_raw = combined[cas_index] if cas_index is not None else None
    if cas_index is None and column_count >= 5:
        # Several annexes place CAS identifiers inside the substance cell. Keep the
        # exact extracted spelling here, including line breaks and malformed
        # source values; normalization validates and canonicalizes separately.
        extracted_identifiers = [
            match.group(0).strip()
            for match in CAS_LIKE_RE.finditer(combined[substance_index])
        ]
        cas_number_raw = "\n".join(extracted_identifiers) or None
    return RawRecord(
        raw_record_id=record["raw_record_id"],
        source_document=record["source_document"],
        section=record["section"],
        reference_number=record["reference_number"],
        reference_number_raw=combined[reference_index],
        original_substance_name=combined[substance_index],
        cas_number_raw=cas_number_raw,
        original_field_of_use_text=(combined[field_of_use_index] if field_of_use_index is not None else (combined[2] if column_count == 6 else None)),
        original_concentration_text=(combined[concentration_index] if concentration_index is not None else (combined[3] if column_count == 6 else None)),
        original_conditions_text=(combined[conditions_index] if conditions_index is not None else (combined[4] if column_count == 6 else None)),
        original_warning_text=(combined[warning_index] if warning_index is not None else (combined[5] if column_count == 6 else None)),
        source_text=source_text,
        source_pages=sorted({fragment.source_page for fragment in fragments}),
        fragments=fragments,
        footnote_references=sorted(record["footnote_references"], key=int),
        jurisdiction_notes=jurisdiction_notes,
        extraction_flags=sorted(set(flags)),
    )


def _superscript_footnote_references(
    page: pdfplumber.page.Page,
    row_bbox: tuple[float, float, float, float],
) -> set[str]:
    x0, top, x1, bottom = row_bbox
    chars = [
        char
        for char in page.chars
        if x0 <= (char["x0"] + char["x1"]) / 2 <= x1
        and top <= (char["top"] + char["bottom"]) / 2 <= bottom
    ]
    if not chars:
        return set()
    median_size = statistics.median(float(char["size"]) for char in chars)
    joined = "".join(char["text"] for char in chars)
    references: set[str] = set()
    for match in re.finditer(r"\((\d{1,2})\)", joined):
        marker_chars = chars[match.start() : match.end()]
        if marker_chars and max(float(char["size"]) for char in marker_chars) <= median_size * 0.8:
            references.add(match.group(1))
    return references


def _extract_table_records(
    *,
    pdf_path: Path,
    source_document: str,
    section: str,
    page_numbers: range,
    column_count: int,
    vertical_lines: list[float] | None = None,
    text_x_tolerance: float = 3.0,
    reference_index: int = 0,
    substance_index: int = 1,
    cas_index: int | None = None,
    field_of_use_index: int | None = None,
    concentration_index: int | None = None,
    conditions_index: int | None = None,
    warning_index: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, str]]:
    records: list[RawRecord] = []
    page_diagnostics: list[dict[str, Any]] = []
    page_texts: dict[int, str] = {}
    current: dict[str, Any] | None = None
    with pdfplumber.open(pdf_path) as document:
        for page_number in page_numbers:
            page = document.pages[page_number - 1]
            page_texts[page_number] = page.extract_text(x_tolerance=text_x_tolerance) or ""
            settings: dict[str, Any] = {}
            if vertical_lines:
                settings = {
                    "vertical_strategy": "explicit",
                    "explicit_vertical_lines": vertical_lines,
                }
            found_tables = page.find_tables(settings)
            candidates = [table for table in found_tables if len(table.columns) == column_count]
            page_diagnostics.append(
                {
                    "source_page": page_number,
                    "table_count": len(candidates),
                    "column_counts": [len(table.columns) for table in found_tables],
                }
            )
            for table in candidates:
                extracted_rows = table.extract(
                    x_tolerance=text_x_tolerance, y_tolerance=3
                )
                for extracted, table_row in zip(extracted_rows, table.rows, strict=True):
                    cells = [clean_cell(cell) for cell in extracted]
                    compact = re.sub(r"\s+", "", "".join(cells).casefold())
                    if not any(cells):
                        continue
                    if (
                        compact.startswith("refno")
                        or compact.startswith("substancescasnumberref.no")
                        or compact.startswith("firstcolumnsecondcolumn")
                        or cells == ["A", "B", "C", "D", "E", "F"]
                        or "fieldofapplicationand/oruse" in compact
                    ):
                        continue
                    reference_raw = cells[reference_index]
                    reference_first_line_raw = re.sub(
                        r"\s+", " ", reference_raw.splitlines()[0]
                    ).strip() if reference_raw else ""
                    reference_first_line = re.sub(
                        r"\s*(?:\((?:\d+|\+)\)|[+#*]+)\s*$", "", reference_first_line_raw
                    ).strip()
                    is_new_reference = bool(REFERENCE_RE.fullmatch(reference_first_line))
                    if is_new_reference:
                        if current is not None:
                            records.append(
                                _finalize_record(
                                    current,
                                    column_count,
                                    reference_index=reference_index,
                                    substance_index=substance_index,
                                    cas_index=cas_index,
                                    field_of_use_index=field_of_use_index,
                                    concentration_index=concentration_index,
                                    conditions_index=conditions_index,
                                    warning_index=warning_index,
                                )
                            )
                        current = {
                            "raw_record_id": f"raw-{source_document}-{section.casefold().replace(' ', '-')}-{reference_first_line.casefold()}",
                            "source_document": source_document,
                            "section": section,
                            "reference_number": reference_first_line,
                            "fragments": [],
                            "extraction_flags": [],
                            "footnote_references": set(),
                        }
                        qualifiers = re.findall(r"\((\d+|\+)\)|([+#*])", reference_first_line_raw)
                        if qualifiers:
                            current["extraction_flags"].extend(
                                f"reference_qualification:{next(value for value in match if value)}"
                                for match in qualifiers
                            )
                    elif current is None:
                        page_diagnostics[-1].setdefault("unassigned_fragments", []).append(
                            " | ".join(cells)
                        )
                        continue
                    elif reference_raw:
                        current["extraction_flags"].append(
                            f"nonstandard_reference_fragment:{reference_raw}"
                        )
                    current["fragments"].append(
                        _fragment(
                            page_number,
                            table.bbox,
                            table_row.bbox,
                            cells,
                            is_continuation=not is_new_reference,
                        )
                    )
                    current["footnote_references"].update(
                        _superscript_footnote_references(page, table_row.bbox)
                    )
    if current is not None:
        records.append(
            _finalize_record(
                current,
                column_count,
                reference_index=reference_index,
                substance_index=substance_index,
                cas_index=cas_index,
                field_of_use_index=field_of_use_index,
                concentration_index=concentration_index,
                conditions_index=conditions_index,
                warning_index=warning_index,
            )
        )
    return [record.model_dump() for record in records], page_diagnostics, page_texts


def _extract_parenthesized_footnotes(page_texts: dict[int, str]) -> list[dict[str, Any]]:
    """Extract source footnotes without mistaking ordinary table rows for notes.

    ACD sections use parenthesized markers such as ``(2)`` while the current
    Singapore consolidation uses bare markers such as ``4``.  The latter are
    accepted only when followed by wording used by the source footnotes.  This
    deliberately conservative rule keeps table references such as ``60`` out
    of the footnote collection.
    """
    notes: list[dict[str, Any]] = []
    for page_number, text in page_texts.items():
        source_text = text.split("FOURTH SCHEDULE", 1)[0]
        matches = list(re.finditer(
            r"(?m)^(?:"
            r"\((?P<parenthesized>\d{1,2}(?:\.\d+)?)\)\s+|"
            r"(?P<plain>\d{1,2}(?:\.\d+)?)(?:\.)?\s+"
            r"(?=(?:For\b|In case\b|Not required\b|Benzophenone\b|The\b|Lakes\b|"
            r"Adopted\b|Solely\b|Concerns\b|Methylisothiazolinone\b))"
            r")",
            source_text,
        ))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(source_text)
            notes.append(
                {
                    "footnote_number": match.group("parenthesized") or match.group("plain"),
                    "source_page": page_number,
                    "source_text": source_text[match.start():end].strip(),
                }
            )
    return notes


def _attach_inline_footnote_references(records: list[dict[str, Any]]) -> None:
    """Attach visibly printed footnote markers to their extracted records."""
    for record in records:
        references = set(record.get("footnote_references", []))
        for value in (
            record.get("reference_number_raw"),
            record.get("original_concentration_text"),
            record.get("original_conditions_text"),
            record.get("original_warning_text"),
        ):
            if not value:
                continue
            references.update(re.findall(r"\((\d{1,2}(?:\.\d+)?)\)", value))
        concentration = (record.get("original_concentration_text") or "").strip()
        if match := re.search(r"%\s*(\d{1,2})$", concentration):
            references.add(match.group(1))
        record["footnote_references"] = sorted(references)


def extract_appendix_i() -> dict[str, Any]:
    with pdfplumber.open(APPENDIX_I_PDF) as document:
        page_texts = {
            index: (page.extract_text(x_tolerance=1) or "")
            for index, page in enumerate(document.pages, 1)
        }
    categories: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in page_texts[2].splitlines():
        stripped = line.strip()
        if stripped.startswith("•"):
            current = {
                "category_id": f"appendix-i-category-{len(categories) + 1:02d}",
                "source_page": 2,
                "original_text": stripped.removeprefix("•").strip(),
                "subcategories": [],
            }
            categories.append(current)
        elif stripped.startswith("o ") and current is not None:
            current["subcategories"].append(stripped[2:].strip())
    return {
        "dataset_version": DATASET_VERSION,
        "source_document": "acd_appendix_i",
        "section": "Appendix I",
        "page_texts": page_texts,
        "definition_and_background_text": page_texts[1],
        "list_is_explicitly_non_exhaustive": "not exhaustive" in page_texts[1].casefold(),
        "categories": categories,
        "extraction_notes": [
            "The source title uses Appendix I while page 2 is internally headed ANNEX I.",
            "No leave-on/rinse-off or user-population classification was inferred beyond explicit source wording.",
        ],
    }


def extract_acd_annex_ii() -> dict[str, Any]:
    records, diagnostics, page_texts = _extract_table_records(
        pdf_path=ACD_PDF,
        source_document="acd_annexes_2026_1",
        section="Annex II Part 1",
        page_numbers=range(2, 98),
        column_count=3,
        vertical_lines=ACD_ANNEX_II_VERTICAL_LINES,
        reference_index=2,
        substance_index=0,
        cas_index=1,
    )
    with pdfplumber.open(ACD_PDF) as document:
        supporting = {
            page_number: document.pages[page_number - 1].extract_text(x_tolerance=1) or ""
            for page_number in range(98, 102)
        }
    return {
        "dataset_version": DATASET_VERSION,
        "source_document": "acd_annexes_2026_1",
        "section": "Annex II Part 1",
        "records": records,
        "page_texts": page_texts,
        "supporting_definitions": supporting,
        "page_diagnostics": diagnostics,
    }


def extract_acd_annex_iii() -> dict[str, Any]:
    records, diagnostics, page_texts = _extract_table_records(
        pdf_path=ACD_PDF,
        source_document="acd_annexes_2026_1",
        section="Annex III Part 1",
        page_numbers=range(103, 258),
        column_count=6,
        vertical_lines=ACD_ANNEX_III_VERTICAL_LINES,
    )
    with pdfplumber.open(ACD_PDF) as document:
        footnote_pages = {
            page_number: document.pages[page_number - 1].extract_text(x_tolerance=1) or ""
            for page_number in (257, 258)
        }
    return {
        "dataset_version": DATASET_VERSION,
        "source_document": "acd_annexes_2026_1",
        "section": "Annex III Part 1",
        "records": records,
        "page_texts": page_texts,
        "footnotes": _extract_parenthesized_footnotes(footnote_pages),
        "footnote_page_texts": footnote_pages,
        "page_diagnostics": diagnostics,
    }


def extract_regulation_6() -> dict[str, Any]:
    reader = PdfReader(SINGAPORE_REGULATION_6_PDF)
    page_texts = {index: page.extract_text() or "" for index, page in enumerate(reader.pages, 1)}
    cleaned_pages = {
        page_number: re.sub(
            r"(?m)^Singapore Statutes Online Current version.*$",
            "",
            text,
        ).strip()
        for page_number, text in page_texts.items()
    }
    combined = "\n".join(cleaned_pages.values())
    section_start = combined.index("Contents of cosmetic products")
    section_end = combined.index("Labelling of cosmetic products", section_start)
    regulation_text = combined[section_start:section_end]

    def clause(number: int, following: str, pages: list[int]) -> dict[str, Any]:
        start = rf"6\.\W*\({number}\)" if number == 1 else rf"(?m)^\({number}\)"
        pattern = rf"{start}.*?(?={following})"
        match = re.search(pattern, regulation_text, re.DOTALL)
        if not match:
            raise ValueError(f"Could not locate Regulation 6({number})")
        text = match.group(0).strip()
        return {
            "provision_id": f"sg-regulation-6-{number}",
            "regulation": "6",
            "paragraph": str(number),
            "source_document": "singapore_regulation_6_excerpt",
            "source_pages": pages,
            "source_text": text,
        }

    return {
        "dataset_version": DATASET_VERSION,
        "source_document": "singapore_regulation_6_excerpt",
        "section": "Regulation 6",
        "page_texts": page_texts,
        "provisions": [
            clause(1, r"\n\(2\)", [2]),
            clause(2, r"\n\(3\)", [2, 3]),
            clause(3, r"\n\(4\)", [3]),
            clause(4, r"\n\(5\)", [3]),
            clause(5, r"\n\(6\)", [3, 4]),
            clause(7, r"\Z", [4]),
        ],
        "structural_mappings": [
            {
                "provision_id": "sg-regulation-6-1",
                "singapore_schedule": "Third Schedule Part I",
                "acd_section": "Annex II Part 1",
                "relationship": "corresponding prohibited-substances structure",
            },
            {
                "provision_id": "sg-regulation-6-2",
                "singapore_schedule": "Third Schedule Part II",
                "acd_section": "Annex III Part 1",
                "relationship": "corresponding restricted-substances structure",
            },
            {
                "provision_id": "sg-regulation-6-3",
                "singapore_schedule": "Third Schedule Part III",
                "acd_section": "Annex IV Part 1",
                "relationship": "corresponding permitted-colouring-agents structure",
            },
            {
                "provision_id": "sg-regulation-6-4",
                "singapore_schedule": "Third Schedule Part IV",
                "acd_section": "Annex VI",
                "relationship": "corresponding permitted-preservatives structure",
            },
            {
                "provision_id": "sg-regulation-6-5",
                "singapore_schedule": "Third Schedule Part V",
                "acd_section": "Annex VII",
                "relationship": "corresponding permitted-UV-filters structure",
            },
        ],
    }


def extract_singapore_part_i() -> dict[str, Any]:
    records, diagnostics, page_texts = _extract_table_records(
        pdf_path=SINGAPORE_FULL_PDF,
        source_document="singapore_regulations_2025_12_01",
        section="Third Schedule Part I",
        page_numbers=range(13, 96),
        column_count=2,
        text_x_tolerance=0.5,
    )
    reader = PdfReader(SINGAPORE_FULL_PDF)
    supporting = {
        page_number: reader.pages[page_number - 1].extract_text() or ""
        for page_number in (95, 96, 97)
    }
    return {
        "dataset_version": DATASET_VERSION,
        "source_document": "singapore_regulations_2025_12_01",
        "section": "Third Schedule Part I",
        "records": records,
        "page_texts": page_texts,
        "supporting_definitions_and_footnotes": supporting,
        "page_diagnostics": diagnostics,
    }


def _extract_singapore_footnotes(page_text: str) -> list[dict[str, Any]]:
    start_match = re.search(r"(?m)^1\s+These?substances", page_text)
    if not start_match:
        return []
    end = page_text.find("PART III", start_match.start())
    candidate = page_text[start_match.start() : end if end >= 0 else len(page_text)]
    matches = list(re.finditer(r"(?m)^(\d{1,2})\s+", candidate))
    notes: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(candidate)
        notes.append(
            {
                "footnote_number": match.group(1),
                "source_page": 168,
                "source_text": candidate[match.start():end].strip(),
            }
        )
    return notes


def extract_singapore_part_ii() -> dict[str, Any]:
    records, diagnostics, page_texts = _extract_table_records(
        pdf_path=SINGAPORE_FULL_PDF,
        source_document="singapore_regulations_2025_12_01",
        section="Third Schedule Part II",
        page_numbers=range(97, 169),
        column_count=6,
        text_x_tolerance=0.5,
    )
    reader = PdfReader(SINGAPORE_FULL_PDF)
    page_168 = reader.pages[167].extract_text() or ""
    return {
        "dataset_version": DATASET_VERSION,
        "source_document": "singapore_regulations_2025_12_01",
        "section": "Third Schedule Part II",
        "records": records,
        "page_texts": page_texts,
        "footnotes": _extract_singapore_footnotes(page_168),
        "footnote_page_text": page_168,
        "page_diagnostics": diagnostics,
    }


COLOURANT_APPLICATIONS = {
    2: "allowed in all cosmetic products",
    3: "allowed in all cosmetic products except those intended to be applied in the vicinity of eyes",
    4: "allowed only in cosmetic products intended not to come into contact with mucous membranes",
    5: "allowed only in cosmetic products intended to come into contact only briefly with the skin",
}


def _apply_acd_colourant_columns(records: list[dict[str, Any]]) -> None:
    for record in records:
        selected: list[str] = []
        limitations: list[str] = []
        colours: list[str] = []
        for fragment in record["fragments"]:
            cells = fragment["cells"]
            if len(cells) < 7:
                continue
            if cells[1]:
                colours.append(cells[1])
            for index in range(2, 6):
                if conservative := clean_cell(cells[index]):
                    if "x" in conservative.casefold():
                        selected.append(COLOURANT_APPLICATIONS[index])
            if cells[6]:
                limitations.append(cells[6])
        record["original_field_of_use_text"] = join_cell_fragments(dict.fromkeys(selected)) or None
        record["original_conditions_text"] = join_cell_fragments(dict.fromkeys(limitations)) or None
        record["original_concentration_text"] = record["original_conditions_text"]
        record["original_warning_text"] = None
        record["cas_number_raw"] = None
        if colours:
            record["jurisdiction_notes"] = sorted(set(record.get("jurisdiction_notes", []) + [f"source_colour:{value}" for value in colours]))


def _source_section(
    *,
    section: str,
    records: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    page_texts: dict[int, str],
    preamble_pages: list[int],
    footnote_pages: list[int],
    section_version: str | None = None,
) -> dict[str, Any]:
    _attach_inline_footnote_references(records)
    return {
        "dataset_version": CANDIDATE_DATASET_VERSION,
        "source_document": (
            "acd_annexes_2026_1" if section.startswith("Annex") else "singapore_regulations_2025_12_01"
        ),
        "section": section,
        "section_version": section_version,
        "records": records,
        "page_texts": page_texts,
        "preamble": [
            {"source_page": page, "source_text": page_texts.get(page, "")}
            for page in preamble_pages
        ],
        "footnotes": _extract_parenthesized_footnotes(
            {page: page_texts.get(page, "") for page in footnote_pages}
        ),
        "page_diagnostics": diagnostics,
    }


def extract_acd_annex_iv() -> dict[str, Any]:
    records, diagnostics, page_texts = _extract_table_records(
        pdf_path=ACD_PDF,
        source_document="acd_annexes_2026_1",
        section="Annex IV Part 1",
        page_numbers=range(259, 266),
        column_count=7,
        reference_index=0,
        substance_index=0,
    )
    _apply_acd_colourant_columns(records)
    return _source_section(
        section="Annex IV Part 1",
        records=records,
        diagnostics=diagnostics,
        page_texts=page_texts,
        preamble_pages=[259],
        footnote_pages=[265],
    )


def extract_acd_annex_vi() -> dict[str, Any]:
    records, diagnostics, page_texts = _extract_table_records(
        pdf_path=ACD_PDF,
        source_document="acd_annexes_2026_1",
        section="Annex VI",
        page_numbers=range(267, 280),
        column_count=5,
        reference_index=0,
        substance_index=1,
        concentration_index=2,
        conditions_index=3,
        warning_index=4,
    )
    with pdfplumber.open(ACD_PDF) as document:
        page_texts[266] = document.pages[265].extract_text(x_tolerance=0.5) or ""
    return _source_section(
        section="Annex VI",
        records=records,
        diagnostics=diagnostics,
        page_texts=page_texts,
        preamble_pages=[266],
        footnote_pages=[279],
    )


def extract_acd_annex_vii() -> dict[str, Any]:
    records, diagnostics, page_texts = _extract_table_records(
        pdf_path=ACD_PDF,
        source_document="acd_annexes_2026_1",
        section="Annex VII",
        page_numbers=range(281, 291),
        column_count=5,
        vertical_lines=ACD_ANNEX_VII_VERTICAL_LINES,
        reference_index=0,
        substance_index=1,
        concentration_index=2,
        conditions_index=3,
        warning_index=4,
    )
    with pdfplumber.open(ACD_PDF) as document:
        page_texts[280] = document.pages[279].extract_text(x_tolerance=0.5) or ""
    return _source_section(
        section="Annex VII",
        records=records,
        diagnostics=diagnostics,
        page_texts=page_texts,
        preamble_pages=[280],
        footnote_pages=[290],
        section_version="2025-2, 12 December 2025",
    )


def extract_singapore_part_iii() -> dict[str, Any]:
    records, diagnostics, page_texts = _extract_table_records(
        pdf_path=SINGAPORE_FULL_PDF,
        source_document="singapore_regulations_2025_12_01",
        section="Third Schedule Part III",
        page_numbers=range(169, 182),
        column_count=3,
        text_x_tolerance=0.5,
        reference_index=0,
        substance_index=0,
        field_of_use_index=2,
        concentration_index=2,
        conditions_index=2,
    )
    return _source_section(
        section="Third Schedule Part III",
        records=records,
        diagnostics=diagnostics,
        page_texts=page_texts,
        preamble_pages=[169],
        footnote_pages=[181],
    )


def _extract_singapore_positive_part(section: str, pages: range, preamble_page: int) -> dict[str, Any]:
    records, diagnostics, page_texts = _extract_table_records(
        pdf_path=SINGAPORE_FULL_PDF,
        source_document="singapore_regulations_2025_12_01",
        section=section,
        page_numbers=pages,
        column_count=5,
        text_x_tolerance=0.5,
        reference_index=0,
        substance_index=1,
        concentration_index=2,
        conditions_index=3,
        warning_index=4,
    )
    return _source_section(
        section=section,
        records=records,
        diagnostics=diagnostics,
        page_texts=page_texts,
        preamble_pages=[preamble_page],
        footnote_pages=[pages.stop - 1],
    )


def extract_singapore_part_iv() -> dict[str, Any]:
    return _extract_singapore_positive_part("Third Schedule Part IV", range(182, 188), 182)


def extract_singapore_part_v() -> dict[str, Any]:
    return _extract_singapore_positive_part("Third Schedule Part V", range(188, 196), 188)


def extract_candidate_all() -> dict[str, Path]:
    CANDIDATE_RAW_ROOT.mkdir(parents=True, exist_ok=True)
    outputs = {
        "source_manifest": CANDIDATE_RAW_ROOT / "source_manifest.json",
        "appendix_i": CANDIDATE_RAW_ROOT / "appendix_i_raw.json",
        "annex_ii": CANDIDATE_RAW_ROOT / "annex_ii_raw.json",
        "annex_iii": CANDIDATE_RAW_ROOT / "annex_iii_raw.json",
        "annex_iv": CANDIDATE_RAW_ROOT / "annex_iv_raw.json",
        "annex_vi": CANDIDATE_RAW_ROOT / "annex_vi_raw.json",
        "annex_vii": CANDIDATE_RAW_ROOT / "annex_vii_raw.json",
        "regulation_6": CANDIDATE_RAW_ROOT / "singapore_regulation_6_raw.json",
        "singapore_part_i": CANDIDATE_RAW_ROOT / "singapore_third_schedule_part_i_raw.json",
        "singapore_part_ii": CANDIDATE_RAW_ROOT / "singapore_third_schedule_part_ii_raw.json",
        "singapore_part_iii": CANDIDATE_RAW_ROOT / "singapore_third_schedule_part_iii_raw.json",
        "singapore_part_iv": CANDIDATE_RAW_ROOT / "singapore_third_schedule_part_iv_raw.json",
        "singapore_part_v": CANDIDATE_RAW_ROOT / "singapore_third_schedule_part_v_raw.json",
    }
    manifest = source_manifest()
    manifest["dataset_version"] = CANDIDATE_DATASET_VERSION
    existing = {
        "appendix_i": extract_appendix_i(),
        "annex_ii": extract_acd_annex_ii(),
        "annex_iii": extract_acd_annex_iii(),
        "regulation_6": extract_regulation_6(),
        "singapore_part_i": extract_singapore_part_i(),
        "singapore_part_ii": extract_singapore_part_ii(),
    }
    for document in existing.values():
        document["dataset_version"] = CANDIDATE_DATASET_VERSION
    values = {
        "source_manifest": manifest,
        **existing,
        "annex_iv": extract_acd_annex_iv(),
        "annex_vi": extract_acd_annex_vi(),
        "annex_vii": extract_acd_annex_vii(),
        "singapore_part_iii": extract_singapore_part_iii(),
        "singapore_part_iv": extract_singapore_part_iv(),
        "singapore_part_v": extract_singapore_part_v(),
    }
    for key, output in outputs.items():
        write_json(output, values[key])
    return outputs


def extract_all() -> dict[str, Path]:
    ensure_output_directories()
    outputs = {
        "source_manifest": RAW_ROOT / "source_manifest.json",
        "appendix_i": RAW_ROOT / "appendix_i_raw.json",
        "annex_ii": RAW_ROOT / "annex_ii_raw.json",
        "annex_iii": RAW_ROOT / "annex_iii_raw.json",
        "regulation_6": RAW_ROOT / "singapore_regulation_6_raw.json",
        "singapore_part_i": RAW_ROOT / "singapore_third_schedule_part_i_raw.json",
        "singapore_part_ii": RAW_ROOT / "singapore_third_schedule_part_ii_raw.json",
    }
    values = {
        "source_manifest": source_manifest(),
        "appendix_i": extract_appendix_i(),
        "annex_ii": extract_acd_annex_ii(),
        "annex_iii": extract_acd_annex_iii(),
        "regulation_6": extract_regulation_6(),
        "singapore_part_i": extract_singapore_part_i(),
        "singapore_part_ii": extract_singapore_part_ii(),
    }
    for key, output in outputs.items():
        write_json(output, values[key])
    return outputs


if __name__ == "__main__":
    for name, path in extract_all().items():
        print(f"{name}: {path}")
