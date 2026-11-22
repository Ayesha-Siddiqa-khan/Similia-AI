import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Search } from "./search";
import { fixtureSnapshot } from "@/test/fixtures/workspace-fixtures";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const passage = (over = {}) => ({ chunk_id: "c1", book_id: "b1", book_title: "Test Book", book_category: "materia_medica", section_heading: "Arnica", content: "Passage text.", similarity: 0.9, metadata: {}, section_path: ["Part 2", "Arnica"], page_start: 12, page_end: 14, book_complete: true, ...over });
async function run(response: unknown) {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><Search data={fixtureSnapshot} /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Search query"), { target: { value: "bruise" } });
  fireEvent.click(screen.getByRole("button", { name: /Review and search/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Confirm search" }));
  await waitFor(() => expect(fetch).toHaveBeenCalled());
}

describe("search evidence", () => {
  it("shows PDF page range and section path without an incomplete notice", async () => {
    await run({ query: "bruise", k: 5, latency_ms: 10, results: [passage()], incomplete_books: [] });
    expect(await screen.findByText("PDF pages 12–14")).toBeInTheDocument();
    expect(screen.getByText("Section path: Part 2 › Arnica")).toBeInTheDocument();
    expect(screen.queryByText(/partly indexed/)).not.toBeInTheDocument();
  });
  it("shows the incomplete-books notice and marks passages from partly indexed books", async () => {
    await run({ query: "bruise", k: 5, latency_ms: 10, results: [passage({ book_complete: false, page_end: 12 })], incomplete_books: ["Test Book"] });
    expect(await screen.findByText("PDF page 12")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/Test Book.*missing evidence from the unindexed parts/);
    expect(screen.getByText("from a partly indexed book")).toBeInTheDocument();
  });
});
