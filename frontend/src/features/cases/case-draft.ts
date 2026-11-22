import type { Symptom } from "./types";

export interface Draft { complaint: string; symptoms: Symptom[] }

/** The backend refuses a case with more entries than this (MAX_SYMPTOMS in backend schemas/cases.py). */
export const MAX_SYMPTOMS = 80;

const detailValues = (s: Symptom) => [s.location, s.sensation, s.better, s.worse, s.concomitants, s.duration];
const hasDetails = (s: Symptom) => detailValues(s).some((value) => (value ?? "").trim());
const hasContent = (s: Symptom) => hasDetails(s) || (s.notes ?? "").trim() !== "";

/** The question text of a card made from an AI question ("Q: ..."), or null for other cards. */
function questionLine(notes?: string | null): string | null {
  const match = /^\s*Q:\s*(.+)$/m.exec(notes ?? "");
  return match ? match[1].trim() : null;
}

/** The text the doctor wrote after "A:" (or all notes for a card that is not question based). */
export function answerText(s: Symptom): string {
  const notes = (s.notes ?? "").trim();
  const at = notes.lastIndexOf("A:");
  return (at >= 0 ? notes.slice(at + 2) : notes).trim();
}

/** Notes for a card made from an AI question: the question (and its Urdu), then an empty answer line. */
export const questionNotes = (q: { question: string; question_ur?: string }, urdu: boolean) =>
  `Q: ${q.question}${urdu && q.question_ur ? `\n${q.question_ur}` : ""}\nA: `;

/** Questions already added to the case, so the same one is not offered twice (and is offered again if its card is deleted). */
export const askedQuestions = (symptoms: Symptom[]): string[] =>
  symptoms.flatMap((s) => { const q = questionLine(s.notes); return q ? [q] : []; });

/** A question card with no answer yet is not a finding; every other card with a title or content is. */
export function isAnswered(s: Symptom): boolean {
  if (questionLine(s.notes) !== null) return answerText(s) !== "" || hasDetails(s);
  return s.label.trim() !== "" || hasContent(s);
}
export const answeredCount = (symptoms: Symptom[]) => symptoms.filter(isAnswered).length;

/** A title for an entry whose title box was left empty, so what the doctor wrote is never dropped. */
function fallbackLabel(s: Symptom): string {
  const firstLine = (s.notes ?? "").split("\n").map((line) => line.replace(/^\s*Q:\s*/i, "").trim()).find(Boolean);
  const text = firstLine ?? detailValues(s).map((value) => (value ?? "").trim()).find(Boolean) ?? "";
  return text ? text.slice(0, 60) : "Untitled entry";
}

/**
 * What is sent to the server. An entry with no title but with written content is kept (with a
 * fallback title); a completely empty entry is skipped. Browser-only fields (key, hint) are left out.
 */
export function toSavePayload(symptoms: Symptom[]) {
  return symptoms.flatMap((s) => {
    const label = s.label.trim();
    if (!label && !hasContent(s)) return [];
    return [{
      kind: s.kind, label: label || fallbackLabel(s), location: s.location, sensation: s.sensation, better: s.better,
      worse: s.worse, concomitants: s.concomitants, duration: s.duration, notes: s.notes, weight: s.weight,
    }];
  });
}
