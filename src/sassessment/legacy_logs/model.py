from __future__ import annotations

import hashlib
import json
from pathlib import Path
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

PARSER_VERSION = "dmf-log/1.0.0"

RECORD_TYPES = (
    "TB_LOG", "SAS_MESSAGE", "SAS_SOURCE", "PAGE_HEADER", "INCLUDE",
    "LIBREF", "DATASET_OPERATION", "TIMING", "EXTERNAL_COMMAND",
    "CHECKPOINT", "FRAMEWORK_STATUS", "LIFECYCLE_INLINE", "RAW_UNKNOWN",
)

SEVERITIES = ("NOTE", "WARNING", "ERROR", "LOG")
IMPACTS = ("INFO", "WARNING", "DATA_QUALITY", "ERROR", "FATAL", "UNKNOWN")


@dataclass
class ParsedRecord:
    file_id: str
    record_type: str = "RAW_UNKNOWN"
    source_severity: Optional[str] = None
    normalized_impact: str = "UNKNOWN"
    category: Optional[str] = None
    timestamp_raw: Optional[str] = None
    timestamp: Optional[str] = None
    user: Optional[str] = None
    sas_source_line: Optional[int] = None
    job_id: Any = None
    entity_or_partition: Any = None
    frequency: Any = None
    environment: Any = None
    iteration: Any = None
    component: Optional[str] = None
    event_name: Optional[str] = None
    lifecycle_marker: Optional[str] = None
    status: Optional[str] = None
    object_name: Optional[str] = None
    row_count: Optional[int] = None
    column_count: Optional[int] = None
    duration_seconds: Optional[float] = None
    message: Optional[str] = None
    context: Optional[str] = None
    start_line: int = 1
    end_line: int = 1
    start_offset: int = 0
    end_offset: int = 0
    raw_text: str = ""
    rule_id: str = "RULE-RAW-000"
    parse_warnings: List[str] = field(default_factory=list)
    parser_version: str = PARSER_VERSION

    record_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["record_id"] = self.record_id
        return data


def record_to_dict(record: ParsedRecord) -> Dict[str, Any]:
    return record.to_dict()


@dataclass
class RawRecord:
    """Streaming assembly unit before semantic classification."""
    anchor: str
    lines: List[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0
    start_offset: int = 0
    end_offset: int = 0
    raw_text: str = ""
    anchor_mode: str = "unknown"


@dataclass
class LifecycleStage:
    component: str
    job_id: Any
    iteration: Any
    entity_or_partition: Any
    start_record_id: str
    end_record_id: Optional[str] = None
    complete: bool = False
    start_timestamp: Optional[float] = None
    end_timestamp: Optional[float] = None
    status_evidence: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    source_level: Optional[str] = None
    marker: str = "INI"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedLog:
    records: List[ParsedRecord] = field(default_factory=list)
    lifecycle: List[LifecycleStage] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    file_id: str = ""


def write_parse_summary(parsed: ParsedLog, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "file_id": parsed.file_id,
        "metrics": parsed.metrics,
        "record_count": len(parsed.records),
        "lifecycle_count": len(parsed.lifecycle),
        "records": [record_to_dict(r) for r in parsed.records],
        "lifecycle": [stage.to_dict() for stage in parsed.lifecycle],
    }
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                           encoding="utf-8")
    return destination
