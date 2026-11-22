import type { BookProgress, ChunkPage, Snapshot } from "@/features/workspace/types";

const demo: BookProgress = {
  file_hash: "a".repeat(64), filename: "demonstration-organon.pdf", title: "Demonstration · Organon", category: "organon",
  pdf_bytes: 240000, text_bytes: 62000, total_pages: 24, original_tokens: 14000, selected: true,
  status: "paused", generated_chunks: 40, stored_vectors: 28, remaining_chunks: 12,
  processed_source_text_bytes: 42000, unique_source_tokens_processed: 9600,
  provider_reported_embedding_tokens: 10200, successful_api_requests: 3, failed_api_requests: 1,
  completion_percent: 70, current_checkpoint: { book_id: "demo-organon", last_part: 1, last_page: 17, last_section: "§28", last_stored_chunk: "demo-chunk-28", timestamp: "2026-10-30T12:00:00Z", error: "Demonstration: HTTP 429 — processing paused; checkpoint retained." }, parts: [],
  minimum_chunk_tokens: 80, maximum_chunk_tokens: 490, average_chunk_tokens: 350, median_chunk_tokens: 340,
};
export const fixtureSnapshot: Snapshot = {
  timestamp: "2026-10-30T12:00:00Z", status: "fixture_preview",
  books: [demo, { ...demo, file_hash: "b".repeat(64), filename: "demonstration-materia-medica.pdf", title: "Demonstration · Materia Medica", category: "materia_medica", status: "completed", stored_vectors: 40, remaining_chunks: 0, completion_percent: 100, current_checkpoint: { book_id: "demo-materia", last_part: 1, last_page: 24, last_stored_chunk: "demo-mm-40" }, failed_api_requests: 0 }],
  inventory: [demo, { ...demo, file_hash: "b".repeat(64), filename: "demonstration-materia-medica.pdf", category: "materia_medica" }],
  usage: { provider_reported_tokens: 20400, budget_charged_tokens: 20400, successful_requests: 6, failed_requests: 1, ambiguous_requests: 0, unknown_usage_reserved_tokens: 0, embedding_model: "voyage-4-lite", embedding_dimensions: 1024 },
  budget: 900000, reserve: 100000, capabilities: { analyse: false, start: false, pause: false, resume: false, retry: false, category_update: false },
  control_reason: "Demonstration only. Live processing controls require budget-safe backend endpoints.", source: "synthetic_fixtures",
};
export const fixtureChunks: ChunkPage = {
  total: 3, offset: 0, limit: 25, statistics: { minimum_chunk_tokens: 18, maximum_chunk_tokens: 32, average_chunk_tokens: 24, median_chunk_tokens: 22 },
  items: [
    { chunk_index: 0, content: "Synthetic passage for interface testing. A practitioner records the presenting concern and requests additional information before review.", token_count: 22, byte_count: 143, embedding_status: "stored", metadata: { section: "Demonstration section", page_start: 2, page_end: 2, aphorism: "DEMO-1" } },
    { chunk_index: 1, content: "Synthetic passage: observations are organized by time, context and the patient's description. This is not clinical guidance.", token_count: 32, byte_count: 124, embedding_status: "pending", metadata: { section: "Demonstration observations", page_start: 3, page_end: 3, remedy: "Demo remedy" } },
    { chunk_index: 2, content: "Synthetic repertory entry for search and layout testing only.", token_count: 18, byte_count: 59, embedding_status: "pending", metadata: { section: "Demonstration rubric", page_start: 4, page_end: 4, rubric_path: ["Demo chapter", "Demo rubric"] } },
  ],
};
