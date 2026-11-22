"""Patient/case persistence over Supabase Postgres.

The backend uses the service-role client, which bypasses RLS, so EVERY query
here filters on `practitioner_id` (the verified caller). A row owned by another
practitioner is indistinguishable from a missing row (returns None / 0 rows).
"""

from datetime import datetime, timezone
from typing import Any, Protocol

CONSENT_TEXT_VERSION = "2026-11-v1"


class CaseStoreError(RuntimeError):
    """A patient/case database operation failed."""


class CaseStore(Protocol):
    """Owner-scoped persistence contract (Supabase in prod, in-memory in tests)."""

    def create_patient(self, owner: str, data: dict[str, Any]) -> dict[str, Any]: ...
    def list_patients(self, owner: str) -> list[dict[str, Any]]: ...
    def get_patient(self, owner: str, patient_id: str) -> dict[str, Any] | None: ...
    def update_patient(
        self, owner: str, patient_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...
    def has_active_consent(self, owner: str, patient_id: str) -> bool: ...
    def active_consent_patient_ids(self, owner: str) -> set[str]: ...
    def list_consents(self, owner: str, patient_id: str) -> list[dict[str, Any]]: ...
    def add_consent(self, owner: str, patient_id: str) -> dict[str, Any]: ...
    def withdraw_consents(self, owner: str, patient_id: str) -> int: ...
    def delete_patient(self, owner: str, patient_id: str) -> bool: ...
    def list_analyses(self, owner: str, case_id: str) -> list[dict[str, Any]]: ...
    def list_reviews(self, owner: str, case_id: str) -> list[dict[str, Any]]: ...
    def create_case(self, owner: str, data: dict[str, Any]) -> dict[str, Any]: ...
    def list_cases(self, owner: str, patient_id: str | None) -> list[dict[str, Any]]: ...
    def get_case(self, owner: str, case_id: str) -> dict[str, Any] | None: ...
    def update_case(
        self, owner: str, case_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...
    def replace_symptoms(
        self, owner: str, case_id: str, symptoms: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...
    def save_analysis(self, owner: str, data: dict[str, Any]) -> dict[str, Any]: ...
    def latest_analysis(self, owner: str, case_id: str) -> dict[str, Any] | None: ...
    def get_analysis(self, owner: str, analysis_id: str) -> dict[str, Any] | None: ...
    def save_review(self, owner: str, data: dict[str, Any]) -> dict[str, Any]: ...
    def audit(self, owner: str, action: str, entity: str, entity_id: str | None) -> None: ...
    def recent_actions(self, owner: str, actions: tuple[str, ...], since: str) -> list[str]: ...


def _run(operation: str, fn: Any) -> Any:
    try:
        return fn().execute()
    except Exception as exc:
        raise CaseStoreError(f"{operation} failed: {exc}") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseCaseStore:
    """CaseStore backed by the Supabase service-role client."""

    def __init__(self, client: Any) -> None:
        self._db = client

    def _first(self, operation: str, query: Any) -> dict[str, Any] | None:
        data = _run(operation, lambda: query).data
        return data[0] if data else None

    # -- patients -----------------------------------------------------------

    def create_patient(self, owner: str, data: dict[str, Any]) -> dict[str, Any]:
        consent_given = data.pop("consent_given")
        row = _run(
            "create_patient",
            lambda: self._db.table("patients").insert({**data, "practitioner_id": owner}),
        ).data[0]
        if consent_given:
            _run(
                "record_consent",
                lambda: self._db.table("consents").insert(
                    {
                        "practitioner_id": owner,
                        "patient_id": row["id"],
                        "purpose": "case_taking_and_ai_analysis",
                        "text_version": CONSENT_TEXT_VERSION,
                    }
                ),
            )
        return row

    def list_patients(self, owner: str) -> list[dict[str, Any]]:
        return _run(
            "list_patients",
            lambda: (
                self._db.table("patients")
                .select("*")
                .eq("practitioner_id", owner)
                .order("created_at", desc=True)
            ),
        ).data

    def get_patient(self, owner: str, patient_id: str) -> dict[str, Any] | None:
        return self._first(
            "get_patient",
            self._db.table("patients")
            .select("*")
            .eq("practitioner_id", owner)
            .eq("id", patient_id),
        )

    def update_patient(
        self, owner: str, patient_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        return self._first(
            "update_patient",
            self._db.table("patients")
            .update({**data, "updated_at": _now()})
            .eq("practitioner_id", owner)
            .eq("id", patient_id),
        )

    def has_active_consent(self, owner: str, patient_id: str) -> bool:
        rows = _run(
            "check_consent",
            lambda: (
                self._db.table("consents")
                .select("id")
                .eq("practitioner_id", owner)
                .eq("patient_id", patient_id)
                .is_("withdrawn_at", "null")
                .limit(1)
            ),
        ).data
        return bool(rows)

    def active_consent_patient_ids(self, owner: str) -> set[str]:
        rows = _run(
            "active_consents",
            lambda: (
                self._db.table("consents")
                .select("patient_id")
                .eq("practitioner_id", owner)
                .is_("withdrawn_at", "null")
            ),
        ).data
        return {row["patient_id"] for row in rows}

    def list_consents(self, owner: str, patient_id: str) -> list[dict[str, Any]]:
        return _run(
            "list_consents",
            lambda: (
                self._db.table("consents")
                .select("*")
                .eq("practitioner_id", owner)
                .eq("patient_id", patient_id)
                .order("granted_at", desc=True)
            ),
        ).data

    def add_consent(self, owner: str, patient_id: str) -> dict[str, Any]:
        return _run(
            "add_consent",
            lambda: self._db.table("consents").insert(
                {
                    "practitioner_id": owner,
                    "patient_id": patient_id,
                    "purpose": "case_taking_and_ai_analysis",
                    "text_version": CONSENT_TEXT_VERSION,
                }
            ),
        ).data[0]

    def withdraw_consents(self, owner: str, patient_id: str) -> int:
        rows = _run(
            "withdraw_consents",
            lambda: (
                self._db.table("consents")
                .update({"withdrawn_at": _now()})
                .eq("practitioner_id", owner)
                .eq("patient_id", patient_id)
                .is_("withdrawn_at", "null")
            ),
        ).data
        return len(rows)

    def delete_patient(self, owner: str, patient_id: str) -> bool:
        rows = _run(
            "delete_patient",
            lambda: (
                self._db.table("patients")
                .delete()
                .eq("practitioner_id", owner)
                .eq("id", patient_id)
            ),
        ).data
        return bool(rows)

    # -- cases --------------------------------------------------------------

    def create_case(self, owner: str, data: dict[str, Any]) -> dict[str, Any]:
        return _run(
            "create_case",
            lambda: self._db.table("cases").insert({**data, "practitioner_id": owner}),
        ).data[0]

    def list_cases(self, owner: str, patient_id: str | None) -> list[dict[str, Any]]:
        def query() -> Any:
            q = self._db.table("cases").select("*").eq("practitioner_id", owner)
            if patient_id:
                q = q.eq("patient_id", patient_id)
            return q.order("updated_at", desc=True)

        return _run("list_cases", query).data

    def _symptoms(self, owner: str, case_id: str) -> list[dict[str, Any]]:
        return _run(
            "list_symptoms",
            lambda: (
                self._db.table("case_symptoms")
                .select("*")
                .eq("practitioner_id", owner)
                .eq("case_id", case_id)
                .order("ordinal")
            ),
        ).data

    def get_case(self, owner: str, case_id: str) -> dict[str, Any] | None:
        case = self._first(
            "get_case",
            self._db.table("cases").select("*").eq("practitioner_id", owner).eq("id", case_id),
        )
        if case is None:
            return None
        return {**case, "symptoms": self._symptoms(owner, case_id)}

    def update_case(self, owner: str, case_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        updated = self._first(
            "update_case",
            self._db.table("cases")
            .update({**data, "updated_at": _now()})
            .eq("practitioner_id", owner)
            .eq("id", case_id),
        )
        if updated is None:
            return None
        return {**updated, "symptoms": self._symptoms(owner, case_id)}

    def replace_symptoms(
        self, owner: str, case_id: str, symptoms: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        # Upsert first, then trim: a failure never leaves a case with no symptoms.
        rows = [
            {**s, "practitioner_id": owner, "case_id": case_id, "ordinal": i}
            for i, s in enumerate(symptoms)
        ]
        if rows:
            _run(
                "upsert_symptoms",
                lambda: self._db.table("case_symptoms").upsert(rows, on_conflict="case_id,ordinal"),
            )
        _run(
            "trim_symptoms",
            lambda: (
                self._db.table("case_symptoms")
                .delete()
                .eq("practitioner_id", owner)
                .eq("case_id", case_id)
                .gte("ordinal", len(rows))
            ),
        )
        _run(
            "touch_case",
            lambda: (
                self._db.table("cases")
                .update({"updated_at": _now()})
                .eq("practitioner_id", owner)
                .eq("id", case_id)
            ),
        )
        return self._symptoms(owner, case_id)

    # -- analyses and reviews ----------------------------------------------

    def save_analysis(self, owner: str, data: dict[str, Any]) -> dict[str, Any]:
        return _run(
            "save_analysis",
            lambda: self._db.table("case_analyses").insert({**data, "practitioner_id": owner}),
        ).data[0]

    def latest_analysis(self, owner: str, case_id: str) -> dict[str, Any] | None:
        return self._first(
            "latest_analysis",
            self._db.table("case_analyses")
            .select("*")
            .eq("practitioner_id", owner)
            .eq("case_id", case_id)
            .order("created_at", desc=True)
            .limit(1),
        )

    def list_analyses(self, owner: str, case_id: str) -> list[dict[str, Any]]:
        return _run(
            "list_analyses",
            lambda: (
                self._db.table("case_analyses")
                .select("*")
                .eq("practitioner_id", owner)
                .eq("case_id", case_id)
                .order("created_at", desc=True)
            ),
        ).data

    def list_reviews(self, owner: str, case_id: str) -> list[dict[str, Any]]:
        return _run(
            "list_reviews",
            lambda: (
                self._db.table("case_reviews")
                .select("*")
                .eq("practitioner_id", owner)
                .eq("case_id", case_id)
                .order("signed_at", desc=True)
            ),
        ).data

    def get_analysis(self, owner: str, analysis_id: str) -> dict[str, Any] | None:
        return self._first(
            "get_analysis",
            self._db.table("case_analyses")
            .select("*")
            .eq("practitioner_id", owner)
            .eq("id", analysis_id),
        )

    def save_review(self, owner: str, data: dict[str, Any]) -> dict[str, Any]:
        return _run(
            "save_review",
            lambda: self._db.table("case_reviews").insert({**data, "practitioner_id": owner}),
        ).data[0]

    def recent_actions(self, owner: str, actions: tuple[str, ...], since: str) -> list[str]:
        rows = _run(
            "recent_actions",
            lambda: (
                self._db.table("audit_log")
                .select("created_at")
                .eq("practitioner_id", owner)
                .in_("action", list(actions))
                .gte("created_at", since)
                .order("created_at")
            ),
        ).data
        return [row["created_at"] for row in rows]

    def audit(self, owner: str, action: str, entity: str, entity_id: str | None) -> None:
        _run(
            "audit",
            lambda: self._db.table("audit_log").insert(
                {
                    "practitioner_id": owner,
                    "action": action,
                    "entity": entity,
                    "entity_id": entity_id,
                }
            ),
        )
