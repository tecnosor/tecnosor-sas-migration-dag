from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from sassessment import __version__
from sassessment.config import load_config, SassessmentConfig
from sassessment.errors import SASsessmentError
from sassessment.graph.engine import GraphEngine
from sassessment.graph.loader import load_graph
from sassessment.graph.predicates import PredicateRegistry
from sassessment.ids import assessment_id as new_assessment_id
from sassessment.ids import session_id as new_session_id
from sassessment.state.checkpoints import CheckpointManager
from sassessment.state.database import Database, Migrator
from sassessment.state.events import AuditEmitter, Redactor
from sassessment.state.repository import Repository
from sassessment.workspace.layout import WorkspaceLayout, ensure_workspace, find_repo_root

REPO_ROOT = find_repo_root(__import__("pathlib").Path(__file__).resolve())

_STATUS_ICON = {
    "PENDING": " ", "READY": ">", "RUNNING": "*", "SUCCEEDED": "+", "FAILED": "X",
    "WAITING_FOR_INPUT": "|", "WAITING_FOR_APPROVAL": "|", "CANCELLED": "-",
    "SKIPPED": "s", "SUPERSEDED": "s",
}


def migrations_dir(repo_root: Path) -> Path:
    package_dir = repo_root / "src" / "sassessment"
    candidate = package_dir / "state" / "migrations"
    if candidate.is_dir():
        return candidate
    return repo_root / "src" / "sassessment" / "state" / "migrations"


def _load_migrations(repo_root: Path) -> List[Any]:
    return [
        (int(p.name.split("__")[0][1:]),
         p.name.split("__", 1)[1].replace(".sql", ""),
         p.read_text(encoding="utf-8"))
        for p in sorted(migrations_dir(repo_root).glob("V*.sql"))
    ]


class ApplicationContext:
    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self.config: SassessmentConfig = load_config(repo_root=repo_root or find_repo_root())
        self.layout: WorkspaceLayout = ensure_workspace(self.config.repo_root)
        self.db = Database(self.config.database_path)
        self.migrator = Migrator(self.db, _load_migrations(self.config.repo_root))
        self.repo = Repository(self.db)
        self.audit = AuditEmitter(self.db, self.layout.audit_log_path(),
                                  Redactor(self.config.redaction_patterns))
        self.graph = load_graph(str(self.config.graph_path))
        self.registry = self._load_registry()
        self.predicates = PredicateRegistry()

    def _load_registry(self):
        from sassessment.demo.nodes import build_registry
        return build_registry()

    def ensure_bootstrap(self) -> str:
        self.migrator.apply_all()
        active = self.config.active_assessment or self.repo.get_meta("active_assessment")
        if not active:
            rows = self.repo.list_assessments()
            if rows:
                active = str(rows[0]["id"])
            else:
                active = new_assessment_id()
                self.repo.create_assessment(active, "Untitled assessment", "")
                self.repo.set_meta("active_assessment", active)
                self.audit.emit(action="assessment.created", actor_type="human",
                                assessment_id=active)
        if not self.repo.get_meta("active_assessment"):
            self.repo.set_meta("active_assessment", active)
        return active

    def active_assessment_id(self) -> str:
        return self.ensure_bootstrap()

    def active_session_id(self, assessment_id: str) -> str:
        open_sessions = [row for row in self.repo.list_sessions(assessment_id, limit=1)
                         if str(row["status"]) == "OPEN"]
        if open_sessions:
            return str(open_sessions[0]["id"])
        sid = new_session_id()
        self.repo.create_session(sid, assessment_id)
        self.audit.emit(action="session.started", actor_type="human",
                        assessment_id=assessment_id, session_id=sid, new_state=sid)
        return sid

    def engine(self) -> GraphEngine:
        aid = self.active_assessment_id()
        sid = self.active_session_id(aid)
        bootstrap = self.repo.get_node_state(aid, self.graph.entry)
        if bootstrap is None:
            self.repo.upsert_node_state(aid, self.graph.entry, status="READY")
        engine = GraphEngine(self.config, self.graph, self.registry, self.predicates,
                             self.repo, self.audit, self.layout, aid, sid)
        recovered = engine.recover_stale_running()
        if recovered:
            print(f"auto-recovery: released stale RUNNING nodes after crash/restart: {recovered}")
        return engine

    def close(self) -> None:
        self.db.close()


def cmd_init(context: ApplicationContext) -> int:
    assessment_id = context.ensure_bootstrap()
    print(f"workspace: {context.config.repo_root}")
    print(f"database:  {context.config.database_path}")
    print(f"graph:     {context.config.graph_path.name} v{context.graph.version}")
    print(f"assessment: {assessment_id}")
    assessment = context.repo.get_assessment(assessment_id)
    print(f"phase:     {assessment['current_phase'] if assessment else '?'}")
    return 0


def cmd_status(context: ApplicationContext) -> int:
    aid = context.active_assessment_id()
    engine = context.engine()
    state = engine.state_snapshot()
    print(f"assessment {aid} phase={state.get('current_phase')}")
    print("nodes:")
    known = sorted(state.get("nodes", {}).items())
    for node_id, node_state in known:
        icon = _STATUS_ICON.get(str(node_state["status"]), " ")
        print(f"  [{icon}] {node_id:24} {node_state['status']}")
    for node in context.graph.nodes.values():
        if node.id not in state.get("nodes", {}):
            print(f"  [ ] {node.id:24} NOT-RUN")
    blockers = engine.blocked_summary()
    if blockers:
        print("blockers:")
        for blocker in blockers:
            print(f"  - {blocker['node']}: {blocker['reason']}")
    completion = engine.assessment_completion()
    print(f"completion status: {completion['status']}"
          + (f" (blocking: {completion['blocking_count']})" if completion["blocking_count"] else ""))
    open_requests = context.repo.list_requests(aid, status="OPEN")
    if open_requests:
        print("open requests:")
        for request in open_requests:
            print(f"  - {request['id']} [{request['priority']}] {request['title']}")
            print(f"      destination: {request['destination_batch']}")
    return 0


def cmd_run(context: ApplicationContext, node_id: Optional[str] = None,
            dry_run: bool = False, max_steps: int = 64) -> int:
    engine = context.engine()
    if node_id:
        outcome = engine.run_node(node_id)
        outcomes = [outcome]
    else:
        outcomes = engine.run(dry_run=dry_run, max_steps=max_steps)
    for outcome in outcomes:
        prefix = "DRY " if outcome.dry_run else ""
        print(f"{prefix}{outcome.node_id}: {outcome.status} {outcome.summary}")
        for source, target, condition in outcome.fired_edges:
            print(f"    route {source} -> {target} [{condition}]")
        for decision_id in outcome.decision_ids:
            print(f"    decision {decision_id}")
    blockers = engine.blocked_summary()
    if blockers:
        print("open blockers:")
        for blocker in blockers:
            print(f"  - {blocker.get('node')}: {blocker.get('reason')}")
    completion = engine.assessment_completion()
    print(f"assessment completion: {completion['status']}")
    ok_statuses = ("SUCCEEDED", "PLANNED", "WAITING_FOR_INPUT",
                   "WAITING_FOR_APPROVAL", "SKIPPED")
    return 0 if all(o.status in ok_statuses for o in outcomes) else 1


def cmd_logs(context: ApplicationContext) -> int:
    aid = context.active_assessment_id()
    sessions = context.repo.list_sessions(aid)
    for session in sessions:
        print(f"session {session['id']} status={session['status']} started={session['started_at']}")
    return 0


def cmd_scan_inputs(context: ApplicationContext) -> int:
    context.ensure_bootstrap()
    candidates = [entry for entry in sorted(context.layout.intake_raw.iterdir())
                  if entry.is_dir() and not entry.name.startswith(".")]
    if not candidates:
        print("no raw batches found under intake/raw/<source-batch-id>/")
        return 0
    for candidate in candidates:
        registered = context.repo.get_meta(f"batch:registered:{candidate.name}")
        status = "REGISTERED" if registered else "NEW"
        print(f"{status}: {candidate}")
    return 0


def cmd_inspect(context: ApplicationContext, target: str) -> int:
    """Preview what the foundation would extract from a raw batch without running nodes."""
    from sassessment.intake.xlsx_reader import read_xlsx
    context.ensure_bootstrap()
    batch_dir = Path(target).expanduser()
    if not batch_dir.is_absolute():
        candidate = context.layout.intake_raw / target
        batch_dir = candidate if candidate.is_dir() else context.config.repo_root / target
    if not batch_dir.is_dir():
        print(f"batch directory not found: {target}")
        return 1
    files = [path for path in sorted(batch_dir.rglob("*")) if path.is_file() and not path.name.startswith(".")]
    if not files:
        print(f"empty batch: {batch_dir}")
        return 1
    print(f"batch: {batch_dir} ({len(files)} files)")
    csv_rows = 0
    for file_path in files:
        suffix = file_path.suffix.lower()
        report_line = f"  {file_path.relative_to(batch_dir)} ({file_path.stat().st_size} bytes)"
        print(report_line)
        if suffix == ".xlsx":
            try:
                sheets = read_xlsx(file_path)
            except Exception as exc:
                print(f"    [xlsx unreadable: {exc}]")
                continue
            for sheet_name, records in sorted(sheets.items()):
                headers = sorted(records[0].keys()) if records else []
                print(f"    sheet '{sheet_name}': {len(records)} rows, columns: {', '.join(headers[:12])}")
                for sample in records[:2]:
                    preview = {key: str(value)[:40] for key, value in list(sample.items())[:6]}
                    print(f"      sample: {preview}")
        elif suffix in (".log", ".txt"):
            lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            for sample in lines[:4]:
                print(f"    | {sample[:120]}")
            if len(lines) > 4:
                print(f"    ... {len(lines)} lines total")
        elif suffix == ".sas":
            text = file_path.read_text(encoding="utf-8", errors="replace")
            includes = len(__import__("re").findall(r"%include", text, __import__("re").IGNORECASE))
            from sassessment.demo.nodes import FROM_RE, JOIN_RE, SET_MERGE_RE, DATA_STEP_RE, MACRO_DEF_RE
            tokens = (
                len(FROM_RE.findall(text)) + len(JOIN_RE.findall(text))
                + len(SET_MERGE_RE.findall(text)) + len(DATA_STEP_RE.findall(text))
                + len(MACRO_DEF_RE.findall(text)) + includes)
            print(f"    SAS tokens found: {tokens} (data-step/sql reads+writes, macros, includes={includes})")
    return 0


def cmd_add_input(context: ApplicationContext, source: str) -> int:
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists():
        print(f"not found: {source_path}")
        return 1
    slug = source_path.stem.lower().replace(" ", "-")[:24] or "input"
    destination = context.layout.intake_raw / f"BAT-manual-{slug}"
    destination.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        shutil.copytree(source_path, destination / source_path.name, dirs_exist_ok=True)
    else:
        shutil.copy2(source_path, destination / source_path.name)
    print(f"staged into {destination} (run start to register)")
    return 0


def cmd_answer(context: ApplicationContext, request_id: str) -> int:
    return answer_request(context, request_id)


def answer_request(context: ApplicationContext, request_id: str) -> int:
    aid = context.active_assessment_id()
    request = context.repo.get_request(request_id)
    if request is None or str(request["assessment_id"]) != aid:
        print(f"request not found in this assessment: {request_id}")
        return 1
    if str(request["status"]) != "OPEN":
        print(f"request is {request['status']}, only OPEN requests can be answered")
        return 1
    destination = Path(str(request["destination_batch"]))
    material_files = [path for path in sorted(destination.rglob("*"))
                      if path.is_file()
                      and path.name not in ("REQUEST.md", "query-pack.sql")]
    if not material_files:
        print("reaction batch still empty; place the DBA/ops export in")
        print(f"  {destination}")
        return 1
    batch_id = f"BAT-res-{request_id.lower().split('-')[-1]}"
    resolved = context.repo.resolve_request(
        request_id, status="RESOLVED", resolution_batch_id=batch_id)
    if resolved:
        from sassessment.intake.registration import register_batch
        register_batch(context.config.repo_root, destination, context.repo, context.audit,
                       batch_id=batch_id)
    if not resolved:
        print("could not resolve request (already resolved?)")
        return 1
    node_id = str(request["node_id"])
    waiting_node = context.repo.get_node_state(aid, node_id)
    if waiting_node is not None:
        context.repo.upsert_node_state(aid, node_id, status="SUCCEEDED",
                                       attempts=int(waiting_node["attempts"]))
    resume_node = str(request["resume_node"] or "")
    if resume_node and resume_node in context.graph.nodes:
        context.repo.upsert_node_state(aid, resume_node, status="READY")
    context.audit.emit(action="request.resolved", actor_type="human",
                       assessment_id=aid, node_id=node_id, new_state=resume_node,
                       rationale=f"result batch delivered with {len(material_files)} file(s)",
                       details={"request": request_id, "batch": batch_id})
    print(f"request {request_id} resolved; resume branch ready at {resume_node or '-'}")
    return 0


def cmd_unblock(context: ApplicationContext, node_id: str) -> int:
    """Release a WAITING_FOR_APPROVAL (quota) or stuck node without consuming one attempt."""
    aid = context.active_assessment_id()
    state = context.repo.get_node_state(aid, node_id)
    if state is None:
        print(f"unknown node in this assessment: {node_id}")
        return 1
    if str(state["status"]) not in ("WAITING_FOR_APPROVAL", "FAILED", "RUNNING", "READY"):
        print(f"node {node_id} state is {state['status']}; only holds and failures can be unblocked")
        return 1
    context.repo.upsert_node_state(aid, node_id, status="READY",
                                   attempts=int(state["attempts"]))
    context.audit.emit(action="node.unblocked", actor_type="human",
                       assessment_id=aid, node_id=node_id,
                       previous_state=str(state["status"]), new_state="READY",
                       rationale="operator released a quota hold or failure")
    print(f"node {node_id} unblocked ({state['status']} -> READY); run `start` to resume")
    return 0


def cmd_checkpoint(context: ApplicationContext) -> int:
    aid = context.active_assessment_id()
    manager = CheckpointManager(context.db, context.repo, context.layout, audit=context.audit)
    ckp = manager.create(aid, "manual checkpoint")
    print(f"checkpoint created: {ckp}")
    return 0


def cmd_sessions(context: ApplicationContext) -> int:
    aid = context.active_assessment_id()
    for session in context.repo.list_sessions(aid):
        print(f"session {session['id']} status={session['status']} started={session['started_at']}")
    return 0


def cmd_history(context: ApplicationContext) -> int:
    aid = context.active_assessment_id()
    events = context.audit.read_events(aid)
    for event in events:
        line = f"{event['ts']} {event['actor_type']:6} {event['action']:22} {event.get('node_id') or '-'}"
        if event.get("new_state") and event["new_state"] != event.get("node_id"):
            line += f" -> {event['new_state']}"[:80]
        print(line)
    return 0


def cmd_review(context: ApplicationContext) -> int:
    aid = context.active_assessment_id()
    findings = context.repo.list_findings(aid, include_inactive=True)
    print(f"findings: {len(findings)}")
    for finding_row in findings:
        confidence = str(finding_row["confidence"])
        final = " [SUPERSEDED]" if str(finding_row["status"]) != "ACTIVE" else ""
        print(f"  - {finding_row['id']} [{confidence}]{final} {str(finding_row['statement'])[:90]}")
    edges = context.repo.list_lineage_edges(aid)
    print(f"lineage edges: {len(edges)}")
    for edge_row in edges:
        print(f"  {edge_row['source_node']} -[{edge_row['relationship']}]-> "
              f"{edge_row['target_node']} ({edge_row['confidence']})")
    return 0


def cmd_export_audit(context: ApplicationContext) -> int:
    aid = context.active_assessment_id()
    destination = context.layout.workspace_audit / f"export-{aid}.jsonl"
    summary = context.audit.export(destination, assessment_id=aid)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_validate(context: ApplicationContext) -> int:
    problems: List[str] = []
    problems.extend(context.layout.validate())
    if not context.config.graph_path.is_file():
        problems.append("foundation graph missing")
    else:
        try:
            graph = load_graph(str(context.config.graph_path))
        except SASsessmentError as exc:
            problems.append(f"graph invalid: {exc.message}")
        else:
            kind = getattr(graph, "kind", None) or "foundation-demo"
            template_path = context.config.repo_root / "graphs" / "assessment-graph.template.json"
            template_plan = ""
            if template_path.is_file():
                try:
                    import json as _json
                    template_doc = _json.loads(template_path.read_text(encoding="utf-8"))
                    template_plan = str(template_doc.get("status"))
                except Exception:
                    pass
            print(f"ok: graph {len(graph.nodes)} nodes / {len(graph.edges)} edges (v{graph.version})")
            print(f"ok: graph kind {kind}"
                  + (f"; assessment-graph.template status={template_plan}" if template_plan else ""))
    if problems:
        print("validation problems:")
        for problem in problems:
            print(f"  problem: {problem}")
        return 1
    print("workspace valid")
    return 0


def cmd_show(context: ApplicationContext, what: str) -> int:
    aid = context.active_assessment_id()
    if what == "graph":
        print(f"graph {context.graph.graph_id} v{context.graph.version}:")
        for node in context.graph.nodes.values():
            targets = ", ".join(edge.target for edge in context.graph.outgoing(node.id))
            print(f"  {node.id} ({node.type}, {node.phase}) -> {targets or '-'}")
        return 0
    if what == "blockers":
        engine = context.engine()
        for blocker in engine.blocked_summary():
            print(f"- {blocker}")
        if not any(True for _ in engine.blocked_summary()):
            print("no blockers")
        return 0
    if what == "requests":
        requests = context.repo.list_requests(aid)
        if not requests:
            print("no human requests on record")
            return 0
        for request in requests:
            print(f"{request['id']} [{request['status']}/{request['priority']}] {request['title']}")
            if str(request["status"]) == "OPEN":
                print(f"  destination batch: {request['destination_batch']}")
                print(f"  resume node: {request['resume_node']}")
        return 0
    print(f"unknown show target: {what}")
    return 1


def run_demo(context: ApplicationContext) -> int:
    from sassessment.demo.synthetic import run_synthetic_demo
    return run_synthetic_demo(context)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sassessment",
                                     description="SASsessment graph-orchestrated assessment tool")
    parser.add_argument("--version", action="version", version=f"sassessment {__version__}")
    parser.add_argument("--workspace", default=None, help="repository root override")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("init", help="init workspace and assessment")
    subparsers.add_parser("status", help="assessment state overview")
    subparsers.add_parser("start", help="run graph until blocked")
    subparsers.add_parser("resume", help="resume graph (same as start)")
    subparsers.add_parser("next", help="show the next runnable node")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("node", nargs="?", default=None)
    run_parser.add_argument("--dry-run", action="store_true")
    scan = subparsers.add_parser("scan-inputs")
    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("target", nargs="?", default=None)
    add = subparsers.add_parser("add-input")
    add.add_argument("path")
    answer = subparsers.add_parser("answer")
    answer.add_argument("request_id")
    unblock = subparsers.add_parser("unblock")
    unblock.add_argument("node_id")
    checkpoint_parser = subparsers.add_parser("checkpoint")
    subparsers.add_parser("sessions")
    subparsers.add_parser("history")
    subparsers.add_parser("review")
    subparsers.add_parser("export-audit")
    subparsers.add_parser("validate")
    demo_parser = subparsers.add_parser("demo")
    demo_parser.add_argument("--workspace", default=None)
    show = subparsers.add_parser("show")
    show.add_argument("target", choices=["graph", "blockers", "requests"])
    return parser


def dispatch(args: argparse.Namespace) -> int:
    context = ApplicationContext(repo_root=Path(args.workspace).resolve() if args.workspace else None)
    try:
        if args.command in ("init",):
            return cmd_init(context)
        if args.command in ("status",):
            return cmd_status(context)
        if args.command in ("start", "resume"):
            return cmd_run(context)
        if args.command == "next":
            engine = context.engine()
            node = engine.next_runnable()
            if node is None:
                print("no runnable node (blocked or complete)")
                return 0
            print(f"next: {node.id} ({node.type}, {node.phase}) handler={node.handler}")
            return 0
        if args.command == "run":
            return cmd_run(context, node_id=args.node, dry_run=args.dry_run)
        if args.command == "scan-inputs":
            return cmd_scan_inputs(context)
        if args.command == "inspect":
            return cmd_inspect(context, args.target or "intake/raw")
        if args.command == "add-input":
            return cmd_add_input(context, args.path)
        if args.command == "answer":
            return cmd_answer(context, args.request_id)
        if args.command == "unblock":
            return cmd_unblock(context, args.node_id)
        if args.command == "checkpoint":
            return cmd_checkpoint(context)
        if args.command == "sessions":
            return cmd_sessions(context)
        if args.command == "history":
            return cmd_history(context)
        if args.command == "review":
            return cmd_review(context)
        if args.command == "export-audit":
            return cmd_export_audit(context)
        if args.command == "validate":
            return cmd_validate(context)
        if args.command == "demo":
            return run_demo(context)
        if args.command == "show":
            return cmd_show(context, args.target)
        return 1
    finally:
        context.close()


HELP_TEXT = """commands:
  init | status | start | resume | next | run [node] | scan-inputs
  add-input <path> | answer <request-id> | checkpoint | sessions
  history | review | export-audit | validate | show graph|blockers|requests
  help | quit
"""


def run_interactive(args: argparse.Namespace) -> int:
    print(f"SASsessment v{__version__} - type 'help' for commands, 'quit' to exit")
    while True:
        try:
            line = input("sassessment> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        try:
            tokens = line.split()
            if tokens[0] in ("quit", "exit", "q"):
                return 0
            if tokens[0] in ("help", "?"):
                print(HELP_TEXT)
                continue
            reparsed = build_parser().parse_args(tokens)
            code = dispatch(reparsed)
            if code != 0 and tokens:
                print(f"(command returned {code})")
        except SASsessmentError as exc:
            print(f"error: {exc.message}")
        except KeyboardInterrupt:
            print("(interrupted)")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.command:
        try:
            return run_interactive(args)
        except SASsessmentError as exc:
            print(f"error: {exc.message}", file=sys.stderr)
            return 2
    return dispatch(args)


if __name__ == "__main__":
    raise SystemExit(main())
