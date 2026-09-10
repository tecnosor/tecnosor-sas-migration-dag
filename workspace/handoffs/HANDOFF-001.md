# Handoff: HANDOFF-001

Handoff for another agent or model session. Contains current state, verification commands, and one recommended next action.

---

## Current State

**Foundation complete.** All slices A through G are implemented and tested. Slice H (documentation and hardening) is not started.

| Slice | Status | Tests |
|-------|--------|-------|
| A: Repository and Durable State | DONE | 18 |
| B: Graph Engine | DONE | 23 |
| C: Interactive CLI | DONE | 7 |
| D: Intake | DONE | 19 |
| E: OpenCode Adapter | DONE | 13 |
| F: Agent/Skill Substrate | DONE | (via B, C) |
| G: Synthetic End-to-End Flow | DONE | (via C) |
| H: Documentation and Hardening | NOT STARTED | 0 |

**Total test count:** 80 (all passing)

**Workspace validator:** Clean

**Demo:** Executable from clean state

---

## Verification Commands

Run these commands to verify the current state. All should succeed.

### 1. Run all tests

```bash
PYTHONPATH=src python3 -m pytest -q
```

Expected output: 80 tests passing.

### 2. Run workspace validator

```bash
PYTHONPATH=src python3 -m sassessment validate
```

Expected output: `workspace valid`

### 3. Run demo from clean state

```bash
rm -f workspace/database/sassessment.db*
rm -rf intake/raw/BAT-demo-fixture intake/raw/req-*
rm -f intake/manifests/*.yaml
PYTHONPATH=src python3 -m sassessment demo
```

Expected output: 14-step demo flow completes successfully. Final line: `=== demo complete ===`

---

## Key Files

### Cross-Session State

- `.sisyphus/backlog/STATE.md` -- Project context, architecture summary, current state, interface stability notes
- `.sisyphus/backlog/todo.yaml` -- Structured task list with completion status (note: todo.yaml shows B-H as "pending" but code is complete; the file was not updated after slices B-G were implemented)
- `.sisyphus/backlog/decisions.md` -- Architectural decisions (Spanish, being formalized in DECISIONS.md)

### Governance Registers (This Deliverable Set)

- `workspace/backlog/BACKLOG.md` -- Phased delivery backlog by vertical slice
- `workspace/decisions/DECISIONS.md` -- Formal decision register (11 ADRs)
- `workspace/assumptions/ASSUMPTIONS.md` -- Assumptions register (8 assumptions)
- `workspace/risks/RISKS.md` -- Risk register (9 risks)
- `workspace/gaps/GAPS.md` -- Gap register (10 gaps)
- `workspace/handoffs/HANDOFF-001.md` -- This file

### Code Structure

```
src/sassessment/
  __init__.py, __main__.py
  config.py              -- Config loader with precedence
  errors.py              -- Typed error hierarchy
  ids.py                 -- Prefixed ID generation
  prompts.py             -- Prompt template mechanism
  cli/main.py            -- CLI commands + ApplicationContext
  graph/
    model.py             -- NodeDef, EdgeDef, GraphDef
    loader.py            -- JSON graph loader
    predicates.py        -- Deterministic predicate registry
    engine.py            -- Graph execution engine
  state/
    database.py          -- SQLite wrapper (WAL, FK, BEGIN IMMEDIATE)
    repository.py        -- Transactional CRUD
    events.py            -- Audit emitter + redactor
    checkpoints.py       -- Immutable snapshot manager
    migrations/          -- SQL migrations (V001__initial.sql)
  intake/
    scanner.py           -- Batch discovery
    registration.py      -- Batch registration with SHA-256
    staging.py           -- Safe archive extraction
  opencode_adapter/
    adapter.py           -- OpenCode CLI adapter + MockAdapter
    envelope.py          -- Result envelope validation
  nodes/
    base.py              -- NodeContext, NodeResult, NodeRegistry
  demo/
    nodes.py             -- Foundation graph node handlers
    synthetic.py         -- Demo runner
  workspace/
    layout.py            -- Workspace directory structure

graphs/
  foundation-graph.json  -- 10-node, 6-phase assessment graph

examples/
  synthetic-fixture/     -- Synthetic SAS estate (2 sources, 1 macro, 1 runtime log, 1 dictionary)

tests/
  test_state.py          -- 18 tests (Slice A)
  test_graph.py          -- 23 tests (Slice B)
  test_cli.py            -- 7 tests (Slice C)
  test_intake.py         -- 19 tests (Slice D)
  test_adapter.py        -- 13 tests (Slice E)
```

---

## Architecture Summary

**Build order:** A -> (B || D) -> (E || F) -> C -> G -> H

**Key patterns:**
- Graph-orchestrated execution with deterministic routing (named predicates, not LLM decisions)
- Dual persistence: SQLite (transactional) + JSONL/YAML (human-readable)
- Envelope validation: all agent output must conform to ResultEnvelope schema
- Secret redaction at audit emitter layer
- Idempotency by design (unique constraints, INSERT OR IGNORE, SHA-256 dedup)
- argv-only subprocess invocation (never shell=True)

**Foundation graph:** 10 nodes across 6 phases (phase0 through phase8)
- phase0: workspace validation
- phase1: intake registration and coverage
- phase2: SAS discovery
- phase3: runtime correlation
- phase4: documentation mapping + DBA lineage request (human pause/resume)
- phase8: quality gate + audit export

---

## One Recommended Next Action

**Start Slice H: Documentation and Hardening.**

Specifically, begin with GAP-009: create the agent and skill markdown files.

**Why this first:**
1. The foundation is solid (80 tests passing, demo works, validator clean).
2. The agent/skill files are needed to make the system usable by OpenCode agents.
3. Without agent definitions, the system cannot be invoked by the coordinator agent or specialized roles.
4. This is the highest-priority gap (marked "High" in GAPS.md).

**Concrete steps:**
1. Create `.opencode/agents/` directory.
2. Create 7 agent markdown files (coordinator, evidence-curator, sas-estate-analyst, runtime-analyst, lineage-analyst, migration-architect, assessment-reviewer).
3. Each file should define: description, mode (subagent), model (opencode-go/glm-5.3-flash per AGENTS.md), temperature, permission, system prompt.
4. Create `.opencode/skills/` directory.
5. Create skill files for key capabilities (sas-discovery, runtime-correlation, lineage-analysis, quality-gate, audit-export).
6. Test that OpenCode discovers the agents and skills.

**After agents/skills are done:**
- Write architecture documentation (docs/architecture.md)
- Write threat model (docs/threat-model.md)
- Create CI pipeline (.github/workflows/ci.yml)
- Complete remaining Slice H items

---

## Notes for Resuming Agent

- Read `.sisyphus/backlog/STATE.md` first for full context.
- Read `.sisyphus/backlog/todo.yaml` for task structure (but note the status discrepancy: code is complete for B-G even though todo.yaml shows them as pending).
- All decisions in `.sisyphus/backlog/decisions.md` are final. Do not re-debate them.
- The system is designed for Python 3.9.6. Do not introduce 3.10+ syntax.
- The corporate environment has pytest and PyYAML preinstalled. Do not add runtime dependencies without justification.
- When in doubt, run the verification commands above to confirm state.
