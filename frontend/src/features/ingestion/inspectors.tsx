"use client";

import { useState } from "react";
import { Badge, Empty, Loading, Notice, number, Panel } from "@/components/ui";
import { CHUNKS_PER_PAGE, TEXT_PAGES_PER_VIEW, useChunks, useText } from "./api";
import type { EmbeddedFilter } from "./types";

const pageRange = (start: number | null, end: number | null) =>
  start === null ? "PDF page unavailable" : end === null || end === start ? `PDF page ${start}` : `PDF pages ${start}-${end}`;

function Pager({ offset, step, total, onChange, noun }: { offset: number; step: number; total: number; onChange: (offset: number) => void; noun: string }) {
  return (
    <div className="button-row pager">
      <button className="button secondary" disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - step))}>Previous {noun}</button>
      <span className="fine-print">{total === 0 ? "None" : `${number(offset + 1)}-${number(Math.min(offset + step, total))} of ${number(total)}`}</span>
      <button className="button secondary" disabled={offset + step >= total} onClick={() => onChange(offset + step)}>Next {noun}</button>
    </div>
  );
}

export function ChunkInspector({ bookId }: { bookId: string }) {
  const [offset, setOffset] = useState(0);
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  const [embedded, setEmbedded] = useState<EmbeddedFilter>("");
  const query = useChunks(bookId, offset, q, embedded);
  return (
    <Panel title="Chunk inspector" description={`${CHUNKS_PER_PAGE} chunks per page. Page numbers are PDF page numbers, not printed page numbers.`}>
      <div className="panel-padding">
        <form className="toolbar" onSubmit={(e) => { e.preventDefault(); setOffset(0); setQ(draft.trim()); }}>
          <div className="field"><label htmlFor="chunk-q">Search chunk text</label><input id="chunk-q" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={200} /></div>
          <div className="field"><label htmlFor="chunk-embedded">Vector status</label>
            <select id="chunk-embedded" value={embedded} onChange={(e) => { setOffset(0); setEmbedded(e.target.value as EmbeddedFilter); }}>
              <option value="">All chunks</option><option value="true">Embedded only</option><option value="false">Not embedded only</option>
            </select></div>
          <button className="button secondary" type="submit">Apply search</button>
        </form>
        {query.isPending ? <Loading /> : query.isError ? <Notice error>{query.error.message}</Notice> : query.data.items.length === 0 ? <Empty title="No chunks found">{q || embedded ? "No chunk matches this search and filter." : "This book has no chunks yet. Prepare it first."}</Empty> : (
          <>
            <p className="fine-print">{number(query.data.total)} matching chunks</p>
            <div className="table-scroll"><table><thead><tr><th>#</th><th>Where</th><th>Section</th><th>Tokens</th><th>Vector</th><th>Text</th></tr></thead>
              <tbody>{query.data.items.map((c) => (
                <tr key={c.id}>
                  <td>{c.chunk_index}</td><td>{pageRange(c.page_start, c.page_end)}</td>
                  <td className="event-message">{c.section_path.length ? c.section_path.join(" > ") : c.section_heading ?? "No section"}</td>
                  <td>{c.token_count === null ? "Unavailable" : `${number(c.token_count)} tokens`}</td>
                  <td><Badge tone={c.embedded ? "good" : "warn"}>{c.embedded ? "Embedded" : "Not embedded"}</Badge></td>
                  <td className="event-message">{c.content.length > 220 ? `${c.content.slice(0, 220)}...` : c.content}</td>
                </tr>
              ))}</tbody></table></div>
            <Pager offset={query.data.offset} step={CHUNKS_PER_PAGE} total={query.data.total} onChange={setOffset} noun="chunks" />
          </>
        )}
      </div>
    </Panel>
  );
}

export function TextInspector({ bookId }: { bookId: string }) {
  const [offset, setOffset] = useState(0);
  const query = useText(bookId, offset);
  return (
    <Panel title="Extracted text" description={`${TEXT_PAGES_PER_VIEW} PDF pages per view, exactly as extracted from the file.`}>
      <div className="panel-padding">
        {query.isPending ? <Loading /> : query.isError ? <Notice error>{query.error.message}</Notice> : query.data.pages.length === 0 ? <Empty title="No extracted text">No text was extracted for this range of PDF pages.</Empty> : (
          <>
            {query.data.pages.map((p) => (
              <div key={p.page} className="text-page">
                <strong>PDF page {p.page}</strong> <span className="fine-print">{number(p.chars)} characters</span>
                {p.truncated && <> <Badge tone="warn">Truncated for display</Badge></>}
                <pre className="text-preview">{p.text}</pre>
              </div>
            ))}
            <Pager offset={query.data.offset} step={TEXT_PAGES_PER_VIEW} total={query.data.total_pages} onChange={setOffset} noun="pages" />
          </>
        )}
      </div>
    </Panel>
  );
}
