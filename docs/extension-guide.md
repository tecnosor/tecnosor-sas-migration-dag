# Extension guide

## Add a deterministic node

1. Write the handler in `src/sassessment/demo/nodes.py` (or any module accepting
   `NodeContext`) with the signature
   `def node_x(context: NodeContext) -> NodeResult`.
2. Register it: `registry.register(node_x, names=["x.do_thing"])` in
   `build_registry()` (`src/sassessment/demo/nodes.py`).
3. Add the node + an edge to `graphs/foundation-graph.json`
   (`type: deterministic`, `handler: x.do_thing`); bump `version`.
4. Tests: extend `tests/test_graph.py` or `tests/test_cli.py`.

Constraints: the handler must NOT advance the graph; return a `NodeResult`
conforming to `src/sassessment/nodes/base.py`. `waiting_for_input` results must
have created their request via `context.request_human_input(...)`.

## Add an OpenCode agent node

1. Author `agents/<name>.md` with `model: opencode-go/glm-5.3-flash` (locked).
2. Mirror into `.opencode/agent/` (symlink).
3. Point `config/default.yaml -> opencode.agents` to it.
4. Add a graph node with `type: opencode`, `agent: <name>`, `handler` naming a
   prompt template in `prompts/<handler>.md` (optional; a default template is
   built in). Engine validates the returned envelope and rejects unknown
   evidence IDs.

## Add a named predicate

Predicates live in `src/sassessment/graph/predicates.py`
(`_BUILTIN_PREDICATES`) or may be registered at runtime via
`PredicateRegistry.register(name, fn(state, args) -> bool)`. They must be pure
and deterministic — no LLM calls, no random, no clock reads. Graph edges
reference them by name: `{"condition": {"name": "...", "args": {...}}}`.

## Add a parser (new input type)

Parsers are contracts + fixtures, not speculative implementations: create
`skills/<n>/SKILL.md` documenting the contract, place a representative fixture
under `examples/`, and implement the parsing logic only when real samples are
available.

## Add a connector

Connectors are optional acquisition adapters. Defaults are disabled
(`config/default.yaml -> connectors.enabled`). Any live/production access must
obey `approval_policy: explicit` and be read-only. Normalize external data into
standard batches under `intake/raw/<source-batch-id>/` so both connected and
manual acquisition converge on the same ingestion contracts.

## Add a checkpoint/restore trigger

Use `sassessment checkpoint` (manual) or the `CheckpointManager`
(`src/sassessment/state/checkpoints.py`) from a validation node. Restores are
hash-verified first; any tamper aborts without touching live state.
