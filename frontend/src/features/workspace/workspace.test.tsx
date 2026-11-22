import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { api, validatePdf } from "./api";
import { Dashboard } from "./dashboard";
import { Chunks } from "./chunks";
import { Search } from "./search";
import { fixtureChunks, fixtureSnapshot } from "@/test/fixtures/workspace-fixtures";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}
describe("PDF validation", () => {
  it("rejects missing, empty, oversized and non-PDF files", () => {
    expect(validatePdf(undefined)).toMatch(/Choose/);
    expect(validatePdf(new File([], "empty.pdf"))).toMatch(/empty/);
    expect(validatePdf(new File(["text"], "notes.txt"))).toMatch(/Only PDF/);
    const file = new File(["pdf"], "book.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: 50 * 1024 * 1024 + 1 });
    expect(validatePdf(file)).toMatch(/50 MB/);
    expect(validatePdf(new File(["%PDF-"], "book.PDF", { type: "application/pdf" }))).toBeNull();
  });
});
it("renders dashboard statistics from the snapshot and loads registered books from the API", async () => {
  const fetch = vi.fn().mockResolvedValue(json([])); vi.stubGlobal("fetch", fetch);
  mount(<Dashboard data={fixtureSnapshot} />);
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("A clearer view");
  expect(screen.getAllByText("20,400")).toHaveLength(2);
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("books"), expect.anything()));
});
it("filters chunks by text and section through the chunk API", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const params = new URL(url, "http://localhost").searchParams;
    const q = (params.get("q") ?? "").toLowerCase(); const section = (params.get("section") ?? "").toLowerCase();
    const items = fixtureChunks.items.filter((c) => c.content.toLowerCase().includes(q) && String(c.metadata.section).toLowerCase().includes(section));
    return json({ ...fixtureChunks, total: items.length, items });
  }));
  mount(<Chunks data={fixtureSnapshot} />);
  await screen.findByText("3 matching chunks");
  fireEvent.change(screen.getByLabelText("Search chunk text"), { target: { value: "observations" } });
  fireEvent.change(screen.getByLabelText("Chapter or section"), { target: { value: "observations" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
  await screen.findByText("1 matching chunks");
  expect(screen.getByText("32 tokens")).toBeInTheDocument();
});
it("validates the search query before asking for confirmation", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  mount(<Search data={{ ...fixtureSnapshot, status: "ready" }} />);
  fireEvent.click(screen.getByRole("button", { name: "Review and search" }));
  expect(await screen.findByText("Enter a search query.")).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
it("requires confirmation before live search and displays request failures", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Operator access denied" }), { status: 403 })));
  mount(<Search data={{ ...fixtureSnapshot, status: "ready" }} />);
  fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "observation" } });
  fireEvent.click(screen.getByRole("button", { name: "Review and search" }));
  await screen.findByRole("dialog");
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Confirm search" }));
  expect(await screen.findByText("Operator access denied")).toBeInTheDocument();
});
it("keeps search available as keyword matching while the provider stop is set", () => {
  mount(<Search data={{ ...fixtureSnapshot, provider_paused: true }} />);
  expect(screen.getByRole("button", { name: "Review and search" })).toBeEnabled();
  expect(screen.getByText(/meaning-based search is off/)).toBeInTheDocument();
});
it("labels keyword results and warns that they are not meaning-based", async () => {
  const result = { query: "q", k: 5, latency_ms: 3, retrieval_mode: "keyword", incomplete_books: [], results: [{ chunk_id: "c1", book_id: "b1", book_title: "Materia Medica", book_category: "materia_medica", section_heading: "Arsenicum", section_path: [], content: "burning pain", similarity: 0.4, metadata: {}, retrieval_mode: "keyword", page_start: 7, page_end: 7, book_complete: true }] };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(result), { status: 200 })));
  mount(<Search data={fixtureSnapshot} />);
  fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "burning pain" } });
  fireEvent.click(screen.getByRole("button", { name: "Review and search" }));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm search" }));
  expect(await screen.findByText(/Keyword matching, not meaning-based search/)).toBeInTheDocument();
  expect(screen.getByText(/Keyword score 0.400/)).toBeInTheDocument();
});
it("maps network failures to a usable error", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
  await waitFor(async () => { await expect(api("books")).rejects.toThrow("Backend unreachable"); });
});
