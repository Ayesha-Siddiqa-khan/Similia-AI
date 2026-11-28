import type { Sex } from "./types";

/** Fixed headings and labels of the printable report, in English and in Urdu (not AI-written). */
export interface ReportLabels {
  title: string; generated: string; patient: string; identifier: string; ageSex: string; years: string; caseId: string;
  signoff: string; signedOff: string; notSignedOff: string; chiefComplaint: string; notRecorded: string;
  urgent: string; cautions: string; keyword: string; incomplete: string; remedies: string; confidence: string;
  confidenceLevels: Record<"low" | "medium" | "high", string>; fits: string; against: string; sources: string; noSources: string;
  author: string; section: string; pdfPage: string; pdfPages: string; partlyIndexed: string; bookText: string; aiInterpretation: string;
  askNext: string; insufficient: string; disclaimer: string; model: string; sexes: Record<Sex, string>;
}

export const enReport: ReportLabels = {
  title: "Similia AI - Case analysis report", generated: "Generated", patient: "Patient", identifier: "ID", ageSex: "Age / sex", years: "years", caseId: "Case",
  signoff: "Practitioner sign-off", signedOff: "Signed off by the practitioner", notSignedOff: "Not signed off - draft analysis",
  chiefComplaint: "Chief complaint", notRecorded: "Not recorded", urgent: "Urgent concern", cautions: "Take extra care",
  keyword: "Passages were found by keyword matching, not meaning-based search; some relevant passages may be missing.",
  incomplete: "Some evidence comes from partly indexed books", remedies: "Suggested remedies", confidence: "confidence",
  confidenceLevels: { low: "low", medium: "medium", high: "high" }, fits: "Fits", against: "Against", sources: "Sources", noSources: "No source passage is attached.",
  author: "Author", section: "Section", pdfPage: "PDF page", pdfPages: "PDF pages", partlyIndexed: "from a partly indexed book", bookText: "Book text", aiInterpretation: "AI interpretation",
  askNext: "Ask next", insufficient: "The knowledge base does not contain enough supporting passages for this case, so no remedy is suggested.",
  disclaimer: "Decision support for a qualified practitioner. Not a diagnosis or prescription. Retrieved historical text is not evidence of clinical efficacy.",
  model: "Model", sexes: { female: "Female", male: "Male", other: "Other", unspecified: "Not specified" },
};

export const urReport: ReportLabels = {
  title: "سمیلیا اے آئی - کیس کے تجزیے کی رپورٹ", generated: "تیار کرنے کی تاریخ", patient: "مریض", identifier: "شناختی نمبر", ageSex: "عمر / جنس", years: "سال", caseId: "کیس",
  signoff: "معالج کی توثیق", signedOff: "معالج نے توثیق کر دی ہے", notSignedOff: "ابھی توثیق نہیں ہوئی - مسودہ تجزیہ",
  chiefComplaint: "بنیادی شکایت", notRecorded: "درج نہیں", urgent: "فوری توجہ طلب نکات", cautions: "خصوصی احتیاط",
  keyword: "عبارتیں الفاظ کی مطابقت (کی ورڈ میچنگ) سے ملی ہیں، مفہوم پر مبنی تلاش سے نہیں؛ ممکن ہے کچھ متعلقہ عبارتیں رہ گئی ہوں۔",
  incomplete: "کچھ شواہد جزوی طور پر انڈیکس کی گئی کتابوں سے ہیں", remedies: "تجویز کردہ ادویات", confidence: "اعتماد",
  confidenceLevels: { low: "کم", medium: "درمیانہ", high: "زیادہ" }, fits: "موافق علامات", against: "مخالف علامات", sources: "حوالہ جاتی ذرائع", noSources: "کوئی حوالہ جاتی عبارت منسلک نہیں۔",
  author: "مصنف", section: "حصہ", pdfPage: "پی ڈی ایف صفحہ", pdfPages: "پی ڈی ایف صفحات", partlyIndexed: "جزوی طور پر انڈیکس شدہ کتاب سے", bookText: "کتابی متن (انگریزی)", aiInterpretation: "اے آئی کی تشریح",
  askNext: "اگلے سوالات", insufficient: "علمی ذخیرے میں اس کیس کے لیے کافی معاون عبارتیں نہیں ملیں، اس لیے کوئی دوا تجویز نہیں کی گئی۔",
  disclaimer: "یہ ایک مستند معالج کے لیے فیصلہ سازی میں معاونت ہے۔ یہ تشخیص یا نسخہ نہیں ہے۔ حاصل کردہ تاریخی متن علاج کی افادیت کا ثبوت نہیں ہے۔",
  model: "ماڈل", sexes: { female: "خاتون", male: "مرد", other: "دیگر", unspecified: "نامعلوم" },
};
