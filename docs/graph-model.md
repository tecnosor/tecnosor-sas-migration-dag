# Graph model

The assessment graph is a JSON document at `graphs/foundation-graph.json`.
The `GraphEngine` loads it via `src/sassessment/graph/loader.py` and validates
it through `src/sassessment/graph/model.py`.

## JSON schema

```json
{
  "id":          "string, unique graph identifier",
  "version":     "string, semver",
  "description": "string, human-readable purpose",
  "entry":       "string, node id of the entry point",
  "max_cycles":  "integer, global cycle counter guard",
  "phases":      ["phase0", "phase1", ...],
  "nodes":       [ NodeDef, ... ],
  "edges":       [ EdgeDef, ... ]
}
```

### NodeDef

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | unique node identifier |
| `type` | string | one of the node types below |
| `phase` | string | phase label (phase0..phase8) |
| `title` | string | human-readable title |
| `handler` | string | handler name resolved in NodeRegistry |
| `agent` | string | opencode agent name (opencode nodes only) |
| `phase_gate` | bool | whether this node gates phase advancement |
| `requires` | [string] | node ids that must be SUCCEEDED before this node runs |
| `max_attempts` | int | hard cap on execution attempts (default 5) |
| `composite` | object | sub-graph definition (composite nodes) |

### EdgeDef

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | source node id |
| `target` | string | target node id |
| `condition` | object | `{ "name": "predicate_name", "args": {...} }` |
| `priority` | int | lower fires first (default 100) |

## Node types

| Type | Behavior |
|------|----------|
| `system` | Infrastructure bootstrap, no handler logic |
| `human` | Creates a human request and waits for input |
| `deterministic` | Pure Python handler, no LLM involved |
| `opencode` | Invokes OpenCode CLI with an agent and prompt |
| `validation` | Quality gate, checks evidence traceability |
| `checkpoint` | Creates an immutable state snapshot |
| `composite` | Contains a sub-graph executed as a unit |

## Edge conditions (named predicates)

All edge conditions reference predicates by name. The `PredicateRegistry`
in `src/sassessment/graph/predicates.py` evaluates them against structured
state. The LLM never decides routing.

| Predicate | Args | Behavior |
|-----------|------|----------|
| `always` | none | always true |
| `never` | none | always false |
| `node_succeeded` | `node` | true if named node status is SUCCEEDED |
| `node_failed` | `node` | true if named node status is FAILED |
| `node_waiting` | `node` | true if named node is WAITING_FOR_INPUT or WAITING_FOR_APPROVAL |
| `has_batches` | none | true if batch_count > 0 |
| `phase_at_least` | `phase` | true if current phase >= target in phase order |
| `has_open_requests` | none | true if open_request_count > 0 |
| `request_resolved` | `request` | true if request id is in resolved_requests list |
| `flag_enabled` | `flag` | true if named flag is set in state.flags |

Custom predicates can be registered via `PredicateRegistry.register(name, fn)`.

## Safety mechanisms

- **Cycle limits.** `max_cycles` on the graph (default 25, foundation graph
  sets 40) and `limits.max_graph_cycles` in config. The engine raises
  `CycleLimitExceededError` when the counter overflows.
- **Max node attempts.** Each node has `max_attempts` (default 5). After
  exhaustion the node stays FAILED and no further transitions fire from it.
- **Transition auditing.** Every state change is emitted through
  `AuditEmitter` with timestamp, rationale, and evidence references.
- **Branch-level waiting.** A node in `WAITING_FOR_INPUT` blocks only its
  own downstream edges. Other branches continue independently.
- **Prerequisites.** The `requires` field on a node lists node ids that must
  be SUCCEEDED before the node becomes runnable.

## Resume semantics

When a human request is resolved via `sassessment answer <request-id>`:

1. The request status moves to RESOLVED.
2. The waiting node status moves to SUCCEEDED.
3. The resume node (specified in the request) moves to READY.
4. The next `sassessment start` picks up from the resume node.

The engine does not re-run already SUCCEEDED nodes. It selects the next
runnable node by status (READY first, then PENDING), phase order, and
alphabetical tiebreak.

## Foundation graph (text rendering)

```
id: sassessment-foundation
version: 1.0.0
entry: sys.workspace
max_cycles: 40
phases: [phase0, phase1, phase2, phase3, phase4, phase8]

nodes:
  sys.workspace         deterministic  phase0  handler=sys.workspace         gate
  intake.register       deterministic  phase1  handler=intake.register
  intake.coverage       deterministic  phase1  handler=intake.coverage       gate
  sas.discover          deterministic  phase2  handler=sas.discover          gate
  runtime.correlate     deterministic  phase3  handler=runtime.correlate
  doc.map_apps          deterministic  phase4  handler=doc.map_apps
  lineage.dba_request   human          phase4  handler=lineage.dba_request
  lineage.ingest_dba    deterministic  phase4  handler=lineage.ingest_dba    requires=[sas.discover]
  quality.gate          validation     phase8  handler=quality.gate
  audit.export          deterministic  phase8  handler=audit.export          requires=[quality.gate]

edges:
  sys.workspace        -> intake.register       [always]
  intake.register      -> intake.coverage       [always]
  intake.coverage      -> sas.discover          [always]
  intake.coverage      -> runtime.correlate     [always]
  sas.discover         -> doc.map_apps          [always]
  sas.discover         -> lineage.dba_request   [always]
  lineage.dba_request  -> lineage.ingest_dba    [always]
  runtime.correlate    -> quality.gate          [always]
  doc.map_apps         -> quality.gate          [always]
  quality.gate         -> audit.export          [always]
```

The graph has two independent branches after `sas.discover`: the main branch
(runtime.correlate, doc.map_apps, quality.gate, audit.export) and the offline
DBA lineage branch (lineage.dba_request, lineage.ingest_dba). The DBA branch
pauses for human input while the main branch continues.
