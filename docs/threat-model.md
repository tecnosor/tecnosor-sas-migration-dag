# Threat model

SASsessment processes sensitive SAS estate material including source code,
runtime logs, data dictionaries, and database metadata. This document
identifies threats and the mitigations implemented in the foundation.

## Prompt injection in documents and SAS comments

**Threat**: Malicious content in SAS source files, log files, or data
dictionaries could attempt to inject instructions into the LLM prompt when
an opencode agent node processes the material.

**Mitigation**:

- Agent prompts in `src/sassessment/prompts.py` include explicit instructions
  to ground statements in state and never modify files outside the execution
  directory.
- The system prompt instructs the model to treat all input as data, not
  instructions.
- Node handlers are deterministic Python code that does not pass raw file
  content directly to the LLM without structuring it first.
- The result envelope validation rejects output that does not conform to
  the expected schema.

**Residual risk**: A sufficiently sophisticated prompt injection could
still influence the LLM's analysis. The quality gate checks evidence
traceability to catch fabricated findings.

## Malicious archives (path traversal, symlink escapes)

**Threat**: A crafted zip or tar archive could contain entries with absolute
paths, `..` traversal, or symlinks pointing outside the extraction directory.

**Mitigation**:

The `safe_extract()` function in `src/sassessment/intake/staging.py` enforces:

- Absolute paths are rejected.
- Members with `..` in their path are rejected (`PathTraversalError`).
- Symlink and hardlink entries pointing outside the destination are rejected
  (`SymlinkEscapeError`).
- Encrypted zip entries are rejected.
- Device-like tar members are rejected.
- On any suspected danger, the archive is moved to `intake/quarantine/` with
  a `.quarantine.txt` explanation file.

Tests in `tests/test_intake.py` verify traversal and symlink escape detection.

## Command injection

**Threat**: User-controlled input (file names, batch ids, prompt content)
could be injected into shell commands.

**Mitigation**:

- All subprocess calls use `subprocess.run(argv, shell=False)` with explicit
  argv arrays. No shell string concatenation.
- The `OpenCodeAdapter` in `src/sassessment/opencode_adapter/adapter.py`
  constructs argv lists directly. The test
  `test_no_shell_injection_in_argv` in `tests/test_adapter.py` verifies
  that hostile input is passed as a single argv element, not interpreted
  by a shell.
- File paths are resolved through `pathlib.Path` operations, not string
  interpolation into commands.

## Secret leakage and redaction

**Threat**: Passwords, API keys, tokens, or private keys in source material
or configuration could leak into logs, audit trails, or persisted state.

**Mitigation**:

The `Redactor` class in `src/sassessment/state/events.py` applies configurable
regex patterns to all audit events before persistence:

```python
patterns = [
    r'(?i)(password|passwd|pwd)\s*[=:]\s*\S+',
    r'(?i)(api[_-]?key|apikey)\s*[=:]\s*\S+',
    r'(?i)(secret|token|credential)[a-z_]*\s*[=:]\s*\S+',
    r'(?i)bearer\s+[A-Za-z0-9._\-]+',
    r'(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----',
]
```

The redactor is applied at the `AuditEmitter` level, so all audit events
(JSONL and SQLite) are redacted before writing. Sensitive dictionary keys
(password, secret, token, etc.) are also redacted by key name.

Additional patterns can be added via `config/default.yaml` (`redaction.patterns`)
or the `SASSESSMENT_REDACTION_PATTERNS` environment variable.

## Hallucinated evidence references

**Threat**: An LLM agent could claim to have used evidence that does not
exist in state, making fabricated findings appear grounded.

**Mitigation**:

The `build_result_from_envelope()` function in
`src/sassessment/opencode_adapter/envelope.py` validates every evidence
reference:

```python
unknown_refs = [
    ev for ev in envelope.evidence_used if not context.repo.get_evidence(ev)
]
if unknown_refs:
    raise ResultValidationError(
        "evidence references not found in state (possible hallucination)",
        details={"unknown": unknown_refs})
```

The envelope is rejected entirely if any evidence id is not found in the
`evidence` table. This prevents fabricated references from entering the state.

## Unauthorized connector use

**Threat**: Connectors to live systems (database, GitLab, Confluence) could
be used without explicit human approval.

**Mitigation**:

- All connectors are disabled by default in `config/default.yaml`:
  ```yaml
  connectors:
    enabled:
      database: false
      gitlab: false
      confluence: false
      sas_metadata: false
    approval_policy: explicit
  ```
- The `approval_policy: explicit` setting requires human approval before
  any connector access, even if enabled.
- Connectors are optional. The foundation operates in file-first offline
  mode without any connector.

## State corruption

**Threat**: Concurrent writes, crashes, or bugs could corrupt the SQLite
database or workspace state.

**Mitigation**:

- **Transactions**: Multi-row mutations use `BEGIN IMMEDIATE` transactions
  via `Database.transaction()`. This prevents write conflicts.
- **WAL mode**: `PRAGMA journal_mode=WAL` allows concurrent reads during
  writes and provides crash recovery.
- **Checkpoint immutability**: Checkpoints are created with
  `mkdir(exist_ok=False)` to prevent overwrites. The manifest includes
  SHA-256 hashes of the database and all protected workspace members.
  Restoration verifies hashes before replacing live state.
- **Append-only audit**: The JSONL audit trail is append-only. The SQLite
  `audit_events` table uses `INSERT OR IGNORE` to prevent duplicate events.

## Concurrent execution conflicts

**Threat**: Multiple processes or threads could attempt to mutate state
simultaneously.

**Mitigation**:

- SQLite `BEGIN IMMEDIATE` acquires a reserved lock at transaction start,
  preventing other writers from beginning until the transaction completes.
- `PRAGMA busy_timeout=30000` retries on lock contention for up to 30 seconds.
- The `human_requests` table has a partial UNIQUE index on
  `(assessment_id, node_id, missing_info) WHERE status = 'OPEN'` to prevent
  duplicate open requests even under concurrent insertion.
- The engine is designed for single-writer operation. Concurrent graph
  execution is not supported in v1.

## Infinite graph cycles

**Threat**: A misconfigured graph with circular edges could cause infinite
execution loops.

**Mitigation**:

- The `GraphEngine` tracks a global cycle counter. When it exceeds
  `limits.max_graph_cycles` (default 25), the engine raises
  `CycleLimitExceededError`.
- Each node has `max_attempts` (default 5). After exhaustion, the node
  stays FAILED and no further transitions fire from it.
- The graph JSON has a `max_cycles` field (foundation graph sets 40) as
  an additional guard.
- The `next_runnable()` method only selects nodes in READY or PENDING status,
  preventing re-execution of SUCCEEDED nodes.

## Unbounded context and token consumption

**Threat**: An opencode agent node could consume unbounded tokens by
including excessive state in the prompt or generating verbose output.

**Mitigation**:

- The `_slim_state()` function in `src/sassessment/prompts.py` limits the
  state passed to the LLM: lists are capped at 200 elements, and only
  simple types and small collections are included.
- The `opencode.max_output_bytes` setting (default 1 MiB) caps captured
  output per stream.
- The `--dry-run` flag on `sassessment run` shows what would be executed
  without actually invoking the LLM, allowing operators to inspect the
  plan before committing tokens.
- Node handlers can set `limitations` in their result to indicate when
  analysis was truncated or incomplete.

## Never execute discovered code

**Critical rule**: SAS, SQL, shell, macros, and ETL logic found in inputs
is treated as data, not something to run. The system never executes
discovered code automatically.

- The `sas.discover` node uses regex parsers to extract structural
  information (table references, macro definitions, data steps) without
  executing the SAS code.
- The `runtime.correlate` node parses log files for process events without
  executing any discovered scripts.
- SQL query packs in human requests are written to files for the human
  to run, not executed by the system.

This rule is enforced by design: no node handler includes code execution
logic. The foundation graph contains no nodes that run discovered SAS,
SQL, or ETL code.
