from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
NS_MAIN_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def read_xlsx(path: Path) -> Dict[str, list]:
    """Parse an XLSX workbook with stdlib only (zipfile + ElementTree).

    Returns ``{sheet_name: [row_dict, ...]}`` where each row dict is keyed by
    the column text of the detected header row. Blank leading rows are skipped
    when searching for the most data-dense header line.
    """
    path = Path(path)
    if not path.is_file():
        raise OSError(f"workbook not found: {path}")
    with zipfile.ZipFile(path) as zf:
        shared = _read_shared_strings(zf)
        sheet_targets = _sheet_targets(zf)
        sheets: Dict[str, list] = {}
        for sheet_name, target in sheet_targets:
            rows = _read_sheet(zf, shared, target)
            if rows:
                sheets[sheet_name] = rows
        return sheets


def _read_shared_strings(zf: zipfile.ZipFile) -> list:
    try:
        root = ElementTree.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for string_node in root.findall(f"{NS_MAIN}si"):
        parts = [node.text or "" for node in string_node.iter() if node.tag == f"{NS_MAIN}t"]
        strings.append("".join(parts))
    return strings


def _sheet_targets(zf: zipfile.ZipFile) -> list:
    workbook = ElementTree.fromstring(zf.read("xl/workbook.xml"))
    rel_root = ElementTree.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rels: Dict[str, str] = {}
    for rel in rel_root.findall(f"{NS_PKG_REL}Relationship"):
        rels[rel.attrib["Id"]] = rel.attrib["Target"]
    targets: list = []
    for sheet in workbook.iter(f"{NS_MAIN}sheet"):
        rid = sheet.attrib.get(f"{NS_REL_NS}id", "")
        target = rels.get(rid, "")
        if target.startswith("/"):
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = "xl/" + target
        targets.append((sheet.attrib.get("name", "sheet"), target))
    return targets


def _read_sheet(zf: zipfile.ZipFile, shared: list, target: str) -> list:
    try:
        root = ElementTree.fromstring(zf.read(target))
    except (KeyError, ValueError):
        return []
    raw_rows: list = []
    for row_node in root.iter(f"{NS_MAIN}row"):
        cells = [_cell_value(cell_node, shared) for cell_node in row_node.iter(f"{NS_MAIN}c")]
        raw_rows.append([str(cell or "").strip() for cell in cells])

    header_row = _choose_header(raw_rows)
    if header_row is None:
        return []
    header_index, header_cells = header_row
    named_columns = sum(1 for cell in header_cells if cell)
    if named_columns == 0:
        return []
    records: list = []
    for cells in raw_rows[header_index + 1:]:
        if not any(cells):
            continue
        record = {}
        for column_name, value in zip(header_cells, cells):
            if column_name:
                record[column_name] = value
        if record:
            records.append(record)
    return records


def _choose_header(raw_rows: list) -> Optional[Tuple[int, list]]:
    best: Optional[Tuple[Tuple[int, int], int, list]] = None
    for index, cells in enumerate(raw_rows[:25]):
        named = sum(1 for cell in cells if cell and re.match(r"\w", str(cell)))
        non_empty = sum(1 for cell in cells if cell and str(cell).strip())
        score = (named, non_empty)
        if best is None or score > best[0]:
            best = (score, index, cells)
    if best is None or best[0][0] == 0:
        return None
    return best[1], best[2]


def _cell_value(node: ElementTree.Element, shared: list) -> str:
    cell_type = node.attrib.get("t", "n")
    value_node = node.find(f"{NS_MAIN}v")
    if cell_type == "s":
        if value_node is None or value_node.text is None:
            return ""
        index = int(value_node.text)
        return shared[index] if 0 <= index < len(shared) else ""
    if cell_type == "inlineStr":
        text = "".join(
            (item.text or "") for item in node.iter(f"{NS_MAIN}t")
        )
        return text
    if value_node is None or value_node.text is None:
        return ""
    return value_node.text


_TABLE_HEADER_HINTS = {"object_name", "table", "table_name", "tabla", "object",
                       "proceso", "process", "job", "programa", "sas_program",
                       "sas_program", "application", "aplicacion"}


def looks_like_inventory(header: list) -> bool:
    normalized = [str(cell).strip().lower().replace(" ", "_") for cell in header if cell]
    return any(hint in normalized for hint in _TABLE_HEADER_HINTS)


def required_archive_file(path: Path) -> bool:
    return path.suffix.lower() == ".xlsx"
