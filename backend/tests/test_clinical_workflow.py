import unicodedata
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pymupdf
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.ai.rag.clinical_research import (
    URGENT_HANDOFF,
    WorkflowStageError,
    research,
    verified_quote,
)
from app.api import auth
from app.api.routes import cases, clinical_images, clinical_workflow
from app.main import create_app
from app.services.clinical_images import sanitize_photo
from app.services.clinical_workflow import DRAFT, report_blocks
from app.services.report_files import render_docx, render_pdf


def test_urgent_research_keeps_handoff_and_skips_all_remote_calls() -> None:
    result = research(
        object(),
        object(),
        "Recorded symptoms",
        "en",
        "hybrid",
        ["Urgent finding from an earlier version"],
        [],
        None,
    )
    assert result["handoff"] == URGENT_HANDOFF
    assert result["urgent_findings"] == ["Urgent finding from an earlier version"]
    assert not result["searches"]
    assert not result["associations"]


def test_quote_validation_preserves_source_words() -> None:
    assert verified_quote("two words", "These are two\nwords.")
    assert not verified_quote("Two words", "These are two\nwords.")
    assert not verified_quote("two other words", "These are two\nwords.")
    assert not verified_quote("word", "These are two\nwords.")
    assert not verified_quote(" ", "These are two\nwords.")


def test_research_reports_keyword_fallback_even_when_no_hits(monkeypatch) -> None:
    from app.ai.rag.case_analysis import NormalisedCase, SearchQuery

    class Reasoner:
        def __init__(self, _llm):
            pass

        def normalise(self, _text, _language):
            return NormalisedCase(queries=[SearchQuery(text="knee stiffness")])

    from app.ai.rag import clinical_research as pipeline

    monkeypatch.setattr(pipeline, "ClaudeReasoner", Reasoner)
    monkeypatch.setattr(pipeline, "book_completeness", lambda _db: {})
    monkeypatch.setattr(
        pipeline,
        "build_retriever",
        lambda *_a, **_kw: SimpleNamespace(
            mode="keyword",
            fallback_reason="Provider unavailable",
            search=lambda *_a, **_kw: ([], 0),
        ),
    )
    result = research(object(), object(), "Knee stiffness", "en", "hybrid", [], [], None)
    assert result["coverage"] == "no_hits"
    assert result["requested_mode"] == "hybrid"
    assert [item["category"] for item in result["searches"]] == ["repertory", "materia_medica"]
    assert all(item["used"] == "keyword" and item["fallback_reason"] for item in result["searches"])


def test_photo_reencode_strips_metadata_and_refuses_unrecognised_files() -> None:
    encoded = BytesIO()
    image = Image.new("RGB", (640, 320), "navy")
    exif = image.getexif()
    exif[0x010E] = "private camera annotation"
    image.save(encoded, "JPEG", exif=exif)
    full, small = sanitize_photo(encoded.getvalue())
    with Image.open(BytesIO(full)) as restored:
        assert not restored.getexif()
        assert restored.size == (640, 320)
    with Image.open(BytesIO(small)) as thumbnail:
        assert thumbnail.size == (320, 160)
    with pytest.raises(ValueError, match="valid"):
        sanitize_photo(b"<svg></svg>")
    with pytest.raises(ValueError, match="under 8 MB"):
        sanitize_photo(b"")


def test_vision_output_excludes_diagnoses_and_arbitrary_text() -> None:
    result = clinical_images.Observations.model_validate(
        {
            "observations": [
                {
                    "feature": "redness",
                    "visibility": "visible",
                    "distribution": "localised",
                    "change": "increased",
                }
            ],
            "limits": ["lighting"],
        }
    )
    assert "increased" in result.description(comparing=True)["observations"][0]
    with pytest.raises(ValidationError):
        clinical_images.Observations.model_validate(
            {
                "observations": [
                    {
                        "feature": "an infection",
                        "visibility": "visible",
                        "distribution": "localised",
                        "change": "increased",
                    }
                ],
                "limits": [],
            }
        )


def test_clinical_signing_ignores_user_editable_metadata(monkeypatch) -> None:
    metadata = {"similia_role": "practitioner"}
    user = SimpleNamespace(
        id=str(uuid4()),
        app_metadata=metadata,
        user_metadata={"similia_clinical_signing": True},
    )
    monkeypatch.setattr(
        auth,
        "get_supabase_admin_client",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(get_user=lambda _token: SimpleNamespace(user=user)),
        ),
    )
    credential = HTTPAuthorizationCredentials(scheme="Bearer", credentials="test")
    with pytest.raises(HTTPException) as denial:
        auth.require_clinical_signer(credential)
    assert denial.value.status_code == 403
    metadata["similia_clinical_signing"] = True
    assert auth.require_clinical_signer(credential) == user.id


class ClinicalMemory:
    def __init__(self):
        self.owner = str(uuid4())
        self.case_id = str(uuid4())
        self.patient_id = str(uuid4())
        self.case = {
            "id": self.case_id,
            "patient_id": self.patient_id,
            "clinical_revision": 1,
            "chief_complaint": "Synthetic case fixture",
            "symptoms": [],
            "language": "en",
            "status": "draft",
        }
        self.patient = {
            "id": self.patient_id,
            "full_name": "Test record",
            "age_years": 0,
        }
        self.saved = []
        self.failed = []
        self.db = object()  # Any accidental database call fails this offline fixture.

    def get_case(self, owner, case_id):
        return self.case if owner == self.owner and case_id == self.case_id else None

    def get_patient(self, owner, patient_id):
        return self.patient if owner == self.owner and patient_id == self.patient_id else None

    def has_active_consent(self, owner, patient_id):
        return self.get_patient(owner, patient_id) is not None

    def audit(self, *_args):
        pass

    def begin(self, _case, _stage, request_id):
        return {"id": request_id, "status": "running"}

    def complete(self, _attempt, values):
        row = {
            "id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_id": None,
            "provider": None,
            "model": None,
            **values,
        }
        if row["status"] == "signed":
            row["signed_at"] = row["created_at"]
        self.saved.insert(0, row)
        return row

    def fail(self, _attempt_id, stage):
        self.failed.append(stage)

    def report(self, case_id, report_id):
        for row in self.saved:
            if row["id"] == report_id and row["case_id"] == case_id:
                return row
        raise HTTPException(404, "Report unavailable")

    def reports(self, case_id):
        return [row for row in self.saved if row["case_id"] == case_id]

    def images(self, _cases):
        return []

    def consent(self, _patient, _scope):
        return None


@pytest.fixture
def workflow_client(monkeypatch):
    state = ClinicalMemory()
    login = {"owner": state.owner, "can_sign": False}
    app = create_app()
    app.dependency_overrides[auth.require_practitioner] = lambda: login["owner"]
    app.dependency_overrides[cases.get_case_store] = lambda: state
    app.dependency_overrides[cases.get_ai_store] = lambda: SimpleNamespace(get=lambda _owner: None)
    app.dependency_overrides[clinical_workflow.clinical_store] = lambda: state

    def sign():
        if not login["can_sign"]:
            raise HTTPException(403, "Clinical signing permission is required")
        return login["owner"]

    app.dependency_overrides[auth.require_clinical_signer] = sign
    monkeypatch.setattr(
        clinical_workflow,
        "get_settings",
        lambda: SimpleNamespace(
            clinical_workflow_enabled=True,
        ),
    )
    monkeypatch.setattr(clinical_workflow, "clinical_store", lambda _owner: state)
    return TestClient(app), state, login


def test_three_reports_are_separate_and_signing_checks_privilege_and_case_revision(
    workflow_client,
    monkeypatch,
) -> None:
    client, state, login = workflow_client
    root = f"/api/cases/{state.case_id}/workflow"
    monkeypatch.setattr(
        clinical_workflow,
        "assess",
        lambda _db, _llm, source: {
            **source,
            "evidence_status": "unavailable",
            "guidelines": [],
            "claims": [],
        },
    )
    result = client.post(f"{root}/research", json={"request_id": str(uuid4())})
    assert result.status_code == 201, result.text
    research_id = result.json()["id"]
    assert result.json()["urgent"]
    assert state.saved[0]["payload"]["coverage"] == "skipped"
    result = client.post(
        f"{root}/assessment",
        json={
            "request_id": str(uuid4()),
            "research_id": research_id,
        },
    )
    assert result.status_code == 201, result.text
    assessment_id = result.json()["id"]
    assert any(block["text"] == DRAFT for block in result.json()["blocks"])
    form = {
        "request_id": str(uuid4()),
        "decision": "modified",
        "assessment_id": assessment_id,
        "author": "Test clinician",
        "assessment": "Technical fixture only",
        "care_plan": "Technical fixture only",
        "reason": "Test amendment",
    }
    assert client.post(f"{root}/final/sign", json=form).status_code == 403
    login["can_sign"] = True
    assert client.post(f"{root}/final/sign", json=form).status_code == 422
    form["urgency_disposition"] = "Fixture disposition recorded by clinician"
    signed = client.post(f"{root}/final/sign", json=form)
    assert signed.status_code == 201, signed.text
    assert signed.json()["status"] == "signed"
    history = client.get(root).json()["reports"]
    assert [row["stage"] for row in history] == ["final", "assessment", "research"]
    assert len({row["id"] for row in history}) == 3
    for row in history:
        uri = f"{root}/reports/{row['id']}/file"
        assert client.get(f"{uri}?format=pdf").content.startswith(b"%PDF")
        assert client.get(f"{uri}?format=docx").content.startswith(b"PK")
    state.case["clinical_revision"] += 1
    assert client.post(f"{root}/final/sign", json=form).status_code == 409
    login["owner"] = str(uuid4())
    assert client.get(root).status_code == 404
    assert client.get(f"{root}/reports/{assessment_id}/file?format=pdf").status_code == 404
    assert (
        client.get(
            f"/api/cases/{state.case_id}/photos/{uuid4()}/full",
        ).status_code
        == 404
    )


def test_failed_provider_does_not_save_completed_report(workflow_client, monkeypatch) -> None:
    client, state, _ = workflow_client
    state.patient["age_years"] = 40
    monkeypatch.setattr(clinical_workflow, "_own_llm", lambda _row: object())
    monkeypatch.setattr(clinical_workflow, "_enforce_limit", lambda *_a, **_kw: None)
    monkeypatch.setattr(clinical_workflow, "embedding_paused", lambda: True)

    def fail(*_args, **_kwargs):
        raise WorkflowStageError("prepare_queries")

    monkeypatch.setattr(clinical_workflow, "research", fail)
    result = client.post(
        f"/api/cases/{state.case_id}/workflow/research",
        json={"request_id": str(uuid4())},
    )
    assert result.status_code == 502
    assert result.json()["detail"] == "Clinical workflow failed at prepare queries"
    assert state.failed == ["prepare_queries"]
    assert not state.saved


def test_photos_cannot_be_sent_without_separate_collection_and_provider_consent(
    workflow_client,
) -> None:
    client, state, _ = workflow_client
    result = client.post(
        f"/api/cases/{state.case_id}/photos/observe",
        json={
            "image_ids": [str(uuid4())],
            "model": "test-vision-model",
        },
    )
    assert result.status_code == 409
    assert result.json()["detail"] == "Record active consent to send photos to Google Gemini"


def test_photo_upload_size_limit_applies_when_calling_backend_directly(workflow_client) -> None:
    client, state, _ = workflow_client
    result = client.post(
        f"/api/cases/{state.case_id}/photos",
        content=b"body is not parsed",
        headers={"content-length": str(9 * 1024 * 1024)},
    )
    assert result.status_code == 413


@pytest.mark.parametrize("stage", ["research", "assessment", "final"])
def test_urdu_word_and_pdf_contain_the_report(stage) -> None:
    row = {
        "id": str(uuid4()),
        "source_id": None,
        "created_at": "2026-11-24T00:00:00Z",
        "locale": "ur",
        "stage": stage,
        "status": "reviewed" if stage == "final" else "translation",
        "payload": {
            "patient_label": "نمونہ",
            "assessment": "طبی رپورٹ",
            **(
                {
                    "translated_blocks": [
                        {"kind": "p", "text": "طبی رپورٹ", "ltr": False},
                    ]
                }
                if stage != "final"
                else {}
            ),
        },
    }
    blocks = report_blocks(row)
    assert any(block.ltr and block.text == f"ID {row['id']}" for block in blocks)
    assert any(block.ltr and block.text == "UTC 2026-11-24 00:00" for block in blocks)
    with ZipFile(BytesIO(render_docx(blocks, "ur"))) as docx:
        xml = docx.read("word/document.xml").decode()
        assert "طبی رپورٹ" in xml
        assert "<w:bidi/>" in xml
    with pymupdf.open(stream=render_pdf(blocks, "ur")) as pdf:
        assert len(pdf) == 1
        assert f"ID {row['id']}" in unicodedata.normalize("NFKC", pdf[0].get_text())
        pixmap = pdf[0].get_pixmap()
        assert len(set(pixmap.samples)) > 5
