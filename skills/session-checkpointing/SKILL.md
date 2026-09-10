---
name: session-checkpointing
description: Create and restore assessment checkpoints with database snapshots and manifest records.
---

# Session Checkpointing

Create assessment checkpoints that capture the full state at a point in time. Support restoration from checkpoints.

## Purpose

Provide durable checkpoints of assessment state for recovery, audit, and handoff between sessions.

## Inputs

- Active assessment ID.
- Current database state (`workspace/database/sassessment.db`).
- Current workspace state (all subdirectories).

## Outputs

- Checkpoint record in `checkpoints` table.
- Checkpoint directory at `workspace/checkpoints/<checkpoint-id>/`.
- Manifest file listing all state components.
- Database snapshot (copy or backup).
- Audit event: `checkpoint.created`.

## Steps

1. Generate a checkpoint ID.
2. Create checkpoint directory at `workspace/checkpoints/<checkpoint-id>/`.
3. Copy the current database file to the checkpoint directory.
4. Generate a manifest listing all workspace files with their SHA-256 hashes.
5. Write the manifest to the checkpoint directory.
6. Compute manifest SHA-256 for integrity verification.
7. Insert checkpoint record via `Repository.create_checkpoint_record()`.
8. Emit audit event.

## Artifacts

- `workspace/checkpoints/<checkpoint-id>/` directory.
- Database snapshot file.
- Manifest file with file hashes.
- Checkpoint record in `checkpoints` table.

## References

- Implementation: `src/sassessment/state/checkpoints.py` `CheckpointManager`.
- CLI: `sassessment checkpoint` command.
- Repository: `src/sassessment/state/repository.py` `create_checkpoint_record()`.
