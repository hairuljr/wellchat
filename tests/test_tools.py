"""Tool read-only yang dipanggil agen, diuji dengan dataset asli."""

import json

import pytest

from wellchat import tools
from wellchat.tools import call_tool


def test_planned_operations_cover_every_report(db_conn):
    plans = json.loads(call_tool(db_conn, "get_planned_operations", {}))["plans"]
    assert {p["type"] for p in plans} == {"DDR", "DGOS"}
    dgos72 = next(p for p in plans if p["file"] == "BARAKUDA-1_DGOS_72_20260829.pdf")
    assert "WL Run #1: PEX-QAIT" in dgos72["next_24_hrs"] and "MDT (QS-Saturn)" in dgos72["next_24_hrs"]
    ddr53 = next(p for p in plans if p["type"] == "DDR" and p["report_no"] == "53")
    assert "MDT-QS" in ddr53["24_hr_forecast"]
    assert [p["report_date"] for p in plans] == sorted(p["report_date"] for p in plans)


def test_list_reports_names_the_wells_with_reports(db_conn):
    out = json.loads(call_tool(db_conn, "list_reports", {}))
    assert out["wells"] == ["BARAKUDA-1"]
    assert "offset" in out["note"].lower()


def test_oversized_result_stays_valid_json(monkeypatch):
    monkeypatch.setitem(tools.DISPATCH, "big", lambda conn: {"text": 'say "hi" ' * 5000})
    out = json.loads(call_tool(None, "big", {}))
    assert out["truncated"] is True and len(out["partial"]) == tools.MAX_RESULT_CHARS


def test_oversized_list_result_drops_items_but_keeps_citations(monkeypatch):
    hits = [{"file": f"r{i}.pdf", "page": i, "text": "x" * 1000} for i in range(30)]
    monkeypatch.setitem(tools.DISPATCH, "many", lambda conn: {"query": "q", "results": hits})
    text = call_tool(None, "many", {})
    out = json.loads(text)
    assert len(text) <= tools.MAX_RESULT_CHARS and out["truncated"] is True
    assert out["results"] == hits[:len(out["results"])] and len(out["results"]) > 5


def test_dgos_mud_weight_is_a_field(db_conn):
    out = json.loads(call_tool(db_conn, "get_report_fields", {"field": "mud weight"}))
    dgos72 = [f for f in out["fields"] if f["file"] == "BARAKUDA-1_DGOS_72_20260829.pdf"]
    assert [f["value"] for f in dgos72] == ["14.1 ppg"]


@pytest.mark.parametrize("topic", ["wireline", "WL", "wireline run"])
def test_planned_operations_filtered_by_topic(db_conn, topic):
    out = json.loads(call_tool(db_conn, "get_planned_operations", {"topic": topic}))
    assert [(p["type"], p["report_no"]) for p in out["plans"]] == [("DDR", "53"), ("DGOS", "72")]
    assert "note" not in out


def test_planned_operations_without_match_still_returns_every_plan(db_conn):
    out = json.loads(call_tool(db_conn, "get_planned_operations", {"topic": "helicopter"}))
    assert len(out["plans"]) == len(json.loads(call_tool(db_conn, "get_planned_operations", {}))["plans"])
    assert "no plan mentions" in out["note"]
