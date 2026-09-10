# Architectural Decision Records

## ADR-001 Python 3.9 stdlib-first

- **Context**: corporate runtime offers system Python 3.9.6 (with pytest 8.4.2
  and PyYAML 6.0.3 preinstalled) plus homebrew 3.14 without either library.
- **Decision**: target 3.9-compatible stdlib code; dependencies limited to
  PyYAML (runtime) and pytest (dev).
- **Alternatives**: require 3.14 (breaks local runtime); add pydantic/jsonschema
  (unnecessary).
- **Consequences**: typing guarded by `typing.Optional`/`List`; no `match`
  statements; no PEP 604 unions at runtime.

## ADR-002 src layout

`src/sassessment/` with setuptools packaging; console script
`sassessment = sassessment.cli.main:main`; pytest `pythonpath=["src"]`.

## ADR-003 dual persistence

SQLite is the transactional index (WAL, FK, `BEGIN IMMEDIATE`); JSONL audit is
the authoritative append-only sequence; YAML/MD sidecars keep human-readable
control. SQLite must never be the sole recovery path (reconstruction from
files is possible without chat history).

## ADR-004 SQL-file migrations

`src/sassessment/state/migrations/V*.sql` applied by `Migrator` with a
`schema_migrations` table. Note: `executescript` commits implicitly, so the
migration script runs outside the wrapping transaction and the version bookkeep
commits separately.

## ADR-005 redaction at the audit emitter

`Redactor` (regex patterns + sensitive dict keys) applies BEFORE both the JSONL
append and the SQLite insert in `AuditEmitter.emit`. Slightly noisier events
are accepted over leakage risk.

## ADR-006 idempotency by design

- human_requests: unique partial index `(assessment_id, node_id, missing_info)
  WHERE status='OPEN'` prevents duplicate DBA requests.
- audit_events: `INSERT OR IGNORE` on unique `event_id`.
- lineage_edges: `UNIQUE (assessment_id, source, target, relationship)`.
- source_artifacts: duplicate detection by sha256 (`duplicate_of`).
- batch registration: idempotent per `batch_dir`.

## ADR-007 named deterministic predicates

Routing uses only registered predicates (`always`, `node_succeeded`,
`phase_at_least`, `request_resolved`, ...). LLM/prose evaluation is not allowed
in v1. Decisions (which predicate fired, route chosen, rationale) are persisted
in `decisions`.

## ADR-008 mock adapter fallback

`create_adapter` returns a `MockAdapter` when the CLI is missing
(`opencode.executable: mock` forces it). Envelope contract identical, so
offline demos/tests pass without OpenCode installed.

## ADR-009 chat history is supplementary

OpenCode session/rehydrate data is recorded (`executions.opencode_session_id`,
`invocation.json`) but SQLite + sidecars remain authoritative for state.

## ADR-010 file-first offline operation

Default mode is disconnected: local batches, DBA exports, dictionaries.
Connectors (`connectors.enabled`) are all `false` by default and gated by
`approval_policy: explicit`.

## ADR-011 human-in-the-loop as persisted requests

Requests carry destination batches under `intake/raw/req-<request-id>/`
(created by `NodeContext.request_human_input`), a generated query pack, and a
resume node. Answering requires non-REQUEST/non-query-pack files in the batch;
the answer flow resolves the request, marks the waiting node SUCCEEDED and the
resume node READY, and equires a result-batch manifest.

## Rejected alternatives

- **JSON Schema dependency for envelope validation**: typed Python validation
  plus explicit problem lists proved sufficient and stays dependency-light.
- **Generic workflow frameworks** (Airflow etc.): far too heavy; the assessment
  lifecycle needs deterministic, auditable, resumable but small machinery.
- **Storing raw files in SQLite**: violates size and recoverability aims; raw
  stays on disk immutable with hash manifests.
