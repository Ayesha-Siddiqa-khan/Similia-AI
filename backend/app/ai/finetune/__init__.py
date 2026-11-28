"""Independent fine-tuning dataset preparation for Similia AI.

The module reads the existing knowledge base in read-only mode, applies a
licence gate, cleans and deduplicates text, builds book-level splits, and
writes separate CPT and SFT datasets locally. It never touches embeddings,
patient data or the production database schema.
"""

from app.ai.finetune.claims import classify_claim
from app.ai.finetune.cleaning import clean_chunk_text, score_text
from app.ai.finetune.config import DATASET_ROOT, PILOT_TARGET
from app.ai.finetune.dedupe import find_duplicates
from app.ai.finetune.licensing import decision_for, partition_books
from app.ai.finetune.pipeline import run_export, verify_export
from app.ai.finetune.reader import ReadOnlyKnowledgeReader, ReadOnlyViolation
from app.ai.finetune.splits import assign_splits, split_manifest

__all__ = [
    "DATASET_ROOT",
    "PILOT_TARGET",
    "ReadOnlyKnowledgeReader",
    "ReadOnlyViolation",
    "assign_splits",
    "classify_claim",
    "clean_chunk_text",
    "decision_for",
    "find_duplicates",
    "partition_books",
    "run_export",
    "score_text",
    "split_manifest",
    "verify_export",
]
