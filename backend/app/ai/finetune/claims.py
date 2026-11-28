"""Separate historical homeopathic claims from established medical evidence.

The corpus is nineteenth and early twentieth-century homeopathic literature.
Nothing in it is promoted to ``established_medical_evidence`` by this module:
that label would require a curated, externally verified evidence source, which
this module deliberately does not invent. Every generated answer is therefore
tagged as a historical claim of its cited author, with an explicit scientific
status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai.finetune.config import SCIENTIFIC_BOUNDARY

HISTORICAL_CLAIM = "historical_homeopathic_claim"
ESTABLISHED_EVIDENCE = "established_medical_evidence"

NOT_ESTABLISHED = "not_established"
NOT_ASSESSED = "not_assessed"

_DOCTRINE = re.compile(
    r"\b(?:remed(?:y|ies)|potenc(?:y|ies)|dilut(?:ion|ions)|proving|proved|"
    r"simillimum|materia medica|homoeopath\w*|homeopath\w*|nosode|miasm\w*|"
    r"psora|sycosis|trituration|dose|dosage|attenuat\w*)\b",
    re.IGNORECASE,
)
_CASE = re.compile(r"\b(?:case|patient|Mrs|Mr|Miss|child|boy|girl|woman|man)\b", re.IGNORECASE)
_POSOLOGY = re.compile(r"\b(?:[0-9]{1,2}\s?(?:c|C|ch|CH)|[0-9]{3}\s?(?:c|C)|1M|LM|Q)\b")


@dataclass(frozen=True)
class ClaimClassification:
    evidence_class: str
    scientific_status: str
    claim_tags: tuple[str, ...]
    boundary: str = SCIENTIFIC_BOUNDARY
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "evidence_class": self.evidence_class,
            "scientific_status": self.scientific_status,
            "claim_tags": list(self.claim_tags),
            "boundary": self.boundary,
            "notes": list(self.notes),
        }


def classify_claim(text: str) -> ClaimClassification:
    """Classify a source passage without asserting clinical efficacy."""
    tags: set[str] = {"historical_source"}
    notes: list[str] = []

    if _DOCTRINE.search(text):
        tags.add("homeopathic_doctrine")
    if _CASE.search(text):
        tags.add("case_report")
    if _POSOLOGY.search(text):
        tags.add("posology")

    # A passage that mentions a remedy, potency or proving is a historical
    # therapeutic claim. Otherwise it is descriptive text whose scientific
    # status has not been assessed here.
    therapeutic = bool({"homeopathic_doctrine", "posology"} & tags)
    status = NOT_ESTABLISHED if therapeutic else NOT_ASSESSED
    if not therapeutic:
        notes.append("Descriptive passage; no therapeutic claim detected.")

    return ClaimClassification(
        evidence_class=HISTORICAL_CLAIM,
        scientific_status=status,
        claim_tags=tuple(sorted(tags)),
        notes=tuple(notes),
    )
