import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/backend";
import type { AiSettings, Analysis, CaseHistoryItem, CaseRecord, ConsentRecord, Patient } from "./types";

const json = (body: unknown): RequestInit => ({ headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: "POST", ...(body === undefined ? {} : json(body)) });
export const patch = <T,>(path: string, body: unknown) => api<T>(path, { method: "PATCH", ...json(body) });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: "PUT", ...json(body) });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });

const noRetryOnAuth = (n: number, error: Error) => n < 1 && (!(error instanceof ApiError) || ![401, 403, 404].includes(error.status));

export function usePatients() {
  return useQuery({ queryKey: ["patients"], queryFn: ({ signal }) => api<Patient[]>("patients", { signal }), retry: noRetryOnAuth });
}
export function usePatient(id: string) {
  return useQuery({ queryKey: ["patient", id], queryFn: ({ signal }) => api<Patient>(`patients/${id}`, { signal }), retry: noRetryOnAuth, enabled: id !== "" });
}
export function usePatientConsents(id: string) {
  return useQuery({ queryKey: ["consents", id], queryFn: ({ signal }) => api<ConsentRecord[]>(`patients/${id}/consents`, { signal }), retry: noRetryOnAuth, enabled: id !== "" });
}
export function usePatientHistory(id: string) {
  return useQuery({ queryKey: ["history", id], queryFn: ({ signal }) => api<CaseHistoryItem[]>(`patients/${id}/history`, { signal }), retry: noRetryOnAuth, enabled: id !== "" });
}
/** Every saved analysis of a case, newest first. Only fetched once `enabled` (the section is opened). */
export function useAnalysisHistory(caseId: string, enabled = true) {
  return useQuery({ queryKey: ["analyses", caseId], queryFn: ({ signal }) => api<Analysis[]>(`cases/${caseId}/analyses`, { signal }), retry: noRetryOnAuth, enabled: enabled && caseId !== "" });
}
export function useCases(patientId?: string) {
  return useQuery({
    queryKey: ["cases", patientId ?? "all"],
    queryFn: ({ signal }) => api<CaseRecord[]>(`cases${patientId ? `?patient_id=${patientId}` : ""}`, { signal }),
    retry: noRetryOnAuth,
  });
}
export function useCase(id: string) {
  return useQuery({ queryKey: ["case", id], queryFn: ({ signal }) => api<CaseRecord>(`cases/${id}`, { signal }), retry: noRetryOnAuth, refetchOnWindowFocus: false });
}
/** The latest saved analysis, or null when none exists yet (the API answers 404). */
export function useLatestAnalysis(id: string) {
  return useQuery({
    queryKey: ["analysis", id],
    queryFn: async ({ signal }) => {
      try { return await api<Analysis>(`cases/${id}/analysis`, { signal }); }
      catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error; }
    },
    retry: noRetryOnAuth,
  });
}
export function useAiSettings() {
  return useQuery({ queryKey: ["ai-settings"], queryFn: ({ signal }) => api<AiSettings>("settings/ai", { signal }), retry: noRetryOnAuth });
}
