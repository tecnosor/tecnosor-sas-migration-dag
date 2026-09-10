# SASsessment — Estado de Construcción (persistencia entre sesiones)

> **Cómo retomar este trabajo en una sesión nueva o tras limpiar contexto:**
> 1. Leer este archivo completo.
> 2. Leer `todo.yaml` (lista estructurada con estados).
> 3. Leer `decisions.md` (decisiones arquitectónicas ya tomadas — NO re-decidir).
> 4. Continuar desde la primera tarea `pending` del `todo.yaml`.
> 5. Al terminar cada tarea: actualizar `todo.yaml` y este archivo.
> 6. Hacer commit incremental de git tras cada slice verde.

## Contexto del proyecto

**Misión**: Construir la fundación de "SASsessment" — aplicación Python orquestada por grafo,
auditable y reanudable, para ayudar a subsidiarias de Personal Finance a evaluar migraciones
desde SAS Analytics hacia el stack estándar de datos de PF.

- Master prompt completo: está en la sesión original (ultrawork loop). Este backlog resume
  todos los requisitos operativos necesarios para continuar.
- Repo: `/Users/madraza/Negocios/BNP/SAS` (inicialmente vacío; sin material previo ABC/SASsessment).
- Modo: ULTRAWORK loop (`/ulw-loop`), completion promise "DONE", ~500 iteraciones.

## Entorno verificado (no re-verificar)

| Componente | Valor |
|---|---|
| Python target | **sistema `/usr/bin/python3` = 3.9.6** (pytest 8.4.2 + PyYAML 6.0.3 preinstalados) |
| Python alternativo | homebrew 3.14 (NO usar: sin pytest ni yaml) |
| Código | solo sintaxis 3.9 (typing.Optional/List, sin `match`, sin uniones PEP 604 en runtime) |
| OpenCode CLI | 1.14.30 en /opt/homebrew/bin/opencode |
| opencode run flags | `--agent`, `--model provider/model`, `-s/--session`, `-c/--continue`, `--format json|default`, `--file`, `--dir`, `--title` |
| opencodeextras | `session list`, `export <id> --sanitize`, `agent list`, `models` |
| git | 2.50.1 disponible |
| Modelos opencode-go disponibles | glm-5.3-flash, glm-5.2, deepseek-v4-flash, etc. |

## Arquitectura acordada (del plan agent)

**Orden de construcción**: A → (B ‖ D) → (E ‖ F) → C → G → H

- **A: Core infra** — pyproject, scaffolding de workspace, config precedence (defaults < YAML < env < overrides),
  IDs, SQLite+migraciones, audit JSONL+SQLite con redacción, checkpoints inmutables. ✅ COMPLETA
- **B: Graph engine** — modelo de grafo JSON versionado, predicados estructurados, motor con
  retries/cycle-limits/resume/branch-waiting.
- **D: Intake** — batches en `intake/raw/<batch-id>/`, manifest+hashes SHA-256, staging seguro
  (path traversal + symlinks), quarantine. Paralelizable tras A.
- **E: OpenCode adapter** — argv arrays (nunca shell=True), timeouts, caps de output, prompt hashes,
  mock adapter offline, envelope de resultados validado con JSON Schema. Requiere interfaces de B.
- **F: Node framework** — nodos: deterministic, agent, human, quality-gate, checkpoint, composite;
  registry. Requiere B+E.
- **C: CLI** — comandos: init, status, start, resume, next, run <node>, add-input, scan-inputs,
  show graph|blockers|requests, answer <request-id>, checkpoint, sessions, history, review,
  export-audit, validate, demo, quit + REPL interactivo.
- **G: Grafo fundacional + demo sintética** — fixtures (2 fuentes SAS, 1 macro/include, 1 tabla
  Oracle leída + 1 escrita, 1 log runtime de solo un proceso, 1 dependencia DB faltante,
  1 diccionario de datos). Flujo demo: init → registrar batch → descubrir evidencia → discovery
  SAS determinista → identificar objetos DB → crear request DBA → pausar rama lineage → continuar
  rama doc-mapping → añadir batch DBA-result → resolver → resumir lineage → checkpoint → quality
  gate → export audit.
- **H: Docs + agents/skills** — agents/*.md (coordinator, evidence-curator, sas-estate-analyst,
  runtime-analyst, lineage-analyst, migration-architect, assessment-reviewer) en formato OpenCode
  discoverable (`.opencode/agent/`), skills en `.opencode/skills/<name>/SKILL.md`, docs completos
  (architecture, threat model, runbooks, guides, ADRs, backlog slices A-H, registers).

## Estado actual (actualizar al final de CADA tarea)

**Slice A: COMPLETA y verde (18/18 tests).**

Modulos existentes:
- `pyproject.toml` — paquete `sassessment`, deps: pyyaml (+pytest dev), console script `sassessment`
- `src/sassessment/` — `__init__.py`, `__main__.py` (stub CLI), `errors.py` (jerarquía tipada con codes),
  `ids.py` (IDs prefijados ASMT/BAT/EV/REQ/CKP/EVT…, formato `PREFIX-YYYYMMDD-8hex`)
- `src/sassessment/config.py` — SassessmentConfig, load_config con precedence
- `src/sassessment/workspace/layout.py` — WorkspaceLayout, ensure_workspace (todas las dirs del spec),
  find_repo_root
- `src/sassessment/state/database.py` — Database (WAL, FK, BEGIN IMMEDIATE), Migrator (schema_migrations)
- `src/sassessment/state/migrations/V001__initial.sql` — 19 tablas: assessments, source_batches,
  source_artifacts, evidence, sessions, node_states, executions, human_requests (idempotente OPEN),
  findings (versionable/supersedable), decisions, assumptions, risks, gaps, checkpoints,
  audit_events, data_objects, lineage_edges (UNIQUE por edge), meta
- `src/sassessment/state/repository.py` — Repository con CRUD transaccional por entidad + project_state()
- `src/sassessment/state/events.py` — AuditEmitter (JSONL append-only + SQLite index, idempotente),
  Redactor (regex patterns + keys sensibles password/secret/token/credential/api_key)
- `src/sassessment/state/checkpoints.py` — CheckpointManager (backup sqlite API + manifest hashes,
  verify/restore, inmutabilidad)
- `tests/test_state.py` — 18 tests verdes (migraciones, repo, eventos, checkpoints, config, ids)

**Nota de estabilidad de interfaces (congelar para trabajo paralelo):**
- `Database(path)` / `db.transaction()` (BEGIN IMMEDIATE) / `db.backup_to(path)`
- `Repository(db)` — métodos: create_assessment, upsert_node_state, create_execution,
  finish_execution, create_batch, add_artifact, create_evidence, create_request(→bool idempotente),
  resolve_request, create_finding, supersede_finding, create_decision, create_gap/assumption/risk,
  upsert_data_object, create_lineage_edge, create_checkpoint_record, project_state(assessment_id)
- `AuditEmitter(db, log_path, redactor).emit(action=..., actor_type=..., ...)` → event_id
- `CheckpointManager(db, repo, layout).create(aid, label) → CKP-id; verify; restore`
- `ensure_workspace(repo_root) → WorkspaceLayout`; `find_repo_root()`
- `load_config(repo_root, overrides, env) → SassessmentConfig` (campos: repo_root, database_path,
  opencode{executable,default_model,agents,timeout_seconds,max_output_bytes}, limits{max_retries,
  max_graph_cycles, max_node_attempts, lineage_max_depth, lineage_max_iterations, ...},
  connectors{enabled, approval_policy}, redaction_patterns, active_assessment, dry_run)
- `errors.py` — usar Notamment: ConfigError, StateError, GraphError, GraphValidationError,
  UnknownNodeError, ConditionError, CycleLimitExceededError, MissingPrerequisiteError,
  NodeExecutionError, IntakeError, UnsafeArchiveError, PathTraversalError, SymlinkEscapeError,
  AdapterError, AdapterTimeoutError, ResultValidationError, CheckpointError, CheckpointImmutableError

## Requisitos clave del master prompt (resumen operativo, no re-leer la sesión)

1. **Nunca ejecutar código descubierto** (SAS/SQL/shell/macros/ETL). Archivos raw inmutables.
2. **OpenCode adapter**: subprocess argv arrays, timeouts, caps bytes, captura stdout/stderr/exit/
   duration/session-id, prompt hash, mock mode. Chat history NO es estado autoritativo.
3. **Envelope de resultados LLM** validado (JSON Schema o modelos tipados) ANTES de mutar estado.
   Campos: node_id, execution_id, status, summary, artifacts, evidence_used, findings, gaps,
   requests, decisions, metrics, recommended_next_nodes, limitations, confidence.
4. **Condiciones de grafo deterministas** (predicados Python sobre estado estructurado), decisión
   registrada con id/inputs/evidencia/ruta/rationale/confidence/timestamp.
5. **Human-in-the-loop**: requests con prioridad BLOCKING/REQUIRED_FOR_CONFIDENCE/OPTIONAL_ENRICHMENT,
   DBA query-pack generado, rama WAITING_FOR_INPUT mientras otras continúan, nuevo batch resuelve
   y reactiva SOLO la rama afectada.
6. **Confidence**: solo CONFIRMED/INFERRED/UNKNOWN. Findings nunca se sobrescriben silenciosamente.
7. **Parámetros del flujo demo** (sección 17): ver arriba en G.
8. **Tests mínimos** (sección 11): graph, persistence, intake, adapter, human-input, audit + smoke test.
9. **Seguridad**: path traversal y symlink escape cubiertos con tests, redacción de secretos,
   `shell=True` prohibido, live connectors requieren aprobación explícita.
10. **Documentación final**: README, AGENTS.md, architecture, graph model, state model, adapter doc,
    agent/skill authoring guide, evidence policy, human-input runbook, threat model, developer/
    operator/testing/extension guides, ADRs, demo walkthrough, backlog, registers, handoff.

## Al finalizar todo

Emitir `<promise>DONE</promise>` → Oracle verifica → loop cierra. NO declarar DONE sin:
tests pasando + demo sintética ejecutada + workspace validator + docs suficientes.
