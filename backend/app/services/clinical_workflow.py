"""Owner-scoped workflow persistence and immutable report presentation."""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from postgrest import APIError

from app.services.report_files import Block

ATTEMPTS = "clinical_workflow_attempts"
REPORTS = "clinical_workflow_reports"
IMAGES = "clinical_images"
FINDINGS = "clinical_image_findings"
IMAGE_CONSENTS = "clinical_image_consents"
BUCKET = "clinical-images"


class ClinicalStore:
    def __init__(self, db: Any, owner: str) -> None:
        self.db = db
        self.owner = owner

    def query(self, table: str) -> Any:
        return self.db.table(table).select("*").eq("practitioner_id", self.owner)

    def reports(self, case_id: str) -> list[dict[str, Any]]:
        return (
            self.query(REPORTS).eq("case_id", case_id).order("created_at", desc=True).execute().data
        )

    def report(self, case_id: str, report_id: str) -> dict[str, Any]:
        rows = self.query(REPORTS).eq("case_id", case_id).eq("id", report_id).execute().data
        if not rows:
            raise HTTPException(404, "Report unavailable")
        return rows[0]

    def begin(self, case_id: str, stage: str, request_id: str) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        self.db.table(ATTEMPTS).update({"status": "failed", "error_stage": "expired"}).eq(
            "practitioner_id",
            self.owner,
        ).eq("case_id", case_id).eq("status", "running").lt("created_at", cutoff).execute()
        try:
            return (
                self.db.table(ATTEMPTS)
                .insert(
                    {
                        "case_id": case_id,
                        "stage": stage,
                        "request_id": request_id,
                        "practitioner_id": self.owner,
                    }
                )
                .execute()
                .data[0]
            )
        except APIError as error:
            if error.code != "23505":
                raise
        rows = (
            self.query(ATTEMPTS).eq("case_id", case_id).eq("request_id", request_id).execute().data
        )
        if rows and rows[0]["status"] == "done" and rows[0]["stage"] == stage:
            return rows[0]
        raise HTTPException(409, "Another request is active or this request already ended.")

    def fail(self, attempt_id: str, stage: str) -> None:
        self.db.table(ATTEMPTS).update({"status": "failed", "error_stage": stage}).eq(
            "practitioner_id",
            self.owner,
        ).eq("id", attempt_id).eq("status", "running").execute()

    def complete(self, attempt: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        attempt_id = attempt["id"]
        if attempt["status"] == "done":
            rows = self.query(REPORTS).eq("attempt_id", attempt_id).execute().data
            if rows:
                return rows[0]
            raise HTTPException(409, "Completed report is unavailable")
        try:
            response = (
                self.db.rpc(
                    "complete_clinical_report",
                    {
                        "report": {
                            **report,
                            "attempt_id": attempt_id,
                            "practitioner_id": self.owner,
                        }
                    },
                )
                .execute()
                .data
            )
        except APIError as error:
            if error.code == "PT409":
                raise HTTPException(409, "The case changed. Refresh and try again.") from None
            raise
        return response[0] if isinstance(response, list) else response

    def images(self, case_ids: list[str], active: bool = True) -> list[dict[str, Any]]:
        query = self.query(IMAGES).in_("case_id", case_ids)
        if active:
            query = query.eq("state", "active")
        return query.order("captured_on", desc=True).order("created_at", desc=True).execute().data

    def consent(self, patient_id: str, scope: str) -> str | None:
        rows = (
            self.query(IMAGE_CONSENTS)
            .eq("patient_id", patient_id)
            .eq("scope", scope)
            .order(
                "created_at",
                desc=True,
            )
            .order("id", desc=True)
            .limit(1)
            .execute()
            .data
        )
        return rows[0]["id"] if rows and rows[0]["granted"] else None


TITLES = {
    "en": {
        "research": "RAG Research Report",
        "assessment": "AI Assessment and Draft Prescription",
        "final": "Doctor’s Final Clinical Report and Prescription",
    },
    "ur": {
        "research": "حوالہ جاتی تحقیق کی رپورٹ",
        "assessment": "اے آئی کا طبی جائزہ اور مجوزہ نسخہ",
        "final": "معالج کی حتمی طبی رپورٹ اور نسخہ",
    },
}
DRAFT = "AI-Generated Draft — Not Clinician Approved"
URGENT = "Urgent concern"
LABELS = {
    URGENT: "فوری توجہ طلب نکات",
    "Patient": "مریض",
    "Created": "تیاری کی تاریخ",
    "Version": "ورژن",
    "Status": "حیثیت",
    "Signed": "دستخط شدہ",
    "Case summary": "کیس کا خلاصہ",
    "Clinical assessment": "طبی جائزہ",
    "Care and follow-up": "نگہداشت اور اگلا معائنہ",
    "Prescription": "نسخہ",
    "Sources": "حوالہ جاتی ذرائع",
    "Author": "مصنف",
    "Research source": "تحقیقی رپورٹ",
    "Assessment source": "جائزے کی رپورٹ",
    "Decision": "فیصلہ",
    "Source version": "اصل رپورٹ کا ورژن",
    "Signer": "دستخط کنندہ",
}
STATUS = {
    "research": "تحقیق",
    "draft": "مسودہ",
    "reviewed": "جائزہ شدہ",
    "signed": "دستخط شدہ",
    "translation": "ترجمہ",
}
COVERAGE = {
    "skipped": "Library search was skipped pending practitioner assessment of urgency.",
    "no_queries": "The analysis produced no usable search queries.",
    "query_unavailable": "Query preparation was unavailable. The urgent handoff is saved.",
    "search_failed": "Library search was unavailable. The urgent handoff is saved.",
    "no_hits": "No passages were found for these queries.",
    "partial": "Retrieval coverage is partial. Check missing categories and unindexed sections.",
    "retrieved": "Passages were retrieved from both library categories.",
}


def report_blocks(report: dict[str, Any]) -> list[Block]:
    p = report["payload"]
    locale = report["locale"]
    stage = report["stage"]
    translated = p.get("translated_blocks")
    if translated is not None:
        content = [Block(**entry) for entry in translated]
    else:
        content = _report_content(stage, p, locale)

    def label(key: str) -> str:
        return LABELS.get(key, key) if locale == "ur" else key

    def identifier(key: str, value: str) -> list[Block]:
        if locale == "ur":
            return [Block("meta", label(key)), Block("meta", f"ID {value}", ltr=True)]
        return [Block("meta", f"{key} · {value}")]

    def timestamp(key: str, value: str) -> list[Block]:
        stamp = datetime.fromisoformat(value).astimezone(timezone.utc)
        if locale == "ur":
            return [
                Block("meta", label(key)),
                Block("meta", stamp.strftime("UTC %Y-%m-%d %H:%M"), ltr=True),
            ]
        return [Block("meta", f"{key} · {stamp:%d %b %Y, %H:%M UTC}")]

    status = report["status"]
    decision = label("Status") + " · " + (STATUS[status] if locale == "ur" else status)
    details = [
        Block("h1", TITLES[locale][stage]),
        *identifier("Version", report["id"]),
        *timestamp("Created", report["created_at"]),
        Block("meta", decision),
        Block("meta", f"{label('Patient')} · {p['patient_label']}"),
    ]
    if report.get("source_id"):
        key = (
            "Research source"
            if stage == "assessment" and status != "translation"
            else "Source version"
        )
        details.extend(identifier(key, report["source_id"]))
    if report.get("model"):
        details.append(
            Block("meta", f"{label('Author')} · {report['provider']} / {report['model']}")
        )
    elif stage != "final":
        details.append(Block("meta", f"{label('Author')} · Similia AI"))
    if report.get("signed_at"):
        details.extend(timestamp("Signed", report["signed_at"]))
        if report.get("signer_id"):
            details.extend(identifier("Signer", report["signer_id"]))
    return details + content


def _report_content(stage: str, p: dict[str, Any], locale: str) -> list[Block]:
    result = []
    if stage == "assessment":
        result.append(Block("banner", DRAFT, True))
    if p.get("urgent_findings"):
        result.append(Block("h2", LABELS[URGENT] if locale == "ur" else URGENT))
        result += [Block("banner", flag) for flag in p["urgent_findings"]]
        if p.get("handoff"):
            result.append(Block("banner", p["handoff"]))
        if p.get("disposition"):
            result.append(Block("p", p["disposition"]))
    result += [Block("banner", note) for note in p.get("safety_notes") or []]
    if stage == "final":
        for key, heading in (
            ("author", "Author"),
            ("decision", "Decision"),
            ("case_summary", "Case summary"),
            ("assessment", "Clinical assessment"),
            ("care_plan", "Care and follow-up"),
            ("prescription", "Prescription"),
            ("research_id", "Research source"),
            ("assessment_id", "Assessment source"),
        ):
            if p.get(key):
                result += [Block("h2", LABELS.get(heading, heading) if locale == "ur" else heading)]
                result.append(Block("p", p[key], ltr=key in {"research_id", "assessment_id"}))
        return result
    result += [
        Block("h2", "Case summary"),
        *[Block("p", line) for line in p["case_summary"].splitlines() if line],
    ]
    if stage == "research":
        result += [Block("h2", "Library search"), Block("p", COVERAGE[p["coverage"]])]
        result.append(Block("p", "Requested method · " + p["requested_mode"]))
        for search in p["searches"]:
            result.append(
                Block(
                    "small",
                    f"{search['query']} · {search['category']} · "
                    f"{search['used']} · {search['hits']} results",
                )
            )
            if search["fallback_reason"]:
                result.append(Block("small", search["fallback_reason"]))
    elif p.get("evidence_status") != "verified_citations":
        explanations = {
            "search_unavailable": "The clinical guideline catalog could not be searched.",
            "interpretation_unavailable": "The AI provider could not interpret the excerpts.",
        }
        result.append(
            Block(
                "banner",
                explanations.get(
                    p.get("evidence_status"),
                    "Clinical guidance unavailable from the approved catalog.",
                ),
            )
        )
    for n, item in enumerate(p.get("associations", [])):
        role = "Leading historical association" if n == 0 else "Alternative historical association"
        result += [Block("h2", f"{role} · {item['name']}"), Block("p", item["interpretation"])]
        for quote in item["citations"] if stage == "research" else []:
            result.append(
                Block(
                    "excerpt",
                    f"{quote['source']} · {quote['relation']} · {quote['text']}",
                    ltr=True,
                )
            )
    for claim in p.get("claims", []):
        result += [
            Block("h2", claim["topic"].replace("_", " ").capitalize()),
            Block("p", f"{claim['consideration']} [{claim['citation']}]"),
            Block("p", claim["uncertainty"]),
            Block("excerpt", claim["quotation"], ltr=True),
        ]
    if p.get("missing_information"):
        result += [Block("h2", "Missing information")]
        result += [Block("li", text) for text in p["missing_information"]]
    if p.get("sources") or p.get("guidelines"):
        result.append(Block("h2", "Sources"))
    for passage in p.get("sources", []):
        section = " › ".join(passage["section_path"]) or passage["section_heading"]
        start, end = passage["page_start"], passage["page_end"]
        pages = f"{start}–{end}" if end and end != start else start
        result += [
            Block("h3", f"{passage['reference']} · {passage['book_title']}", ltr=True),
            Block(
                "small",
                f"{passage['book_author'] or 'Author unavailable'} · "
                f"{section or 'Section unavailable'} · PDF page {pages or 'unavailable'}"
                + ("" if passage["book_complete"] else " · Index coverage partial"),
                ltr=True,
            ),
            Block("excerpt", passage["content"], ltr=True),
        ]
    for guide in p.get("guidelines", []):
        result += [
            Block("h3", f"{guide['reference']} · {guide['title']}", ltr=True),
            Block(
                "small", f"{guide['publisher']} · {guide['edition']} · {guide['section']}", ltr=True
            ),
            Block("small", guide["source_url"], ltr=True),
        ]
    result.append(Block("foot", "Historical literature is not evidence of clinical effectiveness."))
    return result
