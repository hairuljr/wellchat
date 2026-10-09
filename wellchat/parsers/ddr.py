"""Parser untuk Daily Operation Report (DDR, Daily Drilling Report)."""

from __future__ import annotations

import re

from ..pdf_text import PageText, split_labeled_line, to_iso_date
from .common import Line, collect_labeled_block, flatten, sectionize, snake

# Label yang tercetak sebagai `Label : value` di header laporan.
HEADER_LABELS = [
    "Well", "Wellbore No.", "Report no.", "Report date",
    "Event Description", "Water Depth", "Region", "Rig Name",
    "Block", "Lead DS", "Night DS", "PTT Engineer",
    "DOL", "MD", "Rotating Hrs", "Last Casing", "Daily Cost",
    "DFS", "TVD", "Cum Rot Hrs", "Last Hole Size", "Cumm Cost",
    "Total Days", "Progress", "Avg. ROP", "Last Shoe TMD", "AFE Cost",
    "Est days", "Final TMD", "Last Shoe TVD", "Supp Costs / Days",
    "Daily NPT", "Cumm NPT", "Current Hole Size", "Expenditure",
]

# Label yang tercetak sebagai satu baris judul kolom, dengan nilainya di baris berikutnya.
COLUMN_LABELS = ["Objective", "Field / Platform", "AFE No.", "Start date", "Spud date", "End date"]

STATUS_LABELS = ["Current status", "24 hr summary", "24 hr forecast", "Incident / Accident", "Remarks"]

# Baris yang berulang di setiap halaman dan tidak membawa informasi.
DROP = [
    re.compile(r"^PTT PUBLIC COMPANY LIMITED$"),
    re.compile(r"^Daily Operation Report$", re.I),
    re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2} \d+$"),  # cap waktu cetak + nomor halaman
]
PAGE_HEADER = re.compile(r"^Well:.*Report no\.:.*Report date:", re.I)
OPS_TABLE_HEADER = [
    re.compile(r"^From - To Hrs Phase Activity"),
    re.compile(r"^Code Code Non-Productive Status"),
    re.compile(r"^Code$"),
]

HEADINGS = [
    ("WELL INFO", re.compile(r"^WELL INFO$")),
    ("DEPTH / DAYS / COSTS", re.compile(r"^DEPTH DAYS COSTS")),
    ("STATUS", re.compile(r"^STATUS$")),
    ("OPERATION SUMMARY", re.compile(r"^OPERATION SUMMARY$")),
    ("BIT DATA / MUD CHECK", re.compile(r"^BIT DATA")),
    ("BHA ASSEMBLY COMPONENTS", re.compile(r"^Assembly Components$")),
    ("GAS READINGS / MUD VOLUME", re.compile(r"^GAS READINGS")),
    ("PUMP / HYDRAULICS", re.compile(r"^PUMP/HYDRAULICS")),
    ("SHAKER / CENTRIFUGE / HYDROCYCLONE", re.compile(r"^SHAKER")),
    ("LOT/FIT / FORMATION DATA", re.compile(r"^LOT/FIT")),
    ("SUPPORT CRAFT", re.compile(r"^SUPPORT CRAFT$")),
    ("BULKS", re.compile(r"^BULKS$")),
    ("WEATHER / SAFETY CARDS / PERSONNEL", re.compile(r"^WEATHER SAFETY CARDS")),
    ("ANCHOR TENSION", re.compile(r"^ANCHOR TENSION$")),
    ("SAFETY", re.compile(r"^SAFETY$")),
    ("SURVEYS", re.compile(r"^SURVEYS$")),
]

OP_ROW = re.compile(
    r"^(?P<from>\d{1,2}:\d{2})\s*-\s*(?P<to>\d{1,2}:\d{2})\s+(?P<hrs>\d+(?:\.\d+)?)\s+"
    r"(?P<phase>\S+)\s+(?P<activity>\S+)\s+(?P<prod>\S+)\s+(?:(?P<npt>Y|N)\s+)?"
    r"(?P<rig_status>\S+)\s+(?P<md>[\d,]+(?:\.\d+)?|-)\s*(?P<op>.*)$"  # MD bisa bilangan bulat atau kosong ("-")
)
# heading apa pun setelah tabel operasi menandai akhir tabel, walau BIT DATA / BHA tidak ada
OPS_END = [rx for name, rx in HEADINGS if name != "OPERATION SUMMARY"]
NEXT_DAY_ROW = re.compile(r"^(?P<from>\d{1,2}:\d{2})\s*-\s*(?P<to>\d{1,2}:\d{2})\s*hrs$", re.I)
NEXT_DAY_DATE = re.compile(r"^(\d{1,2})(st|nd|rd|th)\s+([A-Za-z]+)\s+(\d{4})$")
SEPARATOR = re.compile(r"^[*_=\-]{6,}$")
DATE_TOKEN = re.compile(r"^\d{2}[/-]\d{2}[/-]\d{4}$")


def _header_fields(lines: list[Line]) -> list[dict]:
    fields: dict[str, dict] = {}
    for i, ln in enumerate(lines):
        if ln.page != 1:
            continue
        for label, value in split_labeled_line(ln.text, HEADER_LABELS).items():
            if label not in fields or (value and not fields[label]["value"]):
                fields[label] = {"key": snake(label), "label": label, "value": value, "page": ln.page}
        # header bergaya kolom: label di satu baris, nilai di baris berikutnya
        if ln.text.startswith("Objective:") and i + 1 < len(lines):
            tokens = lines[i + 1].text.split()
            dates = [t for t in tokens if DATE_TOKEN.match(t)]
            others = [t for t in tokens if not DATE_TOKEN.match(t)]
            for label, value in zip(COLUMN_LABELS[:3], others):
                fields[label] = {"key": snake(label), "label": label, "value": value, "page": ln.page}
            for label, value in zip(COLUMN_LABELS[3:], dates):
                fields[label] = {"key": snake(label), "label": label, "value": value, "page": ln.page}
    status = collect_labeled_block(
        [l for l in lines if l.page == 1], STATUS_LABELS, re.compile(r"^OPERATION SUMMARY$")
    )
    for label, value in status.items():
        fields[label] = {"key": snake(label), "label": label, "value": value, "page": 1}
    return list(fields.values())


def _number(text: str) -> float | None:
    return None if text == "-" else float(text.replace(",", ""))


def _operations(lines: list[Line]) -> tuple[list[dict], list[dict]]:
    """Baris tabel OPERATION SUMMARY, ditambah update 00:00-06:00 hari berikutnya."""
    ops: list[dict] = []
    next_day: list[dict] = []
    in_ops = False
    next_day_date: str | None = None
    current: dict | None = None
    for ln in lines:
        t = ln.text
        if t == "OPERATION SUMMARY":
            in_ops = True
            continue
        if not in_ops:
            continue
        if any(rx.search(t) for rx in OPS_END):
            break
        if PAGE_HEADER.search(t) or any(rx.search(t) for rx in OPS_TABLE_HEADER):
            continue
        m = OP_ROW.match(t)
        if m and next_day_date is None:
            current = {
                "from": m["from"], "to": m["to"], "hours": float(m["hrs"]),
                "phase": m["phase"], "activity": m["activity"],
                "productive_code": m["prod"], "npt": m["npt"] == "Y",
                "rig_status": m["rig_status"], "md_from_m": _number(m["md"]),
                "operation": m["op"].strip(), "page": ln.page,
            }
            ops.append(current)
            continue
        if SEPARATOR.match(t):
            continue
        d = NEXT_DAY_DATE.match(t)
        if d:
            next_day_date = f"{d.group(1)} {d.group(3)} {d.group(4)}"
            continue
        n = NEXT_DAY_ROW.match(t)
        if n:
            current = {"date": next_day_date, "from": n["from"], "to": n["to"], "operation": "", "page": ln.page}
            next_day.append(current)
            continue
        if current is not None:
            current["operation"] = (current["operation"] + "\n" + t).strip()
    return ops, next_day


def parse_ddr(pages: list[PageText]) -> dict:
    lines = flatten(pages, DROP)
    fields = _header_fields(lines)
    by_label = {f["label"]: f["value"] for f in fields}
    operations, next_day = _operations(lines)

    body = [l for l in lines if not PAGE_HEADER.search(l.text)]
    sections = sectionize(body, HEADINGS)

    warnings = []
    report_date = to_iso_date(by_label.get("Report date"))
    spud = to_iso_date(by_label.get("Spud date"))
    if report_date and spud and spud > report_date:
        warnings.append(
            f"Spud date {by_label.get('Spud date')} is after report date {by_label.get('Report date')} "
            "(probably a typo in the source report)."
        )
    npt_rows = sum(o["hours"] for o in operations if o["npt"])
    daily_npt = by_label.get("Daily NPT", "")
    m = re.match(r"([\d.]+)", daily_npt or "")
    if m and operations and abs(float(m.group(1)) - npt_rows) > 0.01:
        warnings.append(
            f"Daily NPT field says {daily_npt} but NPT rows in the operation table sum to {npt_rows:.2f} hr."
        )

    return {
        "doc_type": "DDR",
        "well_name": by_label.get("Well") or None,
        "report_no": by_label.get("Report no.") or None,
        "report_date": report_date,
        "fields": fields,
        "sections": sections,
        "operations": operations,
        "next_day_operations": next_day,
        "derived": {"npt_hours_from_operation_rows": round(npt_rows, 2)},
        "warnings": warnings,
    }
