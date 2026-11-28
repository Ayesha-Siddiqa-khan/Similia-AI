"""PDF and Word report files: content, Urdu handling, owner-only, no AI call."""

# ruff: noqa: F811
import io
import unicodedata
import xml.dom.minidom
import zipfile

import pymupdf

from app.ai.rag.report_translation import UrduRemedy, UrduReport
from app.services import report_files
from tests.test_cases_api import Env, env, make_case, make_patient  # noqa: F401


def analysed(env: Env) -> str:
    case_id = make_case(env)
    assert env.client.post(f"/api/cases/{case_id}/analyze").status_code == 201
    return case_id


def urdu_for(env: Env, case_id: str) -> dict:
    analysis = env.client.get(f"/api/cases/{case_id}/analysis").json()
    remedies = [
        UrduRemedy(
            remedy=r["remedy"],
            rationale="وجہ یہ ہے",
            matching_symptoms=["علامت"] * len(r["matching_symptoms"]),
            contradicting_symptoms=["مخالف"] * len(r["contradicting_symptoms"]),
        )
        for r in analysis["remedies"]
    ]
    return UrduReport(
        chief_complaint="سر درد",
        red_flags=["انتباہ"] * len(analysis["red_flags"]),
        cautions=["احتیاط"] * len(analysis["cautions"]),
        remedies=remedies,
        missing_information=["سوال"] * len(analysis["missing_information"]),
    ).model_dump()


def post(env: Env, case_id: str, **body):
    return env.client.post(f"/api/cases/{case_id}/report/file", json=body)


def pdf_text(data: bytes) -> str:
    raw = "\n".join(page.get_text() for page in pymupdf.open(stream=data, filetype="pdf"))
    return unicodedata.normalize("NFKD", raw)


def docx_xml(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= set(
            archive.namelist()
        )
        document = archive.read("word/document.xml").decode("utf-8")
    xml.dom.minidom.parseString(document)  # well formed
    return document


def test_the_english_pdf_is_a_real_pdf_with_the_report_content(env: Env) -> None:
    case_id = analysed(env)
    response = post(env, case_id, format="pdf", lang="en")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment") and disposition.endswith('-report-en.pdf"')
    assert "Test Patient" not in disposition and "P-001" not in disposition  # name stays inside
    assert response.headers["cache-control"] == "private, no-store"
    text = pdf_text(response.content)
    for expected in (
        "Case analysis report",
        "Test Patient",
        "Chief complaint",
        "Belladonna",
        "Sources",
        "Decision support",
    ):
        assert expected in text, expected
    assert ("doctor-a", "case.report.download", "case", case_id) in env.store.audit_rows


def test_the_english_word_file_is_a_valid_package_with_the_content(env: Env) -> None:
    case_id = analysed(env)
    response = post(env, case_id, format="docx", lang="en")
    assert response.status_code == 200
    assert response.headers["content-type"].endswith("wordprocessingml.document")
    document = docx_xml(response.content)
    for expected in ("Case analysis report", "Test Patient", "Belladonna", "Chief complaint"):
        assert expected in document, expected
    assert "<w:bidi/>" not in document  # English is left to right


def test_the_urdu_files_use_the_translation_and_right_to_left_text(env: Env) -> None:
    case_id = analysed(env)
    translation = urdu_for(env, case_id)
    pdf = post(env, case_id, format="pdf", lang="ur", translation=translation)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert len(pymupdf.open(stream=pdf.content, filetype="pdf")) >= 1
    word = post(env, case_id, format="docx", lang="ur", translation=translation)
    assert word.status_code == 200
    document = docx_xml(word.content)
    assert "<w:bidi/>" in document and "<w:rtl/>" in document
    assert "Jameel Noori Nastaleeq" in document and "سر درد" in document
    assert "Belladonna" in document  # the remedy name and the book text stay Latin


def test_urdu_needs_a_translation_that_lines_up_with_the_analysis(env: Env) -> None:
    case_id = analysed(env)
    assert post(env, case_id, format="pdf", lang="ur").status_code == 422
    bad = urdu_for(env, case_id)
    bad["remedies"] = []
    refused = post(env, case_id, format="pdf", lang="ur", translation=bad)
    assert refused.status_code == 422 and "does not match" in refused.json()["detail"]


def test_a_case_without_an_analysis_and_other_doctors_get_not_found(env: Env) -> None:
    empty = make_case(env)
    assert post(env, empty, format="pdf", lang="en").status_code == 404
    case_id = analysed(env)
    env.as_user("doctor-b")
    assert post(env, case_id, format="pdf", lang="en").status_code == 404


def test_the_blocks_label_keyword_results_and_hold_no_other_patient_data(env: Env) -> None:
    case = {"id": "abcdef12-0000", "status": "draft", "chief_complaint": "itch"}
    patient = {"full_name": "A B", "identifier": "P-9", "age_years": 9, "sex": "female"}
    analysis = {
        "outcome": "ranked",
        "red_flags": [],
        "missing_information": ["Is there fever?"],
        "passages": [
            {
                "chunk_id": "c1",
                "book_title": "MM",
                "retrieval_mode": "keyword",
                "book_complete": False,
                "content": "x" * 900,
                "page_start": 4,
                "page_end": 5,
            }
        ],
        "remedies": [
            {
                "remedy": "Sulphur",
                "confidence": "low",
                "rationale": "r",
                "matching_symptoms": ["a"],
                "contradicting_symptoms": [],
                "citations": ["c1"],
            }
        ],
        "model": "m",
        "created_at": "2026-11-24T10:00:00+00:00",
    }
    blocks = report_files.build_blocks(
        case, patient, analysis, "en", None, "24 Nov 2026", ["Paediatric patient"]
    )
    text = " | ".join(b.text for b in blocks)
    assert "keyword matching" in text and "Search method: Keyword" in text
    assert "partly indexed" in text and "PDF pages 4–5" in text
    assert "Paediatric patient" in text and "…" in text  # long excerpt is shortened
    assert "x" * 700 not in text and "abcdef12" in text and "abcdef12-0000" not in text


def test_the_endpoint_needs_sign_in() -> None:
    import uuid

    from fastapi.testclient import TestClient

    from app.main import create_app

    url = f"/api/cases/{uuid.uuid4()}/report/file"
    assert TestClient(create_app()).post(url, json={"format": "pdf"}).status_code == 401


def test_prescription_pdf_contains_clinical_content_and_omits_technical_details() -> None:
    case = {"id": "12345678-abcd", "chief_complaint": "Severe urticaria with burning pain"}
    patient = {
        "full_name": "Jane Patient",
        "identifier": "MRN-5544",
        "age_years": 42,
        "sex": "female",
    }
    review = {
        "decision": "accepted",
        "chosen_remedy": "Apis mellifica",
        "diagnosis": "Acute Urticaria",
        "potency": "200C",
        "dose": "4 pills",
        "frequency": "Three times daily",
        "duration": "5 days",
        "instructions": "Dissolve in mouth. Avoid camphor and hot applications.",
        "urgency_disposition": (
            "Patient instructed to attend emergency if lip swelling or breathing difficulty occurs."
        ),
        "practitioner_name": "Dr. Treating Doctor",
        "signed_at": "2026-11-24T10:00:00+00:00",
    }
    pdf_bytes = report_files.render_prescription_pdf(case, patient, review)
    assert pdf_bytes.startswith(b"%PDF")
    text = pdf_text(pdf_bytes)

    # Required clinical content:
    assert "Jane Patient" in text
    assert "MRN-5544" in text
    assert "Chief Complaint" not in text
    assert "Severe urticaria with burning pain" not in text
    assert "Acute Urticaria" in text
    assert "Apis mellifica" in text
    assert "200C" in text
    assert "4 pills" in text
    assert "Three times daily" in text
    assert "5 days" in text
    assert "Dissolve in mouth" in text
    assert "Dr. Treating Doctor" in text
    # Urgent Advisory is omitted by default on patient prescription
    assert "Urgent Clinical Advisory" not in text
    assert "lip swelling" not in text

    # When explicitly opted in by practitioner:
    review_with_urgent = {**review, "include_urgent_in_pdf": True}
    pdf_with_urgent = report_files.render_prescription_pdf(case, patient, review_with_urgent)
    text_with_urgent = pdf_text(pdf_with_urgent)
    assert "Urgent Clinical Advisory" in text_with_urgent
    assert "lip swelling" in text_with_urgent

    # STRICTLY OMITTED technical and research details:
    assert "voyage" not in text.lower()
    assert "claude" not in text.lower()
    assert "semantic" not in text.lower()
    assert "keyword matching" not in text.lower()
    assert "match_chunks" not in text.lower()
    assert "chunk-" not in text.lower()
    assert "similarity" not in text.lower()
    assert "materia medica" not in text.lower()
    assert "12345678-abcd" not in text  # full technical uuid is not exposed
