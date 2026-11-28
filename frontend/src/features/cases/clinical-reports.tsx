"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, Printer } from "lucide-react";
import { ProgressDots } from "@/components/progress-dots";
import { Badge, Loading, Notice, Panel } from "@/components/ui";
import { useLocalPref } from "@/lib/use-local-pref";
import { post } from "./api";
import {
  clinicalQueryKey, useClinicalWorkflow, workflowEndpoint,
  type ClinicalReport, type ReportStage,
} from "./clinical-api";
import { casePath, reportPath } from "./paths";
import { searchModeOptions } from "./search-method";
import { ClinicalPhotos } from "./clinical-photos";

const titles: Record<ReportStage, string> = {
  research: "RAG Research Report",
  assessment: "AI Assessment and Draft Prescription",
  final: "Doctor’s Final Clinical Report and Prescription",
};
const stages: ReportStage[] = ["research", "assessment", "final"];

function ReportContent({ report }: { report: ClinicalReport }) {
  return <article className="clinical-print-sheet" lang={report.locale} dir={report.locale === "ur" ? "rtl" : "ltr"}>
    {report.blocks.map((block, index) => {
      const order = block.ltr ? "ltr" : undefined;
      if (block.kind === "h1") return <h1 key={index} dir={order}>{block.text}</h1>;
      if (block.kind === "h2") return <h2 key={index} dir={order}>{block.text}</h2>;
      if (block.kind === "h3") return <h3 key={index} dir={order}>{block.text}</h3>;
      if (block.kind === "excerpt") return <blockquote key={index} dir={order}>{block.text}</blockquote>;
      if (block.kind === "banner") return <Notice key={index}><bdi dir={order}>{block.text}</bdi></Notice>;
      return <p key={index} dir={order} className={["small", "meta", "foot"].includes(block.kind) ? "fine-print" : undefined}>
        {block.kind === "li" ? "• " : ""}{block.text}
      </p>;
    })}
  </article>;
}

export function ClinicalReports({ id }: { id: string }) {
  const client = useQueryClient();
  const query = useClinicalWorkflow(id);
  const root = workflowEndpoint(id);
  const [savedStage, saveStage] = useLocalPref(`similia.clinical-stage.${id}`, "research");
  const stage = stages.find((item) => item === savedStage) ?? "research";
  const [selected, select] = useState<Partial<Record<ReportStage, string>>>({});
  const [mode, setMode] = useState("hybrid");
  const [disposition, setDisposition] = useState("");
  const [researchId, setResearchId] = useState("");
  const [showPhotos, setShowPhotos] = useState(false);
  const [independent, setIndependent] = useState(false);
  const action = useMutation({
    mutationFn: ({ route, data }: { route: string; data?: Record<string, unknown> }) =>
      post<ClinicalReport>(`${root}/${route}`, { ...data, request_id: crypto.randomUUID() }),
    onSuccess: (report) => {
      saveStage(report.stage);
      setIndependent(false);
      select((current) => ({ ...current, [report.stage]: report.id }));
      if (report.stage === "research" && report.status === "research") setResearchId(report.id);
      client.setQueryData<{ enabled: boolean; reports: ClinicalReport[] }>(
        [...clinicalQueryKey(id), false],
        (available) => available ? {
          ...available,
          reports: [report, ...available.reports.filter((item) => item.id !== report.id)],
        } : available,
      );
      void client.invalidateQueries({ queryKey: clinicalQueryKey(id) });
    },
  });
  if (query.isPending) return <Loading />;
  if (query.isError) return <Notice error>{query.error.message}</Notice>;
  if (!query.data.enabled) return <Notice>Clinical reports are unavailable. <Link href={casePath(id)}>Return to case</Link></Notice>;
  const reports = query.data.reports;
  const history = reports.filter((item) => item.stage === stage);
  const report = history.find((item) => item.id === selected[stage]) ?? history[0];
  const research = reports.filter((item) => item.status === "research" && !item.stale);
  const assessments = reports.filter((item) => item.stage === "assessment" && item.status === "draft" && !item.stale);
  const latestResearch = research.find((item) => item.id === researchId) ?? research[0];
  const urgentResearch = report?.status === "research" && report.urgent && !report.stale ? report : null;
  const currentUrgent = [...research, ...assessments].some((item) => item.urgent);
  const formatVersion = (item: ClinicalReport) =>
    `${new Date(item.created_at).toLocaleString()} · ${item.locale.toUpperCase()} · ${item.status}${item.stale ? " · Earlier case revision" : ""}`;
  const download = report && `/api/backend/${root}/reports/${report.id}/file`;
  const editable = report?.stale || independent ? null : report?.editable;

  function finalSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    action.mutate({
      route: submitter?.getAttribute("value") === "sign" ? "final/sign" : "final/review",
      data: { ...data, assessment_id: data.assessment_id || null, research_id: data.research_id || null, draft_id: data.draft_id || null },
    });
  }

  return <div className="clinical-reports stack">
    <div className="page-heading"><div><h1>Clinical reports</h1><div className="button-row">
      <Link className="button secondary" href={casePath(id)}>Back to case</Link>
      <Link className="button secondary" href={reportPath(id)}>Legacy analysis report</Link>
      <button className="button secondary" type="button" aria-expanded={showPhotos} onClick={() => setShowPhotos(!showPhotos)}>Clinical photos</button>
    </div></div></div>
    {showPhotos && <ClinicalPhotos caseId={id} locked />}
    {currentUrgent && <Notice><strong>Urgent concern recorded.</strong> Review the findings and referral handoff in the research or assessment report.</Notice>}
    {!currentUrgent && reports.some((item) => item.stale && item.urgent) && <Notice><strong>An earlier report recorded an urgent concern.</strong> Review it alongside the current case.</Notice>}
    <nav className="button-row" aria-label="Clinical report sections">
      {stages.map((item) => <button key={item} type="button" className={`button ${stage === item ? "primary" : "secondary"}`} aria-pressed={stage === item} onClick={() => saveStage(item)}>{titles[item]}</button>)}
    </nav>
    <Panel title={titles[stage]}>
      <div className="panel-padding stack">
        {action.isPending && <p role="status">Working <ProgressDots /></p>}
        {action.isError && <Notice error>{action.error.message}</Notice>}
        {stage === "research" && <div className="stack">
          <label className="field">Search method<select value={mode} onChange={(event) => setMode(event.target.value)}>
            {searchModeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select></label>
          <div><button type="button" className="button primary" disabled={action.isPending} onClick={() => action.mutate({ route: "research", data: { search_mode: mode } })}>Run research</button></div>
          {urgentResearch && <form className="stack" onSubmit={(event) => {
            event.preventDefault();
            action.mutate({ route: "research", data: { search_mode: mode, research_id: urgentResearch.id, disposition: disposition.trim() } });
          }}>
            <label className="field">Practitioner’s urgency assessment and referral disposition<textarea required minLength={5} maxLength={1000} value={disposition} onChange={(event) => setDisposition(event.target.value)} /></label>
            <div><button className="button secondary" disabled={action.isPending}>Record review and look up references</button></div>
          </form>}
        </div>}
        {stage === "assessment" && <div className="stack">
          <label className="field">Research version<select value={latestResearch?.id ?? ""} onChange={(event) => setResearchId(event.target.value)}>
            {!research.length && <option value="">Run research first</option>}
            {research.map((item) => <option key={item.id} value={item.id}>{formatVersion(item)}</option>)}
          </select></label>
          <div><button type="button" className="button primary" disabled={!latestResearch || action.isPending} onClick={() => action.mutate({ route: "assessment", data: { research_id: latestResearch?.id } })}>Generate assessment draft</button></div>
        </div>}
        {stage === "final" && <form key={editable ? report?.id : "new"} className="stack clinical-edit" onSubmit={finalSubmit}>
          {editable && <div><button type="button" className="button secondary" onClick={() => setIndependent(true)}>Start independent report</button></div>}
          <div className="clinical-grid">
            <label className="field">Language<select name="locale" defaultValue={report?.locale ?? "en"}><option value="en">English</option><option value="ur">Urdu</option></select></label>
            <label className="field">Decision<select name="decision" defaultValue={editable ? report?.decision ?? "independent" : "independent"}>
              <option value="independent">Independent report</option><option value="accepted">Accept AI assessment</option>
              <option value="modified">Modify AI assessment</option><option value="rejected">Reject AI assessment</option>
            </select></label>
            <label className="field">AI assessment reviewed<select name="assessment_id" defaultValue={editable?.assessment_id ?? ""}>
              <option value="">No assessment selected</option>{assessments.map((item) => <option key={item.id} value={item.id}>{formatVersion(item)}</option>)}
            </select></label>
            <label className="field">Research reviewed<select name="research_id" defaultValue={editable?.research_id ?? ""}>
              <option value="">Use linked research, if any</option>{research.map((item) => <option key={item.id} value={item.id}>{formatVersion(item)}</option>)}
            </select></label>
          </div>
          {report && editable && <input type="hidden" name="draft_id" value={report.id} />}
          <label className="field">Clinician name<input name="author" required minLength={2} maxLength={150} defaultValue={editable?.author ?? ""} /></label>
          <label className="field">Clinical assessment<textarea name="assessment" dir="auto" required minLength={5} maxLength={8000} defaultValue={editable?.assessment ?? ""} /></label>
          <label className="field">Care and follow-up<textarea name="care_plan" dir="auto" required minLength={5} maxLength={8000} defaultValue={editable?.care_plan ?? ""} /></label>
          <label className="field">Prescription, if appropriate<textarea name="prescription" dir="auto" maxLength={6000} defaultValue={editable?.prescription ?? ""} /></label>
          <label className="field">Reason for modifying or rejecting<textarea name="reason" dir="auto" maxLength={4000} defaultValue={editable?.reason ?? ""} /></label>
          <label className="field">Urgency assessment and disposition<textarea name="urgency_disposition" dir="auto" maxLength={4000} defaultValue={editable?.urgency_disposition ?? ""} /></label>
          <div className="button-row"><button className="button secondary" disabled={action.isPending}>Save review</button>
            <button className="button primary" value="sign" disabled={action.isPending}>Sign this language version</button></div>
        </form>}
        {history.length > 0 && <label className="field">Report history<select value={report?.id ?? ""} onChange={(event) => {
          setIndependent(false);
          select({ ...selected, [stage]: event.target.value });
        }}>
          {history.map((item) => <option key={item.id} value={item.id}>{formatVersion(item)}</option>)}
        </select></label>}
        {report && <>
          <div className="button-row">
            <Badge tone={report.stale ? "warn" : report.status === "signed" ? "good" : "neutral"}>{report.stale ? "Earlier case revision" : report.status}</Badge>
            <a className="button secondary" href={`${download}?format=pdf`}><Download size={16} /> PDF</a>
            <a className="button secondary" href={`${download}?format=docx`}><Download size={16} /> DOCX</a>
            <button className="button secondary" type="button" onClick={() => window.print()}><Printer size={16} /> Print</button>
            {stage === "assessment" && report.status === "draft" && report.source_id && <button className="button secondary" type="button" onClick={() => {
              if (!report.source_id) return;
              saveStage("research");
              select({ ...selected, research: report.source_id });
            }}>View source research</button>}
            {stage !== "final" && report.locale === "en" && <button className="button secondary" type="button" disabled={action.isPending} onClick={() => action.mutate({ route: `reports/${report.id}/urdu` })}>Translate to Urdu</button>}
          </div>
          <ReportContent report={report} />
        </>}
      </div>
    </Panel>
  </div>;
}
