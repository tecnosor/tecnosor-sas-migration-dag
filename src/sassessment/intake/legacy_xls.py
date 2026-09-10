from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from sassessment.errors import IntakeError

CONVERTER_CANDIDATES = ("soffice", "libreoffice", "ssconvert")
CONVERT_TIMEOUT_SECONDS = 120.0


def find_converter() -> Optional[str]:
    for candidate in CONVERTER_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def convert_xls_to_xlsx(xls_path: Path, out_dir: Path) -> Path:
    """Convert a legacy .xls workbook offline using LibreOffice/Gnumeric.

    argv-array subprocess only, constrained working dir, timeout enforced.
    Returns the produced .xlsx path. Raises IntakeError on failure.
    """
    converter = find_converter()
    if not converter:
        raise IntakeError(
            "no .xls converter available (LibreOffice/Gnumeric not installed); "
            "convert the workbook manually to .xlsx or csv")
    out_dir.mkdir(parents=True, exist_ok=True)
    if converter.endswith("ssconvert"):
        argv = [converter, str(xls_path), str(out_dir / (xls_path.stem + ".xlsx"))]
    else:
        argv = [converter, "--headless", "--convert-to", "xlsx",
                "--outdir", str(out_dir), str(xls_path)]
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=CONVERT_TIMEOUT_SECONDS,
            check=False,
            shell=False,
            cwd=str(out_dir),
        )
    except subprocess.TimeoutExpired as exc:
        raise IntakeError(f"xls conversion timed out after {CONVERT_TIMEOUT_SECONDS}s") from exc
    expected = out_dir / (xls_path.stem + ".xlsx")
    if not expected.is_file():
        detail = proc.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise IntakeError(f"xls conversion produced no file; detail: {detail or 'none'}")
    return expected


def is_legacy_xls(path: Path) -> bool:
    with path.open("rb") as handle:
        head = handle.read(8)
    return head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
