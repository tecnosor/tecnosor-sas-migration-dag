from __future__ import annotations

import re
from typing import Any, List, Optional

from sassessment.legacy_logs.model import ParsedRecord, RawRecord

DMF_ACTION_RE = re.compile(r"\b(INI|FIN|SLEEP|PRIORIDAD)\b")
ITERATION_RE = re.compile(r"exeBucleExploitation\s+(\d+)", re.IGNORECASE)
ERROR_ANCESTOR_WORDS = ("Sin registros", "no rows", "vacio", "EMPTY")


def unquote(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    text = text.strip()
    if len(text) > 1 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    return text


def split_delimited_fields(text: str) -> List[str]:
    segments: List[str] = []
    buffer: List[str] = []
    in_quote = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            in_quote = not in_quote
            buffer.append(char)
            index += 1
            continue
        if (not in_quote and char == "-" and index + 1 < len(text)
                and text[index + 1] == " "):
            segments.append("".join(buffer).strip())
            buffer = []
            index += 2
            continue
        buffer.append(char)
        index += 1
    segments.append("".join(buffer).strip())
    return segments


def parse_sas_duration(raw_text: Optional[str]) -> Optional[float]:
    if not raw_text:
        return None
    cleaned = re.sub(r"\s+", " ", raw_text).strip()
    match = re.match(r"^(\d+):(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?$", cleaned)
    if match:
        return (int(match.group(1)) * 3600 + int(match.group(2)) * 60
                + int(match.group(3))
                + (float("0." + match.group(4)) if match.group(4) else 0.0))
    match = re.match(r"^(\d+):(\d{1,2})(?:\.(\d{1,3}))?$", cleaned)
    if match:
        seconds = int(match.group(1)) * 60 + int(match.group(2))
        return seconds + (float("0." + match.group(3)) if match.group(3) else 0.0)
    match = re.match(r"^(\d+(?:\.\d+)?)$", cleaned)
    if match:
        return float(match.group(1))
    return None


def extract_environment_frequency_entity(context: Optional[str]) -> Dict[str, Any]:
    extracted: Dict[str, Any] = {
        "environment": None, "frequency": None, "entity_or_partition": None,
    }
    if not context:
        return extracted
    tokens = [token.strip(",").strip() for token in re.findall(r"\S+", context)]
    for token in tokens:
        upper = token.upper()
        if extracted["environment"] is None and upper in ("DEFAULT", "PROD", "PRO", "QA", "UAT", "TRN", "DEV"):
            extracted["environment"] = upper
        if extracted["frequency"] is None and re.match(r"^[DNMWH]$", upper):
            extracted["frequency"] = upper
        if extracted["entity_or_partition"] is None and re.match(r"^\d{2,4}$", token):
            extracted["entity_or_partition"] = int(token)
    return extracted


LIBREF_RE = re.compile(r"Libref\s+([A-Za-z0-9_]+)\s+was\s+successfully\s+(assigned|deassigned)")
LIBREF_ENGINE_RE = re.compile(r"Engine\(\d+\):\s+([A-Za-z0-9]+)")
LIBREF_PATH_RE = re.compile(r"Physical Name\(\d+\):\s+(\S.*)")
DATASET_CREATE_RE = re.compile(
    r"Table\s+([A-Za-z0-9_\.]+)\s+created,\s+with\s+(\d+)\s+rows?\s+and\s+(\d+)\s+columns")
DATASET_OBS_RE = re.compile(
    r"The data set\s+([A-Za-z0-9_\.]+)\s+has\s+(\d+)\s+observations?\s+and\s+(\d+)\s+variables")
ROWS_DELETED_RE = re.compile(r"(\d+)\s+rows?\s+were\s+deleted\s+from\s+([A-Za-z0-9_\.]+)")
ROWS_UPDATED_RE = re.compile(r"(\d+)\s+rows?\s+were\s+updated\s+in\s+([A-Za-z0-9_\.]+)")
OBS_ADDED_RE = re.compile(r"(\d+)\s+observations?\s+added")
NO_ROWS_RE = re.compile(r"No rows were selected")
RECURSIVE_TABLE_RE = re.compile(r"CREATE TABLE statement recursively references the target")
INCLUDE_NOTE_RE = re.compile(
    r"NOTE:\s+%INCLUDE\s+\(level\s+(\d+)\)\s+(file|resuming|ending)\s*(\S+)?")
INFILE_COMMAND_RE = re.compile(r"pipe=\"(.*?)\"")
TIMING_REAL_RE = re.compile(r"real\s+time\s+(\S+)")
TIMING_CPU_RE = re.compile(r"cpu\s+time\s+(\S+)")
DATASET_TABLE_RE = re.compile(r"NOTE:\s+Table\s+(\S+)\s+created")

FRAMEWORK_STATUS_KEYS_RE = re.compile(
    r"^(SALIDA|generated_out|OUT_STATUS|LOAD_STATUS|status|cod_err|"
    r"date_etl|num_date_ref_yyyymmdd|Hora leida para salida)\s*[:=]\s*(.+)$",
    re.IGNORECASE)

def _dataset_category(text: str):
    first_line = (text.splitlines() or [""])[0]
    if DATASET_CREATE_RE.search(text):
        match = DATASET_CREATE_RE.search(text)
        return "CREATE", match.group(1), int(match.group(2)), int(match.group(3))
    if NO_ROWS_RE.search(text):
        return "SELECT_ZERO", None, 0, 0
    if first_line.rstrip().endswith("seconds") or "real time" in text.lower():
        return None, None, None, None
    if "Tiempo de proceso total" in text:
        return None, None, None, None
    if DAMAGED_COUNTER_RE := OBS_ADDED_RE.search(text):
        return "APPEND", None, int(DAMAGED_COUNTER_RE.group(1)), None
    if ROWS_UPDATED_RE.search(text):
        match = ROWS_UPDATED_RE.search(text)
        return "UPDATE", match.group(2), int(match.group(1)), None
    if ROWS_DELETED_RE.search(text):
        match = ROWS_DELETED_RE.search(text)
        return "DELETE", match.group(2), int(match.group(1)), None
    if DATASET_OBS_RE.search(text):
        match = DATASET_OBS_RE.search(text)
        return "INSERT", match.group(1), int(match.group(2)), int(match.group(3))
    return None, None, None, None


def parse_tb_log(draft: RawRecord, record: ParsedRecord) -> ParsedRecord:
    record.record_type = "TB_LOG"
    joined = " ".join(line.strip() for line in draft.raw_text.splitlines())
    body = re.sub(r"^\s*TB_LOG:\s*", "", joined, count=1)
    segments = split_delimited_fields(body)
    if len(segments) < 6:
        record.parse_warnings.append("TB_LOG fields incomplete")
    record.timestamp_raw = segments[0] if segments else None
    record.timestamp = record.timestamp_raw
    if len(segments) > 1:
        record.user = unquote(segments[1])
    if len(segments) > 2 and re.match(r"^\d+$", (segments[2] or "").strip()):
        record.job_id = int((segments[2] or "").strip())
    else:
        record.job_id = segments[2] if len(segments) > 2 else None
    if len(segments) > 3:
        record.source_severity = (unquote(segments[3]) or "").upper() or None
    if len(segments) > 4:
        event_raw = unquote(segments[4]) or ""
        marker = DMF_ACTION_RE.search(event_raw)
        record.lifecycle_marker = marker.group(1) if marker else None
        iteration = ITERATION_RE.search(event_raw)
        if iteration:
            record.iteration = int(iteration.group(1))
        stripped_event = re.sub(r"^(Ini|Fin)\s+", "", event_raw, flags=re.IGNORECASE)
        first_word = re.match(r"[A-Za-z][A-Za-z0-9_]*", stripped_event)
        if first_word:
            record.component = first_word.group(0)
        record.event_name = stripped_event
    if len(segments) > 5:
        record.context = unquote(segments[5])
    extracted = extract_environment_frequency_entity(record.context)
    record.environment = extracted["environment"]
    record.frequency = extracted["frequency"]
    record.entity_or_partition = extracted["entity_or_partition"]
    if record.source_severity == "ERROR":
        record.normalized_impact = "ERROR"
        if "Sin registros" in (record.event_name or ""):
            record.category = "EMPTY_REQUIRED_DATASET"
            record.object_name = (record.event_name or "").split()[0]
    elif record.source_severity == "WARNING":
        record.normalized_impact = "WARNING"
        if "numRec" in (record.context or ""):
            record.category = "ZERO_RECORDS_HISTORICIZE"
    elif record.source_severity == "LOG":
        record.normalized_impact = "INFO"
    else:
        record.normalized_impact = "UNKNOWN"
        record.parse_warnings.append("TB_LOG level not recognized")
    return record


_DATA_QUALITY_HINTS = (
    "could not be performed", "is invalid", "_error_", "have been converted",
    "an error", "invalid",
)

UNFINISHED_MESSAGE_LINES = ("real time", "cpu time", "Levels:", "Engine(", "Physical Name(")


def parse_sas_message(draft: RawRecord, record: ParsedRecord, *, kind_hint: Optional[str] = None) -> ParsedRecord:
    lines = draft.raw_text.splitlines()
    first = lines[0] if lines else ""
    severity_match = re.match(r"^(NOTE|WARNING|ERROR):", first)
    record.record_type = "SAS_MESSAGE"
    record.source_severity = severity_match.group(1) if severity_match else None
    record.message = draft.raw_text
    lowered = (record.message or "").lower()
    if record.source_severity == "ERROR":
        record.normalized_impact = "ERROR"
    elif record.source_severity == "WARNING":
        record.normalized_impact = "WARNING"
    elif any(hint in lowered for hint in _DATA_QUALITY_HINTS):
        record.normalized_impact = "DATA_QUALITY"
    else:
        record.normalized_impact = "INFO"

    category, object_name, row_count, column_count = _dataset_category(record.message or "")
    if category:
        record.record_type = "DATASET_OPERATION"
        record.category = category
        record.object_name = object_name
        record.row_count = row_count
        record.column_count = column_count
        return record

    if "recursive" in lowered and "create table" in lowered:
        record.category = "RECURSIVE_TARGET_REFERENCE"
        record.normalized_impact = "WARNING"
        return record

    if "%INCLUDE" in (record.message or "")[:40]:
        record.record_type = "INCLUDE"
        match = INCLUDE_NOTE_RE.search(record.message or "")
        if match:
            record.category = match.group(2).upper()
            record.event_name = match.group(3)
            record.iteration = int(match.group(1))
        return record

    if "Tiempo de proceso total" in (record.message or ""):
        record.record_type = "TIMING"
        proc_match = re.search(r"NOTE:\s+(PROCEDURE\s+\w+|DATA\s+statement)", record.message)
        if proc_match:
            record.component = proc_match.group(1)
        real = TIMING_REAL_RE.search(record.message)
        cpu = TIMING_CPU_RE.search(record.message)
        record.duration_seconds = parse_sas_duration(real.group(1) if real else None)
        if cpu:
            record.context = (record.context or "") + f"cpu={parse_sas_duration(cpu.group(1))}"
        record.category = "TIMING"
        return record

    if "libref" in lowered:
        record.record_type = "LIBREF"
        match = LIBREF_RE.search(record.message)
        if match:
            record.object_name = match.group(1)
            record.status = match.group(2).upper()
            record.category = "LIBREF_" + match.group(2).upper()
        engine_match = LIBREF_ENGINE_RE.search(record.message)
        path_match = LIBREF_PATH_RE.search(record.message)
        if engine_match:
            record.context = (record.context or "") + " engine=" + engine_match.group(1)
        if path_match:
            record.context = (record.context or "") + " physical=" + path_match.group(1)[:160]
        return record

    if "columns" in lowered or "no rows" in lowered:
        return record

    if "infile" in lowered and "pipe" in lowered:
        record.record_type = "EXTERNAL_COMMAND"
        match = INFILE_COMMAND_RE.search(record.message)
        if match:
            record.object_name = match.group(1)[:200]
            record.category = "EXTERNAL_COMMAND"
        return record

    record.category = kind_hint or "SAS_NOTE_TEXT"
    return record


def parse_auto_var(draft: RawRecord, record: ParsedRecord) -> ParsedRecord:
    record.record_type = "SAS_MESSAGE"
    record.category = "SAS_AUTO_VARS"
    record.normalized_impact = "DATA_QUALITY"
    record.source_severity = "NOTE"
    record.message = record.raw_text
    return record


def parse_framework_status(draft: RawRecord, record: ParsedRecord) -> ParsedRecord:
    record.record_type = "FRAMEWORK_STATUS"
    record.normalized_impact = "INFO"
    for line in draft.raw_text.splitlines():
        match = FRAMEWORK_STATUS_KEYS_RE.match(line.strip())
        if not match:
            continue
        key = match.group(1).lower()
        raw_value = match.group(2).strip()
        if key == "generated_out":
            record.row_count = int(raw_value) if raw_value.isdigit() else None
            record.category = "OUTPUT_GENERATED"
            record.status = "OK" if raw_value == "1" else "OUT_ERR"
        elif key == "salida":
            record.row_count = int(raw_value) if raw_value.isdigit() else None
            record.category = "SALIDA"
            record.status = "OK" if raw_value == "1" else "OUT_ERR"
        elif key in ("load_status", "out_status", "status"):
            record.status = raw_value.upper()
            record.category = "FRAMEWORK_STATUS_MARK"
            if raw_value.upper() in ("LOAD_ERR", "OUT_ERR", "CANCEL"):
                record.normalized_impact = "ERROR"
            elif raw_value.upper() in ("LOAD_OK", "OK"):
                record.normalized_impact = "INFO"
        elif key == "cod_err":
            record.status = f"COD_ERR={raw_value}"
            record.normalized_impact = "WARNING" if raw_value not in ("0",) else "INFO"
        elif key == "date_etl":
            record.category = "ETL_DATE"
            record.timestamp_raw = raw_value
        elif key == "num_date_ref_yyyymmdd":
            record.category = "DATE_REFERENCE"
            record.timestamp_raw = raw_value
    return record


def parse_checkpoint_block(draft: RawRecord, record: ParsedRecord) -> ParsedRecord:
    record.record_type = "CHECKPOINT"
    for line in draft.raw_text.splitlines():
        current = re.match(r"^#Tiempo actual:\s*(.+)$", line)
        elapsed = re.match(r"^#Desde el comienzo han pasado (\d+) hs, (\d+) mins, (\d+) seg", line)
        previous = re.match(r"^\$Desde el anterior hito han pasado (\d+) hs, (\d+) mins, (\d+) seg", line)
        if current:
            record.timestamp_raw = current.group(1)
        elif elapsed:
            record.duration_seconds = _hs_mins_secs_seconds(1, int(elapsed.group(1)),
                                                            int(elapsed.group(2)),
                                                            int(elapsed.group(3)))
        elif previous:
            previous_seconds = _hs_mins_secs_seconds(
                hours=int(previous.group(1)),
                minutes=int(previous.group(2)), seconds=int(previous.group(3)))
            record.context = (record.context or "") + f" prev={previous_seconds}"
    record.normalized_impact = "INFO"
    return record


def _hs_mins_secs_seconds(hours: int, minutes: int, seconds: int) -> Optional[float]:
    if None in (hours, minutes, seconds):
        return None
    return hours * 3600 + minutes * 60 + seconds


def parse_time_sleep(draft: RawRecord, record: ParsedRecord) -> ParsedRecord:
    record.record_type = "TIME_SLEEP"
    record.category = "POLLING_SLEEP"
    match = re.match(r"^time_sleep:\s*(\d+)", record.raw_text.strip())
    if match:
        record.duration_seconds = float(int(match.group(1)))
    record.normalized_impact = "INFO"
    return record


SOURCE_NEW_RE = re.compile(r"^(\d+)\s+\+\s?(.*)$")
SOURCE_CONT_RE = re.compile(r"^(\d+)\s*!\+\s?(.*)$")


def parse_sas_source(draft: RawRecord, record: ParsedRecord) -> ParsedRecord:
    record.record_type = "SAS_SOURCE"
    pieces: List[str] = []
    sas_line: Optional[int] = None
    continuation_count = 0
    for line in draft.raw_text.splitlines():
        new_match = SOURCE_NEW_RE.match(line)
        cont_match = SOURCE_CONT_RE.match(line)
        if new_match:
            if sas_line is None:
                sas_line = int(new_match.group(1))
            pieces.append(new_match.group(2))
        elif cont_match:
            continuation_count += 1
            pieces.append(cont_match.group(2))
        else:
            pieces.append(line.strip())
    record.message = "\n".join(p.strip() for p in pieces)
    record.sas_source_line = sas_line
    record.category = f"SOURCE continuations={continuation_count}"
    record.normalized_impact = "INFO"
    return record


def parse_page_header(draft: RawRecord, record: ParsedRecord) -> ParsedRecord:
    record.record_type = "PAGE_HEADER"
    record.normalized_impact = "INFO"
    record.message = record.raw_text
    return record


def parse_unknown(draft: RawRecord, record: ParsedRecord) -> ParsedRecord:
    record.record_type = "RAW_UNKNOWN"
    record.parse_warnings.append("No deterministic rule matched")
    record.message = record.raw_text
    return record


def record_from_draft(draft: RawRecord, file_id: str) -> ParsedRecord:
    record = ParsedRecord(file_id=file_id, start_line=draft.start_line,
                          end_line=draft.end_line, start_offset=draft.start_offset,
                          end_offset=draft.end_offset, raw_text=draft.raw_text)
    anchor = draft.anchor
    if anchor == "TB_LOG":
        return parse_tb_log(draft, record)
    if anchor == "SAS_MESSAGE":
        return parse_sas_message(draft, record)
    if anchor == "SAS_AUTOVAR":
        return parse_auto_var(draft, record)
    if anchor == "FRAMEWORK_STATUS":
        return parse_framework_status(draft, record)
    if anchor == "CHECKPOINT":
        return parse_checkpoint_block(draft, record)
    if anchor == "TIME_SLEEP":
        return parse_time_sleep(draft, record)
    if anchor == "CALL_DMF":
        return parse_call_dmf(draft, record)
    if anchor == "PAGE_HEADER":
        return parse_page_header(draft, record)
    if anchor == "SAS_SOURCE":
        return parse_sas_source(draft, record)
    return parse_unknown(draft, record)


def parse_call_dmf(draft: RawRecord, record: ParsedRecord) -> ParsedRecord:
    record.record_type = "CALL_DMF"
    for line in draft.raw_text.splitlines():
        match = re.match(r"^CALL_DMF:\s+(.*)", line.strip())
        if match:
            record.context = match.group(1).strip()
            for token in re.findall(r"[A-Za-z0-9_]+", record.context):
                if re.match(r"^[A-Z]{2,4}\d{4,6}_", token):
                    record.object_name = token
                    record.component = token.lower()
                    break
    record.normalized_impact = "INFO"
    return record
