"""Parsing PDF yang dibuat saat test, meniru layout laporan tetapi dengan nilai berbeda.

Membuktikan parser bekerja berdasarkan label dan heading, bukan hafal file contoh,
dan test ini tetap jalan tanpa dataset privat.
"""

import json

import pytest

reportlab = pytest.importorskip("reportlab")
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from wellchat.ingest import ingest  # noqa: E402
from wellchat.store import connect  # noqa: E402
from wellchat.tools import call_tool  # noqa: E402

DDR_LINES = [
    "PTT PUBLIC COMPANY LIMITED",
    "Daily Operation Report",
    "Well: KERAPU-2 Wellbore No.: OH Report no.: 7 Report date: 03/02/2027",
    "WELL INFO",
    "Event Description: ORIGINAL Water Depth: 70.10 m Region: PM Rig Name: NAGA-9",
    "Objective: Field / Platform: AFE No.: Start date: Spud date: End date:",
    "EXPLORATION KERAPU-2 P.TEST.0001 20/01/2027 27/01/2027",
    "DEPTH DAYS COSTS(USD)",
    "DOL : 14.00 days MD : 850.00 m Rotating Hrs : Last Casing : 20.000 in Daily Cost : 100,000.00",
    "Daily NPT : 2.00 hr Cumm NPT : 9.75 hr Current Hole Size : 17.500 in Expenditure : 10.00%",
    "STATUS",
    "Current status : Drilling ahead.",
    "24 hr summary : Drilled 17-1/2in hole from 700m to 850m.",
    "24 hr forecast : Continue drilling to section TD.",
    "OPERATION SUMMARY",
    "From - To Hrs Phase Activity Productive / NPT Rig MD from Operation",
    "0:00 - 22:00 22.00 D18 DRL OPRN OPRN 850.00 Drill ahead from 700m to 850m.",
    "22:00 - 0:00 2.00 D18 RRP TPQP Y OPRN 850.00 Repair top drive.",
    "Note:",
    "- Top drive hydraulic hose leak.",
    "BIT DATA MUD CHECK MUD CHECK",
    "Density (ppg) 10.20",
]

DGOS_LINES = [
    "AFE No. : P.TEST.0001 PTT PUBLIC COMPANY LIMITED",
    "DAILY GEOLOGICAL OPERATIONS SUMMARY",
    "Current Date : 04-02-2027",
    "Start Date : 20-01-2027",
    "Spud Date : 27-01-2027",
    "WELL DATA Report No: 8",
    "WELL NAME : KERAPU-2 WD : 70.10 m",
    "OPERATOR : PTT PUBLIC COMPANY LIMITED COUNTRY : MYS |MALAYSIA",
    "CURRENT OPERATION @ 0600 HRS :",
    "Drilling 17-1/2in hole.",
    "LAST 24 HRS OPERATION",
    "Drilled from 850m to 990m.",
    "NPT: 0.50 hrs due to pump repair.",
    "NEXT 24 HRS OPERATION",
    "Perform WL Run #1: GR-Sonic.",
]


def _pdf(path, lines):
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(30, y, line)
        y -= 14
    c.save()


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic")
    raw = root / "raw"
    raw.mkdir()
    _pdf(raw / "any_name_ddr.pdf", DDR_LINES)
    _pdf(raw / "another_dgos.pdf", DGOS_LINES)
    _pdf(raw / "unrelated.pdf", ["MINUTES OF MEETING", "Lunch menu was discussed."])
    stats = ingest(raw, root / "parsed", root / "db.sqlite", log=lambda *_: None)
    return root, stats


def test_all_files_parsed(synthetic):
    _, stats = synthetic
    assert stats == {"parsed": 3, "skipped": 0, "failed": 0, "removed": 0, "documents": 3}


def test_new_ddr_fields_and_npt(synthetic):
    root, _ = synthetic
    d = json.loads((root / "parsed" / "any_name_ddr.pdf.json").read_text())
    f = {x["label"]: x["value"] for x in d["fields"]}
    assert d["doc_type"] == "DDR" and d["well_name"] == "KERAPU-2" and d["report_date"] == "2027-02-03"
    assert f["Cumm NPT"] == "9.75 hr" and f["Rig Name"] == "NAGA-9" and f["Spud date"] == "27/01/2027"
    assert [o["npt"] for o in d["operations"]] == [False, True]
    assert "hydraulic hose" in d["operations"][1]["operation"]
    assert d["warnings"] == []


def test_new_dgos_and_search(synthetic):
    root, _ = synthetic
    d = json.loads((root / "parsed" / "another_dgos.pdf.json").read_text())
    assert d["doc_type"] == "DGOS" and d["report_no"] == "8" and d["npt"] == "0.50 hrs due to pump repair."
    conn = connect(root / "db.sqlite")
    out = json.loads(call_tool(conn, "search_reports", {"query": "GR-Sonic wireline"}))
    assert out["results"][0]["file"] == "another_dgos.pdf"


def test_unknown_layout_still_searchable(synthetic):
    root, _ = synthetic
    conn = connect(root / "db.sqlite")
    out = json.loads(call_tool(conn, "search_reports", {"query": "lunch menu"}))
    assert out["results"] and out["results"][0]["file"] == "unrelated.pdf"
