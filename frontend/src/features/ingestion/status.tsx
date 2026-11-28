import { CircleCheck, CircleDashed, CircleDot, CircleX, CirclePause, RotateCcw, TriangleAlert, Zap } from "lucide-react";
import type { ReactNode } from "react";
import { agoLabel, ordinal, percentDone } from "./format";
import type { BookOverviewItem } from "./types";

const truncate = (text: string, max = 90) => (text.length > max ? `${text.slice(0, max - 3)}...` : text);

/** One unmistakable status per book: icon, colour and words, never colour alone. */
export function StatusChip({ book }: { book: BookOverviewItem }) {
  const percent = percentDone(book);
  const detail = book.detail ?? "";
  const chip = (tone: string, icon: ReactNode, label: string, extra?: string, title?: string) => (
    <span className={`status-chip status-${tone}`} data-state={book.state} title={title ?? (detail || undefined)}>
      {icon}<span className="status-label">{label}</span>{extra && <span className="status-extra">{extra}</span>}
    </span>
  );
  let chipNode: ReactNode;
  let under: string | null = detail || null;
  switch (book.state) {
    case "running": {
      chipNode = chip("running", <span className="pulse-dot" aria-hidden />, "Running", `${percent}%`);
      const parts = [book.idle_seconds !== null ? `updated ${agoLabel(book.idle_seconds)}` : null, detail || null].filter(Boolean);
      under = parts.length ? parts.join(" · ") : null;
      break;
    }
    case "queued": chipNode = chip("neutral", <CircleDashed size={12} aria-hidden />, "Waiting in queue"); under = detail ? truncate(detail) : null; break;
    case "stalled": chipNode = chip("warn", <TriangleAlert size={12} aria-hidden />, "Stalled?"); break;
    case "paused": chipNode = chip("warn", <CirclePause size={12} aria-hidden />, "Paused"); break;
    case "error": chipNode = chip("bad", <CircleX size={12} aria-hidden />, "Error", undefined, detail || "Error"); under = detail ? truncate(detail) : null; break;
    case "interrupted": chipNode = chip("warn", <RotateCcw size={12} aria-hidden />, "Interrupted"); under = detail ? `${detail} · resume to continue` : "Resume to continue"; break;
    case "complete": chipNode = chip("good", <CircleCheck size={12} aria-hidden />, "Complete"); under = null; break;
    case "partial": chipNode = chip("neutral", <CircleDot size={12} aria-hidden />, "Partial", `${percent}%`); break;
    case "ready": chipNode = chip("neutral", <CircleDot size={12} aria-hidden />, "Ready (prepared)"); break;
    default: chipNode = chip("grey", <CircleDashed size={12} aria-hidden />, "Not prepared"); under = null;
  }
  const auto = book.auto_resume;
  const autoLabel = !auto.enabled ? null
    : auto.position === 1 && book.state === "running" ? "Auto · running"
    : auto.position === 1 ? "Auto · next"
    : auto.position !== null ? `Auto · ${ordinal(auto.position)} in queue` : "Auto";
  return (
    <div className="status-cell">
      <div className="status-row">
        {chipNode}
        {autoLabel && <span className="status-chip status-auto" title="Automatic resume is on for this book"><Zap size={12} aria-hidden /><span className="status-label">{autoLabel}</span></span>}
      </div>
      {under && <small className="status-detail" title={detail || undefined}>{under}</small>}
      {!auto.enabled && auto.note && <small className="status-detail">{auto.note}</small>}
    </div>
  );
}
