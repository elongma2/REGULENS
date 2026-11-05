from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.models.screening import (
    LinkageEvidence,
    SingaporeLinkageStatus,
)
from backend.app.services.ingredient_catalog import IngredientCatalog
from backend.app.services.loader import RegulatoryStore


LINKAGE_DATASET_VERSION = "eu-sg-linkage__eu-glossary-2025-1175__acd-2026-1__sg-2025-12-01__parts-i-v-r1"
SINGAPORE_BASELINE = "acd-2026-1__sg-2025-12-01__parts-i-v-r1"
SCREENED_SCOPE = (
    "Third Schedule Part I",
    "Third Schedule Part II",
    "Third Schedule Part III",
    "Third Schedule Part IV",
    "Third Schedule Part V",
)


class AcceptedIngredientLinkageError(RuntimeError):
    """Raised when the independent accepted linkage baseline cannot be verified."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AcceptedIngredientLinkageError(
            f"Accepted ingredient linkage JSON is unreadable: {path.name}"
        ) from error
    if not isinstance(value, dict):
        raise AcceptedIngredientLinkageError(
            f"Accepted ingredient linkage JSON is malformed: {path.name}"
        )
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class IngredientLinkageStore:
    root: Path
    dataset_version: str
    baseline_manifest_hash: str
    identity_dataset_version: str
    identity_dataset_hash: str
    singapore_regulatory_baseline: str
    singapore_regulatory_baseline_hash: str
    screened_scope: tuple[str, ...]
    counts: dict[str, int]
    records_by_catalogue_id: dict[str, dict[str, Any]]

    def find(self, catalogue_ingredient_id: str) -> dict[str, Any] | None:
        return self.records_by_catalogue_id.get(catalogue_ingredient_id)


@dataclass(frozen=True)
class LinkageAssessment:
    effective_status: SingaporeLinkageStatus
    evidence: LinkageEvidence
    singapore_substance_ids: tuple[str, ...]
    reasons: tuple[str, ...]


def load_accepted_ingredient_linkages(root: Path | None = None) -> IngredientLinkageStore:
    root = (root or Path(__file__).resolve().parents[3]).resolve()
    linkage_root = root / "data_pipeline" / "identity" / "eu_singapore_linkage"
    manifest_path = linkage_root / "accepted" / "accepted_linkage_hashes.json"
    if not manifest_path.exists():
        raise AcceptedIngredientLinkageError("Accepted ingredient linkage manifest is missing")
    manifest_hash = _sha256(manifest_path)
    manifest = _load(manifest_path)
    if not isinstance(manifest.get("dataset_version"), str) or not manifest["dataset_version"].strip():
        raise AcceptedIngredientLinkageError("Accepted linkage dataset version is missing")
    hashes = manifest.get("generated_output_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise AcceptedIngredientLinkageError("Accepted linkage manifest contains no output hashes")
    for relative_path, expected_hash in hashes.items():
        path = root / relative_path
        if not path.exists() or _sha256(path) != expected_hash:
            raise AcceptedIngredientLinkageError(
                f"Accepted ingredient linkage file hash mismatch: {relative_path}"
            )
    linkages_path = linkage_root / "accepted" / "linkages.json"
    document = _load(linkages_path)
    binding_fields = (
        "dataset_version",
        "identity_dataset_version",
        "identity_dataset_hash",
        "singapore_regulatory_baseline",
        "singapore_regulatory_baseline_hash",
        "screened_scope",
    )
    if any(document.get(field) != manifest.get(field) for field in binding_fields):
        raise AcceptedIngredientLinkageError("Accepted linkage document bindings do not match its manifest")
    records = document.get("records")
    if not isinstance(records, list):
        raise AcceptedIngredientLinkageError("Accepted linkage records are malformed")
    ids = [record.get("catalogue_ingredient_id") for record in records]
    linkage_ids = [record.get("linkage_id") for record in records]
    if None in ids or len(ids) != len(set(ids)) or len(linkage_ids) != len(set(linkage_ids)):
        raise AcceptedIngredientLinkageError("Accepted linkage records contain duplicate or missing IDs")
    for record in records:
        if record.get("status") not in {"linked", "verified_not_represented", "unresolved"}:
            raise AcceptedIngredientLinkageError("Accepted linkage record has an unsupported status")
        if any(record.get(field) != document.get(field) for field in binding_fields[1:]):
            raise AcceptedIngredientLinkageError("Accepted linkage record bindings are inconsistent")
        targets = record.get("singapore_targets")
        review = record.get("review")
        if not isinstance(targets, list) or not isinstance(review, dict) or review.get("reviewed") is not True:
            raise AcceptedIngredientLinkageError("Accepted linkage record provenance is malformed")
        if record["status"] == "linked" and not targets:
            raise AcceptedIngredientLinkageError("Accepted linked record has no Singapore target")
        if record["status"] != "linked" and targets:
            raise AcceptedIngredientLinkageError("Accepted non-linked record contains Singapore targets")
    counts = Counter(record.get("status") for record in records)
    expected_counts = {
        "accepted_records": len(records),
        "linked": counts["linked"],
        "verified_not_represented": counts["verified_not_represented"],
        "unresolved": counts["unresolved"],
    }
    if document.get("counts") != expected_counts or manifest.get("counts") != expected_counts:
        raise AcceptedIngredientLinkageError("Accepted linkage counts do not match the records")
    return IngredientLinkageStore(
        root=root,
        dataset_version=document["dataset_version"],
        baseline_manifest_hash=manifest_hash,
        identity_dataset_version=document["identity_dataset_version"],
        identity_dataset_hash=document["identity_dataset_hash"],
        singapore_regulatory_baseline=document["singapore_regulatory_baseline"],
        singapore_regulatory_baseline_hash=document["singapore_regulatory_baseline_hash"],
        screened_scope=tuple(document["screened_scope"]),
        counts=expected_counts,
        records_by_catalogue_id={record["catalogue_ingredient_id"]: record for record in records},
    )


def assess_linkage(
    linkage_store: IngredientLinkageStore,
    record: dict[str, Any],
    catalogue_ingredient: dict[str, Any],
    ingredient_catalog: IngredientCatalog,
    regulatory_store: RegulatoryStore,
) -> LinkageAssessment:
    stale: list[str] = []
    if record.get("catalogue_canonical_name") != catalogue_ingredient.get("canonical_name"):
        stale.append("catalogue identity wording changed")
    if record.get("identity_dataset_version") != ingredient_catalog.dataset_version:
        stale.append("identity dataset version changed")
    if record.get("identity_dataset_hash") != ingredient_catalog.baseline_manifest_hash:
        stale.append("identity dataset hash changed")
    if record.get("singapore_regulatory_baseline") != SINGAPORE_BASELINE:
        stale.append("Singapore baseline identifier changed")
    if record.get("singapore_regulatory_baseline_hash") != regulatory_store.baseline_manifest_hash:
        stale.append("Singapore regulatory baseline hash changed")
    if tuple(record.get("screened_scope", ())) != SCREENED_SCOPE:
        stale.append("screened scope changed")

    targets = record.get("singapore_targets", [])
    substance_ids: list[str] = []
    for target in targets:
        rule = regulatory_store.rules_by_id.get(target.get("rule_id"))
        if rule is None:
            stale.append(f"target rule {target.get('rule_id')} is unavailable")
            continue
        expected = {
            "raw_record_id": rule["raw_record_id"],
            "rule_id": rule["rule_id"],
            "substance_id": rule.get("substance_id"),
            "part": rule["regulatory_section"],
            "reference": rule["reference_number"],
            "source_substance_name": rule["substance_name"],
            "source_document": rule["source_document"],
            "source_pages": rule["source_pages"],
            "source_text": rule["source_text"],
        }
        substance = regulatory_store.substances_by_id.get(rule.get("substance_id"))
        expected["source_hash"] = substance.get("source_hash") if substance else None
        if any(target.get(field) != value for field, value in expected.items()):
            stale.append(f"target rule {rule['rule_id']} no longer matches accepted evidence")
            continue
        if not rule["active"] or rule["regulatory_section"] not in SCREENED_SCOPE:
            stale.append(f"target rule {rule['rule_id']} is no longer active in the accepted scope")
            continue
        substance_ids.append(rule["substance_id"])

    accepted_status = SingaporeLinkageStatus(record["status"])
    applicable = not stale
    evidence = LinkageEvidence(
        linkage_id=record["linkage_id"],
        accepted_status=accepted_status,
        applicable_to_active_baseline=applicable,
        identity_dataset_version=record["identity_dataset_version"],
        identity_dataset_hash=record["identity_dataset_hash"],
        singapore_regulatory_baseline=record["singapore_regulatory_baseline"],
        singapore_regulatory_baseline_hash=record["singapore_regulatory_baseline_hash"],
        screened_scope=record["screened_scope"],
        singapore_targets=targets,
        review=record["review"],
        inapplicability_reasons=stale,
        supported_names=record.get("supported_names", []),
        supported_cas_numbers=record.get("supported_cas_numbers", []),
        supported_ci_numbers=record.get("supported_ci_numbers", []),
        supporting_acd_records=record.get("supporting_acd_records", []),
        identity_group=record.get("identity_group"),
        forms=record.get("forms", []),
        target_relationships=record.get("target_relationships", []),
    )
    if stale:
        return LinkageAssessment(
            effective_status=SingaporeLinkageStatus.UNRESOLVED,
            evidence=evidence,
            singapore_substance_ids=(),
            reasons=("linkage_not_valid_for_active_baseline",),
        )
    if accepted_status == SingaporeLinkageStatus.LINKED:
        return LinkageAssessment(
            effective_status=accepted_status,
            evidence=evidence,
            singapore_substance_ids=tuple(sorted(set(substance_ids))),
            reasons=(),
        )
    if accepted_status == SingaporeLinkageStatus.VERIFIED_NOT_REPRESENTED:
        return LinkageAssessment(
            effective_status=accepted_status,
            evidence=evidence,
            singapore_substance_ids=(),
            reasons=(),
        )
    return LinkageAssessment(
        effective_status=SingaporeLinkageStatus.UNRESOLVED,
        evidence=evidence,
        singapore_substance_ids=(),
        reasons=("catalogue_identity_singapore_linkage_unresolved",),
    )
