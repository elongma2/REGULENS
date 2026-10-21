from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from supabase import Client, create_client


FORMULATION_BUCKET = "formulation-files"
LOGGER = logging.getLogger(__name__)


class SupabaseUnavailableError(RuntimeError):
    pass


class ResourceNotFoundError(KeyError):
    pass


class RevisionConflictError(RuntimeError):
    pass


class CaseDeletionError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    email: str | None


class SupabaseGateway:
    """Trusted server gateway. Every domain method verifies membership explicitly."""

    def __init__(self, url: str, publishable_key: str, service_role_key: str):
        self.url = url.rstrip("/")
        self.auth_client: Client = create_client(self.url, publishable_key)
        self.client: Client = create_client(self.url, service_role_key)

    def verify_user(self, access_token: str) -> AuthenticatedUser:
        response = self.auth_client.auth.get_user(access_token)
        user = response.user
        if user is None:
            raise PermissionError("The access token is invalid or expired")
        return AuthenticatedUser(id=UUID(str(user.id)), email=user.email)

    def _memberships(self, user_id: UUID) -> list[dict[str, Any]]:
        return list(
            self.client.table("organisation_members")
            .select("organisation_id,role,organisations(id,name,created_at)")
            .eq("user_id", str(user_id)).execute().data or []
        )

    def me(self, user: AuthenticatedUser) -> dict[str, Any]:
        profile_rows = self.client.table("profiles").select("id,display_name,created_at").eq("id", str(user.id)).execute().data or []
        memberships = self._memberships(user.id)
        if not profile_rows or not memberships:
            raise ResourceNotFoundError("The user workspace has not been provisioned")
        organisations = [
            {**(item.get("organisations") or {}), "role": item["role"]}
            for item in memberships
        ]
        return {
            "id": str(user.id),
            "email": user.email,
            "display_name": profile_rows[0]["display_name"],
            "default_organisation_id": memberships[0]["organisation_id"],
            "organisations": organisations,
        }

    def require_organisation_member(self, user_id: UUID, organisation_id: str | UUID) -> None:
        rows = self.client.table("organisation_members").select("organisation_id").eq(
            "organisation_id", str(organisation_id)
        ).eq("user_id", str(user_id)).limit(1).execute().data or []
        if not rows:
            raise ResourceNotFoundError("Organisation not found")

    def _case_row(self, user_id: UUID, case_id: str | UUID) -> dict[str, Any]:
        rows = self.client.table("cases").select("*").eq("id", str(case_id)).limit(1).execute().data or []
        if not rows:
            raise ResourceNotFoundError("Case not found")
        self.require_organisation_member(user_id, rows[0]["organisation_id"])
        return rows[0]

    def _version_row(self, user_id: UUID, version_id: str | UUID) -> dict[str, Any]:
        rows = self.client.table("formulation_versions").select("*").eq("id", str(version_id)).limit(1).execute().data or []
        if not rows:
            raise ResourceNotFoundError("Formulation version not found")
        self._case_row(user_id, rows[0]["case_id"])
        return rows[0]

    def list_cases(self, user_id: UUID) -> list[dict[str, Any]]:
        organisation_ids = [item["organisation_id"] for item in self._memberships(user_id)]
        if not organisation_ids:
            return []
        cases = self.client.table("cases").select("*").in_("organisation_id", organisation_ids).order("updated_at", desc=True).execute().data or []
        for case in cases:
            versions = self.list_formulations(user_id, case["id"])
            case["formulations"] = versions
            case["latest_formulation"] = versions[0] if versions else None
            case["latest_finding_count"] = self._latest_finding_count(user_id, versions[0]["id"]) if versions else None
            try:
                overview = self.review_overview(user_id, case["id"])
                case["review_summary"] = {
                    "latest_screening_run_id": overview["latest_screening_run_id"],
                    "latest_screening_formulation_version_id": overview["latest_screening_formulation_version_id"],
                    "latest_screening_at": overview["latest_screening_at"],
                    "attention_results": overview["attention_findings"],
                    "reviewer_items_remaining": (
                        overview["not_reviewed"] + overview["in_review"] + overview["awaiting_information"]
                    ),
                    "open_follow_ups": overview["open_follow_ups"],
                    "unresolved_clarifications": overview["unresolved_clarifications"],
                    "last_review_activity_at": overview["last_review_activity_at"],
                }
            except Exception:
                LOGGER.warning("Review summary is unavailable for case %s", case["id"], exc_info=True)
                case["review_summary"] = None
        return cases

    def create_case(self, user_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        organisation_id = payload.get("organisation_id")
        if organisation_id is None:
            memberships = self._memberships(user_id)
            if not memberships:
                raise ResourceNotFoundError("No workspace is available")
            organisation_id = memberships[0]["organisation_id"]
        self.require_organisation_member(user_id, organisation_id)
        row = {
            "organisation_id": str(organisation_id),
            "name": payload["name"].strip(),
            "client_name": payload.get("client_name") or None,
            "created_by": str(user_id),
        }
        return (self.client.table("cases").insert(row).execute().data or [])[0]

    def get_case(self, user_id: UUID, case_id: str | UUID) -> dict[str, Any]:
        case = self._case_row(user_id, case_id)
        case["formulations"] = self.list_formulations(user_id, case_id)
        return case

    def update_case(self, user_id: UUID, case_id: str | UUID, changes: dict[str, Any]) -> dict[str, Any]:
        self._case_row(user_id, case_id)
        if changes.get("status") == "archived":
            changes["archived_at"] = datetime.now(UTC).isoformat()
        elif changes.get("status") == "active":
            changes["archived_at"] = None
        return (self.client.table("cases").update(changes).eq("id", str(case_id)).execute().data or [])[0]

    def delete_case(self, user_id: UUID, case_id: str | UUID) -> None:
        self._case_row(user_id, case_id)
        versions = self.client.table("formulation_versions").select("source_storage_path").eq("case_id", str(case_id)).execute().data or []
        paths = list(dict.fromkeys(item["source_storage_path"] for item in versions if item.get("source_storage_path")))
        if paths:
            try:
                self.client.storage.from_(FORMULATION_BUCKET).remove(paths)
            except Exception as error:
                LOGGER.warning("Case %s storage cleanup failed; database deletion was not started", case_id, exc_info=True)
                raise CaseDeletionError("Uploaded files could not be removed. The case was kept so you can retry.") from error
        try:
            self.client.table("cases").delete().eq("id", str(case_id)).execute()
            remaining = self.client.table("cases").select("id").eq("id", str(case_id)).limit(1).execute().data or []
        except Exception as error:
            LOGGER.exception("Case %s database deletion failed after storage cleanup", case_id)
            raise CaseDeletionError("Case records could not be removed. Please retry or contact the workspace administrator.") from error
        if remaining:
            raise CaseDeletionError("Case records could not be removed. Please retry or contact the workspace administrator.")

    def upload_file(self, path: str, content: bytes, content_type: str | None) -> None:
        options = {"content-type": content_type or "application/octet-stream", "upsert": "false"}
        self.client.storage.from_(FORMULATION_BUCKET).upload(path, content, options)

    def remove_file(self, path: str) -> None:
        self.client.storage.from_(FORMULATION_BUCKET).remove([path])

    def create_version(
        self,
        user_id: UUID,
        version_id: UUID,
        case_id: UUID,
        filename: str,
        storage_path: str,
        raw_extraction: dict[str, Any],
        agent_state: dict[str, Any],
    ) -> dict[str, Any]:
        self._case_row(user_id, case_id)
        response = self.client.rpc("create_formulation_version", {
            "p_id": str(version_id),
            "p_case_id": str(case_id),
            "p_user_id": str(user_id),
            "p_original_filename": filename,
            "p_source_storage_path": storage_path,
            "p_raw_extraction": raw_extraction,
            "p_agent_state": agent_state,
        }).execute().data
        return response[0] if isinstance(response, list) else response

    def list_formulations(self, user_id: UUID, case_id: str | UUID) -> list[dict[str, Any]]:
        self._case_row(user_id, case_id)
        rows = self.client.table("formulation_versions").select(
            "id,case_id,version_number,original_filename,status,revision,created_at,updated_at"
        ).eq("case_id", str(case_id)).order("version_number", desc=True).execute().data or []
        for row in rows:
            row["screening_count"] = len(self.client.table("screening_runs").select("id").eq("formulation_version_id", row["id"]).execute().data or [])
        return rows

    def get_version(self, user_id: UUID, version_id: str | UUID) -> dict[str, Any]:
        row = self._version_row(user_id, version_id)
        row["agent_session"] = row.pop("agent_state", None)
        row["screening_count"] = len(self.client.table("screening_runs").select("id").eq("formulation_version_id", str(version_id)).execute().data or [])
        return row

    def persist_agent_state(
        self,
        user_id: UUID,
        version_id: str | UUID,
        expected_revision: int,
        status: str,
        agent_state: dict[str, Any],
        canonical_formulation: dict[str, Any] | None,
        product_context: dict[str, Any] | None,
        clarifications: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._version_row(user_id, version_id)
        try:
            response = self.client.rpc("persist_formulation_state", {
                "p_formulation_version_id": str(version_id),
                "p_user_id": str(user_id),
                "p_expected_revision": expected_revision,
                "p_status": status,
                "p_agent_state": agent_state,
                "p_canonical_formulation": canonical_formulation,
                "p_product_context": product_context,
                "p_clarifications": clarifications,
            }).execute().data
        except Exception as error:
            if "revision_conflict" in str(error) or "40001" in str(error):
                raise RevisionConflictError("The formulation changed; reload before continuing") from error
            raise
        return response[0] if isinstance(response, list) else response

    def patch_version(self, user_id: UUID, version_id: UUID, revision: int, product_context: dict[str, Any] | None) -> dict[str, Any]:
        current = self._version_row(user_id, version_id)
        if current["revision"] != revision:
            raise RevisionConflictError("The formulation changed; reload before continuing")
        rows = self.client.table("formulation_versions").update({
            "product_context": product_context,
            "revision": revision + 1,
        }).eq("id", str(version_id)).eq("revision", revision).execute().data or []
        if not rows:
            raise RevisionConflictError("The formulation changed; reload before continuing")
        return self.get_version(user_id, version_id)

    def insert_screening(
        self,
        user_id: UUID,
        version_id: UUID,
        dataset_id: str,
        jurisdiction: str,
        request_snapshot: dict[str, Any],
        result_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        self._version_row(user_id, version_id)
        response = self.client.rpc("create_screening_run_with_review_items", {
            "p_formulation_version_id": str(version_id),
            "p_user_id": str(user_id),
            "p_regulatory_dataset_id": dataset_id,
            "p_jurisdiction": jurisdiction,
            "p_request_snapshot": request_snapshot,
            "p_result_snapshot": result_snapshot,
        }).execute().data
        return response[0] if isinstance(response, list) else response

    def list_screenings(self, user_id: UUID, version_id: str | UUID) -> list[dict[str, Any]]:
        self._version_row(user_id, version_id)
        return list(self.client.table("screening_runs").select("*").eq(
            "formulation_version_id", str(version_id)
        ).order("created_at", desc=True).execute().data or [])

    def get_screening(self, user_id: UUID, screening_id: str | UUID) -> dict[str, Any]:
        rows = self.client.table("screening_runs").select("*").eq("id", str(screening_id)).limit(1).execute().data or []
        if not rows:
            raise ResourceNotFoundError("Screening run not found")
        self._version_row(user_id, rows[0]["formulation_version_id"])
        return rows[0]

    @staticmethod
    def _target_columns(target_type: str, target_id: str | UUID | None) -> dict[str, str | None]:
        columns = {
            "formulation_version_id": None,
            "clarification_id": None,
            "review_item_id": None,
        }
        if target_type == "case":
            return columns
        mapping = {
            "formulation": "formulation_version_id",
            "clarification": "clarification_id",
            "review_item": "review_item_id",
        }
        column = mapping.get(target_type)
        if column is None or target_id is None:
            raise ValueError("Unsupported review target")
        columns[column] = str(target_id)
        return columns

    @staticmethod
    def _target_type(row: dict[str, Any]) -> str:
        if row.get("review_item_id"):
            return "review_item"
        if row.get("clarification_id"):
            return "clarification"
        if row.get("formulation_version_id"):
            return "formulation"
        return "case"

    def _display_names(self, user_ids: set[str]) -> dict[str, str]:
        if not user_ids:
            return {}
        rows = self.client.table("profiles").select("id,display_name").in_("id", list(user_ids)).execute().data or []
        return {str(row["id"]): row["display_name"] for row in rows}

    def _decorate_authors(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        names = self._display_names({str(row["created_by"]) for row in rows if row.get("created_by")})
        for row in rows:
            row["author_name"] = names.get(str(row.get("created_by")), "Workspace member")
            row["target_type"] = self._target_type(row)
        return rows

    def _decorate_follow_ups(self, user_id: UUID, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        decorated = self._decorate_authors(rows)
        for row in decorated:
            if row.get("review_item_id"):
                item = self._review_item_row(user_id, row["review_item_id"])
                run = self.get_screening(user_id, item["screening_run_id"])
                result = next((candidate for candidate in (
                    (run.get("result_snapshot") or {}).get("ingredient_results") or []
                ) if candidate.get("submitted_row_number") == item["submitted_row_number"]), None)
                name = ((result or {}).get("submitted_ingredient") or {}).get("name")
                row["target_label"] = f"Ingredient: {name}" if name else f"Ingredient row {item['submitted_row_number']}"
            elif row.get("clarification_id"):
                clarification = self._clarification_row(user_id, row["clarification_id"])
                row["target_label"] = f"Clarification: {clarification['question']}"
            elif row.get("formulation_version_id"):
                version = self._version_row(user_id, row["formulation_version_id"])
                row["target_label"] = f"Formulation version {version['version_number']}"
            else:
                row["target_label"] = "Case"
        return decorated

    def _review_item_row(self, user_id: UUID, review_item_id: str | UUID) -> dict[str, Any]:
        rows = self.client.table("review_items").select("*").eq("id", str(review_item_id)).limit(1).execute().data or []
        if not rows:
            raise ResourceNotFoundError("Review item not found")
        screening = self.get_screening(user_id, rows[0]["screening_run_id"])
        self._version_row(user_id, screening["formulation_version_id"])
        return rows[0]

    def _clarification_row(self, user_id: UUID, clarification_id: str | UUID) -> dict[str, Any]:
        rows = self.client.table("clarifications").select("*").eq("id", str(clarification_id)).limit(1).execute().data or []
        if not rows:
            raise ResourceNotFoundError("Clarification not found")
        self._version_row(user_id, rows[0]["formulation_version_id"])
        return rows[0]

    def _validate_review_target(
        self, user_id: UUID, case_id: str | UUID, target_type: str, target_id: str | UUID | None,
    ) -> None:
        case = self._case_row(user_id, case_id)
        if target_type == "case":
            return
        if target_type == "formulation":
            target = self._version_row(user_id, target_id or "")
            target_case_id = target["case_id"]
        elif target_type == "clarification":
            clarification = self._clarification_row(user_id, target_id or "")
            target_case_id = self._version_row(user_id, clarification["formulation_version_id"])["case_id"]
        elif target_type == "review_item":
            item = self._review_item_row(user_id, target_id or "")
            screening = self.get_screening(user_id, item["screening_run_id"])
            target_case_id = self._version_row(user_id, screening["formulation_version_id"])["case_id"]
        else:
            raise ValueError("Unsupported review target")
        if str(target_case_id) != str(case["id"]):
            raise ResourceNotFoundError("Review target not found")

    def review_overview(self, user_id: UUID, case_id: str | UUID) -> dict[str, Any]:
        case = self._case_row(user_id, case_id)
        versions = self.list_formulations(user_id, case_id)
        current = versions[0] if versions else None
        latest_rows = []
        if versions:
            latest_rows = self.client.table("screening_runs").select("*").in_(
                "formulation_version_id", [version["id"] for version in versions]
            ).order("created_at", desc=True).limit(1).execute().data or []
        latest_run = latest_rows[0] if latest_rows else None
        items = []
        if latest_run:
            items = self.client.table("review_items").select("*").eq("screening_run_id", latest_run["id"]).execute().data or []
        notes = self.client.table("reviewer_notes").select("*").eq("case_id", str(case_id)).order("created_at", desc=True).execute().data or []
        follow_ups = self.client.table("follow_up_actions").select("*").eq("case_id", str(case_id)).execute().data or []
        unresolved = 0
        if current:
            unresolved = len(self.client.table("clarifications").select("id").eq(
                "formulation_version_id", current["id"]
            ).eq("status", "unresolved").execute().data or [])
        statuses = {status: 0 for status in ("not_reviewed", "in_review", "awaiting_information", "reviewed")}
        for item in items:
            if item.get("review_status") in statuses:
                statuses[item["review_status"]] += 1
        activity_dates = [row.get("created_at") for row in notes]
        activity_dates += [row.get("updated_at") for row in follow_ups]
        activity_dates += [row.get("updated_at") for row in items if row.get("review_status") != "not_reviewed"]
        recent_case_notes = self._decorate_authors([
            row for row in notes if self._target_type(row) == "case"
        ][:5])
        open_follow_up_items = self._decorate_follow_ups(user_id, [
            row for row in follow_ups if row.get("status") == "open"
        ])
        result_snapshot = latest_run.get("result_snapshot") if latest_run else None
        return {
            "case_id": case["id"],
            "current_formulation_version_id": current["id"] if current else None,
            "latest_screening_run_id": latest_run["id"] if latest_run else None,
            "latest_screening_formulation_version_id": latest_run["formulation_version_id"] if latest_run else None,
            "latest_screening_at": latest_run["created_at"] if latest_run else None,
            "ingredients_screened": len((result_snapshot or {}).get("ingredient_results") or []),
            "attention_findings": sum(1 for item in items if item.get("requires_attention")),
            **statuses,
            "open_follow_ups": sum(1 for item in follow_ups if item.get("status") == "open"),
            "unresolved_clarifications": unresolved,
            "note_count": len(notes),
            "last_review_activity_at": max((value for value in activity_dates if value), default=None),
            "recent_case_notes": recent_case_notes,
            "open_follow_up_items": open_follow_up_items,
        }

    def case_activity(self, user_id: UUID, case_id: str | UUID) -> dict[str, Any]:
        case = self._case_row(user_id, case_id)
        versions = self.client.table("formulation_versions").select(
            "id,version_number,agent_state"
        ).eq("case_id", str(case_id)).order("version_number").execute().data or []
        version_by_id = {str(row["id"]): row for row in versions}
        version_ids = list(version_by_id)

        runs = []
        if version_ids:
            runs = self.client.table("screening_runs").select(
                "id,formulation_version_id,regulatory_dataset_id,jurisdiction,result_snapshot,created_at"
            ).in_("formulation_version_id", version_ids).order("created_at").execute().data or []
        run_by_id = {str(row["id"]): row for row in runs}
        run_number_by_id: dict[str, int] = {}
        next_run_number: dict[str, int] = {}
        for run in runs:
            version_id = str(run["formulation_version_id"])
            next_run_number[version_id] = next_run_number.get(version_id, 0) + 1
            run_number_by_id[str(run["id"])] = next_run_number[version_id]

        review_items = []
        if run_by_id:
            review_items = self.client.table("review_items").select("*").in_(
                "screening_run_id", list(run_by_id)
            ).execute().data or []
        review_item_by_id = {str(row["id"]): row for row in review_items}

        clarifications = []
        if version_ids:
            clarifications = self.client.table("clarifications").select(
                "id,formulation_version_id,question_key,row_id,question"
            ).in_("formulation_version_id", version_ids).execute().data or []
        clarification_by_id = {str(row["id"]): row for row in clarifications}

        notes = self.client.table("reviewer_notes").select("*").eq(
            "case_id", str(case_id)
        ).execute().data or []
        follow_ups = self.client.table("follow_up_actions").select("*").eq(
            "case_id", str(case_id)
        ).execute().data or []
        user_ids = {
            str(value)
            for row in [*notes, *follow_ups, *review_items]
            for key in ("created_by", "updated_by", "resolved_by")
            if (value := row.get(key))
        }
        display_names = self._display_names(user_ids)

        def source_row_number(version: dict[str, Any] | None, row_id: str | None) -> int | None:
            if not version or not row_id:
                return None
            interpreted_rows = ((version.get("agent_state") or {}).get("interpreted_rows") or [])
            row = next((item for item in interpreted_rows if str(item.get("row_id")) == str(row_id)), None)
            value = (row or {}).get("source_row")
            return int(value) if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else None

        def result_for(run: dict[str, Any] | None, submitted_row_number: int | None) -> dict[str, Any] | None:
            if not run or submitted_row_number is None:
                return None
            return next((item for item in (
                (run.get("result_snapshot") or {}).get("ingredient_results") or []
            ) if item.get("submitted_row_number") == submitted_row_number), None)

        def context_for(row: dict[str, Any]) -> dict[str, Any]:
            target_type = self._target_type(row)
            version = None
            run = None
            clarification = None
            review_item = None
            result = None
            submitted_row = None

            if row.get("review_item_id"):
                target_type = "finding"
                review_item = review_item_by_id.get(str(row["review_item_id"]))
            elif row.get("clarification_id"):
                clarification = clarification_by_id.get(str(row["clarification_id"]))
            elif row.get("formulation_version_id"):
                version = version_by_id.get(str(row["formulation_version_id"]))

            if row.get("screening_run_id"):
                run = run_by_id.get(str(row["screening_run_id"]))
                review_item = row
                target_type = "finding"
            elif review_item:
                run = run_by_id.get(str(review_item.get("screening_run_id")))

            if run:
                version = version_by_id.get(str(run.get("formulation_version_id")))
            elif clarification:
                version = version_by_id.get(str(clarification.get("formulation_version_id")))

            if review_item:
                submitted_row = review_item.get("submitted_row_number")
                result = result_for(run, submitted_row)

            ingredient_name = (((result or {}).get("submitted_ingredient") or {}).get("name"))
            if target_type == "finding":
                target_label = f"Finding · Row {submitted_row}" + (f" · {ingredient_name}" if ingredient_name else "")
            elif target_type == "clarification":
                source_row = source_row_number(version, (clarification or {}).get("row_id"))
                target_label = "Clarification" + (f" · Row {source_row}" if source_row else "")
            elif target_type == "formulation":
                target_label = f"Version {(version or {}).get('version_number', '—')}"
            else:
                target_label = "Case"

            return {
                "case_id": case["id"],
                "case_name": case["name"],
                "target_type": target_type,
                "target_label": target_label,
                "formulation_version_id": (version or {}).get("id"),
                "formulation_version_number": (version or {}).get("version_number"),
                "screening_run_id": (run or {}).get("id"),
                "screening_run_number": run_number_by_id.get(str((run or {}).get("id"))),
                "screening_at": (run or {}).get("created_at"),
                "regulatory_dataset_id": (run or {}).get("regulatory_dataset_id"),
                "clarification_id": (clarification or {}).get("id"),
                "clarification_question_key": (clarification or {}).get("question_key"),
                "clarification_question": (clarification or {}).get("question"),
                "source_row_number": source_row_number(version, (clarification or {}).get("row_id")),
                "review_item_id": (review_item or {}).get("id"),
                "submitted_row_number": submitted_row,
                "ingredient_name": ingredient_name,
                "engine_finding": (review_item or {}).get("engine_finding"),
            }

        entries: list[dict[str, Any]] = []
        for note in notes:
            entries.append({
                "id": note["id"],
                "kind": "note",
                "occurred_at": note["created_at"],
                "author_name": display_names.get(str(note.get("created_by")), "Workspace member"),
                "context": context_for(note),
                "body": note["body"],
            })
        for follow_up in follow_ups:
            entries.append({
                "id": follow_up["id"],
                "kind": "follow_up",
                "occurred_at": follow_up["updated_at"],
                "author_name": display_names.get(str(follow_up.get("created_by")), "Workspace member"),
                "context": context_for(follow_up),
                "action_text": follow_up["action_text"],
                "details": follow_up.get("details"),
                "status": follow_up["status"],
                "created_at": follow_up["created_at"],
                "updated_at": follow_up["updated_at"],
                "resolved_at": follow_up.get("resolved_at"),
                "resolved_by_name": display_names.get(str(follow_up.get("resolved_by"))) if follow_up.get("resolved_by") else None,
            })
        for review_item in review_items:
            if not review_item.get("review_status") or review_item.get("updated_at") == review_item.get("created_at"):
                continue
            entries.append({
                "id": review_item["id"],
                "kind": "review_update",
                "occurred_at": review_item["updated_at"],
                "author_name": display_names.get(str(review_item.get("updated_by")), "Workspace member"),
                "context": context_for(review_item),
                "review_status": review_item["review_status"],
            })

        entries.sort(key=lambda item: item["occurred_at"], reverse=True)
        return {"case_id": case["id"], "entries": entries}

    def review_workspace(
        self, user_id: UUID, version_id: str | UUID, screening_run_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        version = self._version_row(user_id, version_id)
        case_id = version["case_id"]
        run = None
        if screening_run_id is not None:
            run = self.get_screening(user_id, screening_run_id)
            if str(run["formulation_version_id"]) != str(version_id):
                raise ResourceNotFoundError("Screening run not found")
        else:
            runs = self.list_screenings(user_id, version_id)
            run = runs[0] if runs else None
        review_items = []
        if run:
            review_items = self.client.table("review_items").select("*").eq("screening_run_id", run["id"]).order("submitted_row_number").execute().data or []
        item_ids = {str(item["id"]) for item in review_items}
        clarifications = self.client.table("clarifications").select(
            "id,question_key,row_id,field_name,question,status"
        ).eq("formulation_version_id", str(version_id)).execute().data or []
        clarification_ids = {str(item["id"]) for item in clarifications}
        case_notes = self.client.table("reviewer_notes").select("*").eq("case_id", str(case_id)).order("created_at", desc=True).execute().data or []
        notes = [row for row in case_notes if (
            str(row.get("formulation_version_id") or "") == str(version_id)
            or str(row.get("clarification_id") or "") in clarification_ids
            or str(row.get("review_item_id") or "") in item_ids
        )]
        follow_ups = self.client.table("follow_up_actions").select("*").eq("case_id", str(case_id)).order("updated_at", desc=True).execute().data or []
        relevant_follow_ups = [row for row in follow_ups if (
            str(row.get("formulation_version_id") or "") == str(version_id)
            or str(row.get("clarification_id") or "") in clarification_ids
            or str(row.get("review_item_id") or "") in item_ids
        )]
        return {
            "case_id": case_id,
            "formulation_version_id": version_id,
            "screening_run_id": run["id"] if run else None,
            "clarification_targets": clarifications,
            "review_items": review_items,
            "notes": self._decorate_authors(notes),
            "follow_ups": self._decorate_follow_ups(user_id, relevant_follow_ups),
        }

    def update_review_status(self, user_id: UUID, review_item_id: UUID, status: str) -> dict[str, Any]:
        item = self._review_item_row(user_id, review_item_id)
        if not item.get("requires_attention"):
            raise ValueError("This result does not require a reviewer status")
        now = datetime.now(UTC).isoformat()
        changes = {
            "review_status": status,
            "updated_by": str(user_id),
            "reviewed_at": now if status == "reviewed" else None,
        }
        return (self.client.table("review_items").update(changes).eq("id", str(review_item_id)).execute().data or [])[0]

    def create_reviewer_note(
        self, user_id: UUID, case_id: UUID, target_type: str, target_id: UUID | None, body: str,
    ) -> dict[str, Any]:
        self._validate_review_target(user_id, case_id, target_type, target_id)
        row = {
            "case_id": str(case_id),
            **self._target_columns(target_type, target_id),
            "body": body.strip(),
            "created_by": str(user_id),
        }
        created = (self.client.table("reviewer_notes").insert(row).execute().data or [])[0]
        return self._decorate_authors([created])[0]

    def create_follow_up(
        self, user_id: UUID, case_id: UUID, target_type: str, target_id: UUID | None,
        action_text: str, details: str | None,
    ) -> dict[str, Any]:
        self._validate_review_target(user_id, case_id, target_type, target_id)
        row = {
            "case_id": str(case_id),
            **self._target_columns(target_type, target_id),
            "action_text": action_text.strip(),
            "details": details.strip() if details else None,
            "created_by": str(user_id),
        }
        created = (self.client.table("follow_up_actions").insert(row).execute().data or [])[0]
        return self._decorate_follow_ups(user_id, [created])[0]

    def update_follow_up(self, user_id: UUID, follow_up_id: UUID, changes: dict[str, Any]) -> dict[str, Any]:
        rows = self.client.table("follow_up_actions").select("*").eq("id", str(follow_up_id)).limit(1).execute().data or []
        if not rows:
            raise ResourceNotFoundError("Follow-up not found")
        self._case_row(user_id, rows[0]["case_id"])
        if changes.get("status") == "resolved":
            changes["resolved_by"] = str(user_id)
            changes["resolved_at"] = datetime.now(UTC).isoformat()
        elif changes.get("status") == "open":
            changes["resolved_by"] = None
            changes["resolved_at"] = None
        updated = (self.client.table("follow_up_actions").update(changes).eq("id", str(follow_up_id)).execute().data or [])[0]
        return self._decorate_follow_ups(user_id, [updated])[0]

    def signed_file_url(self, user_id: UUID, version_id: UUID, expires_in: int = 60) -> str:
        row = self._version_row(user_id, version_id)
        path = row.get("source_storage_path")
        if not path:
            raise ResourceNotFoundError("The source file is unavailable")
        response = self.client.storage.from_(FORMULATION_BUCKET).create_signed_url(path, expires_in)
        return response.get("signedURL") or response.get("signed_url")

    def _latest_finding_count(self, user_id: UUID, version_id: str | UUID) -> int | None:
        runs = self.list_screenings(user_id, version_id)
        if not runs:
            return None
        ingredients = (runs[0].get("result_snapshot") or {}).get("ingredient_results") or []
        non_attention = {
            "no_issue_identified_within_scoped_rules",
            "restriction_within_limit",
            "permitted_use_within_conditions",
        }
        return sum(1 for item in ingredients if item.get("primary_finding") not in non_attention)

