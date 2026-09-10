from __future__ import annotations

import re
from typing import Iterable, Iterator, List, Optional

from sassessment.legacy_logs.model import RawRecord

RE_TB_LOG = re.compile(r"^TB_LOG:")
RE_SAS_MESSAGE = re.compile(r"^(NOTE|WARNING|ERROR):")
RE_SOURCE_NEW = re.compile(r"^(\d+)\s+\+\s?(.*)$")
RE_SOURCE_CONT = re.compile(r"^(\d+)\s+!\+\s?(.*)$")
RE_CONT_ONLY = re.compile(r"^!\+\s?(.*)$")
RE_PAGE_HEADER = re.compile(r"^(\x0c)?\s*(\d+)\s+Sistema SAS\s*$")
RE_PAGE_DATE = re.compile(
    r"^[a-zA-Z]{3,},?\s+\d{1,2}\s+de\s+[a-zA-Z]+,?\s+de\s+\d{4}\s+\d{1,2}:\d{2}:\d{2}")
RE_CHECKPOINT_CURRENT = re.compile(r"^#Tiempo actual:")
RE_CHECKPOINT_ELAPSED = re.compile(r"^#Desde el comienzo")
RE_CHECKPOINT_PREV = re.compile(r"^\$Desde el anterior hito")
RE_TIME_SLEEP = re.compile(r"^time_sleep:\s*(\d+)")
RE_CALL_DMF = re.compile(r"^CALL_DMF:")
RE_STATUS_KV = re.compile(
    r"^(SALIDA|generated_out|OUT_STATUS|LOAD_STATUS|Hora leida para salida|status|cod_err|date_etl|num_date_ref_yyyymmdd)"
    r"\s*[:=]\s*", re.IGNORECASE)
RE_AUTOVAR = re.compile(r"^_ERROR_\s*[=\s]")


def detect_anchor(content: str) -> Optional[str]:
    if RE_PAGE_HEADER.match(content):
        return "PAGE_HEADER"
    if RE_TB_LOG.match(content):
        return "TB_LOG"
    if RE_SOURCE_NEW.match(content):
        return "SAS_SOURCE"
    if RE_CONT_ONLY.match(content):
        return "SAS_SOURCE_CONT"
    if RE_SAS_MESSAGE.match(content):
        return "SAS_MESSAGE"
    if RE_CHECKPOINT_CURRENT.match(content):
        return "CHECKPOINT"
    if RE_CHECKPOINT_ELAPSED.match(content):
        return "CHECKPOINT"
    if RE_CHECKPOINT_PREV.match(content):
        return "CHECKPOINT"
    if RE_TIME_SLEEP.match(content):
        return "TIME_SLEEP"
    if RE_CALL_DMF.match(content):
        return "CALL_DMF"
    if RE_STATUS_KV.match(content):
        return "FRAMEWORK_STATUS"
    if RE_AUTOVAR.match(content):
        return "SAS_AUTOVAR"
    return None


def is_tb_log_continuation(current_text: str, next_content: str) -> bool:
    """Quote-aware continuation detection for wrapped TB_LOG records."""
    if current_text.count('"') % 2 == 1:
        return True
    stripped = next_content.lstrip()
    if not stripped:
        return True
    if current_text.rstrip().endswith("-"):
        return True
    if stripped.startswith('"') or stripped.startswith("-"):
        return True
    return False


def is_message_continuation(content: str) -> bool:
    if not content.strip():
        return True
    if RE_PAGE_DATE.match(content):
        return False
    return content.startswith(" ")


class LogAssembler:
    """Streams physical lines into draft logical records with provenance."""

    def __init__(self, file_id: str = "") -> None:
        self.file_id = file_id
        self.stack: List[RawRecord] = []
        self.current: Optional[RawRecord] = None

    def flush_current(self) -> Optional[RawRecord]:
        record, self.current = self.current, None
        if record is not None and record.raw_text:
            self.stack.append(record)
            return record
        return None

    def consume(self, line: str, line_number: int, offset: int, end_offset: int) -> None:
        content = line.rstrip()
        anchor = detect_anchor(content)
        if not content.strip():
            if getattr(self, "page_date_pending", False):
                return
            if self.current is not None:
                self.current.raw_text += "\n" + content
                self.current.end_line = line_number
                self.current.end_offset = end_offset
            return
        if getattr(self, "page_date_pending", False) and RE_PAGE_DATE.match(content):
            header = self.stack[-1]
            header.raw_text += "\n" + content
            header.end_line = line_number
            header.end_offset = end_offset
            self.page_date_pending = False
            return
        self.page_date_pending = False

        if anchor == "PAGE_HEADER":
            self.flush_current()
            header = RawRecord(anchor="PAGE_HEADER",
                               start_line=line_number, end_line=line_number,
                               start_offset=offset, end_offset=end_offset)
            header.raw_text = content.lstrip("\x0c").strip()
            self.stack.append(header)
            self.page_date_pending = True
            return

        if self.current is not None:
            kind = self.current.anchor
            if kind == "TB_LOG":
                if is_tb_log_continuation(self.current.raw_text, content):
                    self.current.raw_text += "\n" + content
                    self.current.end_line = line_number
                    self.current.end_offset = end_offset
                    return
                self.flush_current()
            elif kind == "SAS_SOURCE":
                if anchor == "SAS_SOURCE_CONT" or re.match(r"^\d+\s+!\+\s?", content):
                    self.current.raw_text += "\n" + content
                    self.current.end_line = line_number
                    self.current.end_offset = end_offset
                    return
                self.flush_current()
            elif kind == "SAS_MESSAGE" or kind == "SAS_AUTOVAR":
                if anchor is None:
                    self.current.raw_text += "\n" + content
                    self.current.end_line = line_number
                    self.current.end_offset = end_offset
                    return
                self.flush_current()
            elif kind in ("FRAMEWORK_STATUS", "CHECKPOINT", "TIME_SLEEP", "CALL_DMF"):
                if content.startswith(" "):
                    self.current.raw_text += "\n" + content
                    self.current.end_line = line_number
                    self.current.end_offset = end_offset
                    return
                self.flush_current()

        if anchor is None:
            record = RawRecord(anchor="RAW_UNKNOWN",
                               start_line=line_number, end_line=line_number,
                               start_offset=offset, end_offset=end_offset)
            record.raw_text = content
            self.stack.append(record)
            return

        self.flush_current()
        record = RawRecord(anchor=anchor, start_line=line_number,
                           end_line=line_number, start_offset=offset,
                           end_offset=end_offset)
        record.raw_text = content
        if anchor == "TB_LOG":
            self.current = record
        elif anchor in ("SAS_MESSAGE", "SAS_AUTOVAR"):
            self.current = record
        elif anchor in ("FRAMEWORK_STATUS", "CHECKPOINT", "TIME_SLEEP", "CALL_DMF"):
            self.stack.append(record)
        elif anchor == "SAS_SOURCE":
            self.current = record
        else:
            self.stack.append(record)
    def finish(self) -> Optional[RawRecord]:
        return self.flush_current()


def assemble_records(handle, file_id: str) -> List[RawRecord]:
    assembler = LogAssembler(file_id)
    offset = 0
    number = 0
    for raw in handle:
        number += 1
        content = raw.rstrip("\r\n")
        assembler.consume(content, number, offset, offset + len(content))
        offset += len(raw)
    assembler.finish()
    return assembler.stack
