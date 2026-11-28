"""PDF and Word (.docx) files of a case analysis report, in English or Urdu.

Built from the saved case, patient and analysis (read by the owner's endpoint) plus, for Urdu,
the machine translation of the AI-written text. Book passages stay in English. The documents
hold the patient's name and ID because the practitioner is exporting their own record; nothing
is stored: the bytes are returned to the browser and forgotten.

PDF: PyMuPDF renders HTML with the Urdu (Nastaleeq) font, so Urdu is shaped and right-to-left.
Word: a minimal OOXML package written with the standard library (no extra dependency).
"""

import html
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from app.ai.rag.report_translation import UrduReport
from app.ai.rag.retrieval import analysis_search_info

EXCERPT_LENGTH = 600
# Arabic-script ranges (Urdu), built from code points so the source stays plain ASCII.
_RANGES = ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))
_A = "".join(f"{chr(a)}-{chr(b)}" for a, b in _RANGES)
ARABIC = re.compile("[" + _A + "]")
# An Urdu run: Arabic-script letters plus the spaces, digits and marks between them.
_MARKS = r"\s\d.,:;()\-" + chr(0x2013) + chr(0x2014) + chr(0x060C) + chr(0x06D4) + chr(0x061F)
URDU_RUN = re.compile("([" + _A + "][" + _A + _MARKS + "]*)")
URDU_FONT = "Jameel Noori Nastaleeq"
FONT_FILE = "JameelNooriNastaleeq.ttf"

EN = {
    "title": "Similia AI - Case analysis report",
    "generated": "Generated",
    "patient": "Patient",
    "identifier": "ID",
    "ageSex": "Age / sex",
    "years": "years",
    "caseId": "Case",
    "signoff": "Practitioner sign-off",
    "signedOff": "Signed off by the practitioner",
    "notSignedOff": "Not signed off - draft analysis",
    "chiefComplaint": "Chief complaint",
    "notRecorded": "Not recorded",
    "urgent": "Urgent concern",
    "cautions": "Take extra care",
    "keyword": "Passages were found by keyword matching, not meaning-based search; some relevant "
    "passages may be missing.",
    "incomplete": "Some evidence comes from partly indexed books",
    "remedies": "Suggested remedies",
    "remedy": "Remedy",
    "confidence": "confidence",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "fits": "Fits",
    "against": "Against",
    "sources": "Sources",
    "noSources": "No source passage is attached.",
    "author": "Author",
    "section": "Section",
    "pdfPage": "PDF page",
    "pdfPages": "PDF pages",
    "partlyIndexed": "from a partly indexed book",
    "bookText": "Book text",
    "aiInterpretation": "AI interpretation",
    "askNext": "Ask next",
    "insufficient": "The knowledge base does not contain enough supporting passages for this "
    "case, so no remedy is suggested.",
    "disclaimer": "Decision support for a qualified practitioner. Not a diagnosis or "
    "prescription. Retrieved historical text is not evidence of clinical efficacy.",
    "model": "Model",
    "method": "Search method",
    "requestedMethod": "Requested search method",
    "mixed": "Some queries used keyword fallback. Other queries used meaning-based search.",
    "female": "Female",
    "male": "Male",
    "other": "Other",
    "unspecified": "Not specified",
}
UR = {
    "title": "سمیلیا اے آئی - کیس کے تجزیے کی رپورٹ",
    "generated": "تیار کرنے کی تاریخ",
    "patient": "مریض",
    "identifier": "شناختی نمبر",
    "ageSex": "عمر / جنس",
    "years": "سال",
    "caseId": "کیس",
    "signoff": "معالج کی توثیق",
    "signedOff": "معالج نے توثیق کر دی ہے",
    "notSignedOff": "ابھی توثیق نہیں ہوئی - مسودہ تجزیہ",
    "chiefComplaint": "بنیادی شکایت",
    "notRecorded": "درج نہیں",
    "urgent": "فوری توجہ طلب نکات",
    "cautions": "خصوصی احتیاط",
    "keyword": "عبارتیں الفاظ کی مطابقت (کی ورڈ میچنگ) سے ملی ہیں، مفہوم پر مبنی تلاش سے نہیں؛ "
    "ممکن ہے کچھ متعلقہ عبارتیں رہ گئی ہوں۔",
    "incomplete": "کچھ شواہد جزوی طور پر انڈیکس کی گئی کتابوں سے ہیں",
    "remedies": "تجویز کردہ ادویات",
    "remedy": "دوا",
    "confidence": "اعتماد",
    "low": "کم",
    "medium": "درمیانہ",
    "high": "زیادہ",
    "fits": "موافق علامات",
    "against": "مخالف علامات",
    "sources": "حوالہ جاتی ذرائع",
    "noSources": "کوئی حوالہ جاتی عبارت منسلک نہیں۔",
    "author": "مصنف",
    "section": "حصہ",
    "pdfPage": "پی ڈی ایف صفحہ",
    "pdfPages": "پی ڈی ایف صفحات",
    "partlyIndexed": "جزوی طور پر انڈیکس شدہ کتاب سے",
    "bookText": "کتابی متن (انگریزی)",
    "aiInterpretation": "اے آئی کی تشریح",
    "askNext": "اگلے سوالات",
    "insufficient": "علمی ذخیرے میں اس کیس کے لیے کافی معاون عبارتیں نہیں ملیں، اس لیے کوئی دوا "
    "تجویز نہیں کی گئی۔",
    "disclaimer": "یہ ایک مستند معالج کے لیے فیصلہ سازی میں معاونت ہے۔ یہ تشخیص یا نسخہ نہیں ہے۔ "
    "حاصل کردہ تاریخی متن علاج کی افادیت کا ثبوت نہیں ہے۔",
    "model": "ماڈل",
    "method": "تلاش کا طریقہ",
    "requestedMethod": "منتخب تلاش کا طریقہ",
    "mixed": "کچھ عبارتیں مفہوم پر مبنی تلاش سے اور کچھ الفاظ کی مطابقت سے ملیں۔",
    "female": "خاتون",
    "male": "مرد",
    "other": "دیگر",
    "unspecified": "نامعلوم",
}
METHOD_NAMES = {
    "en": {"semantic": "Semantic", "keyword": "Keyword", "hybrid": "Hybrid",
           "mixed": "Mixed", "not_run": "Skipped", "unknown": "Unknown"},
    "ur": {"semantic": "مفہوم پر مبنی", "keyword": "کی ورڈ", "hybrid": "ملا جلا",
           "mixed": "مختلف طریقے", "not_run": "تلاش نہیں ہوئی", "unknown": "نامعلوم"},
}


@dataclass
class Block:
    """kind: h1 h2 h3 meta tag li small p banner excerpt foot. ltr: always left-to-right."""

    kind: str
    text: str
    ltr: bool = False


def _remedy_heading(n: int, name: str, L: dict[str, str], level: str, lang: str) -> str:
    """'1. Sulphur (confidence: low)'. In Urdu it starts with an Urdu word so the line reads from
    the right: 'دوا ۱: Sulphur (اعتماد: کم)'."""
    if lang != "ur":
        return f"{n}. {name}   ({L['confidence']}: {level})"
    digits = "".join(chr(0x06F0 + int(d)) for d in str(n))
    return f"{L['remedy']} {digits}: {name}   ({L['confidence']}: {level})"


def _excerpt(text: str) -> str:
    text = text.strip()
    return text[:EXCERPT_LENGTH].rstrip() + "…" if len(text) > EXCERPT_LENGTH else text


def _pages(start: Any, end: Any, L: dict[str, str]) -> str | None:
    if not start:
        return None
    return f"{L['pdfPages']} {start}–{end}" if end and end != start else f"{L['pdfPage']} {start}"


def _pick(english: list[str], translated: list[str] | None) -> list[str]:
    return translated if translated is not None and len(translated) == len(english) else english


def build_blocks(
    case: dict[str, Any],
    patient: dict[str, Any],
    analysis: dict[str, Any],
    lang: str,
    translation: UrduReport | None,
    generated: str,
    cautions: list[str],
) -> list[Block]:
    """The report as an ordered list of blocks (same content as the on-screen report)."""
    L = UR if lang == "ur" else EN
    tr = translation if lang == "ur" else None
    passages = {p["chunk_id"]: p for p in analysis.get("passages") or []}
    incomplete = sorted(
        {p["book_title"] for p in passages.values() if p.get("book_complete") is False}
    )
    retrieval = analysis_search_info(analysis)
    used = retrieval["retrieval_mode"]
    methods = METHOD_NAMES[lang]
    age = patient.get("age_years")
    age_sex = " / ".join(
        x
        for x in (
            f"{age} {L['years']}" if age is not None else None,
            L.get(patient.get("sex") or "unspecified", ""),
        )
        if x
    )
    out: list[Block] = [Block("h1", L["title"])]
    if tr:
        out.append(Block("small", UrduNotice))
    out += [
        Block("meta", f"{L['generated']}: {generated}"),
        Block("meta", f"{L['caseId']}: {case['id'][:8]}", ltr=lang != "ur"),
        Block("meta", f"{L['patient']}: {patient.get('full_name', '')}"),
        Block("meta", f"{L['identifier']}: {patient.get('identifier', '')}"),
        Block("meta", f"{L['ageSex']}: {age_sex}"),
        Block(
            "meta",
            f"{L['signoff']}: "
            f"{L['signedOff'] if case.get('status') == 'signed_off' else L['notSignedOff']}",
        ),
        Block("meta", f"{L['method']}: {methods.get(used, methods['unknown'])}"),
    ]
    requested = retrieval["requested_mode"]
    if requested != used and requested in methods:
        out.append(Block("meta", f"{L['requestedMethod']}: {methods[requested]}"))
    complaint = ((tr.chief_complaint if tr else "") or case.get("chief_complaint", "")).strip()
    out += [Block("h2", L["chiefComplaint"]), Block("p", complaint or L["notRecorded"])]
    red = _pick(list(analysis.get("red_flags") or []), tr.red_flags if tr else None)
    if red:
        out.append(Block("h2", L["urgent"]))
        out += [Block("banner", f) for f in red]
    care = _pick(cautions, tr.cautions if tr else None)
    if care:
        out.append(Block("h2", L["cautions"]))
        out += [Block("li", c) for c in care]
    if used in ("keyword", "mixed"):
        out.append(Block("banner", L["mixed"] if used == "mixed" else L["keyword"]))
    if retrieval["fallback_reason"]:
        out.append(Block("small", retrieval["fallback_reason"], ltr=True))
    if incomplete:
        out.append(Block("banner", f"{L['incomplete']}: {', '.join(incomplete)}"))
    remedies = analysis.get("remedies") or []
    if analysis.get("outcome") == "insufficient_sources" and not remedies:
        out.append(Block("banner", L["insufficient"]))
    if remedies:
        out.append(Block("h2", L["remedies"]))
    for i, r in enumerate(remedies):
        t = tr.remedies[i] if tr and i < len(tr.remedies) else None
        fits = _pick(list(r.get("matching_symptoms") or []), t.matching_symptoms if t else None)
        against = _pick(
            list(r.get("contradicting_symptoms") or []), t.contradicting_symptoms if t else None
        )
        level = L.get(str(r.get("confidence")), str(r.get("confidence")))
        out += [
            Block("h3", _remedy_heading(i + 1, r.get("remedy", ""), L, level, lang)),
            Block("tag", L["aiInterpretation"]),
            Block("p", (t.rationale if t else "") or r.get("rationale", "")),
        ]
        if fits:
            out.append(Block("h3", L["fits"]))
            out += [Block("li", s) for s in fits]
        if against:
            out.append(Block("h3", L["against"]))
            out += [Block("li", s) for s in against]
        out.append(Block("h3", L["sources"]))
        cited = [passages[c] for c in r.get("citations") or [] if c in passages]
        for p in cited:
            out.append(Block("p", p.get("book_title", ""), ltr=True))
            if p.get("book_author"):
                out.append(Block("small", f"{L['author']}: {p['book_author']}", ltr=True))
            if p.get("section_path"):
                out.append(
                    Block("small", f"{L['section']}: {' › '.join(p['section_path'])}", ltr=True)
                )
            page = _pages(p.get("page_start"), p.get("page_end"), L)
            if page:
                out.append(Block("small", page))
            if p.get("book_complete") is False:
                out.append(Block("small", f"({L['partlyIndexed']})"))
            out += [
                Block("tag", L["bookText"]),
                Block("excerpt", _excerpt(p.get("content", "")), ltr=True),
            ]
        if not cited:
            out.append(Block("small", L["noSources"]))
    questions = _pick(
        list(analysis.get("missing_information") or []), tr.missing_information if tr else None
    )
    if questions:
        out.append(Block("h2", L["askNext"]))
        out += [Block("li", q) for q in questions]
    out.append(Block("foot", L["disclaimer"]))
    if lang == "ur":
        out.append(Block("foot", EN["disclaimer"], ltr=True))
    model = analysis.get("model")
    out.append(
        Block(
            "foot",
            f"{L['model']}: {model}. {_date(analysis.get('created_at'))}"
            if model
            else _date(analysis.get("created_at")),
            ltr=lang != "ur",
        )
    )
    return out


UrduNotice = (
    "اے آئی کا مشینی ترجمہ۔ اسے استعمال سے پہلے کسی سے جانچ لیں۔ کتابی عبارتیں اصل انگریزی میں ہیں۔"
)


def _date(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%d %b %Y")
    except ValueError:
        return ""


# ---------------------------------------------------------------------------------------- PDF

CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.35; color: #000; }
h1 { font-size: 17pt; margin: 0 0 6pt 0; border-bottom: 1.5pt solid #000; padding-bottom: 4pt; }
h2 { font-size: 13pt; margin: 12pt 0 3pt 0; border-bottom: 0.5pt solid #444; }
h3 { font-size: 11pt; margin: 8pt 0 2pt 0; }
p { margin: 2pt 0; } li { margin: 1pt 0; }
.meta { margin: 0; } .small { font-size: 9pt; color: #333; margin: 0; }
.tag { font-size: 8.5pt; font-weight: bold; color: #333; margin: 4pt 0 1pt 0; }
.banner { border: 1pt solid #000; padding: 4pt; margin: 4pt 0; font-weight: bold; }
.excerpt { font-family: serif; font-size: 9.5pt; margin: 1pt 0 6pt 0; color: #222; }
.foot { font-size: 8.5pt; color: #333; margin-top: 8pt; }
.ur { font-family: UrduFont; font-size: 13pt; line-height: 2;
  text-align: right; }
.li.ur { margin-right: 14pt; } .li.ltr { margin-left: 14pt; }
h1.ur { font-size: 17pt; } h2.ur { font-size: 14pt; } h3.ur { font-size: 12pt; }
.ltr { text-align: left; font-family: sans-serif; font-size: 10pt;
  line-height: 1.35; }
"""


def _html_for(blocks: list[Block], lang: str) -> str:
    """Urdu pages read from the right.

    Each Urdu block is right-aligned by its own class. A `dir` attribute is NOT used: the
    renderer then flips the alignment back to the left. The reading order inside a line comes from
    its first strong letter, so Urdu blocks are written to start with Urdu text. Bullets are
    real text.
    """
    rtl = lang == "ur"
    parts: list[str] = []
    for b in blocks:
        text = html.escape(b.text)
        cls = "ltr" if (b.ltr or not rtl) else "ur"
        if b.kind in ("h1", "h2", "h3"):
            parts.append(f'<{b.kind} class="{cls}">{text}</{b.kind}>')
        elif b.kind == "li":
            parts.append(f'<p class="li {cls}">&#8226;&nbsp; {text}</p>')
        else:
            parts.append(f'<p class="{b.kind} {cls}">{text}</p>')
    align = "right" if rtl else "left"
    return f'<html><body style="text-align:{align}">' + "".join(parts) + "</body></html>"


def font_dir() -> Path:
    """Where the Urdu font file lives (the web app's fonts folder by default)."""
    from app.core.config import get_settings

    configured = getattr(get_settings(), "urdu_font_dir", "") or ""
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "frontend" / "public" / "fonts"


def render_pdf(blocks: list[Block], lang: str) -> bytes:
    import pymupdf

    css = CSS
    archive = None
    directory = font_dir()
    if (directory / FONT_FILE).exists():
        archive = pymupdf.Archive(str(directory))
        css = f"@font-face {{ font-family: UrduFont; src: url({FONT_FILE}); }}\n" + CSS
    story = pymupdf.Story(html=_html_for(blocks, lang), user_css=css, archive=archive)
    buffer = BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    page = pymupdf.paper_rect("a4")
    area = page + (40, 40, -40, -40)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()


# --------------------------------------------------------------------------------------- DOCX

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _runs(text: str, size_half_pt: int, bold: bool = False, italic: bool = False) -> str:
    """Split text into Urdu (right-to-left, complex script) and other runs."""
    out = []
    for part in URDU_RUN.split(text):
        if not part:
            continue
        urdu = bool(ARABIC.search(part))
        props = []
        if urdu:
            props.append(
                f'<w:rFonts w:cs="{URDU_FONT}" w:ascii="{URDU_FONT}" w:hAnsi="{URDU_FONT}"/>'
            )
        if bold:
            props.append("<w:b/><w:bCs/>")
        if italic:
            props.append("<w:i/>")
        if urdu:
            props.append("<w:rtl/>")
        props.append(
            f'<w:sz w:val="{size_half_pt}"/>'
            f'<w:szCs w:val="{size_half_pt + 4 if urdu else size_half_pt}"/>'
        )
        out.append(
            f"<w:r><w:rPr>{''.join(props)}</w:rPr>"
            f'<w:t xml:space="preserve">{html.escape(part)}</w:t></w:r>'
        )
    return "".join(out)


def _paragraph(b: Block, rtl_doc: bool) -> str:
    rtl = rtl_doc and not b.ltr
    sizes = {
        "h1": 34,
        "h2": 28,
        "h3": 24,
        "meta": 21,
        "tag": 17,
        "small": 18,
        "p": 21,
        "li": 21,
        "banner": 21,
        "excerpt": 19,
        "foot": 17,
    }
    bold = b.kind in ("h1", "h2", "h3", "tag", "banner")
    italic = b.kind == "excerpt"
    ppr = []
    if b.kind == "li":
        ppr.append('<w:ind w:left="360" w:hanging="240"/>')
    if b.kind == "banner":
        ppr.append(
            '<w:pBdr><w:top w:val="single" w:sz="6" w:space="2" w:color="000000"/>'
            '<w:left w:val="single" w:sz="6" w:space="2" w:color="000000"/>'
            '<w:bottom w:val="single" w:sz="6" w:space="2" w:color="000000"/>'
            '<w:right w:val="single" w:sz="6" w:space="2" w:color="000000"/></w:pBdr>'
        )
    ppr.append('<w:spacing w:before="%d" w:after="60"/>' % (200 if b.kind in ("h1", "h2") else 60))
    if rtl:
        ppr.append("<w:bidi/>")
    text = ("•  " + b.text) if b.kind == "li" else b.text
    runs = _runs(text, sizes.get(b.kind, 21), bold, italic)
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{runs}</w:p>"


def render_docx(blocks: list[Block], lang: str) -> bytes:
    rtl_doc = lang == "ur"
    body = "".join(_paragraph(b, rtl_doc) for b in blocks)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{body}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1000" w:right="1000" w:bottom="1000" w:left="1000" '
        'w:header="500" w:footer="500" w:gutter="0"/></w:sectPr></w:body></w:document>'
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml'
        '.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    )
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


# --------------------------------------------------------------------------------- PRESCRIPTION PDF

PRESCRIPTION_CSS = """
body { font-family: sans-serif; font-size: 10pt; line-height: 1.4; color: #111827; }
.rx-header { border-bottom: 2pt solid #0f766e; padding-bottom: 8pt; margin-bottom: 12pt; }
.rx-title { font-size: 18pt; font-weight: bold; color: #0f766e; margin: 0; }
.rx-subtitle {
  font-size: 9pt; color: #4b5563; margin-top: 2pt;
  text-transform: uppercase; letter-spacing: 0.5px;
}
.rx-meta-table {
  width: 100%; border-collapse: collapse; margin-bottom: 12pt;
  background-color: #f9fafb; border: 1pt solid #e5e7eb;
}
.rx-meta-table td { padding: 5pt 8pt; font-size: 9.5pt; vertical-align: top; }
.rx-label {
  font-weight: bold; color: #374151; font-size: 8.5pt;
  text-transform: uppercase; margin-bottom: 1pt;
}
.rx-section { margin-bottom: 11pt; }
.rx-section-title {
  font-size: 10.5pt; font-weight: bold; color: #0f766e;
  border-bottom: 0.5pt solid #cbd5e1; padding-bottom: 2pt;
  margin-bottom: 4pt; text-transform: uppercase;
}
.rx-box {
  border: 1pt solid #e2e8f0; border-radius: 3pt;
  padding: 6pt 8pt; background: #fff; margin-bottom: 6pt;
}
.rx-table { width: 100%; border-collapse: collapse; margin-top: 4pt; }
.rx-table th {
  background-color: #f1f5f9; text-align: left; padding: 5pt 6pt;
  font-size: 8.5pt; text-transform: uppercase;
  border-bottom: 1pt solid #cbd5e1; color: #334155;
}
.rx-table td { padding: 6pt; font-size: 9.5pt; border-bottom: 0.5pt solid #e2e8f0; }
.rx-urgent {
  background-color: #fef2f2; border: 1pt solid #fecaca;
  border-left: 3pt solid #ef4444; padding: 6pt 8pt;
  margin-bottom: 10pt; font-size: 9pt; color: #991b1b;
}
.rx-sig-block { margin-top: 25pt; display: table; width: 100%; }
.rx-sig-cell-left {
  display: table-cell; width: 55%; vertical-align: bottom;
  font-size: 8pt; color: #64748b;
}
.rx-sig-cell-right { display: table-cell; width: 45%; vertical-align: bottom; text-align: right; }
.rx-sig-line { border-top: 1pt solid #334155; width: 150pt; margin-left: auto; margin-bottom: 4pt; }
.rx-disclaimer {
  margin-top: 15pt; border-top: 0.5pt solid #e2e8f0;
  padding-top: 6pt; font-size: 7.5pt; color: #94a3b8; text-align: center;
}
"""


def render_prescription_pdf(
    case: dict[str, Any],
    patient: dict[str, Any],
    review: dict[str, Any],
) -> bytes:
    """Patient-facing clinical prescription PDF.

    Contains patient information, clinical impression / diagnosis, treatment (Rx),
    advice and treating doctor identification. Omits technical Run IDs, search methods,
    AI model details and research passages.
    """
    import pymupdf

    case_id = str(case.get("id", ""))
    rx_ref = f"RX-{case_id[:8].upper()}" if case_id else "RX-RECORD"
    date_str = _date(review.get("signed_at")) or _date(datetime.now(timezone.utc).isoformat())

    patient_name = html.escape(patient.get("full_name") or "Patient")
    identifier = html.escape(patient.get("identifier") or "—")
    age = f"{patient.get('age_years')} Years" if patient.get("age_years") is not None else ""
    sex = html.escape(str(patient.get("sex") or "").capitalize())
    age_sex = " / ".join(filter(None, [age, sex])) or "—"
    # Nothing clinical is ever filled in for the practitioner: an empty field says so.
    def entered(key: str, empty: str = "Not recorded") -> str:
        return html.escape(str(review.get(key) or "").strip() or empty)

    doctor_label = entered("practitioner_name")
    diagnosis = entered("diagnosis")
    decision = review.get("decision", "accepted")
    remedy = entered("chosen_remedy")
    potency = entered("potency")
    dose = entered("dose")
    frequency = entered("frequency")
    duration = entered("duration")
    instructions = entered("instructions", "None recorded")
    urgency_disposition = review.get("urgency_disposition") or ""

    treatment_html = (
        f"""<table class="rx-table">
          <tr>
            <th>Remedy</th>
            <th>Potency</th>
            <th>Dose</th>
            <th>Frequency</th>
            <th>Duration</th>
          </tr>
          <tr>
            <td><strong>{remedy}</strong></td>
            <td>{potency}</td>
            <td>{dose}</td>
            <td>{frequency}</td>
            <td>{duration}</td>
          </tr>
        </table>"""
        if decision != "rejected"
        else "<div class='rx-box'>Analysis rejected. No homeopathic remedy prescribed.</div>"
    )

    include_urgent = review.get("include_urgent_in_pdf") is True
    urgent_html = (
        f"""<div class="rx-urgent">
          <strong>Urgent Clinical Advisory:</strong><br>{html.escape(urgency_disposition)}
        </div>"""
        if (include_urgent and urgency_disposition.strip())
        else ""
    )

    doc_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
</head>
<body>
<div class="rx-header">
  <div class="rx-title">SIMILIA CLINICAL PRESCRIPTION</div>
  <div class="rx-subtitle">Homeopathic Medical Consultation & Care</div>
</div>

<table class="rx-meta-table">
  <tr>
    <td width="50%"><div class="rx-label">Patient Name</div><strong>{patient_name}</strong></td>
    <td width="50%"><div class="rx-label">Identifier / MRN</div><strong>{identifier}</strong></td>
  </tr>
  <tr>
    <td><div class="rx-label">Age / Sex</div>{age_sex}</td>
    <td><div class="rx-label">Date of Issue</div>{date_str}</td>
  </tr>
  <tr>
    <td colspan="2"><div class="rx-label">Treating Practitioner</div>{doctor_label}</td>
  </tr>
</table>

{urgent_html}

<div class="rx-section">
  <div class="rx-section-title">Clinical Impression / Diagnosis</div>
  <div class="rx-box">{diagnosis}</div>
</div>

<div class="rx-section">
  <div class="rx-section-title">Treatment Plan (Rx)</div>
  {treatment_html}
</div>

<div class="rx-section">
  <div class="rx-section-title">Advice & Instructions</div>
  <div class="rx-box">{instructions}</div>
</div>

<div class="rx-sig-block">
  <div class="rx-sig-cell-left">
    Prescription reference: <strong>{rx_ref}</strong><br>
    Finalised by treating practitioner on {date_str}
  </div>
  <div class="rx-sig-cell-right">
    <div class="rx-sig-line"></div>
    <strong>{doctor_label}</strong><br>
    <span style="font-size: 8pt; color: #64748b;">Authorised Clinical Decision</span>
  </div>
</div>

<div class="rx-disclaimer">
  This prescription is issued by the treating doctor following clinical case evaluation.
  Take medicines strictly as directed. Keep out of reach of children. In case of acute
  medical emergencies, seek immediate hospital or specialist medical care.
</div>
</body>
</html>"""

    archive = None
    directory = font_dir()
    if (directory / FONT_FILE).exists():
        archive = pymupdf.Archive(str(directory))
    story = pymupdf.Story(html=doc_html, user_css=PRESCRIPTION_CSS, archive=archive)
    buffer = BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    page = pymupdf.paper_rect("a4")
    area = page + (36, 36, -36, -36)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()
