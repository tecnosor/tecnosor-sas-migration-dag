# Legacy DMF/SAS log parser — architecture and operations

Deterministic, streaming, offline parser for the legacy SAS/DMF batch
execution logs. Module: `src/sassessment/legacy_logs/`. No LLM by design
(LLM only sees the parser's own summary when the operator opts in via the
`runtime.legacy_interpret` agent node).

## Layer stack

| File | Responsibility |
|---|---|
| `model.py` | Normalized records; file/line/byte provenance; parser version. Supports `TB_LOG`, `SAS_MESSAGE`, `SAS_SOURCE`, `PAGE_HEADER`, `INCLUDE`, `LIBREF`, `DATASET_OPERATION`, `TIMING`, `EXTERNAL_COMMAND`, `CHECKPOINT`, `FRAMEWORK_STATUS`, `TIME_SLEEP`, `CALL_DMF`, `RAW_UNKNOWN` |
| `assembler.py` | Streaming, deterministic record boundary rules: `NOTE:/WARNING:/ERROR:` multiline reconstruction, quote-aware `TB_LOG` wrapping, `!+` SAS source continuation, page-header + localized page-date joining, blank-line handling |
| `parsers.py` | Per-family field parsing with quote-safe ` - ` split, SAS duration decoding (mm:ss.ms → seconds), heap of runtime mk-maps (user/level/component/entity/frequency/environment/iteration) |
| `lifecycle.py` | INI/FIN correlation on `(component, job_id, instance, score; iteration)`; returns `LifecycleStage` objects and loop iterations with sleep segments; canonical keys |
| `status.py` | Evidence hierarchy → batch outcome FAILED / PARTIAL / SUCCESS / UNKNOWN. Framework marks (LOAD_OK/LOAD_ERR/OUT_ERR/CANCEL, OUTPUT, SALIDA) |
| `engine.py` | Orchestrates assemble → families → lifecycle → status; emits summary metrics (records, type/severity/aps, unclassified %, orphan FIN, incomplete lifecycle, sleep counts). Writes `analysis/runtime/<LOG>.dmf-summary.json` |

## Boundary & precedence

1. PAGE_HEADER lines that match regex `^ (\x0c)? ^(\\d+)\\s+Sistema SAS$` are
   isolated and their localized date line is joined exactly as recorded; they
   are intentionally not part of any runtime event.
2. `TB_LOG:` lines open quote-tracked continuation records: they close when
   quote balance is even and their last non-blank line does NOT end with `-`
   and the next physical line doesn't impair field alignment via `"` or `-`.
3. `NOTE:/WARNING:/ERROR:` lines stay open while any continuation matches:
   source-echo line numbers (`\\d+\\s+\\+`), SAS auto-var lines (`_ERROR_=`),
   "real time"/"cpu time"/"Engine(...)"/"Physical Name(...)" style lines, ".\\n"
   continuations; page header interrupts without forcing the previous message
   to be stale (the page record inserts cleanly).
4. `#Tiempo actual:`/`#Desde el comienzo`/`\\$Desde el anterior hito` checkpoint
   three-lines attach as one block.
5. `\\SALIDA:`/`generated_out`/`date_etl:` lines mark framework status anchors.
6. Bare (non-anchor) unprefixed short lines are preserved as `RAW_UNKNOWN` with
   a `No deterministic rule matched` warning (never silently dropped).

## Lifecycle & itérations semantics

- Open/close keys: `(component, job_id, entity, iteration)`.
- Nested events pair FIFO; unmatched FIN keeps `marker="ORPHAN_FIN"`,
  duplicated INIs each hold their lifecycle stage.
- `Ini/Fin dmf_execution_expl` events produce `iteration_runs` (frontier
  markers of `exeBucleExploitation N`); `time_sleep:` rows feed loop summaries;
  `sleep` assemblies attach to the current iteration's stage list.

## Operational guide

```bash
# inspect what the deterministic parser sees on your raw logs
PYTHONPATH=src python3 -m sassessment inspect intake/raw/<source-batch-id>

# after registration:
PYTHONPATH=src python3 -m sassassment start
# runtime.dmf_logs runs each registered *.log/*.txt in streaming mode.
# summary artifacts: analysis/runtime/<stem>.dmf-summary.json
# review unclassified lines:
python3 -m pytest tests/test_legacy_log_parser.py -v     # golden fixtures
```

**Inspect unclassified records:** read `.dmf-summary.json` and filter
`record_type=="RAW_UNKNOWN"`; each entry lists `start_line/end_line/raw_text`.

**Add a rule:** private handler `parse_*` in `parsers.py` assigned via
`record_from_draft` anchor switch; tie a unique `rule_id` (from the record_type)
and register in the same heading position (deterministic order).

**Versioning:** `PARSER_VERSION` in `model.py` stamped on every record; DPR
diffing is by re-running the golden suite and comparing
`analysis/runtime/*.dmf-summary.json` files between versions.

**Coverage matrix (fixture mapping)** — see `tests/test_legacy_log_parser.py`:
plain TB_LOG, multiline TB_LOG, TB_LOG with ` - ` inside quoted event/context,
INI/FIN pairing, missing FIN at EOF, orphan FIN, duplicate INI, 2 iterations,
sleep=5 lambda, 5:00.00==300s duration, source echo with `+`/`!+`,
page header addition, TB_LOG ERROR “Sin registros” (explicit), RAW unknown
records retained, framework statuses (SUCCESS/FAILED/PARTIAL branches).

## vs current runtime.correlate node

`runtime.correlate` remains the free-form, non-DMF, structural fallback; the
DMF parser is a second deterministic pass that only activates log files under
registered batches. When `runtime.dmf_logs` leaves > 40% of lines as
`RAW_UNKNOWN`, it raises the `runtime.legacy_interpret_needed` flag and the
agent node (`runtime.legacy_interpret`) runs after it (real OpenCode runs are
opt-in via `sampassessment config/opencode.force_mock=false`).
