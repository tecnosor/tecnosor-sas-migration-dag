from __future__ import annotations

import csv
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from sassessment.nodes.base import (
    HumanRequestSpec,
    NodeContext,
    NodeRegistry,
    NodeResult,
)

SAS_EXTENSIONS = {".sas"}
DICTIONARY_EXTENSIONS = {".csv", ".tsv"}
LOG_EXTENSIONS = {".log", ".txt"}

INCLUDE_RE = re.compile(r"^\s*%include\s+([^;]+);", re.IGNORECASE)
MACRO_DEF_RE = re.compile(r"^\s*%macro\s+(\w+)", re.IGNORECASE)
DATA_STEP_RE = re.compile(r"^\s*data\s+([\w\.]+)\s*;", re.IGNORECASE)
SET_MERGE_RE = re.compile(r"^\s*(?:set|merge|update)\s+([^;]+);", re.IGNORECASE)
CREATE_TABLE_RE = re.compile(r"create\s+table\s+([\w.]+)", re.IGNORECASE)
INSERT_INTO_RE = re.compile(r"insert\s+into\s+([\w.]+)", re.IGNORECASE)
FROM_RE = re.compile(r"\bfrom\s+([\w.]+)", re.IGNORECASE)
JOIN_RE = re.compile(r"\bjoin\s+([\w.]+)", re.IGNORECASE)
LOG_EVENT_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\s+PROCESS\s+(?P<process>\S+)\s+"
    r"(?P<event>START|END|FINISHED)(?:\s+duration_s=(?P<duration>\d+))?", re.IGNORECASE)


def build_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register(node_sys_workspace, names=["sys.workspace"])
    registry.register(node_intake_register, names=["intake.register"])
    registry.register(node_intake_coverage, names=["intake.coverage"])
    registry.register(node_inventory_extract, names=["inventory.extract"])
    registry.register(node_sas_discover, names=["sas.discover"])
    registry.register(node_runtime_correlate, names=["runtime.correlate"])
    registry.register(node_dba_request, names=["lineage.dba_request"])
    registry.register(node_doc_mapping, names=["doc.map_apps"])
    registry.register(node_ingest_dba, names=["lineage.ingest_dba"])
    registry.register(node_quality_gate, names=["quality.gate"])
    registry.register(node_audit_export, names=["audit.export"])
    return registry


def node_sys_workspace(context: NodeContext) -> NodeResult:
    problems = context.layout.validate()
    if problems:
        return NodeResult(status="failed", summary="workspace invalid",
                          limitations=[str(problem) for problem in problems])
    evidence = context.register_evidence(
        "system", "workspace validated", locator=str(context.layout.repo_root))
    return NodeResult(status="success", summary="workspace valid",
                      evidence_used=[evidence], confidence="CONFIRMED")



POWER_WORDS = ("complete", "finished", "end", "success", "done", "running",
               "start", "error", "job", "process", "hour", "minute", "second",
               "duration", "elapsed", "status", "date", "timestamp")

LEGACY_TS_PATTERNS = (
    r"(\d{4}-\d{2}-\d{2})([ T])?(\d{2}:\d{2}(:\d{2})?)?\b",
    r"\b(\d{2}/\d{2}/\d{4})([ ]?\d{1,2}:\d{2}(:\d{2})?)?\b",
    r"\b(\d{2}-\d{2}-\d{2})[ ]?(\d{1,2}:\d{2}(:\d{2})?)?\b",
    r"\b(\d{1,2}:\d{2}:\d{2}(\.\d+)?)\b",
)


def parse_legacy_log_event(line: str) -> Optional[Dict[str, Any]]:
    """Heuristic event extraction for legacy/free-form scheduler log lines."""
    if not line or len(line) < 12 or line.startswith("#"):
        return None
    matched_ts: Optional[str] = None
    for ts_pattern in LEGACY_TS_PATTERNS:
        ts_match = re.search(ts_pattern, line)
        if ts_match:
            matched_ts = ts_match.group(0)
            break
    if not matched_ts:
        return None
    words = re.findall(r"[A-Za-z][A-Za-z0-9_\-]{3,}", line)
    candidates = [word for word in words
                  if word.lower() not in POWER_WORDS and word.lower() != "process"]
    syslog_style = re.compile(r"^[A-Z]{2,4}\d{3,5}[A-Z]?$")
    candidates = [word for word in candidates if not syslog_style.match(word)] or candidates
    if not candidates:
        return None
    process_token = candidates[0]
    line_lower = line.lower()
    finish_signals = ("complete", "finished", "end", "done", "ok", "success", "csar")
    duration_match = re.search(r"elapsed|duration[ =:]+(\d+)", line_lower)
    event_kind = "END" if any(signal in line_lower for signal in finish_signals) else "START"
    duration_value = duration_match.group(1) if duration_match and duration_match.groups() else ""
    return {
        "ts": matched_ts,
        "process": process_token,
        "event": event_kind,
        "duration": duration_value,
    }

def node_intake_register(context: NodeContext) -> NodeResult:
    from sassessment.intake.registration import register_batch
    candidates = [entry for entry in sorted(context.layout.intake_raw.iterdir())
                  if entry.is_dir() and not entry.name.startswith(".")]
    if not candidates:
        return NodeResult(
            status="waiting_for_input",
            summary="no raw batches under intake/raw/<source-batch-id>/ yet",
            confidence="UNKNOWN",
            limitations=["place material in intake/raw/<source-batch-id>/"])

    for batch_dir in candidates:
        if context.repo.get_meta(f"batch:registered:{batch_dir.name}"):
            continue
        outcome = register_batch(
            context.config.repo_root, batch_dir, context.repo, context.audit)
        context.repo.set_meta(f"batch:registered:{batch_dir.name}", outcome.batch_id)
        evidence = context.register_evidence(
            "batch",
            f"batch {outcome.batch_id} registered with {outcome.file_count} files",
            locator=outcome.manifest_path)
        context.register_finding(
            f"Material batch {outcome.batch_id} ingested ({outcome.file_count} files, "
            f"{outcome.duplicate_count} duplicates)",
            "intake", confidence="CONFIRMED", evidence_ids=[evidence],
            extraction_method="file-intake-registry", scope=str(batch_dir))

    return NodeResult(status="success", summary="batch registration complete",
                      confidence="CONFIRMED", metrics={"batches": len(candidates)})


def node_intake_coverage(context: NodeContext) -> NodeResult:
    coverage: Dict[str, int] = defaultdict(int)
    for manifest_path in sorted(context.layout.intake_manifests.glob("*.yaml")):
        manifest = _read_yaml(manifest_path)
        if not manifest:
            continue
        for entry in manifest.get("files", []):
            coverage[str(entry.get("media_type", "unknown"))] += 1

    has_sas = coverage.get("sas-source", 0) > 0
    has_runtime = coverage.get("log-text", 0) > 0
    coverage_summary = ", ".join(f"{kind}={count}" for kind, count in sorted(coverage.items()))
    evidence = context.register_evidence("coverage", f"coverage: {coverage_summary}")
    if not has_sas:
        context.register_gap("no SAS sources found in raw material", "phase1")
    if not has_runtime:
        context.request_human_input(HumanRequestSpec(
            title="Runtime evidence (scheduler export or logs) not supplied",
            missing_info="scheduler.logs",
            reason="runtime correlation needs scheduler/log exports to derive frequency and last execution",
            priority="OPTIONAL_ENRICHMENT",
            retrieval_attempted="searched intake/raw for .log/.txt runtime exports",
            expected_provider="Subsidiary operations team",
            accepted_formats="csv, txt, log, xlsx",
            security_notes="scheduler exports only; no credentials required",
        ))
    context.log(f"coverage: {coverage_summary}")
    return NodeResult(
        status="success",
        summary=f"coverage assessed ({coverage_summary})",
        evidence_used=[evidence],
        metrics=dict(coverage),
        confidence="CONFIRMED" if has_sas else "INFERRED",
    )


INVENTORY_HEADER_HINTS = ("object_name", "table", "table_name", "tabla", "object", "schema", "esquema")
PROCESS_HEADER_HINTS = ("proceso", "process", "job", "programa", "sas_program", "program")
APPLICATION_HINTS = ("application", "aplicacion", "app", "owner_app", "system", "sistema")


def _read_workbook_sheets(xlsx_path: Path) -> Dict[str, list]:
    from sassessment.intake.xlsx_reader import read_xlsx
    try:
        return read_xlsx(xlsx_path)
    except (OSError, zipfile.BadZipFile, KeyError):
        return {}


def _sheet_classifier(header_keys: list) -> str:
    lowered = {str(key).strip().lower() for key in header_keys}
    if lowered.intersection(INVENTORY_HEADER_HINTS):
        return "inventory"
    if lowered.intersection(PROCESS_HEADER_HINTS):
        return "process"
    return "other"


def _lookup_hint(record: dict, hints: tuple) -> str:
    for key in record:
        if str(key).strip().lower() in hints:
            value = str(record[key]).strip()
            if value:
                return value
    return ""


def node_inventory_extract(context: NodeContext) -> NodeResult:
    workbook_files: List[Path] = []
    legacy_xls: List[str] = []
    for manifest_path in sorted(context.layout.intake_manifests.glob("*.yaml")):
        manifest = _read_yaml(manifest_path)
        if not manifest:
            continue
        batch_dir = Path(str(manifest.get("raw_dir", "")))
        for entry in manifest.get("files", []):
            media_type = str(entry.get("media_type"))
            file_path = batch_dir / str(entry.get("path", ""))
            if media_type == "office-excel" and file_path.is_file() and file_path.suffix.lower() == ".xlsx":
                workbook_files.append(file_path)
            elif media_type == "office-excel-legacy":
                legacy_xls.append(str(entry.get("path", "")))

    for legacy_path in legacy_xls:
        short_name = legacy_path.split("/")[-1]
        context.register_gap(
            f"legacy .xls workbook needs conversion to .xlsx or csv: {short_name}",
            "phase1")
    if not workbook_files:
        return NodeResult(
            status="waiting_for_input",
            summary="no .xlsx inventory workbooks available",
            confidence="UNKNOWN",
            limitations=["place .xlsx inventories under intake/raw/<source-batch-id>/",
                         "legacy .xls must be converted to .xlsx or csv"])
    extracted_tables = 0
    extracted_processes = 0
    mapped_rows = 0
    for xlsx_path in sorted(workbook_files):
        sheets = _read_workbook_sheets(xlsx_path)
        sheet_evidence: list = []
        for sheet_name, records in sorted(sheets.items()):
            if not records:
                continue
            headers = sorted(records[0].keys())
            evidence = context.register_evidence(
                "xlsx-inventory",
                f"workbook {xlsx_path.name}, sheet {sheet_name}: {len(records)} rows, "
                f"columns: {', '.join(headers[:10])}",
                locator=f"xlsx:{xlsx_path.name}#{sheet_name}")
            inventory_kind = _sheet_classifier(headers)
            if inventory_kind == "inventory":
                for record in records:
                    table_name = _lookup_hint(record, INVENTORY_HEADER_HINTS)
                    application = _lookup_hint(record, APPLICATION_HINTS)
                    if not table_name:
                        continue
                    context.upsert_domain_object("table", table_name, evidence_id=evidence)
                    extracted_tables += 1
                    if application:
                        ownership_evidence = context.register_evidence(
                            "application",
                            f"{table_name} owned by {application}",
                            locator=f"xlsx:{xlsx_path.name}#{sheet_name}")
                        context.add_lineage_edge(
                            f"app:{application}",
                            f"db:{table_name.strip().upper()}", "owns",
                            extraction_method="xlsx-inventory",
                            evidence_ids=[ownership_evidence],
                            confidence="CONFIRMED",
                            validation_status="VALIDATED")
                        mapped_rows += 1
            elif inventory_kind == "process":
                for record in records:
                    process_name = _lookup_hint(record, PROCESS_HEADER_HINTS)
                    if not process_name:
                        continue
                    context.upsert_domain_object("sas_process", process_name,
                                                 evidence_id=evidence)
                    extracted_processes += 1
    if not any(expected for expected in (extracted_tables, extracted_processes)):
        return NodeResult(
            status="skipped",
            summary="xlsx workbooks found but no recognizable inventory headers",
            confidence="INFERRED",
            limitations=["expected headers like object_name/table/proceso for table or process inventories"])
    return NodeResult(
        status="success",
        summary=f"extracted {extracted_tables} table(s) and {extracted_processes} process(es) "
                f"from xlsx inventories",
        metrics={"tables": extracted_tables, "processes": extracted_processes,
                 "mappings": mapped_rows},
        confidence="INFERRED")


def node_sas_discover(context: NodeContext) -> NodeResult:
    sas_files: List[Path] = []
    for manifest_path in sorted(context.layout.intake_manifests.glob("*.yaml")):
        manifest = _read_yaml(manifest_path)
        if not manifest:
            continue
        batch_dir = Path(str(manifest.get("raw_dir", "")))
        for entry in manifest.get("files", []):
            if str(entry.get("media_type")) == "sas-source":
                candidate = batch_dir / str(entry.get("path", ""))
                if candidate.is_file():
                    sas_files.append(candidate)

    if not sas_files:
        return NodeResult(
            status="waiting_for_input",
            summary="no SAS sources available for discovery",
            confidence="UNKNOWN",
            limitations=["SAS sources must be staged under intake/raw/<source-batch-id>/"])

    process_map: Dict[str, Dict[str, List[str]]] = {}
    includes: List[str] = []
    for sas_file in sas_files:
        text = sas_file.read_text(encoding="utf-8", errors="replace")
        process_name = sas_file.stem.lower()
        detail: Dict[str, List[str]] = {"reads": [], "writes": [], "macros": []}
        for match in SET_MERGE_RE.finditer(text):
            for token in match.group(1).split():
                detail["reads"].append(token.strip())
        for match in CREATE_TABLE_RE.finditer(text):
            detail["writes"].append(match.group(1))
        for match in INSERT_INTO_RE.finditer(text):
            detail["writes"].append(match.group(1))
        for match in FROM_RE.finditer(text):
            detail["reads"].append(match.group(1))
        for match in JOIN_RE.finditer(text):
            detail["reads"].append(match.group(1))
        for match in DATA_STEP_RE.finditer(text):
            target = match.group(1)
            if "." in target:
                detail["writes"].append(target)
        for match in MACRO_DEF_RE.finditer(text):
            detail["macros"].append(match.group(1))
        for match in INCLUDE_RE.finditer(text):
            for token in match.group(1).replace('"', " ").replace("'", " ").split():
                includes.append(token)
        process_map[process_name] = detail

    evidence_ids: List[str] = []
    for process_name, detail in sorted(process_map.items()):
        evidence = context.register_evidence(
            "sas-analysis", f"static analysis of {process_name}",
            locator=f"sas-file:{process_name}")
        evidence_ids.append(evidence)
        context.upsert_domain_object("sas_process", process_name, evidence_id=evidence)
        for table in sorted(set(detail["reads"])):
            if "." not in table:
                continue
            context.upsert_domain_object("table", table,
                                         schema_name=_schema_of(table),
                                         evidence_id=evidence)
            context.add_lineage_edge(
                f"sas:{process_name}", _object_label(table), "reads",
                extraction_method="sas-static-analysis",
                evidence_ids=[evidence],
                confidence="CONFIRMED",
                validation_status="VALIDATED",
                limitations="static qualified names only; dynamic SQL not covered")
        for table in sorted(set(detail["writes"])):
            if "." not in table:
                continue
            context.upsert_domain_object("table", table,
                                         schema_name=_schema_of(table),
                                         evidence_id=evidence)
            context.add_lineage_edge(
                f"sas:{process_name}", _object_label(table), "writes",
                extraction_method="sas-static-analysis",
                evidence_ids=[evidence],
                confidence="CONFIRMED",
                validation_status="VALIDATED")
        for macro_name in detail["macros"]:
            context.upsert_domain_object("macro", macro_name, evidence_id=evidence)

    context.register_finding(
        f"Discovered {len(process_map)} candidate SAS process(es) from static analysis",
        "sas-processes", confidence="INFERRED", evidence_ids=evidence_ids,
        extraction_method="sas-static-analysis",
        rationale="process identity initialised from source files; final identity requires scheduler/log correlation",
        scope="synthetic fixture estate",
        limitations="source code alone does not guarantee business-process identity")

    for include_token in sorted(set(includes)):
        context.upsert_domain_object("include", include_token)

    return NodeResult(
        status="success",
        summary=f"discovered {len(process_map)} candidate process(es)",
        artifacts=[str(path) for path in sas_files],
        evidence_used=evidence_ids,
        metrics={"processes": len(process_map)},
        limitations=["static placeholder analysis, bounded", "no SCL/macro-level parsing"],
        recommended_next_nodes=["runtime.correlate", "doc.map_apps"],
        confidence="INFERRED",
    )


def node_runtime_correlate(context: NodeContext) -> NodeResult:
    log_files: List[Tuple[Path, Dict[str, Any]]] = []
    for manifest_path in sorted(context.layout.intake_manifests.glob("*.yaml")):
        manifest = _read_yaml(manifest_path)
        if not manifest:
            continue
        batch_dir = Path(str(manifest.get("raw_dir", "")))
        for entry in manifest.get("files", []):
            if str(entry.get("media_type")) in ("log-text", "text"):
                candidate = batch_dir / str(entry.get("path", ""))
                if candidate.is_file():
                    log_files.append((candidate, entry))

    if not log_files:
        context.request_human_input(HumanRequestSpec(
            title="Runtime logs absent for correlation",
            missing_info="runtime.logs",
            reason="no .log/.txt runtime assets were provided in raw batches",
            priority="REQUIRED_FOR_CONFIDENCE",
            retrieval_attempted="searched intake/raw for scheduler or execution logs",
            expected_provider="Subsidiary operations",
            accepted_formats="txt, log, csv",
        ))
        return NodeResult(
            status="waiting_for_input",
            summary="runtime correlation paused until logs are provided",
            confidence="UNKNOWN")

    events_by_process: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    unstructured_lines = 0
    for path, _entry in log_files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            structured_match = LOG_EVENT_RE.match(stripped)
            if structured_match:
                events_by_process[structured_match.group("process").lower()].append(
                    structured_match.groupdict())
                continue
            legacy_event = parse_legacy_log_event(stripped)
            if legacy_event is not None:
                events_by_process[legacy_event["process"].lower()].append(legacy_event)
            else:
                unstructured_lines += 1

    correlate_evidence: List[str] = []
    for process_name, events in sorted(events_by_process.items()):
        if not events:
            continue
        sorted_events = sorted(events, key=lambda event: event["ts"])
        last_event = sorted_events[-1]
        end_events = [event for event in sorted_events if event["event"] in ("END", "FINISHED")]
        durations = [int(event["duration"]) for event in end_events if event["duration"]]
        frequency_per_day = _days_between(sorted_events[0]["ts"], last_event["ts"]) or 1
        executions = max(len(end_events), 1)
        evidence = context.register_evidence(
            "runtime", f"correlated {executions} executions of {process_name}")
        correlate_evidence.append(evidence)
        context.register_finding(
            f"Process {process_name}: {executions} executions over "
            f"{frequency_per_day} day(s), average duration "
            f"{round(sum(durations) / len(durations)) if durations else 'unknown'}s, "
            f"last observed {last_event['ts']}",
            "runtime", confidence="CONFIRMED", evidence_ids=[evidence],
            extraction_method="log-correlation",
            scope=process_name,
        )


    context.register_finding(
        "Processes without runtime evidence are candidate-inactive (not obsolete): "
        "absence of logs is not proof of orphan status",
        "orphans", confidence="INFERRED",
        evidence_ids=[path_evidence for path_evidence in correlate_evidence],
        extraction_method="coverage-diff",
        rationale="only processes with scheduler/log zero-activity AND documentation support may be declared orphan",
        scope="coverage diff between discovered processes and runtime-correlated logs",
    )

    total_executions = sum(len(events) for events in events_by_process.values())
    if not events_by_process and unstructured_lines:
        return NodeResult(
            status="skipped",
            summary="legacy logs present but none matched deterministic parsing; "
                    "delegate semantic reading to the runtime.legacy_interpret agent node",
            metrics={"unstructured_lines": unstructured_lines},
            confidence="UNKNOWN",
            limitations=["no structured events recognized; semantic interpretation required"],
        )
    status = "success" if events_by_process else "waiting_for_input"
    return NodeResult(
        status=status,
        summary=f"correlated runtime: {len(events_by_process)} process(es)",
        evidence_used=correlate_evidence,
        metrics={"correlated_processes": len(events_by_process),
                 "executions": total_executions,
                 "unstructured_lines": unstructured_lines},
        confidence="CONFIRMED" if events_by_process else "UNKNOWN",
    )


def node_dba_request(context: NodeContext) -> NodeResult:
    table_count = sum(
        1 for row in context.repo.list_data_objects(context.assessment_id)
        if str(row["object_type"]) in ("table", "view"))
    if not table_count:
        return NodeResult(status="skipped", summary="no database objects identified yet",
                          confidence="INFERRED")

    if context.config.connectors.enabled.get("database", False):
        context.register_gap("live DB connector requires explicit approval pack; foundation stays offline", "phase4")
        return NodeResult(status="waiting_for_approval",
                          summary="live database path requires explicit human approval",
                          confidence="UNKNOWN")

    context.request_human_input(HumanRequestSpec(
        title="Run ALL_DEPENDENCIES export for identified Oracle objects",
        missing_info="oracle.all_dependencies",
        reason="database lineage requires dependency-view export; live DB access unavailable in offline mode",
        priority="BLOCKING",
        retrieval_attempted="connector disabled in configuration",
        expected_provider="Subsidiary DBA",
        accepted_formats="csv, tsv, xls, txt",
        security_notes="read-only catalog query; NO data values exported",
        query_pack="SELECT owner, name, type, referenced_owner, referenced_name,\n"
                   "       referenced_type\n"
                   "FROM   all_dependencies\n"
                   "WHERE  referenced_owner NOT IN ('SYS','SYSTEM')\n"
                   "ORDER  BY owner, name;\n",
        resume_node="lineage.ingest_dba",
    ))
    context.log("DBA request created")
    return NodeResult(status="waiting_for_input",
                      summary=f"DBA query pack created ({table_count} database objects)",
                      confidence="UNKNOWN")


def node_doc_mapping(context: NodeContext) -> NodeResult:
    owning_evidence: List[str] = []
    mapped_tables: List[str] = []
    unmapped_tables: List[str] = []
    table_objects = context.repo.list_data_objects(context.assessment_id)
    tables = {str(row["normalized_name"]): str(row["id"]) for row in table_objects}
    dictionary_rows = _load_dictionaries(context)
    if not dictionary_rows:
        return NodeResult(
            status="waiting_for_input",
            summary="no data dictionaries available yet for application mapping",
            confidence="UNKNOWN",
            limitations=["data dictionaries must be staged as CSV/TSV in a raw batch"])
    for dictionary_row in dictionary_rows:
        table_name = str(dictionary_row.get("object_name", "")).strip().upper()
        application = str(dictionary_row.get("application", "")).strip()
        if not table_name or not application:
            continue
        table_id = tables.get(table_name)
        if not table_id:
            unmapped_tables.append(f"{table_name} (not present in SAS estate)")
            continue
        evidence = context.register_evidence(
            "data-dictionary", f"{table_name} owned by {application}",
            locator=f"dictionary:{dictionary_row.get('source_file', 'fixture')}")
        owning_evidence.append(evidence)
        mapped_tables.append(table_name)
        context.add_lineage_edge(
            f"app:{application}", f"db:{table_name}", "owns",
            extraction_method="data-dictionary",
            evidence_ids=[evidence],
            confidence="CONFIRMED",
            validation_status="VALIDATED",
        )
    context.register_finding(
        f"Application mapping produced from data dictionaries "
        f"({len(mapped_tables)} tables mapped, {len(unmapped_tables)} unknown)",
        "applications", confidence="INFERRED",
        evidence_ids=owning_evidence,
        extraction_method="dictionary-correlation",
        limitations="dictionaries are partial; unmapped objects must be confirmed with owners",
    )
    return NodeResult(
        status="success",
        summary=f"mapped {len(mapped_tables)} table(s) to applications",
        evidence_used=owning_evidence,
        metrics={"mapped": len(mapped_tables), "unmapped": len(unmapped_tables)},
        confidence="CONFIRMED",
    )


def node_ingest_dba(context: NodeContext) -> NodeResult:
    all_requests = context.repo.list_requests(context.assessment_id)
    dba_requests = [request for request in all_requests
                    if str(request["missing_info"]) == "oracle.all_dependencies"]
    resolved = [request for request in dba_requests if str(request["status"]) == "RESOLVED"]
    if not dba_requests:
        return NodeResult(status="skipped", summary="no DBA request on record",
                          confidence="INFERRED")
    if not resolved:
        return NodeResult(
            status="waiting_for_input",
            summary="DBA export not yet delivered; lineage branch parked at WAITING_FOR_INPUT",
            confidence="UNKNOWN",
        )
    batch_id = str(resolved[0]["resolution_batch_id"] or "")
    if not batch_id:
        return NodeResult(status="waiting_for_input",
                          summary="resolution recorded without a batch reference",
                          confidence="UNKNOWN")
    manifest = _find_batch_manifest(context, batch_id)
    if manifest is None:
        context.register_gap(
            f"batch {batch_id} referenced by request but manifest missing", "phase4")
        return NodeResult(status="failed", summary="DBA batch manifest missing")

    evidence_ids: List[str] = []
    edges_created = 0
    batch_dir = Path(str(manifest.get("raw_dir", "")))
    for entry in manifest.get("files", []):
        relative_path = str(entry.get("path", ""))
        if not relative_path.lower().endswith((".csv", ".txt")):
            continue
        csv_path = batch_dir / relative_path
        try:
            handle = open(csv_path, "r", encoding="utf-8", newline="")
        except OSError:
            continue
        with handle:
            reader = csv.DictReader(handle)
            for record in reader:
                owner = str(record.get("owner", "")).strip().upper()
                name = str(record.get("name", "")).strip()
                referenced_owner = str(record.get("referenced_owner", "")).strip().upper()
                referenced_name = str(record.get("referenced_name", "")).strip().upper()
                if not name or not referenced_name:
                    continue
                evidence = context.register_evidence(
                    "dba-export",
                    f"{owner}.{name} depends on {referenced_owner}.{referenced_name}",
                    locator=f"dba-export:{relative_path}:{reader.line_num}")
                context.add_lineage_edge(
                    f"db:oracle:{owner}.{name}",
                    f"db:oracle:{referenced_owner}.{referenced_name}",
                    "depends_on",
                    extraction_method="all-dependencies-export",
                    evidence_ids=[evidence],
                    confidence="CONFIRMED",
                    validation_status="VALIDATED",
                    limitations="dependency views do not capture dynamic SQL, synonyms, database links",
                    depth=1,
                )
                edges_created += 1
                evidence_ids.append(evidence)

    context.register_finding(
        f"Ingested DBA dependency export batch {batch_id}: {edges_created} lineage edges",
        "lineage", confidence="CONFIRMED", evidence_ids=evidence_ids,
        extraction_method="dba-result-ingestion",
        limitations="unresolved relationships remain: dynamic SQL, synonyms, database links",
    )
    return NodeResult(
        status="success",
        summary=f"resumed lineage branch; ingested {edges_created} edges from DBA export",
        evidence_used=evidence_ids,
        metrics={"edges": edges_created},
        confidence="CONFIRMED",
    )


def node_quality_gate(context: NodeContext) -> NodeResult:
    findings = context.repo.list_findings(context.assessment_id)
    if not findings:
        context.register_gap("quality gate found no findings to review", "phase8")
        return NodeResult(status="failed", summary="no findings to validate")

    failures: List[str] = []
    for finding_row in findings:
        parsed_evidence = _parse_list(finding_row["evidence_ids"])
        if not parsed_evidence:
            failures.append(f"finding {finding_row['id']} lacks evidence references")
        for evidence_id in parsed_evidence:
            if not context.repo.get_evidence(evidence_id):
                failures.append(
                    f"finding {finding_row['id']} cites missing evidence {evidence_id}")
    for edge_row in context.repo.list_lineage_edges(context.assessment_id):
        edge_evidence = _parse_list(edge_row["evidence_ids"])
        if not edge_evidence:
            failures.append(f"edge {edge_row['id']} lacks evidence references")
        for evidence_id in edge_evidence:
            if not context.repo.get_evidence(evidence_id):
                failures.append(
                    f"edge {edge_row['id']} cites missing evidence {evidence_id}")

    if failures:
        for failure_text in failures:
            context.register_gap(f"quality gate failure: {failure_text}", "phase8")
        return NodeResult(
            status="failed",
            summary=f"quality gate FAILED with {len(failures)} problem(s)",
            limitations=failures[:10],
        )

    evidence = context.register_evidence("quality", "quality gate passed")
    context.register_finding(
        "Quality gate passed: all findings and lineage edges trace to existing evidence",
        "quality", confidence="CONFIRMED", evidence_ids=[evidence],
        extraction_method="gate-check")
    return NodeResult(
        status="success",
        summary="quality gate passed",
        evidence_used=[evidence],
        confidence="CONFIRMED",
        recommended_next_nodes=["audit.export"])


def node_audit_export(context: NodeContext) -> NodeResult:
    destination = context.layout.workspace_audit / "export-latest.jsonl"
    summary = context.audit.export(destination, assessment_id=context.assessment_id)
    events = context.audit.read_events(context.assessment_id)
    report = {
        "assessment_id": context.assessment_id,
        "event_count": len(events),
        "node_states": {
            str(row["node_id"]): str(row["status"])
            for row in context.repo.list_node_states(context.assessment_id)
        },
        "open_requests": [str(row["id"]) for row in
                          context.repo.list_requests(context.assessment_id, status="OPEN")],
        "destination": str(destination),
    }
    artifact = context.write_artifact("audit-summary.json", json.dumps(report, indent=2))
    return NodeResult(
        status="success",
        summary=f"audit trail exported ({summary['event_count']} events)",
        artifacts=[artifact, str(destination)],
        metrics=dict(summary),
        confidence="CONFIRMED")


def _read_yaml(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document if isinstance(document, dict) else None


def _schema_of(raw_name: str) -> str:
    return raw_name.split(".")[0] if "." in raw_name else ""


def _object_label(raw_name: str) -> str:
    parts = raw_name.split(".")
    if len(parts) > 1:
        return f"db:oracle:{parts[0].upper()}.{parts[-1].upper()}"
    return f"db:{parts[-1].upper()}"


def _days_between(earlier: str, later: str) -> int:
    from datetime import datetime
    fmt = "%Y-%m-%dT%H:%M:%S" if "T" in earlier else "%Y-%m-%d %H:%M:%S"
    try:
        start = datetime.strptime(earlier[:19], fmt)
        end = datetime.strptime(later[:19], fmt)
    except ValueError:
        return 0
    return max((end - start).days, 1)


def _find_batch_manifest(context: NodeContext, batch_id: str) -> Optional[Dict[str, Any]]:
    direct = context.layout.intake_manifests / f"{batch_id}.yaml"
    document = _read_yaml(direct)
    if document:
        return document
    for manifest_path in sorted(context.layout.intake_manifests.glob("*.yaml")):
        document = _read_yaml(manifest_path)
        if document and str(document.get("batch_id", "")) == batch_id:
            return document
    return None


def _parse_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item)]
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, list):
                return [str(item) for item in decoded if str(item)]
        except json.JSONDecodeError:
            return [raw.strip()]
    return []


def _load_dictionaries(context: NodeContext) -> list:
    rows: list = []
    for manifest_path in sorted(context.layout.intake_manifests.glob("*.yaml")):
        manifest = _read_yaml(manifest_path)
        if not manifest:
            continue
        batch_dir = Path(str(manifest.get("raw_dir", "")))
        for entry in manifest.get("files", []):
            if str(entry.get("media_type")) not in ("csv", "tsv", "text"):
                continue
            path = batch_dir / str(entry.get("path", ""))
            delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
            try:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    first_line = handle.readline()
                    handle.seek(0)
                    if first_line.count(";") > first_line.count(","):
                        delimiter = ";"
                    reader = csv.DictReader(handle, delimiter=delimiter)
                    for record in reader:
                        rows.append({str(key).strip().lower(): value for key, value in record.items()})
            except (csv.Error, OSError):
                continue
    return rows
