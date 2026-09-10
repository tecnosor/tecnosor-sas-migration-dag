# State and persistence

SASsessment uses dual persistence: a SQLite database as the queryable index
and JSONL/YAML sidecars as human-readable, append-only records.

## SQLite schema v1

The initial migration lives at
`src/sassessment/state/migrations/V001__initial.sql`. It creates 19 tables:

| Table | Purpose |
|-------|---------|
| `assessments` | top-level assessment records (id, name, subsidiary, status, current_phase) |
| `source_batches` | registered intake batches (batch_dir, integrity_hash, manifest_path) |
| `source_artifacts` | individual files within batches (sha256, media_type, parser_status) |
| `evidence` | registered evidence items (kind, title, locator, confidence) |
| `sessions` | assessment sessions (status OPEN/CLOSED, started_at, closed_at) |
| `node_states` | per-node status within an assessment (status, attempts, cycles) |
| `executions` | individual node executions (attempt, status, duration_ms, prompt_hash, model) |
| `human_requests` | human input requests (priority, status, destination_batch, resume_node) |
| `findings` | analysis findings (statement, category, confidence, version, superseded_by) |
| `decisions` | routing and analysis decisions (selected_route, rationale, confidence) |
| `assumptions` | recorded assumptions (statement, rationale, status) |
| `risks` | identified risks (statement, severity, mitigation, status) |
| `gaps` | knowledge gaps (description, phase, status) |
| `checkpoints` | checkpoint metadata (manifest_path, db_snapshot_path, manifest_sha256) |
| `audit_events` | indexed audit trail (seq, event_id, action, actor_type, details_json) |
| `data_objects` | discovered data objects (object_type, schema_name, normalized_name) |
| `lineage_edges` | lineage relationships (source_node, target_node, relationship, confidence) |
| `meta` | key-value store for engine metadata (active_assessment, batch registration flags) |
| `schema_migrations` | applied migration versions |

### Key constraints

- `source_batches.batch_dir` is UNIQUE.
- `source_artifacts` has UNIQUE on `(batch_id, relative_path)`.
- `data_objects` has UNIQUE on `(assessment_id, object_type, normalized_name)`.
- `lineage_edges` has UNIQUE on `(assessment_id, source_node, target_node, relationship)`.
- `human_requests` has a partial UNIQUE index on
  `(assessment_id, node_id, missing_info) WHERE status = 'OPEN'` to prevent
  duplicate open requests for the same missing information.
- `audit_events.event_id` is UNIQUE.

## Transactional transitions

The `Database` wrapper in `src/sassessment/state/database.py` configures:

- `PRAGMA journal_mode=WAL` for concurrent read access during writes.
- `PRAGMA foreign_keys=ON` for referential integrity.
- `PRAGMA busy_timeout=30000` for retry on lock contention.
- `PRAGMA synchronous=NORMAL` for balanced durability.

Multi-row mutations use `BEGIN IMMEDIATE` transactions via the
`Database.transaction()` context manager. This prevents write conflicts
when multiple code paths attempt concurrent mutations.

## State kinds

| Kind | Storage | Description |
|------|---------|-------------|
| project | `workspace/project/` | assessment-level metadata sidecars |
| session | `sessions` table | execution sessions with OPEN/CLOSED status |
| execution | `executions` table + `workspace/executions/<EXE-id>/` | per-node run artifacts |
| checkpoint | `checkpoints` table + `workspace/checkpoints/<CKP-id>/` | immutable snapshots |
| specialist | `findings`, `decisions`, `gaps`, `assumptions`, `risks` tables | analysis outputs |
| domain | `data_objects`, `lineage_edges` tables | discovered SAS estate objects |

## Execution status lifecycle

```
PENDING --> READY --> RUNNING --> SUCCEEDED
                           |-> FAILED
                           |-> WAITING_FOR_INPUT
                           |-> WAITING_FOR_APPROVAL
                           |-> CANCELLED
                           |-> SKIPPED
                           |-> SUPERSEDED
```

| Status | Meaning |
|--------|---------|
| `PENDING` | not yet eligible to run |
| `READY` | eligible, waiting for engine selection |
| `RUNNING` | currently executing |
| `WAITING_FOR_INPUT` | blocked on human request |
| `WAITING_FOR_APPROVAL` | blocked on human approval |
| `SUCCEEDED` | completed successfully |
| `FAILED` | completed with error |
| `CANCELLED` | explicitly cancelled |
| `SUPERSEDED` | replaced by a newer execution |
| `SKIPPED` | not executed (condition not met) |

Both `node_states.status` and `executions.status` use this same set of values,
defined in `src/sassessment/state/repository.py`.

## JSONL audit + SQLite index

Every mutation emits an audit event through `AuditEmitter.emit()`:

1. The event is redacted by `Redactor` (configurable regex patterns).
2. A JSON line is appended to `workspace/audit/sassessment.jsonl`.
3. The same event is inserted (INSERT OR IGNORE) into `audit_events`.

The JSONL file is the authoritative sequence. SQLite is a queryable index.
Both writes occur before `emit()` returns.

## Immutable checkpoints

`CheckpointManager` in `src/sassessment/state/checkpoints.py`:

- **Create**: backs up the SQLite database to
  `workspace/checkpoints/<CKP-id>/state.db`, hashes every protected workspace
  member (project, decisions, findings, requests, evidence, assumptions, risks,
  gaps), writes a `manifest.yaml` with SHA-256 digests, and records the
  checkpoint in the `checkpoints` table.
- **Verify**: re-hashes the manifest and every member. Any mismatch is
  reported without modifying live state.
- **Restore**: verifies first, then replaces the live database from the
  snapshot. Aborts on any hash mismatch.

Checkpoint directories are created with `mkdir(exist_ok=False)` to prevent
accidental overwrites. The manifest includes `"immutable": true`.

## Recovery rules

SQLite is not the only way to recover state:

- The JSONL audit trail can reconstruct the event sequence independently.
- Checkpoint snapshots provide full database restoration.
- YAML manifests in `intake/manifests/` record batch registrations.
- Workspace sidecars under `workspace/decisions/`, `workspace/findings/`, etc.
  provide human-readable records alongside the database.

If the database is lost, re-running `sassessment init` creates a fresh
database. Batch manifests and audit JSONL remain intact on disk.
