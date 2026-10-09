"""Penyimpanan SQLite yang dibangun dari file JSON hasil parsing.

File JSON adalah sumber kebenaran; database hanyalah indeks turunan yang dibangun
ulang oleh `ingest` setiap kali dijalankan, jadi selalu aman untuk dihapus.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE documents (
    doc_id      TEXT PRIMARY KEY,   -- path relative to the raw data folder
    file_name   TEXT NOT NULL,
    doc_type    TEXT NOT NULL,      -- DDR | DGOS | UNKNOWN | GLOSSARY
    well_name   TEXT,
    report_no   TEXT,
    report_date TEXT,               -- ISO yyyy-mm-dd
    page_count  INTEGER,
    json_path   TEXT NOT NULL,
    warnings    TEXT                -- JSON array
);
CREATE TABLE fields (
    doc_id TEXT, key TEXT, label TEXT, value TEXT, page INTEGER
);
CREATE TABLE sections (
    doc_id TEXT, name TEXT, pages TEXT, text TEXT
);
CREATE TABLE operations (
    doc_id TEXT, seq INTEGER, day TEXT, time_from TEXT, time_to TEXT, hours REAL,
    phase TEXT, activity TEXT, productive_code TEXT, npt INTEGER, rig_status TEXT,
    md_from_m REAL, operation TEXT, page INTEGER
);
CREATE TABLE report_tables (
    doc_id TEXT, name TEXT, page INTEGER, columns TEXT, rows TEXT
);
CREATE TABLE glossary (
    term TEXT, meaning TEXT, full_form TEXT, description TEXT, category TEXT,
    to_be_confirmed INTEGER, doc_id TEXT
);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY, doc_id TEXT, kind TEXT, ref TEXT, page INTEGER, text TEXT
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, content='chunks', content_rowid='id', tokenize='porter unicode61'
);
CREATE INDEX idx_fields_doc ON fields(doc_id);
CREATE INDEX idx_ops_doc ON operations(doc_id);
CREATE INDEX idx_gloss_term ON glossary(term COLLATE NOCASE);
"""

CHUNK_CHARS = 1500


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Buka koneksi dan pastikan selalu ditutup, termasuk saat terjadi error.

    `with connect(...)` hanya melakukan commit/rollback dan koneksinya tetap terbuka,
    sehingga pemanggil yang jalan per pertanyaan (atau per baris yang dirender)
    membocorkan file handle.
    """
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _split(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Potong per baris menjadi potongan berukuran paling banyak ~limit karakter.

    Dua baris terakhir dibawa ke potongan berikutnya (overlap) supaya konteks tidak
    terputus di tengah kalimat. Overlap diukur dengan aturan yang sama seperti
    akumulasi normal (panjang baris + newline), sehingga `size` selalu mencerminkan
    panjang potongan yang sebenarnya.
    """
    pieces, buf = [], []
    size = 0
    for line in text.splitlines():
        if size + len(line) > limit and buf:
            pieces.append("\n".join(buf))
            keep = buf[-2:]  # sedikit overlap
            buf, size = keep, sum(len(l) + 1 for l in keep)
        buf.append(line)
        size += len(line) + 1
    if buf:
        pieces.append("\n".join(buf))
    return pieces


def _doc_label(doc: dict) -> str:
    parts = [doc.get("doc_type", ""), f"report #{doc['report_no']}" if doc.get("report_no") else "",
             doc.get("report_date") or "", doc.get("well_name") or ""]
    return " ".join(p for p in parts if p)


def _rebuild(conn: sqlite3.Connection, docs: list[tuple[Path, dict]]) -> None:
    cur = conn.cursor()
    chunks: list[tuple] = []
    for json_path, doc in docs:
        src = doc["source"]
        doc_id = src["relative_path"]
        cur.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)",
            (doc_id, src["file_name"], doc["doc_type"], doc.get("well_name"), doc.get("report_no"),
             doc.get("report_date"), src.get("page_count"), str(json_path), json.dumps(doc.get("warnings", []))),
        )
        if doc["doc_type"] == "GLOSSARY":
            for e in doc["entries"]:
                cur.execute(
                    "INSERT INTO glossary VALUES (?,?,?,?,?,?,?)",
                    (e["term"], e["meaning"], e["full_form"], e["description"], e["category"],
                     int(e["to_be_confirmed"]), doc_id),
                )
                chunks.append((doc_id, "glossary", e["term"], None, f"Glossary: {e['term']} = {e['meaning']}"))
            continue

        label = _doc_label(doc)
        field_lines = []
        for f in doc.get("fields", []):
            cur.execute("INSERT INTO fields VALUES (?,?,?,?,?)", (doc_id, f["key"], f["label"], f["value"], f["page"]))
            if f["value"]:
                field_lines.append(f"{f['label']}: {f['value']}")
        if field_lines:
            chunks.append((doc_id, "fields", "header fields", 1, f"[{label}] header fields\n" + "\n".join(field_lines)))
        extra = []
        if doc.get("npt"):
            extra.append(f"NPT: {doc['npt']}")
        for r in doc.get("daily_remarks", []):
            extra.append(f"Remark {r['no']}: {r['text']}")
        for k, v in (doc.get("progress") or {}).items():
            extra.append(f"{k}: " + ", ".join(f"{a}={b}" for a, b in v.items() if a != "page"))
        if doc.get("derived"):
            extra += [f"{k}: {v}" for k, v in doc["derived"].items()]
        if extra:
            chunks.append((doc_id, "summary", "key values", 1, f"[{label}] key values\n" + "\n".join(extra)))

        for s in doc.get("sections", []):
            cur.execute("INSERT INTO sections VALUES (?,?,?,?)", (doc_id, s["name"], json.dumps(s["pages"]), s["text"]))
            if s["name"] == "OPERATION SUMMARY" or doc["doc_type"] == "UNKNOWN":
                continue  # diindeks per baris / per halaman di bawah
            for piece in _split(s["text"]):
                chunks.append((doc_id, "section", s["name"], s["pages"][0], f"[{label}] {s['name']}\n{piece}"))

        seq = 0
        for o in doc.get("operations", []):
            seq += 1
            cur.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, seq, "report day", o["from"], o["to"], o["hours"], o["phase"], o["activity"],
                 o["productive_code"], int(o["npt"]), o["rig_status"], o["md_from_m"], o["operation"], o["page"]),
            )
            npt = " NPT" if o["npt"] else ""
            md = "-" if o["md_from_m"] is None else f"{o['md_from_m']} m"
            chunks.append((doc_id, "operation", f"{o['from']}-{o['to']}", o["page"],
                           f"[{label}] operation {o['from']}-{o['to']} ({o['hours']} hr, {o['phase']}/{o['activity']}"
                           f"/{o['productive_code']}{npt}, MD {md})\n{o['operation']}"))
        for o in doc.get("next_day_operations", []):
            seq += 1
            cur.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, seq, o.get("date") or "next day", o["from"], o["to"], None, None, None, None, 0, None, None,
                 o["operation"], o["page"]),
            )
            chunks.append((doc_id, "operation", f"{o.get('date')} {o['from']}-{o['to']}", o["page"],
                           f"[{label}] next-day update {o.get('date')} {o['from']}-{o['to']}\n{o['operation']}"))

        for t in doc.get("tables", []):
            cur.execute("INSERT INTO report_tables VALUES (?,?,?,?,?)",
                        (doc_id, t["name"], t["page"], json.dumps(t["columns"]), json.dumps(t["rows"])))
            body = "\n".join("; ".join(f"{k}={v}" for k, v in r.items() if v) for r in t["rows"])
            for piece in _split(body):
                chunks.append((doc_id, "table", t["name"], t["page"], f"[{label}] table {t['name']}\n{piece}"))

        if doc["doc_type"] == "UNKNOWN":
            for p in doc.get("pages", []):
                for piece in _split(p["text"]):
                    chunks.append((doc_id, "page", f"page {p['page']}", p["page"], f"[{label or src['file_name']}] page {p['page']}\n{piece}"))

    cur.executemany("INSERT INTO chunks (doc_id, kind, ref, page, text) VALUES (?,?,?,?,?)", chunks)
    cur.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    conn.commit()


def rebuild_database(db_path: Path, parsed_dir: Path) -> int:
    """Bangun (ulang) file SQLite dari semua JSON di parsed_dir. Mengembalikan jumlah dokumen."""
    docs = []
    for p in sorted(parsed_dir.glob("*.json")):
        with open(p, encoding="utf-8") as f:
            docs.append((p, json.load(f)))
    tmp = db_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = connect(tmp)
    conn.executescript(SCHEMA)
    _rebuild(conn, docs)
    conn.close()
    tmp.replace(db_path)  # tukar atomik: aplikasi yang sedang jalan tidak pernah membaca DB setengah jadi
    return len(docs)


def fts_query(text: str) -> str:
    """Ubah teks bebas menjadi query FTS5 berbentuk OR dari istilah yang dikutip, supaya aman."""
    terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9.#/-]*", text)
    terms = [t.strip(".-/") for t in terms if len(t.strip(".-/")) > 1 or t.isdigit()]
    seen, out = set(), []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append('"' + t.replace('"', "") + '"')
    return " OR ".join(out)
