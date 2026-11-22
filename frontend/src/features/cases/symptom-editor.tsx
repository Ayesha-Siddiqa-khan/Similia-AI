"use client";

import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight, Plus, Trash2 } from "lucide-react";
import { AutoTextarea } from "@/components/auto-textarea";
import { Badge } from "@/components/ui";
import { useLocalPref } from "@/lib/use-local-pref";
import { Bi, both } from "./bilingual";
import { answerText, MAX_SYMPTOMS } from "./case-draft";
import { newKey } from "./symptom-key";
import type { Symptom, SymptomKind } from "./types";
import { URDU_PREF_KEY, urLabels } from "./urdu-labels";
import { MicButton } from "./voice-input";

export const kindLabel: Record<SymptomKind, string> = {
  mental: "Mind and emotions", physical_general: "Whole-body (general) symptoms", particular: "Particular complaints",
  history: "Past medical history", family: "Family history", medication: "Current medication",
};

// Quick-add prompts following the usual homeopathic case-taking order.
const presets: Partial<Record<SymptomKind, string[]>> = {
  mental: ["Fears", "Anger / irritability", "Anxiety", "Grief or loss", "Mood and temperament", "Company or solitude", "Consolation"],
  physical_general: ["Thermal state (hot / chilly)", "Thirst", "Appetite", "Food desires", "Food aversions", "Sleep", "Dreams", "Perspiration", "Stool", "Urine", "Menses"],
};

const weights = [{ value: 1, label: "Minor" }, { value: 2, label: "Notable" }, { value: 3, label: "Key / peculiar" }];
// Each box shows a grey example so it is clear how much detail helps.
const detailFields = [
  ["location", "Where (location)", "e.g. behind the knees, both elbows, palms"],
  ["sensation", "What it feels like", "e.g. burning, intense itching, stinging, cracks"],
  ["worse", "Worse from", "e.g. night, winter, after a hot bath, scratching"],
  ["better", "Better from", "e.g. warmth, applying oil, open air, summer"],
  ["concomitants", "Accompanied by", "e.g. dry skin, thick sticky discharge, restlessness"],
  ["duration", "Since when / duration", "e.g. 2 years, since last winter"],
] as const;
const labelExamples: Record<SymptomKind, string> = {
  mental: "e.g. Irritable when disturbed", physical_general: "e.g. Chilly, wants warm clothes", particular: "e.g. Skin eruption on the hands",
  history: "e.g. Measles at age 5", family: "e.g. Father has asthma", medication: "e.g. Cetirizine 10 mg at night",
};
const notesExamples: Record<SymptomKind, string> = {
  mental: "Write in full sentences. Example: “She gets irritable when disturbed, mostly in the evening, and wants to be left alone.”",
  physical_general: "Write in full sentences. Example: “She feels cold easily, is very thirsty for cold water, and sleeps badly because of itching.”",
  particular: "Write in full sentences. Example: “The itching is worst at night and after a hot bath; scratching makes a thick, sticky fluid come out.”",
  history: "Example: “Had measles at age 5 and frequent colds in childhood. Eczema began at age 13.”",
  family: "Example: “Her father has asthma and her aunt has skin allergies.”",
  medication: "Example: “Takes an antihistamine at night when the itching is bad. Used Graphites CM 3-4 times, six months apart.”",
};

const keyOf = (s: Symptom, index: number) => s.key ?? s.id ?? `i${index}`;
const isBlank = (s: Symptom) => !s.label.trim() && !(s.notes ?? "").trim();
// A card made from an AI question starts with "Q:"; its details stay hidden until asked for.
const fromQuestion = (s: Symptom) => !!s.hint || (s.notes ?? "").startsWith("Q:");
/**
 * Cards for one kind of finding. The newest card is at the top and open (question and answer only);
 * earlier cards fold into a one-line summary, so the doctor never has to scroll far.
 */
export function SymptomEditor({ kind, symptoms, onChange, disabled }: { kind: SymptomKind; symptoms: Symptom[]; onChange: (next: Symptom[]) => void; disabled: boolean }) {
  const [urduPref] = useLocalPref(URDU_PREF_KEY, "0");
  const urdu = urduPref === "1";
  const entries = symptoms.map((symptom, index) => ({ symptom, index })).filter((e) => e.symptom.kind === kind);
  const hasDetails = kind !== "history" && kind !== "family" && kind !== "medication";

  // When a card is added, the new one opens and every manual open/close choice is reset.
  const [seenCount, setSeenCount] = useState(entries.length);
  const [justAdded, setJustAdded] = useState(false);
  const [openState, setOpenState] = useState<Record<string, boolean>>({});
  const [detailState, setDetailState] = useState<Record<string, boolean>>({});
  if (entries.length !== seenCount) {
    setSeenCount(entries.length);
    setJustAdded(entries.length > seenCount);
    if (entries.length > seenCount) setOpenState({});
  }
  const newest = entries.length ? entries[entries.length - 1] : null;
  const newestKey = newest ? keyOf(newest.symptom, newest.index) : null;
  const isOpen = (s: Symptom, k: string) => openState[k] ?? ((justAdded && k === newestKey) || isBlank(s));
  const detailsOpen = (s: Symptom, k: string) => detailState[k] ?? !fromQuestion(s);
  useEffect(() => {
    if (justAdded && newestKey) document.getElementById(`card-${newestKey}`)?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [justAdded, newestKey]);

  const atLimit = symptoms.length >= MAX_SYMPTOMS;
  const add = (label = "") => { if (!atLimit) onChange([...symptoms, { kind, label, weight: 2, key: newKey() }]); };
  const update = (index: number, patch: Partial<Symptom>) => onChange(symptoms.map((s, i) => i === index ? { ...s, ...patch } : s));
  const remove = (index: number) => onChange(symptoms.filter((_, i) => i !== index));
  const weightLabel = (w: number) => weights.find((x) => x.value === w)?.label ?? "";
  const addButton = !disabled && <button type="button" className="button secondary" disabled={atLimit} onClick={() => add()}><Plus size={16} />{kind === "particular" ? <Bi en="Add complaint" ur={urLabels.addComplaint} show={urdu} /> : <Bi en="Add entry" ur={urLabels.addEntry} show={urdu} />}</button>;
  const trash = (symptom: Symptom, index: number) => <button type="button" className="icon-button" aria-label={`Remove ${symptom.label || "symptom"}`} onClick={() => remove(index)}><Trash2 size={16} /></button>;

  return (
    <div className="symptom-editor">
      {!disabled && presets[kind] && <div className="chips" aria-label="Quick add">{presets[kind]!.map((label) => <button type="button" className="chip" key={label} disabled={atLimit} onClick={() => add(label)}>+ <Bi en={label} ur={urLabels.presets[label] ?? ""} show={urdu && !!urLabels.presets[label]} /></button>)}</div>}
      {addButton}
      {atLimit && !disabled && <p className="field-error" role="alert">This case has the maximum of 80 entries. Remove entries you do not need before adding more.</p>}
      {entries.length === 0 && <p className="muted">Nothing recorded here yet. Use &ldquo;Skip&rdquo; if it does not apply.{urdu && <> <bdi className="urdu-inline" lang="ur" dir="rtl">{urLabels.nothingYet}</bdi></>}</p>}
      {[...entries].reverse().map(({ symptom, index }) => {
        const k = keyOf(symptom, index);
        if (!isOpen(symptom, k)) {
          const answer = answerText(symptom);
          return (
            <div className="symptom-collapsed" key={k}>
              <button type="button" className="collapsed-main" aria-expanded={false} aria-label={`Open ${symptom.label || "entry"}`} onClick={() => setOpenState({ ...openState, [k]: true })}>
                <ChevronRight size={16} aria-hidden />
                <strong>{symptom.label || "Untitled"}</strong>
                <Badge tone={symptom.weight === 3 ? "warn" : "neutral"}>{weightLabel(symptom.weight)}</Badge>
                <span className="answer-preview">{answer || <em>No answer yet{urdu && <> · <bdi lang="ur" dir="rtl" className="urdu-inline">{urLabels.noAnswer}</bdi></>}</em>}</span>
              </button>
              {!disabled && trash(symptom, index)}
            </div>
          );
        }
        const detailsShown = detailsOpen(symptom, k);
        return (
          <div className="symptom-card" id={`card-${k}`} key={k}>
            <fieldset className="plain-fieldset" disabled={disabled}>
              <div className="symptom-head">
                <div className="field grow"><label htmlFor={`label-${index}`}>{kind === "particular" ? <Bi en="Complaint" ur={urLabels.complaint} show={urdu} /> : <Bi en="Symptom or note" ur={urLabels.symptomOrNote} show={urdu} />}</label><input id={`label-${index}`} value={symptom.label} maxLength={300} placeholder={both(labelExamples[kind], urLabels.labelExamples[kind], urdu)} onChange={(e) => update(index, { label: e.target.value })} /></div>
                <div className="field"><label htmlFor={`weight-${index}`}><Bi en="Importance" ur={urLabels.importance} show={urdu} /></label><select id={`weight-${index}`} value={symptom.weight} onChange={(e) => update(index, { weight: Number(e.target.value) })}>{weights.map((w) => <option key={w.value} value={w.value}>{both(w.label, urLabels.importanceLevels[w.value], urdu)}</option>)}</select></div>
                {trash(symptom, index)}
              </div>
              <div className="field"><div className="label-row"><label htmlFor={`notes-${index}`}><Bi en="Patient&apos;s own words / notes" ur={urLabels.notes} show={urdu} /></label>{!disabled && <MicButton compact label="Dictate notes" onText={(text) => update(index, { notes: `${symptom.notes ?? ""}${symptom.notes && !/\s$/.test(symptom.notes) ? " " : ""}${text}`.slice(0, 4000) })} />}</div><AutoTextarea id={`notes-${index}`} dir="auto" minRows={6} value={symptom.notes ?? ""} maxLength={4000} placeholder={both(notesExamples[kind], urLabels.notesExamples[kind], urdu, "\n")} onChange={(e) => update(index, { notes: e.target.value })} />{(symptom.hint || symptom.hint_ur) && <div className="answer-hint" aria-label="Example answer"><strong><Bi en="How to write a good answer:" ur={urLabels.goodAnswer} show={urdu} /></strong>{symptom.hint && <span>{symptom.hint}</span>}{symptom.hint_ur && <span className="urdu" lang="ur" dir="rtl">{symptom.hint_ur}</span>}</div>}</div>
              {hasDetails && detailsShown && (
                <div className="symptom-grid">{detailFields.map(([key, label, example]) => <div className="field" key={key}><label htmlFor={`${key}-${index}`}><Bi en={label} ur={urLabels.details[key].label} show={urdu} /></label><AutoTextarea id={`${key}-${index}`} dir="auto" minRows={2} value={symptom[key] ?? ""} maxLength={500} placeholder={both(example, urLabels.details[key].example, urdu, "\n")} onChange={(e) => update(index, { [key]: e.target.value })} /></div>)}</div>
              )}
            </fieldset>
            <div className="card-actions">
              {hasDetails && <button type="button" className="button secondary" aria-expanded={detailsShown} onClick={() => setDetailState({ ...detailState, [k]: !detailsShown })}>{detailsShown ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}{detailsShown ? <Bi en="Hide details" ur={urLabels.hideDetails} show={urdu} /> : <Bi en="More details" ur={urLabels.moreDetails} show={urdu} />}</button>}
              <button type="button" className="button secondary" onClick={() => setOpenState({ ...openState, [k]: false })}><Check size={16} aria-hidden /><Bi en="Done" ur={urLabels.done} show={urdu} /></button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
