"""Parser untuk Daily Geological Operations Summary (DGOS)."""

from __future__ import annotations

import re

from ..pdf_text import PageText, split_labeled_line, to_iso_date
from .common import Line, flatten, sectionize, snake

HEADER_LABELS = [
    "AFE No.", "Current Date", "Start Date", "Spud Date", "Report No",
    "WELL NAME", "WD", "OPERATOR", "COUNTRY", "OPERATORSHIP", "REGION",
    "BLOCK", "WELL CLASSIFICATION", "BASIN", "WELL PROFILE",
    "LATITUDE", "NORTHING", "LONGITUDE", "EASTING", "DATUM", "PROJECTION",
    "MAX DEVIATION", "LOCATION REMARKS", "Operation Geologist(s)", "Wellsite Geologist",
    "RIG NAME", "RIG TYPE", "RIG CONTRACTOR", "DFE (AMSL)", "OFFSET WELLS",
]

# Blok teks bebas: baris heading -> nama section. Isinya berlanjut sampai heading berikutnya.
HEADINGS = [
    ("CURRENT OPERATION @ 0600 HRS", re.compile(r"^CURRENT OPERATION @")),
    ("LAST 24 HRS OPERATION", re.compile(r"^LAST 24 HRS OPERATION")),
    ("NEXT 24 HRS OPERATION", re.compile(r"^NEXT 24 HRS OPERATION")),
    ("OBJECTIVES", re.compile(r"^(OFFSET WELLS.*|OBJECTIVES)$")),
    ("LOCATION / RIG DATA", re.compile(r"^LOCATION DATA")),
    ("DAILY REMARKS", re.compile(r"DAILY REMARKS$")),
    ("DRILLING SUMMARY / CASING", re.compile(r"^(DRILLING SUMMARY|CASING AND SHOE DEPTH)$")),
    ("FORMATION TOPS", re.compile(r"^FORMATION TOPS")),
    ("GAS SHOWS", re.compile(r"^GAS SHOWS?$")),
    ("OIL SHOWS", re.compile(r"^OIL SHOWS?$")),
    ("MNEMONICS", re.compile(r"^MNEMONICS")),
]

# "D12 71.50 35.43 2530.00 / 2498.93"  -> phase, hari, biaya MUSD, kedalaman MDDF / TVDSS
PHASE_ROW = re.compile(r"^(?P<phase>[A-Z]{1,4}\d{0,3})\s+(?P<days>[\d.]+)\s+(?P<cost>[\d.]+)\s+(?P<md>[\d.]+)\s*/\s*(?P<tvdss>[\d.]+)$")
# "LOCATION DATA AFE 70.08 51.00 3135.00 / 3105.00"
AFE_ROW = re.compile(r"AFE\s+(?P<days>[\d.]+)\s+(?P<cost>[\d.]+)\s+(?P<md>[\d.]+)\s*/\s*(?P<tvdss>[\d.]+)")
# "- - 14.1 SBM 29-08-2026 hrs 06:00" -> progress, avg ROP, mud weight, jenis mud, tanggal, jam
MUD_ROW = re.compile(r"^(?P<progress>\S+)\s+(?P<rop>\S+)\s+(?P<mw>[\d.]+)\s+(?P<mud>[A-Z]+)\s+(?P<date>\d{2}-\d{2}-\d{4})\s+hrs\s+(?P<time>\d{2}:\d{2})")
NPT_LINE = re.compile(r"^NPT\s*:\s*(?P<text>.+)$", re.I)
REMARK_ROW = re.compile(r"^(?P<no>\d{1,2})\s+(?P<text>[A-Za-z].+)$")


def _fields(lines: list[Line]) -> list[dict]:
    fields: dict[str, dict] = {}
    for ln in lines:
        text = ln.text.replace("Report No:", "Report No :").replace("OFFSET WELLS:", "OFFSET WELLS :")
        for label, value in split_labeled_line(text, HEADER_LABELS).items():
            if label not in fields or (value and not fields[label]["value"]):
                fields[label] = {"key": snake(label), "label": label, "value": value, "page": ln.page}
    # sebagian label kehilangan titik dua saat teks putih dibersihkan; pulihkan pola "Start Date 18-06-2026"
    for label in ("Start Date", "Spud Date", "Current Date"):
        if not fields.get(label, {}).get("value"):
            for ln in lines:
                m = re.match(rf"^{label}\s*:?\s*(\d{{2}}-\d{{2}}-\d{{4}})", ln.text)
                if m:
                    fields[label] = {"key": snake(label), "label": label, "value": m.group(1), "page": ln.page}
                    break
    # buang heading di ujung baris yang menempel pada MAX DEVIATION / RIG NAME dll.; hanya bila
    # menempel di belakang teks lain, karena OPERATOR bisa berisi persis "PTT PUBLIC COMPANY LIMITED"
    for f in fields.values():
        f["value"] = re.sub(r"(?<=\S)\s+(RIG INFORMATION|PTT PUBLIC COMPANY LIMITED)$", "", f["value"]).strip()
    # OFFSET WELLS berlanjut ke baris baru, satu-dua baris di bawah, berselang-seling dengan OBJECTIVES
    offset = fields.get("OFFSET WELLS")
    if offset and offset["value"].endswith(","):
        start = next(i for i, l in enumerate(lines) if l.text.startswith("OFFSET WELLS"))
        for l in lines[start + 1:start + 4]:
            if re.match(r"^[A-Z0-9-]+ PLATFORM \(", l.text):
                offset["value"] += " " + l.text
                break
    return list(fields.values())


def _progress(lines: list[Line]) -> dict:
    out: dict = {}
    for ln in lines:
        t = ln.text
        if "phase" not in out and (m := PHASE_ROW.match(t)) and not t.startswith("AFE"):
            out["phase"] = {"phase": m["phase"], "days": float(m["days"]), "cost_musd": float(m["cost"]),
                            "depth_m_mddf": float(m["md"]), "depth_m_tvdss": float(m["tvdss"]), "page": ln.page}
        if "afe" not in out and (m := AFE_ROW.search(t)):
            out["afe"] = {"days": float(m["days"]), "cost_musd": float(m["cost"]),
                          "depth_m_mddf": float(m["md"]), "depth_m_tvdss": float(m["tvdss"]), "page": ln.page}
        if "mud" not in out and (m := MUD_ROW.match(t)):
            out["mud"] = {"progress_m": m["progress"], "avg_rop_m_per_hr": m["rop"],
                          "mud_weight_ppg": float(m["mw"]), "mud_type": m["mud"],
                          "date": m["date"], "time": m["time"], "page": ln.page}
    return out


def _table_block(pages: list[PageText], start: re.Pattern, row: re.Pattern, width: int) -> dict | None:
    """Baris dari satu tabel logis di dalam grid tabel pdfplumber (sering selebar halaman).

    Halaman DGOS terdeteksi sebagai satu grid besar, jadi tabel logis adalah
    rangkaian baris setelah sel heading (`start`) yang sel pertamanya cocok dengan
    `row`. Kolom yang kosong di semua baris data dibuang; hasilnya dilengkapi sampai `width`.
    """
    for p in pages:
        for t in p.tables:
            idx = next((i for i, r in enumerate(t) if r and start.search(r[0])), None)
            if idx is None:
                continue
            rows = []
            for r in t[idx + 1:]:
                if not r or not r[0]:
                    continue
                if row.match(r[0]):
                    rows.append(r)
                elif rows:
                    break
            if not rows:
                continue
            keep = [i for i in range(len(rows[0])) if any(i < len(r) and r[i] for r in rows)]
            data = [[r[i] for i in keep][:width] for r in rows]
            data = [d + [""] * (width - len(d)) for d in data]
            return {"page": p.number, "rows": data}
    return None


def parse_dgos(pages: list[PageText]) -> dict:
    lines = flatten(pages)
    fields = _fields(lines)
    by_label = {f["label"]: f["value"] for f in fields}
    sections = sectionize(lines, HEADINGS)

    npt = next((NPT_LINE.match(l.text)["text"] for l in lines if NPT_LINE.match(l.text)), None)
    remarks = []
    in_remarks = False
    for ln in lines:
        if ln.text.endswith("DAILY REMARKS"):
            in_remarks = True
            continue
        if in_remarks:
            if ln.text in ("DRILLING SUMMARY", "CASING AND SHOE DEPTH"):
                break
            if m := REMARK_ROW.match(ln.text):
                remarks.append({"no": int(m["no"]), "text": m["text"], "page": ln.page})

    tables = []
    table_specs = [
        ("DRILLING SUMMARY / CASING", re.compile(r"^HOLE SIZE"), re.compile(r"^\d"),
         ["Hole Size (in)", "Start Hole Depth (m MDDF)", "End Hole Depth (m MDDF)",
          "Shoe Depth (m MDDF)", "FIT/LOT (ppg)", "Casing size and type"]),
        ("FORMATION TOPS", re.compile(r"^FORMATION TOPS \*|^FORMATION TOPS$"),
         re.compile(r"^(Seabed|Top |FTD|[A-Z][\w/-]*\d\**$|[A-Z][\w/ -]*\*+$)"),
         ["Formation", "MD Prog (m MDDF)", "TVD Prog (m TVDDF)", "TVDSS Prog (m)",
          "MD Act (m MDDF)", "TVD Act (m TVDDF)", "TVDSS Act (m)", "Diff Hi/Lo (m)", "Remarks"]),
    ]
    for name, start, row, columns in table_specs:
        block = _table_block(pages, start, row, len(columns))
        if block:
            tables.append({"name": name, "page": block["page"], "columns": columns,
                           "rows": [dict(zip(columns, r)) for r in block["rows"]]})

    warnings = []
    report_date = to_iso_date(by_label.get("Current Date"))
    spud = to_iso_date(by_label.get("Spud Date"))
    if report_date and spud and spud > report_date:
        warnings.append(f"Spud date {by_label.get('Spud Date')} is after report date {by_label.get('Current Date')}.")

    return {
        "doc_type": "DGOS",
        "well_name": by_label.get("WELL NAME") or None,
        "report_no": by_label.get("Report No") or None,
        "report_date": report_date,
        "fields": fields,
        "sections": sections,
        "npt": npt,
        "progress": _progress(lines),
        "daily_remarks": remarks,
        "tables": tables,
        "warnings": warnings,
    }
