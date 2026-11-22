import { describe, expect, it } from "vitest";
import { answeredCount, answerText, askedQuestions, isAnswered, questionNotes, toSavePayload } from "./case-draft";
import type { Symptom } from "./types";

const entry = (over: Partial<Symptom>): Symptom => ({ kind: "particular", label: "", weight: 2, ...over });

describe("toSavePayload", () => {
  it("keeps an entry that has notes but no title, with a title taken from what was written", () => {
    const [saved] = toSavePayload([entry({ notes: "Itching is worst at night and after a hot bath." })]);
    expect(saved.label).toBe("Itching is worst at night and after a hot bath.");
    expect(saved.notes).toContain("worst at night");
  });
  it("keeps an entry that only has a detail box filled in", () => {
    const [saved] = toSavePayload([entry({ worse: "winter" })]);
    expect(saved.label).toBe("winter");
  });
  it("uses the question as the title of an untitled question card", () => {
    const [saved] = toSavePayload([entry({ notes: "Q: When did it start?\nA: Two years ago" })]);
    expect(saved.label).toBe("When did it start?");
  });
  it("falls back to a plain title and skips only entries with nothing in them", () => {
    expect(toSavePayload([entry({ label: "   " }), entry({ notes: "  " })])).toEqual([]);
    expect(toSavePayload([entry({ label: "Fear", weight: 3 })])[0]).toMatchObject({ label: "Fear", weight: 3 });
  });
  it("never sends browser-only fields", () => {
    const [saved] = toSavePayload([entry({ label: "Thirst", key: "k1", id: "s1", hint: "example", hint_ur: "مثال" })]);
    expect(Object.keys(saved)).not.toContain("key");
    expect(Object.keys(saved)).not.toContain("hint");
    expect(Object.keys(saved)).not.toContain("id");
  });
  it("shortens a long fallback title to fit the 300 character limit", () => {
    const [saved] = toSavePayload([entry({ notes: "x".repeat(900) })]);
    expect(saved.label.length).toBeLessThanOrEqual(60);
  });
});

describe("answers and duplicates", () => {
  it("builds question notes with an empty answer line, and Urdu only when asked", () => {
    expect(questionNotes({ question: "Where?", question_ur: "کہاں؟" }, false)).toBe("Q: Where?\nA: ");
    expect(questionNotes({ question: "Where?", question_ur: "کہاں؟" }, true)).toBe("Q: Where?\nکہاں؟\nA: ");
  });
  it("reads the answer after A:", () => {
    expect(answerText(entry({ notes: "Q: Where?\nA:  Behind the knees " }))).toBe("Behind the knees");
    expect(answerText(entry({ notes: "Q: Where?\nA: " }))).toBe("");
  });
  it("does not count an unanswered question card as a finding", () => {
    const asked = entry({ label: "Discharge", notes: "Q: What colour?\nA: " });
    const answered = entry({ label: "Discharge", notes: "Q: What colour?\nA: Yellow" });
    const detailed = entry({ label: "Discharge", notes: "Q: What colour?\nA: ", sensation: "sticky" });
    expect(isAnswered(asked)).toBe(false);
    expect(isAnswered(answered)).toBe(true);
    expect(isAnswered(detailed)).toBe(true);
    expect(answeredCount([asked, answered, entry({ label: "Fear" })])).toBe(2);
  });
  it("lists questions already added, so they are not offered twice", () => {
    expect(askedQuestions([entry({ notes: "Q: When?\nA: now" }), entry({ label: "x" }), entry({ notes: "Q: Where?\nکہاں؟\nA: " })])).toEqual(["When?", "Where?"]);
  });
});
