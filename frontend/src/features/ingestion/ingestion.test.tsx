import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { IngestionJobs } from "./index";
import { overviewInterval } from "./api";
import type { AutoResult, BookOverviewItem, BookIngestionOut, ChunkPage, EventOut, IngestionLimits, JobOut, OverviewOut, PlanOut, TextPreview } from "./types";

const limits: IngestionLimits = {
  provider: "Voyage AI embeddings", endpoint_host: "api.example-provider.test", model: "test-embed-1", dimension: 1024,
  per_job_token_limit: 250_000, budget_token_limit: 1_000_000, budget_tokens_used: 123_456, budget_tokens_remaining: 876_544,
  batch_tokens: 8_000, requests_per_minute: 7, provider_paused: false, provider_pause_reason: null,
};
const book = (over: Partial<BookOverviewItem> = {}): BookOverviewItem => ({
  book_id: "b1", title: "Test Materia Medica", category: "materia_medica", source_filename: "mm.pdf", total_pages: 321,
  total_chunks: 400, embedded_chunks: 150, pending_chunks: 250, embedded_tokens: 61_000, pending_tokens: 98_765,
  prepared: true, complete: false, frozen_plan: false,
  state: "partial", detail: null, idle_seconds: null, latest_job: null, auto_resume: { enabled: false, position: null, since: null, failures: 0, note: null }, ...over,
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

interface World { autoResult: AutoResult; overview: OverviewOut; detail: BookIngestionOut; failures: Record<string, { status: number; detail: string }> }
let world: World;
let calls: { path: string; method: string; body: unknown }[];
const respond = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

function freshWorld(over: Partial<BookIngestionOut> = {}, books: BookOverviewItem[] = [book(), book({ book_id: "b2", title: "Second Book", total_chunks: 0, embedded_chunks: 0, pending_chunks: 0, pending_tokens: 0, prepared: false, state: "not_prepared" })]): World {
  return { autoResult: { queued: [], skipped: [], total_pending_tokens: 0 }, overview: { limits, books, active_jobs: [] }, detail: { plan: plan(), jobs: [], events: [], ...over }, failures: {} };
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
    if (path === "ingestion/books/list.pdf") return new Response(new Blob(["%PDF-1.7"]), { status: 200, headers: { "content-type": "application/pdf" } });
    if (path.endsWith("/ingestion")) return respond(200, world.detail);
    if (path.includes("/chunks")) return respond(200, chunkPage);
    if (path.includes("/text")) return respond(200, textPreview);
    if (path.includes("/events")) return respond(200, [event({ id: 9, message: "Job-only event" })]);
    if (path.endsWith("/prepare")) return respond(200, world.detail.plan);
    if (path.endsWith("/ingest")) return respond(202, job());
    if (path.endsWith("/pause")) return respond(200, job({ pause_requested: true }));
    if (path === "ingestion/auto") return respond(200, world.autoResult);
    if (path === "ingestion/auto/stop") return respond(200, { stopped: [] });
    return respond(404, { detail: "unexpected" });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

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
    world.overview.books = [book({ complete: true, state: "complete", embedded_chunks: 400, pending_chunks: 0, pending_tokens: 0 })];
    mount();
    const finished = (await screen.findByRole("heading", { name: /Completed \(1\)/ })).closest("section")!;
    fireEvent.click(within(finished).getByRole("button", { name: "Show completed" }));
    expect(await screen.findByText("Complete")).toBeInTheDocument();
    cleanup();
    world.failures["GET ingestion/overview"] = { status: 503, detail: "A required service is not configured or unavailable." };
    mount();
    expect(await screen.findByText(/not configured or unavailable/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
  it("downloads a PDF list of the PDF document names", async () => {
    mount();
    await screen.findByText("Test Materia Medica");
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    fireEvent.click(screen.getByRole("button", { name: "Download book list (PDF)" }));
    await waitFor(() => expect(names).toEqual(["ingestion-book-list.pdf"]));
    expect(calls.filter((c) => c.path === "ingestion/books/list.pdf" && c.method === "GET")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Download book list (PDF)" })).toBeEnabled();
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

const AUTO_OFF = { enabled: false, position: null, since: null, failures: 0, note: null };
const mk = (id: string, over: Partial<BookOverviewItem> = {}) => book({ book_id: id, title: `Book ${id}`, source_filename: `${id}.pdf`, ...over });
async function mountList(books: BookOverviewItem[], over: Partial<IngestionLimits> = {}) {
  world.overview.books = books;
  world.overview.limits = { ...limits, ...over };
  mount();
  await screen.findByRole("heading", { name: /In progress and waiting/ });
}
const showCompleted = async () => {
  const section = (await screen.findByRole("heading", { name: /^Completed \(\d+\)/ })).closest("section")!;
  fireEvent.click(within(section).getByRole("button", { name: "Show completed" }));
  return section;
};
const checkbox = (name: string | RegExp) => screen.getByRole("checkbox", { name });

describe("status chips", () => {
  it("shows an icon-and-text chip for every state", async () => {
    await mountList([
      mk("r", { state: "running", idle_seconds: 12, detail: "Command-line run", latest_job: job({ processed_chunks: 50, total_chunks: 200 }) }),
      mk("s", { state: "stalled", detail: "No progress reported for 3 min 5 s" }),
      mk("p", { state: "paused", detail: "Token limit reached" }),
      mk("e", { state: "error", detail: "Provider answered 500: upstream failed" }),
      mk("i", { state: "interrupted", detail: "Server restarted" }),
      mk("c", { state: "complete", complete: true, pending_chunks: 0, embedded_chunks: 400 }),
      mk("pa", { state: "partial" }),
      mk("rd", { state: "ready", embedded_chunks: 0 }),
      mk("n", { state: "not_prepared", prepared: false, pending_chunks: 0 }),
    ]);
    await showCompleted();
    for (const text of ["Running", "Stalled?", "Paused", "Error", "Interrupted", "Complete", "Partial", "Ready (prepared)", "Not prepared"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText(/updated 12s ago/)).toBeInTheDocument();
    expect(screen.getByText(/Command-line run/)).toBeInTheDocument();
    expect(screen.getByText("No progress reported for 3 min 5 s")).toBeInTheDocument();
    expect(screen.getByText("Token limit reached")).toBeInTheDocument();
    expect(screen.getByText("Provider answered 500: upstream failed")).toBeInTheDocument();
    expect(screen.getByText(/Server restarted · resume to continue/)).toBeInTheDocument();
  });
  it("shows the Auto badge with its queue position and the note when auto is off", async () => {
    await mountList([
      mk("a", { state: "running", auto_resume: { ...AUTO_OFF, enabled: true, position: 1 } }),
      mk("b", { auto_resume: { ...AUTO_OFF, enabled: true, position: 2 } }),
      mk("c", { state: "error", detail: "Embedding failed", auto_resume: { ...AUTO_OFF, note: "Stopped after 3 failed attempts. Last error: Embedding failed" } }),
    ]);
    expect(screen.getByText("Auto · running")).toBeInTheDocument();
    expect(screen.getByText("Auto · 2nd in queue")).toBeInTheDocument();
    expect(screen.getByText(/Stopped after 3 failed attempts/)).toBeInTheDocument();
  });
  it("summarises running, waiting and attention counts with the running book", async () => {
    await mountList([
      mk("a", { state: "running", title: "Alpha", latest_job: job({ processed_chunks: 10, total_chunks: 40 }), auto_resume: { ...AUTO_OFF, enabled: true, position: 1 } }),
      mk("b", { auto_resume: { ...AUTO_OFF, enabled: true, position: 2 } }),
      mk("c", { state: "error", detail: "x" }), mk("d", { state: "stalled" }), mk("e", { state: "paused" }),
    ]);
    expect(screen.getByText("1 running · 1 waiting in auto queue · 3 need attention")).toBeInTheDocument();
    expect(screen.getByText("Running now: Alpha — 25%")).toBeInTheDocument();
  });
});

describe("polling", () => {
  const data = (books: BookOverviewItem[]): OverviewOut => ({ limits, books, active_jobs: [] });
  it("refreshes every 5 s when a book runs, stalls or is queued, otherwise every 30 s", () => {
    expect(overviewInterval(data([mk("a", { state: "running" })]))).toBe(5000);
    expect(overviewInterval(data([mk("a", { state: "stalled" })]))).toBe(5000);
    expect(overviewInterval(data([mk("a", { auto_resume: { ...AUTO_OFF, enabled: true, position: 1 } })]))).toBe(5000);
    expect(overviewInterval(data([mk("a")]))).toBe(30_000);
    expect(overviewInterval(undefined)).toBe(30_000);
  });
});

describe("automatic resume", () => {
  const books = () => [
    mk("a"), mk("b", { pending_tokens: 1_000 }), mk("f", { frozen_plan: true }),
    mk("u", { prepared: false, state: "not_prepared", pending_chunks: 0 }),
    mk("c", { complete: true, state: "complete", pending_chunks: 0 }),
    mk("x", { auto_resume: { ...AUTO_OFF, enabled: true, position: 1 }, state: "running" }),
  ];
  it("disables frozen, unprepared, complete and already-automatic rows and explains why", async () => {
    await mountList(books());
    await showCompleted();
    expect(checkbox(/Select Book f \(Command-line pipeline: continue it with the command line\)/)).toBeDisabled();
    expect(checkbox(/Select Book u \(Not prepared yet\)/)).toBeDisabled();
    expect(checkbox(/Select Book c \(Already complete\)/)).toBeDisabled();
    expect(checkbox(/Select Book x \(Automatic resume is already on\)/)).toBeDisabled();
    expect(checkbox("Select Book a for automatic resume")).toBeEnabled();
  });
  it("the header checkbox selects only eligible books and the toolbar shows count and tokens", async () => {
    await mountList(books());
    expect(screen.queryByRole("button", { name: /Resume selected automatically/ })).toBeNull();
    fireEvent.click(checkbox("Select all resumable"));
    expect(checkbox("Select Book a for automatic resume")).toBeChecked();
    expect(checkbox("Select Book b for automatic resume")).toBeChecked();
    expect(checkbox(/Select Book f/)).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Resume selected automatically (2 books, ~99,765 tokens)" })).toBeInTheDocument();
  });
  it("shows the spending facts, sends nothing on Cancel, and posts once on confirm", async () => {
    await mountList(books());
    fireEvent.click(checkbox("Select Book a for automatic resume"));
    fireEvent.click(screen.getByRole("button", { name: /^Resume selected automatically/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Resume these books automatically?")).toBeInTheDocument();
    for (const text of ["api.example-provider.test", "test-embed-1", "98,765", "250,000 tokens", "876,544 tokens", "8,000", "7 requests per minute", "Voyage AI embeddings"]) {
      expect(within(dialog).getAllByText(text).length).toBeGreaterThan(0);
    }
    expect(within(dialog).getByText(/one at a time until they are complete, you stop it, the budget or a limit is reached, or the provider refuses/)).toBeInTheDocument();
    expect(within(dialog).getByText("Any provider stop pauses it.")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts()).toHaveLength(0);
    world.autoResult = { queued: [{ book_id: "a", title: "Book a", pending_chunks: 250, pending_tokens: 98_765 }], skipped: [{ book_id: "z", title: "Book z", reason: "Already queued" }], total_pending_tokens: 98_765 };
    fireEvent.click(screen.getByRole("button", { name: /^Resume selected automatically/ }));
    const confirm = within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm and resume automatically" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]).toMatchObject({ path: "ingestion/auto", body: { book_ids: ["a"], confirmed: true } });
    expect(await screen.findByText("1 book queued for automatic resume.")).toBeInTheDocument();
    expect(screen.getByText("Book z was skipped: Already queued")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(posts()).toHaveLength(1);
  });
  it("Resume all queues every eligible book through the same dialog", async () => {
    await mountList(books());
    fireEvent.click(screen.getByRole("button", { name: "Resume all" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm and resume automatically" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0].body).toEqual({ book_ids: ["a", "b"], confirmed: true });
  });
  it("shows the safe message when the backend refuses", async () => {
    world.failures["POST ingestion/auto"] = { status: 429, detail: "Embedding is stopped: the provider stop is set." };
    await mountList(books());
    fireEvent.click(screen.getByRole("button", { name: "Resume all" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirm and resume automatically" }));
    expect(await screen.findByText("Embedding is stopped: the provider stop is set.")).toBeInTheDocument();
  });
  it("stops one book or everything without a confirmation dialog", async () => {
    await mountList(books());
    expect(screen.getByText("Auto · running")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop auto for Book x" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]).toMatchObject({ path: "ingestion/auto/stop", body: { book_ids: ["x"] } });
    expect(await screen.findByText("Stopping: the running job will finish its current batch.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop automatic resume" }));
    await waitFor(() => expect(posts()).toHaveLength(2));
    expect(posts()[1].path).toBe("ingestion/auto/stop");
    expect((posts()[1].body as { book_ids?: string[] }).book_ids).toBeUndefined();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("disables the auto buttons with the reason while the provider stop is set", async () => {
    await mountList(books(), { provider_paused: true, provider_pause_reason: "Quota check pending" });
    fireEvent.click(checkbox("Select Book a for automatic resume"));
    expect(screen.getByRole("button", { name: "Resume all" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Resume selected automatically/ })).toBeDisabled();
    expect(screen.getByText(/The embedding provider stop is set/)).toBeInTheDocument();
  });
});

describe("two sections", () => {
  it("lists finished books separately from the running and waiting ones, in queue order", async () => {
    const waiting = (id: string, title: string, position: number) => book({ book_id: id, title, state: "queued", auto_resume: { enabled: true, position, since: "2026-01-01", failures: 0, note: null } });
    await mountList([
      book({ book_id: "done1", title: "Finished One", state: "complete", complete: true, embedded_chunks: 400, pending_chunks: 0, pending_tokens: 0 }),
      waiting("q3", "Third in line", 3),
      book({ book_id: "idle", title: "Not prepared yet", state: "not_prepared", prepared: false, total_chunks: 0, embedded_chunks: 0, pending_chunks: 0, pending_tokens: 0 }),
      waiting("q2", "Second in line", 2),
      book({ book_id: "run", title: "Running Now", state: "running", auto_resume: { enabled: true, position: 1, since: "2026-01-01", failures: 0, note: null } }),
      book({ book_id: "done2", title: "Finished Two", state: "complete", complete: true, embedded_chunks: 400, pending_chunks: 0, pending_tokens: 0 }),
    ]);
    const remaining = screen.getByRole("heading", { name: /In progress and waiting \(4\)/ }).closest("section")!;
    const finished = screen.getByRole("heading", { name: /Completed \(2\)/ }).closest("section")!;
    const order = within(remaining).getAllByRole("row").slice(1).map((r) => r.querySelector("td:nth-child(2) strong")?.textContent);
    expect(order).toEqual(["Running Now", "Second in line", "Third in line", "Not prepared yet"]);
    expect(within(finished).queryByText("Finished One")).not.toBeInTheDocument();
    fireEvent.click(within(finished).getByRole("button", { name: "Show completed" }));
    expect(within(finished).getByText("Finished One")).toBeInTheDocument();
    expect(within(finished).getByText("Finished Two")).toBeInTheDocument();
    expect(within(remaining).queryByText("Finished One")).not.toBeInTheDocument();
    expect(within(finished).queryByText("Running Now")).not.toBeInTheDocument();
    fireEvent.click(within(finished).getByRole("button", { name: "Hide completed" }));
    expect(within(finished).queryByText("Finished One")).not.toBeInTheDocument();
  });
  it("says so when nothing is waiting", async () => {
    await mountList([book({ state: "complete", complete: true, embedded_chunks: 400, pending_chunks: 0, pending_tokens: 0 })]);
    expect(screen.getByText(/Nothing is waiting: every book is fully embedded/)).toBeInTheDocument();
  });
});
