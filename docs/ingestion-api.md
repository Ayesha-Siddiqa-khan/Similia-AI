# Book ingestion API (operator only)

All endpoints require an **operator** account (role `operator` or `admin`). The browser calls them only
through the proxy at `/api/backend/<path>`. Response and request shapes are the Pydantic models in
`backend/app/schemas/ingestion.py` (and `knowledge.py` for search). No response ever contains an API key.

## How embedding a book works

1. **Upload** (`POST books`): the file is checked (size, real PDF header), its text is extracted and saved.
   Nothing is sent to any provider. A book with identical content is refused (409).
2. **Prepare** (`POST books/{id}/prepare`): the text is cleaned and split into chunks that are saved without
   vectors. This is local and **free**. It returns the plan with an exact token estimate. Safe to repeat.
3. **Start / Resume / Retry** (`POST books/{id}/ingest`): sends the chunks that still have no vector to the
   embedding provider, in small token-limited batches at a paced rate. **This spends paid tokens**, so the
   server refuses it unless the body says `confirmed: true`. One call serves all three: the next job simply
   continues with the chunks that are still missing, so completed work is never repeated or re-billed.
4. **Pause** (`POST ingestion-jobs/{id}/pause`): the job finishes its current batch, then stops safely.
5. A job also stops by itself, safely, when: its token limit is reached, the total budget is used up, the
   provider stop is set, or the provider returns an error. Every stop is recorded in the event history.
6. After a crash or restart a job with no heartbeat for 5 minutes is marked failed ("interrupted"); starting
   again resumes from the last stored chunk.

## Endpoints

| Method and path | Purpose | Returns |
|---|---|---|
| `GET ingestion/overview` | every book with real index counts, active jobs, limits | `OverviewOut` |
| `GET books/{id}/ingestion` | plan, last 10 jobs, last 50 events for one book | `BookIngestionOut` |
| `POST books/{id}/prepare` | extract and split text (free) | `PlanOut` |
| `POST books/{id}/ingest` | body `StartRequest`; start/resume/retry (spends tokens) | `JobOut` (HTTP 202) |
| `POST ingestion-jobs/{id}/pause` | request a safe pause | `JobOut` |
| `GET ingestion-jobs/{id}` | one job | `JobOut` |
| `GET ingestion-jobs/{id}/events?limit=50` | history and errors of one job | `EventOut[]` |
| `GET books/{id}/chunks?offset=0&limit=20&q=&embedded=` | inspect chunks; `embedded` is `true`, `false` or empty | `ChunkPage` |
| `GET books/{id}/text?offset=0&limit=5` | inspect extracted text by PDF page | `TextPreview` |
| `POST books` | upload (multipart: `file`, `title`, `category`, optional `author`, `publisher`, `publication_year`, `language`, `source_uri`) | `BookOut` (HTTP 201) |
| `POST search` | RAG search; results carry `page_start`, `page_end`, `book_complete`; response carries `incomplete_books` | `SearchResponse` |

Categories: `materia_medica`, `repertory`, `organon`, `general`.

Error statuses the screens must handle: 409 (already registered, already has an active job, nothing left to embed,
confirmation missing), 422 (invalid file or input), 429 (provider stop is set, or the token budget is used up),
503 (service not configured). The proxy passes the backend's own explanation for 409, 422, 428 and 429.

## Rules the interface must follow

- Never show a number the backend did not return. No placeholders, no demo values.
- The Start/Resume/Retry button label follows the state: no vectors yet = "Start embedding"; some vectors or a paused
  job = "Resume embedding"; latest job failed = "Retry failed batches"; every chunk embedded = disabled, "All chunks embedded".
- The button is disabled while `plan.can_start` is false and the reasons in `plan.blockers` are shown.
- Starting always opens a confirmation dialog showing: the provider host (`endpoint_host`), model, estimated tokens
  (`stats.pending_tokens`), the limit for this job (`effective_token_limit`), budget used and remaining, batch size and
  requests per minute. Only its confirm button sends `confirmed: true`.
- While a job is `pending` or `running`: refresh every 3 seconds, show progress (`processed_chunks` of `total_chunks`),
  tokens used against the limit, and enable Pause. After Pause is requested show "Pause requested, finishing the current batch".
- A book with `frozen_plan: true` belongs to the command-line pipeline: show that, and do not offer Start.
- A book with `complete: false` is only partly searchable. Say so wherever its passages appear.
- Page numbers are PDF page numbers, not printed page numbers. Label them "PDF page".
