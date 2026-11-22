"use client";

import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { z } from "zod";
import { Search as SearchIcon } from "lucide-react";
import { Badge, Empty, Notice, number, Panel } from "@/components/ui";
import { api, categoryLabel } from "./api";
import type { SearchResult, Snapshot } from "./types";

const schema = z.object({ query: z.string().trim().min(1, "Enter a search query.").max(2000, "Use 2,000 characters or fewer."), k: z.number().int().min(1).max(50), category: z.enum(["", "materia_medica", "repertory", "organon", "general"]), threshold: z.number().min(-1).max(1) });
type SearchFields = z.infer<typeof schema>;

function SearchConfirmation({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) {
      if (typeof element.showModal === "function") element.showModal();
      else element.setAttribute("open", "");
    }
    return () => { if (element?.open && typeof element.close === "function") element.close(); };
  }, []);
  return <dialog ref={dialog} className="modal" aria-modal="true" aria-labelledby="search-confirm-title" onCancel={onCancel}><h2 id="search-confirm-title">Confirm embedding API request</h2><p>This search sends your query to the embedding provider. It may consume free allowance or incur a charge. Account-wide remaining balance is unknown. Do not enter patient information.</p><p>Search usage is not part of the Phase 2B ingestion ledger.</p><div className="button-row"><button autoFocus className="button secondary" onClick={onCancel}>Cancel</button><button className="button primary" onClick={onConfirm}>Confirm search</button></div></dialog>;
}

function pageRange(start: number, end?: number | null) {
  return end != null && end !== start ? `PDF pages ${start}–${end}` : `PDF page ${start}`;
}

export function Search({ data }: { data: Snapshot }) {
  const [confirm, setConfirm] = useState<SearchFields | null>(null);
  const [book, setBook] = useState("");
  const paused = data.provider_paused ?? data.status === "stopped_provider_http_429";
  const { register, handleSubmit, formState: { errors } } = useForm<SearchFields>({ resolver: zodResolver(schema), defaultValues: { query: "", k: 5, category: "", threshold: 0 } });
  const search = useMutation({ mutationFn: async (value: SearchFields) => {
    return api<SearchResult>("search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...value, category: value.category || null }) });
  } });
  const results = search.data?.results.filter((p) => !book || p.book_id === book) ?? [];
  return <><div className="page-heading"><div><span className="eyebrow">RETRIEVAL EVALUATION</span><h1>RAG Search</h1><p>Test whether the right source passages surface for your query.</p></div><Badge>Retrieval only</Badge></div>
    {paused && <Notice>The embedding provider stop is set, so meaning-based search is off. Searches use keyword matching on the stored text instead; no provider call is made.</Notice>}
    {search.data?.retrieval_mode === "keyword" && <Notice error>Keyword matching, not meaning-based search: passages that use different words for the same idea can be missed. Treat results as a starting point.</Notice>}
    <Panel title="Search your knowledge base" description="Results contain retrieved passages, not generated clinical advice."><form className="search-form" onSubmit={handleSubmit((value) => setConfirm(value))} noValidate><label htmlFor="rag-query">Search query</label><textarea id="rag-query" rows={3} placeholder="Describe the concept or passage you want to find…" {...register("query")} aria-invalid={!!errors.query} aria-describedby={errors.query ? "rag-error" : undefined} />{errors.query && <p id="rag-error" className="field-error" role="alert">{errors.query.message}</p>}<div className="filter-grid"><div className="field"><label htmlFor="rag-source">Knowledge source</label><select id="rag-source" {...register("category")}><option value="">All sources</option>{["materia_medica", "repertory", "organon", "general"].map((c) => <option value={c} key={c}>{categoryLabel[c]}</option>)}</select></div><div className="field"><label htmlFor="rag-k">Top K · 1–50</label><input id="rag-k" type="number" min={1} max={50} {...register("k", { valueAsNumber: true })} />{errors.k && <p className="field-error" role="alert">Choose 1–50 results.</p>}</div><div className="field"><label htmlFor="rag-threshold">Similarity threshold · −1 to 1</label><input id="rag-threshold" type="number" min={-1} max={1} step={0.05} {...register("threshold", { valueAsNumber: true })} />{errors.threshold && <p className="field-error" role="alert">Choose a threshold from −1 to 1.</p>}</div></div><div className="search-actions"><p className="fine-print">Each search uses embedding API tokens and stores a retrieval evaluation.</p><button className="button primary" disabled={search.isPending}><SearchIcon size={16} />{search.isPending ? "Searching…" : "Review and search"}</button></div></form></Panel>
    {confirm && <SearchConfirmation onCancel={() => setConfirm(null)} onConfirm={() => { search.mutate(confirm); setConfirm(null); }} />}
    {search.isError && <Notice error>{search.error.message}</Notice>}
    <Panel title="Retrieved passages" description={search.data ? `${search.data.results.length} returned · ${number(search.data.latency_ms)} ms` : "Your results will appear here after a search."} action={<select aria-label="Filter returned results by book" value={book} onChange={(e) => setBook(e.target.value)}><option value="">All returned books</option>{[...new Map(search.data?.results.map((p) => [p.book_id, p.book_title]) ?? []).entries()].map(([id, title]) => <option value={id} key={id}>{title}</option>)}</select>}><div className="panel-padding">{!!search.data?.incomplete_books?.length && <Notice error>Some results come from partly indexed books: {search.data.incomplete_books.join(", ")}. Results may be missing evidence from the unindexed parts of these books.</Notice>}<p className="fine-print">Book selection filters returned results only. The backend does not support book-scoped vector search.</p>{search.data ? results.length ? <div className="chunk-list">{results.map((p, i) => <article className="chunk-card" key={p.chunk_id}><div className="chunk-top"><div><Badge>Result {i + 1}</Badge><strong>{p.book_title}</strong></div><Badge tone="good">{p.retrieval_mode === "keyword" ? "Keyword score" : "Similarity"} {p.similarity.toFixed(3)}</Badge></div><small>{p.section_heading ?? (p.section_path.join(" › ") || "Section unavailable")} · {categoryLabel[p.book_category] ?? p.book_category}</small>{p.section_path.length > 0 && <small>Section path: {p.section_path.join(" › ")}</small>}{p.page_start != null && <small>{pageRange(p.page_start, p.page_end)}</small>}{p.book_complete === false && <div><Badge tone="warn">from a partly indexed book</Badge></div>}<p className="passage-text">{p.content}</p><div className="chunk-meta"><span>Source chunk: {p.chunk_id}</span></div></article>)}</div> : <Empty title="No matching passages">Try a different query, source or similarity threshold.</Empty> : <Empty title="Ready to inspect retrieval">Enter a query to review its source passages.</Empty>}</div></Panel>
  </>;
}
