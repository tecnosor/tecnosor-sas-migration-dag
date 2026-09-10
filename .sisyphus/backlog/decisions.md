# Decisiones arquitectónicas (ADR log en construcción)

> Regla: una decisión tomada aquí NO se re-debate en sesiones futuras salvo defecto probado.

## ADR-001: Runtime Python 3.9 del sistema, stdlib-first
- **Decisión**: código compatible con Python 3.9.6 (`/usr/bin/python3`), deps solo PyYAML (runtime) + pytest (dev).
- **Razón**: python3.14 homebrew no tiene pytest/PyYAML; el sistema 3.9 los trae. Avoid 3.10+ syntax
  (sin `match`, sin `X | Y` en runtime; `from __future__ import annotations` permitido).
- **Rechazado**: requerir 3.14 (rompe entorno corporativo local), añadir pydantic/jsonschema (innecesario ahora).

## ADR-002: src layout + paquete `sassessment`
- pyproject setuptools, `pythonpath=["src"]` en pytest, console script `sassessment = sassessment.cli.main:main`.

## ADR-003: Doble persistencia — SQLite transaccional + JSONL/YAML human-readable
- SQLite = índice transaccional (WER, FKs ON, WAL). JSONL audit = secuencia autoritativa append-only.
- Sidecars YAML/MD/CSV para inspección humana y recuperación. SQLite nunca es la única vía de recuperación.

## ADR-004: Migraciones embebidas en `state/migrations/V*.sql` con tabla schema_migrations
- Migrator aplica por versión; `executescript` fuera de transaction externa (limitación sqlite3),
  registro en schema_migrations en transaction propia.

## ADR-005: Redacción de secretos en la capa de audit emitter
- Redactor aplica regex patterns (+keys sensibles password/secret/token/credential/api_key) ANTES de
  escribir a JSONL y a SQLite. Sacrifica leve ruido en eventos por garantía de no-filtración.

## ADR-006: Idempotencia por diseño
- Requests humanos: único registro OPEN por (assessment, node, missing_info) — unique partial index.
- Audit events: INSERT OR IGNORE por event_id.
- lineage_edges: UNIQUE (assessment, source, target, relationship); add_artifact detecta duplicados por sha256.

## Pendientes de decidir (Slices B/C/E/G)
- Formato exacto de predicados de condición (hash de predicados nombrados registrados vs. expresiones en JSON).
- Cómo el engine garantiza "failed node no corrompe checkpoint previo" (checkpoint-before-transition).
- Envelope validation: JSON Schema con `jsonschema` NO disponible → validar con modelos Python tipados + checks manuales.
- Estrategia de prompts: plantillas en prompts/ con placeholders sobre contexto curado.
