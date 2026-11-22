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
  retrieval_mode?: "semantic" | "keyword";
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
  retrieval_mode?: "semantic" | "keyword";
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
  key_last4: string | null;
  model: string;
  validated_at: string | null;
  models: AiModelOption[];
  active: boolean;
  active_until: string | null;
  active_options: AiModelOption[];
  usage: { window_minutes: number; questions: { used: number; limit: number }; analyses: { used: number; limit: number } } | null;
}
