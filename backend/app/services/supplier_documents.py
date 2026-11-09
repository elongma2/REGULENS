from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pypdf import PdfReader

from backend.app.models.document_intake import DocumentExtraction, DocumentRole
from backend.app.services.agent_csv import (
    CSVUploadError,
    MAX_FILE_BYTES,
    ParsedCSV,
    parse_formulation_upload,
)
from backend.app.services.document_extraction import EXTRACTION_SCHEMA_VERSION, extract_document
from backend.app.services.document_vision import DocumentVisionExtractor
from backend.app.services.document_text import DocumentTextExtractor
from backend.app.services.supabase_gateway import SupabaseGateway


DETERMINISTIC_PROCESSOR_CONFIGURATION = "deterministic-trade-document-v1"
REUSABLE_ROLES = {DocumentRole.SDS_MSDS, DocumentRole.SUPPLIER_COMPOSITION}


def _automatic_supplier_role(extraction: DocumentExtraction) -> DocumentRole | None:
    """Return a supplier role only when the document evidence is unambiguous.

    This is an intake decision, not a regulatory one.  A partial disclosure or
    an unresolved constituent may still require review later, but neither makes
    the user reconfirm that an otherwise clear SDS/composition is a supplier
    document.
    """
    classification = extraction.classification
    if classification.multiple_products_detected or not extraction.supplier_materials:
        return None
    recommended = {
        "supplier_composition": DocumentRole.SUPPLIER_COMPOSITION,
        "sds_composition": DocumentRole.SDS_MSDS,
    }.get(classification.recommended_extraction_schema)
    reliable_roles = [
        item.role for item in classification.proposed_roles
        if item.role in REUSABLE_ROLES and item.confidence in {"confirmed", "high"}
    ]
    if recommended is not None and recommended in reliable_roles:
        return recommended
    # Some layouts resemble a finished formulation at document level while
    # still yielding one unambiguous supplier-material hierarchy. Prefer that
    # structured evidence only when exactly one reusable role is reliable.
    unique_roles = list(dict.fromkeys(reliable_roles))
    return unique_roles[0] if len(unique_roles) == 1 else None


def _processing_decision(extraction: DocumentExtraction) -> tuple[list[str], str, str]:
    automatic_role = _automatic_supplier_role(extraction)
    has_rows = bool(extraction.supplier_materials or extraction.direct_ingredients)
    needs_confirmation = (
        extraction.classification.multiple_products_detected
        or not has_rows
        or automatic_role is None
    )
    return (
        [automatic_role.value] if automatic_role else [],
        "needs_confirmation" if needs_confirmation else "ready",
        "needs_confirmation" if needs_confirmation else "available",
    )


class SupplierDocumentProcessingError(RuntimeError):
    def __init__(self, code: str, message: str, *, recoverable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable


def _raw(parsed: ParsedCSV) -> dict[str, Any]:
    return {
        "filename": parsed.filename,
        "delimiter": parsed.delimiter,
        "rows": [list(row) for row in parsed.rows],
        "source_format": parsed.source_format,
        "row_pages": list(parsed.row_pages),
        "row_snippets": list(parsed.row_snippets),
        "page_count": parsed.page_count,
    }


def _pdf_page_count(content: bytes) -> int | None:
    try:
        return len(PdfReader(BytesIO(content)).pages)
    except Exception:
        return None


class SupplierDocumentService:
    """Process and reuse organisation-private supplier documents.

    Regulatory interpretation is intentionally absent here. This service only
    stores the private source, extracts source-backed document facts and creates
    a formulation-local snapshot. Deterministic formulation assembly and the
    existing screening engine consume those facts later.
    """

    def __init__(self, gateway: SupabaseGateway) -> None:
        self.gateway = gateway

    @staticmethod
    def extraction_is_compatible(
        document: dict[str, Any],
        *,
        vision_extractor: DocumentVisionExtractor | None,
        text_extractor: DocumentTextExtractor | None = None,
    ) -> bool:
        if document.get("extraction_schema_version") != EXTRACTION_SCHEMA_VERSION:
            return False
        if not document.get("extraction_result"):
            return False
        diagnostics = document.get("processing_diagnostics") or {}
        if int(diagnostics.get("model_calls") or 0) == 0:
            return document.get("model_configuration") == DETERMINISTIC_PROCESSOR_CONFIGURATION
        configured_model = diagnostics.get("configured_model")
        active_model = (
            getattr(text_extractor, "model", None)
            or getattr(vision_extractor, "model", None)
        )
        return active_model is None or configured_model == active_model

    def upload_and_attach(
        self,
        *,
        user_id: UUID,
        version_id: UUID,
        filename: str,
        content: bytes,
        content_type: str | None,
        preparsed: ParsedCSV | None = None,
        preparsed_error: CSVUploadError | None = None,
        process_immediately: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        version = self.gateway.get_version(user_id, version_id)
        case = self.gateway.get_case(user_id, version["case_id"])
        document, reused = self.upload_to_library(
            user_id=user_id,
            organisation_id=UUID(str(case["organisation_id"])),
            filename=filename,
            content=content,
            content_type=content_type,
            preparsed=preparsed,
            preparsed_error=preparsed_error,
            process_immediately=process_immediately,
        )
        return self.gateway.attach_supplier_document(
            user_id,
            version_id,
            UUID(str(document["id"])),
        ), reused

    def upload_to_library(
        self,
        *,
        user_id: UUID,
        organisation_id: UUID,
        filename: str,
        content: bytes,
        content_type: str | None,
        preparsed: ParsedCSV | None = None,
        preparsed_error: CSVUploadError | None = None,
        process_immediately: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        safe_name = Path(filename or "supplier-document.pdf").name
        if not content:
            raise CSVUploadError("agent_csv_empty", "The uploaded file is empty")
        if len(content) > MAX_FILE_BYTES:
            raise CSVUploadError(
                "agent_csv_too_large",
                "Formulation and supplier files are limited to 2 MiB",
                413,
            )
        if Path(safe_name).suffix.casefold() not in {
            ".csv", ".tsv", ".txt", ".xlsx", ".xls", ".json", ".pdf",
        }:
            raise CSVUploadError(
                "agent_csv_type_unsupported",
                "Supported formulation and supplier files: .csv, .tsv, .txt, .xlsx, .xls, .json, and .pdf",
            )
        digest = hashlib.sha256(content).hexdigest()

        existing = self.gateway.find_supplier_document_by_hash(
            user_id,
            organisation_id,
            digest,
        )
        if existing is not None:
            return existing, True

        if not process_immediately:
            document_id = uuid4()
            storage_path = (
                f"{organisation_id}/supplier-documents/{document_id}/{safe_name}"
            )
            self.gateway.upload_file(storage_path, content, content_type)
            try:
                document, reused_after_race = self.gateway.create_supplier_document(
                    user_id,
                    document_id=document_id,
                    organisation_id=organisation_id,
                    filename=safe_name,
                    storage_path=storage_path,
                    mime_type=content_type or "application/octet-stream",
                    sha256=digest,
                    page_count=_pdf_page_count(content) if safe_name.casefold().endswith(".pdf") else None,
                    processing_status="uploaded",
                    library_status="processing",
                )
            except Exception:
                self.gateway.remove_file(storage_path)
                raise
            if reused_after_race:
                self.gateway.remove_file(storage_path)
            return document, reused_after_race

        parse_error = preparsed_error
        parsed = preparsed
        if parsed is None and parse_error is None:
            try:
                parsed = parse_formulation_upload(safe_name, content)
            except CSVUploadError as error:
                parse_error = error
        if parse_error is not None and parse_error.code != "agent_pdf_text_unavailable":
            # An image-only PDF is still a valuable private supplier source. It
            # is retained for bounded OCR/vision retry rather than forcing the
            # user to upload the confidential file again. Other invalid input
            # errors are returned immediately and are not persisted.
            raise parse_error

        document_id = uuid4()
        storage_path = (
            f"{organisation_id}/supplier-documents/{document_id}/{safe_name}"
        )
        self.gateway.upload_file(storage_path, content, content_type)
        try:
            document, reused_after_race = self.gateway.create_supplier_document(
                user_id,
                document_id=document_id,
                organisation_id=organisation_id,
                filename=safe_name,
                storage_path=storage_path,
                mime_type=content_type or "application/octet-stream",
                sha256=digest,
                page_count=parsed.page_count if parsed else _pdf_page_count(content),
                processing_status="parsing",
                library_status="processing",
            )
        except Exception:
            self.gateway.remove_file(storage_path)
            raise

        if reused_after_race:
            self.gateway.remove_file(storage_path)
            return document, True

        if parse_error is not None:
            document = self.gateway.persist_supplier_document_processing(
                user_id,
                document_id,
                expected_revision=int(document["revision"]),
                changes={
                    "processing_status": "interrupted",
                    "library_status": "needs_confirmation",
                    "processing_attempt": 1,
                    "error": {
                        "code": parse_error.code,
                        "message": str(parse_error),
                        "recoverable": True,
                        "next_action": "ocr_or_vision_retry",
                    },
                    "processing_diagnostics": {
                        "parser": "pypdf",
                        "text_extracted": False,
                    },
                    "processing_key": (
                        f"{organisation_id}:{digest}:{EXTRACTION_SCHEMA_VERSION}:pending-ocr"
                    ),
                },
            )
        else:
            assert parsed is not None
            extraction = extract_document(parsed, document_id=str(document_id))
            classification = extraction.classification
            confirmed_roles, processing_status, library_status = _processing_decision(extraction)
            document = self.gateway.persist_supplier_document_processing(
                user_id,
                document_id,
                expected_revision=int(document["revision"]),
                changes={
                    "supplier_name": classification.supplier_name,
                    "trade_name": classification.trade_name,
                    "product_code": classification.product_code,
                    "document_revision_label": classification.document_revision_label,
                    "detected_roles": [
                        item.model_dump(mode="json") for item in classification.proposed_roles
                    ],
                    "confirmed_roles": confirmed_roles,
                    "parsed_content": _raw(parsed),
                    "extraction_result": extraction.model_dump(mode="json"),
                    "extraction_schema_version": EXTRACTION_SCHEMA_VERSION,
                    "model_configuration": DETERMINISTIC_PROCESSOR_CONFIGURATION,
                    "processing_status": processing_status,
                    "library_status": library_status,
                    "processing_attempt": 1,
                    "processing_diagnostics": {
                        "processor": DETERMINISTIC_PROCESSOR_CONFIGURATION,
                        "source_rows": len(parsed.rows),
                        "model_calls": 0,
                    },
                    "error": None,
                    "processing_key": (
                        f"{organisation_id}:{digest}:{EXTRACTION_SCHEMA_VERSION}:"
                        f"{DETERMINISTIC_PROCESSOR_CONFIGURATION}"
                    ),
                },
            )

        return document, False

    def confirm_library_metadata(
        self,
        *,
        user_id: UUID,
        document_id: UUID,
        expected_revision: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.gateway.get_supplier_document_detail(user_id, document_id)
        confirmed_roles = changes.get("confirmed_roles", current.get("confirmed_roles") or [])
        normalized_roles = {DocumentRole(value) for value in confirmed_roles}
        requested_status = changes.get("library_status")
        if requested_status == "available":
            if not normalized_roles & REUSABLE_ROLES:
                raise ValueError(
                    "Only a confirmed SDS/MSDS or supplier-composition document can be saved for reuse"
                )
            if not current.get("extraction_result"):
                raise ValueError("The document has no confirmed extraction to reuse")
        return self.gateway.update_supplier_document(
            user_id,
            document_id,
            expected_revision=expected_revision,
            changes=changes,
        )

    def retry_processing(
        self,
        *,
        user_id: UUID,
        document_id: UUID,
        vision_extractor: DocumentVisionExtractor | None,
        text_extractor: DocumentTextExtractor | None = None,
    ) -> dict[str, Any]:
        """Retry a retained document without requiring the private file again."""
        current, content = self.gateway.download_supplier_document_source(user_id, document_id)
        lease_value = current.get("lease_expires_at")
        if current.get("processing_status") in {"parsing", "classifying", "extracting"} and lease_value:
            lease_expires_at = datetime.fromisoformat(str(lease_value).replace("Z", "+00:00"))
            if lease_expires_at > datetime.now(UTC):
                raise SupplierDocumentProcessingError(
                    "document_processing_in_progress",
                    "This saved document is already being processed.",
                )
        run_id = uuid4()
        started_at = datetime.now(UTC)
        attempt = int(current.get("processing_attempt") or 0) + 1
        current = self.gateway.persist_supplier_document_processing(
            user_id,
            document_id,
            expected_revision=int(current["revision"]),
            changes={
                "processing_status": "parsing",
                "library_status": "processing",
                "processing_attempt": attempt,
                "processor_run_id": str(run_id),
                "processing_started_at": started_at.isoformat(),
                "heartbeat_at": started_at.isoformat(),
                "lease_expires_at": (started_at + timedelta(minutes=5)).isoformat(),
                "error": None,
            },
        )
        filename = str(current["original_filename"])
        diagnostics: dict[str, Any]
        model_configuration = DETERMINISTIC_PROCESSOR_CONFIGURATION
        source_parsed: ParsedCSV | None = None
        try:
            parsed = parse_formulation_upload(filename, content)
            source_parsed = parsed
            diagnostics = {
                "processor": DETERMINISTIC_PROCESSOR_CONFIGURATION,
                "source_rows": len(parsed.rows),
                "model_calls": 0,
            }
        except CSVUploadError as error:
            if error.code != "agent_pdf_text_unavailable":
                failure = SupplierDocumentProcessingError(
                    error.code,
                    str(error),
                    recoverable=False,
                )
                self._persist_retry_failure(user_id, document_id, current, failure)
                raise failure from error
            if vision_extractor is None:
                failure = SupplierDocumentProcessingError(
                    "document_vision_not_configured",
                    "This PDF has no usable text. Configure the bounded document-vision extractor and retry; the private file has been preserved.",
                )
                self._persist_retry_failure(user_id, document_id, current, failure)
                raise failure from error
            try:
                vision = vision_extractor.extract_pdf(filename, content)
            except Exception as vision_error:
                failure = SupplierDocumentProcessingError(
                    "document_vision_failed",
                    "The image-only document could not be interpreted. The private file has been preserved for another retry.",
                )
                self._persist_retry_failure(user_id, document_id, current, failure)
                raise failure from vision_error
            parsed = vision.parsed
            diagnostics = dict(vision.diagnostics)
            model_configuration = str(
                diagnostics.get("processor") or "bounded-document-vision-v1"
            )

        try:
            extraction = extract_document(parsed, document_id=str(document_id))
        except Exception as extraction_error:
            failure = SupplierDocumentProcessingError(
                "supplier_document_extraction_failed",
                "The retained document could not be converted into a reliable supplier composition. The private file has been preserved for another retry.",
            )
            self._persist_retry_failure(user_id, document_id, current, failure)
            raise failure from extraction_error
        has_rows = bool(extraction.supplier_materials or extraction.direct_ingredients)
        if not has_rows and source_parsed is not None and text_extractor is None:
            failure = SupplierDocumentProcessingError(
                "document_text_interpretation_not_configured",
                "The document has selectable text, but its composition layout is not supported by deterministic extraction and the bounded document-text interpreter is not configured. The private file has been preserved for retry.",
            )
            self._persist_retry_failure(user_id, document_id, current, failure)
            raise failure
        if not has_rows and source_parsed is not None and text_extractor is not None:
            try:
                interpreted = text_extractor.extract_text(filename, source_parsed)
                extraction = extract_document(
                    interpreted.parsed,
                    document_id=str(document_id),
                )
                diagnostics = dict(interpreted.diagnostics)
                model_configuration = str(
                    diagnostics.get("processor") or "bounded-document-text-v1"
                )
            except Exception as text_error:
                failure = SupplierDocumentProcessingError(
                    "document_text_interpretation_failed",
                    "The selectable text could not be interpreted into reliable composition rows. The private file has been preserved for another retry.",
                )
                self._persist_retry_failure(user_id, document_id, current, failure)
                raise failure from text_error
        classification = extraction.classification
        auto_roles, processing_status, automatic_library_status = _processing_decision(extraction)
        current_roles = list(current.get("confirmed_roles") or [])
        current_reusable_roles = {
            DocumentRole(value) for value in current_roles
        } & REUSABLE_ROLES
        # A prior generic/incorrect role must not prevent a later reliable
        # supplier-composition extraction from becoming calculation-ready.
        # Explicitly confirmed reusable roles are preserved.
        confirmed_roles = current_roles if current_reusable_roles else auto_roles
        reusable_confirmed = bool(
            {DocumentRole(value) for value in confirmed_roles} & REUSABLE_ROLES
        )
        library_status = (
            "available" if reusable_confirmed and automatic_library_status == "available"
            else "needs_confirmation"
        )
        return self.gateway.persist_supplier_document_processing(
            user_id,
            document_id,
            expected_revision=int(current["revision"]),
            changes={
                "supplier_name": classification.supplier_name or current.get("supplier_name"),
                "trade_name": classification.trade_name or current.get("trade_name"),
                "product_code": classification.product_code or current.get("product_code"),
                "document_revision_label": (
                    classification.document_revision_label
                    or current.get("document_revision_label")
                ),
                "detected_roles": [
                    item.model_dump(mode="json") for item in classification.proposed_roles
                ],
                "confirmed_roles": confirmed_roles,
                # Keep the original local parser output as the faithful raw
                # extraction even when a bounded model was needed to interpret it.
                "parsed_content": _raw(source_parsed or parsed),
                "extraction_result": extraction.model_dump(mode="json"),
                "extraction_schema_version": EXTRACTION_SCHEMA_VERSION,
                "model_configuration": model_configuration,
                "processing_status": processing_status,
                "library_status": library_status,
                "processing_attempt": attempt,
                "processing_diagnostics": diagnostics,
                "error": None,
                "processor_run_id": str(run_id),
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "lease_expires_at": None,
                "processing_key": (
                    f"{current['organisation_id']}:{current['sha256']}:"
                    f"{EXTRACTION_SCHEMA_VERSION}:"
                    f"{model_configuration}"
                ),
            },
        )

    def _persist_retry_failure(
        self,
        user_id: UUID,
        document_id: UUID,
        current: dict[str, Any],
        error: SupplierDocumentProcessingError,
    ) -> None:
        self.gateway.persist_supplier_document_processing(
            user_id,
            document_id,
            expected_revision=int(current["revision"]),
            changes={
                "processing_status": "interrupted" if error.recoverable else "failed",
                "library_status": "needs_confirmation" if error.recoverable else "failed",
                "error": {
                    "code": error.code,
                    "message": str(error),
                    "recoverable": error.recoverable,
                },
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "lease_expires_at": None,
            },
        )
