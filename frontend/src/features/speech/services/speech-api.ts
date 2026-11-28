/**
 * API client services for communicating with local speech backend endpoints.
 */

import {
  ModelValidationResult,
  SpeechSettings,
  SpeechStatusResponse,
  TranscriptionResult,
} from "../types";

const BACKEND_BASE = "/api/backend";

async function handleResponse<T>(res: Response, fallbackMessage: string): Promise<T> {
  if (!res.ok) {
    const errorJson = await res.json().catch(() => ({}));
    const message = errorJson.detail || fallbackMessage;
    throw new Error(typeof message === "string" ? message : fallbackMessage);
  }
  return res.json() as Promise<T>;
}

export async function fetchSpeechStatus(signal?: AbortSignal): Promise<SpeechStatusResponse> {
  const res = await fetch(`${BACKEND_BASE}/speech/settings`, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });
  return handleResponse<SpeechStatusResponse>(res, "Failed to load speech settings.");
}

export async function updateSpeechSettings(
  settings: Partial<SpeechSettings>
): Promise<SpeechStatusResponse> {
  const res = await fetch(`${BACKEND_BASE}/speech/settings`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(settings),
  });
  await handleResponse<SpeechStatusResponse>(res, "Failed to update speech settings.");
  const confirmed = await fetchSpeechStatus();
  if (Object.entries(settings).some(([key, value]) => confirmed.settings[key as keyof SpeechSettings] !== value)) {
    throw new Error("The backend did not confirm the saved speech settings. Refresh status and try again.");
  }
  return confirmed;
}

export async function validateModelPath(
  modelPath: string
): Promise<ModelValidationResult> {
  const res = await fetch(`${BACKEND_BASE}/speech/validate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ model_path: modelPath }),
  });
  return handleResponse<ModelValidationResult>(res, "Failed to validate model path.");
}

export async function loadSpeechModel(): Promise<SpeechStatusResponse> {
  const res = await fetch(`${BACKEND_BASE}/speech/load`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  return handleResponse<SpeechStatusResponse>(res, "Failed to load speech model.");
}

export async function unloadSpeechModel(): Promise<SpeechStatusResponse> {
  const res = await fetch(`${BACKEND_BASE}/speech/unload`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  return handleResponse<SpeechStatusResponse>(res, "Failed to unload speech model.");
}

export async function transcribeAudio(
  audioBlob: Blob,
  options?: { language?: string; initialPrompt?: string }
): Promise<TranscriptionResult> {
  const formData = new FormData();
  const filename = audioBlob.type.includes("wav") ? "dictation.wav" : "dictation.webm";
  formData.append("audio", audioBlob, filename);
  if (options?.language && options.language !== "auto") {
    formData.append("language", options.language);
  }
  if (options?.initialPrompt) {
    formData.append("initial_prompt", options.initialPrompt);
  }

  const res = await fetch(`${BACKEND_BASE}/speech/transcribe`, {
    method: "POST",
    body: formData,
  });
  return handleResponse<TranscriptionResult>(res, "Transcription failed.");
}
