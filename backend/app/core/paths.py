"""Filesystem locations that differ between a source checkout and an installed app.

The desktop launcher sets ``SIMILIA_DATA_DIR`` to the per-user application data
folder. Development keeps the historical repository-relative layout.
"""

import os
from pathlib import Path


def data_dir() -> Path:
    """Writable application data root (never the read-only install directory)."""
    configured = os.environ.get("SIMILIA_DATA_DIR", "").strip()
    if configured:
        return Path(configured)
    # backend/app/core/paths.py -> repository root in a source checkout.
    return Path(__file__).resolve().parents[3]
