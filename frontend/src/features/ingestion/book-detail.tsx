"use client";

import { useState } from "react";
import { Badge, Empty, Loading, Metric, Notice, number, Panel, Progress } from "@/components/ui";
import { isLive, useBookIngestion, useJobEvents, usePause, usePrepare, useStart } from "./api";
import { ConfirmEmbedding } from "./confirm-dialog";
import { EventTable } from "./events";
import { allEmbedded, indexState, jobTone, rpmLabel, startLabel, stateLabel, stateTone, when } from "./format";
import { ChunkInspector, TextInspector } from "./inspectors";
import type { JobOut, PlanOut } from "./types";

function Limits({ plan }: { plan: PlanOut }) {
  const { limits } = plan;
  const rows: [string, string][] = [
    ["Provider host", limits.endpoint_host],
    ["Model", `${limits.model} (${number(limits.dimension)} dimensions)`],
    ["Limit for this job", `${number(plan.effective_token_limit)} tokens (per-job cap ${number(limits.per_job_token_limit)})`],
    ["Budget used", `${number(limits.budget_tokens_used)} of ${number(limits.budget_token_limit)} tokens`],
    ["Budget remaining", `${number(limits.budget_tokens_remaining)} tokens`],
    ["Batch size", `${number(limits.batch_tokens)} tokens`],
    ["Request pace", rpmLabel(limits.requests_per_minute)],
  ];
  return (
    <Panel title="Limits" description="Spending limits that apply to every embedding job.">
      <div className="panel-padding">
        <Progress value={limits.budget_tokens_used} total={limits.budget_token_limit} label="Token budget used" />
        <dl className="measurements">{rows.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl>
      </div>
    </Panel>
  );
}

function LiveJob({ job }: { job: JobOut }) {
  return (
    <Panel title="Embedding in progress" description={`Job status: ${job.status}, stage: ${job.stage}. Refreshes every 3 seconds.`}>
      <div className="panel-padding">
        <Progress value={job.processed_chunks} total={job.total_chunks} label={`${number(job.processed_chunks)} of ${number(job.total_chunks)} chunks processed`} />
        <p className="fine-print">Tokens used: {number(job.embedded_tokens)} of {job.token_limit === null ? "no job limit" : number(job.token_limit)}</p>
        {job.pause_requested && <Notice>Pause requested, finishing the current batch.</Notice>}
      </div>
    </Panel>
  );
}

export function BookDetail({ bookId }: { bookId: string }) {
  const query = useBookIngestion(bookId);
  const prepare = usePrepare(bookId);
  const start = useStart(bookId);
  const pause = usePause();
  const [confirming, setConfirming] = useState(false);
  const [eventsOf, setEventsOf] = useState<string | null>(null);
  const jobEvents = useJobEvents(eventsOf);

  if (query.isPending) return <Loading />;
  if (query.isError) return <Notice error>{query.error.message}</Notice>;
  const { plan, jobs, events } = query.data;
  const { stats, limits } = plan;
  const state = indexState(stats);
  const live = plan.active_job && isLive(plan.active_job.status) ? plan.active_job : null;
  const label = startLabel(plan);
  const startBlocked = !plan.can_start || allEmbedded(plan) || live !== null || start.isPending;
  const error = prepare.error ?? start.error ?? pause.error;

  return (
    <>
      <Panel title={stats.title} description={`${stats.source_filename} · ${stats.total_pages === null ? "page count unavailable" : `${number(stats.total_pages)} PDF pages`}`}
        action={<Badge tone={stateTone[state]}>{stateLabel[state]}</Badge>}>
        <div className="panel-padding">
          <Progress value={stats.embedded_chunks} total={stats.total_chunks} label="Chunks embedded" />
          <div className="metric-grid three">
            <Metric label="Chunks" value={number(stats.total_chunks)} detail={`${number(stats.embedded_chunks)} embedded, ${number(stats.pending_chunks)} pending`} />
            <Metric label="Tokens embedded" value={number(stats.embedded_tokens)} detail="Already stored, never billed again" />
            <Metric label="Tokens pending" value={number(stats.pending_tokens)} detail="Estimated cost of finishing this book" />
          </div>
          {!stats.complete && stats.prepared && <p className="fine-print">This book is only partly searchable until every chunk has a vector.</p>}
        </div>
      </Panel>

      {limits.provider_paused && <Notice error>Provider stop is set: embedding is blocked. {limits.provider_pause_reason ?? "No reason was recorded."}</Notice>}
      {stats.frozen_plan && <Notice>This book belongs to the command-line pipeline (frozen plan). It cannot be embedded from this screen.</Notice>}
      {!stats.frozen_plan && !plan.can_start && plan.blockers.length > 0 && (
        <Notice error><strong>Embedding cannot start:</strong><ul>{plan.blockers.map((b) => <li key={b}>{b}</li>)}</ul></Notice>
      )}
      {error && <Notice error>{error.message}</Notice>}

      <Limits plan={plan} />

      {live && <LiveJob job={live} />}

      {!stats.frozen_plan && (
        <div className="button-row">
          <button className="button secondary" disabled={prepare.isPending || live !== null} onClick={() => prepare.mutate()}>{prepare.isPending ? "Preparing..." : "Prepare"}</button>
          <button className="button primary" disabled={startBlocked} onClick={() => setConfirming(true)}>{label}</button>
          <button className="button secondary" disabled={!live || live.pause_requested || pause.isPending} onClick={() => live && pause.mutate(live.id)}>Pause</button>
        </div>
      )}
      <p className="fine-print">Prepare splits the text into chunks and is free. Embedding sends chunks to the provider and spends paid tokens.</p>

      {confirming && (
        <ConfirmEmbedding plan={plan} label={label} busy={start.isPending} onCancel={() => setConfirming(false)}
          onConfirm={() => start.mutate({ confirmed: true }, { onSettled: () => setConfirming(false) })} />
      )}

      <Panel title="Recent jobs" description="The last jobs for this book. Select one to see only its events.">
        {jobs.length === 0 ? <Empty title="No jobs yet">No embedding job has been started for this book.</Empty> : (
          <div className="table-scroll"><table><thead><tr><th>Status</th><th>Stage</th><th>Chunks</th><th>Tokens</th><th>Started</th><th>Stop reason</th><th /></tr></thead>
            <tbody>{jobs.map((j) => (
              <tr key={j.id}>
                <td><Badge tone={jobTone(j)}>{j.status}</Badge></td><td>{j.stage}</td>
                <td>{number(j.processed_chunks)} of {number(j.total_chunks)}</td><td>{number(j.embedded_tokens)}</td>
                <td>{when(j.started_at ?? j.created_at)}</td><td className="event-message">{j.error ?? j.stop_reason ?? ""}</td>
                <td><button className="text-link" onClick={() => setEventsOf(eventsOf === j.id ? null : j.id)}>{eventsOf === j.id ? "Show all events" : "Show job events"}</button></td>
              </tr>
            ))}</tbody></table></div>
        )}
      </Panel>

      {eventsOf !== null && (jobEvents.isPending ? <Loading /> : jobEvents.isError ? <Notice error>{jobEvents.error.message}</Notice>
        : <EventTable events={jobEvents.data} title="Job events" description="History and errors of the selected job." />)}
      {eventsOf === null && <EventTable events={events} title="Event history" description="The latest events for this book. Errors are highlighted." />}

      {stats.total_chunks > 0 ? <ChunkInspector key={`c-${bookId}`} bookId={bookId} /> : <Empty title="No chunks to inspect">Prepare this book to split its text into chunks.</Empty>}
      <TextInspector key={`t-${bookId}`} bookId={bookId} />
    </>
  );
}
