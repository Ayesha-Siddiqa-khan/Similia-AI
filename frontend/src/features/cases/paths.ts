import type { CaseStatus } from "./types";

export const patientPath = (id: string) => `/workspace/patients/${id}`;
export const casePath = (id: string) => `/workspace/case/${id}`;
export const reportPath = (id: string) => `/workspace/report/${id}`;

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
export const outcomeLabel: Record<"ranked" | "insufficient_sources" | "red_flag", string> = { ranked: "Remedies suggested", insufficient_sources: "Not enough sources", red_flag: "Urgent concern flagged" };

export const statusLabel: Record<CaseStatus, string> = { draft: "Draft", analyzed: "Analysed · awaiting review", signed_off: "Signed off" };
export const statusTone: Record<CaseStatus, "neutral" | "warn" | "good"> = { draft: "neutral", analyzed: "warn", signed_off: "good" };
