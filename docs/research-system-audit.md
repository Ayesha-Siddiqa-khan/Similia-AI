# Research and consultation system: audit, baseline and plan

Date: 28 November 2026. Covers the brief "Advanced Clinical Research, Adaptive Consultation and Evidence Reasoning System" (sections 2 to 27). This is Phases 1 to 3. No live model, embedding or web call was made, and no migration was written or applied.

How to read the evidence: **Checked** means I confirmed it in the code or by running something. **Reported** means a read-only audit agent found it by reading the code and I have not re-checked it.

## 1. State of the repository

- Last commit: `7da26e2` on `main`, pushed to `origin`. About 200 changed or new files are **not committed**. Most were written after that commit: the clinical reports workflow, four AI providers, local speech, a Windows desktop build, query batching with a shared Voyage budget, and a fine-tuning dataset module.
- The four newer migrations (`20261124160000` to `20261124210000`) are applied: their tables and columns exist (**Checked**, read-only).
- A pattern scan of the changed files found only short dummy keys in tests (**Checked**). `*.bak` files, `fix_similia_desktop_reports.py` and `build commands.txt` are untracked and probably should not be committed.

## 2. Baseline (before any change in this task)

| Check | Result |
|---|---|
| Backend tests | 380 passed, 1 failed |
| Backend lint | 1 error (`app/ai/finetune/pilot.py`, unused variable) |
| Frontend tests | 248 passed |
| Frontend lint and types | clean |

The failing test is `test_pilot_builds_verified_examples_from_cleared_sources`: its fixture uses page 4, but the code rejects pages below 5 (`pilot.py:385`, **Checked**). It belongs to unfinished fine-tuning work, so I left it alone.

After the fixes in section 3: backend 393 passed (the same 1 failed, the same lint error), frontend 250 passed with lint and types clean.

No baseline of answer **quality** exists yet. There are no reference cases, relevance labels or scored runs.

## 3. Defects found

| # | Defect | Evidence | State |
|---|---|---|---|
| D1 | Clinical Reports research failed whenever a search returned a passage: a local variable `count` shadowed the imported `count()` function. | Reproduced by two new tests | **Fixed**, with `tests/test_clinical_research_hits.py` |
| D2 | The prescription form is prefilled with 30C, 4 pills, twice daily, 7 days and standard advice, also for children. The PDF and the signed card show the same values when a field is empty. The brief (section 14) forbids this. | `analysis-view.tsx:84-86,130-133`, `report_files.py:581-589` (**Checked**) | **Fixed** (see note) |
| D3 | Sign-off accepts **any** earlier analysis of the case, so an older analysis without urgent findings can be signed. It does not check consent or archive state. | `cases.py:831-851` (**Checked**) | **Fixed** |
| D4 | "Use AI Suggestion" inserts a fixed template as the urgent-findings disposition (it states that referral advice was given) with one click, satisfying the safety requirement. | `analysis-view.tsx:137-150,329-345` (**Checked**) | **Fixed** |
| D5 | The prescription PDF prints the user's internal ID as the treating practitioner. | `cases.py:903` (**Checked**) | **Fixed** |
| D6 | The red-flag screen matches substrings with no negation handling ("no chest pain" flags), and a patient of unknown age gets no child safeguards. | `case_analysis.py:38-141`, `patient_rules.py` (**Reported**) | Open |
| D7 | Legacy analyses are not invalidated when patient age or photographs change, and legacy sign-off works even when the clinical workflow is switched on. | `cases.py:479-492,831` (**Reported**) | Open |

**How D2 to D5 were fixed** (tests: `backend/tests/test_signoff_safety.py`, `cases.test.tsx`; not yet checked in a browser):

- D2: every prescription field starts empty, including the remedy and diagnosis; the PDF and the signed card say "Not recorded". The potency pick list remains and selects nothing by itself.
- D3: sign-off is refused unless the analysis is the newest one, consent is active and the patient is not archived. The check is made in the API; two requests at the same instant are not serialised in the database.
- D4: both template buttons and their draft text are removed. Dictation remains.
- D5: a prescriber's name field (required on screen for an accepted or changed remedy) is stored with the review and printed. The API refuses such a sign-off without a name (422).

**Existing records.** Earlier signed reviews keep what was stored. On 28 November, 1 of 3 signed reviews held all four old default values (30C, 4 pills, Twice daily, 7 days); a practitioner should confirm it was intended. Earlier reviews have no prescriber name.

## 4. Traceability matrix

The matrix describes the state at the audit, before the D2 to D5 fixes.

| § | Requirement | Today | Main gap | Status |
|---|---|---|---|---|
| 3 | Live adaptive consultation | A batch of up to 24 suggested questions, refreshed by hand (`case_questions.py`) | No one-question loop that learns from each answer | Missing |
| 4 | Case-taking intelligence | Symptom cards; per-run lists of negative and uncertain findings | No finding states (confirmed, absent, uncertain, contradictory, unassessed) or link to the patient's words | Partial |
| 5 | Persistent consultation state | Autosaved draft; revision counter | No transcript, questions are lost on reload, corrections overwrite rows | Missing |
| 6 | Internal retrieval | Planned queries, batching, hybrid ranking, deduplication, author and book limits, exact-quote checks (clinical path) | No contradiction, remedy-specific or previous-treatment queries; no neighbouring passages; no OCR-quality flag | Partial |
| 7 | External research | None | Everything | Missing |
| 8 | De-identified external queries | Identifier filter on search phrases | Applies to nothing external yet | Partial |
| 9 | Internal versus external comparison | Historical associations only | No comparison, agreement or limitation structure | Missing |
| 10 | Case-based reasoning | One ranking call with fits and against | No chronology, alternatives or "why this finding matters" | Partial |
| 11 | Remedy suggestions | Remedy, confidence word, fits, against, citations; may return nothing | No missing information per remedy, evidence quality or previous-treatment note | Partial |
| 12 | Previous-treatment analysis | Prompts mention it | No structured record or analysis; earlier reviews are not read | Missing |
| 13 | Independent critical review | Quote and citation-ID checks | No second, separate review call | Missing |
| 14 | Prescription workflow | Draft, reviewed and signed reports with a signing grant; a separate legacy prescription form | Two parallel paths, no route or rationale field, defaults (D2), no structured research draft | Partial |
| 15 | Contextual safety | Red-flag screen, urgent handoff, disposition, minor and infant rules | D3, D4, D6; no urgency level or recorded evidence per finding | Partial |
| 16 | Modular versioned prompts | Several separate prompts | None versioned, no changelog, patient text not delimited, one ranking prompt does not treat passages as data | Partial |
| 17 | Separate records | Analyses, reports, reviews, images | Transcript, questions, answers, corrections, external results, critical review, follow-ups, outcomes, evaluation feedback | Partial |
| 18 | PDF and JSON exports | Analysis and clinical report PDF and Word, patient JSON, Urdu | 6 of 8 documents, page numbers, de-identified export; legacy excerpts cut at 600 characters | Partial |
| 19 | Evaluation workspace | Search-mode comparison script | Workspace, replay, comparison, feedback | Missing |
| 20 | Follow-up and outcomes | Photograph comparison only | Visits, outcomes, longitudinal comparison | Missing |
| 21 | Model configuration | Four providers, encrypted keys, rate limits, schema validation | No per-stage model, no token, cost or latency record, uneven timeouts and retries | Partial |
| 22 | Traceability | Model and passages stored | No provider on legacy rows, no prompt or application version, no tokens or latency | Partial |
| 23 | Evaluation suite | Unit tests | No scenario set, no regression case, no injection or long-consultation tests | Missing |
| 24 | Performance measures | Retrieval counters in logs | None of the listed measures | Missing |
| 25 | Interface | Stepper, analysis, clinical reports, exports | No conversation screen, research, review, follow-up or experiment views | Partial |
| 26, 27 | Method and verification | This document | Later phases | In progress |

Prompts today (**Reported**): `case_analysis.py` (rules, normalise, rank), `case_questions.py`, `clinical_research.py` (research, guidelines), `report_translation.py`, two translation and photograph prompts in the clinical routes.

## 5. Proposed increments

Each is behind a feature flag, adds tables only (written as a migration file for you to run in project `ivlmduwdkwgrxqxjjuyg`), and is tested with a mocked model.

| Order | Increment | Main files | Database | Depends on |
|---|---|---|---|---|
| 0 | Safety and honesty fixes: D2 to D5 | `analysis-view.tsx`, `report_files.py`, `cases.py`, tests | none | your yes |
| 1 | Adaptive consultation: turns with original wording and timestamps, finding states linked to turns, corrections as new revisions, one question at a time, resume; prompt registry with versions (A, I); the de-identified chronic-skin regression scenario | new `ai/consultation/`, `ai/prompts/`, new routes and screen | consultation, turn, finding, revision tables | 0 recommended |
| 2 | Retrieval and external research: contradiction and previous-treatment queries, neighbouring passages, research interface that reports "unavailable" until a source is chosen, citation records (B, C, D) | `ai/rag/`, new `services/research/` | research query and source tables | provider decision |
| 3 | Comparative reasoning and separate critical review, bounded re-analysis, execution metadata (E, F) | new `ai/reasoning/` | comparison, review, run tables | 1, 2 |
| 4 | Research draft and prescription record: one path, explicit practitioner fields, AI draft kept unchanged (G) | clinical workflow | draft and prescription tables | 3 |
| 5 | Eight documents, de-identified and JSON exports, page numbers | `report_files.py` | none | 4 |
| 6 | Follow-up (H), evaluation workspace, measures, held-out cases | new screens | follow-up, outcome, evaluation tables | 5 |

Measures that need a clinician (relevance, correctness, safety) cannot be produced by me. The software can record them; a qualified reviewer must score them.

## 6. Decisions needed

1. **Order:** answered: D2 to D5 were fixed first. Next is increment 1.
2. **Commit:** save the current uncommitted work as its own commit first, so new work stays separate and reversible? (Excluding the `.bak` files and scratch scripts.)
3. **Synthetic cases:** earlier you asked for no synthetic data in the app. The brief asks for synthetic experimental cases. Proposal: synthetic data only in tests and in a clearly separated, labelled experiment area, never beside patient records.
4. **External research:** free sources first (for example PubMed and Europe PMC, after checking their terms), your AI provider's own web search (cost and support differ per provider), or a paid search service (a new company receives de-identified queries)?
