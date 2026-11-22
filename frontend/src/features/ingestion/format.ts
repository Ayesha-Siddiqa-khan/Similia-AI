import type { BookIndexStats, JobOut, PlanOut } from "./types";

export type IndexState = "complete" | "partial" | "unprepared";
export const indexState = (b: BookIndexStats): IndexState => (b.complete ? "complete" : b.prepared ? "partial" : "unprepared");
export const stateLabel: Record<IndexState, string> = { complete: "Complete", partial: "Partial", unprepared: "Not prepared" };
export const stateTone = { complete: "good", partial: "warn", unprepared: "neutral" } as const;

/** The Start / Resume / Retry button label follows the book's real state (rules in docs/ingestion-api.md). */
export function startLabel(plan: PlanOut): string {
  const { stats, latest_job } = plan;
  if (stats.total_chunks > 0 && stats.pending_chunks === 0) return "All chunks embedded";
  if (latest_job?.status === "failed") return "Retry failed batches";
  if (stats.embedded_chunks > 0 || latest_job?.status === "paused") return "Resume embedding";
  return "Start embedding";
}
export const allEmbedded = (plan: PlanOut): boolean => plan.stats.total_chunks > 0 && plan.stats.pending_chunks === 0;

export const when = (iso: string | null | undefined): string => (iso ? new Date(iso).toLocaleString("en-GB") : "Unavailable");
export const rpmLabel = (rpm: number): string => (rpm > 0 ? `${rpm.toLocaleString("en-US")} requests per minute` : "Not paced");
export const jobTone = (j: JobOut): "good" | "bad" | "warn" | "neutral" =>
  j.status === "completed" ? "good" : j.status === "failed" ? "bad" : j.status === "paused" ? "warn" : "neutral";
export function compactDetails(details: Record<string, unknown>): string {
  const keys = Object.keys(details);
  if (keys.length === 0) return "";
  const text = keys.map((k) => `${k}: ${typeof details[k] === "object" ? JSON.stringify(details[k]) : String(details[k])}`).join(", ");
  return text.length > 140 ? `${text.slice(0, 137)}...` : text;
}
