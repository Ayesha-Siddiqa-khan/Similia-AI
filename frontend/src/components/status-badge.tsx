import { Activity, CircleAlert, LoaderCircle } from "lucide-react";

import { describeBackendStatus } from "@/lib/health";
import type { BackendStatus } from "@/types";

const toneClasses = {
  success: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  error: "bg-red-500/10 text-red-600 dark:text-red-400",
  muted: "bg-zinc-500/10 text-zinc-500",
} as const;

const icons = {
  ok: Activity,
  down: CircleAlert,
  checking: LoaderCircle,
} as const;

/** Small pill showing backend connectivity. */
export function StatusBadge({ status }: { status: BackendStatus }) {
  const { label, tone } = describeBackendStatus(status);
  const Icon = icons[status];
  return (
    <span
      data-tone={tone}
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ${toneClasses[tone]}`}
    >
      <Icon aria-hidden size={14} className={status === "checking" ? "animate-spin" : ""} />
      {label}
    </span>
  );
}
