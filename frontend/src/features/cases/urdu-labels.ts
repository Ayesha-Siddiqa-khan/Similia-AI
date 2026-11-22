import type { SymptomKind } from "./types";

// Same browser setting as the "Also show in Urdu" checkbox on the AI questions.
export const URDU_PREF_KEY = "similia.questions-urdu";

// Fixed Urdu wording for the form (labels, importance levels, quick-add buttons, grey examples).
// These are not AI-written, so they appear instantly and cost nothing.
export const urLabels = {
  symptomOrNote: "علامت یا نوٹ",
  complaint: "شکایت",
  importance: "اہمیت",
  importanceLevels: { 1: "معمولی", 2: "قابلِ ذکر", 3: "اہم / منفرد" } as Record<number, string>,
  notes: "مریض کے اپنے الفاظ / نوٹس",
  addEntry: "اندراج شامل کریں",
  addComplaint: "شکایت شامل کریں",
  nothingYet: "یہاں ابھی کچھ درج نہیں۔ اگر ضرورت نہ ہو تو چھوڑ دیں۔",
  goodAnswer: "اچھا جواب کیسے لکھیں",
  moreDetails: "مزید تفصیل",
  hideDetails: "تفصیل چھپائیں",
  done: "مکمل",
  noAnswer: "ابھی جواب نہیں",
  hideQuestions: "سوالات چھپائیں",
  showQuestions: "سوالات دکھائیں",
  back: "پیچھے",
  next: "آگے",
  skip: "چھوڑیں",
  save: {
    saved: "تمام تبدیلیاں محفوظ", saving: "محفوظ ہو رہا ہے…", idle: "ٹائپ کرتے ہی خودکار محفوظ",
    error: "محفوظ نہیں ہوا؛ اگلی تبدیلی پر دوبارہ کوشش ہوگی",
  } as Record<string, string>,
  kinds: {
    mental: "ذہن اور جذبات", physical_general: "پورے جسم کی (عمومی) علامات", particular: "مخصوص شکایات",
    history: "ماضی کی طبی تاریخ", family: "خاندانی تاریخ", medication: "موجودہ ادویات",
  } as Record<SymptomKind, string>,
  steps: {
    complaint: { title: "بنیادی شکایت", hint: "مریض کو بغیر ٹوکے اپنے الفاظ میں مسئلہ بیان کرنے دیں۔" },
    mental: { title: "ذہن", hint: "مزاج، خوف، دباؤ اور تسلی پر ردعمل۔ منفرد یا شدت سے محسوس ہونے والی علامات سب سے زیادہ وزن رکھتی ہیں۔" },
    general: { title: "پورا جسم", hint: "پورے جسم کی علامات: گرمی یا سردی، پیاس، بھوک، پسند اور ناپسند، نیند، خواب، پسینہ۔" },
    particular: { title: "شکایات", hint: "ہر شکایت کے لیے مقام، احساس، کس چیز سے بڑھتی یا کم ہوتی ہے، اور ساتھ کیا ہوتا ہے لکھیں۔" },
    history: { title: "تاریخ", hint: "ماضی کی بیماریاں، خاندانی تاریخ اور موجودہ ادویات۔" },
    analyze: { title: "تجزیہ", hint: "کیس کا خلاصہ دیکھیں، پھر حوالہ جاتی کتابی عبارتیں اور ممکنہ ادویات حاصل کریں۔" },
  } as Record<string, { title: string; hint: string }>,
  chiefComplaint: "مریض کو کیا مسئلہ ہے؟",
  chiefComplaintExample: "مثال: ”میری عمر 15 سال ہے۔ دو سال سے گھٹنوں کے پیچھے اور کہنیوں پر خارش والی خشک جلد ہے۔ سردیوں میں اور کھجانے سے بڑھ جاتی ہے اور پیلا چپچپا مادہ نکلتا ہے۔“",
  details: {
    location: { label: "کہاں (مقام)", example: "مثلاً گھٹنوں کے پیچھے، دونوں کہنیاں، ہتھیلیاں" },
    sensation: { label: "کیسا محسوس ہوتا ہے", example: "مثلاً جلن، شدید خارش، چبھن، دراڑیں" },
    worse: { label: "کس چیز سے بڑھتا ہے", example: "مثلاً رات، سردی، گرم پانی سے نہانے کے بعد، کھجانے سے" },
    better: { label: "کس چیز سے آرام ملتا ہے", example: "مثلاً گرمائش، تیل لگانے سے، کھلی ہوا، گرمی کا موسم" },
    concomitants: { label: "ساتھ کیا ہوتا ہے", example: "مثلاً خشک جلد، گاڑھا چپچپا مادہ، بے چینی" },
    duration: { label: "کب سے / دورانیہ", example: "مثلاً دو سال سے، پچھلی سردیوں سے" },
  } as Record<string, { label: string; example: string }>,
  labelExamples: {
    mental: "مثلاً چھیڑنے پر چڑچڑاپن",
    physical_general: "مثلاً سردی زیادہ لگتی ہے، گرم کپڑے پسند ہیں",
    particular: "مثلاً ہاتھوں پر جلد کے دانے",
    history: "مثلاً پانچ سال کی عمر میں خسرہ",
    family: "مثلاً والد کو دمہ ہے",
    medication: "مثلاً رات کو سیٹریزین 10 ملی گرام",
  } as Record<SymptomKind, string>,
  notesExamples: {
    mental: "مکمل جملوں میں لکھیں۔ مثال: ”وہ شام کو تنگ کیے جانے پر چڑچڑی ہو جاتی ہے اور اکیلا رہنا چاہتی ہے۔“",
    physical_general: "مکمل جملوں میں لکھیں۔ مثال: ”اسے جلدی سردی لگتی ہے، ٹھنڈا پانی بہت پیتی ہے، اور خارش کی وجہ سے نیند خراب رہتی ہے۔“",
    particular: "مکمل جملوں میں لکھیں۔ مثال: ”خارش رات کو اور گرم پانی سے نہانے کے بعد سب سے زیادہ ہوتی ہے؛ کھجانے سے گاڑھا چپچپا مادہ نکلتا ہے۔“",
    history: "مثال: ”پانچ سال کی عمر میں خسرہ ہوا اور بچپن میں بار بار نزلہ رہا۔ ایگزیما تیرہ سال کی عمر میں شروع ہوا۔“",
    family: "مثال: ”والد کو دمہ اور خالہ کو جلد کی الرجی ہے۔“",
    medication: "مثال: ”خارش زیادہ ہو تو رات کو اینٹی ہسٹامین لیتی ہے۔ گریفائٹس سی ایم تین چار بار، چھ ماہ کے وقفے سے لی۔“",
  } as Record<SymptomKind, string>,
  presets: {
    "Fears": "خوف", "Anger / irritability": "غصہ / چڑچڑاپن", "Anxiety": "بے چینی / فکر", "Grief or loss": "غم یا نقصان",
    "Mood and temperament": "مزاج اور طبیعت", "Company or solitude": "ساتھ یا تنہائی", "Consolation": "تسلی",
    "Thermal state (hot / chilly)": "گرمی / سردی کی کیفیت", "Thirst": "پیاس", "Appetite": "بھوک", "Food desires": "کھانے کی خواہش",
    "Food aversions": "کھانوں سے نفرت", "Sleep": "نیند", "Dreams": "خواب", "Perspiration": "پسینہ", "Stool": "پاخانہ",
    "Urine": "پیشاب", "Menses": "ماہواری",
  } as Record<string, string>,
};
