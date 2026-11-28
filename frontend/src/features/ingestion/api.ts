import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/backend";
import type { AutoRequest, AutoResult, BookIngestionOut, StopResult, ChunkPage, EmbeddedFilter, EventOut, JobOut, JobStatus, OverviewOut, PlanOut, StartRequest, TextPreview } from "./types";

export const POLL_MS = 3000;
export const CHUNKS_PER_PAGE = 20;
export const TEXT_PAGES_PER_VIEW = 5;

export const isLive = (status: JobStatus | undefined) => status === "pending" || status === "running";
const noRetryOnAuth = (n: number, error: Error) => n < 1 && (!(error instanceof ApiError) || ![401, 403, 404, 409, 429].includes(error.status));
const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, body === undefined ? { method: "POST" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const OVERVIEW_FAST_MS = 5000;
export const OVERVIEW_SLOW_MS = 30_000;
/** 5 s while any book is running or stalled or an automatic queue exists, otherwise 30 s. */
export function overviewInterval(data: OverviewOut | undefined): number {
  const busy = data?.books.some((b) => b.state === "running" || b.state === "stalled" || b.auto_resume.enabled) || data?.active_jobs.some((j) => isLive(j.status));
  return busy ? OVERVIEW_FAST_MS : OVERVIEW_SLOW_MS;
}
/** All books with real index counts and live status. Not refreshed while the tab is hidden. */
export function useOverview() {
  return useQuery({
    queryKey: ["ingestion", "overview"],
    queryFn: ({ signal }) => api<OverviewOut>("ingestion/overview", { signal }),
    retry: noRetryOnAuth,
    refetchInterval: (q) => overviewInterval(q.state.data),
    refetchIntervalInBackground: false,
  });
}
/** Plan, recent jobs and events of one book. Refreshes every 3 s while its job is pending or running. */
export function useBookIngestion(bookId: string | null) {
  return useQuery({
    queryKey: ["ingestion", "book", bookId],
    queryFn: ({ signal }) => api<BookIngestionOut>(`books/${bookId}/ingestion`, { signal }),
    enabled: bookId !== null,
    retry: noRetryOnAuth,
    refetchInterval: (q) => (isLive(q.state.data?.plan.active_job?.status) ? POLL_MS : false),
  });
}
export function useJobEvents(jobId: string | null) {
  return useQuery({
    queryKey: ["ingestion", "events", jobId],
    queryFn: ({ signal }) => api<EventOut[]>(`ingestion-jobs/${jobId}/events?limit=50`, { signal }),
    enabled: jobId !== null,
    retry: noRetryOnAuth,
    refetchInterval: POLL_MS,
  });
}
export function useChunks(bookId: string, offset: number, q: string, embedded: EmbeddedFilter) {
  const params = new URLSearchParams({ offset: String(offset), limit: String(CHUNKS_PER_PAGE) });
  if (q) params.set("q", q);
  if (embedded) params.set("embedded", embedded);
  return useQuery({
    queryKey: ["ingestion", "chunks", bookId, offset, q, embedded],
    queryFn: ({ signal }) => api<ChunkPage>(`books/${bookId}/chunks?${params}`, { signal }),
    retry: noRetryOnAuth,
  });
}
export function useText(bookId: string, offset: number) {
  return useQuery({
    queryKey: ["ingestion", "text", bookId, offset],
    queryFn: ({ signal }) => api<TextPreview>(`books/${bookId}/text?offset=${offset}&limit=${TEXT_PAGES_PER_VIEW}`, { signal }),
    retry: noRetryOnAuth,
  });
}

function useIngestionMutation<V, T>(fn: (v: V) => Promise<T>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => client.invalidateQueries({ queryKey: ["ingestion"] }) });
}
export const usePrepare = (bookId: string) => useIngestionMutation<void, PlanOut>(() => post<PlanOut>(`books/${bookId}/prepare`));
/** Spends paid tokens: callers must only pass confirmed: true from the confirmation dialog. */
export const useStart = (bookId: string) => useIngestionMutation<StartRequest, JobOut>((body) => post<JobOut>(`books/${bookId}/ingest`, body));
export const usePause = () => useIngestionMutation<string, JobOut>((jobId) => post<JobOut>(`ingestion-jobs/${jobId}/pause`));
/** Spends paid tokens: only the automatic-resume confirmation dialog may call this, always with confirmed: true. */
export const useStartAuto = () => useIngestionMutation<AutoRequest, AutoResult>((body) => post<AutoResult>("ingestion/auto", body));
/** Omit book_ids to stop every automatic resume. A running job finishes its current batch first. */
export const useStopAuto = () => useIngestionMutation<string[] | undefined, StopResult>((ids) => post<StopResult>("ingestion/auto/stop", { book_ids: ids }));
