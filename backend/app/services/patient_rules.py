"""Age-based safeguards for children. Pure functions: no database, no AI."""

from datetime import date
from typing import Any

MINOR_AGE = 18
INFANT_AGE = 1

GUARDIAN_REQUIRED = (
    "Patients under 18 need a guardian's name and relationship. "
    "Record who gave consent on the patient's behalf."
)
INFANT_FLAG = (
    "Infant under 1 year: urgency must be assessed in person. "
    "Do not rely on this tool for the decision to wait."
)
MINOR_CAUTION = (
    "Paediatric patient: choose remedy and any dosing yourself, in person, with the guardian. "
    "Retrieved texts were written mostly for adults."
)


def age_in_years(patient: dict[str, Any], today: date | None = None) -> float | None:
    """Age from the date of birth when known, otherwise from the stated years. Never guessed."""
    today = today or date.today()
    born = patient.get("date_of_birth")
    if isinstance(born, str):
        try:
            born = date.fromisoformat(born[:10])
        except ValueError:
            born = None
    if isinstance(born, date):
        return max(0.0, (today - born).days / 365.25)
    years = patient.get("age_years")
    if isinstance(years, int) and not isinstance(years, bool):
        return float(years)
    return None


def is_minor(patient: dict[str, Any], today: date | None = None) -> bool:
    age = age_in_years(patient, today)
    return age is not None and age < MINOR_AGE


def is_infant(patient: dict[str, Any], today: date | None = None) -> bool:
    age = age_in_years(patient, today)
    return age is not None and age < INFANT_AGE


def guardian_missing(patient: dict[str, Any]) -> bool:
    """True when a minor has no guardian name and relationship."""
    return is_minor(patient) and not (
        (patient.get("guardian_name") or "").strip()
        and (patient.get("guardian_relationship") or "").strip()
    )


def cautions(patient: dict[str, Any]) -> list[str]:
    return [MINOR_CAUTION] if is_minor(patient) else []
