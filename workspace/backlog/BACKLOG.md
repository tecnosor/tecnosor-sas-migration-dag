# SASsessment Delivery Backlog

Phased delivery by vertical slice. Each slice is independently testable.
Status reflects actual code and test state as of the current session.

Total test count: 80 (all passing).

---

## Slice A: Repository and Durable State

| Field | Value |
|-------|-------|
| ID | A |
| Goal | Package skeleton, config, typed errors, IDs, SQLite persistence, audit trail, checkpoints |
| Dependencies | None (foundation slice) |
| Status | DONE |

### Components

| Component | Path |
|-----------|------|
| Package config | `pyproject.toml` |
| Entry point | `src/sassessment/__init__.py`, `src/sassessment/__main__.py` |
| Config loader | `src/sassessment/config.py`, `config/default.yaml` |
| Typed errors | `src/sassessment/errors.py` |
| Prefixed IDs | `src/sassessment/ids.py` |
| Workspace layout | `src/sassessment/workspace/layout.py` |
| Database + migrations | `src/sassessment/state/database.py`, `src/sassessment/state/migrations/V001__initial.sql` |
| Repository | `src/sassessment/state/repository.py` |
| Audit emitter + redactor | `src/sassessment/state/events.py` |
| Checkpoint manager | `src/sassessment/state/checkpoints.py` |

### Acceptance Criteria

- [x] `pyproject.toml` defines package `sassessment` with console script entry point
- [x] Config precedence: defaults < YAML file < environment < overrides
- [x] 19 tables created by V001 migration (assessments, source_batches, source_artifacts, evidence, sessions, node_states, executions, human_requests, findings, decisions, assumptions, risks, gaps, checkpoints, audit_events, data_objects, lineage_edges, meta, schema_migrations)
- [x] SQLite uses WAL mode, foreign keys enabled, BEGIN IMMEDIATE transactions
- [x] Migration idempotent on reapply
- [x] Audit events written as append-only JSONL with SQLite index
- [x] Secret redaction applied before persistence (password, secret, token, credential, api_key patterns)
- [x] Checkpoints produce immutable snapshots with SHA-256 manifest, verify and restore
- [x] Repository CRUD is transactional; duplicate human requests rejected by unique partial index

### Tests

| File | Count |
|------|-------|
| `tests/test_state.py` | 18 |

Covers: migrations, repository roundtrips, duplicate request rejection, transaction rollback, audit emission, redaction, checkpoint create/verify/restore, config loading, ID generation, workspace layout.

### Risks

- SQLite concurrent writes under heavy load remain untested (WAL + BEGIN IMMEDIATE handle moderate concurrency).

---

## Slice B: Graph Engine

| Field | Value |
|-------|-------|
| ID | B |
| Goal | Graph model, JSON loader, deterministic predicates, engine with retry/cycle/resume/branch-waiting |
| Dependencies | Slice A |
| Status | DONE |

### Components

| Component | Path |
|-----------|------|
| Graph model | `src/sassessment/graph/model.py` |
| JSON loader | `src/sassessment/graph/loader.py` |
| Predicate registry | `src/sassessment/graph/predicates.py` |
| Graph engine | `src/sassessment/graph/engine.py` |
| Graph definition | `graphs/foundation-graph.json` |

### Acceptance Criteria

- [x] Graph JSON validated on load: unique node IDs, valid edge references, known entry node, valid node types
- [x] Named predicates evaluated deterministically against structured state (always, never, node_succeeded, node_failed, has_evidence, has_open_requests, phase_reached)
- [x] Engine selects next runnable node respecting prerequisites and phase ordering
- [x] Failed nodes isolate: no downstream routing, checkpoint intact
- [x] Waiting branches (WAITING_FOR_INPUT) block only themselves
- [x] Cycle limit enforced (configurable max_cycles)
- [x] Max attempts per node enforced
- [x] Transitions audited

### Tests

| File | Count |
|------|-------|
| `tests/test_graph.py` | 23 |

Covers: graph model validation, JSON loading, predicate evaluation, engine selection, prerequisite enforcement, failure isolation, waiting branch behavior, cycle limits, attempt limits, resume after waiting.

### Risks

- Composite subgraph runtime (nested graph execution within a node) is defined in the model but not exercised by the foundation graph.

---

## Slice C: Interactive CLI

| Field | Value |
|-------|-------|
| ID | C |
| Goal | Full CLI command set with REPL, graph interaction, input management, audit export |
| Dependencies | Slices A, B, D, E, F, G |
| Status | DONE |

### Components

| Component | Path |
|-----------|------|
| CLI main | `src/sassessment/cli/main.py` |
| ApplicationContext | `src/sassessment/cli/main.py` (class) |

### Commands Implemented

`init`, `status`, `start`, `resume`, `run`, `add-input`, `scan-inputs`, `show` (block, graph, requests), `answer`, `checkpoint`, `sessions`, `history`, `review`, `export-audit`, `validate`, `demo`, `quit`

### Acceptance Criteria

- [x] `init` scaffolds workspace and creates assessment
- [x] `status` shows node states, blockers, open requests
- [x] `start` runs graph from current state
- [x] `add-input` stages a file into intake raw
- [x] `scan-inputs` discovers and registers new batches
- [x] `answer` resolves an open human request
- [x] `validate` checks workspace integrity
- [x] `demo` runs the synthetic end-to-end flow
- [x] `export-audit` writes JSONL audit trail
- [x] `history` shows execution history

### Tests

| File | Count |
|------|-------|
| `tests/test_cli.py` | 7 |

Covers: init, status, validate, scan-and-add-input, full graph run with fixtures, history and export.

### Risks

- REPL mode (interactive quit/loop) is stubbed but not deeply tested.

---

## Slice D: Intake

| Field | Value |
|-------|-------|
| ID | D |
| Goal | Batch scanner, registration with SHA-256 manifests, safe archive staging, duplicate detection |
| Dependencies | Slice A |
| Status | DONE |

### Components

| Component | Path |
|-----------|------|
| Batch scanner | `src/sassessment/intake/scanner.py` |
| Registration | `src/sassessment/intake/registration.py` |
| Safe staging | `src/sassessment/intake/staging.py` |

### Acceptance Criteria

- [x] Scanner discovers batches under `intake/raw/`
- [x] Registration produces YAML manifest with per-file SHA-256 and batch integrity hash
- [x] Re-registration is idempotent
- [x] Raw files are never modified by registration
- [x] Duplicate content detected by SHA-256
- [x] Archive extraction rejects path traversal (entries escaping target directory)
- [x] Symlink escapes rejected
- [x] Media type detection for staged files
- [x] Quarantine mechanism for unsafe archives

### Tests

| File | Count |
|------|-------|
| `tests/test_intake.py` | 19 |

Covers: scanner discovery, registration roundtrip, manifest integrity, idempotent re-registration, raw file immutability, duplicate detection, archive path traversal rejection, symlink escape rejection, nested archives, media type detection.

### Risks

- Production SAS parsers (real .sas, .spc, .sto files) are not implemented. Current discovery uses regex-based static analysis only.

---

## Slice E: OpenCode Adapter

| Field | Value |
|-------|-------|
| ID | E |
| Goal | Headless CLI adapter with capability discovery, argv-only invocation, timeout, envelope validation, mock fallback |
| Dependencies | Slice A |
| Status | DONE |

### Components

| Component | Path |
|-----------|------|
| Adapter | `src/sassessment/opencode_adapter/adapter.py` |
| Envelope validation | `src/sassessment/opencode_adapter/envelope.py` |

### Acceptance Criteria

- [x] Capability discovery via `--version` and `--help` probes
- [x] All invocations use argv arrays (never `shell=True`)
- [x] Timeout enforced; timed-out invocations recorded
- [x] Output capped to configurable max bytes
- [x] Prompt hash recorded per invocation
- [x] Session ID captured from stdout when reported
- [x] MockAdapter provides offline fallback for testing
- [x] Result envelope extracted from fenced JSON or largest brace block
- [x] Envelope validated: required fields (status, summary), valid status values, valid confidence values, evidence references are non-empty strings
- [x] Shell injection attempts do not alter argv structure

### Tests

| File | Count |
|------|-------|
| `tests/test_adapter.py` | 13 |

Covers: real CLI detection, capability report, argv construction, shell injection resistance, session continue flags, timeout handling, nonzero exit capture, malformed envelope rejection, missing envelope handling, mock adapter operation.

### Risks

- OpenCode CLI flag changes could break adapter. Mitigated by capability discovery at startup.

---

## Slice F: Agent and Skill Substrate (Node Framework)

| Field | Value |
|-------|-------|
| ID | F |
| Goal | Node contracts (NodeContext, NodeResult), registry, handler framework, prompt template mechanism |
| Dependencies | Slices A, B, E |
| Status | DONE |

### Components

| Component | Path |
|-----------|------|
| Node base | `src/sassessment/nodes/base.py` |
| Prompt templates | `src/sassessment/prompts.py` |
| Demo node handlers | `src/sassessment/demo/nodes.py` |

### Acceptance Criteria

- [x] NodeContext provides: state read, artifact write, evidence registration, finding registration, decision recording, human request creation, logging
- [x] NodeResult validates status and confidence values
- [x] NodeRegistry maps handler names to callables
- [x] HumanRequestSpec captures all fields needed for DBA/external requests
- [x] Prompt template lookup: `prompts/<handler>.md` then `prompts/<node-id>.md` then built-in default
- [x] Prompt placeholders: `{{node_id}}`, `{{phase}}`, `{{title}}`, `{{state}}`
- [x] System prompt instructs agent to ground statements in state, never invent evidence IDs, produce fenced JSON result envelope
- [x] Demo handlers implement all 10 foundation graph nodes

### Tests

Exercised indirectly through `tests/test_graph.py` (23 tests) and `tests/test_cli.py` (7 tests) which exercise the full node handler pipeline.

### Risks

- OpenCode agent markdown files (`.opencode/agents/`) and skill files (`.opencode/skills/`) are not yet created. The substrate supports them but they do not exist on disk.

---

## Slice G: Synthetic End-to-End Flow

| Field | Value |
|-------|-------|
| ID | G |
| Goal | Foundation graph JSON, synthetic fixtures, demo runner exercising the full 14-step flow |
| Dependencies | Slices A through F |
| Status | DONE |

### Components

| Component | Path |
|-----------|------|
| Foundation graph | `graphs/foundation-graph.json` |
| Synthetic fixture | `examples/synthetic-fixture/` |
| Demo runner | `src/sassessment/demo/synthetic.py` |
| Demo node handlers | `src/sassessment/demo/nodes.py` |

### Foundation Graph

10 nodes across 6 phases (phase0 through phase8):

| Node | Type | Phase |
|------|------|-------|
| sys.workspace | deterministic | phase0 |
| intake.register | deterministic | phase1 |
| intake.coverage | deterministic | phase1 |
| sas.discover | deterministic | phase2 |
| runtime.correlate | deterministic | phase3 |
| doc.map_apps | deterministic | phase4 |
| lineage.dba_request | human | phase4 |
| lineage.ingest_dba | deterministic | phase4 |
| quality.gate | validation | phase8 |
| audit.export | deterministic | phase8 |

### Synthetic Fixture

- `sources/proceso_1.sas` -- reads `cust.customer_master`, writes `cust.customer_dq`, includes `shared_macros/fmt_check.sas`
- `sources/proceso_2.sas` -- reads `cust.customer_dq` only
- `sources/shared_macros/fmt_check.sas` -- shared include/macro
- `runtime/scheduler_export.log` -- execution log for proceso_1 only (proceso_2 intentionally absent)
- `dictionary/data_dictionary.csv` -- table-to-application mapping
- Oracle `all_dependencies` export intentionally absent (triggers DBA request)

### Demo Flow (14 steps)

1. Workspace scaffold
2. Stage fixture batch
3. Workspace validation (sys.workspace)
4. Batch registration (intake.register)
5. Coverage assessment (intake.coverage)
6. SAS discovery (sas.discover)
7. Runtime correlation (runtime.correlate)
8. DBA request creation (lineage.dba_request) -- pauses lineage branch
9. Synthetic DBA result placed
10. Request answered
11. Lineage branch resumed (lineage.ingest_dba)
12. Checkpoint created
13. Quality gate
14. Audit export

### Acceptance Criteria

- [x] Foundation graph loads and validates
- [x] Synthetic fixture contains all required artifact types
- [x] Demo runner executes full 14-step flow without errors
- [x] DBA request is generated, paused, and resumed
- [x] Checkpoint is created mid-flow
- [x] Quality gate runs
- [x] Audit trail is exported
- [x] Demo is repeatable from clean state

### Tests

Exercised through `tests/test_cli.py::test_cli_full_graph_runs_with_fixtures` and the `sassessment demo` command.

### Risks

- Demo state pollution if previous run artifacts remain. Mitigated by clean-state procedure documented in HANDOFF-001.

---

## Slice H: Documentation and Hardening

| Field | Value |
|-------|-------|
| ID | H |
| Goal | Agent/skill markdown files, full documentation set, governance registers |
| Dependencies | Slices A through G |
| Status | NOT STARTED |

### Planned Components

| Component | Path | Status |
|-----------|------|--------|
| Agent definitions | `.opencode/agents/*.md` (7 roles) | NOT STARTED |
| Skill definitions | `.opencode/skills/<name>/SKILL.md` (~24 skills) | NOT STARTED |
| Architecture docs | `docs/architecture.md` | NOT STARTED |
| Threat model | `docs/threat-model.md` | NOT STARTED |
| Runbooks | `docs/runbooks/` | NOT STARTED |
| ADR snapshots | `docs/ADRs.md` | NOT STARTED |
| Demo walkthrough | `docs/demo-walkthrough.md` | NOT STARTED |
| Governance registers | `workspace/backlog/`, `workspace/decisions/`, `workspace/assumptions/`, `workspace/risks/`, `workspace/gaps/`, `workspace/handoffs/` | IN PROGRESS (this deliverable) |

### Acceptance Criteria

- [ ] 7 agent markdown files discoverable by OpenCode
- [ ] Skill files with SKILL.md for each capability
- [ ] Architecture document covering all slices
- [ ] Threat model covering adapter, intake, state, and LLM interaction surfaces
- [ ] Runbooks for common operations (init, resume, checkpoint, export)
- [ ] ADR log with all decisions from DECISIONS.md
- [ ] Demo walkthrough document
- [ ] Governance registers (this deliverable set)

### Tests

Documentation is verified by review, not automated tests. Agent/skill files verified by OpenCode discovery.

### Risks

- Scope creep: documentation can expand indefinitely. Bound by the acceptance criteria above.

---

## Slice Summary

| Slice | Status | Tests | Key Files |
|-------|--------|-------|-----------|
| A | DONE | 18 | `state/`, `config.py`, `ids.py`, `errors.py`, `workspace/` |
| B | DONE | 23 | `graph/`, `graphs/foundation-graph.json` |
| C | DONE | 7 | `cli/main.py` |
| D | DONE | 19 | `intake/` |
| E | DONE | 13 | `opencode_adapter/` |
| F | DONE | (via B,C) | `nodes/base.py`, `prompts.py`, `demo/nodes.py` |
| G | DONE | (via C) | `demo/synthetic.py`, `examples/synthetic-fixture/` |
| H | NOT STARTED | 0 | `.opencode/`, `docs/`, `workspace/` registers |
