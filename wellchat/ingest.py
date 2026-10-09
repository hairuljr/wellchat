"""Parsing semua PDF / DOCX di folder data mentah menjadi JSON, lalu bangun ulang SQLite.

    python -m wellchat.ingest            # hanya file baru atau yang berubah
    python -m wellchat.ingest --force    # parsing ulang semuanya
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from . import config
from .parsers import parse_docx_glossary, parse_pdf
from .parsers import _sha256 as sha256
from .store import rebuild_database


def _json_name(rel_path: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", rel_path) + ".json"


def ingest(raw_dir: Path, parsed_dir: Path, db_path: Path, force: bool = False, log=print) -> dict:
    raw_dir, parsed_dir = Path(raw_dir), Path(parsed_dir)
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"Raw data folder not found: {raw_dir}")
    parsed_dir.mkdir(parents=True, exist_ok=True)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    sources = sorted(p for p in raw_dir.rglob("*") if p.suffix.lower() in (".pdf", ".docx") and not p.name.startswith("~$"))
    expected = set()
    stats = {"parsed": 0, "skipped": 0, "failed": 0, "removed": 0}
    for src in sources:
        rel = str(src.relative_to(raw_dir))
        out = parsed_dir / _json_name(rel)
        expected.add(out.name)
        if out.exists() and not force:
            try:
                old = json.loads(out.read_text(encoding="utf-8"))
                if old["source"]["sha256"] == sha256(str(src)):
                    stats["skipped"] += 1
                    continue
            except Exception:
                pass
        t0 = time.time()
        try:
            if src.suffix.lower() == ".pdf":
                doc = parse_pdf(str(src), str(raw_dir))
            else:
                doc = parse_docx_glossary(str(src), str(raw_dir))
        except Exception as exc:  # satu file bermasalah tidak boleh menghentikan semuanya
            stats["failed"] += 1
            log(f"  FAILED  {rel}: {exc}")
            continue
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        stats["parsed"] += 1
        what = doc["doc_type"]
        if what == "GLOSSARY":
            what += f", {len(doc['entries'])} terms"
        else:
            what += f" #{doc.get('report_no')} {doc.get('report_date')}"
        log(f"  parsed  {rel} -> {out.name} ({what}, {time.time() - t0:.1f}s)")
        for w in doc.get("warnings", []):
            log(f"          warning: {w}")

    for stale in parsed_dir.glob("*.json"):
        if stale.name not in expected:
            stale.unlink()
            stats["removed"] += 1
            log(f"  removed {stale.name} (source file no longer present)")

    stats["documents"] = rebuild_database(Path(db_path), parsed_dir)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", default=str(config.RAW_DIR))
    ap.add_argument("--parsed-dir", default=str(config.PARSED_DIR))
    ap.add_argument("--db", default=str(config.DB_PATH))
    ap.add_argument("--force", action="store_true", help="re-parse files even if unchanged")
    args = ap.parse_args(argv)
    print(f"Raw data : {args.raw_dir}\nJSON out : {args.parsed_dir}\nSQLite   : {args.db}")
    try:
        stats = ingest(Path(args.raw_dir), Path(args.parsed_dir), Path(args.db), args.force)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Done: {stats}")
    return 0 if stats["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
