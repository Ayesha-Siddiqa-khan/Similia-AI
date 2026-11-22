"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Plus, Sparkles } from "lucide-react";
import { Notice } from "@/components/ui";
import { ApiErrorNotice } from "./api-error-notice";
import { Bi } from "./bilingual";
import type { FollowUpQuestion, FollowUps } from "./types";
import { urLabels } from "./urdu-labels";

export type QuestionStep = "mental" | "physical_general" | "particular" | "history";

interface Props {
  step?: QuestionStep;
  questions: FollowUps | null;
  loading: boolean;
  error?: Error | null;
  canSuggest: boolean;
  /** Questions already added to the case; when given, it decides what shows as Added. */
  asked?: string[];
  /** The case already holds the maximum number of entries. */
  full?: boolean;
  urdu: boolean;
  onUrduChange: (value: boolean) => void;
  onSuggest: () => void;
  onUse: (question: FollowUpQuestion) => void;
}

/**
 * AI-written follow-up questions for the current step: the question and its Urdu translation only.
 * (The example answer appears later, under the card made by "Add to case".) The list scrolls inside
 * its own box and can be hidden, so the card you are working on stays in view.
 */
export function SuggestedQuestions({ step, questions, loading, error, canSuggest, asked, full, urdu, onUrduChange, onSuggest, onUse }: Props) {
  const [used, setUsed] = useState<Set<string>>(new Set());
  const [hidden, setHidden] = useState(false);
  const items = step && questions ? questions[step] : [];
  const askedSet = asked ? new Set(asked) : null;
  const hasList = !!questions && questions.red_flags.length === 0 && !!step && items.length > 0;
  return (
    <div className="suggested">
      <div className="suggested-head">
        <strong><Sparkles size={15} aria-hidden /> AI follow-up questions</strong>
        <div className="suggested-actions">
          <label htmlFor="questions-urdu" className="check-label inline"><input id="questions-urdu" type="checkbox" checked={urdu} onChange={(e) => onUrduChange(e.target.checked)} disabled={loading} /> Also show in Urdu <span lang="ur" className="urdu-inline">(اردو)</span></label>
          {hasList && <button type="button" className="button secondary" aria-expanded={!hidden} onClick={() => setHidden(!hidden)}>{hidden ? <ChevronDown size={16} aria-hidden /> : <ChevronUp size={16} aria-hidden />}{hidden ? <Bi en="Show questions" ur={urLabels.showQuestions} show={urdu} /> : <Bi en="Hide questions" ur={urLabels.hideQuestions} show={urdu} />}</button>}
          <button type="button" className="button secondary" disabled={!canSuggest || loading} onClick={onSuggest}>
            {loading ? "Thinking…" : questions ? "Refresh questions" : "Suggest questions"}
          </button>
        </div>
      </div>
      {!canSuggest && <p className="fine-print">Write the chief complaint first.</p>}
      <p className="fine-print">Sends this case&apos;s text to the AI provider to write questions. Prompts only; not a diagnosis.</p>
      {full && <Notice error>This case already has the maximum number of entries. Remove entries you do not need before adding more.</Notice>}
      {error && <ApiErrorNotice error={error} />}
      {questions && questions.red_flags.length > 0 && <Notice error><strong>Possible urgent concern. Questions were not generated.</strong><ul>{questions.red_flags.map((f) => <li key={f}>{f}</li>)}</ul><p>Assess urgency first.</p></Notice>}
      {questions && questions.red_flags.length === 0 && step && items.length === 0 && <p className="muted">No suggestions for this step yet. Try &ldquo;Refresh questions&rdquo; after adding more details.</p>}
      {hasList && !hidden && (
        <ul className="question-list">{items.map((q) => {
          const key = `${step}:${q.question}`;
          const added = askedSet ? askedSet.has(q.question) : used.has(key);
          return <li key={key}>
            <div>
              <strong>{q.topic}</strong>
              <span>{q.question}</span>
              {urdu && q.question_ur && <span className="urdu" lang="ur" dir="rtl">{q.topic_ur ? <strong>{q.topic_ur}: </strong> : null}{q.question_ur}</span>}
            </div>
            <button type="button" className="chip" disabled={added || full} onClick={() => { setUsed(new Set(used).add(key)); onUse(q); }}><Plus size={13} aria-hidden /> {added ? "Added" : "Add to case"}</button>
          </li>;
        })}</ul>
      )}
    </div>
  );
}
