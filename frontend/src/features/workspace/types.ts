export type Category = "materia_medica" | "repertory" | "organon" | "general";
export interface InventoryBook {
  file_hash: string; filename: string; title?: string; author?: string; category: Category;
  pdf_bytes?: number; text_bytes?: number; total_pages?: number; original_tokens?: number; selected: boolean; priority?: number | null;
}
export interface Checkpoint {
  book_id?: string; job_id?: string; last_part?: number; last_page?: number;
  last_section?: string; last_stored_chunk?: string; timestamp?: string; error?: string | null;
}
export interface Part {
  part: number; stored_chunks: number; chunk_start: number; chunk_end: number;
  page_start: number; page_end: number; checkpoint: Checkpoint;
}
export interface BookProgress extends InventoryBook {
  status: string; generated_chunks: number; stored_vectors: number; remaining_chunks: number;
  processed_source_text_bytes: number; unique_source_tokens_processed: number;
  provider_reported_embedding_tokens: number; successful_api_requests: number; failed_api_requests: number;
  completion_percent: number; current_checkpoint: Checkpoint; parts: Part[];
  minimum_chunk_tokens?: number; maximum_chunk_tokens?: number; average_chunk_tokens?: number; median_chunk_tokens?: number;
}
export interface Usage {
  provider_reported_tokens: number; budget_charged_tokens: number; successful_requests: number;
  failed_requests: number; ambiguous_requests: number; unknown_usage_reserved_tokens: number;
  embedding_model?: string; embedding_dimensions?: number; voyage_sdk_version?: string;
}
export interface Snapshot {
  timestamp: string; status: string; inventory: InventoryBook[]; books: BookProgress[]; usage: Usage;
  budget: number; reserve: number; required_action?: string; provider_paused?: boolean;
  capabilities: Record<"analyse" | "start" | "pause" | "resume" | "retry" | "category_update", boolean>;
  control_reason: string; source: string;
}
export interface RegisteredBook {
  id: string; title: string; source_filename: string; category: Category; author: string | null;
  section_count: number; chunk_count: number; metadata: Record<string, unknown>;
}
export interface Chunk {
  chunk_index: number; content: string; token_count: number; byte_count: number;
  embedding_status: string; metadata: Record<string, unknown>;
}
export interface ChunkPage {
  items: Chunk[]; total: number; offset: number; limit: number;
  statistics: Record<string, number | null>;
}
export interface Passage {
  chunk_id: string; book_id: string; book_title: string; book_category: string;
  section_heading: string | null; content: string; similarity: number;
  metadata: Record<string, unknown>; section_path: string[];
  book_author?: string | null; page_start?: number | null; page_end?: number | null; book_complete?: boolean; retrieval_mode?: "semantic" | "keyword" | "hybrid"; matched_by?: string[];
}
export interface SearchResult { query: string; k: number; latency_ms: number; results: Passage[]; incomplete_books?: string[]; retrieval_mode?: "semantic" | "keyword" | "hybrid"; requested_mode?: "semantic" | "keyword" | "hybrid"; fallback_reason?: string | null }
export interface BookIndexStats {
  book_id: string; title: string; category: string; source_filename: string; total_pages: number | null;
  total_chunks: number; embedded_chunks: number; pending_chunks: number; embedded_tokens: number; pending_tokens: number;
  prepared: boolean; complete: boolean; frozen_plan: boolean;
}
export interface IngestionOverview { books: BookIndexStats[] }
