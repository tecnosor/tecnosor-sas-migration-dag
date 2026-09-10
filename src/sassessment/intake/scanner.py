from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from sassessment.errors import IntakeError
from sassessment.workspace.layout import INTAKE_RAW


def scan_batches(repo_root: Path) -> List[Path]:
    """Discover candidate batch directories directly under intake/raw/."""
    raw_root = repo_root / INTAKE_RAW
    if not raw_root.is_dir():
        raise IntakeError(f"missing intake raw directory: {raw_root}")
    candidates: List[Path] = []
    for entry in sorted(raw_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name == ".gitkeep":
            continue
        candidates.append(entry)
    return candidates


def files_in_batch(batch_dir: Path) -> List[Path]:
    if not batch_dir.is_dir():
        raise IntakeError(f"not a batch directory: {batch_dir}")
    return [path for path in sorted(batch_dir.rglob("*")) if path.is_file() and not path.name.startswith(".")]
