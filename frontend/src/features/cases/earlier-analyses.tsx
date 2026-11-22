"use client";

import { useState } from "react";
import { Badge, Loading, Notice } from "@/components/ui";
import { useAnalysisHistory } from "./api";
import { formatDate, outcomeLabel } from "./paths";
import type { Analysis } from "./types";

const outcomeTone = { ranked: "good", insufficient_sources: "neutral", red_flag: "warn" } as const;

/** A read-only summary of one saved analysis. Saved analyses never change. */
function SavedAnalysis({ analysis }: { analysis: Analysis }) {
  return (
    <div className="stack">
      {analysis.red_flags.length > 0 && <Notice error>Urgent concern: {analysis.red_flags.join("; ")}</Notice>}
      {(analysis.cautions ?? []).length > 0 && <Notice><ul>{analysis.cautions.map((c) => <li key={c}>{c}</li>)}</ul></Notice>}
      {analysis.remedies.length === 0 ? <p className="fine-print">No remedy was suggested.</p> : (
        <ol>{analysis.remedies.map((r) => <li key={r.remedy}><strong>{r.remedy}</strong> <Badge>{r.confidence} confidence</Badge> · {r.citations.length} {r.citations.length === 1 ? "source" : "sources"}<p>{r.rationale}</p></li>)}</ol>
      )}
      <p className="fine-print">{analysis.model ? `Model: ${analysis.model}.` : ""}</p>
    </div>
  );
}

/** Collapsed by default; the list is only fetched once the section is opened. */
export function EarlierAnalyses({ caseId }: { caseId: string }) {
  const [open, setOpen] = useState(false);
  const history = useAnalysisHistory(caseId, open);
  return (
    <details className="panel" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="panel-heading"><div><h2>Earlier analyses</h2><p>Every analysis run on this case, newest first. These are saved snapshots and cannot be changed.</p></div></summary>
      <div className="panel-padding stack">
        {!open ? null : history.isPending ? <Loading /> : history.isError ? <Notice error>{history.error.message}</Notice> : history.data.length === 0 ? <p className="fine-print">No earlier analyses.</p> : history.data.map((a) => (
          <details key={a.id}>
            <summary>{formatDate(a.created_at)} · <Badge tone={outcomeTone[a.outcome]}>{outcomeLabel[a.outcome]}</Badge>{a.remedies.length > 0 && <> · {a.remedies.map((r) => r.remedy).join(", ")}</>}</summary>
            <SavedAnalysis analysis={a} />
          </details>
        ))}
      </div>
    </details>
  );
}
