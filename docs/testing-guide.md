# Testing guide

## Run

```bash
python3 -m pytest -q           # full suite (80 tests)
python3 -m pytest tests/test_graph.py -v
```

pytest config lives in `pyproject.toml` (`testpaths=["tests"]`, `pythonpath=["src"]`).

## Coverage matrix

| File | Covers | Highlights |
|---|---|---|
| `tests/test_state.py` | Slice A: migrations, repository CRUD, audit events, checkpoints, config | migration idempotency; transaction rollback; finding supersession; secret redaction; tampered-checkpoint detection |
| `tests/test_graph.py` | Slice B: graph model + engine + predicates + envelope | unknown node; self-loop; duplicate ids; unreachable nodes; missing handler; prerequisites; branch waiting; cycle bound; dry-run; fake-evidence rejection |
| `tests/test_intake.py` | Slice D: scanner, registration, staging | mkdir travel; duplicate hash detection; raw immutability; traversal/symlink/absolute/encrypted members; corrupt zip quarantine |
| `tests/test_adapter.py` | Slice E: OpenCode adapter + envelope | capability discovery (real CLI), argv/no-shell, session flags, timeout, non-zero exit, malformed output, session capture, mock fallback, evidence guard |
| `tests/test_cli.py` | Slices C+G smoke: CLI commands over an isolated repo copy | init/status/start loop; add-input; answer expands; history/export; end-to-end synthetic demo incl. pause+resume |

## Smoke equivalence

`tests/test_cli.py::test_smoke_end_to_end` reproduces the 14-step synthetic demo
flow against an isolated workspace copy. The manual flow is documented in
`docs/demo-walkthrough.md`.

## What is not covered

- Real OpenCode `run` execution (adapter tests either probe `--version` or mock
  the subprocess); live LLM nodes are exercised manually via `sassessment demo`.
- No CI pipeline yet (see workspace/gaps/GAPS.md).
