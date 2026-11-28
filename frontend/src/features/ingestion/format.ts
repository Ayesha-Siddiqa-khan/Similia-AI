import type { BookIndexStats, BookOverviewItem, JobOut, PlanOut } from "./types";

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

const ORDINALS = ["th", "st", "nd", "rd"];
export function ordinal(n: number): string {
  const v = n % 100;
  return `${n}${ORDINALS[(v - 20) % 10] ?? ORDINALS[v] ?? ORDINALS[0]}`;
}
/** "12s ago", "3 min ago", "2 h ago" from a number of seconds. */
export function agoLabel(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
}
/** Percent of the book (or of its running job) already done, from real counts only. */
export function percentDone(b: BookOverviewItem): number {
  const job = b.state === "running" ? b.latest_job : null;
  const [done, total] = job && job.total_chunks > 0 ? [job.processed_chunks, job.total_chunks] : [b.embedded_chunks, b.total_chunks];
  return total > 0 ? Math.min(100, Math.max(0, Math.round(done / total * 100))) : 0;
}
export const ATTENTION_STATES = ["error", "stalled", "interrupted", "paused"] as const;
/** Why a book cannot be queued for automatic resume, or null when it can. */
export function autoBlocker(b: BookOverviewItem): string | null {
  if (b.frozen_plan) return "Command-line pipeline: continue it with the command line";
  if (!b.prepared) return "Not prepared yet";
  if (b.complete || b.pending_chunks === 0) return "Already complete";
  if (b.auto_resume.enabled) return "Automatic resume is already on";
  return null;
}
