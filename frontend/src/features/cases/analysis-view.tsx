"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { Badge, Notice, Panel } from "@/components/ui";
import { post } from "./api";
import type { Analysis, CaseStatus } from "./types";

const confidenceTone = { low: "neutral", medium: "warn", high: "good" } as const;

function RedFlagNotice({ flags, onAcknowledge, busy }: { flags: string[]; onAcknowledge: () => void; busy: boolean }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <Notice error>
      <strong><ShieldAlert size={16} aria-hidden /> Possible urgent concern. Remedy analysis was not run.</strong>
      <ul>{flags.map((f) => <li key={f}>{f}</li>)}</ul>
      <p>Assess the patient&apos;s urgency first and arrange emergency or specialist care if needed.</p>
      {(confirming
        ? <div className="button-row"><button className="button primary" disabled={busy} onClick={onAcknowledge}>{busy ? "Analysing…" : "I have assessed urgency. Analyse anyway"}</button><button className="button secondary" onClick={() => setConfirming(false)}>Cancel</button></div>
        : <button className="button secondary" onClick={() => setConfirming(true)}>I have assessed this myself…</button>)}
    </Notice>
  );
}

function ReviewForm({ caseId, analysis, remedies }: { caseId: string; analysis: string; remedies: string[] }) {
  const client = useQueryClient();
  const [decision, setDecision] = useState<"accepted" | "modified" | "rejected">("accepted");
  const [chosen, setChosen] = useState(remedies[0] ?? "");
  const [notes, setNotes] = useState("");
  const submit = useMutation({
    mutationFn: () => post(`cases/${caseId}/review`, { analysis_id: analysis, decision, chosen_remedy: decision === "rejected" ? null : chosen.trim(), notes: notes.trim() || null }),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ["case", caseId] }); void client.invalidateQueries({ queryKey: ["cases"] }); },
  });
  const missingRemedy = decision !== "rejected" && !chosen.trim();
  return (
    <Panel title="Practitioner review" description="Record your own decision. This signs off the case.">
      <form className="case-form" onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
        <div className="field"><label htmlFor="rv-decision">Decision</label><select id="rv-decision" value={decision} onChange={(e) => setDecision(e.target.value as typeof decision)}><option value="accepted">Accept a suggested remedy</option><option value="modified">Choose a different remedy</option><option value="rejected">Reject the analysis</option></select></div>
        {decision !== "rejected" && <div className="field"><label htmlFor="rv-remedy">Remedy chosen</label><input id="rv-remedy" value={chosen} maxLength={200} onChange={(e) => setChosen(e.target.value)} list="rv-options" /><datalist id="rv-options">{remedies.map((r) => <option key={r} value={r} />)}</datalist></div>}
        <div className="field"><label htmlFor="rv-notes">Notes</label><textarea id="rv-notes" rows={3} value={notes} maxLength={4000} onChange={(e) => setNotes(e.target.value)} /></div>
        {submit.isError && <Notice error>{submit.error.message}</Notice>}
        <button className="button primary" disabled={submit.isPending || missingRemedy}>{submit.isPending ? "Signing off…" : "Sign off case"}</button>
      </form>
    </Panel>
  );
}

export function AnalysisView({ analysis, caseId, status, onAcknowledge, acknowledging }: { analysis: Analysis; caseId: string; status: CaseStatus; onAcknowledge: () => void; acknowledging: boolean }) {
  const passages = new Map(analysis.passages.map((p) => [p.chunk_id, p]));
  const incompleteBooks = [...new Set([...(analysis.incomplete_books ?? []), ...analysis.passages.filter((p) => p.book_complete === false).map((p) => p.book_title)])];
  return (
    <div className="stack">
      {analysis.outcome === "red_flag" && <RedFlagNotice flags={analysis.red_flags} onAcknowledge={onAcknowledge} busy={acknowledging} />}
      {(analysis.cautions ?? []).length > 0 && <Notice><strong>Take extra care.</strong><ul>{analysis.cautions.map((c) => <li key={c}>{c}</li>)}</ul></Notice>}
      {analysis.outcome !== "red_flag" && analysis.red_flags.length > 0 && <Notice error>Urgency was acknowledged by the practitioner for: {analysis.red_flags.join("; ")}</Notice>}
      {(analysis.retrieval_mode === "keyword" || analysis.passages.some((p) => p.retrieval_mode === "keyword")) && <Notice error>These passages were found by keyword matching, not meaning-based search (the search provider was unavailable). Passages that use different words may be missing. Check the sources yourself before relying on this analysis.</Notice>}
      {incompleteBooks.length > 0 && <Notice error>Some evidence comes from partly indexed books: {incompleteBooks.join(", ")}. This analysis may be missing evidence from the unindexed parts of these books.</Notice>}
      {analysis.outcome === "insufficient_sources" && <Notice>The knowledge base does not contain enough supporting passages for this case, so no remedy is suggested. Add detail, or consult your own references.</Notice>}
      {analysis.outcome === "ranked" && analysis.remedies.map((r, i) => (
        <section className="panel remedy-card" key={r.remedy}>
          <div className="panel-heading"><div><h2>{i + 1}. {r.remedy}</h2><small className="evidence-label">AI interpretation</small><p>{r.rationale}</p></div><Badge tone={confidenceTone[r.confidence]}>{r.confidence} confidence</Badge></div>
          <div className="panel-padding">
            {r.matching_symptoms.length > 0 && <><h3>Fits</h3><ul>{r.matching_symptoms.map((s) => <li key={s}>{s}</li>)}</ul></>}
            {r.contradicting_symptoms.length > 0 && <><h3>Against</h3><ul>{r.contradicting_symptoms.map((s) => <li key={s}>{s}</li>)}</ul></>}
            <details><summary>Sources ({r.citations.length})</summary>
              {r.citations.map((id) => { const p = passages.get(id); return p ? <article className="chunk-card" key={id}><div className="chunk-top"><strong>{p.book_title}</strong><Badge>{p.section_heading ?? p.book_category}</Badge></div>{p.book_author && <small>Author: {p.book_author}</small>}{!!p.section_path?.length && <small>Section path: {p.section_path.join(" › ")}</small>}{p.page_start != null && <small>{p.page_end != null && p.page_end !== p.page_start ? `PDF pages ${p.page_start}–${p.page_end}` : `PDF page ${p.page_start}`}</small>}{p.book_complete === false && <div><Badge tone="warn">from a partly indexed book</Badge></div>}<small className="evidence-label">Book text</small><p className="passage-text">{p.content}</p><div className="chunk-meta"><span>Source chunk: {p.chunk_id}</span><span>Similarity {p.similarity.toFixed(3)}</span></div></article> : null; })}
            </details>
          </div>
        </section>
      ))}
      {analysis.missing_information.length > 0 && <Panel title="Ask next" description="Information that would sharpen this analysis"><ul className="panel-padding">{analysis.missing_information.map((q) => <li key={q}>{q}</li>)}</ul></Panel>}
      <p className="fine-print">{analysis.disclaimer}{analysis.model ? ` Model: ${analysis.model}.` : ""}</p>
      {status === "signed_off"
        ? <Notice>This case has been signed off and is locked. Reopen it from the notice above to change it.</Notice>
        : status === "draft" && analysis.outcome !== "red_flag"
          ? <Notice error>The case was changed after this analysis, so it is out of date. Run the analysis again before signing off.</Notice>
          : analysis.outcome !== "red_flag" && <ReviewForm caseId={caseId} analysis={analysis.id} remedies={analysis.remedies.map((r) => r.remedy)} />}
    </div>
  );
}
