import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Books } from "./books";
import { fixtureSnapshot } from "@/test/fixtures/workspace-fixtures";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

function setup(uploadResponse: Response) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    if (init?.method === "POST" && u.endsWith("/books")) return uploadResponse.clone();
    if (u.includes("ingestion/overview")) return reply({ limits: {}, active_jobs: [], books: [{ book_id: "r1", title: "Registered", category: "repertory", source_filename: "r.pdf", total_pages: 5, total_chunks: 10, embedded_chunks: 4, pending_chunks: 6, embedded_tokens: 1, pending_tokens: 2, prepared: true, complete: false, frozen_plan: false }] });
    if (u.endsWith("/books")) return reply([{ id: "r1", title: "Registered", source_filename: "r.pdf", category: "repertory", author: null, section_count: 1, chunk_count: 10, metadata: {} }]);
    return reply({});
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><Books data={fixtureSnapshot} /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: /Upload PDF/ }));
  return fetch;
}
const fill = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const choosePdf = () => fireEvent.change(screen.getByLabelText(/PDF file/), { target: { files: [new File(["%PDF-1.4"], "book.pdf", { type: "application/pdf" })] } });
const posted = (fetch: ReturnType<typeof setup>) => fetch.mock.calls.find(([, init]) => init?.method === "POST")?.[1]?.body as FormData | undefined;

describe("upload form", () => {
  it("sends the exact multipart field names and omits empty optionals", async () => {
    const fetch = setup(reply({ id: "n1" }, 201));
    choosePdf(); fill("Book title", "  My Book "); fill("Category", "organon");
    fireEvent.click(screen.getByRole("button", { name: "Register book" }));
    await waitFor(() => expect(posted(fetch)).toBeTruthy());
    const form = posted(fetch)!;
    expect([...form.keys()].sort()).toEqual(["category", "file", "language", "title"]);
    expect(form.get("title")).toBe("My Book"); expect(form.get("category")).toBe("organon"); expect(form.get("language")).toBe("en");
  });
  it("sends every optional field when filled", async () => {
    const fetch = setup(reply({ id: "n1" }, 201));
    choosePdf(); fill("Book title", "T"); fill("Author (optional)", "A"); fill("Publisher (optional)", "P"); fill("Publication year (optional)", "1890"); fill("Language", "de"); fill("Source URI (optional)", "https://example.org/x");
    fireEvent.click(screen.getByRole("button", { name: "Register book" }));
    await waitFor(() => expect(posted(fetch)).toBeTruthy());
    const form = posted(fetch)!;
    expect([...form.keys()].sort()).toEqual(["author", "category", "file", "language", "publication_year", "publisher", "source_uri", "title"]);
    expect(form.get("publication_year")).toBe("1890"); expect(form.get("language")).toBe("de");
  });
  it("shows field-level errors and does not send", () => {
    const fetch = setup(reply({}, 201));
    choosePdf(); fill("Publication year (optional)", "2200");
    fireEvent.click(screen.getByRole("button", { name: "Register book" }));
    expect(screen.getByText("Enter a title.")).toBeInTheDocument();
    expect(screen.getByText("Enter a year from 0 to 2100.")).toBeInTheDocument();
    expect(posted(fetch)).toBeUndefined();
  });
  it("shows the backend text for 409", async () => {
    setup(reply({ detail: "This book is already registered." }, 409));
    choosePdf(); fill("Book title", "T");
    fireEvent.click(screen.getByRole("button", { name: "Register book" }));
    expect(await screen.findByText("This book is already registered.")).toBeInTheDocument();
  });
  it("shows the backend text for 422", async () => {
    setup(reply({ detail: "The file is not a valid PDF." }, 422));
    choosePdf(); fill("Book title", "T");
    fireEvent.click(screen.getByRole("button", { name: "Register book" }));
    expect(await screen.findByText("The file is not a valid PDF.")).toBeInTheDocument();
  });
  it("after success says the book is not searchable yet and links to Ingestion Jobs", async () => {
    setup(reply({ id: "n1" }, 201));
    choosePdf(); fill("Book title", "T");
    fireEvent.click(screen.getByRole("button", { name: "Register book" }));
    expect(await screen.findByText(/not searchable yet/)).toBeInTheDocument();
    expect(screen.getByText(/only after you confirm/)).toBeInTheDocument();
    const link = screen.getAllByRole("link", { name: "Open Ingestion Jobs" })[0];
    expect(link).toHaveAttribute("href", "/workspace/ingestion");
  });
  it("shows real index progress for registered books", async () => {
    setup(reply({}, 201));
    expect(await screen.findByText("Partly indexed")).toBeInTheDocument();
    expect(screen.getByText(/4 of 10 chunks embedded/)).toBeInTheDocument();
  });
});
