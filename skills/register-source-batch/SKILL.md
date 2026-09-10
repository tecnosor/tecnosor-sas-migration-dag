---
name: register-source-batch
description: Register a raw material batch under intake/raw with hashing, manifest generation, and duplicate detection.
---

# Register Source Batch

Register a directory of raw material under `intake/raw/<batch-id>/` with full integrity tracking.

## Purpose

Create a `BatchRegistration` record with per-file SHA-256 hashes, media type classification, duplicate detection, and a YAML manifest in `intake/manifests/`.

## Inputs

- `repo_root` -- repository root path (resolved via `find_repo_root()`).
- `batch_dir` -- directory under `intake/raw/<batch-id>/` containing source files.
- Optional: `provider`, `source_team`, `environment`, `authority_level`, `confidentiality`, `known_omissions`, `batch_id`.

## Outputs

- `BatchRegistration` dataclass with: batch_id, batch_dir, manifest_path, file_count, duplicate_count, integrity_hash.
- YAML manifest at `intake/manifests/<batch-id>.yaml`.
- Database rows in `source_batches` and `source_artifacts`.
- Audit event: `batch.registered`.

## Steps

1. Validate that `batch_dir` lives directly under `intake/raw/` (no nested paths).
2. Iterate all files in the batch directory (recursive, excluding dotfiles).
3. For each file: compute SHA-256, classify media type via `MEDIA_TYPES` registry in `src/sassessment/intake/registration.py`.
4. Detect duplicates: check `source_artifacts` for matching SHA-256.
5. Compute batch-level integrity hash (sorted concatenation of path+hash pairs).
6. Write YAML manifest with `raw_dir`, `files[]` entries.
7. Persist `source_batches` and `source_artifacts` rows via Repository.
8. Emit audit event.

## Artifacts

- `intake/manifests/<batch-id>.yaml`
- Database records in `source_batches`, `source_artifacts`.

## References

- Implementation: `src/sassessment/intake/registration.py` (`register_batch()`).
- Media type registry: `MEDIA_TYPES` dict in `registration.py`.
- Fixture: `examples/synthetic-fixture/sources/` for expected batch structure.
