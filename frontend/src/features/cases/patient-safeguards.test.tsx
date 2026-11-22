import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnalysisView } from "./analysis-view";
import { CasePage } from "./case-page";
import { PatientDetail, PatientsPage } from "./patients";
import { fixtureAnalysis, fixturePatient } from "@/test/fixtures/cases-fixtures";
import type { Analysis, CaseHistoryItem, CaseRecord, ConsentRecord, Patient } from "./types";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); push.mockReset(); });

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const adult: Patient = { ...fixturePatient, id: "p1", identifier: "P-1", full_name: "Adult Patient" };
const archived: Patient = { ...adult, archived_at: "2026-11-01T00:00:00Z", consent_active: false };
const consents: ConsentRecord[] = [
  { id: "k2", purpose: "care", text_version: "v1", granted_at: "2026-11-02T00:00:00Z", withdrawn_at: null },
  { id: "k1", purpose: "care", text_version: "v1", granted_at: "2026-10-01T00:00:00Z", withdrawn_at: "2026-10-20T00:00:00Z" },
];
const history: CaseHistoryItem[] = [{ id: "c1", status: "signed_off", chief_complaint: "itchy skin", language: "en", created_at: "2026-10-05T00:00:00Z", updated_at: "2026-10-06T00:00:00Z", analysis_count: 2, latest_outcome: "ranked", review_decision: "accepted", chosen_remedy: "Sulphur-test", signed_at: "2026-10-06T00:00:00Z" }];

type Call = { url: string; method: string; body?: unknown };
/** A stand-in backend for the patient page. Every request is recorded. */
function stubPatientApi(patient: Patient) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url).replace("/api/backend/", "");
    const method = init?.method ?? "GET";
    calls.push({ url: u, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (u.endsWith("/consents")) return json(consents);
    if (u.endsWith("/history")) return json(history);
    if (u.endsWith("/export")) return json({ format: "similia-patient-export-v1", patient });
    if (u.endsWith("/consent/withdraw")) return json({ ...patient, archived_at: "2026-11-03T00:00:00Z", consent_active: false });
    if (method === "DELETE") return new Response(null, { status: 204 });
    return json(patient);
  }));
  return calls;
}

describe("new patient: guardian for a child", () => {
  function stubCreate() {
    const calls: Call[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ url: String(url), method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return method === "POST" ? json(adult, 201) : json([]);
    }));
    return calls;
  }
  async function fillBasics(age: string) {
    fireEvent.click(await screen.findByRole("button", { name: /New patient/ }));
    fireEvent.change(screen.getByLabelText("Patient ID"), { target: { value: "P-9" } });
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Young Test" } });
    fireEvent.change(screen.getByLabelText("Age (years)"), { target: { value: age } });
    fireEvent.click(screen.getByLabelText(/has given informed consent/));
  }
  it("asks for a guardian and refuses to save without one", async () => {
    const calls = stubCreate();
    mount(<PatientsPage />);
    await fillBasics("9");
    expect(await screen.findByLabelText("Guardian name")).toBeInTheDocument();
    expect(screen.getByLabelText("Relationship to patient")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create patient" }));
    expect((await screen.findAllByText(/need a guardian's name and relationship/)).length).toBe(2);
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
  it("sends the guardian details for a child", async () => {
    const calls = stubCreate();
    mount(<PatientsPage />);
    await fillBasics("9");
    fireEvent.change(await screen.findByLabelText("Guardian name"), { target: { value: "Parent Test" } });
    fireEvent.change(screen.getByLabelText("Relationship to patient"), { target: { value: "Mother" } });
    fireEvent.click(screen.getByRole("button", { name: "Create patient" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ age_years: 9, guardian_name: "Parent Test", guardian_relationship: "Mother" });
  });
  it("asks for a guardian when the date of birth is under 18 years ago", async () => {
    stubCreate();
    mount(<PatientsPage />);
    await fillBasics("");
    const year = new Date().getFullYear() - 5;
    fireEvent.change(screen.getByLabelText(/Date of birth/), { target: { value: `${year}-01-01` } });
    expect(await screen.findByLabelText("Guardian name")).toBeInTheDocument();
  });
  it("shows no guardian fields for an adult and sends no guardian values", async () => {
    const calls = stubCreate();
    mount(<PatientsPage />);
    await fillBasics("35");
    expect(screen.queryByLabelText("Guardian name")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Create patient" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ guardian_name: null, guardian_relationship: null });
  });
});

describe("patients list", () => {
  const rows: Patient[] = [adult, { ...adult, id: "p2", identifier: "P-2", full_name: "Old Record", archived_at: "2026-11-01T00:00:00Z", consent_active: false }, { ...adult, id: "p3", identifier: "P-3", full_name: "Small Child", age_years: 6, is_minor: true }];
  it("hides archived patients until asked, and badges children and withdrawn consent", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(rows)));
    mount(<PatientsPage />);
    expect(await screen.findByText("Adult Patient")).toBeInTheDocument();
    expect(screen.queryByText("Old Record")).toBeNull();
    expect(screen.getByText("Child")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Show archived/));
    expect(await screen.findByText("Old Record")).toBeInTheDocument();
    expect(screen.getByText("Consent withdrawn")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/Show archived/));
    expect(screen.queryByText("Old Record")).toBeNull();
  });
});

describe("patient page", () => {
  beforeEach(() => { URL.createObjectURL = vi.fn(() => "blob:test"); URL.revokeObjectURL = vi.fn(); });
  it("shows consent history and the case history with the signed remedy", async () => {
    stubPatientApi(adult);
    mount(<PatientDetail id="p1" />);
    expect(await screen.findByText(/Withdrawn 20 Oct 2026/)).toBeInTheDocument();
    expect(screen.getByText("Consent active")).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "itchy skin" });
    expect(link).toHaveAttribute("href", "/workspace/case/c1");
    expect(screen.getByText(/2 analyses/)).toBeInTheDocument();
    expect(screen.getByText(/Signed remedy: Sulphur-test on 6 Oct 2026/)).toBeInTheDocument();
  });
  it("withdraws consent only after the confirmation, and cancelling sends nothing", async () => {
    const calls = stubPatientApi(adult);
    mount(<PatientDetail id="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Withdraw consent" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(/stops all AI use/);
    expect(dialog).toHaveTextContent(/Nothing is deleted/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Withdraw consent" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Withdraw consent" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(1));
    expect(calls.find((c) => c.method === "POST")!.url).toBe("patients/p1/consent/withdraw");
  });
  it("disables starting a case for an archived patient and offers to record consent again", async () => {
    stubPatientApi(archived);
    mount(<PatientDetail id="p1" />);
    expect(await screen.findByRole("button", { name: "Start new case" })).toBeDisabled();
    expect(screen.getAllByText(/archived \(read-only\)/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Record consent again" })).toBeInTheDocument();
    expect(screen.getByLabelText("Full name")).toBeDisabled();
  });
  it("does not show the erase section for an active patient", async () => {
    stubPatientApi(adult);
    mount(<PatientDetail id="p1" />);
    await screen.findByText("Consent active");
    expect(screen.queryByText("Erase patient")).toBeNull();
  });
  it("keeps the erase button disabled until the exact ID is typed, then deletes and leaves the page", async () => {
    const calls = stubPatientApi(archived);
    mount(<PatientDetail id="p1" />);
    const button = await screen.findByRole("button", { name: /Erase patient permanently/ });
    const input = screen.getByLabelText("Type the patient ID to confirm");
    expect(button).toBeDisabled();
    fireEvent.change(input, { target: { value: "p-1" } });
    expect(button).toBeDisabled();
    fireEvent.change(input, { target: { value: "P-1" } });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/workspace/patients"));
    const deletes = calls.filter((c) => c.method === "DELETE");
    expect(deletes).toHaveLength(1);
    expect(deletes[0].url).toBe("patients/p1?confirm_identifier=P-1");
  });
  it("shows the server's message when erasing fails and does not leave the page", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => init?.method === "DELETE" ? json({ detail: "The ID you typed does not match this patient." }, 422) : String(url).endsWith("/consents") || String(url).endsWith("/history") ? json([]) : json(archived)));
    mount(<PatientDetail id="p1" />);
    fireEvent.change(await screen.findByLabelText("Type the patient ID to confirm"), { target: { value: "P-1" } });
    fireEvent.click(screen.getByRole("button", { name: /Erase patient permanently/ }));
    expect(await screen.findByText(/does not match this patient/)).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
  it("downloads the record as a JSON file with one request and no others", async () => {
    const calls = stubPatientApi(adult);
    const names: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    mount(<PatientDetail id="p1" />);
    await screen.findByText("Consent active");
    const before = calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Download patient record" }));
    await waitFor(() => expect(names).toEqual(["patient-P-1.json"]));
    expect(calls.slice(before).map((c) => c.url)).toEqual(["patients/p1/export"]);
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    click.mockRestore();
  });
});

describe("cautions and earlier analyses", () => {
  const props = { caseId: "c1", status: "analyzed" as const, onAcknowledge: vi.fn(), acknowledging: false };
  it("shows the paediatric caution above the remedies", () => {
    mount(<AnalysisView analysis={{ ...fixtureAnalysis, cautions: ["Child patient: dose and potency need extra care."] }} {...props} />);
    const caution = screen.getByText(/dose and potency need extra care/);
    expect(caution).toBeInTheDocument();
    expect(caution.compareDocumentPosition(screen.getByText(/Demonstration remedy A/)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it("shows the infant red-flag text and still needs the two-step acknowledgement", () => {
    const onAcknowledge = vi.fn();
    mount(<AnalysisView analysis={{ ...fixtureAnalysis, outcome: "red_flag", remedies: [], red_flags: ["Infant under 1 year: seek paediatric care first."] }} {...props} onAcknowledge={onAcknowledge} />);
    expect(screen.getByText(/Infant under 1 year/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /I have assessed this myself/ }));
    fireEvent.click(screen.getByRole("button", { name: /Analyse anyway/ }));
    expect(onAcknowledge).toHaveBeenCalledTimes(1);
  });

  const record: CaseRecord = { id: "c1", patient_id: "p1", status: "draft", chief_complaint: "itchy skin", language: "en", created_at: "", updated_at: "", symptoms: [] };
  const earlier: Analysis = { ...fixtureAnalysis, id: "old-1", created_at: "2026-10-01T10:00:00Z", remedies: [{ ...fixtureAnalysis.remedies[0], remedy: "Earlier remedy Z" }] };
  function stubCase(patient: Patient, calls: Call[] = []) {
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url).replace("/api/backend/", "");
      calls.push({ url: u, method: init?.method ?? "GET" });
      if (u === "cases/c1/analyses") return json([earlier]);
      if (u.endsWith("/analysis")) return json({ detail: "none" }, 404);
      if (u.startsWith("patients/")) return json(patient);
      if (init?.method === "PATCH" || init?.method === "PUT") return json({ detail: "This patient is archived (read-only). Re-grant consent to reopen the record." }, 409);
      return json(record);
    }));
  }
  it("lists earlier analyses only once the section is opened", async () => {
    const calls: Call[] = [];
    stubCase(adult, calls);
    mount(<CasePage id="c1" />);
    await screen.findByText("Earlier analyses");
    expect(calls.some((c) => c.url.endsWith("/analyses"))).toBe(false);
    fireEvent.click(screen.getByText("Earlier analyses"));
    expect((await screen.findAllByText(/Earlier remedy Z/)).length).toBeGreaterThan(0);
    expect(screen.getByText("Remedies suggested")).toBeInTheDocument();
    expect(screen.getByText(/1 Oct 2026/)).toBeInTheDocument();
  });
  it("makes the case read-only for an archived patient and sends no saves", async () => {
    const calls: Call[] = [];
    stubCase(archived, calls);
    mount(<CasePage id="c1" />);
    expect(await screen.findByText(/This patient is archived \(read-only\)\./)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText(/What brings the patient in/)).toBeDisabled());
    expect(calls.filter((c) => c.method === "PATCH" || c.method === "PUT")).toHaveLength(0);
  });
  it("shows the archived message once when a save is refused, without retrying", async () => {
    const calls: Call[] = [];
    stubCase(adult, calls);
    mount(<CasePage id="c1" />);
    fireEvent.change(await screen.findByLabelText(/What brings the patient in/), { target: { value: "itchy skin for two years" } });
    expect(await screen.findByText(/archived \(read-only\)\. Re-grant consent/, undefined, { timeout: 4000 })).toBeInTheDocument();
    const saves = calls.filter((c) => c.method === "PATCH").length;
    await new Promise((resolve) => setTimeout(resolve, 2600));
    expect(calls.filter((c) => c.method === "PATCH").length).toBe(saves);
  }, 12000);
});
