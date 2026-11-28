"use client";

import Link from "next/link";
import { useRef, useState, type Ref } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, Download, FileText, Languages, Printer } from "lucide-react";
import { Loading, Notice } from "@/components/ui";
import { ApiErrorNotice } from "./api-error-notice";
import { post, useCase, useLatestAnalysis, usePatient } from "./api";
import { casePath, formatDate } from "./paths";
import { REPORT_CSS } from "./report-css";
import { enReport, urReport, type ReportLabels } from "./report-labels";
import type { Analysis, CaseRecord, Patient, UrduReport } from "./types";

type Lang = "en" | "ur";
const EXCERPT_LENGTH = 600;
const TRANSLATION_CONSENT = "This sends the analysis wording (not the patient's name, ID or contact) to your AI provider for translation. Machine translation: have it checked.";

export const excerpt = (text: string, max = EXCERPT_LENGTH) => { const t = text.trim(); return t.length > max ? `${t.slice(0, max).trimEnd()}…` : t; };
const fileSafe = (value: string) => value.replace(/[^A-Za-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
const pages = (a?: number | null, b?: number | null, L: ReportLabels = enReport) => (a == null ? null : b != null && b !== a ? `${L.pdfPages} ${a}–${b}` : `${L.pdfPage} ${a}`);

function ReportSheet({ record, patient, analysis, lang, translation, generated, innerRef }: { record: CaseRecord; patient: Patient; analysis: Analysis; lang: Lang; translation: UrduReport | null; generated: string; innerRef: Ref<HTMLElement> }) {
  const L = lang === "ur" ? urReport : enReport;
  const tr = lang === "ur" ? translation : null;
  const passages = new Map(analysis.passages.map((p) => [p.chunk_id, p]));
  const incompleteBooks = [...new Set([...(analysis.incomplete_books ?? []), ...analysis.passages.filter((p) => p.book_complete === false).map((p) => p.book_title)])];
  const keyword = analysis.retrieval_mode === "keyword";
  const mixed = analysis.retrieval_mode === "mixed";
  const list = (english: string[], translated?: string[]) => (tr && translated && translated.length === english.length ? translated : english);
  const redFlags = list(analysis.red_flags, tr?.red_flags);
  const cautions = list(analysis.cautions ?? [], tr?.cautions);
  const questions = list(analysis.missing_information, tr?.missing_information);
  const complaint = (tr?.chief_complaint || record.chief_complaint).trim();
  const ageSex = [patient.age_years != null ? `${patient.age_years} ${L.years}` : null, L.sexes[patient.sex]].filter(Boolean).join(" / ");
  const ranked = analysis.remedies.length > 0;
  return (
    <article ref={innerRef} className="report-sheet" dir={lang === "ur" ? "rtl" : "ltr"} lang={lang === "ur" ? "ur" : "en"} aria-label={L.title}>
      <h1>{L.title}</h1>
      {tr && <p className="rp-note">{tr.notice}</p>}
      <dl className="rp-meta">
        <div><dt>{L.generated}:</dt><dd>{generated}</dd></div>
        <div><dt>{L.caseId}:</dt><dd><bdi>{record.id.slice(0, 8)}</bdi></dd></div>
        <div><dt>{L.patient}:</dt><dd><bdi>{patient.full_name}</bdi></dd></div>
        <div><dt>{L.identifier}:</dt><dd><bdi>{patient.identifier}</bdi></dd></div>
        <div><dt>{L.ageSex}:</dt><dd>{ageSex}</dd></div>
        <div><dt>{L.signoff}:</dt><dd>{record.status === "signed_off" ? L.signedOff : L.notSignedOff}</dd></div>
      </dl>
      <h2>{L.chiefComplaint}</h2>
      <p dir="auto">{complaint || L.notRecorded}</p>
      {redFlags.length > 0 && <><h2>{L.urgent}</h2><div className="rp-banner"><ul>{redFlags.map((f, i) => <li key={i} dir="auto">{f}</li>)}</ul></div></>}
      {cautions.length > 0 && <><h2>{L.cautions}</h2><ul>{cautions.map((c, i) => <li key={i} dir="auto">{c}</li>)}</ul></>}
      {keyword && <p className="rp-banner" role="note">{L.keyword}</p>}
      {mixed && <p className="rp-banner" role="note">{lang === "ur" ? "کچھ عبارتیں مفہوم پر مبنی تلاش سے اور کچھ الفاظ کی مطابقت سے ملیں۔" : "Some queries used keyword fallback. Other queries used meaning-based search."}</p>}
      {analysis.retrieval_mode && <p className="rp-note" dir="ltr">
        Search method used: {analysis.retrieval_mode === "not_run" ? "Skipped" : analysis.retrieval_mode}
        {analysis.requested_mode && analysis.requested_mode !== analysis.retrieval_mode ? ` (requested: ${analysis.requested_mode})` : ""}
        {analysis.fallback_reason ? ` · ${analysis.fallback_reason}` : ""}
      </p>}
      {incompleteBooks.length > 0 && <p className="rp-banner" role="note">{L.incomplete}: <bdi dir="ltr">{incompleteBooks.join(", ")}</bdi></p>}
      {analysis.outcome === "insufficient_sources" && !ranked && <p className="rp-banner" role="note">{L.insufficient}</p>}
      {ranked && <h2>{L.remedies}</h2>}
      {analysis.remedies.map((r, i) => {
        const t = tr?.remedies[i];
        const fits = list(r.matching_symptoms, t?.matching_symptoms);
        const against = list(r.contradicting_symptoms, t?.contradicting_symptoms);
        return (
          <section className="rp-remedy" key={`${r.remedy}-${i}`}>
            <div className="rp-remedy-head"><h3>{i + 1}. <bdi>{r.remedy}</bdi></h3><span>{L.confidence}: {L.confidenceLevels[r.confidence]}</span></div>
            <span className="rp-tag">{L.aiInterpretation}</span>
            <p dir="auto">{t?.rationale || r.rationale}</p>
            {fits.length > 0 && <><h3>{L.fits}</h3><ul>{fits.map((s, k) => <li key={k} dir="auto">{s}</li>)}</ul></>}
            {against.length > 0 && <><h3>{L.against}</h3><ul>{against.map((s, k) => <li key={k} dir="auto">{s}</li>)}</ul></>}
            <h3>{L.sources}</h3>
            {r.citations.map((id) => passages.get(id)).filter((p): p is NonNullable<typeof p> => !!p).map((p) => (
              <div className="rp-source" key={p.chunk_id}>
                <strong dir="ltr"><bdi>{p.book_title}</bdi></strong>
                {p.book_author && <div className="rp-small">{L.author}: <bdi dir="ltr">{p.book_author}</bdi></div>}
                {!!p.section_path?.length && <div className="rp-small">{L.section}: <bdi dir="ltr">{p.section_path.join(" › ")}</bdi></div>}
                {pages(p.page_start, p.page_end, L) && <div className="rp-small">{pages(p.page_start, p.page_end, L)}</div>}
                {p.book_complete === false && <div className="rp-small">({L.partlyIndexed})</div>}
                <span className="rp-tag">{L.bookText}</span>
                <p className="rp-excerpt" dir="ltr" lang="en">{excerpt(p.content)}</p>
              </div>
            ))}
            {r.citations.length === 0 && <p className="rp-small">{L.noSources}</p>}
          </section>
        );
      })}
      {questions.length > 0 && <><h2>{L.askNext}</h2><ul>{questions.map((q, i) => <li key={i} dir="auto">{q}</li>)}</ul></>}
      <div className="rp-foot">
        <p>{L.disclaimer}</p>
        {lang === "ur" && <p dir="ltr" lang="en">{enReport.disclaimer}</p>}
        <p>{analysis.model ? `${L.model}: ${analysis.model}. ` : ""}{formatDate(analysis.created_at)}</p>
      </div>
    </article>
  );
}

/** The report as one self-contained HTML document: no script, no network, the styles inline. */
export function buildReportHtml(sheetHtml: string, lang: Lang, title: string): string {
  const safeTitle = title.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] ?? c);
  // The downloaded file cannot load the app's font file, so it falls back to a system Urdu font.
  const css = `body{margin:0;background:#fff}@page{size:A4;margin:14mm}@media print{.report-sheet{padding:0}}${REPORT_CSS}`;
  return `<!doctype html>\n<html lang="${lang === "ur" ? "ur" : "en"}" dir="${lang === "ur" ? "rtl" : "ltr"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${safeTitle}</title><style>${css}</style></head><body>${sheetHtml}</body></html>`;
}

function useUrduReport(caseId: string, analysisId: string | undefined, requested: boolean) {
  return useQuery({
    queryKey: ["report-urdu", analysisId],
    queryFn: () => post<UrduReport>(`cases/${caseId}/report/urdu?analysis_id=${analysisId}`),
    meta: { autoRefresh: false },
    enabled: requested && !!analysisId,
    staleTime: Infinity, gcTime: Infinity, retry: false, refetchOnWindowFocus: false, refetchOnReconnect: false, refetchOnMount: false,
  });
}

export function CaseReport({ id }: { id: string }) {
  const caseQuery = useCase(id);
  const patientQuery = usePatient(caseQuery.data?.patient_id ?? "");
  const analysisQuery = useLatestAnalysis(id);
  const [lang, setLang] = useState<Lang>("en");
  const [requested, setRequested] = useState(false);
  const [fileBusy, setFileBusy] = useState<"pdf" | "docx" | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const sheet = useRef<HTMLElement>(null);
  const analysis = analysisQuery.data ?? null;
  const urdu = useUrduReport(id, analysis?.id, requested);
  const [generated] = useState(() => formatDate(new Date().toISOString()));

  const toolbarFor = (ready: boolean, patient?: Patient) => (
    <div className="report-toolbar no-print button-row" role="toolbar" aria-label="Report options">
      <div className="report-lang" role="group" aria-label="Report language">
        <button type="button" className={`button ${lang === "en" ? "primary" : "secondary"}`} aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button>
        <button type="button" className={`button ${lang === "ur" ? "primary" : "secondary"}`} aria-pressed={lang === "ur"} lang="ur" onClick={() => setLang("ur")}>اردو</button>
      </div>
      <button type="button" className="button secondary" disabled={!ready} onClick={() => window.print()}><Printer size={16} /> Print / Save as PDF</button>
      <button type="button" className="button secondary" disabled={!ready || fileBusy !== null} onClick={() => void downloadFile("pdf")}><FileText size={16} /> {fileBusy === "pdf" ? "Preparing PDF…" : "Download PDF"}</button>
      <button type="button" className="button secondary" disabled={!ready || fileBusy !== null} onClick={() => void downloadFile("docx")}><FileText size={16} /> {fileBusy === "docx" ? "Preparing Word file…" : "Download Word (.docx)"}</button>
      <button type="button" className="button secondary" disabled={!ready} onClick={() => download(patient)}><Download size={16} /> Download HTML file</button>
      <Link className="button secondary" href={casePath(id)}><ChevronLeft size={16} /> Back to case</Link>
    </div>
  );
  /** A PDF or Word file made by the server from the saved analysis (no AI call, nothing stored). */
  async function downloadFile(kind: "pdf" | "docx") {
    setFileError(null);
    setFileBusy(kind);
    try {
      const response = await fetch(`/api/backend/cases/${id}/report/file`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format: kind, lang, analysis_id: analysis?.id, ...(lang === "ur" && urdu.data ? { translation: urdu.data } : {}) }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : "The file could not be created. Try again.");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `case-${id.slice(0, 8)}-report-${lang}.${kind}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      setFileError(error instanceof Error ? error.message : "The file could not be created. Try again.");
    } finally {
      setFileBusy(null);
    }
  }
  function download(patient?: Patient) {
    if (!sheet.current) return;
    const html = buildReportHtml(sheet.current.outerHTML, lang, (lang === "ur" ? urReport : enReport).title);
    const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `case-${fileSafe(patient?.identifier ?? "") || id.slice(0, 8)}-report-${lang}.html`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  if (caseQuery.isPending || (caseQuery.data && (patientQuery.isPending || analysisQuery.isPending))) return <Loading />;
  if (caseQuery.isError) return <Notice error>{caseQuery.error.message}</Notice>;
  if (patientQuery.isError) return <Notice error>{patientQuery.error.message}</Notice>;
  if (analysisQuery.isError) return <Notice error>{analysisQuery.error.message}</Notice>;
  const record = caseQuery.data!;
  const patient = patientQuery.data!;
  if (!analysis) return <><div className="page-heading no-print"><div><span className="eyebrow">CASE REPORT</span><h1>Report</h1></div></div><Notice>This case has no saved analysis yet, so there is nothing to report.</Notice><div className="button-row no-print"><Link className="button secondary" href={casePath(id)}><ChevronLeft size={16} /> Back to case</Link></div></>;

  const waitingForUrdu = lang === "ur" && !urdu.data;
  return (
    <>
      <style>{REPORT_CSS}</style>
      <div className="page-heading no-print"><div><span className="eyebrow">CASE REPORT</span><h1>Analysis report</h1><p>Download it as a PDF or Word file, print it, or save the page as HTML.</p></div></div>
      {toolbarFor(!waitingForUrdu, patient)}
      {fileError && <div className="no-print"><Notice error>{fileError}</Notice></div>}
      {waitingForUrdu ? (
        <section className="panel no-print" aria-label="Urdu report">
          <div className="panel-padding stack">
            <h2><Languages size={16} aria-hidden /> Urdu report</h2>
            <p>{TRANSLATION_CONSENT}</p>
            {urdu.isFetching
              ? <p role="status">Translating to Urdu…</p>
              : <div className="button-row"><button type="button" className="button primary" onClick={() => (requested ? void urdu.refetch() : setRequested(true))}>{urdu.isError ? "Try again" : "Translate to Urdu"}</button></div>}
            {urdu.isError && <ApiErrorNotice error={urdu.error} />}
          </div>
        </section>
      ) : <ReportSheet innerRef={sheet} record={record} patient={patient} analysis={analysis} lang={lang} translation={urdu.data ?? null} generated={generated} />}
    </>
  );
}
