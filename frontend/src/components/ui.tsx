import type { ReactNode } from "react";
import { AlertCircle, Inbox, LoaderCircle } from "lucide-react";

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "good" | "warn" | "bad" }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
export function Panel({ title, description, children, action }: { title: ReactNode; description?: ReactNode; children: ReactNode; action?: ReactNode }) {
  return <section className="panel"><div className="panel-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{action}</div>{children}</section>;
}
export function Notice({ children, error = false }: { children: ReactNode; error?: boolean }) {
  return <div className={`notice ${error ? "notice-error" : ""}`} role={error ? "alert" : "status"}><AlertCircle size={18} aria-hidden /><div>{children}</div></div>;
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><Inbox size={28} aria-hidden /><h3>{title}</h3><p>{children}</p></div>;
}
export function Loading() {
  return <div className="empty" role="status"><LoaderCircle className="spin" size={24} aria-hidden /><p>Loading workspace data…</p></div>;
}
export function Progress({ value, total, label }: { value: number; total: number; label: string }) {
  const percent = total > 0 ? Math.min(100, Math.max(0, value / total * 100)) : 0;
  return <div className="progress-wrap"><div className="progress-label"><span>{label}</span><strong>{percent.toFixed(1)}%</strong></div><progress aria-label={label} max={Math.max(total, 1)} value={value} /></div>;
}
export function Metric({ label, value, detail, icon }: { label: string; value: ReactNode; detail: string; icon?: ReactNode }) {
  return <div className="metric"><div className="metric-label">{label}{icon}</div><strong>{value}</strong><p>{detail}</p></div>;
}
export const number = (value: unknown): string => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("en-US", { maximumFractionDigits: 1 }) : "Unavailable";
export const bytes = (value: unknown): string => typeof value === "number" ? `${number(value / 1024 / 1024)} MB` : "Unavailable";
