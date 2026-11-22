import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnalysisView } from "./analysis-view";
import { fixtureAnalysis } from "@/test/fixtures/cases-fixtures";
import type { Analysis } from "./types";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const props = { caseId: "c1", status: "analyzed" as const, onAcknowledge: vi.fn(), acknowledging: false };
function mount(analysis: Analysis) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><AnalysisView analysis={analysis} {...props} /></QueryClientProvider>);
}
const withEvidence = (over: Partial<Analysis["passages"][number]> = {}, extra: Partial<Analysis> = {}): Analysis => ({
  ...fixtureAnalysis, ...extra,
  passages: [{ ...fixtureAnalysis.passages[0], book_author: "J. T. Kent", section_path: ["Part 1", "Headache"], page_start: 41, page_end: 43, book_complete: true, ...over }],
});

describe("analysis evidence", () => {
  it("shows author, section path, PDF page range and the two labels", () => {
    mount(withEvidence());
    expect(screen.getByText(/J\. T\. Kent/)).toBeInTheDocument();
    expect(screen.getByText(/Part 1 › Headache/)).toBeInTheDocument();
    expect(screen.getByText("PDF pages 41–43")).toBeInTheDocument();
    expect(screen.getByText("Book text")).toBeInTheDocument();
    expect(screen.getByText("AI interpretation")).toBeInTheDocument();
    expect(screen.queryByText(/partly indexed/)).not.toBeInTheDocument();
  });
  it("warns naming the books when analysis.incomplete_books is set", () => {
    mount(withEvidence({}, { incomplete_books: ["Synthetic demonstration source"] }));
    expect(screen.getByRole("alert")).toHaveTextContent(/partly indexed books: Synthetic demonstration source.*missing evidence/);
  });
  it("says so when passages were found by keyword matching", () => {
    mount(withEvidence({ retrieval_mode: "keyword" }, { retrieval_mode: "keyword" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/keyword matching, not meaning-based search/);
  });
  it("shows no keyword warning for meaning-based results", () => {
    mount(withEvidence({}));
    expect(screen.queryByText(/keyword matching/)).not.toBeInTheDocument();
  });
  it("warns when a passage has book_complete false even without the list", () => {
    mount(withEvidence({ book_complete: false }));
    expect(screen.getByRole("alert")).toHaveTextContent(/Synthetic demonstration source.*missing evidence/);
    expect(screen.getByText("from a partly indexed book")).toBeInTheDocument();
  });
});
