"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { Badge, Loading, Notice, number, Panel } from "@/components/ui";
import { AiSettingsPage, CasePage, CasesPage, PatientDetail, PatientsPage } from "@/features/cases";
import { IngestionJobs } from "@/features/ingestion";
import { api, useSnapshot } from "./api";
import { Dashboard } from "./dashboard";
import { Books } from "./books";
import { Chunks } from "./chunks";
import { Search } from "./search";
import type { Snapshot } from "./types";

function Settings({ data }: { data?: Snapshot }) {
  const graph = useQuery({ queryKey: ["graphql-health"], queryFn: ({ signal }) => api<{ health: string }>("graphql", { signal }), retry: 1 });
  return <><div className="page-heading"><div><span className="eyebrow">WORKSPACE CONFIGURATION</span><h1>Settings</h1><p>Connection details and the boundaries of this development phase.</p></div></div><Panel title="Service connections" description="Configuration is managed on the server."><dl className="measurements"><div><dt>Authentication</dt><dd>Verified Supabase operator session</dd></div><div><dt>GraphQL health</dt><dd>{graph.isPending ? "Checking…" : graph.isError ? "Unavailable" : graph.data.health}</dd></div><div><dt>Embedding model</dt><dd>{data?.usage.embedding_model ?? "Unavailable"}</dd></div><div><dt>Vector dimensions</dt><dd>{number(data?.usage.embedding_dimensions)}</dd></div><div><dt>Provider free balance</dt><dd>Unknown</dd></div></dl></Panel><Notice>Database schema, RLS, API keys and chunking rules cannot be changed from this interface. Coding-agent context and token usage are unavailable.</Notice><Panel title="Feature readiness"><div className="registered-list"><div><strong>Knowledge inspection</strong><Badge tone="good">Read-only APIs</Badge></div><div><strong>Browser uploads</strong><span>Supported for PDF registration; no automatic embeddings</span></div><div><strong>Phase 2B ingestion controls</strong><span>Awaiting budget-safe HTTP controls</span></div><div><strong>Patient records and case analysis</strong><Badge tone="good">Practitioner workspace</Badge></div></div></Panel></>;
}

export function WorkspacePage({ section, id }: { section: string; id?: string }) {
  const query = useSnapshot();
  if (section === "case") return id ? <CasePage id={id} /> : <CasesPage />;
  if (section === "patients") return id ? <PatientDetail id={id} /> : <PatientsPage />;
  if (section === "ai") return <AiSettingsPage />;
  if (section === "ingestion") return <IngestionJobs />;
  if (section === "settings") return <Settings data={query.data} />;
  if (query.isPending) return <Loading />;
  if (query.isError && !query.data) return <><div className="page-heading"><h1>Workspace data unavailable</h1></div><Notice error>{query.error.message}</Notice><div className="button-row"><button className="button secondary" onClick={() => void query.refetch()}>Try again</button><Link className="button secondary" href="/login">Sign in</Link></div></>;
  const data = query.data!;
  return <>{query.isError && <Notice error>Refresh failed. Showing the last saved response; data may be stale. {query.error.message}</Notice>}{section === "dashboard" || section === "knowledge" ? <Dashboard data={data} knowledge={section === "knowledge"} /> : section === "books" ? <Books data={data} /> : section === "chunks" ? <Chunks data={data} /> : <Search data={data} />}<div className="data-freshness"><span><span className="dot" /> Backend report timestamp: {data.timestamp}</span><button className="text-link" disabled={query.isFetching} onClick={() => void query.refetch()}><RefreshCw size={13} className={query.isFetching ? "spin" : ""} /> Refresh</button></div></>;
}
