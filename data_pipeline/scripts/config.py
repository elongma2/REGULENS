from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPOSITORY_ROOT / "data_pipeline"
SOURCE_ROOT = PIPELINE_ROOT / "Sources"
RAW_ROOT = PIPELINE_ROOT / "raw"
PROCESSED_ROOT = PIPELINE_ROOT / "processed"
REPORT_ROOT = PIPELINE_ROOT / "reports"
ACCEPTED_BASELINE_PATH = PIPELINE_ROOT / "accepted_output_hashes.json"

ACD_PDF = SOURCE_ROOT / "annexes-of-the-asean-cosmetic-directive.pdf"
APPENDIX_I_PDF = (
    SOURCE_ROOT / "appendix-i-illustrative-list-by-category-of-cosmetic-products.pdf"
)
SINGAPORE_REGULATION_6_PDF = (
    SOURCE_ROOT / "Health Products (Cosmetic Products — ASEAN Cosmeti.pdf"
)
SINGAPORE_FULL_PDF = (
    SOURCE_ROOT
    / "singapore-health-products-cosmetic-products-acd-regulations-2007-current-2025-12-01.pdf"
)

RETRIEVAL_DATE = "2026-09-14"
DATASET_VERSION = "acd-2026-1__sg-2025-12-01__parts-i-v-r1"
CANDIDATE_DATASET_VERSION = "acd-2026-1__sg-2025-12-01__parts-i-v-r1"
CANDIDATE_ROOT = PIPELINE_ROOT / "candidate"
CANDIDATE_RAW_ROOT = CANDIDATE_ROOT / "raw"
CANDIDATE_PROCESSED_ROOT = CANDIDATE_ROOT / "processed"
CANDIDATE_REPORT_ROOT = CANDIDATE_ROOT / "reports"
CANDIDATE_BASELINE_PATH = CANDIDATE_ROOT / "candidate_output_hashes.json"

EXPECTED_SOURCE_HASHES = {
    "acd_appendix_i": "30690ead067954dc90dafc59833a2663f82827f3ffc44d887658a2d449dbf231",
    "acd_annexes_2026_1": "ffad59f6c01a92c82042c54203ee14969425c2a82bd04c2f4012ff82513e69f1",
    "singapore_regulation_6_excerpt": "6b573bf215c5fc35c28e28205c432a786681678902f6fd248a97b84810609e27",
    "singapore_regulations_2025_12_01": "8e9a255e7ba67331db20b6c8ae2572a9edc2b0171b410b111804ddbca4b12ff5",
}

SOURCE_DEFINITIONS = {
    "acd_appendix_i": {
        "path": APPENDIX_I_PDF,
        "title": "ACD Appendix I - Illustrative List of Cosmetic Products by Categories",
        "authority": "Health Sciences Authority",
        "source_url": "https://file.go.gov.sg/appendix-i-illustrative-list-by-category-of-cosmetic-products.pdf",
        "document_revision": None,
        "effective_date": None,
        "retrieval_date": RETRIEVAL_DATE,
        "snapshot_generated_at": None,
    },
    "acd_annexes_2026_1": {
        "path": ACD_PDF,
        "title": "Annexes of the ASEAN Cosmetic Directive",
        "authority": "Health Sciences Authority",
        "source_url": "https://file.go.gov.sg/annexes-of-the-asean-cosmetic-directive.pdf",
        "document_revision": "2026-1, 22 June 2026",
        "effective_date": None,
        "retrieval_date": RETRIEVAL_DATE,
        "snapshot_generated_at": None,
    },
    "singapore_regulation_6_excerpt": {
        "path": SINGAPORE_REGULATION_6_PDF,
        "title": "Health Products (Cosmetic Products - ASEAN Cosmetic Directive) Regulations 2007 - Regulation 6 excerpt",
        "authority": "Singapore Statutes Online",
        "source_url": "https://sso.agc.gov.sg/SL/HPA2007-S683-2007?ProvIds=pr6-",
        "document_revision": "version in force from 1 December 2025",
        "effective_date": "2025-12-01",
        "retrieval_date": RETRIEVAL_DATE,
        "snapshot_generated_at": "2026-09-14",
    },
    "singapore_regulations_2025_12_01": {
        "path": SINGAPORE_FULL_PDF,
        "title": "Health Products (Cosmetic Products - ASEAN Cosmetic Directive) Regulations 2007",
        "authority": "Singapore Statutes Online",
        "source_url": "https://sso.agc.gov.sg/SL/HPA2007-S683-2007?DocDate=20251128&ViewType=Pdf&_=20251201212702",
        "document_revision": "informal consolidation - version in force from 1 December 2025",
        "effective_date": "2025-12-01",
        "retrieval_date": "2026-09-15",
        "snapshot_generated_at": "2025-12-01T17:34:45+08:00",
    },
}


def ensure_output_directories() -> None:
    for directory in (RAW_ROOT, PROCESSED_ROOT, REPORT_ROOT):
        directory.mkdir(parents=True, exist_ok=True)


def ensure_candidate_directories() -> None:
    for directory in (
        CANDIDATE_RAW_ROOT,
        CANDIDATE_PROCESSED_ROOT,
        CANDIDATE_REPORT_ROOT,
    ):
        directory.mkdir(parents=True, exist_ok=True)
