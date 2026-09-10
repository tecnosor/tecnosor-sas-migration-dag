# Architecture

SASsessment is a graph-orchestrated, auditable and resumable Python foundation
for assessing SAS Analytics estates ahead of migration to the Personal Finance
standard data technology stack. Version 0.1.0 implements the foundation graph
with deterministic node handlers and a synthetic demonstration.

## Layered modules

```
cli/                  argparse entry point, ApplicationContext wiring
graph/                GraphDef model, JSON loader, GraphEngine, PredicateRegistry
nodes/                NodeContext, NodeResult, NodeRegistry, HumanRequestSpec
opencode_adapter/     OpenCodeAdapter (subprocess), MockAdapter, envelope validation
state/                SQLite Database, Repository, AuditEmitter, Redactor, CheckpointManager
intake/               scanner, registration, staging (safe archive extraction)
demo/                 synthetic fixture runner, deterministic node handlers
workspace/            WorkspaceLayout, directory scaffold, find_repo_root
config.py             SassessmentConfig dataclass, env/CLI precedence
errors.py             Typed error hierarchy with machine-readable codes
ids.py                Prefixed sortable identifiers (ASMT-, SES-, EXE-, EV-, ...)
prompts.py            Template rendering for opencode agent nodes
```

## Data flow

```
human places files
       |
       v
intake/raw/<batch>/  -->  scan-inputs  -->  intake.register (hash, manifest)
                                                    |
                                                    v
                                           intake.coverage (gap/request if missing)
                                                    |
                              +---------------------+---------------------+
                              |                     |                     |
                        sas.discover         runtime.correlate     lineage.dba_request
                              |                     |                     |
                        doc.map_apps                |              [WAITING_FOR_INPUT]
                              |                     |                     |
                              +--------> quality.gate <--------+          |
                                           |                             |
                                       audit.export                      |
                                                                        |
                                                          human answers request
                                                          (place files in req-<id>/)
                                                          lineage.ingest_dba resumes
```

1. **Intake**: files land in `intake/raw/<source-batch-id>/`. The `intake.register`
   node hashes every file, detects duplicates by SHA-256, writes a YAML manifest
   under `intake/manifests/`, and persists batch and artifact rows.
2. **Coverage**: `intake.coverage` checks whether expected media types are
   present. Missing material generates a `HumanRequestSpec` that flips the node
   to `WAITING_FOR_INPUT` and creates a destination batch at
   `intake/raw/req-<request-id>/`.
3. **Discovery and correlation**: `sas.discover` runs placeholder regex parsers
   over `.sas` sources. `runtime.correlate` matches log events to discovered
   processes. `doc.map_apps` maps tables to owning applications from data
   dictionaries.
4. **Offline DBA branch**: `lineage.dba_request` creates a DBA query pack and
   waits. The lineage branch is independent; the main branch continues to
   `quality.gate` through `runtime.correlate` and `doc.map_apps`.
5. **Quality and export**: `quality.gate` checks evidence traceability.
   `audit.export` writes the full audit trail to
   `workspace/audit/export-<ASMT-id>.jsonl`.

## Determinism guarantees

- **Named predicates only for routing.** The `PredicateRegistry` in
  `src/sassessment/graph/predicates.py` evaluates edge conditions. The LLM
  never decides which edge fires. Available predicates: `always`, `never`,
  `node_succeeded`, `node_failed`, `node_waiting`, `has_batches`,
  `phase_at_least`, `has_open_requests`, `request_resolved`, `flag_enabled`.
- **LLM assists semantics, not decisions.** OpenCode agent nodes return a
  structured `ResultEnvelope` with findings, gaps, and evidence references.
  Every decision is recorded with rationale and timestamp in the `decisions`
  table and the audit trail.
- **Transitions are audited.** Every state change emits an `AuditEmitter` event
  to both the JSONL sidecar and the `audit_events` SQLite index.
- **Attempts and cycles are hard-bounded.** `max_node_attempts` (default 5)
  and `max_graph_cycles` (default 25) prevent infinite loops. The engine
  raises `CycleLimitExceededError` when the global counter overflows.
- **Handlers never advance the graph.** Node handlers return a `NodeResult`.
  Only `GraphEngine` owns transitions.

## Workspace layout

```
config/default.yaml          default configuration
graphs/foundation-graph.json the assessment graph definition
prompts/                     agent prompt templates ({{node_id}}, {{phase}}, ...)
examples/synthetic-fixture/  synthetic demo data (clearly labeled)
intake/raw/                  raw material batches (immutable once placed)
intake/staged/               extracted archive contents
intake/quarantine/           rejected unsafe archives
intake/manifests/            per-batch YAML manifests
workspace/database/          SQLite database (sassessment.db)
workspace/audit/             JSONL audit trail + exports
workspace/checkpoints/       immutable checkpoint snapshots
workspace/project/           project-level sidecars
workspace/decisions/         decision records
workspace/findings/          finding records
workspace/requests/          human request records
workspace/evidence/          evidence index sidecars
workspace/sessions/          session summaries
workspace/executions/        per-execution artifacts
analysis/                    normalized analysis outputs
deliverables/                draft/review/validated/final reports
```

## Configuration precedence

```
code defaults < config/default.yaml < SASSESSMENT_* env vars < CLI flags
```

See `config/default.yaml` for all knobs. See `.env.example` for the
environment variable map.
