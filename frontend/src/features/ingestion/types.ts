// Mirrors backend/app/schemas/ingestion.py. Every number shown on screen comes from these responses.
export type JobStatus = "pending" | "running" | "paused" | "completed" | "failed";
export type Level = "info" | "warning" | "error";

export interface IngestionLimits {
  provider: string;
  endpoint_host: string;
  model: string;
  dimension: number;
  per_job_token_limit: number;
  budget_token_limit: number;
  budget_tokens_used: number;
  budget_tokens_remaining: number;
  batch_tokens: number;
  requests_per_minute: number; // 0 = not paced
  provider_paused: boolean;
  provider_pause_reason: string | null;
}
export interface BookIndexStats {
  book_id: string;
  title: string;
  category: string;
  source_filename: string;
  total_pages: number | null;
  total_chunks: number;
  embedded_chunks: number;
  pending_chunks: number;
  embedded_tokens: number;
  pending_tokens: number;
  prepared: boolean;
  complete: boolean;
  frozen_plan: boolean;
}
export type BookState = "running" | "queued" | "stalled" | "paused" | "error" | "interrupted" | "complete" | "partial" | "ready" | "not_prepared";
export interface AutoResumeInfo { enabled: boolean; position: number | null; since: string | null; failures: number; note: string | null }
/** A book in the overview: index counts plus its live status and automatic-resume state. */
export interface BookOverviewItem extends BookIndexStats {
  state: BookState;
  detail: string | null;
  idle_seconds: number | null;
  latest_job: JobOut | null;
  auto_resume: AutoResumeInfo;
}
export interface AutoQueued { book_id: string; title: string; pending_chunks: number; pending_tokens: number }
export interface AutoSkipped { book_id: string; title?: string; reason: string }
export interface AutoRequest { book_ids: string[]; confirmed: boolean }
export interface AutoResult { queued: AutoQueued[]; skipped: AutoSkipped[]; total_pending_tokens: number }
export interface StopResult { stopped: string[] }
export interface JobOut {
  id: string;
  book_id: string;
  status: JobStatus;
  stage: string;
  total_chunks: number;
  processed_chunks: number;
  embedded_tokens: number;
  token_limit: number | null;
  estimated_tokens: number | null;
  pause_requested: boolean;
  error: string | null;
  stop_reason: string | null;
  resumed_from: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
}
export interface EventOut {
  id: number;
  job_id: string | null;
  book_id: string;
  level: Level;
  kind: string;
  message: string;
  details: Record<string, unknown>;
  created_at: string | null;
}
export interface PlanOut {
  stats: BookIndexStats;
  limits: IngestionLimits;
  effective_token_limit: number;
  can_start: boolean;
  blockers: string[];
  active_job: JobOut | null;
  latest_job: JobOut | null;
}
export interface StartRequest { confirmed: boolean; max_tokens?: number }
export interface BookIngestionOut { plan: PlanOut; jobs: JobOut[]; events: EventOut[] }
export interface OverviewOut { limits: IngestionLimits; books: BookOverviewItem[]; active_jobs: JobOut[] }
export interface ChunkOut {
  id: string;
  chunk_index: number;
  content: string;
  token_count: number | null;
  embedded: boolean;
  page_start: number | null;
  page_end: number | null;
  section_heading: string | null;
  section_path: string[];
}
export interface ChunkPage { total: number; offset: number; limit: number; items: ChunkOut[] }
export interface PageTextOut { page: number; chars: number; text: string; truncated: boolean }
export interface TextPreview { total_pages: number; offset: number; limit: number; pages: PageTextOut[] }
export type EmbeddedFilter = "" | "true" | "false";
