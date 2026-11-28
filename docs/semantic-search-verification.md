# Semantic search investigation

## Findings

Library Search, legacy Case Analysis, and Clinical Reports use `build_retriever`. The shared vector path calls Voyage with query input, then sends the resulting vector to the read-only Supabase `match_chunks` RPC. The migration defines a cosine search over `vector(1024)`. Ingestion uses document input. The configured model during verification was `voyage-4-lite`, with a similarity threshold of 0.25 and the embedding stop clear.

The reported `RuntimeError` identifies the fallback boundary but does not establish the historical provider or database fault. The old embedding adapter collapsed exhausted transient Voyage failures into a plain `RuntimeError`. Response count and dimension failures also used `RuntimeError`. The fallback displayed the outer exception class alone, losing the stage and underlying status. No contemporaneous trace was available to distinguish those paths for the affected run.

The new checks on the three approved, non-sensitive queries each returned a 1,024-value vector and six rows from the existing index. All eighteen returned rows came from Materia Medica. Several were relevant paraphrases, while others matched only an isolated word or symptom. This confirms current connectivity and compatibility with the existing searchable index.

| Verification query | Example from the returned passages | Limits found on inspection |
| --- | --- | --- |
| Eczema with sticky discharge, worse during winter | `encyclopedia-of-homeopathy`, PDF p. 196 (0.575), describes sticky fluid exuding from inflamed patches. `DISEASES OF SKIN`, PDF p. 55 (0.553), mentions winter aggravation. | These are separate matches. The first stored section label appears unrelated to the passage text. |
| Skin itching aggravated by warmth of bed at night | Frans Vermeulen, `Synoptic Materia medica I.pdf`, Face, PDF p. 325 (0.650), uses “itching, night agg.” and “warm, on becoming.” Skin, PDF p. 494 (0.619), records evening itching in bed. | The warm-bed phrase on p. 325 appears in a pain entry. It should not be attributed to itching from that passage. |
| Thick honey-like discharge from skin eruptions | Frans Vermeulen, `Synoptic Materia medica I.pdf`, Face, PDF p. 148 (0.623), describes eczema resembling dried honey. | It supports appearance only. A lower result used “honey” for perspiration odour and did not support the discharge finding. |

Page, section and author fields above come from indexed source records. The check reads the stored passages and does not independently establish pagination or clinical efficacy.

## Repair plan

Preserve stage and safe error details for Voyage requests and the Supabase RPC. Bound retries on interactive embedding calls and reuse a query vector across consecutive category searches. Preserve requested and actual modes through the case pipeline, including empty results and late fallback. Test those paths without regenerating vectors or updating historical reports.

## Changes

| Files | Change |
| --- | --- |
| `backend/app/services/embeddings.py` | Interactive embeddings keep their underlying provider errors, stop at two attempts, respect short retry windows and reject unusable vectors. Document-ingestion retry behavior is preserved. |
| `backend/app/ai/rag/retrieval.py`, `backend/app/ai/rag/guard.py` | The shared retriever reuses one query vector across consecutive category RPCs. Failures identify Voyage, Supabase or result parsing and retain safe status and error codes. Logs omit upstream bodies and queries. The provider stop still takes precedence. |
| `backend/app/ai/rag/case_analysis.py`, `backend/app/api/routes/cases.py` | Case analysis deduplicates phrases and chunks, uses ranks to compare results across different methods and rejects invalid citation IDs. New snapshots save search execution metadata in the existing JSON field, including empty and mixed results. |
| `backend/app/api/routes/knowledge.py` | Library Search still returns retrieved sources if coverage stats or retrieval evaluation storage is temporarily unavailable. |
| `backend/app/services/report_files.py`, `backend/scripts/evaluate_search_modes.py` | PDF and Word reports and the evaluator read current and historical snapshots and preserve search provenance. |
| `frontend/src/features/cases/analysis-view.tsx`, `case-report.tsx`, `search-method.tsx`, `types.ts` | Case views and web reports surface the requested and actual search modes, including mixed, skipped and unknown states. |
| `backend/tests/test_embeddings.py`, `test_search_modes.py`, `test_case_analysis.py`, `test_keyword_search.py`, `frontend/src/features/cases/analysis-evidence.test.tsx` | Regression coverage preserves safe error detail, tests partial fallback, and checks the behavior of old and new snapshots. |
| `backend/tests/test_clinical_workflow.py` | Normalize PDF text extraction before comparing report IDs, since the renderer can extract letter pairs as a single ligature. |

The approved saved-case check found seven historical analyses. The latest requested Semantic and stored both semantic and keyword passages. The original fallback text was present in the saved history and still contained only the generic error class. The in-memory verification respected the recorded urgency warning and produced the urgent handoff with zero searches, zero provider calls and zero writes.

No schema change or background ingestion restart is required. Keep the model and vector dimension aligned with the indexed corpus. If a future fallback reports a Voyage error, check the server's provider access, quota and provider-stop status. If it reports Supabase vector search, check the service account's `match_chunks` access and database availability. Existing snapshots remain readable and the original historical error cannot be reconstructed from the saved label.

Local verification passed 325 backend tests and 227 frontend tests, alongside TypeScript and lint checks for changed files.
