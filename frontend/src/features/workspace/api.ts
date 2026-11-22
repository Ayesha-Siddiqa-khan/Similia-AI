import { useQuery } from "@tanstack/react-query";
import type { Snapshot } from "./types";

import { api, ApiError } from "@/lib/backend";
export { api, ApiError };
export function useSnapshot() {
  return useQuery({
    queryKey: ["snapshot"],
    queryFn: ({ signal }) => api<Snapshot>("monitor/snapshot", { signal }),
    retry: (n, error) => n < 2 && (!(error instanceof ApiError) || ![401, 403, 429].includes(error.status)),
    refetchInterval: (q) => q.state.error ? Math.min(120_000, 15_000 * 2 ** Math.min(q.state.fetchFailureCount + 1, 3)) : 15_000,
    refetchIntervalInBackground: false,
  });
}
export const categoryLabel: Record<string, string> = { materia_medica: "Materia Medica", repertory: "Repertory", organon: "Organon", general: "General knowledge", philosophy: "Homeopathic Philosophy", unknown: "Unknown" };
export const MAX_PDF_BYTES = 50 * 1024 * 1024;
export function validatePdf(file: File | undefined): string | null {
  if (!file) return "Choose a PDF file.";
  if (!file.name.toLowerCase().endsWith(".pdf") || (file.type !== "application/pdf" && file.type !== "")) return "Only PDF files are supported.";
  if (!file.size) return "The selected file is empty.";
  if (file.size > MAX_PDF_BYTES) return "The PDF must be 50 MB or smaller.";
  return null;
}
