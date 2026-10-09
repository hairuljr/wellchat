"""Tool read-only yang bisa dipanggil LLM. Setiap hasil membawa file + halaman untuk sitasi."""

from __future__ import annotations

import json
import sqlite3

from . import config
from .store import fts_query

# Batas karakter untuk satu hasil tool. Nilai aslinya dari config (env MAX_TOOL_RESULT_CHARS);
# dibaca lewat config saat dipakai supaya perubahan env atau monkeypatch tetap berlaku.
MAX_RESULT_CHARS = config.MAX_TOOL_RESULT_CHARS


def _limit() -> int:
    return int(getattr(config, "MAX_TOOL_RESULT_CHARS", MAX_RESULT_CHARS) or MAX_RESULT_CHARS)


def _docs(conn: sqlite3.Connection, include_glossary: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM documents"
    if not include_glossary:
        sql += " WHERE doc_type != 'GLOSSARY'"
    return conn.execute(sql + " ORDER BY report_date, file_name").fetchall()


def _resolve(conn: sqlite3.Connection, file: str | None) -> sqlite3.Row | None:
    if not file:
        return None
    row = conn.execute("SELECT * FROM documents WHERE file_name = ? OR doc_id = ?", (file, file)).fetchone()
    if row:
        return row
    return conn.execute("SELECT * FROM documents WHERE file_name LIKE ?", (f"%{file}%",)).fetchone()


def _doc_brief(d: sqlite3.Row) -> dict:
    return {"file": d["file_name"], "type": d["doc_type"], "well": d["well_name"],
            "report_no": d["report_no"], "report_date": d["report_date"], "pages": d["page_count"]}


def list_reports(conn: sqlite3.Connection) -> dict:
    docs = _docs(conn, include_glossary=True)
    return {
        "wells": sorted({d["well_name"] for d in docs if d["doc_type"] != "GLOSSARY" and d["well_name"]}),
        "reports": [{**_doc_brief(d), "data_quality_warnings": json.loads(d["warnings"] or "[]")}
                    for d in docs if d["doc_type"] != "GLOSSARY"],
        "glossaries": [d["file_name"] for d in docs if d["doc_type"] == "GLOSSARY"],
        "note": ("DDR = Daily Drilling/Operation Report, DGOS = Daily Geological Operations Summary. "
                 "Only the wells listed in `wells` have reports. Other well/platform names in the text "
                 "(e.g. OFFSET WELLS) are references only; there is no data about them."),
    }


def get_planned_operations(conn: sqlite3.Connection) -> dict:
    """Rencana operasi berikutnya menurut setiap laporan, diurutkan dari laporan terlama."""
    plans = []
    for d in _docs(conn):
        brief = _doc_brief(d)
        if d["doc_type"] == "DGOS":
            rows = conn.execute("SELECT text FROM sections WHERE doc_id = ? AND name = 'NEXT 24 HRS OPERATION'",
                                (d["doc_id"],)).fetchall()
            text = " ".join(r["text"] for r in rows).replace("NEXT 24 HRS OPERATION", "", 1).strip()
            if text:
                plans.append({**brief, "page": 1, "next_24_hrs": text})
        elif d["doc_type"] == "DDR":
            fields = {r["key"]: r for r in conn.execute(
                "SELECT key, value, page FROM fields WHERE doc_id = ? AND key IN ('24_hr_forecast', 'current_status')",
                (d["doc_id"],))}
            if fields:
                plans.append({**brief, "page": min(f["page"] for f in fields.values()),
                              **{k: f["value"] for k, f in fields.items()}})
    return {"plans": plans}


def search_reports(conn: sqlite3.Connection, query: str, report_type: str = "ANY", limit: int = 8) -> dict:
    q = fts_query(query)
    if not q:
        return {"results": [], "note": "empty query"}
    limit = max(1, min(int(limit or 8), 15))
    sql = (
        "SELECT c.text, c.kind, c.ref, c.page, d.file_name, d.doc_type, d.report_no, d.report_date "
        "FROM chunks_fts f JOIN chunks c ON c.id = f.rowid JOIN documents d ON d.doc_id = c.doc_id "
        "WHERE chunks_fts MATCH ? AND d.doc_type != 'GLOSSARY'"
    )
    args: list = [q]
    if report_type and report_type.upper() in ("DDR", "DGOS", "UNKNOWN"):
        sql += " AND d.doc_type = ?"
        args.append(report_type.upper())
    sql += " ORDER BY bm25(chunks_fts) LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    return {"results": [
        {"file": r["file_name"], "type": r["doc_type"], "report_no": r["report_no"], "report_date": r["report_date"],
         "page": r["page"], "section": r["ref"], "text": r["text"]} for r in rows
    ]}


def get_report_fields(conn: sqlite3.Connection, field: str | None = None, file: str | None = None) -> dict:
    """Field header (misalnya 'Cumm NPT', 'COUNTRY') dari semua laporan, kecuali `file` diisi."""
    sql = ("SELECT d.file_name, d.doc_type, d.report_no, d.report_date, f.label, f.value, f.page "
           "FROM fields f JOIN documents d ON d.doc_id = f.doc_id WHERE f.value != ''")
    args: list = []
    if file:
        doc = _resolve(conn, file)
        if not doc:
            return {"error": f"unknown file {file!r}; call list_reports"}
        sql += " AND d.doc_id = ?"
        args.append(doc["doc_id"])
    if field:
        words = [w for w in field.replace("_", " ").split() if w]
        for w in words:
            sql += " AND (f.label LIKE ? OR f.key LIKE ?)"
            args += [f"%{w}%", f"%{w}%"]
    sql += " ORDER BY d.report_date, d.file_name"
    rows = conn.execute(sql, args).fetchall()
    out = [{"file": r["file_name"], "type": r["doc_type"], "report_no": r["report_no"], "report_date": r["report_date"],
            "field": r["label"], "value": r["value"], "page": r["page"]} for r in rows]
    # baris NPT di DGOS berupa teks bebas, bukan field header; tampilkan juga saat yang dicari NPT
    if field and "npt" in field.lower():
        for d in _docs(conn):
            if d["doc_type"] == "DGOS":
                with open(d["json_path"], encoding="utf-8") as fh:
                    npt = json.load(fh).get("npt")
                if npt and (not file or _resolve(conn, file)["doc_id"] == d["doc_id"]):
                    out.append({"file": d["file_name"], "type": "DGOS", "report_no": d["report_no"],
                                "report_date": d["report_date"], "field": "NPT (Last 24 hrs operation)",
                                "value": npt, "page": 1})
    return {"fields": out} if out else {"fields": [], "note": "no matching field; try search_reports"}


def read_report_section(conn: sqlite3.Connection, file: str, section: str | None = None) -> dict:
    doc = _resolve(conn, file)
    if not doc:
        return {"error": f"unknown file {file!r}; call list_reports"}
    sections = conn.execute("SELECT name, pages, text FROM sections WHERE doc_id = ?", (doc["doc_id"],)).fetchall()
    names = [s["name"] for s in sections]
    if doc["doc_type"] == "DGOS":
        names.append("TABLES")
    if not section:
        return {**_doc_brief(doc), "sections": names}
    wanted = section.strip().upper()
    if wanted == "TABLES":
        tabs = conn.execute("SELECT name, page, rows FROM report_tables WHERE doc_id = ?", (doc["doc_id"],)).fetchall()
        return {**_doc_brief(doc), "tables": [{"name": t["name"], "page": t["page"], "rows": json.loads(t["rows"])} for t in tabs]}
    if wanted.startswith("OPERATION"):
        ops = conn.execute("SELECT * FROM operations WHERE doc_id = ? ORDER BY seq", (doc["doc_id"],)).fetchall()
        rows = [{"day": o["day"], "from": o["time_from"], "to": o["time_to"], "hours": o["hours"], "phase": o["phase"],
                 "activity": o["activity"], "productive_code": o["productive_code"], "npt": bool(o["npt"]),
                 "rig_status": o["rig_status"], "md_from_m": o["md_from_m"], "operation": o["operation"], "page": o["page"]}
                for o in ops]
        result = {**_doc_brief(doc), "section": "OPERATION SUMMARY", "rows": rows,
                  "npt_hours_in_rows": sum(r["hours"] or 0 for r in rows if r["npt"])}
    else:
        match = [s for s in sections if wanted in s["name"].upper()] or [s for s in sections if s["name"].upper() in wanted]
        if not match:
            return {"error": f"section {section!r} not found", "sections": names}
        result = {**_doc_brief(doc), "sections": [{"section": s["name"], "pages": json.loads(s["pages"]), "text": s["text"]} for s in match]}
    return result


def lookup_glossary(conn: sqlite3.Connection, term: str) -> dict:
    term = (term or "").strip()
    rows = conn.execute(
        "SELECT g.*, d.file_name FROM glossary g JOIN documents d ON d.doc_id = g.doc_id "
        "WHERE g.term = ? COLLATE NOCASE OR replace(g.term, '.', '') = ? COLLATE NOCASE", (term, term.replace(".", ""))
    ).fetchall()
    if not rows:
        q = fts_query(term)
        if q:
            rows = conn.execute(
                "SELECT g.*, d.file_name FROM chunks_fts f JOIN chunks c ON c.id = f.rowid "
                "JOIN glossary g ON g.term = c.ref AND g.doc_id = c.doc_id JOIN documents d ON d.doc_id = g.doc_id "
                "WHERE chunks_fts MATCH ? AND c.kind = 'glossary' ORDER BY bm25(chunks_fts) LIMIT 6", (q,)
            ).fetchall()
    return {"entries": [{"term": r["term"], "meaning": r["meaning"], "category": r["category"],
                         "to_be_confirmed": bool(r["to_be_confirmed"]), "file": r["file_name"]} for r in rows]}


TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "list_reports",
        "description": "List every parsed well report (file, type DDR/DGOS, report number, date) and glossary files, plus data-quality warnings found while parsing.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "search_reports",
        "description": "Full-text (BM25) search over report text: header fields, status, operation rows, remarks, tables. Reports are in ENGLISH with oil & gas abbreviations, so query with English keywords/abbreviations as they appear in reports (e.g. 'wireline run PEX MDT', 'NPT', 'mud weight', 'casing shoe').",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "report_type": {"type": "string", "enum": ["ANY", "DDR", "DGOS"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 15}},
            "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "get_report_fields",
        "description": "Exact header field values (e.g. 'Cumm NPT', 'Daily NPT', 'COUNTRY', 'REGION', 'Spud date', 'Daily Cost', 'Water Depth', 'Rig Name') across ALL reports, or one report when `file` is given. Best tool for numbers that must be compared between reports.",
        "parameters": {"type": "object", "properties": {
            "field": {"type": "string", "description": "words of the field label; empty = all fields"},
            "file": {"type": "string", "description": "file name from list_reports (optional)"}},
            "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "get_planned_operations",
        "description": "What every report says is planned next: DGOS 'NEXT 24 HRS OPERATION' and DDR '24 hr forecast' + 'Current status', oldest report first. Use for planned / next / forecast / rencana questions (e.g. planned wireline runs, next operation).",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "read_report_section",
        "description": "Read a whole section of one report. Omit `section` to list the sections. DDR sections include STATUS, OPERATION SUMMARY (row table with NPT flags), BIT DATA / MUD CHECK, SURVEYS, BULKS... DGOS sections include CURRENT OPERATION @ 0600 HRS, LAST 24 HRS OPERATION, NEXT 24 HRS OPERATION, DAILY REMARKS, TABLES (casing & formation tops).",
        "parameters": {"type": "object", "properties": {
            "file": {"type": "string"},
            "section": {"type": "string"}},
            "required": ["file"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "lookup_glossary",
        "description": "Look up an Oil & Gas term or abbreviation in the project glossary (Glossaries.docx). Accepts an abbreviation ('NPT', 'BHA') or words ('blowout').",
        "parameters": {"type": "object", "properties": {"term": {"type": "string"}},
                       "required": ["term"], "additionalProperties": False}}},
]

DISPATCH = {
    "list_reports": list_reports,
    "search_reports": search_reports,
    "get_report_fields": get_report_fields,
    "get_planned_operations": get_planned_operations,
    "read_report_section": read_report_section,
    "lookup_glossary": lookup_glossary,
}


def call_tool(conn: sqlite3.Connection, name: str, arguments: str | dict) -> str:
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        fn = DISPATCH[name]
        result = fn(conn, **args)
    except KeyError:
        result = {"error": f"unknown tool {name}"}
    except Exception as exc:  # error dari tool dikembalikan ke model, bukan ke pengguna
        result = {"error": f"{type(exc).__name__}: {exc}"}
    return _fit(result)


def _fit(result: dict) -> str:
    """Serialisasi hasil tool tanpa melewati MAX_RESULT_CHARS, dan tetap JSON yang valid.

    Item terakhir dari list terpanjang dibuang dulu, supaya struktur dan sitasi item
    yang tersisa tetap utuh. Bila tidak ada list yang bisa dipangkas (misalnya satu
    section yang sangat panjang), teksnya dipotong lalu dibungkus.
    """
    limit = _limit()
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= limit:
        return text
    result = {**result, "truncated": True, "note": "result too long; narrow the request for the rest"}
    while len(text) > limit:
        lists = [k for k, v in result.items() if isinstance(v, list) and len(v) > 1]
        if not lists:
            return json.dumps({"truncated": True, "note": result["note"], "partial": text[:limit]},
                              ensure_ascii=False)
        key = max(lists, key=lambda k: len(json.dumps(result[k], ensure_ascii=False)))
        result[key] = result[key][:-1]
        text = json.dumps(result, ensure_ascii=False)
    return text
