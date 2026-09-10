# Decision Register

Formal record of architectural and technical decisions for the SASsessment project.
Each decision is immutable once recorded. Reversal requires a new decision entry.

---

## ADR-001: System Python 3.9 Runtime, stdlib-first

| Field | Value |
|-------|-------|
| ID | ADR-001 |
| Status | Accepted |
| Slice | A |

**Decision.** Code must be compatible with Python 3.9.6 (`/usr/bin/python3`). Runtime dependency limited to PyYAML. Dev dependency limited to pytest. No Python 3.10+ syntax at runtime (no `match`, no PEP 604 `X | Y` unions). `from __future__ import annotations` is permitted.

**Rationale.** The corporate environment provides system Python 3.9 with pytest and PyYAML preinstalled. Homebrew Python 3.14 lacks these packages. Requiring a newer Python would break the local environment.

**Rejected alternatives.** Requiring Python 3.14 (breaks corporate environment). Adding pydantic or jsonschema as runtime dependencies (unnecessary complexity for current scope).

---

## ADR-002: src Layout with Package Name sassessment

| Field | Value |
|-------|-------|
| ID | ADR-002 |
| Status | Accepted |
| Slice | A |

**Decision.** Use `src/` layout with package name `sassessment`. `pyproject.toml` uses setuptools. pytest configured with `pythonpath=["src"]`. Console script entry point: `sassessment = sassessment.cli.main:main`.

**Rationale.** Standard Python packaging convention. Separates package source from project root. Enables clean imports.

---

## ADR-003: Dual Persistence (SQLite Transactional + JSONL/YAML Human-Readable)

| Field | Value |
|-------|-------|
| ID | ADR-003 |
| Status | Accepted |
| Slice | A |

**Decision.** SQLite serves as the transactional index (WAL mode, foreign keys enabled, BEGIN IMMEDIATE). JSONL audit log is the authoritative append-only sequence. YAML sidecars (manifests, checkpoints) provide human-readable inspection and recovery. SQLite is never the sole recovery path.

**Rationale.** SQLite provides ACID transactions for structured state. JSONL provides an immutable, grep-friendly audit trail. YAML manifests are human-inspectable. The dual path ensures recovery even if the database is corrupted.

---

## ADR-004: Embedded Migrations with schema_migrations Table

| Field | Value |
|-------|-------|
| ID | ADR-004 |
| Status | Accepted |
| Slice | A |

**Decision.** SQL migrations live in `src/sassessment/state/migrations/V*.sql`. The Migrator applies them in version order and records each in the `schema_migrations` table. Reapplication is idempotent. `executescript` is used outside the outer transaction (SQLite limitation); the schema_migrations insert uses its own transaction.

**Rationale.** Embedded migrations keep schema changes versioned alongside code. The `schema_migrations` table prevents duplicate application.

---

## ADR-005: Secret Redaction at Audit Emitter Layer

| Field | Value |
|-------|-------|
| ID | ADR-005 |
| Status | Accepted |
| Slice | A |

**Decision.** The Redactor applies regex patterns (configurable) plus hardcoded sensitive keys (password, secret, token, credential, api_key) before writing to both JSONL and SQLite. This sacrifices slight event noise for a guarantee against secret leakage.

**Rationale.** Secrets must never appear in persistent logs. Redacting at the emitter layer ensures no code path can bypass redaction.

---

## ADR-006: Idempotency by Design

| Field | Value |
|-------|-------|
| ID | ADR-006 |
| Status | Accepted |
| Slice | A |

**Decision.** Human requests: unique partial index on (assessment, node, missing_info) ensures only one OPEN request per combination. Audit events: INSERT OR IGNORE by event_id. Lineage edges: UNIQUE (assessment, source, target, relationship). Artifact registration detects duplicates by SHA-256.

**Rationale.** The system must be safely re-runnable. Idempotency prevents duplicate state from retries, re-registration, or resume operations.

---

## ADR-007: Graph JSON as Versioned Definition Format

| Field | Value |
|-------|-------|
| ID | ADR-007 |
| Status | Accepted |
| Slice | B |

**Decision.** The assessment graph is defined as a versioned JSON document (`graphs/foundation-graph.json`). Nodes declare type, phase, handler, prerequisites, max_attempts. Edges declare source, target, condition (named predicate), priority. The graph loader validates structure on load.

**Rationale.** JSON is human-readable, diff-friendly, and parseable without external dependencies. Versioning allows graph evolution. Named predicates (not inline expressions) keep routing deterministic.

**Evidence in code.** `src/sassessment/graph/model.py` defines NodeDef, EdgeDef, GraphDef, Condition. `src/sassessment/graph/loader.py` loads and validates. `graphs/foundation-graph.json` is the foundation graph.

---

## ADR-008: Mock Adapter Fallback for Offline Operation

| Field | Value |
|-------|-------|
| ID | ADR-008 |
| Status | Accepted |
| Slice | E |

**Decision.** The adapter layer provides a MockAdapter that simulates OpenCode CLI responses offline. The `create_adapter` factory selects MockAdapter when the real CLI is unavailable or when explicitly configured. This enables testing and demo execution without network or CLI access.

**Rationale.** Development, testing, and demo must work without a live OpenCode CLI. The mock adapter provides deterministic responses for graph node execution.

**Evidence in code.** `src/sassessment/opencode_adapter/adapter.py` defines both `OpenCodeAdapter` and `MockAdapter`. `create_adapter()` selects between them.

---

## ADR-009: Prompt Template Mechanism with File-Based Lookup

| Field | Value |
|-------|-------|
| ID | ADR-009 |
| Status | Accepted |
| Slice | F |

**Decision.** Agent prompts are rendered from templates. Lookup order: `prompts/<handler>.md`, then `prompts/<node-id>.md`, then built-in default. Placeholders `{{node_id}}`, `{{phase}}`, `{{title}}`, `{{state}}` are substituted from the node context. The system prompt instructs the agent to ground all statements in provided state, never invent evidence IDs, and produce a fenced JSON result envelope.

**Rationale.** File-based templates allow non-developers to tune agent behavior without code changes. The fallback default ensures every node has a usable prompt. The structured output requirement enables envelope validation.

**Evidence in code.** `src/sassessment/prompts.py` implements `render_prompt()` with the lookup chain and placeholder substitution.

---

## ADR-010: Deterministic Routing via Named Predicates Only

| Field | Value |
|-------|-------|
| ID | ADR-010 |
| Status | Accepted |
| Slice | B |

**Decision.** Graph edge conditions reference predicates by name (e.g., `always`, `node_succeeded`, `has_evidence`). The PredicateRegistry evaluates them against structured state. Natural language condition evaluation is never used. Handlers may record semantic judgements as decisions or findings, but transition evaluation stays deterministic.

**Rationale.** LLM non-determinism must not affect graph routing. Named predicates are testable, auditable, and reproducible.

**Evidence in code.** `src/sassessment/graph/predicates.py` implements PredicateRegistry with built-in predicates: always, never, node_succeeded, node_failed, has_evidence, has_open_requests, phase_reached.

---

## ADR-011: Envelope Validation via Typed Python Models (Not JSON Schema)

| Field | Value |
|-------|-------|
| ID | ADR-011 |
| Status | Accepted |
| Slice | E |

**Decision.** Result envelopes from agent output are validated using typed Python dataclasses with explicit field checks, not JSON Schema (the `jsonschema` library is not available in the corporate environment). The `ResultEnvelope` dataclass validates status values, confidence values, summary presence, and evidence reference format.

**Rationale.** The corporate environment lacks the `jsonschema` package. Typed Python models provide equivalent validation without external dependencies.

**Evidence in code.** `src/sassessment/opencode_adapter/envelope.py` defines `ResultEnvelope` with a `problems()` method that returns validation errors.
