import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CaseReport } from "./case-report";
import { CasePage } from "./case-page";
import { fixtureAnalysis } from "@/test/fixtures/cases-fixtures";
import type { Analysis, UrduReport } from "./types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
afterEach(() => { cleanup(); localStorage.removeItem(`similia.case-step.${record.id}`); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const record = { id: "11111111-aaaa", patient_id: "p1", status: "analyzed", chief_complaint: "itchy skin", language: "en", created_at: "", updated_at: "", symptoms: [] };
const patient = { id: "p1", identifier: "P/1 x", full_name: "Test Patient", age_years: 35, sex: "female", preferred_language: "en" };
const longText = "word ".repeat(300);
const analysis = (over: Partial<Analysis> = {}): Analysis => ({
  ...fixtureAnalysis, id: "an1", case_id: record.id, ...over,
  passages: [{ ...fixtureAnalysis.passages[0], book_title: "Kent Repertory", book_author: "J. T. Kent", section_path: ["Part 1", "Skin"], page_start: 41, page_end: null, content: longText }],
});
const urdu: UrduReport = {
  analysis_id: "an1", chief_complaint: "جلد میں خارش",
  red_flags: [], cautions: [], missing_information: ["کیا درد ایک طرف ہے؟"], notice: "مشینی ترجمہ: اسے جانچ لیں۔",
  remedies: [{ remedy: "Demonstration remedy A", rationale: "دوا کی وجہ", matching_symptoms: ["روشنی میں سر درد"], contradicting_symptoms: [] }],
};

function stub(an: Analysis | null, onUrdu?: () => Response) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    void init;
    if (u.includes("/report/urdu")) return onUrdu ? onUrdu() : json(urdu);
    if (u.endsWith("/analysis")) return an ? json(an) : json({ detail: "none" }, 404);
    if (u.includes("/patients/")) return json(patient);
    return json(record);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
const urduCalls = (f: ReturnType<typeof vi.fn>) => f.mock.calls.filter(([u]) => String(u).includes("/report/urdu"));

describe("case report (English)", () => {
  it("renders every section of the saved analysis", async () => {
    stub(analysis());
    mount(<CaseReport id={record.id} />);
    expect(await screen.findByRole("heading", { name: "Similia AI - Case analysis report" })).toBeInTheDocument();
    expect(screen.getByText("Test Patient")).toBeInTheDocument();
    expect(screen.getByText("P/1 x")).toBeInTheDocument();
    expect(screen.getByText("35 years / Female")).toBeInTheDocument();
    expect(screen.getByText("11111111")).toBeInTheDocument();
    expect(screen.getByText("Not signed off - draft analysis")).toBeInTheDocument();
    expect(screen.getByText("itchy skin")).toBeInTheDocument();
    expect(screen.getByText(/Demonstration remedy A/)).toBeInTheDocument();
    expect(screen.getByText("Headache worse in bright light")).toBeInTheDocument();
    expect(screen.getByText("Fits")).toBeInTheDocument();
    expect(screen.getByText("Against")).toBeInTheDocument();
    expect(screen.getByText("PDF page 41")).toBeInTheDocument();
    expect(screen.getByText("Kent Repertory")).toBeInTheDocument();
    expect(screen.getByText("AI interpretation")).toBeInTheDocument();
    expect(screen.getByText("Book text")).toBeInTheDocument();
    const excerpt = screen.getByText(/^word word/);
    expect(excerpt.textContent!.length).toBeLessThanOrEqual(601);
    expect(excerpt.textContent!.endsWith("…")).toBe(true);
    expect(screen.getByText("Synthetic example: is the pain one-sided?")).toBeInTheDocument();
    expect(screen.getByText(/Not a diagnosis or prescription/)).toBeInTheDocument();
  });
  it("shows the signed-off state from the case status", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => String(url).endsWith("/analysis") ? json(analysis()) : String(url).includes("/patients/") ? json(patient) : json({ ...record, status: "signed_off" })));
    mount(<CaseReport id={record.id} />);
    expect(await screen.findByText("Signed off by the practitioner")).toBeInTheDocument();
  });
  it("shows the keyword and partly-indexed banners when flagged", async () => {
    stub(analysis({ retrieval_mode: "keyword", incomplete_books: ["Kent Repertory"] }));
    mount(<CaseReport id={record.id} />);
    expect(await screen.findByText(/found by keyword matching, not meaning-based search/)).toBeInTheDocument();
    expect(screen.getByText(/partly indexed books/)).toHaveTextContent("Kent Repertory");
  });
  it("shows no banners for a clean semantic analysis", async () => {
    stub(analysis());
    mount(<CaseReport id={record.id} />);
    await screen.findByText(/Demonstration remedy A/);
    expect(screen.queryByText(/keyword matching/)).toBeNull();
    expect(screen.queryByText(/partly indexed/)).toBeNull();
  });
  it("shows only the urgent notes for a red-flag analysis", async () => {
    stub(analysis({ outcome: "red_flag", red_flags: ["Possible heart emergency"], remedies: [], passages: [], missing_information: [] }));
    mount(<CaseReport id={record.id} />);
    expect(await screen.findByText("Possible heart emergency")).toBeInTheDocument();
    expect(screen.queryByText("Suggested remedies")).toBeNull();
    expect(screen.queryByText("Book text")).toBeNull();
  });
  it("prints through the browser once", async () => {
    stub(analysis());
    const print = vi.fn();
    vi.stubGlobal("print", print);
    mount(<CaseReport id={record.id} />);
    fireEvent.click(await screen.findByRole("button", { name: /Print \/ Save as PDF/ }));
    expect(print).toHaveBeenCalledTimes(1);
  });
  it("downloads one script-free HTML file without any request", async () => {
    const fetchMock = stub(analysis());
    mount(<CaseReport id={record.id} />);
    await screen.findByText(/Demonstration remedy A/);
    const callsBefore = fetchMock.mock.calls.length;
    let blob: Blob | undefined;
    URL.createObjectURL = vi.fn((b: Blob) => { blob = b; return "blob:x"; });
    URL.revokeObjectURL = vi.fn();
    const names: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    fireEvent.click(screen.getByRole("button", { name: /Download HTML file/ }));
    expect(click).toHaveBeenCalledTimes(1);
    expect(names).toEqual(["case-P-1-x-report-en.html"]);
    expect(fetchMock.mock.calls.length).toBe(callsBefore);
    const text = await new Promise<string>((resolve) => { const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.readAsText(blob!); });
    expect(text).toMatch(/^<!doctype html>/);
    expect(text).toContain("Demonstration remedy A");
    expect(text.toLowerCase()).not.toContain("<script");
    expect(text).not.toContain("Print / Save as PDF");
  });
  it("downloads a server-made PDF or Word file with one POST and no AI call", async () => {
    const fetchMock = stub(analysis());
    mount(<CaseReport id={record.id} />);
    await screen.findByText(/Demonstration remedy A/);
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) =>
      String(url).includes("/report/file") ? new Response(new Blob(["%PDF-1.7"]), { status: 200 }) : original(url, init));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    await waitFor(() => expect(names).toEqual(["case-11111111-report-en.pdf"]));
    fireEvent.click(screen.getByRole("button", { name: "Download Word (.docx)" }));
    await waitFor(() => expect(names).toEqual(["case-11111111-report-en.pdf", "case-11111111-report-en.docx"]));
    const posts = fetchMock.mock.calls.filter(([u]) => String(u).includes("/report/file"));
    expect(posts).toHaveLength(2);
    expect(String(posts[0][0])).toBe("/api/backend/cases/11111111-aaaa/report/file");
    expect(JSON.parse(String(posts[0][1]?.body))).toEqual({ format: "pdf", lang: "en", analysis_id: "an1" });
    expect(urduCalls(fetchMock)).toHaveLength(0);
  });
  it("shows the backend's message when the file cannot be made and downloads nothing", async () => {
    const fetchMock = stub(analysis());
    mount(<CaseReport id={record.id} />);
    await screen.findByText(/Demonstration remedy A/);
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) =>
      String(url).includes("/report/file") ? json({ detail: "The report file could not be created." }, 500) : original(url, init));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    expect(await screen.findByText("The report file could not be created.")).toBeInTheDocument();
    expect(click).not.toHaveBeenCalled();
  });
  it("sends the Urdu translation with the Urdu file request", async () => {
    const fetchMock = stub(analysis());
    mount(<CaseReport id={record.id} />);
    await screen.findByText(/Demonstration remedy A/);
    fireEvent.click(screen.getByRole("button", { name: "اردو" }));
    fireEvent.click(await screen.findByRole("button", { name: "Translate to Urdu" }));
    await screen.findByText("جلد میں خارش");
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) =>
      String(url).includes("/report/file") ? new Response(new Blob(["%PDF"]), { status: 200 }) : original(url, init));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/report/file"))).toBe(true));
    const post = fetchMock.mock.calls.find(([u]) => String(u).includes("/report/file"))!;
    const body = JSON.parse(String(post[1]?.body));
    expect(body.lang).toBe("ur");
    expect(body.translation.chief_complaint).toBe("جلد میں خارش");
  });
  it("says so when there is no saved analysis", async () => {
    stub(null);
    mount(<CaseReport id={record.id} />);
    expect(await screen.findByText(/no saved analysis yet/)).toBeInTheDocument();
  });
});

describe("case report (Urdu)", () => {
  it("asks first and requests nothing until the doctor confirms", async () => {
    const fetchMock = stub(analysis());
    mount(<CaseReport id={record.id} />);
    await screen.findByText(/Demonstration remedy A/);
    fireEvent.click(screen.getByRole("button", { name: "اردو" }));
    expect(screen.getByText(/not the patient's name, ID or contact/)).toBeInTheDocument();
    expect(screen.getByText(/Machine translation: have it checked/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Print/ })).toBeDisabled();
    expect(urduCalls(fetchMock)).toHaveLength(0);
  });
  it("posts once on confirmation, shows rtl Urdu with a ltr English excerpt, and does not post again when switching", async () => {
    const fetchMock = stub(analysis());
    mount(<CaseReport id={record.id} />);
    await screen.findByText(/Demonstration remedy A/);
    fireEvent.click(screen.getByRole("button", { name: "اردو" }));
    fireEvent.click(screen.getByRole("button", { name: "Translate to Urdu" }));
    const sheet = await screen.findByRole("article");
    expect(sheet).toHaveAttribute("dir", "rtl");
    expect(sheet).toHaveAttribute("lang", "ur");
    expect(within(sheet).getByText("جلد میں خارش")).toBeInTheDocument();
    expect(within(sheet).getByText("دوا کی وجہ")).toBeInTheDocument();
    expect(within(sheet).getByText("مشینی ترجمہ: اسے جانچ لیں۔")).toBeInTheDocument();
    expect(within(sheet).getByText(/^word word/)).toHaveAttribute("dir", "ltr");
    expect(within(sheet).getByText("Demonstration remedy A")).toBeInTheDocument();
    expect(urduCalls(fetchMock)).toHaveLength(1);
    const [url, init] = urduCalls(fetchMock)[0];
    expect(String(url)).toBe(`/api/backend/cases/${record.id}/report/urdu?analysis_id=an1`);
    expect((init as RequestInit).method).toBe("POST");
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(screen.getByRole("article")).toHaveAttribute("dir", "ltr");
    fireEvent.click(screen.getByRole("button", { name: "اردو" }));
    expect(await screen.findByText("دوا کی وجہ")).toBeInTheDocument();
    expect(urduCalls(fetchMock)).toHaveLength(1);
  });
  it("shows the add-key notice on 428", async () => {
    stub(analysis(), () => json({ detail: "Add your own AI key in AI Settings to use this feature" }, 428));
    mount(<CaseReport id={record.id} />);
    await screen.findByText(/Demonstration remedy A/);
    fireEvent.click(screen.getByRole("button", { name: "اردو" }));
    fireEvent.click(screen.getByRole("button", { name: "Translate to Urdu" }));
    expect(await screen.findByText(/Add your own AI key/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open AI Settings" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("Report button on the case page", () => {
  async function openAnalyseStep(an: Analysis | null) {
    stub(an);
    mount(<CasePage id={record.id} />);
    fireEvent.click(await screen.findByRole("button", { name: /Analyse/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Run analysis/ })).toBeInTheDocument());
  }
  it("links to the report page when a usable analysis exists", async () => {
    await openAnalyseStep(analysis());
    expect(await screen.findByRole("link", { name: "Report" })).toHaveAttribute("href", `/workspace/report/${record.id}`);
  });
  it("returns to the last step when the case page is reopened", async () => {
    await openAnalyseStep(analysis());
    cleanup();
    mount(<CasePage id={record.id} />);

    expect(await screen.findByRole("button", { name: /Analyse/ })).toHaveAttribute("aria-current", "step");
    expect(await screen.findByRole("button", { name: "Run analysis again" })).toBeInTheDocument();
  });
  it("reruns an existing keyword analysis with the selected semantic method", async () => {
    const previous = analysis({ retrieval_mode: "keyword" });
    const next = analysis({ id: "an2", retrieval_mode: "semantic", requested_mode: "semantic" });
    const analyze = vi.fn(() => json(next, 201));
    await openAnalyseStep(previous);
    const read = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation((input, init) => String(input).includes("/analyze?")
      ? Promise.resolve(analyze())
      : read(input, init));

    fireEvent.change(screen.getByLabelText("Search method"), { target: { value: "semantic" } });
    fireEvent.click(screen.getByRole("button", { name: "Run analysis again" }));

    await waitFor(() => expect(screen.getByTestId("search-method")).toHaveTextContent("Search method used: Semantic"));
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/analyze?search_mode=semantic"), expect.objectContaining({ method: "POST" }));
    expect(analyze).toHaveBeenCalledTimes(1);
  });
  it("is hidden when there is no analysis or it is a red flag", async () => {
    await openAnalyseStep(null);
    expect(screen.queryByRole("link", { name: "Report" })).toBeNull();
    cleanup();
    await openAnalyseStep(analysis({ outcome: "red_flag", red_flags: ["x"], remedies: [] }));
    expect(screen.queryByRole("link", { name: "Report" })).toBeNull();
  });
  it("shows a failed acknowledged retry beside the safety notice and reports no search for the earlier run", async () => {
    await openAnalyseStep(analysis({ outcome: "red_flag", red_flags: ["Synthetic concern"], remedies: [] }));
    const read = vi.mocked(fetch).getMockImplementation()!;
    const detail = "The source library could not be searched. Try again later.";
    let finish!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => { finish = resolve; });
    vi.mocked(fetch).mockImplementation((input, init) => String(input).includes("/analyze?")
      ? pending
      : read(input, init));

    fireEvent.click(await screen.findByRole("button", { name: /I have assessed this myself/ }));
    fireEvent.click(screen.getByRole("button", { name: /Analyse anyway/ }));
    const busy = await screen.findByRole("button", { name: /^Analysing$/ });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy.querySelectorAll("circle")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Run analysis again" })).toBeDisabled();
    finish(json({ detail }, 502));

    const error = await screen.findByText(detail);
    expect(error.closest('[role="alert"]')?.previousElementSibling).toHaveTextContent("Possible urgent concern");
    expect(screen.getByText("Library search was skipped.")).toBeInTheDocument();
    expect(screen.queryByTestId("search-method")).toBeNull();
    expect(screen.queryByRole("link", { name: "Report" })).toBeNull();
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("acknowledge_red_flags=true"), expect.objectContaining({ method: "POST" }));
  });
});
