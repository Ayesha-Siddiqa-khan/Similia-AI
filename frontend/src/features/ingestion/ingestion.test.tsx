import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { IngestionJobs } from "./index";
import type { BookIndexStats, BookIngestionOut, ChunkPage, EventOut, IngestionLimits, JobOut, OverviewOut, PlanOut, TextPreview } from "./types";

const limits: IngestionLimits = {
  provider: "Voyage AI embeddings", endpoint_host: "api.example-provider.test", model: "test-embed-1", dimension: 1024,
  per_job_token_limit: 250_000, budget_token_limit: 1_000_000, budget_tokens_used: 123_456, budget_tokens_remaining: 876_544,
  batch_tokens: 8_000, requests_per_minute: 7, provider_paused: false, provider_pause_reason: null,
};
const book = (over: Partial<BookIndexStats> = {}): BookIndexStats => ({
  book_id: "b1", title: "Test Materia Medica", category: "materia_medica", source_filename: "mm.pdf", total_pages: 321,
  total_chunks: 400, embedded_chunks: 150, pending_chunks: 250, embedded_tokens: 61_000, pending_tokens: 98_765,
  prepared: true, complete: false, frozen_plan: false, ...over,
});
const job = (over: Partial<JobOut> = {}): JobOut => ({
  id: "j1", book_id: "b1", status: "running", stage: "embedding", total_chunks: 250, processed_chunks: 40, embedded_tokens: 15_000,
  token_limit: 98_765, estimated_tokens: 98_765, pause_requested: false, error: null, stop_reason: null, resumed_from: null,
  created_at: "2026-01-01T10:00:00Z", started_at: "2026-01-01T10:00:01Z", finished_at: null, heartbeat_at: null, ...over,
});
const plan = (over: Partial<PlanOut> = {}): PlanOut => ({
  stats: book(), limits, effective_token_limit: 90_000, can_start: true, blockers: [], active_job: null, latest_job: null, ...over,
});
const event = (over: Partial<EventOut> = {}): EventOut => ({
  id: 1, job_id: "j1", book_id: "b1", level: "info", kind: "batch_done", message: "Batch stored", details: {}, created_at: "2026-01-01T10:05:00Z", ...over,
});
const chunkPage: ChunkPage = { total: 1, offset: 0, limit: 20, items: [{ id: "c1", chunk_index: 3, content: "Aconite is used in sudden fear.", token_count: 77, embedded: true, page_start: 12, page_end: 13, section_heading: "Aconite", section_path: ["Remedies", "Aconite"] }] };
const textPreview: TextPreview = { total_pages: 321, offset: 0, limit: 5, pages: [{ page: 1, chars: 4321, text: "First page text", truncated: true }] };

interface World { overview: OverviewOut; detail: BookIngestionOut; failures: Record<string, { status: number; detail: string }> }
let world: World;
let calls: { path: string; method: string; body: unknown }[];
const respond = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

function freshWorld(over: Partial<BookIngestionOut> = {}, books: BookIndexStats[] = [book(), book({ book_id: "b2", title: "Second Book", total_chunks: 0, embedded_chunks: 0, pending_chunks: 0, pending_tokens: 0, prepared: false })]): World {
  return { overview: { limits, books, active_jobs: [] }, detail: { plan: plan(), jobs: [], events: [], ...over }, failures: {} };
}
beforeEach(() => {
  world = freshWorld();
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace("/api/backend/", "");
    const method = init?.method ?? "GET";
    calls.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const failure = world.failures[`${method} ${path.split("?")[0]}`];
    if (failure) return respond(failure.status, { detail: failure.detail });
    if (path === "ingestion/overview") return respond(200, world.overview);
    if (path.endsWith("/ingestion")) return respond(200, world.detail);
    if (path.includes("/chunks")) return respond(200, chunkPage);
    if (path.includes("/text")) return respond(200, textPreview);
    if (path.includes("/events")) return respond(200, [event({ id: 9, message: "Job-only event" })]);
    if (path.endsWith("/prepare")) return respond(200, world.detail.plan);
    if (path.endsWith("/ingest")) return respond(202, job());
    if (path.endsWith("/pause")) return respond(200, job({ pause_requested: true }));
    return respond(404, { detail: "unexpected" });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><IngestionJobs /></QueryClientProvider>);
}
async function openBook(title = "Test Materia Medica") {
  mount();
  await screen.findByText(title);
  fireEvent.click(screen.getAllByRole("button", { name: "Select" })[title === "Test Materia Medica" ? 0 : 1]);
  await screen.findByText("Limits");
}
const posts = () => calls.filter((c) => c.method === "POST");

describe("book list", () => {
  it("shows index progress and badges from the API only", async () => {
    mount();
    await screen.findByText("Test Materia Medica");
    expect(screen.getByText("150 of 400 chunks")).toBeInTheDocument();
    expect(screen.getByText("98,765")).toBeInTheDocument();
    expect(screen.getByText("Partial")).toBeInTheDocument();
    expect(screen.getByText("Not prepared")).toBeInTheDocument();
    expect(screen.getByText("No chunks yet")).toBeInTheDocument();
  });
  it("shows a complete badge and an error with retry when the overview fails", async () => {
    world.overview.books = [book({ complete: true, embedded_chunks: 400, pending_chunks: 0, pending_tokens: 0 })];
    mount();
    expect(await screen.findByText("Complete")).toBeInTheDocument();
    cleanup();
    world.failures["GET ingestion/overview"] = { status: 503, detail: "A required service is not configured or unavailable." };
    mount();
    expect(await screen.findByText(/not configured or unavailable/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
  it("says so when no book is registered", async () => {
    world.overview.books = [];
    mount();
    expect(await screen.findByText("No books registered")).toBeInTheDocument();
  });
});

describe("plan, limits and confirmation", () => {
  it("shows the limits and labels the start button from the book's state", async () => {
    await openBook();
    expect(screen.getByText("api.example-provider.test")).toBeInTheDocument();
    expect(screen.getByText("test-embed-1 (1,024 dimensions)")).toBeInTheDocument();
    expect(screen.getByText("876,544 tokens")).toBeInTheDocument();
    expect(screen.getByText("7 requests per minute")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume embedding" })).toBeEnabled();
  });
  it("opens a dialog with the spending facts and sends nothing until confirmed", async () => {
    await openBook();
    fireEvent.click(screen.getByRole("button", { name: "Resume embedding" }));
    const dialog = await screen.findByRole("dialog");
    for (const text of ["api.example-provider.test", "test-embed-1", "98,765", "90,000", "876,544", "123,456", "8,000", "7 requests per minute"]) {
      expect(within(dialog).getByText(text)).toBeInTheDocument();
    }
    expect(posts()).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts()).toHaveLength(0);
  });
  it("sends confirmed: true only from the confirm button", async () => {
    await openBook();
    fireEvent.click(screen.getByRole("button", { name: "Resume embedding" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /^Confirm/ }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]).toMatchObject({ path: "books/b1/ingest", body: { confirmed: true } });
  });
  it("labels Start, Retry and the finished state correctly", async () => {
    world.detail.plan = plan({ stats: book({ embedded_chunks: 0, pending_chunks: 400 }) });
    await openBook();
    expect(screen.getByRole("button", { name: "Start embedding" })).toBeInTheDocument();
    cleanup();
    world.detail.plan = plan({ latest_job: job({ status: "failed" }) });
    await openBook();
    expect(await screen.findByRole("button", { name: "Retry failed batches" })).toBeInTheDocument();
    cleanup();
    world.detail.plan = plan({ stats: book({ embedded_chunks: 400, pending_chunks: 0, complete: true }) });
    await openBook();
    expect(await screen.findByRole("button", { name: "All chunks embedded" })).toBeDisabled();
  });
  it("lists blockers and disables Start when the plan cannot start", async () => {
    world.detail.plan = plan({ can_start: false, blockers: ["Token budget is used up."] });
    await openBook();
    expect(await screen.findByText("Token budget is used up.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume embedding" })).toBeDisabled();
  });
  it("shows the frozen plan notice and offers no Start", async () => {
    world.detail.plan = plan({ stats: book({ frozen_plan: true }), can_start: false });
    await openBook();
    expect(await screen.findByText(/command-line pipeline/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /embedding|Retry/ })).toBeNull();
  });
  it("shows the provider stop banner with its reason", async () => {
    world.detail.plan = plan({ limits: { ...limits, provider_paused: true, provider_pause_reason: "Quota check pending" }, can_start: false, blockers: ["Provider stop is set."] });
    await openBook();
    expect((await screen.findAllByText(/Quota check pending/)).length).toBeGreaterThan(0);
  });
  it("prepares through its own endpoint without a confirmation", async () => {
    await openBook();
    fireEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0].path).toBe("books/b1/prepare");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("a running job", () => {
  it("shows progress and Pause calls the pause endpoint", async () => {
    world.detail.plan = plan({ active_job: job() });
    await openBook();
    expect(await screen.findByText(/40 of 250 chunks processed/)).toBeInTheDocument();
    expect(screen.getByText(/Tokens used: 15,000 of 98,765/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume embedding" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0].path).toBe("ingestion-jobs/j1/pause");
  });
  it("tells the operator the current batch is finishing after a pause request", async () => {
    world.detail.plan = plan({ active_job: job({ pause_requested: true }) });
    await openBook();
    expect(await screen.findByText("Pause requested, finishing the current batch.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause" })).toBeDisabled();
  });
  it("refreshes every 3 seconds while the job runs", async () => {
    world.detail.plan = plan({ active_job: job() });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await openBook();
    const count = () => calls.filter((c) => c.path === "books/b1/ingestion").length;
    const before = count();
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(count()).toBeGreaterThan(before);
  });
});

describe("history and inspectors", () => {
  it("shows error events clearly with their details", async () => {
    world.detail.events = [event({ id: 5, level: "error", kind: "provider_error", message: "Provider answered 429", details: { status: 429 } }), event({ id: 4 })];
    await openBook();
    expect(await screen.findByText("Provider answered 429")).toBeInTheDocument();
    expect(screen.getByText("error")).toBeInTheDocument();
    expect(screen.getByText("provider_error")).toBeInTheDocument();
    expect(screen.getByText("status: 429")).toBeInTheDocument();
  });
  it("says so when there are no events and loads one job's events on request", async () => {
    await openBook();
    expect(await screen.findByText("No events yet")).toBeInTheDocument();
    cleanup();
    world.detail.jobs = [job({ status: "failed", error: "Provider answered 429" })];
    await openBook();
    fireEvent.click(await screen.findByRole("button", { name: "Show job events" }));
    expect(await screen.findByText("Job-only event")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "ingestion-jobs/j1/events?limit=50")).toBe(true);
  });
  it("shows chunk page ranges and sends the filter in the query string", async () => {
    await openBook();
    expect(await screen.findByText("PDF pages 12-13")).toBeInTheDocument();
    expect(screen.getByText("Remedies > Aconite")).toBeInTheDocument();
    expect(screen.getByText("77 tokens")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search chunk text"), { target: { value: "fear" } });
    fireEvent.change(screen.getByLabelText("Vector status"), { target: { value: "true" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply search" }));
    await waitFor(() => expect(calls.some((c) => c.path === "books/b1/chunks?offset=0&limit=20&q=fear&embedded=true")).toBe(true));
  });
  it("shows extracted text by PDF page with the truncated flag", async () => {
    await openBook();
    expect(await screen.findByText("PDF page 1")).toBeInTheDocument();
    expect(screen.getByText("First page text")).toBeInTheDocument();
    expect(screen.getByText("Truncated for display")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "books/b1/text?offset=0&limit=5")).toBe(true);
  });
  it("explains that an unprepared book has no chunks to inspect", async () => {
    world.detail.plan = plan({ stats: book({ book_id: "b2", total_chunks: 0, prepared: false, embedded_chunks: 0, pending_chunks: 0 }) });
    await openBook("Second Book");
    expect(await screen.findByText("No chunks to inspect")).toBeInTheDocument();
  });
});

describe("refusals from the backend", () => {
  it("shows the 409 message when the book already has an active job", async () => {
    world.failures["POST books/b1/ingest"] = { status: 409, detail: "This book already has an active embedding job." };
    await openBook();
    fireEvent.click(screen.getByRole("button", { name: "Resume embedding" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /^Confirm/ }));
    expect(await screen.findByText("This book already has an active embedding job.")).toBeInTheDocument();
  });
  it("shows the 429 message when the provider stop is set", async () => {
    world.failures["POST books/b1/ingest"] = { status: 429, detail: "Embedding is stopped: the provider stop is set." };
    await openBook();
    fireEvent.click(screen.getByRole("button", { name: "Resume embedding" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /^Confirm/ }));
    expect(await screen.findByText("Embedding is stopped: the provider stop is set.")).toBeInTheDocument();
  });
});
