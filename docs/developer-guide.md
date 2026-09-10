# Developer guide

This guide covers local setup, running tests, code layout, adding migrations,
and configuration precedence.

## Local setup

### Requirements

- Python 3.9 or later (stdlib-only plus PyYAML)
- pip or equivalent package manager
- git (for version control)

### Installation

Clone the repository and install in editable mode:

```bash
git clone <repo-url> SAS
cd SAS
pip install -e ".[dev]"
```

Or run without installation using PYTHONPATH:

```bash
PYTHONPATH=src python3 -m sassessment --help
```

### Verify installation

```bash
PYTHONPATH=src python3 -m sassessment validate
# ok: graph 10 nodes / 10 edges (v1.0.0)
# workspace valid

PYTHONPATH=src python3 -m pytest -q
# 80 passed
```

## Running tests

```bash
PYTHONPATH=src python3 -m pytest -q
```

The test suite includes 80 tests across 5 modules:

- `tests/test_adapter.py` (13 tests): OpenCode adapter, mock adapter, envelope
- `tests/test_cli.py` (7 tests): CLI commands, isolated repo fixtures
- `tests/test_graph.py` (23 tests): graph engine, predicates, validation
- `tests/test_intake.py` (19 tests): scanner, registration, staging, archives
- `tests/test_state.py` (18 tests): database, repository, checkpoints, audit

All tests use `tmp_path` fixtures for isolation. No test modifies the
actual workspace.

## Code layout map

```
src/sassessment/
  __init__.py              version string
  __main__.py              python -m entry point
  cli/
    main.py                argparse CLI, ApplicationContext, command handlers
  config.py                SassessmentConfig dataclass, env/CLI precedence
  errors.py                typed error hierarchy with machine-readable codes
  ids.py                   prefixed sortable identifiers
  prompts.py               template rendering for opencode agent nodes
  graph/
    __init__.py
    engine.py              GraphEngine, RunOutcome, next_runnable, blocked_summary
    loader.py              load_graph from JSON
    model.py               GraphDef, NodeDef, EdgeDef, Condition, graph_from_json
    predicates.py          PredicateRegistry, built-in predicates
  nodes/
    __init__.py
    base.py                NodeContext, NodeResult, NodeRegistry, HumanRequestSpec
  opencode_adapter/
    __init__.py
    adapter.py             OpenCodeAdapter, MockAdapter, InvocationResult
    envelope.py            ResultEnvelope, extract_envelope, build_result_from_envelope
  state/
    __init__.py
    database.py            Database wrapper, Migrator, _Transaction
    repository.py          Repository (data access), status constants
    events.py              AuditEmitter, Redactor
    checkpoints.py         CheckpointManager, sha256_file
    migrations/
      V001__initial.sql    initial schema (19 tables)
  intake/
    __init__.py
    scanner.py             scan_batches, files_in_batch
    registration.py        register_batch, BatchRegistration, media_type_of
    staging.py             safe_extract, is_archive, StagingResult
  demo/
    __init__.py
    nodes.py               build_registry, deterministic node handlers
    synthetic.py           run_synthetic_demo
  workspace/
    __init__.py
    layout.py              WorkspaceLayout, ensure_workspace, find_repo_root
```

## Adding migrations

Migrations live in `src/sassessment/state/migrations/` with the naming
convention `V<NNN>__<description>.sql`:

```
V001__initial.sql
V002__add_new_table.sql
V003__add_index.sql
```

The `Migrator` class in `src/sassessment/state/database.py`:

1. Reads all `V*.sql` files from the migrations directory.
2. Parses the version number from the file name (e.g., `V001` -> 1).
3. Checks the `schema_migrations` table for already-applied versions.
4. Applies pending migrations in version order within a transaction.
5. Records each applied migration in `schema_migrations`.

Migrations are idempotent: they use `CREATE TABLE IF NOT EXISTS` and
`CREATE INDEX IF NOT EXISTS` to allow safe re-application.

To add a new migration:

1. Create `src/sassessment/state/migrations/V002__add_new_table.sql`.
2. Write the SQL using `IF NOT EXISTS` clauses.
3. Run `sassessment init` to apply the migration.
4. Verify with `sassessment validate`.

## Configuration precedence

Configuration is loaded by `load_config()` in `src/sassessment/config.py`:

```
code defaults < config/default.yaml < SASSESSMENT_* env vars < CLI flags
```

### Code defaults

The `SassessmentConfig` dataclass in `config.py` defines defaults:

```python
@dataclass
class OpenCodeSettings:
    executable: str = "opencode"
    default_model: str = "opencode-go/glm-5.3-flash"
    timeout_seconds: int = 600
    max_output_bytes: int = 1048576
```

### config/default.yaml

The YAML file at `config/default.yaml` overrides code defaults. It includes
all knobs with documentation comments.

### Environment variables

Environment variables with the `SASSESSMENT_` prefix override YAML settings.
The mapping is defined in `_ENV_MAP` in `config.py`:

```python
_ENV_MAP = {
    "SASSESSMENT_DATABASE_PATH": ("database_path", "path"),
    "SASSESSMENT_OPENCODE_EXECUTABLE": ("opencode.executable", "str"),
    "SASSESSMENT_OPENCODE_MODEL": ("opencode.default_model", "str"),
    "SASSESSMENT_MAX_RETRIES": ("limits.max_retries", "int"),
    ...
}
```

Dotted keys (e.g., `opencode.executable`) set nested fields.

### CLI flags

The `--workspace` flag overrides the repository root. Other CLI flags
override specific settings (e.g., `--dry-run` on `sassessment run`).

## Error handling

All errors inherit from `SASsessmentError` in `src/sassessment/errors.py`
and carry a machine-readable `code` attribute:

```python
class GraphValidationError(GraphError):
    code = "GRAPH_VALIDATION_ERROR"
```

The CLI catches `SASsessmentError` and prints the message and details.
The audit trail records errors with the error code and message.

## Identifier format

All identifiers use the format `<PREFIX>-<YYYYMMDD>-<8 hex chars>`:

```python
assessment_id()  -> "ASMT-20260910-1a2b3c4d"
session_id()     -> "SES-20260910-5e6f7g8h"
execution_id()   -> "EXE-20260910-9i0j1k2l"
evidence_id()    -> "EV-20260910-3m4n5o6p"
```

Prefixes are defined in `src/sassessment/ids.py`. Identifiers are sortable
by date and safe to use as path segments and SQLite keys.
