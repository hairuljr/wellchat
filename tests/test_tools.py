"""Read-only tools the agent calls, run against the real dataset."""

import json

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
