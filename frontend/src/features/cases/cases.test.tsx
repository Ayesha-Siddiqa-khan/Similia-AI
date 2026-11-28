import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnalysisView } from "./analysis-view";
import { CasePage } from "./case-page";
import { PatientsPage } from "./patients";
import { SymptomEditor } from "./symptom-editor";
import { fixtureAiSettings, fixtureAnalysis, fixturePatient } from "@/test/fixtures/cases-fixtures";
import type { Analysis, CaseRecord, Symptom } from "./types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

// Stand-in for the backend: serves one case and its patient, and says there is no analysis yet.
function stubCaseApi(over: Partial<CaseRecord> = {}) {
  const record: CaseRecord = { id: "c1", patient_id: "p1", status: "draft", chief_complaint: "itchy skin", language: "en", created_at: "", updated_at: "", symptoms: [], ...over };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const u = String(url);
    if (u.includes("/analysis")) return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
    if (u.includes("/patients/")) return new Response(JSON.stringify({ id: "p1", identifier: "P-1", full_name: "Test Patient", preferred_language: "en" }), { status: 200 });
    return new Response(JSON.stringify(record), { status: 200 });
  }));
}

describe("symptom editor", () => {
  it("adds a quick-add prompt and edits modalities", () => {
    const onChange = vi.fn();
    mount(<SymptomEditor kind="physical_general" symptoms={[]} onChange={onChange} disabled={false} />);
    fireEvent.click(screen.getByRole("button", { name: "+ Thirst" }));
    expect(onChange).toHaveBeenCalledWith([{ kind: "physical_general", label: "Thirst", weight: 2, key: expect.any(String) }]);
  });
  it("only shows entries of its own kind and removes by index", () => {
    const symptoms: Symptom[] = [{ kind: "mental", label: "Fear of dark", weight: 3 }, { kind: "particular", label: "Headache", weight: 2 }];
    const onChange = vi.fn();
    mount(<SymptomEditor kind="particular" symptoms={symptoms} onChange={onChange} disabled={false} />);
    expect(screen.queryByDisplayValue("Fear of dark")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remove Headache" }));
    expect(onChange).toHaveBeenCalledWith([symptoms[0]]);
  });
});

describe("analysis view", () => {
  const props = { caseId: "c1", status: "analyzed" as const, onAcknowledge: vi.fn(), acknowledging: false };
  it("shows cited sources for each remedy and the disclaimer", () => {
    mount(<AnalysisView analysis={fixtureAnalysis} {...props} />);
    expect(screen.getAllByText(/Demonstration remedy A/)[0]).toBeInTheDocument();
    expect(screen.getByText("Source chunk: demo-chunk-1")).toBeInTheDocument();
    expect(screen.getByText(/not clinical evidence/)).toBeInTheDocument();
  });
  it("blocks remedies on a red flag and needs two steps to acknowledge", () => {
    const onAcknowledge = vi.fn();
    mount(<AnalysisView analysis={{ ...fixtureAnalysis, outcome: "red_flag", red_flags: ["Possible heart or breathing emergency"], remedies: [] }} {...props} onAcknowledge={onAcknowledge} />);
    expect(screen.getByText(/Remedy analysis was not run/)).toBeInTheDocument();
    expect(screen.queryByText(/Demonstration remedy A/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /I have assessed this myself/ }));
    expect(onAcknowledge).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Analyse anyway/ }));
    expect(onAcknowledge).toHaveBeenCalledTimes(1);
  });
  it("never suggests a remedy when sources are insufficient", () => {
    mount(<AnalysisView analysis={{ ...fixtureAnalysis, outcome: "insufficient_sources", remedies: [] }} {...props} />);
    expect(screen.getByText(/does not contain enough supporting passages/)).toBeInTheDocument();
  });
});

describe("pages", () => {
  it("requires consent before a patient can be created", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    mount(<PatientsPage />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /New patient/ }));
    fireEvent.change(screen.getByLabelText("Patient ID"), { target: { value: "P-1" } });
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create patient" }));
    expect(await screen.findByText(/Record the patient's consent/)).toBeInTheDocument();
    expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith("/patients") && init?.method === "POST")).toBe(false);
  });
});

import { SuggestedQuestions } from "./suggested-questions";
describe("suggested questions", () => {
  const base = { step: "particular" as const, loading: false, canSuggest: true, urdu: false, onUrduChange: vi.fn(), onSuggest: vi.fn(), onUse: vi.fn() };
  const questions = { red_flags: [], mental: [], physical_general: [], history: [], disclaimer: "", particular: [{ topic: "Discharge", question: "What colour is the discharge?" }] };
  it("lists this step's questions and adds one to the case once", () => {
    const onUse = vi.fn();
    mount(<SuggestedQuestions {...base} questions={questions} onUse={onUse} />);
    fireEvent.click(screen.getByRole("button", { name: /Add to case/ }));
    expect(onUse).toHaveBeenCalledWith(questions.particular[0]);
    expect(screen.getByRole("button", { name: /Added/ })).toBeDisabled();
  });
  it("needs a chief complaint before asking the AI", () => {
    mount(<SuggestedQuestions {...base} questions={null} canSuggest={false} />);
    expect(screen.getByRole("button", { name: "Suggest questions" })).toBeDisabled();
  });
  it("shows the urgent notice instead of questions", () => {
    mount(<SuggestedQuestions {...base} questions={{ ...questions, red_flags: ["Possible heart or breathing emergency"] }} />);
    expect(screen.getByText(/Questions were not generated/)).toBeInTheDocument();
    expect(screen.queryByText("What colour is the discharge?")).toBeNull();
  });
});

import { AiSettingsPage } from "./ai-settings";
import { ApiErrorNotice } from "./api-error-notice";
import { ApiError } from "@/lib/backend";
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
describe("AI settings", () => {
  it("switches to Gemini with a separate key and model ID", async () => {
    const existing = { ...fixtureAiSettings, configured: true, key_last4: "WXYZ" };
    const saved = { ...existing, provider: "gemini", model: "gemini-example", key_last4: "3456" };
    const fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/models")) return json([{ id: "gemini-example", label: "Gemini Example" }]);
      return json(init?.method === "PUT" ? saved : existing);
    });
    vi.stubGlobal("fetch", fetch);
    mount(<AiSettingsPage />);
    const provider = await screen.findByLabelText("Provider");
    expect(screen.getByRole("option", { name: "OpenAI" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "OpenRouter" })).toBeInTheDocument();
    fireEvent.change(provider, { target: { value: "gemini" } });
    expect(screen.getByRole("button", { name: "Update model" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "synthetic-provider-key-123456" } });
    await screen.findByRole("option", { name: "Gemini Example (gemini-example)" });
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "gemini-example" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and verify" }));
    expect(await screen.findByText(/Google Gemini key ending in 3456/)).toBeInTheDocument();
    const submission = fetch.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(submission?.[1]?.body))).toMatchObject({ provider: "gemini", model: "gemini-example" });
  });
  it("saves a key, clears the field and never shows the key back", async () => {
    const saved = { ...fixtureAiSettings, configured: true, key_last4: "WXYZ", validated_at: "2026-11-22T10:00:00Z" };
    const fetch = vi.fn().mockResolvedValueOnce(json(fixtureAiSettings)).mockResolvedValueOnce(json(saved));
    vi.stubGlobal("fetch", fetch);
    mount(<AiSettingsPage />);
    const input = await screen.findByLabelText("API key");
    expect(input).toHaveAttribute("type", "password");
    fireEvent.change(input, { target: { value: "sk-ant-api03-synthetic-test-key-WXYZ" } });
    fireEvent.click(screen.getByRole("button", { name: "Show key" }));
    expect(input).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: "Save and verify" }));
    expect(await screen.findByText(/stored encrypted/)).toBeInTheDocument();
    const [url, init] = fetch.mock.calls[1];
    expect(String(url)).toBe("/api/backend/settings/ai");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toMatchObject({ api_key: "sk-ant-api03-synthetic-test-key-WXYZ", model: "claude-sonnet-5-5" });
    expect(await screen.findByText(/ending in WXYZ/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("synthetic-test-key");
  });
  it("shows the server's message when the key is rejected", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(fixtureAiSettings)).mockResolvedValueOnce(json({ detail: "The key was not accepted by Anthropic. Check it and try again" }, 422)));
    mount(<AiSettingsPage />);
    fireEvent.change(await screen.findByLabelText("API key"), { target: { value: "sk-ant-api03-synthetic-test-key-0000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and verify" }));
    expect(await screen.findByText(/was not accepted by Anthropic/)).toBeInTheDocument();
  });
  it("blocks saving when the server has no key storage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ ...fixtureAiSettings, vault_ready: false })));
    mount(<AiSettingsPage />);
    expect(await screen.findByText(/APP_ENCRYPTION_KEY/)).toBeInTheDocument();
    expect(screen.getByLabelText("API key")).toBeDisabled();
  });
  it("needs a confirmation before removing a saved key", async () => {
    const saved = { ...fixtureAiSettings, configured: true, key_last4: "WXYZ" };
    const fetch = vi.fn().mockResolvedValueOnce(json(saved)).mockResolvedValueOnce(json(fixtureAiSettings));
    vi.stubGlobal("fetch", fetch);
    mount(<AiSettingsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove key" }));
    expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Yes, remove my key" }));
    expect(await screen.findByText("No key yet")).toBeInTheDocument();
    expect(fetch.mock.calls[1][1].method).toBe("DELETE");
  });
  it("points to AI Settings when the doctor has no key (HTTP 428)", () => {
    mount(<ApiErrorNotice error={new ApiError("Add your own AI key", 428)} />);
    expect(screen.getByRole("link", { name: "Open AI Settings" })).toHaveAttribute("href", "/workspace/ai");
  });
});

describe("AI key active period and usage", () => {
  const active = { ...fixtureAiSettings, configured: true, key_last4: "WXYZ", active: true, active_until: "2026-11-23T10:00:00Z" };
  const paused = { ...active, active: false };
  it("offers 1 day (default), 1 week and 1 month and sends the choice with a new key", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json(fixtureAiSettings)).mockResolvedValueOnce(json(active));
    vi.stubGlobal("fetch", fetch);
    mount(<AiSettingsPage />);
    const period = await screen.findByLabelText("Keep the key active for");
    expect(period).toHaveValue("1d");
    expect(screen.getByRole("option", { name: "1 week" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "1 month" })).toBeInTheDocument();
    fireEvent.change(period, { target: { value: "30d" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "sk-ant-api03-synthetic-test-key-WXYZ" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and verify" }));
    await screen.findByText(/stored encrypted/);
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toMatchObject({ active_for: "30d" });
  });
  it("shows a paused key and turns it back on without asking for the key again", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json(paused)).mockResolvedValueOnce(json(active));
    vi.stubGlobal("fetch", fetch);
    mount(<AiSettingsPage />);
    expect(await screen.findByText("Paused")).toBeInTheDocument();
    expect(screen.getByText(/saved but not active/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Turn on for"), { target: { value: "7d" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByText(/Active until/)).toBeInTheDocument();
    const [url, init] = fetch.mock.calls[1];
    expect(String(url)).toBe("/api/backend/settings/ai/activate");
    expect(JSON.parse(init.body)).toEqual({ active_for: "7d" });
    expect(init.body).not.toContain("sk-ant");
  });
  it("pauses an active key immediately", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(json(active)).mockResolvedValueOnce(json(paused));
    vi.stubGlobal("fetch", fetch);
    mount(<AiSettingsPage />);
    expect(await screen.findByText(/Active until/)).toBeInTheDocument();
    expect(screen.getByText("Enabled in Similia")).toBeInTheDocument();
    expect(screen.getByText(/Anthropic checks API billing and available credits/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause now" }));
    expect(await screen.findByText("Paused")).toBeInTheDocument();
    expect(String(fetch.mock.calls[1][0])).toBe("/api/backend/settings/ai/deactivate");
  });
  it("shows this hour's usage against the limits", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ ...active, usage: { window_minutes: 60, questions: { used: 4, limit: 30 }, analyses: { used: 1, limit: 10 } } })));
    mount(<AiSettingsPage />);
    expect(await screen.findByText("4 of 30")).toBeInTheDocument();
    expect(screen.getByText("1 of 10")).toBeInTheDocument();
  });
  it("saves and clears a personal hourly analysis cap", async () => {
    const settings = { ...active, hourly_analysis_limit: null };
    const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method !== "PUT") return json(settings);
      const { hourly_analysis_limit } = JSON.parse(String(init.body));
      return json({ ...settings, hourly_analysis_limit, usage: {
        ...settings.usage, analyses: { used: 10, limit: hourly_analysis_limit ?? 10 },
      } });
    });
    vi.stubGlobal("fetch", fetch);
    mount(<AiSettingsPage />);
    const limit = await screen.findByLabelText("Hourly case analysis limit");
    const save = () => screen.getByRole("button", { name: "Save hourly limit" });
    expect(save()).toBeDisabled();
    fireEvent.change(limit, { target: { value: "0" } });
    fireEvent.click(save());
    expect(await screen.findByText(/10 · No hourly cap/)).toBeInTheDocument();
    fireEvent.change(limit, { target: { value: "" } });
    fireEvent.click(save());
    expect(await screen.findByText("10 of 10")).toBeInTheDocument();
    const writes = fetch.mock.calls.filter(([, init]) => init?.method === "PUT");
    expect(writes.map(([url]) => url)).toEqual(Array(2).fill("/api/backend/settings/ai/analysis-limit"));
    expect(writes.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
      { hourly_analysis_limit: 0 }, { hourly_analysis_limit: null },
    ]);
  });
  it("saves a daily analysis cap without changing the hourly cap", async () => {
    const settings = { ...active, hourly_analysis_limit: 15, daily_analysis_limit: null, usage: {
      ...active.usage, daily_analyses: { used: 40, limit: 40 },
    } };
    const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method !== "PUT") return json(settings);
      expect(JSON.parse(String(init.body))).toEqual({ daily_analysis_limit: 70 });
      return json({ ...settings, daily_analysis_limit: 70, usage: {
        ...settings.usage, daily_analyses: { used: 40, limit: 70 },
      } });
    });
    vi.stubGlobal("fetch", fetch);
    mount(<AiSettingsPage />);
    expect(await screen.findByText("40 of 40")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Daily case analysis limit"), { target: { value: "70" } });
    fireEvent.click(screen.getByRole("button", { name: "Save daily limit" }));
    expect(await screen.findByText("40 of 70")).toBeInTheDocument();
    expect(screen.getByLabelText("Hourly case analysis limit")).toHaveValue(15);
  });
  it("points a paused-key error to AI Settings", () => {
    mount(<ApiErrorNotice error={new ApiError("Your AI key is paused. Turn it on again in AI Settings to continue", 428)} />);
    expect(screen.getByText(/key is paused/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open AI Settings" })).toHaveAttribute("href", "/workspace/ai");
  });
});


describe("Urdu option for questions", () => {
  const base = { step: "particular" as const, loading: false, canSuggest: true, onSuggest: vi.fn(), onUse: vi.fn() };
  const withUrdu = { red_flags: [], mental: [], physical_general: [], history: [], disclaimer: "", particular: [{ topic: "Discharge", question: "What colour is the discharge?", topic_ur: "رطوبت", question_ur: "رطوبت کا رنگ کیسا ہے؟" }] };
  it("shows English first and Urdu below it, right-to-left, only when switched on", () => {
    const { rerender } = mount(<SuggestedQuestions {...base} questions={withUrdu} urdu={false} onUrduChange={vi.fn()} />);
    expect(screen.getByText("What colour is the discharge?")).toBeInTheDocument();
    expect(screen.queryByText(/رطوبت کا رنگ/)).toBeNull();
    cleanup();
    mount(<SuggestedQuestions {...base} questions={withUrdu} urdu onUrduChange={vi.fn()} />);
    const urdu = screen.getByText(/رطوبت کا رنگ/);
    expect(urdu).toHaveAttribute("dir", "rtl");
    expect(urdu).toHaveAttribute("lang", "ur");
    const english = screen.getByText("What colour is the discharge?");
    expect(english.compareDocumentPosition(urdu) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    void rerender;
  });
  it("lets the doctor switch Urdu on and off", () => {
    const onUrduChange = vi.fn();
    mount(<SuggestedQuestions {...base} questions={null} urdu={false} onUrduChange={onUrduChange} />);
    fireEvent.click(screen.getByLabelText(/Also show in Urdu/));
    expect(onUrduChange).toHaveBeenCalledWith(true);
  });
});

import { MicButton, voiceErrors } from "./voice-input";
describe("voice typing", () => {
  class FakeRecognition {
    static last: FakeRecognition | null = null;
    lang = ""; continuous = false; interimResults = false;
    onresult: ((e: unknown) => void) | null = null; onerror: ((e: { error: string }) => void) | null = null; onend: (() => void) | null = null;
    started = false; stopped = false;
    constructor() { FakeRecognition.last = this; }
    start() { this.started = true; }
    stop() { this.stopped = true; this.onend?.(); }
  }
  const result = (text: string, isFinal: boolean) => ({ isFinal, 0: { transcript: text }, length: 1 });
  afterEach(() => { delete (window as unknown as Record<string, unknown>).webkitSpeechRecognition; FakeRecognition.last = null; localStorage.clear(); });
  const install = () => { (window as unknown as Record<string, unknown>).webkitSpeechRecognition = FakeRecognition; };

  it("explains when the browser has no speech recognition", async () => {
    mount(<MicButton onText={vi.fn()} />);
    expect(await screen.findByText(/needs a browser with speech recognition/)).toBeInTheDocument();
  });
  it("dictates English by default, appends only finished phrases, and shows the privacy note", async () => {
    install();
    const onText = vi.fn();
    mount(<MicButton onText={onText} />);
    expect(screen.getByText(/speech service/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /Voice typing/ }));
    const rec = FakeRecognition.last!;
    expect(rec.started).toBe(true);
    expect(rec.lang).toBe("en-US");
    expect(rec.continuous && rec.interimResults).toBe(true);
    rec.onresult?.({ resultIndex: 0, results: [result("my skin itch", false)] });
    expect(onText).not.toHaveBeenCalled();
    expect(await screen.findByText(/my skin itch/)).toBeInTheDocument();
    rec.onresult?.({ resultIndex: 0, results: [result("  my skin itches at night ", true)] });
    expect(onText).toHaveBeenCalledWith("my skin itches at night");
    fireEvent.click(screen.getByRole("button", { name: "Stop voice typing" }));
    expect(rec.stopped).toBe(true);
    expect(screen.queryByText(/Listening/)).toBeNull();
  });
  it("switches to Urdu and remembers the choice", async () => {
    install();
    mount(<MicButton onText={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText("Voice language"), { target: { value: "ur-PK" } });
    fireEvent.click(screen.getByRole("button", { name: /Voice typing/ }));
    expect(FakeRecognition.last!.lang).toBe("ur-PK");
    expect(localStorage.getItem("similia.voice-language")).toBe("ur-PK");
    cleanup();
    mount(<MicButton compact onText={vi.fn()} />);  // compact mics reuse the saved language
    fireEvent.click(await screen.findByRole("button", { name: "Voice typing" }));
    expect(FakeRecognition.last!.lang).toBe("ur-PK");
  });
  it("shows a clear message when the microphone is blocked", async () => {
    install();
    mount(<MicButton onText={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Voice typing/ }));
    FakeRecognition.last!.onerror?.({ error: "not-allowed" });
    expect(await screen.findByRole("alert")).toHaveTextContent(voiceErrors["not-allowed"]);
  });
  it("stops listening when the field is closed", async () => {
    install();
    const { unmount } = mount(<MicButton onText={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Voice typing/ }));
    unmount();
    expect(FakeRecognition.last!.stopped).toBe(true);
  });
});

describe("roomier boxes and example answers", () => {
  it("shows the AI's example answer under the answer box and Urdu example when present", () => {
    const symptoms: Symptom[] = [{ kind: "mental", label: "Temperament", notes: "Q: How would you describe your nature?\nA: ", weight: 2, hint: "I am shy, but I get angry when I am disturbed.", hint_ur: "میں شرمیلا ہوں مگر تنگ کرنے پر غصہ آتا ہے۔" }];
    mount(<SymptomEditor kind="mental" symptoms={symptoms} onChange={vi.fn()} disabled={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Open Temperament" }));
    const hint = screen.getByLabelText("Example answer");
    expect(hint).toHaveTextContent("How to write a good answer");
    expect(hint).toHaveTextContent("I am shy, but I get angry when I am disturbed.");
    expect(screen.getByText(/میں شرمیلا ہوں/)).toHaveAttribute("dir", "rtl");
  });
  it("shows no example block for entries added by hand, but gives grey example placeholders", () => {
    mount(<SymptomEditor kind="particular" symptoms={[{ kind: "particular", label: "", weight: 2 }]} onChange={vi.fn()} disabled={false} />);
    expect(screen.queryByLabelText("Example answer")).toBeNull();
    expect(screen.getByLabelText("Where (location)")).toHaveAttribute("placeholder", expect.stringContaining("behind the knees"));
    expect(screen.getByLabelText("Complaint")).toHaveAttribute("placeholder", expect.stringContaining("e.g."));
    expect(screen.getByLabelText(/Patient's own words/)).toHaveAttribute("placeholder", expect.stringContaining("Example"));
  });
  it("gives the answer box room (at least 6 lines) and lets it grow", () => {
    mount(<SymptomEditor kind="mental" symptoms={[{ kind: "mental", label: "x", weight: 2 }]} onChange={vi.fn()} disabled={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Open x" }));
    const notes = screen.getByLabelText(/Patient's own words/);
    expect(notes).toHaveAttribute("rows", "6");
    expect(notes.className).toContain("auto-textarea");
  });
  it("never stores the example hint: it is not part of what gets saved", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (String(url).includes("/questions")) return json({ red_flags: [], mental: [{ topic: "Temperament", question: "How would you describe your nature?", example_answer: "I am shy but easily angered." }], physical_general: [], particular: [], history: [], disclaimer: "" });
      if (String(url).endsWith("/symptoms")) return json({ id: "c1", patient_id: "p1", status: "draft", chief_complaint: "itch", language: "en", created_at: "", updated_at: "", symptoms: [] });
      if (String(url).includes("/analysis")) return json({ detail: "none" }, 404);
      if (String(url).includes("/patients/")) return json({ id: "p1", identifier: "P-1", full_name: "Test", preferred_language: "en" });
      return json({ id: "c1", patient_id: "p1", status: "draft", chief_complaint: "itch", language: "en", created_at: "", updated_at: "", symptoms: [] });
    }));
    mount(<CasePage id="c1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Suggest questions" }));
    fireEvent.click(await screen.findByRole("button", { name: /Mind$/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Add to case/ }));
    expect(await screen.findByLabelText("Example answer")).toHaveTextContent("I am shy but easily angered.");
    fireEvent.change(screen.getByLabelText(/Patient's own words/), { target: { value: "Q: ...\nA: I get angry quickly." } });
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/symptoms") && JSON.stringify(c.body).includes("angry"))).toBe(true), { timeout: 4000 });
    const saved = calls.filter((c) => c.url.endsWith("/symptoms")).map((c) => JSON.stringify(c.body)).join(" ");
    expect(saved).not.toContain("hint");
    expect(saved).not.toContain("shy but easily");
  });
});

describe("AI question list", () => {
  const base = { step: "particular" as const, loading: false, canSuggest: true, onUrduChange: vi.fn(), onSuggest: vi.fn(), onUse: vi.fn() };
  const make = (extra: object) => ({ red_flags: [], mental: [], physical_general: [], history: [], disclaimer: "", particular: [{ topic: "Discharge", question: "What colour is the discharge?", ...extra }] });
  it("shows only the question and its Urdu translation, never the example answer", () => {
    const questions = make({ question_ur: "رطوبت کا رنگ کیسا ہے؟", example_answer: "It is thick and yellow, like honey.", example_answer_ur: "یہ پیلا ہے۔" });
    mount(<SuggestedQuestions {...base} urdu questions={questions} />);
    expect(screen.getByText("What colour is the discharge?")).toBeInTheDocument();
    expect(screen.getByText(/رطوبت کا رنگ/)).toHaveAttribute("dir", "rtl");
    expect(screen.queryByText(/thick and yellow/)).toBeNull();
    expect(screen.queryByText(/Example answer/)).toBeNull();
    expect(screen.queryByText(/یہ پیلا ہے/)).toBeNull();
  });
  it("can be hidden and shown again so the card below stays in view", () => {
    mount(<SuggestedQuestions {...base} urdu={false} questions={make({})} />);
    expect(screen.getByText("What colour is the discharge?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Hide questions/ }));
    expect(screen.queryByText("What colour is the discharge?")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Show questions/ }));
    expect(screen.getByText("What colour is the discharge?")).toBeInTheDocument();
  });
  it("scrolls inside its own box instead of pushing the cards far down", () => {
    mount(<SuggestedQuestions {...base} urdu={false} questions={make({})} />);
    expect(document.querySelector(".question-list")).not.toBeNull();
  });
});

describe("Urdu beside the form labels", () => {
  const entry: Symptom[] = [{ kind: "particular", label: "", weight: 2 }];
  afterEach(() => localStorage.clear());
  it("shows English only by default", () => {
    mount(<SymptomEditor kind="particular" symptoms={entry} onChange={vi.fn()} disabled={false} />);
    expect(screen.getByLabelText("Where (location)")).toBeInTheDocument();
    expect(screen.getByLabelText("Importance")).toBeInTheDocument();
    expect(screen.queryByText(/کہاں/)).toBeNull();
  });
  it("adds Urdu after each English label, importance level and button when Urdu is on", () => {
    localStorage.setItem("similia.questions-urdu", "1");
    mount(<SymptomEditor kind="particular" symptoms={entry} onChange={vi.fn()} disabled={false} />);
    const where = screen.getByLabelText(/Where \(location\)/);
    expect(where).toBeInTheDocument();
    const urduLabel = screen.getByText(/کہاں \(مقام\)/);
    expect(urduLabel).toHaveAttribute("lang", "ur");
    expect(urduLabel).toHaveAttribute("dir", "rtl");
    expect(screen.getByLabelText(/Where \(location\)/).closest(".field")!.textContent!.indexOf("Where")).toBeLessThan(
      screen.getByLabelText(/Where \(location\)/).closest(".field")!.textContent!.indexOf("کہاں"));
    for (const text of [/کیسا محسوس ہوتا ہے/, /کس چیز سے بڑھتا ہے/, /کس چیز سے آرام ملتا ہے/, /ساتھ کیا ہوتا ہے/, /کب سے/, /شکایت$/, /اہمیت/, /مریض کے اپنے الفاظ/, /شکایت شامل کریں/]) {
      expect(screen.getAllByText(text).length).toBeGreaterThan(0);
    }
    expect(screen.getByRole("option", { name: /Key \/ peculiar · اہم \/ منفرد/ })).toBeInTheDocument();
  });
  it("shows the Urdu example inside each grey placeholder, English first", () => {
    localStorage.setItem("similia.questions-urdu", "1");
    mount(<SymptomEditor kind="particular" symptoms={entry} onChange={vi.fn()} disabled={false} />);
    const placeholder = screen.getByLabelText(/Where \(location\)/).getAttribute("placeholder")!;
    expect(placeholder.startsWith("e.g. behind the knees")).toBe(true);
    expect(placeholder).toContain("گھٹنوں کے پیچھے");
    expect(screen.getByLabelText(/Patient's own words/).getAttribute("placeholder")).toContain("مکمل جملوں میں لکھیں");
  });
  it("adds Urdu to the quick-add buttons and keeps the saved entry name in English", () => {
    localStorage.setItem("similia.questions-urdu", "1");
    const onChange = vi.fn();
    mount(<SymptomEditor kind="mental" symptoms={[]} onChange={onChange} disabled={false} />);
    fireEvent.click(screen.getByRole("button", { name: /Fears.*خوف/ }));
    expect(onChange).toHaveBeenCalledWith([{ kind: "mental", label: "Fears", weight: 2, key: expect.any(String) }]);
  });
});

import { AutoTextarea } from "@/components/auto-textarea";
describe("self-sizing text boxes", () => {
  const wrap = (el: HTMLElement) => el.closest(".grow-wrap")!;
  it("keeps an invisible copy of the text so the box always fits it", () => {
    const { rerender } = mount(<AutoTextarea aria-label="box" value="line one" onChange={vi.fn()} />);
    expect(wrap(screen.getByLabelText("box")).getAttribute("data-replicated-value")).toBe("line one\n");
    rerender(<QueryClientProvider client={new QueryClient()}><AutoTextarea aria-label="box" value={"line one\nline two\nline three"} onChange={vi.fn()} /></QueryClientProvider>);
    expect(wrap(screen.getByLabelText("box")).getAttribute("data-replicated-value")).toBe("line one\nline two\nline three\n");
  });
  it("sizes an empty box for its grey example text, including the Urdu line", () => {
    mount(<AutoTextarea aria-label="box" value="" placeholder={"e.g. behind the knees\nمثلاً گھٹنوں کے پیچھے"} onChange={vi.fn()} />);
    expect(wrap(screen.getByLabelText("box")).getAttribute("data-replicated-value")).toContain("مثلاً گھٹنوں کے پیچھے");
  });
  it("starts at the requested minimum number of lines", () => {
    mount(<AutoTextarea aria-label="box" value="" minRows={6} onChange={vi.fn()} />);
    expect(screen.getByLabelText("box")).toHaveAttribute("rows", "6");
  });
});

describe("Urdu step names and buttons", () => {
  beforeEach(() => stubCaseApi());
  afterEach(() => localStorage.clear());
  it("is English only by default", async () => {
    mount(<CasePage id="c1" />);
    expect(await screen.findByRole("button", { name: /Mind$/ })).toBeInTheDocument();
    expect(screen.queryByText("پیچھے")).toBeNull();
    expect(screen.queryByText("آگے")).toBeNull();
  });
  it("adds Urdu after every step name, the step description and the Back / Next buttons", async () => {
    localStorage.setItem("similia.questions-urdu", "1");
    mount(<CasePage id="c1" />);
    for (const name of [/Chief complaint · بنیادی شکایت/, /Mind · ذہن/, /Whole body · پورا جسم/, /Complaints · شکایات/, /History · تاریخ/, /Analyse · تجزیہ/]) {
      expect(await screen.findByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByText(/مریض کو بغیر ٹوکے/)).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("button", { name: /Back · پیچھے/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Next · آگے/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Next · آگے/ }));
    expect(await screen.findByText(/ذہن اور جذبات|مزاج، خوف/)).toBeInTheDocument();
  });
  it("keeps English first in every label", async () => {
    localStorage.setItem("similia.questions-urdu", "1");
    mount(<CasePage id="c1" />);
    const button = await screen.findByRole("button", { name: /Mind · ذہن/ });
    const text = button.textContent!;
    expect(text.indexOf("Mind")).toBeLessThan(text.indexOf("ذہن"));
  });
});

describe("autosave failure", () => {
  it("tells the doctor the reason and offers Save now when saving fails", async () => {
    let fail = true;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith("/symptoms")) return fail ? json({ detail: "One of the boxes is too long or invalid. Shorten the longest answer and try again" }, 422) : json({ id: "c1", patient_id: "p1", status: "draft", chief_complaint: "itch", language: "en", created_at: "", updated_at: "", symptoms: [] });
      if (u.includes("/analysis")) return json({ detail: "none" }, 404);
      if (u.includes("/patients/")) return json({ id: "p1", identifier: "P-1", full_name: "Test", preferred_language: "en" });
      void init;
      return json({ id: "c1", patient_id: "p1", status: "draft", chief_complaint: "itch", language: "en", created_at: "", updated_at: "", symptoms: [] });
    }));
    mount(<CasePage id="c1" />);
    const box = await screen.findByLabelText(/What brings the patient in/);
    fireEvent.change(box, { target: { value: "itchy skin for two years" } });
    expect(await screen.findByText(/Shorten the longest answer/, undefined, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText(/Not saved/)).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Save now" }));
    expect(await screen.findByText("All changes saved")).toBeInTheDocument();
    expect(screen.queryByText(/Shorten the longest answer/)).toBeNull();
  });
});

import { useState } from "react";
describe("folding cards, newest first", () => {
  const saved: Symptom = { id: "s1", kind: "particular", label: "Skin eruption", notes: "Q: Where is it?\nA: Behind the knees and elbows", weight: 3 };
  function Harness({ initial = [saved] }: { initial?: Symptom[] }) {
    const [symptoms, setSymptoms] = useState<Symptom[]>(initial);
    const addQuestionCard = () => setSymptoms([...symptoms, { key: `q${symptoms.length}`, kind: "particular", label: `Topic ${symptoms.length}`, notes: "Q: What colour is it?\nA: ", hint: "It is thick and yellow.", weight: 2 }]);
    return <><button onClick={addQuestionCard}>simulate-add-question</button><SymptomEditor kind="particular" symptoms={symptoms} onChange={setSymptoms} disabled={false} /></>;
  }
  afterEach(() => localStorage.clear());

  it("shows a saved card folded into one line with its answer", () => {
    mount(<Harness />);
    const row = screen.getByRole("button", { name: "Open Skin eruption" });
    expect(row).toHaveTextContent("Behind the knees and elbows");
    expect(row).toHaveTextContent("Key / peculiar");
    expect(screen.queryByLabelText(/Patient's own words/)).toBeNull();
  });
  it("opens a card from its summary and folds it again with Done", () => {
    mount(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Open Skin eruption" }));
    expect(screen.getByLabelText(/Patient's own words/)).toHaveValue("Q: Where is it?\nA: Behind the knees and elbows");
    fireEvent.click(screen.getByRole("button", { name: /Done/ }));
    expect(screen.queryByLabelText(/Patient's own words/)).toBeNull();
    expect(screen.getByRole("button", { name: "Open Skin eruption" })).toBeInTheDocument();
  });
  it("puts a newly added question card on top, open, showing only its question and answer", () => {
    mount(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "simulate-add-question" }));
    const open = document.querySelector(".symptom-card") as HTMLElement;
    const folded = document.querySelector(".symptom-collapsed") as HTMLElement;
    expect(open).not.toBeNull();
    expect(folded).not.toBeNull();
    // newest first: the open card comes before the folded older one
    expect(open.compareDocumentPosition(folded) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText(/Patient's own words/)).toHaveValue("Q: What colour is it?\nA: ");
    expect(screen.getByLabelText("Example answer")).toHaveTextContent("It is thick and yellow.");
    // everything else is hidden until asked for
    expect(screen.queryByLabelText(/Where \(location\)/)).toBeNull();
    expect(screen.getByRole("button", { name: /More details/ })).toBeInTheDocument();
  });
  it("folds the card you finished when the next one is added", () => {
    mount(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "simulate-add-question" }));
    fireEvent.click(screen.getByRole("button", { name: "simulate-add-question" }));
    expect(document.querySelectorAll(".symptom-card")).toHaveLength(1);
    expect(document.querySelectorAll(".symptom-collapsed")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Open Topic 1" })).toBeInTheDocument();
    // the newest of all is the one that is open
    expect((document.querySelector(".symptom-card input") as HTMLInputElement).value).toBe("Topic 2");
  });
  it("keeps the extra details hidden until 'More details' is clicked, then hides them again", () => {
    mount(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "simulate-add-question" }));
    fireEvent.click(screen.getByRole("button", { name: /More details/ }));
    expect(screen.getByLabelText(/Where \(location\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Hide details/ }));
    expect(screen.queryByLabelText(/Where \(location\)/)).toBeNull();
  });
  it("shows the details at once for a card added by hand, and puts it on top", () => {
    mount(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /Add complaint/ }));
    expect(screen.getByLabelText(/Where \(location\)/)).toBeInTheDocument();
    const open = document.querySelector(".symptom-card") as HTMLElement;
    const folded = document.querySelector(".symptom-collapsed") as HTMLElement;
    expect(open.compareDocumentPosition(folded) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it("puts the add button above the cards so a new card appears right below it", () => {
    mount(<Harness />);
    const add = screen.getByRole("button", { name: /Add complaint/ });
    const folded = document.querySelector(".symptom-collapsed") as HTMLElement;
    expect(add.compareDocumentPosition(folded) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
  it("shows 'No answer yet' on a folded card that has no answer", () => {
    mount(<Harness initial={[{ id: "s2", kind: "particular", label: "Itching", weight: 2, notes: "Q: When?\nA: " }]} />);
    expect(screen.getByRole("button", { name: "Open Itching" })).toHaveTextContent("No answer yet");
  });
});

describe("signed-off (locked) case", () => {
  afterEach(() => localStorage.clear());
  it("explains the lock, makes the record read-only and hides the analysis button", async () => {
    stubCaseApi({ status: "signed_off" });
    mount(<CasePage id="c1" />);
    expect(await screen.findByText(/signed off and locked/)).toBeInTheDocument();
    expect(screen.getByLabelText(/What brings the patient in/)).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Analyse$/ }));
    expect(screen.queryByRole("button", { name: /Run analysis/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Reopen case" })).toBeInTheDocument();
  });
  it("sends no save requests for a locked case", async () => {
    stubCaseApi({ status: "signed_off" });
    mount(<CasePage id="c1" />);
    await screen.findByText(/signed off and locked/);
    const saves = (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls.filter(([, init]) => init?.method === "PUT" || init?.method === "PATCH");
    expect(saves).toHaveLength(0);
  });
  it("reopens the case, which unlocks the record as a draft", async () => {
    let status = "signed_off";
    const record = () => ({ id: "c1", patient_id: "p1", status, chief_complaint: "itchy skin", language: "en", created_at: "", updated_at: "", symptoms: [] });
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      void init;
      const u = String(url);
      if (u.endsWith("/reopen")) { status = "draft"; return json(record()); }
      if (u.includes("/analysis")) return json({ detail: "none" }, 404);
      if (u.includes("/patients/")) return json({ id: "p1", identifier: "P-1", full_name: "Test Patient", preferred_language: "en" });
      return json(record());
    });
    vi.stubGlobal("fetch", fetchMock);
    mount(<CasePage id="c1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Reopen case" }));
    await waitFor(() => expect(screen.getByLabelText(/What brings the patient in/)).not.toBeDisabled());
    expect(screen.queryByText(/signed off and locked/)).toBeNull();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/cases/c1/reopen") && init?.method === "POST")).toBe(true);
  });
});

describe("an analysis that no longer matches the case", () => {
  const props = { caseId: "c1", onAcknowledge: vi.fn(), acknowledging: false };
  it("is flagged out of date and cannot be signed off until it is run again", () => {
    mount(<AnalysisView analysis={fixtureAnalysis} {...props} status="draft" />);
    expect(screen.getByText(/out of date/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save & Finalise Prescription|Sign off case/i })).toBeNull();
  });
  it("offers sign-off when the analysis is current", () => {
    mount(<AnalysisView analysis={fixtureAnalysis} {...props} status="analyzed" />);
    expect(screen.getByRole("button", { name: /Save & Finalise Prescription|Sign off case/i })).toBeInTheDocument();
    expect(screen.queryByText(/out of date/)).toBeNull();
  });
});

describe("practitioner-owned prescription workflow", () => {
  const props = { caseId: "c1", onAcknowledge: vi.fn(), acknowledging: false };
  const patient = fixturePatient;

  it("starts every prescription field empty: nothing clinical is filled in for the practitioner", () => {
    mount(<AnalysisView analysis={fixtureAnalysis} {...props} status="analyzed" patient={patient} />);
    expect(screen.getByText("Prescription & Clinical Decision")).toBeInTheDocument();
    for (const label of [/Diagnosis \/ Clinical Impression/i, /Remedy Chosen/i, /Potency/i, /^Dose$/i, /Frequency/i, /Duration/i, /Patient Instructions & Advice/i, /Prescriber's name/i]) {
      expect(screen.getByLabelText(label)).toHaveValue("");
    }
    expect(screen.queryByRole("button", { name: /Use AI Suggestion|^Insert$/i })).toBeNull();
    expect(screen.getByRole("button", { name: "Save & Finalise Prescription" })).toBeDisabled();
  });

  it("needs the remedy and the prescriber's name before it can be finalised", () => {
    mount(<AnalysisView analysis={fixtureAnalysis} {...props} status="analyzed" patient={patient} />);
    const save = screen.getByRole("button", { name: "Save & Finalise Prescription" });
    fireEvent.change(screen.getByLabelText(/Remedy Chosen/i), { target: { value: "Sulphur" } });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Prescriber's name/i), { target: { value: "Dr A. Example" } });
    expect(save).not.toBeDisabled();
  });

  it("submits the finalized prescription directly to the review endpoint without external approval", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith("/cases/c1/review") && init?.method === "POST") {
        const body = JSON.parse(init.body as string);
        return json({
          id: "rev-1",
          practitioner_id: "doc-1",
          analysis_id: "a1",
          case_id: "c1",
          decision: body.decision,
          chosen_remedy: body.chosen_remedy,
          diagnosis: body.diagnosis,
          potency: body.potency,
          dose: body.dose,
          frequency: body.frequency,
          duration: body.duration,
          instructions: body.instructions,
          urgency_disposition: body.urgency_disposition,
          notes: body.notes,
          signed_at: "2026-11-24T10:00:00Z",
        });
      }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    mount(<AnalysisView analysis={fixtureAnalysis} {...props} status="analyzed" patient={patient} />);

    fireEvent.change(screen.getByLabelText(/Remedy Chosen/i), { target: { value: "Demonstration remedy A" } });
    fireEvent.change(screen.getByLabelText(/Prescriber's name/i), { target: { value: "Dr A. Example" } });
    fireEvent.change(screen.getByLabelText(/Diagnosis \/ Clinical Impression/i), {
      target: { value: "Migraine without aura (Verified)" },
    });
    fireEvent.change(screen.getByLabelText(/Potency/i), {
      target: { value: "200C" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save & Finalise Prescription" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) => {
          if (!String(url).endsWith("/cases/c1/review") || init?.method !== "POST") return false;
          const body = JSON.parse(init.body as string);
          return (
            body.decision === "accepted" &&
            body.chosen_remedy === "Demonstration remedy A" &&
            body.diagnosis === "Migraine without aura (Verified)" &&
            body.potency === "200C" &&
            body.dose === null && body.frequency === null && body.duration === null && body.instructions === null &&
            body.practitioner_name === "Dr A. Example"
          );
        })
      ).toBe(true);
    });
  });

  it("requires urgency disposition when red flags are present", () => {
    const analysisWithFlags: Analysis = {
      ...fixtureAnalysis,
      outcome: "ranked",
      red_flags: ["Sudden severe headache with neurological signs"],
    };
    mount(
      <AnalysisView
        analysis={analysisWithFlags}
        {...props}
        status="analyzed"
        patient={patient}
      />
    );

    fireEvent.change(screen.getByLabelText(/Remedy Chosen/i), { target: { value: "Sulphur" } });
    fireEvent.change(screen.getByLabelText(/Prescriber's name/i), { target: { value: "Dr A. Example" } });
    expect(screen.getByLabelText(/Urgent Findings Assessment & Disposition \*/i)).toBeInTheDocument();
    // Save button should be disabled when urgency disposition is empty
    expect(screen.getByRole("button", { name: "Save & Finalise Prescription" })).toBeDisabled();

    // Fill in urgency disposition
    fireEvent.change(screen.getByLabelText(/Urgent Findings Assessment & Disposition \*/i), {
      target: { value: "Emergency referral arranged via local hospital ED." },
    });
    expect(screen.getByRole("button", { name: "Save & Finalise Prescription" })).not.toBeDisabled();
  });

  it("offers no ready-made text for the urgent assessment or the notes", () => {
    const analysisWithFlags: Analysis = { ...fixtureAnalysis, outcome: "ranked", red_flags: ["Sudden severe headache with neurological signs"] };
    mount(<AnalysisView analysis={analysisWithFlags} {...props} status="analyzed" patient={patient} />);
    expect(screen.queryByRole("button", { name: /Use AI Suggestion|^Insert$/i })).toBeNull();
    expect(screen.queryByText(/AI Suggested draft/i)).toBeNull();
    expect(screen.getByLabelText(/Urgent Findings Assessment & Disposition \*/i)).toHaveValue("");
    expect(screen.getByLabelText(/Internal Doctor's Notes/i)).toHaveValue("");
  });

  it("says Not recorded on the signed card instead of showing a default", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => String(url).endsWith("/cases/c1/review")
      ? json({ id: "rev-2", analysis_id: "a1", case_id: "c1", decision: "accepted", chosen_remedy: "Sulphur", signed_at: "2026-11-24T10:00:00Z" })
      : json({})));
    mount(<AnalysisView analysis={fixtureAnalysis} {...props} status="signed_off" patient={patient} />);
    expect(await screen.findByText("Sulphur")).toBeInTheDocument();
    expect(screen.getAllByText("Not recorded")).toHaveLength(5);
    expect(screen.queryByText(/30C|4 pills|Twice daily|7 days/)).toBeNull();
  });

  it("displays the finalised prescription card and separate report link when signed off", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const u = String(url);
      if (u.endsWith("/cases/c1/review")) {
        return json({
          id: "rev-1",
          practitioner_id: "doc-1",
          analysis_id: "a1",
          case_id: "c1",
          decision: "accepted",
          chosen_remedy: "Belladonna",
          diagnosis: "Acute fever with congestion",
          potency: "30C",
          dose: "4 pills",
          frequency: "Twice daily",
          duration: "5 days",
          instructions: "Avoid strong odors.",
          signed_at: "2026-11-24T10:00:00Z",
        });
      }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    mount(
      <AnalysisView
        analysis={fixtureAnalysis}
        {...props}
        status="signed_off"
        patient={patient}
      />
    );

    expect(await screen.findByText("Finalised Prescription")).toBeInTheDocument();
    expect(await screen.findByText("Belladonna")).toBeInTheDocument();
    expect(screen.getByText("Acute fever with congestion")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download Prescription PDF/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Detailed RAG Analysis Report/i })).toHaveAttribute(
      "href",
      "/workspace/report/c1"
    );
  });
});
