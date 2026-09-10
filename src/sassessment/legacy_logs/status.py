from __future__ import annotations

from typing import Any, Dict, List, Optional

from sassessment.legacy_logs.model import ParsedRecord

FRAMEWORK_SUCCESS_STATUSES = {"LOAD_OK", "OK", "OUT_OK", "SALIDA_OK"}
FRAMEWORK_FAILURE_STATUSES = {"LOAD_ERR", "OUT_ERR", "CANCEL"}


def _impact_rank(record: ParsedRecord) -> int:
    return {
        "INFO": 0, "UNKNOWN": 1, "DATA_QUALITY": 2, "WARNING": 3,
        "ERROR": 4, "FATAL": 5,
    }.get(record.normalized_impact, 1)


def derive_status_evidence(parsed_records: List[ParsedRecord]) -> Dict[str, Any]:
    framework_marks = [r for r in parsed_records if r.record_type == "FRAMEWORK_STATUS"
                       and r.status]
    fatal_messages = [r for r in parsed_records
                      if r.record_type in ("SAS_MESSAGE", "TB_LOG")
                      and r.normalized_impact == "ERROR"]
    zero_record_marks = [r for r in parsed_records
                         if r.record_type == "TB_LOG"
                         and (r.category or "") in ("EMPTY_REQUIRED_DATASET",
                                                    "ZERO_RECORDS_HISTORICIZE")]
    local_evidence: List[Dict[str, Any]] = []
    global_outcome: str = "UNKNOWN"

    terminal_marks = [mark for mark in framework_marks
                      if str(mark.status).upper() in FRAMEWORK_FAILURE_STATUSES]
    if terminal_marks:
        return {
            "global_outcome": "FAILED",
            "evidence": [{"record_id": mark.record_id, "status": mark.status,
                          "record_type": mark.record_type} for mark in terminal_marks],
        }
    if fatal_messages:
        return {
            "global_outcome": "FAILED",
            "evidence": [{"record_id": record.record_id,
                          "severity": record.source_severity,
                          "message": (record.message or record.raw_text)[:200]}
                      for record in fatal_messages],
        }
    if zero_record_marks:
        return {
            "global_outcome": "PARTIAL",
            "evidence": [{"record_id": record.record_id,
                          "category": record.category} for record in zero_record_marks],
        }
    if framework_marks:
        return {
            "global_outcome": "SUCCESS",
            "evidence": [{"record_id": mark.record_id, "status": mark.status}
                         for mark in framework_marks],
        }
    return {
        "global_outcome": "UNKNOWN",
        "evidence": [],
    }
