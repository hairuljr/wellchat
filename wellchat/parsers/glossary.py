"""Glossary (.docx) -> list of term entries.

Any 2-column table in the document is read as `term | meaning`. Header rows
("Abbreviation | Meaning") and alphabet divider rows ("A | A") are skipped.
"""

from __future__ import annotations

import re

import docx

TBC = re.compile(r"\(to be confirmed\)", re.I)


def parse_glossary(path: str) -> list[dict]:
    document = docx.Document(path)
    entries: list[dict] = []
    for t_index, table in enumerate(document.tables):
        rows = [[c.text.strip() for c in r.cells] for r in table.rows]
        if not rows or len(rows[0]) < 2:
            continue
        header = rows[0][0].lower()
        category = "well_name_part" if header == "part" else "abbreviation"
        for row in rows[1:]:
            term, meaning = row[0], row[1]
            if not term or not meaning:
                continue
            if term == meaning and len(term) == 1:  # alphabet divider
                continue
            full_form, _, description = meaning.partition(" – ")
            if not description:
                full_form, description = meaning, ""
            entries.append({
                "term": term,
                "meaning": meaning,
                "full_form": full_form.strip(),
                "description": description.strip(),
                "category": category,
                "to_be_confirmed": bool(TBC.search(meaning)) or meaning.lower().startswith("unknown"),
                "table": t_index + 1,
            })
    return entries
