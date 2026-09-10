# Operator guide

This guide covers daily operation of SASsessment: initialization, file
placement, graph execution, request handling, checkpointing, and audit
export.

## Daily workflow

```
init -> place files -> scan-inputs -> start -> show blockers
  -> answer requests -> resume -> checkpoint -> review -> export-audit
```

### 1. Initialize

```bash
sassessment init
# workspace: /path/to/SAS
# database:  /path/to/SAS/workspace/database/sassessment.db
# graph:     foundation-graph.json v1.0.0
# assessment: ASMT-20260910-1a2b3c4d
# phase:     phase0
```

This creates the workspace scaffold, applies database migrations, and
creates the first assessment if none exists.

### 2. Place files

Place source material in `intake/raw/<source-batch-id>/`:

```bash
mkdir -p intake/raw/BAT-sas-export-2026Q1
cp *.sas intake/raw/BAT-sas-export-2026Q1/
cp scheduler_export.log intake/raw/BAT-sas-export-2026Q1/
cp data_dictionary.csv intake/raw/BAT-sas-export-2026Q1/
```

Or use `add-input` for convenience:

```bash
sassessment add-input /path/to/export.csv
```

### 3. Scan inputs

```bash
sassessment scan-inputs
# NEW: intake/raw/BAT-sas-export-2026Q1
```

This lists batch directories under `intake/raw/` and shows whether each
has been registered.

### 4. Start the graph

```bash
sassessment start
# sys.workspace: SUCCEEDED workspace valid
# intake.register: SUCCEEDED batch registration complete
# intake.coverage: SUCCEEDED coverage assessment complete
# sas.discover: SUCCEEDED discovered 2 SAS processes, 5 data objects
# runtime.correlate: SUCCEEDED correlated 1 process with runtime evidence
# doc.map_apps: SUCCEEDED mapped 3 tables to applications
# lineage.dba_request: WAITING_FOR_INPUT Oracle all_dependencies export not supplied
```

The engine runs nodes until blocked. Nodes that succeed are not re-run.

### 5. Show blockers

```bash
sassessment status
# assessment ASMT-20260910-1a2b3c4d phase=phase4
# nodes:
#   [+] sys.workspace              SUCCEEDED
#   [+] intake.register            SUCCEEDED
#   [+] intake.coverage            SUCCEEDED
#   [+] sas.discover               SUCCEEDED
#   [+] runtime.correlate          SUCCEEDED
#   [+] doc.map_apps               SUCCEEDED
#   [|] lineage.dba_request        WAITING_FOR_INPUT
#   [ ] lineage.ingest_dba         NOT-RUN
#   [ ] quality.gate               NOT-RUN
#   [ ] audit.export               NOT-RUN
# blockers:
#   - lineage.dba_request: waiting for human input: Oracle all_dependencies export not supplied
# open requests:
#   - REQ-20260910-abcdef12 [REQUIRED_FOR_CONFIDENCE] Oracle all_dependencies export not supplied
#       destination: intake/raw/req-20260910-abcdef12
```

### 6. Answer requests

Place the requested files in the destination batch:

```bash
cp all_dependencies_export.csv intake/raw/req-20260910-abcdef12/
```

Answer the request:

```bash
sassessment answer REQ-20260910-abcdef12
# request REQ-20260910-abcdef12 resolved; resume branch ready at lineage.ingest_dba
```

### 7. Resume

```bash
sassessment start
# lineage.ingest_dba: SUCCEEDED ingested DBA export, 3 lineage edges
# quality.gate: SUCCEEDED quality gate passed
# audit.export: SUCCEEDED exported 42 events
```

The engine picks up from the resume node and continues to completion.

### 8. Checkpoint

```bash
sassessment checkpoint
# checkpoint created: CKP-20260910-7q8r9s0t
```

Creates an immutable snapshot of the database and workspace state.

### 9. Review

```bash
sassessment review
# findings: 8
#   - FND-20260910-abcdef01 [CONFIRMED] Material batch BAT-... ingested
#   - FND-20260910-abcdef02 [INFERRED] Process proceso_1 reads cust.customer_master
#   ...
# lineage edges: 5
#   cust.customer_master -[READS]-> proceso_1 (CONFIRMED)
#   ...
```

### 10. Export audit

```bash
sassessment export-audit
# {
#   "destination": "workspace/audit/export-ASMT-20260910-1a2b3c4d.jsonl",
#   "event_count": 42
# }
```

Exports the full audit trail to a JSONL file.

## Sessions

Each `sassessment start` runs within a session. Sessions track the
execution context:

```bash
sassessment sessions
# session SES-20260910-1a2b3c4d status=OPEN started=2026-09-10T10:30:00Z
```

Sessions are created automatically on first use. The session id is used
for OpenCode session continuation when invoking agent nodes.

## Resume semantics

The graph is resumable at any point:

- If interrupted during node execution, the node status stays RUNNING.
  The next `start` re-runs the node (incrementing the attempt counter).
- If a node is WAITING_FOR_INPUT, the graph pauses at that node. Other
  branches continue independently.
- After answering a request, the resume node becomes READY and the next
  `start` runs it.
- SUCCEEDED nodes are never re-run. The engine selects the next runnable
  node by status (READY first, then PENDING), phase order, and alphabetical
  tiebreak.

## Interruption behavior

If the process is interrupted (Ctrl-C, crash, power loss):

- The SQLite database uses WAL mode with `BEGIN IMMEDIATE` transactions.
  In-flight transactions are rolled back on recovery.
- The JSONL audit trail is append-only with flush after each write.
  Events written before the interruption are durable.
- Checkpoints provide full state restoration if needed.
- Node execution artifacts in `workspace/executions/<EXE-id>/` persist
  across interruptions.

To resume after an interruption:

```bash
sassessment status    # check current state
sassessment start     # continue from where it left off
```

## Dry run

To see what would execute without actually running:

```bash
sassessment run --dry-run
# DRY sys.workspace: PLANNED
#     route sys.workspace -> intake.register [always]
```

Dry run shows the next runnable node and the edges that would fire. It
does not invoke any node handlers or LLM agents.

## History

To see the audit trail:

```bash
sassessment history
# 2026-09-10T10:30:00.123Z human  assessment.created       - -> ASMT-20260910-1a2b3c4d
# 2026-09-10T10:30:01.456Z human  session.started          - -> SES-20260910-1a2b3c4d
# 2026-09-10T10:30:02.789Z node   node.execution.started   sys.workspace
# 2026-09-10T10:30:03.012Z node   node.execution.completed sys.workspace -> SUCCEEDED
# ...
```

## Show commands

```bash
sassessment show graph
# graph sassessment-foundation v1.0.0:
#   sys.workspace (deterministic, phase0) -> intake.register
#   intake.register (deterministic, phase1) -> intake.coverage
#   ...

sassessment show blockers
# - lineage.dba_request: waiting for human input: Oracle all_dependencies export not supplied

sassessment show requests
# REQ-20260910-abcdef12 [OPEN/REQUIRED_FOR_CONFIDENCE] Oracle all_dependencies export not supplied
#   destination batch: intake/raw/req-20260910-abcdef12
#   resume node: lineage.ingest_dba
```

## Multi-day operation and crash recovery

| Scenario | Actions |
|---|---|
| Provider quota dies mid-node | Engine pauses the node as `WAITING_FOR_APPROVAL` WITHOUT consuming attempt budget (test hook: `node.quota_hold` audit event). Other branches keep running. |
| Quota resets next day | `sassessment unblock <node-id>` sets it READY (no attempt burn), then `sassessment start` resumes only pending work. |
| VM relaunch / process killed mid-node | On startup `ApplicationContext.engine()` calls `engine.recover_stale_running()` which releases stale RUNNING nodes to READY (attempts preserved) and marks their half-open executions CANCELLED. |
| Same quota problems on an offline portion | Deterministic nodes never call OpenCode, so they are immune. |
| Idempotency used before | `intake.register` skips already-registered batches, the human request unique-index prevents repeated DBA/ops asks. |
