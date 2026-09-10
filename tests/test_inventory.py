import zipfile
from pathlib import Path

import pytest

from sassessment.intake.xlsx_reader import read_xlsx

_REPO_ROOT = Path(__file__).resolve().parents[1]

CT = '''<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>'''

RELS_WB = '''<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''

RELS_ROOT = '''<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

SS = '''<?xml version="1.0"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="8" uniqueCount="8">
<si><t>object_name</t></si><si><t>application</t></si><si><t>table_name</t></si><si><t>OWNER</t></si><si><t>rows</t></si><si><t>Evolution</t></si><si><t>proceso</t></si><si><t>batch_cli</t></si>
</sst>'''


def build_xlsx(path: Path, sheet_name: str, header_cells: str, data_cells: str) -> None:
    workbook = f'''<?xml version="1.0"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    sheet = f'''<?xml version="1.0"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>
{header_cells}
{data_cells}
</sheetData></worksheet>'''
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CT)
        z.writestr("_rels/.rels", RELS_ROOT)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", RELS_WB)
        z.writestr("xl/sharedStrings.xml", SS)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def build_engine(tmp_path, with_batch: bool = True):
    from sassessment.config import load_config
    from sassessment.workspace.layout import ensure_workspace
    from sassessment.state.database import Database, Migrator
    from sassessment.state.repository import Repository
    from sassessment.state.events import AuditEmitter, Redactor
    from sassessment.intake.registration import register_batch
    from sassessment.demo.nodes import build_registry
    from sassessment.graph.predicates import PredicateRegistry
    from sassessment.graph.engine import GraphEngine
    from sassessment.ids import session_id as new_session_id
    from sassessment.graph.model import GraphDef, NodeDef, EdgeDef

    cfg = load_config(repo_root=_REPO_ROOT)
    cfg.database_path = tmp_path / "inv-db.sqlite"
    layout = ensure_workspace(tmp_path)
    migrations = tuple(
        (int(p.name.split("__")[0][1:]), p.name.split("__", 1)[1].replace(".sql", ""), p.read_text(encoding="utf-8"))
        for p in sorted((_REPO_ROOT / "src" / "sassessment" / "state" / "migrations").glob("V*.sql"))
    )
    db = Database(cfg.database_path)
    Migrator(db, migrations).apply_all()
    repo = Repository(db)
    aid = "ASMT-inv"
    repo.create_assessment(aid, "inventory test", "sub")
    audit = AuditEmitter(db, layout.audit_log_path(), Redactor([]))
    sid = new_session_id()
    repo.create_session(sid, aid)

    batch_dir = layout.intake_raw / "BAT-inv"
    if with_batch:
        batch_dir.mkdir()
        build_xlsx(batch_dir / "inventario.xlsx", "Tables",
                   '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>',
                   '<row r="2"><c t="s"><v>2</v></c><c t="s"><v>3</v></c></row>'
                   '<row r="3"><c t="s"><v>4</v></c><c t="s"><v>5</v></c></row>')
        register_batch(tmp_path, batch_dir, repo, audit)

    node = NodeDef(id="inventory.extract", type="deterministic", phase="phase1",
                   handler="inventory.extract")
    graph = GraphDef(graph_id="g-inv", version="1", entry=node.id,
                     nodes={node.id: node}, edges=[])
    graph.validate()
    engine = GraphEngine(cfg, graph, build_registry(), PredicateRegistry(), repo, audit,
                         layout, aid, sid)
    engine.db = db
    engine.repo_obj = repo
    return engine


def test_read_xlsx_sheet(tmp_path):
    xlsx = tmp_path / "inv.xlsx"
    build_xlsx(xlsx, "Tables",
               '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>',
               '<row r="2"><c t="s"><v>2</v></c><c t="s"><v>3</v></c></row>')
    sheets = read_xlsx(xlsx)
    assert sheets["Tables"][0] == {"object_name": "table_name", "application": "OWNER"}


def test_inventory_extract_registers_tables_and_edges(tmp_path):
    engine = build_engine(tmp_path, with_batch=True)
    outcome = engine.run_node("inventory.extract")
    assert outcome.status == "SUCCEEDED", outcome.summary
    tables = engine.repo.list_data_objects(engine.assessment_id)
    names = {str(row["normalized_name"]) for row in tables}
    assert "TABLE_NAME" in names
    edges = engine.repo.list_lineage_edges(engine.assessment_id)
    assert edges, "ownership edges expected from application column"
    assert all(str(edge["relationship"]) == "owns" for edge in edges)


def test_inventory_extract_without_xlsx_waits(tmp_path):
    engine = build_engine(tmp_path, with_batch=False)
    outcome = engine.run_node("inventory.extract")
    assert outcome.status == "WAITING_FOR_INPUT"
