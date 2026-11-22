"use client";

import { useEffect, useRef } from "react";
import { number } from "@/components/ui";
import { rpmLabel } from "./format";
import type { PlanOut } from "./types";

/** Starting spends paid tokens, so only this dialog's confirm button may send `confirmed: true`. */
export function ConfirmEmbedding({ plan, label, busy, onCancel, onConfirm }: { plan: PlanOut; label: string; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) {
      if (typeof element.showModal === "function") element.showModal();
      else element.setAttribute("open", "");
    }
    return () => { if (element?.open && typeof element.close === "function") element.close(); };
  }, []);
  const { limits, stats } = plan;
  const rows: [string, string][] = [
    ["Book", stats.title],
    ["Provider host", limits.endpoint_host],
    ["Model", limits.model],
    ["Estimated tokens", number(stats.pending_tokens)],
    ["Limit for this job", number(plan.effective_token_limit)],
    ["Budget used", number(limits.budget_tokens_used)],
    ["Budget remaining", number(limits.budget_tokens_remaining)],
    ["Batch size (tokens)", number(limits.batch_tokens)],
    ["Request pace", rpmLabel(limits.requests_per_minute)],
  ];
  return (
    <dialog ref={dialog} className="modal" aria-modal="true" aria-labelledby="embed-confirm-title" onCancel={onCancel}>
      <h2 id="embed-confirm-title">Confirm paid embedding</h2>
      <p>This sends the chunks that still have no vector to the embedding provider and spends paid tokens. Work already stored is never repeated or billed again.</p>
      <dl className="measurements">{rows.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl>
      <div className="button-row">
        <button autoFocus className="button secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="button primary" onClick={onConfirm} disabled={busy}>{busy ? "Starting..." : `Confirm: ${label}`}</button>
      </div>
    </dialog>
  );
}
