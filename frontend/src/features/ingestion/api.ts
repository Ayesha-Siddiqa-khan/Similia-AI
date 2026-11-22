import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/backend";
import type { BookIngestionOut, ChunkPage, EmbeddedFilter, EventOut, JobOut, JobStatus, OverviewOut, PlanOut, StartRequest, TextPreview } from "./types";

export const POLL_MS = 3000;
export const CHUNKS_PER_PAGE = 20;
export const TEXT_PAGES_PER_VIEW = 5;

export const isLive = (status: JobStatus | undefined) => status === "pending" || status === "running";
const noRetryOnAuth = (n: number, error: Error) => n < 1 && (!(error instanceof ApiError) || ![401, 403, 404, 409, 429].includes(error.status));
const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, body === undefined ? { method: "POST" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** All books with real index counts. Refreshes every 3 s while any job is pending or running. */
export function useOverview() {
  return useQuery({
    queryKey: ["ingestion", "overview"],
    queryFn: ({ signal }) => api<OverviewOut>("ingestion/overview", { signal }),
    retry: noRetryOnAuth,
    refetchInterval: (q) => (q.state.data?.active_jobs.some((j) => isLive(j.status)) ? POLL_MS : false),
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
