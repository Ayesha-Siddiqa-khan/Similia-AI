"use client";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { number } from "@/components/ui";
import { rpmLabel } from "./format";
import type { BookOverviewItem, IngestionLimits } from "./types";

/** Starting automatic resume spends paid tokens: only this dialog's confirm button may send `confirmed: true`. */
export function ConfirmAuto({ books, limits, busy, onCancel, onConfirm }: { books: BookOverviewItem[]; limits: IngestionLimits; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  const total = books.reduce((sum, b) => sum + b.pending_tokens, 0);
  const rows: [string, string][] = [
    ["Estimated tokens in total", number(total)],
    ["Provider", limits.provider],
    ["Provider host", limits.endpoint_host],
    ["Model", limits.model],
    ["Limit per job", `${number(limits.per_job_token_limit)} tokens`],
    ["Budget remaining", `${number(limits.budget_tokens_remaining)} tokens`],
    ["Batch size (tokens)", number(limits.batch_tokens)],
    ["Request pace", rpmLabel(limits.requests_per_minute)],
  ];
  return (
    <ConfirmDialog id="auto-confirm" title="Resume these books automatically?" confirmLabel="Confirm and resume automatically" busyLabel="Starting..." busy={busy} onCancel={onCancel} onConfirm={onConfirm}>
      <p>This sends the chunks that still have no vector to the embedding provider and spends paid tokens. Work already stored is never repeated or billed again.</p>
      <ul className="auto-books">{books.map((b) => <li key={b.book_id}><strong>{b.title}</strong> <span className="fine-print">{number(b.pending_chunks)} chunks · {number(b.pending_tokens)} tokens pending</span></li>)}</ul>
      <dl className="measurements">{rows.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}</dl>
      <p>It will keep resuming these books one at a time until they are complete, you stop it, the budget or a limit is reached, or the provider refuses.</p>
      <p>Any provider stop pauses it.</p>
    </ConfirmDialog>
  );
}
