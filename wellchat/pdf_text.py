"""Ekstraksi teks PDF tingkat rendah yang dipakai bersama oleh semua parser laporan.

PDF dari operator mengandung dua jenis noise yang merusak ekstraksi biasa:

* label tersembunyi berwarna putih yang ditumpuk di atas nilai asli (misalnya
  "Current Date" putih di atas "10-09-2026" -> "Cu1r0r-e0n9t- 2D0a2t6e"), dan
* teks "fake bold" yang digambar dua kali di posisi hampir sama
  (-> "DDAAIILLYY UUPPDDAATTEESS").

Keduanya dibuang di sini, sebelum teksnya dibaca parser mana pun.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pdfplumber


def _is_visible_char(obj: dict) -> bool:
    if obj.get("object_type") != "char":
        return True
    if obj.get("size", 10) < 2:  # artefak berukuran sangat kecil
        return False
    color = obj.get("non_stroking_color")
    if color is None:
        return True
    if isinstance(color, (int, float)):
        color = (color,)
    color = tuple(c for c in color if isinstance(c, (int, float)))
    if not color:
        return True
    if len(color) == 1:  # grayscale, 1.0 = putih
        return color[0] < 0.95
    if len(color) == 3:  # RGB
        return min(color) < 0.95
    if len(color) == 4:  # CMYK, semua nol = putih
        return max(color) > 0.05
    return True


@dataclass
class PageText:
    number: int  # dimulai dari 1
    text: str
    lines: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)


def _clean_cell(value) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _clean_table(raw: list[list]) -> list[list[str]]:
    rows = [[_clean_cell(c) for c in row] for row in raw]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    # buang kolom yang kosong di semua baris (pdfplumber menghasilkan banyak kolom ini untuk sel gabungan)
    keep = [i for i in range(max(len(r) for r in rows)) if any(i < len(r) and r[i] for r in rows)]
    return [[r[i] if i < len(r) else "" for i in keep] for r in rows]


def extract_pages(path: str, with_tables: bool = True) -> list[PageText]:
    pages: list[PageText] = []
    with pdfplumber.open(path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            clean = page.filter(_is_visible_char).dedupe_chars(tolerance=1)
            text = clean.extract_text() or ""
            lines = [ln.rstrip() for ln in text.splitlines()]
            tables: list[list[list[str]]] = []
            if with_tables:
                try:
                    for raw in clean.extract_tables():
                        t = _clean_table(raw)
                        if len(t) >= 2:
                            tables.append(t)
                except Exception:  # deteksi tabel bersifat best effort
                    pass
            pages.append(PageText(number=idx, text=text, lines=lines, tables=tables))
    return pages


def detect_doc_type(first_page_text: str) -> str:
    upper = first_page_text.upper()
    if "DAILY GEOLOGICAL OPERATIONS SUMMARY" in upper:
        return "DGOS"
    if "DAILY OPERATION REPORT" in upper or "DAILY DRILLING REPORT" in upper:
        return "DDR"
    return "UNKNOWN"


def split_labeled_line(line: str, labels: list[str]) -> dict[str, str]:
    """Pecah satu baris yang berisi beberapa pasangan `Label : value`.

    `labels` adalah daftar label yang mungkin muncul; nilai sebuah label adalah
    teks di antara titik duanya dan label berikutnya yang dikenal. Label dicocokkan
    dari yang terpanjang, sehingga "Cum Rot Hrs" menang atas "Rot Hrs".
    """
    ordered = sorted(labels, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![A-Za-z])(" + "|".join(re.escape(l) for l in ordered) + r")\s*:\s*",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(line))
    result: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
        canonical = next(l for l in labels if l.lower() == m.group(1).lower())
        value = line[m.end():end].strip()
        if canonical not in result or (value and not result[canonical]):
            result[canonical] = value
    return result


DATE_PATTERNS = [
    (re.compile(r"^(\d{2})/(\d{2})/(\d{4})$"), "dmy"),
    (re.compile(r"^(\d{2})-(\d{2})-(\d{4})$"), "dmy"),
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), "ymd"),
]


def to_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    for pattern, order in DATE_PATTERNS:
        m = pattern.match(value)
        if m:
            if order == "dmy":
                d, mth, y = m.groups()
            else:
                y, mth, d = m.groups()
            return f"{y}-{mth}-{d}"
    return None
