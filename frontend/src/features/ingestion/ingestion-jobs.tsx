"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, FileDown } from "lucide-react";
import { Badge, Empty, Loading, Notice, number, Panel, Progress } from "@/components/ui";
import { useOverview, useStartAuto, useStopAuto } from "./api";
import { ConfirmAuto } from "./auto-resume";
import { BookDetail } from "./book-detail";
import { ATTENTION_STATES, autoBlocker, percentDone } from "./format";
import { StatusChip } from "./status";
import type { AutoResult } from "./types";

export function IngestionJobs() {
  const overview = useOverview();
  const startAuto = useStartAuto();
  const stopAuto = useStopAuto();
  const [picked, setPicked] = useState<string | null>(null);
  const [completedShown, setCompletedShown] = useState(false);
  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
  const [confirmIds, setConfirmIds] = useState<string[] | null>(null);
  const sending = useRef(false);
  const [result, setResult] = useState<AutoResult | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  /** A server-made PDF listing every book's PDF document name (no AI call, nothing stored). */
  const exportList = async () => {
    if (exporting) return;
    setExporting(true);
    setExportError(null);
    try {
      const response = await fetch("/api/backend/ingestion/books/list.pdf");
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(typeof body.detail === "string" ? body.detail : "The list could not be created. Try again.");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "ingestion-book-list.pdf";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (error) {
      setExportError(error instanceof Error ? error.message : "The list could not be created. Try again.");
    } finally {
      setExporting(false);
    }
  };
  const header = (
    <div className="page-heading"><div><span className="eyebrow">EMBEDDING CONTROL</span><h1>Ingestion Jobs</h1><p>Prepare books for free, then embed them within a token budget you confirm first.</p></div>
      <button type="button" className="button secondary" disabled={exporting} onClick={() => void exportList()}><FileDown size={17} /> {exporting ? "Preparing PDF…" : "Download book list (PDF)"}</button>
    </div>
  );
  const books = overview.data?.books;
  const eligible = useMemo(() => (books ?? []).filter((b) => autoBlocker(b) === null), [books]);
  if (overview.isPending) return <>{header}<Loading /></>;
  if (overview.isError) {
    return <>{header}<Notice error>{overview.error.message}</Notice><div className="button-row"><button className="button secondary" onClick={() => void overview.refetch()}>Try again</button></div></>;
  }
  const { limits } = overview.data;
  const all = overview.data.books;
  if (all.length === 0) return <>{header}<Empty title="No books registered">Upload a PDF on the Books page. It will appear here, ready to prepare.</Empty></>;
  const selected = all.find((b) => b.book_id === picked) ?? null;
  // Two groups: what still needs work (running first, then the queue in order) and what is done.
  const rank: Record<string, number> = { running: 0, stalled: 1, queued: 2, paused: 3, error: 3, interrupted: 3, partial: 4, ready: 5, not_prepared: 6 };
  const remaining = all
    .filter((b) => b.state !== "complete")
    .sort((a, b) => (rank[a.state] ?? 9) - (rank[b.state] ?? 9) || (a.auto_resume.position ?? 99) - (b.auto_resume.position ?? 99));
  const completed = all.filter((b) => b.state === "complete");

  const chosen = eligible.filter((b) => checked.has(b.book_id));
  const chosenTokens = chosen.reduce((sum, b) => sum + b.pending_tokens, 0);
  const allChosen = eligible.length > 0 && chosen.length === eligible.length;
  const autoOn = all.filter((b) => b.auto_resume.enabled);
  const running = all.filter((b) => b.state === "running");
  const waiting = autoOn.filter((b) => b.state !== "running").length;
  const attention = all.filter((b) => (ATTENTION_STATES as readonly string[]).includes(b.state)).length;
  const blockedReason = limits.provider_paused ? "The embedding provider stop is set" : null;
  const toggle = (id: string) => setChecked((prev) => { const next = new Set(prev); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const dialogBooks = confirmIds === null ? [] : eligible.filter((b) => confirmIds.includes(b.book_id));
  const confirm = () => {
    if (sending.current || startAuto.isPending || dialogBooks.length === 0) return;
    sending.current = true;
    startAuto.mutate({ book_ids: dialogBooks.map((b) => b.book_id), confirmed: true }, {
      onSuccess: (data) => { setResult(data); setChecked(new Set()); },
      onSettled: () => { sending.current = false; setConfirmIds(null); },
    });
  };
  const stop = (ids?: string[]) => { setResult(null); stopAuto.mutate(ids); };
  const actionError = startAuto.error ?? stopAuto.error;

  const renderRow = (b: (typeof all)[number]) => {
    const blocker = autoBlocker(b);
    return (
      <tr key={b.book_id}>
        <td><input type="checkbox" checked={blocker === null && checked.has(b.book_id)} disabled={blocker !== null}
          aria-label={blocker ? `Select ${b.title} (${blocker})` : `Select ${b.title} for automatic resume`} title={blocker ?? undefined} onChange={() => toggle(b.book_id)} /></td>
        <td><strong>{b.title}</strong><br /><small>{b.source_filename}</small></td>
        <td><StatusChip book={b} />{b.frozen_plan && <Badge>Command-line plan</Badge>}</td>
        <td>{b.total_chunks === 0 ? "No chunks yet" : <><Progress value={b.embedded_chunks} total={b.total_chunks} label={`${b.title} embedded`} /><span className="fine-print">{number(b.embedded_chunks)} of {number(b.total_chunks)} chunks</span></>}</td>
        <td>{number(b.pending_tokens)}</td>
        <td>
          <div className="button-row row-actions">
            <button className="button secondary" aria-pressed={selected?.book_id === b.book_id} onClick={() => setPicked(b.book_id)}>{selected?.book_id === b.book_id ? "Selected" : "Select"}</button>
            {b.auto_resume.enabled && <button className="button secondary" aria-label={`Stop auto for ${b.title}`} disabled={stopAuto.isPending} onClick={() => stop([b.book_id])}>Stop auto</button>}
          </div>
        </td>
      </tr>
    );
  };

  return (
    <>
      {header}
      {exportError && <Notice error>{exportError}</Notice>}
      {limits.provider_paused && <Notice error>Provider stop is set: embedding is blocked. {limits.provider_pause_reason ?? "No reason was recorded."}</Notice>}
      <div className="overview-strip ingestion-summary" aria-label="Ingestion summary">
        <div>
          <strong>{running.length} running · {waiting} waiting in auto queue · {attention} need attention</strong>
          {running.length > 0 && <p>Running now: {running.map((b) => `${b.title} — ${percentDone(b)}%`).join("; ")}</p>}
        </div>
      </div>
      {actionError && <Notice error>{actionError.message}</Notice>}
      {result && (
        <Notice>
          <strong>{result.queued.length} {result.queued.length === 1 ? "book" : "books"} queued for automatic resume.</strong>
          {result.skipped.length > 0 && <ul>{result.skipped.map((s) => <li key={s.book_id}>{s.title ?? s.book_id} was skipped: {s.reason}</li>)}</ul>}
        </Notice>
      )}
      {(stopAuto.isPending || stopAuto.isSuccess) && <Notice>Stopping: the running job will finish its current batch.</Notice>}
      <Panel title={`In progress and waiting (${remaining.length})`} description={`Running first, then the automatic queue in order. Index progress comes from the database. Budget used: ${number(limits.budget_tokens_used)} of ${number(limits.budget_token_limit)} tokens.`}>
        <div className="panel-padding auto-toolbar">
          <div className="button-row">
            {chosen.length > 0 && (
              <button className="button primary" disabled={blockedReason !== null} onClick={() => setConfirmIds(chosen.map((b) => b.book_id))}>
                Resume selected automatically ({chosen.length} {chosen.length === 1 ? "book" : "books"}, ~{number(chosenTokens)} tokens)
              </button>
            )}
            <button className="button secondary" disabled={blockedReason !== null || eligible.length === 0} onClick={() => setConfirmIds(eligible.map((b) => b.book_id))}>Resume all</button>
            {autoOn.length > 0 && <button className="button secondary" disabled={stopAuto.isPending} onClick={() => stop()}>Stop automatic resume</button>}
          </div>
          {blockedReason && <p className="fine-print">Automatic resume is unavailable: {blockedReason}.</p>}
        </div>
        {remaining.length === 0 ? <div className="panel-padding"><p>Nothing is waiting: every book is fully embedded.</p></div> : (
          <div className="table-scroll"><table><thead><tr>
            <th><input type="checkbox" aria-label="Select all resumable" checked={allChosen} disabled={eligible.length === 0}
              onChange={() => setChecked(allChosen ? new Set() : new Set(eligible.map((b) => b.book_id)))} /></th>
            <th>Book</th><th>Status</th><th>Chunks embedded</th><th>Tokens pending</th><th /></tr></thead>
            <tbody>{remaining.map(renderRow)}</tbody></table></div>
        )}
      </Panel>
      <Panel title={`Completed (${completed.length})`} description="Every chunk of these books has a vector and is searchable."
        action={
          <button type="button" className="button secondary" aria-expanded={completedShown} onClick={() => setCompletedShown(!completedShown)}>
            {completedShown ? <ChevronUp size={16} aria-hidden /> : <ChevronDown size={16} aria-hidden />}
            {completedShown ? "Hide completed" : "Show completed"}
          </button>
        }>
        {completedShown && (completed.length === 0 ? <div className="panel-padding"><p>No book is complete yet.</p></div> : (
          <div className="table-scroll"><table><thead><tr>
            <th /><th>Book</th><th>Status</th><th>Chunks embedded</th><th>Tokens pending</th><th /></tr></thead>
            <tbody>{completed.map(renderRow)}</tbody></table></div>
        ))}
      </Panel>
      {confirmIds !== null && dialogBooks.length > 0 && <ConfirmAuto books={dialogBooks} limits={limits} busy={startAuto.isPending} onCancel={() => setConfirmIds(null)} onConfirm={confirm} />}
      {selected ? <BookDetail key={selected.book_id} bookId={selected.book_id} /> : <Empty title="Select a book">Choose a book above to see its plan, limits, history and text.</Empty>}
    </>
  );
}
