export type Language = "en" | "hi" | "ur";
export type Sex = "female" | "male" | "other" | "unspecified";
export type SymptomKind = "mental" | "physical_general" | "particular" | "history" | "family" | "medication";
export type CaseStatus = "draft" | "analyzed" | "signed_off";

export interface Patient {
  id: string;
  identifier: string;
  full_name: string;
  date_of_birth: string | null;
  age_years: number | null;
  sex: Sex;
  preferred_language: Language;
  contact: string | null;
  notes: string | null;
  guardian_name: string | null;
  guardian_relationship: string | null;
  is_minor: boolean;
  is_infant: boolean;
  consent_active: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConsentRecord {
  id: string;
  purpose: string;
  text_version: string;
  granted_at: string;
  withdrawn_at: string | null;
}

export interface CaseHistoryItem {
  id: string;
  status: CaseStatus;
  chief_complaint: string;
  language: Language;
  created_at: string;
  updated_at: string;
  analysis_count: number;
  latest_outcome: "ranked" | "insufficient_sources" | "red_flag" | null;
  review_decision: "accepted" | "modified" | "rejected" | null;
  chosen_remedy: string | null;
  signed_at: string | null;
}

export interface Symptom {
  id?: string;
  // Browser-only id for a card that has not been saved yet (never sent to the server).
  key?: string;
  kind: SymptomKind;
  label: string;
  location?: string | null;
  sensation?: string | null;
  better?: string | null;
  worse?: string | null;
  concomitants?: string | null;
  duration?: string | null;
  notes?: string | null;
  weight: number;
  // Writing aids kept in the browser only (never saved): an example of a good answer.
  hint?: string;
  hint_ur?: string;
}

export interface CaseRecord {
  id: string;
  patient_id: string;
  status: CaseStatus;
  chief_complaint: string;
  language: Language;
  created_at: string;
  updated_at: string;
  symptoms: Symptom[];
}

export interface Remedy {
  remedy: string;
  confidence: "low" | "medium" | "high";
  rationale: string;
  matching_symptoms: string[];
  contradicting_symptoms: string[];
  citations: string[];
}

export interface AnalysisPassage {
  chunk_id: string;
  book_title: string;
  book_category: string;
  book_author?: string | null;
  section_heading: string | null;
  section_path?: string[];
  page_start?: number | null;
  page_end?: number | null;
  book_complete?: boolean;
  retrieval_mode?: "semantic" | "keyword" | "hybrid";
  matched_by?: string[];
  content: string;
  similarity: number;
}

export interface Analysis {
  id: string;
  case_id: string;
  outcome: "ranked" | "insufficient_sources" | "red_flag";
  red_flags: string[];
  /** Extra care notes, for example for a child. */
  cautions: string[];
  remedies: Remedy[];
  passages: AnalysisPassage[];
  missing_information: string[];
  incomplete_books?: string[];
  requested_mode?: "semantic" | "keyword" | "hybrid" | "unknown" | "not_run";
  fallback_reason?: string | null;
  retrieval_mode?: "semantic" | "keyword" | "hybrid" | "mixed" | "not_run" | "unknown";
  model: string | null;
  created_at: string;
  disclaimer: string;
}

export interface FollowUpQuestion { topic: string; question: string; topic_ur?: string; question_ur?: string; example_answer?: string; example_answer_ur?: string }
export interface FollowUps {
  red_flags: string[];
  mental: FollowUpQuestion[];
  physical_general: FollowUpQuestion[];
  particular: FollowUpQuestion[];
  history: FollowUpQuestion[];
  disclaimer: string;
}

export interface AiModelOption { id: string; label: string }
export interface AiSettings {
  configured: boolean;
  vault_ready: boolean;
  provider: string;
  providers: (AiModelOption & { model_example?: string | null })[];
  key_last4: string | null;
  model: string;
  validated_at: string | null;
  models: AiModelOption[];
  active: boolean;
  active_until: string | null;
  hourly_analysis_limit?: number | null;
  daily_analysis_limit?: number | null;
  active_options: AiModelOption[];
  usage: { window_minutes: number; questions: { used: number; limit: number }; analyses: { used: number; limit: number }; daily_analyses?: { used: number; limit: number } } | null;
}

/** Machine translation of the AI-written wording of one analysis (same item count and order as the English). */
export interface UrduReport {
  analysis_id: string;
  chief_complaint: string;
  red_flags: string[];
  cautions: string[];
  remedies: { remedy: string; rationale: string; matching_symptoms: string[]; contradicting_symptoms: string[] }[];
  missing_information: string[];
  notice: string;
}

export interface Review {
  id: string;
  case_id: string;
  analysis_id: string;
  decision: "accepted" | "modified" | "rejected";
  chosen_remedy: string | null;
  diagnosis?: string | null;
  potency?: string | null;
  dose?: string | null;
  frequency?: string | null;
  duration?: string | null;
  instructions?: string | null;
  urgency_disposition?: string | null;
  include_urgent_in_pdf?: boolean;
  practitioner_name?: string | null;
  notes?: string | null;
  signed_at: string;
}
