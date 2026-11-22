# Budgeted PDF ingestion

The batch command extends `app.ai.ingestion` and reuses the existing Voyage
provider, Supabase admin client, knowledge tables and `apply_chunk_embeddings`
RPC. It does not change the database schema, RLS or original PDFs.

Run commands from `E:\github\Similia AI\backend`:

```powershell
# Local extraction, inventory, token-based chunking and sample QA artifacts.
uv run --offline --no-sync python -m app.ai.ingestion --inventory

# Live: first verify a representative sample, then process books in token order.
uv run --offline --no-sync python -m app.ai.ingestion --live

# Optional: stop after storing/verifying 16 representative chunks.
uv run --offline --no-sync python -m app.ai.ingestion --live --sample
```

`backend/.env` supplies `VOYAGE_API_KEY`, `VOYAGE_MODEL`, `SUPABASE_URL` and
`SUPABASE_SECRET_KEY`. The chosen storage project is `ivlmduwdkwgrxqxjjuyg`;
the command rejects a different project URL. The Codex Supabase connector's
login is separate from the backend's server-side credentials. Never put a secret
key in the frontend, a report, a command-line argument or chat.

The official Voyage tokenizer is stored at
`reports/ingestion/tokenizer/tokenizer.json`. It was fetched from
`https://huggingface.co/voyageai/voyage-4-lite/resolve/main/tokenizer.json`.
After that initial artifact download, preparation runs locally. The CLI never
installs dependencies or silently downloads a missing tokenizer.

Configuration: `MAX_RUN_EMBEDDING_TOKENS` in the backend environment defaults to
200000. CLI overrides are `--max-run-embedding-tokens`, `--part-threshold`
(default 100000 source tokens), `--batch-chunks` (16), and `--batch-tokens`
(10000, including a conservative document-prompt allowance).

The journal budget persists across restarts. Re-running the command does **not**
grant another 200000 tokens. Do not delete or edit checkpoints to reset the
budget. An authorized increase can be passed explicitly. A final batch that
cannot fit its reservation is left pending, so some budget can remain unused.
Actual API usage and unknown usage from failed connections are recorded
separately. Remaining account-wide free quota is unknown.

Requests are sequential and paced for the documented free-trial rolling limits
of 3 RPM / 10000 TPM. Retry-After, exponential backoff, quota stops and dynamic
batch reduction are handled by the runner. SDK-level retries are disabled for
this runner so every attempt can be reserved and accounted for.

## Durable resume

`reports/ingestion/checkpoint.sqlite3` uses FULL-synchronous transactions.
Each provider response saves vectors and reported usage atomically into a local
outbox **before** the Supabase write. Writes use stable identifiers, and stored
content hashes and 1024-dimensional vectors are read back before a batch is
checkpointed. A failed database write reuses cached vectors, including when
batch boundaries change on restart. A lost database acknowledgement is resolved
by reading the stored rows. Parts have independent checkpoint records; normal
processing finishes Part 1 before Part 2.

If the process dies during a provider call before its response is persisted,
there is no reliable way to distinguish an unbilled request from a billed request
whose response was lost. Such an in-flight request retains its token reservation
and pauses automatic replay for manual reconciliation. This avoids claiming
exactly-once billing when the provider has not supplied an idempotency guarantee.

The process holds an OS file lock. Process exit releases it automatically.
Keep the whole reports directory backed up, including SQLite files. Local reports,
tokenizer artifacts and checkpoints are ignored by Git.

## Quality and source fidelity

The inventory sorts by official Voyage tokenizer counts, not PDF size. It
selects only the two smallest valid PDFs and never silently substitutes another
book when either fails extraction checks. Original extracted text is retained
along with page coordinates, full source hashes, chapter/rubric/aphorism links,
UTF-8 byte ranges and unique source-token coordinates.

Structure detection uses local rules, not an LLM or embedding-based semantic
segmentation. LangChain applies paragraph/sentence-aware token splitting only
inside detected structural units. Materia Medica targets 450 tokens with 60
overlap and a 650-token maximum; repertory units have no overlap and a 250-token
maximum; independent aphorisms stay separate and split only above 500 tokens.
Small complete sections can fall below preferred sizes. Unusually large rubric
lists are split with their hierarchy repeated and linked-part metadata.

The supplied Materia Medica includes OCR noise and digitization watermarks.
Recognized watermarks and running page headers are excluded from embeddings; exact source ranges
are reported; original text is untouched. Running headers supply a remedy-name vocabulary, while body headings establish the actual remedy boundaries, so a page title cannot relabel text continuing from the preceding remedy. The non-text Materia pages 631 and 649
were visually checked as blank/cover pages. Organon page 1 is an image cover and
128 is blank. No OCR dependencies were added.

Organon's source has a misspelled `Prara 24`, an attached page number before
`PARA-245`, and no printed marker for 227 on page 94. Detected identifiers retain
their numbers. The missing marker is reported and the affected section carries
`source_marker_gap_after`; no missing identifier or text is invented.

`qa_sample.json` contains ten representative local chunks per selected book.
`retrieval_cases.json` contains source quotes, pages and expected content hashes;
it is a prepared test set, not a claim that live retrieval quality was evaluated.
Retrieval of historical homeopathic material does not establish clinical efficacy.

Persistent outputs include `pdf_inventory.json`, `chunking_report.json`,
`embedding_usage.json`, `ingestion_progress.json`, `ingestion_summary.md`,
and source/plan/sample artifacts. Byte coverage excludes overlap and counts
only source slices; billed/reported embedding tokens are tracked separately.
The coding agent's context/token usage is unavailable from this runtime.

## Offline checks

```powershell
uv run --offline --no-sync pytest --basetemp .pytest_tmp_ingestion
uv run --offline --no-sync ruff check app tests
```

Fault-injection tests cover interrupted provider requests, quota errors,
Retry-After, dynamic batches, database failures, lost database acknowledgements,
durable budgets, cached-vector reuse and duplicate-free restarts. Live storage verification passed against project `ivlmduwdkwgrxqxjjuyg`: a synthetic 1024-dimensional vector and a remote job checkpoint were written and read back, then the synthetic fixture was removed. The representative Organon sample also passed a restart with zero extra provider requests. Local migration filenames match the versions recorded by the Supabase migration service.

Documentation checked: [MongoDB client routing](https://www.mongodb.com/docs/voyageai/api-and-clients/),
[tokenization](https://www.mongodb.com/docs/voyageai/tutorials/tokenization/),
[trial rate limits](https://www.mongodb.com/docs/voyageai/api-reference/overview/),
[Supabase upserts](https://supabase.com/docs/reference/python/upsert),
and Context7's current PyMuPDF and LangChain splitter references.


## Expanded eight-book run

The user added five PDFs and reported a total original free allowance of
1000000 tokens. The expanded run uses a **cumulative 900000-token cap**, including
all previously recorded API usage, with a 100000-token reserve. This is a
pipeline guard, not a claim about the provider's remaining account balance.
Usage outside this pipeline is not observable here.

The current queue includes all seven suitable PDFs, in source-token order,
while Kent's Repertory retains its original explicit exclusion. Existing vectors
and checkpoints are reused. The two Hartman books passed review: most flagged
pages were padded contents/index pages, and image-only pages were blank except
for a handwritten ownership note. Those images are retained in the originals.
Synoptic Materia Medica uses large-font remedy headings rather than treating
capitalized symptom fragments as remedy names.

```powershell
# Initial expanded inventory and authorized run.
uv run --offline --no-sync python -u -m app.ai.ingestion --live --include-added-books --max-run-embedding-tokens 900000

# Resume the saved selection without adding any further files or resetting usage.
uv run --offline --no-sync python -u -m app.ai.ingestion --live --max-run-embedding-tokens 900000
```

`run_manifest.json` records scope and budget. `expanded_live_run.log` records each
committed batch. A completion follow-up watches the same run; it must not start
a second process while the OS lock is held or retry an ambiguous provider call.
The final report is `ingestion_summary.md`, backed by the JSON reports and the
FULL-synchronous SQLite journal. Stop on budget, quota/payment rejection, or an
error that cannot safely resume. Never buy credits or raise the cap automatically.
