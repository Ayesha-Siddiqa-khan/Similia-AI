"""AI follow-up questions tailored to the chief complaint.

Helps the practitioner decide what to ask next, step by step (mind, whole body,
complaint details, history). It never diagnoses or names remedies. The same
deterministic red-flag screen as the analysis runs first, so an urgent case
returns a notice instead of routine questions.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.ai.rag.case_analysis import SYSTEM_RULES, build_case_text, screen_red_flags
from app.services.llm import LLMProvider

STEPS = ("mental", "physical_general", "particular", "history")
MAX_PER_STEP = 6


class FollowUpQuestion(BaseModel):
    topic: str = Field(description="2-4 word label, e.g. 'Itching' or 'Thirst'")
    question: str = Field(description="One short question to ask the patient, in English")
    example_answer: str = Field(
        default="",
        description="A short, clearly illustrative sample of how a patient might answer this "
        "question in one full sentence. It is a writing aid, never a real finding.",
    )
    topic_ur: str = Field(default="", description="Urdu translation of topic (only if requested)")
    question_ur: str = Field(
        default="", description="Urdu translation of the question (only if requested)"
    )
    example_answer_ur: str = Field(
        default="", description="Urdu translation of example_answer (only if requested)"
    )


class FollowUps(BaseModel):
    mental: list[FollowUpQuestion] = Field(default_factory=list)
    physical_general: list[FollowUpQuestion] = Field(default_factory=list)
    particular: list[FollowUpQuestion] = Field(default_factory=list)
    history: list[FollowUpQuestion] = Field(default_factory=list)


class QuestionWriter(Protocol):
    def write(self, case_text: str, include_urdu: bool) -> FollowUps: ...


class ClaudeQuestionWriter:
    """QuestionWriter over the configured chat model (structured output)."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def write(self, case_text: str, include_urdu: bool) -> FollowUps:
        model = self._llm.chat_model().with_structured_output(FollowUps)  # type: ignore[attr-defined]
        urdu = (
            " For every item also fill topic_ur, question_ur and example_answer_ur with a natural "
            "Urdu translation "
            "(Arabic script, simple everyday words a patient understands; keep an English medical "
            "term in brackets only if there is no common Urdu word)."
            if include_urdu
            else " Leave topic_ur, question_ur and example_answer_ur empty."
        )
        return model.invoke(
            [
                (
                    "system",
                    SYSTEM_RULES
                    + " Write follow-up questions in English, in simple words a patient "
                    f"understands, at most {MAX_PER_STEP} per group. Tailor them to the chief "
                    "complaint and do not repeat anything already answered. Groups: "
                    "mental (temperament, fears, reactions to stress, consolation, company); "
                    "physical_general (heat/cold, thirst, appetite, food desires/aversions, "
                    "sleep, dreams, perspiration, stool, urine, menses); "
                    "particular (for the main complaint: exact location, sensation, discharge or "
                    "appearance, what makes it better or worse, what accompanies it, timing, and "
                    "any warning signs that need a doctor); "
                    "history (earlier illnesses, family history, medicines and remedies taken and "
                    "how the patient responded, any aggravation after them). "
                    "For every question also write example_answer: one short, plain, full sentence "
                    "showing how a patient might answer, so the practitioner can see what a good "
                    "answer looks like (invent a neutral illustration; it must not state facts "
                    "about this patient). "
                    "Never suggest a diagnosis, remedy, potency or dose." + urdu,
                ),
                ("human", case_text),
            ]
        )


@dataclass
class QuestionResult:
    red_flags: list[str] = field(default_factory=list)
    questions: dict[str, list[dict[str, str]]] = field(
        default_factory=lambda: {step: [] for step in STEPS}
    )


def _clean(items: list[FollowUpQuestion], include_urdu: bool) -> list[dict[str, str]]:
    cleaned: list[dict[str, str]] = []
    for item in items:
        topic, question = item.topic.strip()[:80], item.question.strip()[:300]
        if topic and question:
            cleaned.append(
                {
                    "topic": topic,
                    "question": question,
                    # Urdu is optional; only keep it when it was asked for and both parts exist.
                    "topic_ur": item.topic_ur.strip()[:80] if include_urdu else "",
                    "question_ur": item.question_ur.strip()[:400] if include_urdu else "",
                    "example_answer": item.example_answer.strip()[:300],
                    "example_answer_ur": (
                        item.example_answer_ur.strip()[:400] if include_urdu else ""
                    ),
                }
            )
        if len(cleaned) == MAX_PER_STEP:
            break
    return cleaned


def suggest_questions(
    case: dict[str, Any], writer: QuestionWriter, include_urdu: bool = False
) -> QuestionResult:
    text = build_case_text(case)
    flags = screen_red_flags(text)
    if flags:  # urgent first: no routine questions, no AI call
        return QuestionResult(red_flags=flags)
    written = writer.write(text, include_urdu)
    return QuestionResult(
        questions={step: _clean(getattr(written, step), include_urdu) for step in STEPS}
    )
