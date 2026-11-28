import type { AiSettings, Analysis, CaseRecord, Patient } from "@/features/cases/types";

// TEST-ONLY sample data. Never imported by the application; it exists so automated tests have records to render.
export const fixturePatient: Patient = {
  id: "demo-patient", identifier: "DEMO-001", full_name: "Demonstration Patient", date_of_birth: null, age_years: 35,
  sex: "unspecified", preferred_language: "en", contact: null, notes: "Synthetic preview record", archived_at: null,
  guardian_name: null, guardian_relationship: null, is_minor: false, is_infant: false, consent_active: true,
  created_at: "2026-10-30T12:00:00Z", updated_at: "2026-10-30T12:00:00Z",
};

export const fixtureCase: CaseRecord = {
  id: "demo-case", patient_id: fixturePatient.id, status: "analyzed", chief_complaint: "Synthetic example: intermittent headache",
  language: "en", created_at: "2026-10-30T12:00:00Z", updated_at: "2026-10-30T12:00:00Z",
  symptoms: [
    { id: "s1", kind: "mental", label: "Irritable when disturbed", worse: "consolation", weight: 3 },
    { id: "s2", kind: "particular", label: "Headache", location: "forehead", sensation: "throbbing", worse: "bright light", better: "rest in the dark", duration: "two weeks", weight: 2 },
  ],
};

export const fixtureAnalysis: Analysis = {
  id: "demo-analysis", case_id: fixtureCase.id, outcome: "ranked", red_flags: [], cautions: [], model: "synthetic-preview", created_at: "2026-10-30T12:05:00Z",
  disclaimer: "Retrieved historical text is decision support for a qualified practitioner. It is not clinical evidence, a diagnosis, or a prescription.",
  remedies: [{ remedy: "Demonstration remedy A", confidence: "medium", rationale: "Synthetic illustration of how a cited rationale appears.", matching_symptoms: ["Headache worse in bright light"], contradicting_symptoms: ["Better from consolation is not reported"], citations: ["demo-chunk-1"] }],
  passages: [{ chunk_id: "demo-chunk-1", book_title: "Synthetic demonstration source", book_category: "materia_medica", section_heading: "Demonstration section", content: "Synthetic passage text used only to show citation layout.", similarity: 0.8 }],
  missing_information: ["Synthetic example: is the pain one-sided?"],
};

export const fixtureAiSettings: AiSettings = {
  configured: false, vault_ready: true, provider: "anthropic", key_last4: null, model: "claude-sonnet-5-5", validated_at: null,
  providers: [{ id: "anthropic", label: "Anthropic" }, { id: "openai", label: "OpenAI", model_example: "gpt-4.1-mini" }, { id: "gemini", label: "Google Gemini" }, { id: "openrouter", label: "OpenRouter" }],
  models: [{ id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5 (recommended)" }, { id: "claude-opus-5-5", label: "Claude Opus 5.5" }, { id: "claude-haiku-5-5", label: "Claude Haiku 5.5" }],
  active: false, active_until: null,
  active_options: [{ id: "1d", label: "1 day (default)" }, { id: "7d", label: "1 week" }, { id: "30d", label: "1 month" }],
  usage: { window_minutes: 60, questions: { used: 0, limit: 30 }, analyses: { used: 0, limit: 10 } },
};
