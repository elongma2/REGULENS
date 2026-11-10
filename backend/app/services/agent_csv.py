from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime, time
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

import openpyxl
import xlrd
from openpyxl.utils.exceptions import InvalidFileException
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from xlrd.biffh import XLRDError


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PDF_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 500
MAX_COLUMNS = 50
MAX_CELL_CHARACTERS = 8_192
MAX_DECODED_CHARACTERS = 250_000
MAX_PDF_PAGES = 50


class CSVUploadError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ParsedCSV:
    filename: str
    delimiter: str
    rows: tuple[tuple[str, ...], ...]
    source_format: str = "structured_grid"
    row_pages: tuple[int | None, ...] = ()
    row_snippets: tuple[str | None, ...] = ()
    page_count: int | None = None

    def page_for_row(self, source_row: int) -> int | None:
        index = source_row - 1
        return self.row_pages[index] if 0 <= index < len(self.row_pages) else None

    def snippet_for_row(self, source_row: int) -> str | None:
        index = source_row - 1
        return self.row_snippets[index] if 0 <= index < len(self.row_snippets) else None


def _decode_csv(content: bytes) -> str:
    encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        text = content.decode(encoding)
    except UnicodeDecodeError as error:
        raise CSVUploadError(
            "agent_csv_encoding_unsupported",
            "CSV must be UTF-8, UTF-8 with BOM, or BOM-identified UTF-16 text",
        ) from error
    if len(text) > MAX_DECODED_CHARACTERS:
        raise CSVUploadError("agent_csv_too_large", "Decoded CSV exceeds 250,000 characters", 413)
    return text


def parse_formulation_upload(filename: str, content: bytes) -> ParsedCSV:
    safe_name = Path(filename or "formulation.csv").name
    suffix = Path(safe_name).suffix.casefold()
    if suffix not in {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".json", ".pdf"}:
        raise CSVUploadError("agent_csv_type_unsupported", "Supported formulation files: .csv, .tsv, .txt, .xlsx, .xls, .json, and .pdf")
    if not content:
        raise CSVUploadError("agent_csv_empty", "The uploaded file is empty")
    file_limit = MAX_PDF_FILE_BYTES if suffix == ".pdf" else MAX_FILE_BYTES
    if len(content) > file_limit:
        limit_mib = file_limit // (1024 * 1024)
        raise CSVUploadError(
            "agent_csv_too_large",
            f"{suffix.removeprefix('.').upper()} formulation files are limited to {limit_mib} MiB",
            413,
        )
    if suffix == ".xlsx":
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            if not workbook.worksheets:
                raise CSVUploadError("agent_csv_empty", "The uploaded workbook contains no worksheets")
            if len(workbook.worksheets) == 1:
                rows = [tuple(_cell_text(value) for value in row) for row in workbook.worksheets[0].iter_rows(values_only=True)]
            else:
                rows = []
                for worksheet in workbook.worksheets:
                    sheet_rows = [tuple(_cell_text(value) for value in row) for row in worksheet.iter_rows(values_only=True)]
                    if any(any(cell.strip() for cell in row) for row in sheet_rows):
                        rows.append((f"Worksheet: {worksheet.title}",))
                        rows.extend(sheet_rows)
        except CSVUploadError:
            raise
        except (BadZipFile, InvalidFileException, KeyError, OSError, ValueError) as error:
            raise CSVUploadError("agent_csv_malformed", "The XLSX workbook could not be read") from error
        return _validate_rows(safe_name, rows, "\t")
    if suffix == ".xls":
        try:
            workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
            if workbook.nsheets == 0:
                raise CSVUploadError("agent_csv_empty", "The uploaded workbook contains no worksheets")
            if workbook.nsheets == 1:
                sheet = workbook.sheet_by_index(0)
                rows = [tuple(_cell_text(value) for value in sheet.row_values(index)) for index in range(sheet.nrows)]
            else:
                rows = []
                for sheet_index in range(workbook.nsheets):
                    sheet = workbook.sheet_by_index(sheet_index)
                    sheet_rows = [tuple(_cell_text(value) for value in sheet.row_values(index)) for index in range(sheet.nrows)]
                    if any(any(cell.strip() for cell in row) for row in sheet_rows):
                        rows.append((f"Worksheet: {sheet.name}",))
                        rows.extend(sheet_rows)
        except CSVUploadError:
            raise
        except (XLRDError, IndexError, OSError, ValueError) as error:
            raise CSVUploadError("agent_csv_malformed", "The XLS workbook could not be read") from error
        return _validate_rows(safe_name, rows, "\t")
    if suffix == ".json":
        try:
            payload = json.loads(content.decode("utf-8-sig"))
            records = payload if isinstance(payload, list) else payload.get("rows") if isinstance(payload, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CSVUploadError("agent_csv_malformed", "JSON could not be parsed") from error
        if not isinstance(records, list):
            raise CSVUploadError("agent_csv_malformed", "JSON must contain an array of rows or an object with a rows array")
        if not all(isinstance(row, list) for row in records):
            raise CSVUploadError("agent_csv_malformed", "Every JSON row must be an array of cell values")
        rows = [tuple(_cell_text(value) for value in row) for row in records]
        return _validate_rows(safe_name, rows, "\t")
    if suffix == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > MAX_PDF_PAGES:
                raise CSVUploadError(
                    "agent_pdf_too_many_pages",
                    f"PDF files are limited to {MAX_PDF_PAGES} pages",
                    413,
                )
            pdf_rows: list[tuple[str, ...]] = []
            row_pages: list[int | None] = []
            row_snippets: list[str] = []
            extracted_characters = 0
            for page_number, page in enumerate(reader.pages, start=1):
                if "/Contents" not in page:
                    continue
                page_text = page.extract_text(extraction_mode="layout") or ""
                extracted_characters += len(page_text)
                if extracted_characters > MAX_DECODED_CHARACTERS:
                    raise CSVUploadError(
                        "agent_csv_too_large",
                        "Extracted PDF text exceeds 250,000 characters",
                        413,
                    )
                for raw_line in page_text.splitlines():
                    line = " ".join(raw_line.split()).strip()
                    if not line:
                        continue
                    pdf_rows.append((line,))
                    row_pages.append(page_number)
                    row_snippets.append(line[:1_000])
        except (PdfReadError, OSError, ValueError) as error:
            if isinstance(error, CSVUploadError):
                raise
            raise CSVUploadError("agent_csv_malformed", "The PDF could not be read") from error
        if not pdf_rows or not any(re.search(r"[A-Za-z0-9]", row[0]) for row in pdf_rows):
            raise CSVUploadError(
                "agent_pdf_text_unavailable",
                "Unable to extract text from this PDF. Please upload a text-based PDF or a supported spreadsheet.",
            )
        validated = _validate_rows(safe_name, pdf_rows, "pdf_text")
        return ParsedCSV(
            filename=validated.filename,
            delimiter=validated.delimiter,
            rows=validated.rows,
            source_format="pdf",
            row_pages=tuple(row_pages),
            row_snippets=tuple(row_snippets),
            page_count=len(reader.pages),
        )
    else:
        text = _decode_csv(content)
    if not text.strip():
        raise CSVUploadError("agent_csv_empty", "The uploaded CSV contains no data")
    try:
        dialect = csv.Sniffer().sniff(text[:16_384], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    try:
        rows = [tuple(row) for row in csv.reader(io.StringIO(text), dialect, strict=True)]
    except csv.Error as error:
        raise CSVUploadError("agent_csv_malformed", f"CSV could not be parsed: {error}") from error
    if not any(any(cell.strip() for cell in row) for row in rows):
        raise CSVUploadError("agent_csv_empty", "The uploaded CSV contains no non-empty rows")
    if len(rows) > MAX_ROWS:
        raise CSVUploadError("agent_csv_too_many_rows", f"Files are limited to {MAX_ROWS} rows")
    if max(len(row) for row in rows) > MAX_COLUMNS:
        raise CSVUploadError("agent_csv_too_many_columns", f"CSV files are limited to {MAX_COLUMNS} columns")
    if any(len(cell) > MAX_CELL_CHARACTERS for row in rows for cell in row):
        raise CSVUploadError("agent_csv_cell_too_large", f"CSV cells are limited to {MAX_CELL_CHARACTERS} characters")
    return ParsedCSV(filename=safe_name, delimiter=dialect.delimiter, rows=tuple(rows))


def _validate_rows(filename: str, rows: list[tuple[str, ...]], delimiter: str) -> ParsedCSV:
    if not rows or not any(any(cell.strip() for cell in row) for row in rows):
        raise CSVUploadError("agent_csv_empty", "The uploaded file contains no data")
    if len(rows) > MAX_ROWS or max(len(row) for row in rows) > MAX_COLUMNS:
        raise CSVUploadError("agent_csv_shape_invalid", "The uploaded file exceeds the row or column limits")
    if any(len(cell) > MAX_CELL_CHARACTERS for row in rows for cell in row):
        raise CSVUploadError("agent_csv_cell_too_large", f"Cells are limited to {MAX_CELL_CHARACTERS} characters")
    return ParsedCSV(filename=filename, delimiter=delimiter, rows=tuple(rows))


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value)


parse_csv_upload = parse_formulation_upload
