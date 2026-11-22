"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FileUp, Search } from "lucide-react";
import { Badge, bytes, Empty, Notice, number, Panel } from "@/components/ui";
import { api, categoryLabel, validatePdf } from "./api";
import { BookTable } from "./dashboard";
import type { BookIndexStats, IngestionOverview, RegisteredBook, Snapshot } from "./types";
const categoryHelp: Record<string, string> = {
  materia_medica: "Remedy descriptions: symptoms and characteristics of each remedy.",
  repertory: "Symptom-to-remedy indexes listing which remedies match each symptom.",
  organon: "Foundational philosophy and principles of homeopathic practice.",
  general: "Any other homeopathic reference that fits none of the above.",
};
const categories = ["materia_medica", "repertory", "organon", "general"] as const;
type UploadFields = { title: string; category: string; author: string; publisher: string; year: string; language: string; sourceUri: string };
type FieldErrors = Partial<Record<keyof UploadFields, string>>;
const emptyFields: UploadFields = { title: "", category: "materia_medica", author: "", publisher: "", year: "", language: "en", sourceUri: "" };

function validateFields(f: UploadFields): FieldErrors {
  const e: FieldErrors = {};
  if (!f.title.trim()) e.title = "Enter a title."; else if (f.title.trim().length > 300) e.title = "Use 300 characters or fewer.";
  if (f.author.trim().length > 300) e.author = "Use 300 characters or fewer.";
  if (f.publisher.trim().length > 300) e.publisher = "Use 300 characters or fewer.";
  if (f.sourceUri.trim().length > 500) e.sourceUri = "Use 500 characters or fewer.";
  if (f.year.trim() && !(/^\d{1,4}$/.test(f.year.trim()) && Number(f.year) <= 2100)) e.year = "Enter a year from 0 to 2100.";
  if (!f.language.trim()) e.language = "Enter a language code, for example en.";
  return e;
}

function UploadForm() {
  const client = useQueryClient();
  const [file, setFile] = useState<File>();
  const [fields, setFields] = useState<UploadFields>(emptyFields);
  const [fileError, setFileError] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const set = (key: keyof UploadFields) => (e: { target: { value: string } }) => setFields((f) => ({ ...f, [key]: e.target.value }));
  const upload = useMutation({ mutationFn: async () => {
    const body = new FormData();
    body.set("file", file!); body.set("title", fields.title.trim()); body.set("category", fields.category);
    const optional: [string, string][] = [["author", fields.author], ["publisher", fields.publisher], ["publication_year", fields.year], ["language", fields.language], ["source_uri", fields.sourceUri]];
    for (const [name, value] of optional) if (value.trim()) body.set(name, value.trim());
    return api<RegisteredBook>("books", { method: "POST", body });
  }, onSuccess: () => { void client.invalidateQueries({ queryKey: ["registered-books"] }); void client.invalidateQueries({ queryKey: ["ingestion-overview"] }); void client.invalidateQueries({ queryKey: ["snapshot"] }); setFile(undefined); setFields(emptyFields); } });
  const err = (key: keyof UploadFields) => errors[key] && <p className="field-error" role="alert">{errors[key]}</p>;
  return <Panel title="Register a PDF" description="Upload extracts and saves the text only. Nothing is sent to an embedding provider."><form className="form-grid" noValidate onSubmit={(event) => { event.preventDefault(); const fe = validatePdf(file); const ve = validateFields(fields); setFileError(fe ?? ""); setErrors(ve); if (!fe && !Object.keys(ve).length) upload.mutate(); }}>
    <div className="field"><label htmlFor="pdf-file">PDF file · maximum 50 MB</label><input id="pdf-file" type="file" accept=".pdf,application/pdf" onChange={(e) => { const next = e.target.files?.[0]; setFile(next); setFileError(validatePdf(next) ?? ""); upload.reset(); }} />{fileError && <p className="field-error" role="alert">{fileError}</p>}</div>
    <div className="field"><label htmlFor="book-title">Book title</label><input id="book-title" value={fields.title} maxLength={300} aria-invalid={!!errors.title} onChange={set("title")} />{err("title")}</div>
    <div className="field"><label htmlFor="upload-category">Category</label><select id="upload-category" value={fields.category} onChange={set("category")}>{categories.map((c) => <option key={c} value={c}>{categoryLabel[c]}</option>)}</select><ul className="fine-print">{categories.map((c) => <li key={c}><strong>{categoryLabel[c]}:</strong> {categoryHelp[c]}</li>)}</ul></div>
    <div className="field"><label htmlFor="book-author">Author (optional)</label><input id="book-author" value={fields.author} maxLength={300} aria-invalid={!!errors.author} onChange={set("author")} />{err("author")}</div>
    <div className="field"><label htmlFor="book-publisher">Publisher (optional)</label><input id="book-publisher" value={fields.publisher} maxLength={300} aria-invalid={!!errors.publisher} onChange={set("publisher")} />{err("publisher")}</div>
    <div className="field"><label htmlFor="book-year">Publication year (optional)</label><input id="book-year" inputMode="numeric" value={fields.year} aria-invalid={!!errors.year} onChange={set("year")} />{err("year")}</div>
    <div className="field"><label htmlFor="book-language">Language</label><input id="book-language" value={fields.language} maxLength={20} aria-invalid={!!errors.language} onChange={set("language")} />{err("language")}</div>
    <div className="field"><label htmlFor="book-source">Source URI (optional)</label><input id="book-source" value={fields.sourceUri} maxLength={500} aria-invalid={!!errors.sourceUri} onChange={set("sourceUri")} />{err("sourceUri")}</div>
    <div className="field form-action"><button className="button primary" disabled={upload.isPending}>{upload.isPending ? "Registering…" : "Register book"}</button></div>
    {upload.isError && <Notice error>{upload.error.message}</Notice>}
    {upload.isSuccess && <Notice>Book saved. It is <strong>not searchable yet</strong>: it must be prepared and embedded first. <Link className="text-link" href="/workspace/ingestion">Open Ingestion Jobs</Link> to prepare it. Preparing is free; embedding spends provider tokens only after you confirm.</Notice>}
  </form></Panel>;
}

function IndexProgress({ stats, loading }: { stats?: BookIndexStats; loading: boolean }) {
  if (!stats) return <small>{loading ? "Loading index progress…" : "Index progress unavailable."}</small>;
  const [tone, label] = !stats.prepared ? (["neutral", "Not prepared"] as const) : stats.complete ? (["good", "Fully indexed"] as const) : stats.embedded_chunks > 0 ? (["warn", "Partly indexed"] as const) : (["neutral", "Prepared, not embedded"] as const);
  return <small><Badge tone={tone}>{label}</Badge> {stats.prepared ? `${number(stats.embedded_chunks)} of ${number(stats.total_chunks)} chunks embedded` : "No chunks yet"}</small>;
}


export function Books({ data }: { data: Snapshot }) {
  const params = useSearchParams();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const overview = useQuery({ queryKey: ["ingestion-overview"], queryFn: ({ signal }) => api<IngestionOverview>("ingestion/overview", { signal }) });
  const indexById = new Map((overview.data?.books ?? []).map((x) => [x.book_id, x]));
  const registered = useQuery({ queryKey: ["registered-books"], queryFn: ({ signal }) => api<RegisteredBook[]>("books", { signal }) });
  const detail = data.inventory.find((b) => b.file_hash === (selected || params.get("book")));
  const progress = data.books.find((b) => b.file_hash === (selected || params.get("book")));
  const filtered = { ...data, books: data.books.filter((b) => (b.title ?? b.filename).toLowerCase().includes(query.toLowerCase())) };
  return <><div className="page-heading"><div><span className="eyebrow">SOURCE LIBRARY</span><h1>PDF Books</h1><p>Review source files, extraction statistics and registered knowledge.</p></div><button className="button primary" onClick={() => setUploadOpen(!uploadOpen)} aria-expanded={uploadOpen}><FileUp size={17} /> Upload PDF</button></div>
    {uploadOpen && <UploadForm />}
    <Panel title="Ingestion library" description="Selected and frozen plans" action={<div className="search-field"><Search size={16} aria-hidden /><input aria-label="Search books" placeholder="Search books…" value={query} onChange={(e) => setQuery(e.target.value)} /></div>}><BookTable data={filtered} /></Panel>
    <Panel title="Local PDF inventory" description="Reported by the backend; the browser never reads local disk paths."><div className="table-scroll"><table><thead><tr><th>Source file</th><th>File size</th><th>Pages</th><th>Source tokens</th><th>Priority</th><th>Selection</th><th>Details</th></tr></thead><tbody>{data.inventory.map((b) => <tr key={b.file_hash}><td><strong>{b.filename}</strong></td><td>{bytes(b.pdf_bytes)}<small>{number(b.pdf_bytes)} bytes</small></td><td>{number(b.total_pages)}</td><td>{number(b.original_tokens)}</td><td>{b.priority ?? "—"}</td><td><Badge tone={b.selected ? "neutral" : "warn"}>{b.selected ? "Selected" : "Excluded"}</Badge></td><td><button className="text-link" onClick={() => setSelected(b.file_hash)}>View details <ArrowRight size={14} /></button></td></tr>)}</tbody></table></div></Panel>
    {detail && <Panel title={detail.title ?? detail.filename} description="Extraction details"><div className="detail-grid"><div><small>PDF bytes</small><strong>{number(detail.pdf_bytes)}</strong></div><div><small>Extracted UTF-8 bytes</small><strong>{number(detail.text_bytes)}</strong></div><div><small>Source pages</small><strong>{number(detail.total_pages)}</strong></div><div><small>Original source tokens</small><strong>{number(detail.original_tokens)}</strong></div><div><small>Detected category</small><strong>{categoryLabel[detail.category] ?? "Unknown"}</strong></div><div><small>Embedding API input tokens</small><strong>{number(progress?.provider_reported_embedding_tokens)}</strong></div></div></Panel>}
    <Panel title="Registered in Supabase" description="Live database API, separate from local inventory">{registered.isPending ? <p className="panel-padding">Loading registered books…</p> : registered.isError ? <Notice error>{registered.error.message}</Notice> : <div className="registered-list">{registered.data?.map((b) => <div key={b.id}><strong>{b.title}</strong><span>{categoryLabel[b.category]} · {number(b.chunk_count)} generated chunks<small>{number(b.metadata.total_pages)} pages · {bytes(b.metadata.pdf_bytes)} · {number(b.metadata.text_bytes)} extracted bytes</small><IndexProgress stats={indexById.get(b.id)} loading={overview.isPending} /></span></div>)}{!registered.data?.length && <Empty title="No registered books" />}</div>}</Panel>
    <p className="fine-print">Need processing details? <Link className="text-link" href={"/workspace/ingestion"}>Open Ingestion Jobs</Link></p>
  </>;
}
