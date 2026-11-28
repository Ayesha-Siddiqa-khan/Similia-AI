"use client";

import { SearchMethodNotice } from "./search-method";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, ShieldAlert } from "lucide-react";
import { Badge, Notice, Panel } from "@/components/ui";
import { ProgressDots } from "@/components/progress-dots";
import { post, useReview } from "./api";
import { ApiErrorNotice } from "./api-error-notice";
import { formatDate, reportPath } from "./paths";
import type { Analysis, CaseStatus, Patient } from "./types";
import { LocalMicButton } from "@/features/speech";

const confidenceTone = { low: "neutral", medium: "warn", high: "good" } as const;

export async function downloadPrescriptionPdf(caseId: string, patientIdentifier?: string) {
  const response = await fetch(`/api/backend/cases/${caseId}/prescription/file`);
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(typeof errorBody.detail === "string" ? errorBody.detail : "Could not download prescription PDF");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  const safeId = (patientIdentifier ?? "").replace(/[^A-Za-z0-9-]+/g, "-") || caseId.slice(0, 8);
  link.download = `prescription-${safeId}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function RedFlagNotice({ flags, onAcknowledge, busy, acknowledging }: { flags: string[]; onAcknowledge: () => void; busy: boolean; acknowledging: boolean }) {
  const [confirming, setConfirming] = useState(false);
  return (
    <Notice error>
      <strong><ShieldAlert size={16} aria-hidden /> Possible urgent concern. Remedy analysis was not run.</strong>
      <ul>{flags.map((f) => <li key={f}>{f}</li>)}</ul>
      <p>Assess the patient&apos;s urgency first and arrange emergency or specialist care if needed.</p>
      {(confirming
        ? <div className="button-row"><button className="button primary" disabled={busy} aria-busy={acknowledging} onClick={onAcknowledge}>{acknowledging ? <>Analysing <ProgressDots /></> : "I have assessed urgency. Analyse anyway"}</button><button className="button secondary" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button></div>
        : <button className="button secondary" disabled={busy} onClick={() => setConfirming(true)}>I have assessed this myself…</button>)}
    </Notice>
  );
}

function FinalisedPrescriptionCard({ caseId, patient }: { caseId: string; patient?: Patient }) {
  const reviewQuery = useReview(caseId);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const review = reviewQuery.data;

  async function handleDownload() {
    setDownloadError(null);
    setDownloading(true);
    try {
      await downloadPrescriptionPdf(caseId, patient?.identifier);
    } catch (err: unknown) {
      setDownloadError(err instanceof Error ? err.message : "Failed to download prescription PDF");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <Panel
      title="Finalised Prescription"
      description="Prescription recorded and finalised by the treating practitioner."
      action={<Badge tone="good">Finalised & Signed</Badge>}
    >
      <div className="panel-padding stack">
        <Notice>
          This prescription was finalised and authorised by the treating doctor on {review ? formatDate(review.signed_at) : "record"}.
          To modify or correct it, reopen the case using the Reopen button above.
        </Notice>

        {review && (
          <dl className="measurements">
            <div><dt>Chosen Remedy</dt><dd><strong>{review.chosen_remedy || "None (Rejected)"}</strong></dd></div>
            <div><dt>Potency</dt><dd>{review.potency || "Not recorded"}</dd></div>
            <div><dt>Dose</dt><dd>{review.dose || "Not recorded"}</dd></div>
            <div><dt>Frequency</dt><dd>{review.frequency || "Not recorded"}</dd></div>
            <div><dt>Duration</dt><dd>{review.duration || "Not recorded"}</dd></div>
            <div><dt>Prescriber</dt><dd>{review.practitioner_name || "Not recorded"}</dd></div>
            {review.diagnosis && <div><dt>Diagnosis / Impression</dt><dd>{review.diagnosis}</dd></div>}
            {review.instructions && <div style={{ gridColumn: "1 / -1" }}><dt>Instructions & Advice</dt><dd>{review.instructions}</dd></div>}
            {review.urgency_disposition && <div style={{ gridColumn: "1 / -1" }}><dt>Urgent Findings Disposition</dt><dd>{review.urgency_disposition}</dd></div>}
            {review.notes && <div style={{ gridColumn: "1 / -1" }}><dt>Doctor&apos;s Notes</dt><dd>{review.notes}</dd></div>}
          </dl>
        )}

        {downloadError && <Notice error>{downloadError}</Notice>}

        <div className="button-row">
          <button type="button" className="button primary" disabled={downloading} onClick={() => void handleDownload()}>
            <Download size={16} /> {downloading ? "Downloading PDF…" : "Download Prescription PDF"}
          </button>
          <Link className="button secondary" href={reportPath(caseId)} target="_blank" rel="noopener noreferrer">
            <FileText size={16} /> Detailed RAG Analysis Report
          </Link>
        </div>
      </div>
    </Panel>
  );
}

function PrescriptionReviewForm({
  caseId,
  analysis,
  remedies,
  redFlags,
  patient,
}: {
  caseId: string;
  analysis: string;
  remedies: string[];
  redFlags: string[];
  patient?: Patient;
}) {
  const client = useQueryClient();
  const [decision, setDecision] = useState<"accepted" | "modified" | "rejected">("accepted");
  const [chosen, setChosen] = useState("");
  const [diagnosis, setDiagnosis] = useState("");
  const [potency, setPotency] = useState("");
  const [dose, setDose] = useState("");
  const [frequency, setFrequency] = useState("");
  const [duration, setDuration] = useState("");
  const [instructions, setInstructions] = useState("");
  const [practitionerName, setPractitionerName] = useState("");
  const [urgencyDisposition, setUrgencyDisposition] = useState("");
  const [includeUrgentInPdf, setIncludeUrgentInPdf] = useState(false);
  const [notes, setNotes] = useState("");

  const submit = useMutation({
    mutationFn: () =>
      post(`cases/${caseId}/review`, {
        analysis_id: analysis,
        decision,
        chosen_remedy: decision === "rejected" ? null : chosen.trim(),
        diagnosis: diagnosis.trim() || null,
        potency: potency.trim() || null,
        dose: dose.trim() || null,
        frequency: frequency.trim() || null,
        duration: duration.trim() || null,
        instructions: instructions.trim() || null,
        urgency_disposition: urgencyDisposition.trim() || null,
        include_urgent_in_pdf: includeUrgentInPdf,
        practitioner_name: practitionerName.trim() || null,
        notes: notes.trim() || null,
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["case", caseId] });
      await client.invalidateQueries({ queryKey: ["review", caseId] });
      await client.invalidateQueries({ queryKey: ["cases"] });
      // Trigger PDF download immediately upon finalisation
      try {
        await downloadPrescriptionPdf(caseId, patient?.identifier);
      } catch {
        // Fallback: the download button is also readily available on the finalised card
      }
    },
  });

  const missingRemedy = decision !== "rejected" && !chosen.trim();
  const missingUrgency = redFlags.length > 0 && !urgencyDisposition.trim();
  const missingName = decision !== "rejected" && !practitionerName.trim();

  return (
    <Panel
      title="Prescription & Clinical Decision"
      description="The authenticated treating doctor is the final decision-maker. Enter the prescription yourself before finalising."
    >
      <form
        className="case-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit.mutate();
        }}
      >
        <Notice>
          AI suggestions are decision support and must never be mistaken for confirmed diagnoses or automatically issued prescriptions.
          Enter the remedy, potency, dose and instructions yourself. Nothing is filled in for you.
        </Notice>

        {redFlags.length > 0 && (
          <Notice error>
            <strong>Urgent clinical concern flagged:</strong> {redFlags.join("; ")}
            <p>You must address these urgent findings and record your clinical assessment and disposition before finalising treatment.</p>
          </Notice>
        )}

        <div className="field">
          <label htmlFor="rv-decision">Decision</label>
          <select id="rv-decision" value={decision} onChange={(e) => setDecision(e.target.value as typeof decision)}>
            <option value="accepted">Accept a suggested remedy</option>
            <option value="modified">Choose a different remedy</option>
            <option value="rejected">Reject the analysis</option>
          </select>
        </div>

        {decision !== "rejected" && (
          <>
            <div className="field">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <label htmlFor="rv-diagnosis" style={{ marginBottom: 0 }}>Diagnosis / Clinical Impression</label>
                <LocalMicButton compact label="Dictate diagnosis" onText={(text) => setDiagnosis((prev) => `${prev}${prev && !/\s$/.test(prev) ? " " : ""}${text}`)} />
              </div>
              <textarea
                id="rv-diagnosis"
                rows={3}
                value={diagnosis}
                onChange={(e) => setDiagnosis(e.target.value)}
                placeholder="e.g. Acute Eczema with nocturnal pruritus"
              />
            </div>

            <div className="field">
              <label htmlFor="rv-remedy">Remedy Chosen</label>
              <input
                id="rv-remedy"
                value={chosen}
                maxLength={200}
                onChange={(e) => setChosen(e.target.value)}
                list="rv-options"
                placeholder="Enter or select remedy"
              />
              <datalist id="rv-options">
                {remedies.map((r) => (
                  <option key={r} value={r} />
                ))}
              </datalist>
            </div>

            <div className="field">
              <label htmlFor="rv-potency">Potency</label>
              <input
                id="rv-potency"
                value={potency}
                maxLength={100}
                onChange={(e) => setPotency(e.target.value)}
                list="potency-presets"
                placeholder="e.g. 30C, 200C, 1M, 6X, Q"
              />
              <datalist id="potency-presets">
                <option value="30C" />
                <option value="200C" />
                <option value="1M" />
                <option value="10M" />
                <option value="6C" />
                <option value="12C" />
                <option value="6X" />
                <option value="12X" />
                <option value="Q (Mother Tincture)" />
              </datalist>
            </div>

            <div className="field">
              <label htmlFor="rv-dose">Dose</label>
              <input
                id="rv-dose"
                value={dose}
                maxLength={200}
                onChange={(e) => setDose(e.target.value)}
                placeholder="e.g. 4 pills, 4 drops, 1 powder"
              />
            </div>

            <div className="field">
              <label htmlFor="rv-frequency">Frequency</label>
              <input
                id="rv-frequency"
                value={frequency}
                maxLength={200}
                onChange={(e) => setFrequency(e.target.value)}
                placeholder="e.g. Twice daily, Three times daily, Once at bedtime"
              />
            </div>

            <div className="field">
              <label htmlFor="rv-duration">Duration</label>
              <input
                id="rv-duration"
                value={duration}
                maxLength={200}
                onChange={(e) => setDuration(e.target.value)}
                placeholder="e.g. 7 days, 14 days, 1 month"
              />
            </div>

            <div className="field">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <label htmlFor="rv-instructions" style={{ marginBottom: 0 }}>Patient Instructions & Advice</label>
                <LocalMicButton compact label="Dictate instructions" onText={(text) => setInstructions((prev) => `${prev}${prev && !/\s$/.test(prev) ? " " : ""}${text}`.slice(0, 2000))} />
              </div>
              <textarea
                id="rv-instructions"
                rows={3}
                value={instructions}
                maxLength={2000}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder="Dietary rules, dosage directions, and follow-up guidance..."
              />
            </div>

            <div className="field">
              <label htmlFor="rv-practitioner">Prescriber&apos;s name *</label>
              <input
                id="rv-practitioner"
                value={practitionerName}
                maxLength={200}
                required
                autoComplete="name"
                onChange={(e) => setPractitionerName(e.target.value)}
                placeholder="Your name as it should appear on the prescription"
              />
            </div>
          </>
        )}

        {redFlags.length > 0 && (
          <div className="field">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
              <label htmlFor="rv-urgency" style={{ marginBottom: 0 }}>Urgent Findings Assessment & Disposition *</label>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <LocalMicButton compact label="Dictate disposition" onText={(text) => setUrgencyDisposition((prev) => `${prev}${prev && !/\s$/.test(prev) ? " " : ""}${text}`.slice(0, 2000))} />
              </div>
            </div>
            <textarea
              id="rv-urgency"
              rows={3}
              value={urgencyDisposition}
              maxLength={2000}
              required
              onChange={(e) => setUrgencyDisposition(e.target.value)}
              placeholder="Record your clinical assessment of the urgent findings and disposition/referral..."
            />
            <label className="check-label" style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={includeUrgentInPdf}
                onChange={(e) => setIncludeUrgentInPdf(e.target.checked)}
              />
              Print Urgent Clinical Advisory on patient Prescription PDF (Optional, unchecked by default)
            </label>
          </div>
        )}

        <div className="field">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <label htmlFor="rv-notes" style={{ marginBottom: 0 }}>Internal Doctor&apos;s Notes (Optional)</label>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <LocalMicButton compact label="Dictate notes" onText={(text) => setNotes((prev) => `${prev}${prev && !/\s$/.test(prev) ? " " : ""}${text}`.slice(0, 4000))} />
            </div>
          </div>
          <textarea
            id="rv-notes"
            rows={2}
            value={notes}
            maxLength={4000}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Private practitioner clinical notes..."
          />
        </div>

        {submit.isError && <Notice error>{submit.error.message}</Notice>}

        <div className="button-row">
          <button
            type="submit"
            className="button primary"
            disabled={submit.isPending || missingRemedy || missingUrgency || missingName}
          >
            {submit.isPending ? "Saving & finalising…" : "Save & Finalise Prescription"}
          </button>
        </div>
      </form>
    </Panel>
  );
}

export function AnalysisView({
  analysis,
  caseId,
  status,
  onAcknowledge,
  acknowledging,
  analysisPending = acknowledging,
  acknowledgementError,
  patient,
}: {
  analysis: Analysis;
  caseId: string;
  status: CaseStatus;
  onAcknowledge: () => void;
  acknowledging: boolean;
  analysisPending?: boolean;
  acknowledgementError?: Error | null;
  patient?: Patient;
}) {
  const passages = new Map(analysis.passages.map((p) => [p.chunk_id, p]));
  const incompleteBooks = [
    ...new Set([
      ...(analysis.incomplete_books ?? []),
      ...analysis.passages.filter((p) => p.book_complete === false).map((p) => p.book_title),
    ]),
  ];

  return (
    <div className="stack">
      {analysis.outcome === "red_flag" && (
        <RedFlagNotice
          flags={analysis.red_flags}
          onAcknowledge={onAcknowledge}
          busy={analysisPending}
          acknowledging={acknowledging}
        />
      )}
      {analysis.outcome === "red_flag" && acknowledgementError && <ApiErrorNotice error={acknowledgementError} />}
      {(analysis.cautions ?? []).length > 0 && (
        <Notice>
          <strong>Take extra care.</strong>
          <ul>
            {analysis.cautions.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </Notice>
      )}
      {analysis.outcome !== "red_flag" && analysis.red_flags.length > 0 && (
        <Notice error>Urgency was acknowledged by the practitioner for: {analysis.red_flags.join("; ")}</Notice>
      )}
      {analysis.outcome === "red_flag" ? (
        <p className="fine-print">Library search was skipped.</p>
      ) : (
        <SearchMethodNotice
          requested={analysis.requested_mode}
          used={analysis.retrieval_mode}
          reason={analysis.fallback_reason}
        />
      )}
      {analysis.outcome !== "red_flag" && analysis.retrieval_mode === "keyword" && (
        <Notice error>
          Keyword matching can miss passages that use different words. Review the source text before relying on this analysis.
        </Notice>
      )}
      {incompleteBooks.length > 0 && (
        <Notice error>
          Some evidence comes from partly indexed books: {incompleteBooks.join(", ")}. This analysis may be missing evidence from the unindexed parts of these books.
        </Notice>
      )}
      {analysis.outcome === "insufficient_sources" && (
        <Notice>
          The knowledge base does not contain enough supporting passages for this case, so no remedy is suggested. Add detail, or consult your own references.
        </Notice>
      )}
      {analysis.outcome === "ranked" &&
        analysis.remedies.map((r, i) => (
          <section className="panel remedy-card" key={r.remedy}>
            <div className="panel-heading">
              <div>
                <h2>
                  {i + 1}. {r.remedy}
                </h2>
                <small className="evidence-label">AI interpretation</small>
                <p>{r.rationale}</p>
              </div>
              <Badge tone={confidenceTone[r.confidence]}>{r.confidence} confidence</Badge>
            </div>
            <div className="panel-padding">
              {r.matching_symptoms.length > 0 && (
                <>
                  <h3>Fits</h3>
                  <ul>
                    {r.matching_symptoms.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                </>
              )}
              {r.contradicting_symptoms.length > 0 && (
                <>
                  <h3>Against</h3>
                  <ul>
                    {r.contradicting_symptoms.map((s) => (
                      <li key={s}>{s}</li>
                    ))}
                  </ul>
                </>
              )}
              <details>
                <summary>Sources ({r.citations.length})</summary>
                {r.citations.map((id) => {
                  const p = passages.get(id);
                  return p ? (
                    <article className="chunk-card" key={id}>
                      <div className="chunk-top">
                        <strong>{p.book_title}</strong>
                        <Badge>{p.section_heading ?? p.book_category}</Badge>
                      </div>
                      {p.book_author && <small>Author: {p.book_author}</small>}
                      {!!p.section_path?.length && <small>Section path: {p.section_path.join(" › ")}</small>}
                      {p.page_start != null && (
                        <small>
                          {p.page_end != null && p.page_end !== p.page_start
                            ? `PDF pages ${p.page_start}–${p.page_end}`
                            : `PDF page ${p.page_start}`}
                        </small>
                      )}
                      {p.book_complete === false && (
                        <div>
                          <Badge tone="warn">from a partly indexed book</Badge>
                        </div>
                      )}
                      <small className="evidence-label">Book text</small>
                      <p className="passage-text">{p.content}</p>
                      <div className="chunk-meta">
                        <span>Source chunk: {p.chunk_id}</span>
                        <span>Similarity {p.similarity.toFixed(3)}</span>
                      </div>
                    </article>
                  ) : null;
                })}
              </details>
            </div>
          </section>
        ))}
      {analysis.missing_information.length > 0 && (
        <Panel title="Ask next" description="Information that would sharpen this analysis">
          <ul className="panel-padding">
            {analysis.missing_information.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </Panel>
      )}
      <p className="fine-print">
        {analysis.disclaimer}
        {analysis.model ? ` Model: ${analysis.model}.` : ""}
      </p>

      {status === "signed_off" ? (
        <FinalisedPrescriptionCard caseId={caseId} patient={patient} />
      ) : status === "draft" && analysis.outcome !== "red_flag" ? (
        <Notice error>The case was changed after this analysis, so it is out of date. Run the analysis again before finalising.</Notice>
      ) : (
        analysis.outcome !== "red_flag" && (
          <PrescriptionReviewForm
            caseId={caseId}
            analysis={analysis.id}
            remedies={analysis.remedies.map((r) => r.remedy)}
            redFlags={analysis.red_flags}
            patient={patient}
          />
        )
      )}
    </div>
  );
}
