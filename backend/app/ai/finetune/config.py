"""Configuration for the independent fine-tuning dataset module.

This module is deliberately separate from the RAG pipeline. It only reads the
``knowledge_*`` tables, never selects embeddings or raw book text, and writes
datasets to a local folder that is excluded from Git and from the production
database.
"""

from __future__ import annotations

from pathlib import Path

from app.core.paths import data_dir

MODULE_VERSION = "finetune-v1"
POLICY_VERSION = "pd-basis-v1"

# Local, Git-ignored output. Never inside the Supabase project or the API routes.
DATASET_ROOT = data_dir() / "datasets" / "finetune"

LICENCE_REGISTRY_PATH = Path(__file__).with_name("licence_registry.json")

# The only tables this module may read. Patient, case and clinical tables are
# deliberately absent and must never be added here.
READABLE_TABLES = frozenset({"knowledge_books", "knowledge_chunks", "knowledge_sections"})

# Columns that must never leave the database through this module.
FORBIDDEN_COLUMNS = frozenset({"embedding", "raw_text"})

BOOK_COLUMNS = (
    "id",
    "title",
    "author",
    "publisher",
    "publication_year",
    "language",
    "category",
    "source_filename",
    "source_uri",
    "content_hash",
    "section_count",
    "chunk_count",
)

CHUNK_COLUMNS = (
    "id",
    "book_id",
    "section_id",
    "chunk_index",
    "content",
    "content_hash",
    "token_count",
    "metadata",
)

SECTION_COLUMNS = (
    "id",
    "book_id",
    "ordinal",
    "heading",
    "path",
    "section_type",
    "page_start",
    "page_end",
)

READ_PAGE_SIZE = 500

# Book-level split fractions. Books, never chunks, are split.
TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
TEST_FRACTION = 0.15
SPLIT_SALT = "similia-finetune-v1"

# Cleaning and quality gates.
MIN_CPT_CHARS = 160
MIN_SFT_CHARS = 240
MIN_SFT_WORDS = 35
MIN_ALPHABETIC_RATIO = 0.55
MAX_SFT_ANSWER_CHARS = 2_200

# Pilot dataset target.
PILOT_TARGET = 500
PILOT_MIN_PER_BOOK = 20

# Near-duplicate detection.
NEAR_DUPLICATE_JACCARD = 0.90
NEAR_DUPLICATE_MIN_TOKENS = 50
SHINGLE_SIZE = 5

# CPT document size (characters). Large enough to keep chapter context.
CPT_DOCUMENT_CHARS = 40_000

SAFETY_NOTE = (
    "Historical homeopathic literature. Statements describe the doctrines and "
    "observations of the cited source; they are not established medical evidence "
    "and must not be presented as clinical advice."
)

SCIENTIFIC_BOUNDARY = (
    "Homeopathic remedy indications and provings recorded in this corpus are "
    "historical claims. They are not supported as established clinical evidence "
    "by modern controlled research. Answers must attribute the claim to the "
    "source and must not assert therapeutic efficacy."
)

SFT_SYSTEM_PROMPT = (
    "You are a careful research assistant working with a digitised corpus of "
    "historical homeopathic literature. Answer only from the supplied source "
    "passage, quote it faithfully, and always name the book, author and page. "
    "Treat every remedy indication, proving and clinical anecdote as a "
    "historical claim of the cited author, not as established medical evidence. "
    "Never give medical advice. If the source does not support an answer, say so."
)
