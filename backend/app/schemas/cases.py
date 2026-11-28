"""Request/response schemas for patients, cases and AI case analysis."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Language = Literal["en", "hi", "ur"]
Sex = Literal["female", "male", "other", "unspecified"]
SymptomKind = Literal["mental", "physical_general", "particular", "history", "family", "medication"]
CaseStatus = Literal["draft", "analyzed", "signed_off"]
AnalysisOutcome = Literal["ranked", "insufficient_sources", "red_flag"]
Confidence = Literal["low", "medium", "high"]

MAX_SYMPTOMS = 80
Short = Field(default=None, max_length=500)
Long = Field(default=None, max_length=4000)


class PatientCreate(BaseModel):
    identifier: str = Field(min_length=1, max_length=64)
    full_name: str = Field(min_length=1, max_length=200)
    date_of_birth: date | None = None
    age_years: int | None = Field(default=None, ge=0, le=130)
    sex: Sex = "unspecified"
    preferred_language: Language = "en"
    contact: str | None = Field(default=None, max_length=200)
    notes: str | None = Long
    guardian_name: str | None = Field(default=None, max_length=200)
    guardian_relationship: str | None = Field(default=None, max_length=100)
    consent_given: bool = Field(description="Patient gave informed consent to record and analyse")


class PatientUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    date_of_birth: date | None = None
    age_years: int | None = Field(default=None, ge=0, le=130)
    sex: Sex | None = None
    preferred_language: Language | None = None
    contact: str | None = Field(default=None, max_length=200)
    notes: str | None = Long
    guardian_name: str | None = Field(default=None, max_length=200)
    guardian_relationship: str | None = Field(default=None, max_length=100)
    archived: bool | None = None


class PatientOut(BaseModel):
    id: UUID
    identifier: str
    full_name: str
    date_of_birth: date | None = None
    age_years: int | None = None
    sex: str
    preferred_language: str
    contact: str | None = None
    notes: str | None = None
    guardian_name: str | None = None
    guardian_relationship: str | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    is_minor: bool = False  # under 18: guardian consent is required
    is_infant: bool = False  # under 1 year: urgency must be assessed in person
    consent_active: bool = False


class ConsentOut(BaseModel):
    id: UUID
    purpose: str
    text_version: str
    granted_at: datetime
    withdrawn_at: datetime | None = None


class CaseHistoryOut(BaseModel):
    """One line per case for a patient's history: no symptom detail, no AI text."""

    id: UUID
    status: CaseStatus
    chief_complaint: str
    language: str
    created_at: datetime
    updated_at: datetime
    analysis_count: int = 0
    latest_outcome: AnalysisOutcome | None = None
    review_decision: str | None = None
    chosen_remedy: str | None = None
    signed_at: datetime | None = None


class SymptomIn(BaseModel):
    kind: SymptomKind
    label: str = Field(min_length=1, max_length=300)
    location: str | None = Short
    sensation: str | None = Short
    better: str | None = Short
    worse: str | None = Short
    concomitants: str | None = Short
    duration: str | None = Field(default=None, max_length=500)
    notes: str | None = Long
    weight: int = Field(default=2, ge=1, le=3)


class SymptomOut(SymptomIn):
    id: UUID
    ordinal: int


class SymptomsPut(BaseModel):
    symptoms: list[SymptomIn] = Field(max_length=MAX_SYMPTOMS)


class CaseCreate(BaseModel):
    patient_id: UUID
    chief_complaint: str = Field(default="", max_length=2000)
    language: Language = "en"


class CaseUpdate(BaseModel):
    chief_complaint: str | None = Field(default=None, max_length=2000)
    language: Language | None = None


class CaseOut(BaseModel):
    id: UUID
    patient_id: UUID
    status: CaseStatus
    chief_complaint: str
    language: str
    created_at: datetime
    updated_at: datetime
    symptoms: list[SymptomOut] = []


class RemedyOut(BaseModel):
    remedy: str
    confidence: Confidence
    rationale: str
    matching_symptoms: list[str] = []
    contradicting_symptoms: list[str] = []
    citations: list[str] = Field(description="chunk_ids from the passages list")


class AnalysisPassageOut(BaseModel):
    chunk_id: str
    book_title: str
    book_category: str
    book_author: str | None = None
    section_heading: str | None = None
    section_path: list[str] = []
    page_start: int | None = None  # PDF page number (not the printed page number)
    page_end: int | None = None
    book_complete: bool = True  # False: the book is only partly indexed
    retrieval_mode: str = "semantic"  # "keyword": found by word matching, not by meaning
    matched_by: list[str] = []
    content: str
    similarity: float


class AnalysisOut(BaseModel):
    id: UUID
    case_id: UUID
    outcome: AnalysisOutcome
    red_flags: list[str] = []
    remedies: list[RemedyOut] = []
    passages: list[AnalysisPassageOut] = []
    missing_information: list[str] = []
    cautions: list[str] = []  # patient-specific cautions (children, infants)
    retrieval_mode: str = "semantic"  # the method that actually ran: semantic, keyword, hybrid
    requested_mode: str = "semantic"
    fallback_reason: str | None = None
    incomplete_books: list[str] = []  # titles of partly indexed books the evidence came from
    model: str | None = None
    created_at: datetime
    disclaimer: str = (
        "Retrieved historical text is decision support for a qualified practitioner. "
        "It is not clinical evidence, a diagnosis, or a prescription."
    )


class QuestionOut(BaseModel):
    topic: str
    question: str
    topic_ur: str = ""
    question_ur: str = ""
    example_answer: str = ""
    example_answer_ur: str = ""


class UrduRemedyOut(BaseModel):
    remedy: str
    rationale: str
    matching_symptoms: list[str] = []
    contradicting_symptoms: list[str] = []


class UrduReportOut(BaseModel):
    """Machine translation of the AI-written parts of an analysis. Book passages stay English."""

    analysis_id: UUID
    chief_complaint: str = ""
    red_flags: list[str] = []
    cautions: list[str] = []
    remedies: list[UrduRemedyOut] = []
    missing_information: list[str] = []
    notice: str = (
        "Machine translation by AI. Have it checked before you rely on it. "
        "Book passages are shown in their original English."
    )


class QuestionsOut(BaseModel):
    red_flags: list[str] = []
    mental: list[QuestionOut] = []
    physical_general: list[QuestionOut] = []
    particular: list[QuestionOut] = []
    history: list[QuestionOut] = []
    disclaimer: str = (
        "Suggested questions are prompts for the practitioner. They are not a diagnosis "
        "or a recommendation of any remedy."
    )


class ReviewIn(BaseModel):
    analysis_id: UUID
    decision: Literal["accepted", "modified", "rejected"]
    chosen_remedy: str | None = Field(default=None, max_length=200)
    diagnosis: str | None = Field(default=None)
    potency: str | None = Field(default=None, max_length=100)
    dose: str | None = Field(default=None, max_length=200)
    frequency: str | None = Field(default=None, max_length=200)
    duration: str | None = Field(default=None, max_length=200)
    instructions: str | None = Field(default=None, max_length=2000)
    urgency_disposition: str | None = Field(default=None, max_length=2000)
    include_urgent_in_pdf: bool = False
    practitioner_name: str | None = Field(default=None, max_length=200)  # as typed by the signer
    notes: str | None = Long


class ReviewOut(BaseModel):
    id: UUID
    case_id: UUID
    analysis_id: UUID
    decision: str
    chosen_remedy: str | None = None
    diagnosis: str | None = None
    potency: str | None = None
    dose: str | None = None
    frequency: str | None = None
    duration: str | None = None
    instructions: str | None = None
    urgency_disposition: str | None = None
    include_urgent_in_pdf: bool = False
    practitioner_name: str | None = None
    notes: str | None = None
    signed_at: datetime
