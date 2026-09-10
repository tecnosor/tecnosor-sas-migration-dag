from __future__ import annotations

import shutil
from pathlib import Path

from sassessment.cli.main import answer_request


def run_synthetic_demo(context) -> int:
    repo_root: Path = context.config.repo_root
    fixture_src = repo_root / "examples" / "synthetic-fixture"
    raw_target = context.layout.intake_raw / "BAT-demo-fixture"

    print("=== SASsessment synthetic foundation demo (all data SYNTHETIC) ===")
    print("[1] workspace scaffold")
    problems = context.layout.validate()
    print("    ok" if not problems else f"    problems: {problems}")

    print("[2] stage fixture batch")
    if not raw_target.exists():
        shutil.copytree(fixture_src, raw_target)
        print(f"    staged -> {raw_target}")
    else:
        print(f"    already staged: {raw_target}")

    print("[3-5] run graph: workspace validation, registration, coverage, discovery, runtime")
    engine = context.engine()
    outcomes = engine.run()
    for outcome in outcomes:
        print(f"    {outcome.node_id}: {outcome.status} - {outcome.summary}")

    aid = context.active_assessment_id()
    requests = context.repo.list_requests(aid, status="OPEN")
    dba_requests = [r for r in requests if str(r["missing_info"]) == "oracle.all_dependencies"]
    print("[6-7] DBA request pause/resume")
    if not dba_requests:
        print("    no DBA request open (branch may have resumed already)")
    else:
        request = dba_requests[0]
        destination = Path(str(request["destination_batch"]))
        dba_csv = destination / "all_dependencies_export.csv"
        dba_csv.write_text(
            "owner,name,type,referenced_owner,referenced_name,referenced_type\n"
            "CUST,CUSTOMER_MASTER,TABLE,DLQ,DQ_VALIDATOR,PROCEDURE\n"
            "CUST,CUSTOMER_MASTER,TABLE,ETL_LoadService,LOAD_CUST_EXT,PACKAGE\n"
            "CUST,ADDRESS_EXT,TABLE,CRM_APP,CRM_CUST_VIEW,VIEW\n",
            encoding="utf-8")
        print(f"    [8-9] synthetic DBA result placed -> {dba_csv}")
        code = answer_request(context, str(request["id"]))
        print(f"    answer rc={code}")

    print("[10-11] resume lineage branch")
    engine2 = context.engine()
    outcomes2 = engine2.run()
    for outcome in outcomes2:
        print(f"    {outcome.node_id}: {outcome.status} - {outcome.summary}")

    print("[12] checkpoint")
    from sassessment.state.checkpoints import CheckpointManager
    manager = CheckpointManager(context.db, context.repo, context.layout, audit=context.audit)
    ckp = manager.create(aid, "synthetic demo checkpoint")
    print(f"    checkpoint {ckp}")

    print("[13] quality gate")
    gate = context.engine().run_node("quality.gate") if "quality.gate" not in \
        {o.node_id: o.status for o in outcomes} else None
    if gate is not None:
        print(f"    {gate.node_id}: {gate.status} - {gate.summary}")

    print("[14] audit export")
    destination = context.layout.workspace_audit / f"export-{aid}.jsonl"
    summary = context.audit.export(destination, assessment_id=aid)
    print(f"    {summary['event_count']} events -> {summary['destination']}")
    print("=== demo complete ===")
    return 0
