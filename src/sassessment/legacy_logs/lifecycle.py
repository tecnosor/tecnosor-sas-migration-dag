from __future__ import annotations

from typing import Any, Dict, List, Optional

from sassessment.legacy_logs.model import LifecycleStage, ParsedRecord


def _correlation_key(record: ParsedRecord, iteration_marker: Optional[int] = None) -> Optional[tuple]:
    component = record.component
    if component is None:
        return None
    return (
        component.lower(),
        record.job_id,
        record.entity_or_partition,
        record.iteration or iteration_marker,
    )


def _current_iteration(records: List[ParsedRecord], index: int) -> Optional[int]:
    for record in records[:index][::-1]:
        if record.record_type == "TB_LOG" and record.iteration is not None:
            return int(record.iteration)
    return None


ADJUSTMENT_WORDS = ("Ini", "Fin", "ini", "fin")
_MISSING_FIN = "incomplete"
_ORPHAN_FIN = "orphan_fin"


def build_lifecycle(records: List[ParsedRecord]) -> List[LifecycleStage]:
    stages: List[LifecycleStage] = []
    opening: Dict[tuple, LifecycleStage] = {}
    iteration_context: Optional[int] = None

    for record in records:
        if record.record_type != "TB_LOG":
            continue
        if record.iteration is not None and record.iteration != iteration_context:
            iteration_context = record.iteration
        marker = record.lifecycle_marker
        if marker not in ("INI", "FIN"):
            continue
        key = _correlation_key(record, iteration_marker=iteration_context)
        if key is None:
            continue
        if marker == "INI":
            stage = LifecycleStage(
                component=str(record.component),
                job_id=record.job_id,
                iteration=record.iteration,
                entity_or_partition=record.entity_or_partition,
                start_record_id=record.record_id,
                start_timestamp=_float(record.timestamp_raw),
                source_level=record.source_severity,
            )
            stages.append(stage)
            opening.setdefault(key, []).append(stage) if False else None
            _push(opening, key, stage)
        elif marker == "FIN":
            stack: List[LifecycleStage] = opening.get(key, [])
            if not stack:
                orphan_stage = LifecycleStage(
                    component=str(record.component),
                    job_id=record.job_id,
                    iteration=record.iteration,
                    entity_or_partition=record.entity_or_partition,
                    start_record_id=record.record_id,
                    complete=False,
                    marker="ORPHAN_FIN",
                )
                stages.append(orphan_stage)
                continue
            stage = stack.pop()
            stage.complete = True
            stage.end_record_id = record.record_id
            stage.end_timestamp = _float(record.timestamp_raw)
    return stages


def _push(opening: Dict[tuple, List["LifecycleStage"]], key: tuple, stage: LifecycleStage) -> None:
    opening.setdefault(key, []).append(stage)


def _float(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def iterate_loop_runs(records: List[ParsedRecord]) -> List[Dict[str, Any]]:
    """Turn Ini/Fin dmf_execution_expl events into loop iteration summaries."""
    runs: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for record in records:
        if record.record_type != "TB_LOG":
            continue
        event = (record.event_name or "").lower()
        if record.iteration is not None and event.startswith("dmf_execution_expl"):
            opened = record.raw_text.lower().startswith("tb_log")
            marker = record.lifecycle_marker
            if marker == "INI":
                current = {
                    "iteration": record.iteration,
                    "job_id": record.job_id,
                    "start_record_id": record.record_id,
                    "stages": [],
                }
                runs.append(current)
            elif marker == "FIN" and current is not None:
                current["end_record_id"] = record.record_id
                current["complete"] = True
                current = None
        elif record.record_type == "TIME_SLEEP" and current is not None:
            sleep_value = record.duration_seconds or 0
            current.setdefault("sleeps", []).append(sleep_value)
        elif current is not None and record.record_type == "TB_LOG" and record.lifecycle_marker in ("INI", "FIN"):
            current.setdefault("stages", []).append(record.component)
    return runs
