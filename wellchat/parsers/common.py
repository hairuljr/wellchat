from __future__ import annotations

import re
from dataclasses import dataclass

from ..pdf_text import PageText


@dataclass
class Line:
    page: int
    text: str


def flatten(pages: list[PageText], drop: list[re.Pattern] | None = None) -> list[Line]:
    """All non-empty lines of the document, minus repeated headers/footers."""
    drop = drop or []
    out: list[Line] = []
    for p in pages:
        for raw in p.lines:
            t = raw.strip()
            if not t or any(rx.search(t) for rx in drop):
                continue
            out.append(Line(p.number, t))
    return out


def sectionize(lines: list[Line], headings: list[tuple[str, re.Pattern]]) -> list[dict]:
    """Cut the line stream into sections at lines matching a heading pattern.

    Text before the first heading goes to a "HEADER" section. A heading that
    re-appears (e.g. table header repeated on every page) continues the open
    section instead of starting a duplicate.
    """
    sections: list[dict] = []
    current = {"name": "HEADER", "page_start": lines[0].page if lines else 1, "lines": []}
    for ln in lines:
        name = next((n for n, rx in headings if rx.search(ln.text)), None)
        if name and name != current["name"]:
            if current["lines"]:
                sections.append(current)
            current = {"name": name, "page_start": ln.page, "lines": []}
        current["lines"].append(ln)
    if current["lines"]:
        sections.append(current)

    result = []
    for s in sections:
        pages = sorted({l.page for l in s["lines"]})
        result.append(
            {
                "name": s["name"],
                "pages": pages,
                "text": "\n".join(l.text for l in s["lines"]),
            }
        )
    return result


def collect_labeled_block(lines: list[Line], labels: list[str], stop: re.Pattern) -> dict[str, str]:
    """Multi-line `Label : value` blocks where values wrap onto following lines.

    Used for the DDR STATUS block (Current status / 24 hr summary / ...).
    """
    label_rx = re.compile(r"^(" + "|".join(re.escape(l) for l in labels) + r")\s*:\s*(.*)$", re.IGNORECASE)
    out: dict[str, list[str]] = {}
    current: str | None = None
    for ln in lines:
        if stop.search(ln.text):
            break
        m = label_rx.match(ln.text)
        if m:
            current = next(l for l in labels if l.lower() == m.group(1).lower())
            out[current] = [m.group(2).strip()] if m.group(2).strip() else []
        elif current:
            out[current].append(ln.text)
    return {k: " ".join(v).strip() for k, v in out.items()}


def snake(label: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", label).strip("_").lower()
    return s or "field"
