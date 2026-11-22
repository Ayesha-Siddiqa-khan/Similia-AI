"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Sparkles } from "lucide-react";
import { Badge, Loading, Notice, Panel } from "@/components/ui";
import { ApiError } from "@/lib/backend";
import { AnalysisView } from "./analysis-view";
import { EarlierAnalyses } from "./earlier-analyses";
import { ApiErrorNotice } from "./api-error-notice";
import { patch, post, put, useCase, useLatestAnalysis, usePatient } from "./api";
import { patientPath, statusLabel, statusTone } from "./paths";
import { kindLabel, SymptomEditor } from "./symptom-editor";
import { SuggestedQuestions, type QuestionStep } from "./suggested-questions";
import { Bi, UrduLine } from "./bilingual";
import { answeredCount, askedQuestions, type Draft, MAX_SYMPTOMS, questionNotes, toSavePayload } from "./case-draft";
import { newKey } from "./symptom-key";
import { type AutosaveState, useAutosave } from "./use-autosave";
import { URDU_PREF_KEY, urLabels } from "./urdu-labels";
import { MicButton } from "./voice-input";
import { AutoTextarea } from "@/components/auto-textarea";
import { useLocalPref } from "@/lib/use-local-pref";
import type { Analysis, CaseRecord, FollowUpQuestion, FollowUps, Symptom, SymptomKind } from "./types";

const steps: { id: string; title: string; hint: string; kinds?: SymptomKind[]; questionStep?: QuestionStep }[] = [
  { id: "complaint", title: "Chief complaint", hint: "Let the patient describe the problem in their own words, without interrupting." },
  { id: "mental", title: "Mind", kinds: ["mental"], questionStep: "mental", hint: "Temperament, fears, reactions to stress and consolation. Peculiar or strongly felt traits carry the most weight." },
  { id: "general", title: "Whole body", kinds: ["physical_general"], questionStep: "physical_general", hint: "Symptoms of the person as a whole: heat or cold, thirst, appetite, desires and aversions, sleep, dreams, perspiration." },
  { id: "particular", title: "Complaints", kinds: ["particular"], questionStep: "particular", hint: "For each complaint note the location, sensation, what makes it better or worse, and what accompanies it." },
  { id: "history", title: "History", kinds: ["history", "family", "medication"], questionStep: "history", hint: "Past illnesses, family history and any current medication." },
  { id: "analyze", title: "Analyse", hint: "Review the case summary, then retrieve cited book passages and candidate remedies." },
];

const saveText: Record<AutosaveState, string> = { saved: "All changes saved", saving: "Saving…", dirty: "Unsaved changes…", error: "Not saved. Retrying automatically", idle: "Autosaves as you type" };
const hasUrdu = (q: FollowUps) => [q.mental, q.physical_general, q.particular, q.history].some((list) => list.some((item) => item.question_ur));

function CaseEditor({ initial }: { initial: CaseRecord }) {
  const client = useQueryClient();
  const analysisQuery = useLatestAnalysis(initial.id);
  const caseQuery = useCase(initial.id);
  const status = caseQuery.data?.status ?? initial.status;
  const patientQuery = usePatient(initial.patient_id);
  const archived = !!patientQuery.data?.archived_at; // an archived patient's cases are read-only
  const signedOff = status === "signed_off"; // a signed-off record is read-only until it is reopened
  const locked = signedOff || archived;
  const [step, setStep] = useState(0);
  const [complaint, setComplaint] = useState(initial.chief_complaint);
  const [symptoms, setSymptoms] = useState<Symptom[]>(initial.symptoms);
  // The newest draft lives in a ref so saves never send stale text; state only drives the screen.
  const draft = useRef<Draft>({ complaint: initial.chief_complaint, symptoms: initial.symptoms });
  const autosave = useAutosave<Draft>({
    enabled: !locked,
    // A read-only record (HTTP 409) cannot be fixed by trying again: show the reason once and stop.
    shouldRetry: (failure) => !(failure instanceof ApiError && failure.status === 409),
    save: async (value) => {
      await patch(`cases/${initial.id}`, { chief_complaint: value.complaint });
      await put(`cases/${initial.id}/symptoms`, { symptoms: toSavePayload(value.symptoms) });
      // An edit can make an earlier analysis out of date; refresh the case status shown on screen.
      void client.invalidateQueries({ queryKey: ["case", initial.id] });
    },
  });
  const saveState = autosave.state;
  const changeDraft = (changes: Partial<Draft>) => {
    draft.current = { ...draft.current, ...changes };
    if (changes.complaint !== undefined) setComplaint(changes.complaint);
    if (changes.symptoms !== undefined) setSymptoms(changes.symptoms);
    autosave.schedule(draft.current);
  };

  const [questions, setQuestions] = useState<FollowUps | null>(null);
  const [urduPref, setUrduPref] = useLocalPref(URDU_PREF_KEY, "0");
  const urdu = urduPref === "1";
  const suggest = useMutation({
    mutationFn: async (withUrdu: boolean) => { await autosave.saveNow(); return post<FollowUps>(`cases/${initial.id}/questions${withUrdu ? "?include_urdu=true" : ""}`); },
    onSuccess: setQuestions,
  });
  const changeUrdu = (value: boolean) => {
    setUrduPref(value ? "1" : "0");
    // Questions already on screen have no Urdu yet: fetch them again with Urdu, once.
    if (value && questions && questions.red_flags.length === 0 && !hasUrdu(questions) && complaint.trim()) suggest.mutate(true);
  };
  const reopen = useMutation({
    mutationFn: () => post<CaseRecord>(`cases/${initial.id}/reopen`),
    onSuccess: (record) => {
      client.setQueryData(["case", initial.id], record);
      void client.invalidateQueries({ queryKey: ["cases"] });
    },
  });
  const analyze = useMutation({
    mutationFn: async (acknowledge: boolean) => {
      await autosave.saveNow();
      return post<Analysis>(`cases/${initial.id}/analyze${acknowledge ? "?acknowledge_red_flags=true" : ""}`);
    },
    onSuccess: (analysis) => {
      client.setQueryData(["analysis", initial.id], analysis);
      void client.invalidateQueries({ queryKey: ["analyses", initial.id] });
      void client.invalidateQueries({ queryKey: ["case", initial.id] });
      void client.invalidateQueries({ queryKey: ["cases"] });
    },
  });

  const edit = (next: Symptom[]) => changeDraft({ symptoms: next });
  const atLimit = symptoms.length >= MAX_SYMPTOMS;
  const addQuestion = (step: QuestionStep, q: FollowUpQuestion) => {
    if (draft.current.symptoms.length >= MAX_SYMPTOMS) return;
    edit([...draft.current.symptoms, { key: newKey(), kind: step, label: q.topic, notes: questionNotes(q, urdu), weight: 2, hint: q.example_answer, hint_ur: urdu ? q.example_answer_ur : undefined }]);
  };
  const suggestions = (step?: QuestionStep) => <SuggestedQuestions step={step} questions={questions} loading={suggest.isPending} error={suggest.isError ? suggest.error : null} canSuggest={complaint.trim().length > 0} asked={atLimit ? undefined : askedQuestions(symptoms)} full={atLimit} urdu={urdu} onUrduChange={changeUrdu} onSuggest={() => suggest.mutate(urdu)} onUse={(q) => step && addQuestion(step, q)} />;
  const current = steps[step];
  const analysis = analyze.data ?? analysisQuery.data ?? null;
  const entered = answeredCount(symptoms);
  const canAnalyze = !locked && (complaint.trim() || entered > 0);

  return (
    <>
      <nav className="stepper" aria-label="Case-taking steps">
        {steps.map((s, i) => <button key={s.id} type="button" className={`step-btn ${i === step ? "active" : ""}`} aria-current={i === step ? "step" : undefined} onClick={() => setStep(i)}><span>{i + 1}</span><Bi en={s.title} ur={urLabels.steps[s.id].title} show={urdu} /></button>)}
      </nav>
      <Panel title={<Bi en={current.title} ur={urLabels.steps[current.id].title} show={urdu} />} description={<>{current.hint}<UrduLine text={urLabels.steps[current.id].hint} show={urdu} /></>} action={<span className={`save-state save-${saveState}`} role="status"><Bi en={saveText[saveState]} ur={urLabels.save[saveState]} show={urdu} />{saveState === "error" && <> <button type="button" className="text-link" onClick={() => { autosave.saveNow().catch(() => {}); }}>Save now</button><span className="save-reason"> ({autosave.error})</span>{/sign in|session/i.test(autosave.error) && <> <Link className="text-link" href="/login" target="_blank" rel="noopener noreferrer">Sign in again (your work stays here)</Link></>}</>}</span>}>
        <div className="panel-padding">
          {current.id === "complaint" && <><div className="field"><label htmlFor="complaint">What brings the patient in?{urdu && <> · <bdi className="urdu-inline" lang="ur" dir="rtl">{urLabels.chiefComplaint}</bdi></>}</label>{!locked && <MicButton onText={(text) => { const prev = draft.current.complaint; changeDraft({ complaint: `${prev}${prev && !/\s$/.test(prev) ? " " : ""}${text}`.slice(0, 2000) }); }} />}<AutoTextarea id="complaint" dir="auto" minRows={7} maxLength={2000} value={complaint} disabled={locked} placeholder={`Write it in the patient’s own words. Example: “I am 15 years old. For two years I have had itchy, dry skin behind my knees and on my elbows. It gets worse in winter and when I scratch it, and a sticky yellow fluid comes out.”${urdu ? `\n${urLabels.chiefComplaintExample}` : ""}`} onChange={(e) => changeDraft({ complaint: e.target.value })} /></div>{suggestions()}{questions && questions.red_flags.length === 0 && <p className="fine-print">Questions are ready. Continue to the next steps to see them.</p>}</>}
          {current.questionStep && suggestions(current.questionStep)}
          {current.kinds?.map((kind) => <div key={kind}>{current.kinds!.length > 1 && <h3><Bi en={kindLabel[kind]} ur={urLabels.kinds[kind]} show={urdu} /></h3>}<SymptomEditor kind={kind} symptoms={symptoms} onChange={edit} disabled={locked} /></div>)}
          {current.id === "analyze" && (
            <div className="stack">
              <dl className="measurements"><div><dt>Chief complaint</dt><dd>{complaint || "Not recorded"}</dd></div><div><dt>Entries recorded (answered)</dt><dd>{entered}</dd></div><div><dt>Key symptoms</dt><dd>{symptoms.filter((s) => s.weight === 3 && s.label.trim()).map((s) => s.label).join(", ") || "None marked"}</dd></div></dl>
              {!locked && <button className="button primary" disabled={!canAnalyze || analyze.isPending} onClick={() => analyze.mutate(false)}><Sparkles size={16} />{analyze.isPending ? "Retrieving sources and analysing…" : analysis ? "Run analysis again" : "Run analysis"}</button>}
              {!canAnalyze && !locked && <p className="fine-print">Add a chief complaint or at least one symptom first.</p>}
              {analyze.isError && <ApiErrorNotice error={analyze.error} />}
            </div>
          )}
        </div>
        <div className="panel-padding button-row">
          <button type="button" className="button secondary" disabled={step === 0} onClick={() => setStep(step - 1)}><ChevronLeft size={16} /><Bi en="Back" ur={urLabels.back} show={urdu} /></button>
          {step < steps.length - 1 && <button type="button" className="button secondary" onClick={() => setStep(step + 1)}>{(current.kinds?.every((k) => !symptoms.some((s) => s.kind === k)) ?? false) ? <Bi en="Skip" ur={urLabels.skip} show={urdu} /> : <Bi en="Next" ur={urLabels.next} show={urdu} />}<ChevronRight size={16} /></button>}
        </div>
      </Panel>
      {archived && <Notice><strong>This patient is archived (read-only).</strong> This case cannot be changed or analysed. Re-grant consent on the patient&apos;s page to reopen the record.</Notice>}
      {signedOff && <Notice><strong>This case is signed off and locked.</strong> Its record cannot be changed. To correct it, reopen it: it becomes a draft and needs a new analysis and sign-off. <button type="button" className="button secondary" disabled={reopen.isPending} onClick={() => reopen.mutate()}>{reopen.isPending ? "Reopening…" : "Reopen case"}</button>{reopen.isError && <span className="field-error" role="alert"> {reopen.error.message}</span>}</Notice>}
      {current.id === "analyze" && analysis && <AnalysisView analysis={analysis} caseId={initial.id} status={status} acknowledging={analyze.isPending} onAcknowledge={() => analyze.mutate(true)} />}
      <EarlierAnalyses caseId={initial.id} />
    </>
  );
}

export function CasePage({ id }: { id: string }) {
  const query = useCase(id);
  const patient = usePatient(query.data?.patient_id ?? "");
  if (query.isPending) return <Loading />;
  if (query.isError) return <Notice error>{query.error.message}</Notice>;
  const record = query.data;
  return (
    <>
      <div className="page-heading"><div><span className="eyebrow">AI CASE WORKSPACE</span><h1>{patient.data?.full_name ?? "Case"}</h1><p>{patient.data ? <><Link className="text-link" href={patientPath(patient.data.id)}>{patient.data.identifier}</Link> · </> : null}Language {record.language.toUpperCase()}</p></div><Badge tone={statusTone[record.status]}>{statusLabel[record.status]}</Badge></div>
      <Notice>Case text is sent to the configured AI provider and embedding service for analysis. Only analyse patients who have consented.</Notice>
      <CaseEditor key={record.id} initial={record} />
    </>
  );
}
