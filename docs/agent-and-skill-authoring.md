# Agent and skill authoring

This guide covers how to add OpenCode agents, node handlers, graph nodes,
edges, predicates, and prompt templates.

## Adding agents

Agent definitions live in `.opencode/agents/` as Markdown files with YAML
frontmatter. Each file name becomes the agent name used in the `--agent` flag.

### Required frontmatter

```yaml
---
description: Short description of what this agent does
mode: subagent
model: opencode-go/glm-5.3-flash
temperature: 0.2
permission:
  edit: deny
  bash:
    "*": ask
    "grep *": allow
---

You are a SASsessment specialist executing ONE bounded graph node.
...
```

**Critical**: the `model` field must be pinned to `opencode-go/glm-5.3-flash`
to match `config/default.yaml` (`opencode.default_model`). This ensures
consistent behavior across all agent invocations.

### Agent naming convention

The foundation graph references agents by role in `config/default.yaml`:

```yaml
opencode:
  agents:
    coordinator: sassessment-coordinator
    evidence_curator: evidence-curator
    sas_analyst: sas-estate-analyst
    ...
```

Create the corresponding file at `.opencode/agents/sassessment-coordinator.md`.

### Agent system prompt

The agent prompt should instruct the model to:

1. Ground every statement in the provided state or attached files.
2. Never invent evidence ids; only reference ids that exist in state.
3. End the reply with a single fenced JSON result envelope.
4. Not modify files outside the execution directory.
5. Not advance the graph (only the engine owns transitions).

## Adding node handlers

Node handlers are Python functions registered in a `NodeRegistry`. The
foundation handlers live in `src/sassessment/demo/nodes.py`.

### Handler signature

```python
def my_node_handler(context: NodeContext) -> NodeResult:
    ...
```

### NodeContext API

The `NodeContext` in `src/sassessment/nodes/base.py` provides:

| Method | Purpose |
|--------|---------|
| `context.log(message)` | append to execution log |
| `context.write_artifact(name, content)` | write a file to the execution directory |
| `context.register_evidence(kind, title, ...)` | register an evidence item, returns evidence id |
| `context.register_finding(statement, category, ...)` | register a finding, returns finding id |
| `context.register_gap(description, phase)` | register a gap, returns gap id |
| `context.request_human_input(spec)` | create a human request, flips node to WAITING_FOR_INPUT |
| `context.record_decision(route, rationale, ...)` | record a routing decision |
| `context.state` | current structured state snapshot |
| `context.node_id` | the node being executed |
| `context.execution_id` | current execution id |
| `context.execution_dir` | directory for writing artifacts |
| `context.layout` | WorkspaceLayout for path resolution |
| `context.config` | SassessmentConfig |
| `context.repo` | Repository for data access |
| `context.audit` | AuditEmitter for audit events |

### NodeResult

```python
NodeResult(
    status="success",           # success|failed|waiting_for_input|waiting_for_approval|skipped
    summary="...",
    artifacts=["path/to/file"],
    evidence_used=["EV-..."],
    findings=[...],
    gaps=[...],
    requests=[HumanRequestSpec(...)],
    metrics={"count": 42},
    limitations=["..."],
    recommended_next_nodes=["..."],
    confidence="CONFIRMED",     # CONFIRMED|INFERRED|UNKNOWN
)
```

### Registering handlers

In `src/sassessment/demo/nodes.py`, the `build_registry()` function creates
the registry:

```python
def build_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register(node_sys_workspace, names=["sys.workspace"])
    registry.register(node_intake_register, names=["intake.register"])
    ...
    return registry
```

To add a new handler, define the function and register it with one or more
names. The name must match the `handler` field in the graph JSON.

## Adding graph nodes and edges

Edit `graphs/foundation-graph.json`:

### Adding a node

```json
{
  "id": "my.new.node",
  "type": "deterministic",
  "phase": "phase3",
  "title": "My new analysis step",
  "handler": "my.new.node",
  "max_attempts": 3
}
```

### Adding an edge

```json
{
  "source": "existing.node",
  "target": "my.new.node",
  "condition": {"name": "always"}
}
```

### Using predicates in conditions

```json
{
  "source": "quality.gate",
  "target": "audit.export",
  "condition": {"name": "node_succeeded", "args": {"node": "quality.gate"}}
}
```

After editing the graph, validate it:

```bash
PYTHONPATH=src python3 -m sassessment validate
```

## Adding predicates

Custom predicates are registered in `src/sassessment/graph/predicates.py`:

```python
def _my_predicate(state: Dict[str, Any], args: Dict[str, Any]) -> bool:
    return bool(state.get("my_flag", False))

# In __init__:
self._predicates["my_predicate"] = _my_predicate
```

Or register at runtime:

```python
registry = PredicateRegistry()
registry.register("my_predicate", _my_predicate)
```

The predicate function receives the current state snapshot and the `args`
from the edge condition. It must return a boolean.

## Prompt templates

Prompt templates live in `prompts/` as Markdown files. The rendering logic
in `src/sassessment/prompts.py` looks for templates in this order:

1. `prompts/<node.handler>.md`
2. `prompts/<node.id>.md`
3. Built-in default template

### Placeholders

Templates support these placeholders:

| Placeholder | Replaced with |
|-------------|---------------|
| `{{node_id}}` | the node id |
| `{{phase}}` | the current phase |
| `{{title}}` | the node title |
| `{{state}}` | JSON dump of the current structured state |

### Example template

```markdown
# Node task: {{node_id}} ({{title}})

Phase: {{phase}}

## Current structured state
```json
{{state}}
```

## Your task
Complete the bounded task described in the structured state and provide
a result envelope.
```

The system prompt (added automatically by `render_prompt()`) instructs the
model to ground statements in state, avoid inventing evidence ids, and end
with a fenced JSON result envelope.
