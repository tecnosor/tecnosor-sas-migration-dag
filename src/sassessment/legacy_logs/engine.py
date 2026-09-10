from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, List, Optional

from sassessment.legacy_logs.assembler import assemble_records
from sassessment.legacy_logs.lifecycle import build_lifecycle, iterate_loop_runs
from sassessment.legacy_logs.model import LifecycleStage, ParsedLog, ParsedRecord, RawRecord
from sassessment.legacy_logs.parsers import record_from_draft
from sassessment.legacy_logs.status import derive_status_evidence


def _record_id(draft: RawRecord, file_id: str, index: int) -> str:
    return f"{file_id}#{index}"


def parse_file(log_path: Path, *, file_id: Optional[str] = None) -> ParsedLog:
    target_id = file_id or Path(log_path).name
    with open(log_path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        return _parse_stream(handle, target_id)


def parse_text(text: str, *, file_id: str = "in-memory") -> ParsedLog:
    return _parse_stream(io.StringIO(text), file_id)


def _parse_stream(handle, file_id: str) -> ParsedLog:
    drafts: List[RawRecord] = assemble_records(handle, file_id)
    records: List[ParsedRecord] = []
    for index, draft in enumerate(drafts, start=1):
        record = record_from_draft(draft, file_id)
        record.record_id = _record_id(draft, file_id, index)
        records.append(record)
    stages = build_lifecycle(records)
    parsed = ParsedLog(records=records, lifecycle=stages, file_id=file_id)
    parsed.metrics = _metrics(parsed)
    return parsed


def _metrics(parsed: ParsedLog) -> Dict[str, Any]:
    records = parsed.records
    counts_by_type: Dict[str, int] = {}
    severity_counts: Dict[str, int] = {}
    impacts: Dict[str, int] = {}
    for record in records:
        counts_by_type[record.record_type] = counts_by_type.get(record.record_type, 0) + 1
        impacts[record.normalized_impact] = impacts.get(record.normalized_impact, 0) + 1
        if record.source_severity:
            severity_counts[record.source_severity] = severity_counts.get(record.source_severity, 0) + 1
    unknown_percent = 0.0
    if records:
        unknown = counts_by_type.get("RAW_UNKNOWN", 0)
        unknown_percent = 100.0 * unknown / len(records) if records else 0.0
    status_evidence = derive_status_evidence(parsed.records)
    incomplete_lifecycle = [stage for stage in parsed.lifecycle if not stage.complete]
    malformed_tb = [r for r in parsed.records
                    if r.record_type == "TB_LOG" and r.parse_warnings]
    sleeps = [r.duration_seconds for r in records if r.record_type == "TIME_SLEEP"
              and r.duration_seconds is not None]
    iterations = sorted({r.iteration for r in records
                         if r.record_type == "TB_LOG" and r.iteration is not None})
    return {
        "total_physical_lines": max((r.end_line for r in records), default=0),
        "total_logical_records": len(records),
        "counts_by_type": counts_by_type,
        "counts_by_severity": severity_counts,
        "counts_by_impact": impacts,
        "unclassified_count": counts_by_type.get("RAW_UNKNOWN", 0),
        "unclassified_percent": round(unknown_percent, 2),
        "incomplete_lifecycle_count": len(incomplete_lifecycle),
        "orphan_fin_count": sum(1 for s in parsed.lifecycle
                                if s.marker == "ORPHAN_FIN"),
        "malformed_tb_log_count": len(malformed_tb),
        "sleeps": sleeps,
        "iterations": iterations,
        "global_outcome": status_evidence.get("global_outcome", "UNKNOWN"),
        "status_evidence": status_evidence.get("evidence", []),
    }


def outcome(parsed: ParsedLog) -> str:
    return parsed.metrics.get("global_outcome", "UNKNOWN")
