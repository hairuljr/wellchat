import json

import pytest


def _load(parsed_dir, needle):
    files = [p for p in parsed_dir.glob("*.json") if needle in p.name]
    assert files, f"no parsed file containing {needle}"
    return json.loads(files[0].read_text(encoding="utf-8"))


def _field(doc, label):
    return next(f["value"] for f in doc["fields"] if f["label"] == label)


def test_dgos_header_and_location(parsed_dir):
    d = _load(parsed_dir, "DGOS_72")
    assert d["doc_type"] == "DGOS" and d["report_no"] == "72" and d["report_date"] == "2026-08-29"
    assert "MALAYSIA" in _field(d, "COUNTRY")
    assert _field(d, "BASIN") == "OFFSHORE TERENGGANU"


def test_dgos_hidden_white_labels_are_removed(parsed_dir):
    d = _load(parsed_dir, "DGOS_84")
    assert _field(d, "Current Date") == "10-09-2026"  # not "Cu1r0r-e0n9t- 2D0a2t6e"
    assert d["npt"].startswith("1.50 hrs due to redressing Saturn packer")


def test_dgos_planned_wireline_runs(parsed_dir):
    d = _load(parsed_dir, "DGOS_72")
    nxt = next(s for s in d["sections"] if s["name"] == "NEXT 24 HRS OPERATION")
    assert "WL Run #1: PEX-QAIT" in nxt["text"] and "WL Run #2: MDT (QS-Saturn)" in nxt["text"]


def test_dgos_tables(parsed_dir):
    d = _load(parsed_dir, "DGOS_84")
    tops = next(t for t in d["tables"] if t["name"] == "FORMATION TOPS")
    seabed = tops["rows"][0]
    assert seabed["Formation"] == "Seabed" and seabed["MD Act (m MDDF)"] == "95.9"
    casing = next(t for t in d["tables"] if t["name"] == "DRILLING SUMMARY / CASING")
    assert any(r["Casing size and type"] == '20" Casing' for r in casing["rows"])


def test_ddr_header_and_npt(parsed_dir):
    d = _load(parsed_dir, "DDR_32")
    assert d["doc_type"] == "DDR" and d["report_no"] == "32" and d["report_date"] == "2026-07-19"
    assert _field(d, "Daily NPT") == "1.50 hr" and _field(d, "Cumm NPT") == "1.50 hr"
    assert d["derived"]["npt_hours_from_operation_rows"] == pytest.approx(1.5)
    assert any("Spud date" in w for w in d["warnings"])  # 27/06/2027 typo in the source


def test_ddr_operations(parsed_dir):
    d = _load(parsed_dir, "DDR_53")
    ops = d["operations"]
    assert ops[0]["from"] == "0:00" and ops[0]["activity"] == "FLW"
    assert sum(o["hours"] for o in ops) == pytest.approx(24.0)
    assert any("PEX-QAIT" in o["operation"] for o in ops)
    assert d["next_day_operations"][0]["date"] == "10 August 2026"


def test_glossary(parsed_dir):
    g = _load(parsed_dir, "Glossaries")
    terms = {e["term"]: e for e in g["entries"]}
    assert terms["NPT"]["full_form"] == "Non-Productive Time"
    assert terms["BMP"]["to_be_confirmed"] is True
    assert "A" not in terms  # alphabet divider rows are skipped
