# SASsessment

Graph-orchestrated, auditable and resumable foundation for assessing SAS Analytics
estates ahead of migration to the Personal Finance standard data technology stack.

**Status**: foundation-complete. This repository contains the operational substrate
(executable graph, state model, intake, OpenCode adapter, CLI, audit, checkpoints,
tests, synthetic demo). It deliberately does NOT perform a real subsidiary
assessment yet.

## Quick start

```bash
# corporate runtime: system python3 (3.9+), PyYAML + pytest only
pip3 install -e .            # or run from repo with PYTHONPATH=src
python3 -m sassessment init       # scaffold workspace + assessment
python3 -m sassessment status     # current graph state + next actions
python3 -m sassessment validate   # workspace validator
python3 -m sassessment demo       # synthetic end-to-end demonstration
python3 -m sassessment            # interactive chatbot/REPL (quit exits)
```

Run the synthetic demo from a clean state:

```bash
rm -f workspace/database/sassessment.db* && rm -rf intake/raw/BAT-demo-fixture intake/raw/req-* intake/manifests/*.yaml
PYTHONPATH=src python3 -m sassessment demo
```

## Where to put raw data

```text
intake/raw/<source-batch-id>/
```

Accepted: DOCX, XLSX/XLS/CSV, PPTX, PDF, Markdown/text, SAS sources, SQL/PL-SQL,
logs, metadata export, DataStage/Talend exports, and ZIP/TAR/TAR.GZ archives
(with nested archives). Raw files are treated as **immutable evidence**: they are
hashed (SHA-256), never modified, and manifest records live under
`intake/manifests/<batch-id>.yaml`.

Human inputs (DBA exports, runtime logs, dictionaries) get a dedicated
destination batch that the program prints when it raises a request; resolve it
with `sassessment answer <request-id>` after dropping files there.

## What is inside

| Layer | Entry |
|---|---|
| Graph engine (versioned foundation graph, phases 0-8) | `graphs/foundation-graph.json` |
| Python package + CLI + REPL | `src/sassessment/` (`python -m sassessment`) |
| SQLite state + migrations + audit + immutable checkpoints | `src/sassessment/state/`, `workspace/database/`, `workspace/audit/` |
| Safe intake (hashing, manifests, traversal/symlink-safe staging, quarantine) | `src/sassessment/intake/` |
| OpenCode headless adapter (argv-only, timeouts, prompt hashes, mock fallback) | `src/sassessment/opencode_adapter/` |
| Specialist agents + skills (OpenCode-discoverable) | `agents/`, `skills/`, `.opencode/` |
| Documentation | `docs/` |

## Determinism and safety

- Graph routing runs through **named deterministic predicates** over structured
  state; the LLM never decides transitions.
- Agent/envelope output is validated before any state mutation; evidence IDs
  must exist in state or the result is rejected.
- Discovered SAS/SQL/ETL code is **never executed**.
- Archives are treated as untrusted: path traversal and symlink escapes are
  rejected and quarantined.
- Secrets are redacted from logs, audit events, and invocation records.
- Attempt counters, cycle bounds, and immutable checkpoints protect long-running
  sessions; a failed node never corrupts a prior checkpoint.

## Documentation

Start with `docs/architecture.md`, then `docs/operator-guide.md`,
`docs/human-input-runbook.md`, `docs/threat-model.md`, and
`docs/demo-walkthrough.md`. ADRs live in `docs/ADRs.md`. The build backlog and
registers live in `workspace/backlog/BACKLOG.md` and friends; the internal
session-continuity state lives in `.sisyphus/backlog/` (todo.yaml, STATE.md).

## Testing

```bash
python3 -m pytest -q            # full suite
python3 -m pytest tests/test_graph.py -v   # engine only
```

The synthetic demo (and its smoke test) exercises: initialization, raw batch
registration, evidence coverage, deterministic SAS discovery placeholder,
database object identification, DBA request creation with query pack, branch
pause/resume after a simulated DBA result, checkpoint creation, quality gate,
and audit export. All fixture data is synthetic.
