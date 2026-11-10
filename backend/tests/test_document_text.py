from __future__ import annotations

from backend.app.services.agent_csv import ParsedCSV
from backend.app.services.document_text import MAX_TEXT_INPUT_CHARS, _bounded_document_text


def test_bounded_document_text_represents_every_page_and_prioritises_composition_rows() -> None:
    rows: list[tuple[str, ...]] = []
    pages: list[int] = []
    snippets: list[str] = []
    for page in range(1, 21):
        for index in range(30):
            value = f"Background text page {page} line {index} " + ("x" * 180)
            rows.append((value,))
            pages.append(page)
            snippets.append(value)
        composition = f"GLYCERIN 56-81-5 {page}%"
        rows.append((composition,))
        pages.append(page)
        snippets.append(composition)
    parsed = ParsedCSV(
        filename="long-supplier.pdf",
        delimiter="pdf_text",
        rows=tuple(rows),
        source_format="pdf",
        row_pages=tuple(pages),
        row_snippets=tuple(snippets),
        page_count=20,
    )

    bounded = _bounded_document_text(parsed)

    assert len(bounded) <= MAX_TEXT_INPUT_CHARS
    for page in range(1, 21):
        assert f"[page {page} begins]" in bounded
        assert f"GLYCERIN 56-81-5 {page}%" in bounded
