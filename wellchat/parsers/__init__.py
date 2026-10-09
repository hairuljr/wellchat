"""Ubah satu file sumber menjadi struktur JSON yang dijelaskan di README.md."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone

from ..pdf_text import detect_doc_type, extract_pages
from .common import flatten, sectionize
from .ddr import parse_ddr
from .dgos import parse_dgos
from .glossary import parse_glossary

SCHEMA_VERSION = "1.0"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _source(path: str, root: str) -> dict:
    return {
        "file_name": os.path.basename(path),
        "relative_path": os.path.relpath(path, root),
        "sha256": _sha256(path),
    }


def _generic(pages) -> dict:
    """Fallback untuk PDF yang bukan DDR maupun DGOS: teks per halaman tetap bisa dicari."""
    lines = flatten(pages)
    heading = re.compile(r"^[A-Z][A-Z0-9 /&()@.-]{3,60}$")
    return {
        "doc_type": "UNKNOWN",
        "well_name": None,
        "report_no": None,
        "report_date": None,
        "fields": [],
        "sections": sectionize(lines, [("SECTION", heading)]) if lines else [],
        "warnings": ["Unrecognised report layout; only raw text was extracted."],
    }


def parse_pdf(path: str, root: str) -> dict:
    pages = extract_pages(path)
    doc_type = detect_doc_type(pages[0].text if pages else "")
    if doc_type == "DDR":
        body = parse_ddr(pages)
    elif doc_type == "DGOS":
        body = parse_dgos(pages)
    else:
        body = _generic(pages)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {**_source(path, root), "page_count": len(pages)},
        "parsed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **body,
        "pages": [{"page": p.number, "text": p.text} for p in pages],
    }


def parse_docx_glossary(path: str, root: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": _source(path, root),
        "parsed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "doc_type": "GLOSSARY",
        "entries": parse_glossary(path),
    }
