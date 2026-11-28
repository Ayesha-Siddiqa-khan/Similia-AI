/**
 * Types for local speech recognition and settings.
 */

export interface ModelValidationResult {
  valid: boolean;
  error?: string | null;
  engine: string;
  model_type?: string | null;
  architecture?: string | null;
  model_path: string;
  size_bytes: number;
  size_mb: number;
  files_found: string[];
  missing_files: string[];
}

export interface TranscriptionSegment {
  id: number;
  start: number;
  end: number;
  text: string;
}

export interface TranscriptionResult {
  text: string;
  language?: string | null;
  language_probability?: number | null;
  duration_seconds: number;
  segments: TranscriptionSegment[];
}

export interface EngineStatus {
  status: "unloaded" | "loading" | "ready" | "transcribing" | "error";
  engine: string;
  model_path?: string | null;
  device: string;
  compute_type: string;
  idle_seconds_remaining?: number | null;
  idle_timeout_seconds: number;
  memory_rss_mb?: number | null;
  last_active_timestamp?: number | null;
  error_message?: string | null;
  python_executable?: string | null;
  supported_devices: string[];
  supported_languages: Array<{ code: string; label: string }>;
}

export interface SpeechSettings {
  enabled: boolean;
  engine: string;
  model_path: string;
  device: string;
  compute_type: string;
  idle_timeout_seconds: number;
  default_language: string;
  python_executable: string;
}

export interface SpeechStatusResponse {
  settings: SpeechSettings;
  status: EngineStatus;
}
