"use client";

import { useState } from "react";
import { Badge, Empty, Loading, Notice, number, Panel, Progress } from "@/components/ui";
import { useOverview } from "./api";
import { BookDetail } from "./book-detail";
import { indexState, stateLabel, stateTone } from "./format";

export function IngestionJobs() {
  const overview = useOverview();
  const [picked, setPicked] = useState<string | null>(null);
  const header = (
    <div className="page-heading"><div><span className="eyebrow">EMBEDDING CONTROL</span><h1>Ingestion Jobs</h1><p>Prepare books for free, then embed them within a token budget you confirm first.</p></div></div>
  );
  if (overview.isPending) return <>{header}<Loading /></>;
  if (overview.isError) {
    return <>{header}<Notice error>{overview.error.message}</Notice><div className="button-row"><button className="button secondary" onClick={() => void overview.refetch()}>Try again</button></div></>;
  }
  const { books, limits } = overview.data;
  if (books.length === 0) return <>{header}<Empty title="No books registered">Upload a PDF on the Books page. It will appear here, ready to prepare.</Empty></>;
  const selected = books.find((b) => b.book_id === picked) ?? null;

  return (
    <>
      {header}
      {limits.provider_paused && <Notice error>Provider stop is set: embedding is blocked. {limits.provider_pause_reason ?? "No reason was recorded."}</Notice>}
      <Panel title="Books" description={`Index progress comes from the database. Budget used: ${number(limits.budget_tokens_used)} of ${number(limits.budget_token_limit)} tokens.`}>
        <div className="table-scroll"><table><thead><tr><th>Book</th><th>Index</th><th>Chunks embedded</th><th>Tokens pending</th><th /></tr></thead>
          <tbody>{books.map((b) => {
            const state = indexState(b);
            return (
              <tr key={b.book_id}>
                <td><strong>{b.title}</strong><br /><small>{b.source_filename}</small></td>
                <td><Badge tone={stateTone[state]}>{stateLabel[state]}</Badge>{b.frozen_plan && <> <Badge>Command-line plan</Badge></>}</td>
                <td>{b.total_chunks === 0 ? "No chunks yet" : <><Progress value={b.embedded_chunks} total={b.total_chunks} label={`${b.title} embedded`} /><span className="fine-print">{number(b.embedded_chunks)} of {number(b.total_chunks)} chunks</span></>}</td>
                <td>{number(b.pending_tokens)}</td>
                <td><button className="button secondary" aria-pressed={selected?.book_id === b.book_id} onClick={() => setPicked(b.book_id)}>{selected?.book_id === b.book_id ? "Selected" : "Select"}</button></td>
              </tr>
            );
          })}</tbody></table></div>
      </Panel>
      {selected ? <BookDetail key={selected.book_id} bookId={selected.book_id} /> : <Empty title="Select a book">Choose a book above to see its plan, limits, history and text.</Empty>}
    </>
  );
}
