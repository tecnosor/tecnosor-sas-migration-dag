---
name: safe-archive-staging
description: Safely extract zip/tar archives with path-traversal protection, symlink checks, and quarantine on failure.
---

# Safe Archive Staging

Extract archive files (zip, tar, tar.gz, tgz) with safety guarantees. Quarantine anything suspicious.

## Purpose

Provide safe archive extraction that never writes outside the destination directory, rejects path traversal, and quarantines corrupt or dangerous archives.

## Inputs

- `archive_path` -- path to the archive file (must be under `intake/raw/`).
- `destination` -- extraction target directory (typically `intake/staged/` or a batch subdirectory).
- Optional: `quarantine_dir` -- defaults to `intake/quarantine/`.

## Outputs

- `StagingResult` dataclass with: archive, staged_dir, extracted_files, rejected_entries.
- On failure: archive moved to `intake/quarantine/` with a `.quarantine.txt` reason file.

## Steps

1. Resolve archive path and verify it is a file.
2. Check archive type via `is_archive()` (suffixes: .zip, .tar, .tar.gz, .tgz).
3. Resolve destination and create if needed.
4. For zip archives:
   - Reject encrypted entries (flag bit 0x1).
   - Reject absolute paths and `..` traversal members.
   - Reject symlink/hardlink entries pointing outside destination.
   - Extract each safe member.
5. For tar archives:
   - Reject absolute paths and `..` traversal members.
   - Reject symlink/hardlink entries pointing outside destination.
   - Reject device-like members.
   - Extract each safe member.
6. On any exception: move archive to quarantine directory with reason file.

## Artifacts

- Extracted files in destination directory.
- Quarantine note at `intake/quarantine/<archive-name>.quarantine.txt` on failure.

## References

- Implementation: `src/sassessment/intake/staging.py` (`safe_extract()`).
- Constants: `ARCHIVE_SUFFIXES`, `ZIP_ENCRYPTED_FLAG`.
