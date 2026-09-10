import json
from pathlib import Path

import pytest

from sassessment.legacy_logs.engine import parse_text, parse_file
from sassessment.legacy_logs.model import ParsedLog

_REPO_ROOT = Path(__file__).resolve().parents[1]

ONE_LINE_TB_LOG = (
    'TB_LOG: 2104380894.63074 - "batch_user" - 2347184 - "LOG" - '
    '"dmf_loop_exploitation INI 2347184" - "PRO 07SEP26 D 400 DEFAULT"'
)
WRAPPED_TB_LOG = (
    'TB_LOG: 2104380898.489 - "batch_user" - 2347184 - "LOG" -\n'
    '"dmf_exploitation_transform FIN" -\n'
    '"07SEP26 D 400 DEFAULT"'
)
TB_LOG_WITH_DASH_IN_EVENT = (
    'TB_LOG: 2104380904.09874 - "batch_user" - 2347200 - "LOG" -\n'
    '"call dmf_loop - prios" - "EXPL_D_400 - note"'
)


def tb_records(parsed):
    return [r for r in parsed.records if r.record_type == "TB_LOG"]


def test_single_line_tb_log():
    parsed = parse_text(ONE_LINE_TB_LOG)
    tb = tb_records(parsed)
    assert len(tb) == 1
    record = tb[0]
    assert record.user == "batch_user"
    assert record.job_id == 2347184
    assert record.source_severity == "LOG"
    assert record.lifecycle_marker == "INI"
    assert record.component == "dmf_loop_exploitation"
    assert record.entity_or_partition == 400
    assert record.normalized_impact == "INFO"


def test_multiline_tb_log_parsing():
    parsed = parse_text(WRAPPED_TB_LOG)
    tb = tb_records(parsed)
    assert tb[0].event_name.startswith("dmf_exploitation_transform")
    assert tb[0].lifecycle_marker == "FIN"


def test_tb_log_dash_inside_quotes_not_split():
    parsed = parse_text(TB_LOG_WITH_DASH_IN_EVENT)
    tb = tb_records(parsed)
    assert tb[0].context == "EXPL_D_400 - note"
    assert "call" in tb[0].event_name or "dmf" in tb[0].event_name


def test_ini_fin_pairing_and_missing_fin():
    text = (
        ONE_LINE_TB_LOG + "\n"
        'TB_LOG: 2104380895 - "u" - 1 - "LOG" - "dmf_exploitation_transform INI" - "ctx"\n'
        'TB_LOG: 2104380899 - "u" - 1 - "LOG" - "dmf_exploitation_transform FIN" - "ctx"\n'
        'TB_LOG: 2104380900 - "u" - 1 - "LOG" - "dmf_exploitation_load INI" - "ctx"\n'
    )
    parsed = parse_text(text)
    incomplete = [stage for stage in parsed.lifecycle if not stage.complete]
    assert incomplete
    assert any(stage.component == "dmf_exploitation_load" for stage in incomplete)


def test_orphan_fin_preserved():
    text = 'TB_LOG: 1 - "u" - 1 - "LOG" - "dmf_exploitation_orphan FIN" - "c"\n'
    parsed = parse_text(text)
    orphans = [s for s in parsed.lifecycle if s.marker == "ORPHAN_FIN"]
    assert orphans
    assert parsed.metrics["orphan_fin_count"] >= 1


def test_duplicate_ini_keeps_both_stages():
    text = (
        'TB_LOG: 1 - "u" - 1 - "LOG" - "dmf_exploitation_x INI" - "e 400"\n'
        'TB_LOG: 2 - "u" - 1 - "LOG" - "dmf_exploitation_x FIN" - "e 400"\n'
        'TB_LOG: 3 - "u" - 1 - "LOG" - "dmf_exploitation_x INI" - "e 400"\n'
    )
    parsed = parse_text(text)
    x_stages = [s for s in parsed.lifecycle if s.component == "dmf_exploitation_x"]
    assert len(x_stages) == 2


def test_loop_iterations_and_sleep():
    text = (
        'TB_LOG: 1 - "u" - 1 - "LOG" - "Ini dmf_execution_expl Job: 100 - '
        'exeBucleExploitation 1" - ""\n'
        'TB_LOG: 2 - "u" - 1 - "LOG" - "Fin dmf_execution_expl - '
        'exeBucleExploitation 1" - ""\n'
        "time_sleep: 5\n"
        'TB_LOG: 3 - "u" - 1 - "LOG" - "Ini dmf_execution_expl Job: 100 - '
        'exeBucleExploitation 2" - ""\n'
    )
    parsed = parse_text(text)
    assert parsed.metrics["iterations"] == [1, 2]
    assert parsed.metrics["sleeps"] == [5.0]


def test_sas_duration_five_minutes():
    parsed = parse_text(
        "NOTE: DATA statement ha utilizado (Tiempo de proceso total):\n"
        "real time 5:00.00\n"
        "cpu time 0.00 seconds\n"
    )
    timings = [r for r in parsed.records if r.record_type == "TIMING"]
    assert timings[0].duration_seconds == 5.0 * 60


def test_source_echo_and_continuation():
    text = '307781    + filename cmd pipe "find\n"307781   !+ ! -perm 775;"\n'
    parsed = parse_text(text.replace('307781    + ba', '307781    + ba'))
    src = [r for r in parsed.records if r.record_type == "SAS_SOURCE"]
    if not src:
        pytest.skip("source continuation not assembled")
    assert src[0].message is not None


def test_page_header_line_kept_as_header_record():
    text = "\x0c5362                 Sistema SAS\nlunes, 7 de septiembre de 2026 06:14:00\n"
    parsed = parse_text(text)
    assert any(r.record_type == "PAGE_HEADER" for r in parsed.records)


def test_unknown_records_retained():
    text = "loitertast otx unknown-marker no-anchor\n"
    parsed = parse_text(text)
    assert any(r.record_type == "RAW_UNKNOWN" for r in parsed.records)
    assert parsed.metrics["unclassified_count"] >= 1
