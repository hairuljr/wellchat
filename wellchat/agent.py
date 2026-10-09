"""Agen chat berbasis tool calling: model hanya boleh menjawab dari hasil tool.

Satu pertanyaan dijawab dalam dua fase:

1. Riset: model memanggil tool sebanyak yang dibutuhkan, tanpa `response_format`.
   Sebagian proxy OpenAI-compatible menerapkan JSON schema dengan memaksa model
   langsung menjawab, sehingga tool tidak pernah dipanggil bila keduanya dikirim bersamaan.
2. Jawaban: satu panggilan dengan `response_format` dan `tool_choice="none"`
   untuk menyusun jawaban JSON dari hasil riset.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from openai import BadRequestError, OpenAI

from . import config
from .prompts import ANSWER_SCHEMA, FINAL_INSTRUCTION, NOT_FOUND, REFUSAL, SYSTEM_PROMPT
from .tools import TOOL_SPECS, call_tool

MAX_RETRIES = 1
CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


@dataclass
class ChatResult:
    status: str
    answer: str
    sources: list[dict]
    language: str = "id"
    seconds: float = 0.0
    tool_calls: list[dict] = field(default_factory=list)


def _is_reasoning_model(model: str) -> bool:
    m = model.lower()
    return m.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


def _attempt_timeout(window: float) -> float:
    """SDK menerapkan timeout per percobaan, jadi jatah waktunya dibagi ke semua retry."""
    return min(config.REQUEST_TIMEOUT_S, window) / (MAX_RETRIES + 1)


class AnswerTimeout(TimeoutError):
    """Model tidak membalas dalam batas waktu dinding (wall-clock)."""


def _call_with_deadline(fn, seconds: float, **kwargs):
    """Jalankan `fn` di thread terpisah dan menyerah setelah `seconds` detik wall-clock.

    Timeout SDK (httpx) dihitung per jeda baca, sehingga provider yang terus mengirim
    keep-alive bisa menahan satu request jauh melewati batas. Thread yang ditinggalkan
    selesai sendiri di latar belakang; thread baru per panggilan dipakai supaya request
    yang macet tidak mengantre di depan request berikutnya.
    """
    box: dict = {}

    def run():
        try:
            box["value"] = fn(**kwargs)
        except BaseException as exc:  # diteruskan ke pemanggil di thread utama
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise AnswerTimeout(f"Model tidak membalas dalam {seconds:.0f} detik.")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _parse_answer(content: str) -> dict:
    """Jawaban akhir model sebagai dict, juga bila JSON-nya dibungkus ```json atau bukan JSON sama sekali."""
    try:
        # strict=False: sebagian model menulis baris baru apa adanya di dalam string JSON
        data = json.loads(CODE_FENCE.sub("", content), strict=False)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:  # JSONDecodeError turunan ValueError
        data = {"status": "answered", "answer": content, "sources": []}
    if data.get("status", "answered") == "answered" and str(data.get("answer") or "").strip().upper() in ("", "READY"):
        data["status"] = "not_found"  # jawaban kosong (atau sinyal fase riset) tidak boleh tampil sebagai jawaban
    return data


class WellChatAgent:
    def __init__(self, conn: sqlite3.Connection, client: OpenAI | None = None, model: str | None = None):
        self.conn = conn
        self.model = model or config.OPENAI_MODEL
        self.client = client or OpenAI(api_key=config.OPENAI_API_KEY or None, base_url=config.API_BASE_URL,
                                       timeout=config.REQUEST_TIMEOUT_S, max_retries=MAX_RETRIES)

    def _create(self, messages: list[dict], timeout: float, final: bool = False, tool_choice: str | None = None):
        kwargs = dict(model=self.model, messages=messages, tools=TOOL_SPECS, timeout=timeout)
        if final:
            kwargs.update(tool_choice="none", response_format=ANSWER_SCHEMA)
        elif tool_choice:
            kwargs["tool_choice"] = tool_choice
        if config.OPENAI_REASONING_EFFORT and _is_reasoning_model(self.model):
            kwargs["reasoning_effort"] = config.OPENAI_REASONING_EFFORT
        elif not _is_reasoning_model(self.model):
            kwargs["temperature"] = 0
        # batas wall-clock = jatah semua percobaan SDK (timeout per percobaan x jumlah percobaan)
        return _call_with_deadline(self.client.chat.completions.create, timeout * (MAX_RETRIES + 1), **kwargs)

    def _offset_well_only(self, question: str) -> bool:
        """True bila pertanyaan menyebut offset well (tanpa laporan) dan tidak menyebut sumur yang punya laporan."""
        q = question.upper()
        wells = {r[0].upper() for r in self.conn.execute(
            "SELECT DISTINCT well_name FROM documents WHERE doc_type != 'GLOSSARY' AND well_name IS NOT NULL")}
        offsets = set()
        for (value,) in self.conn.execute("SELECT value FROM fields WHERE label LIKE 'OFFSET WELL%'"):
            offsets |= {m.upper() for m in re.findall(r"([A-Z0-9]+(?:-[A-Z0-9]+)+)", value.upper())}
        named = lambda name: re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", q)
        return any(named(o) for o in offsets - wells) and not any(named(w) for w in wells)

    def ask(self, question: str, history: list[dict] | None = None) -> ChatResult:
        started = time.monotonic()
        deadline = started + config.ANSWER_DEADLINE_S
        if self._offset_well_only(question):
            lang = "en" if re.search(r"\b(what|which|how|where|who|when|is|are|the|of)\b", question, re.I) else "id"
            return ChatResult("not_found", NOT_FOUND[lang], [], lang, seconds=round(time.monotonic() - started, 1))
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in (history or [])[-6:]:  # memori pendek untuk pertanyaan lanjutan
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": question})

        trace: list[dict] = []
        consulted: dict[str, set] = {}
        self._research(messages, deadline, trace, consulted)
        data = self._answer(messages, deadline)
        if data["status"] == "not_found" and not trace:
            # model menyerah tanpa mencari: wajibkan satu ronde riset lagi sebelum menerima "tidak ditemukan"
            try:
                self._research(messages, deadline, trace, consulted, require_tool=True)
            except BadRequestError:  # endpoint tidak mendukung tool_choice="required"; terima "tidak ditemukan"
                pass
            if trace:
                data = self._answer(messages, deadline)

        result = self._finalize(data, trace, consulted)
        result.seconds = round(time.monotonic() - started, 1)
        return result

    def _research(self, messages: list[dict], deadline: float, trace: list[dict], consulted: dict[str, set],
                  require_tool: bool = False) -> None:
        """Ronde tool sampai model berhenti memanggil tool, jatah ronde habis, atau waktunya mepet."""
        for round_no in range(config.MAX_TOOL_ROUNDS):
            remaining = deadline - time.monotonic()
            if remaining <= 2 * config.FINAL_ROUND_RESERVE_S:
                return
            # ronde tool tidak boleh memakai waktu yang disisihkan untuk jawaban akhir
            try:
                response = self._create(messages, timeout=_attempt_timeout(remaining - config.FINAL_ROUND_RESERVE_S),
                                        tool_choice="required" if require_tool and round_no == 0 else None)
            except AnswerTimeout:
                return  # riset dihentikan; jawaban disusun dari data yang sudah didapat
            msg = response.choices[0].message
            if not msg.tool_calls:
                return
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                               for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                output = call_tool(self.conn, tc.function.name, tc.function.arguments)
                trace.append({"tool": tc.function.name, "arguments": tc.function.arguments})
                self._collect_sources(output, consulted)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})

    def _answer(self, messages: list[dict], deadline: float) -> dict:
        remaining = deadline - time.monotonic()
        final_messages = messages + [{"role": "user", "content": FINAL_INSTRUCTION}]
        response = self._create(final_messages, timeout=_attempt_timeout(max(remaining, config.FINAL_ROUND_RESERVE_S)),
                                final=True)
        return _parse_answer(response.choices[0].message.content or "")

    @staticmethod
    def _collect_sources(output: str, consulted: dict[str, set]) -> None:
        """Catat file/halaman yang benar-benar dikembalikan tool (cadangan sitasi)."""
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return

        def walk(node):
            if isinstance(node, dict):
                if "file" in node and isinstance(node["file"], str):
                    consulted.setdefault(node["file"], set())
                    if isinstance(node.get("page"), int):
                        consulted[node["file"]].add(node["page"])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)

    def _documents(self) -> dict[str, sqlite3.Row]:
        return {r["file_name"]: r for r in self.conn.execute("SELECT file_name, doc_type, report_no FROM documents")}

    @staticmethod
    def _mentioned(answer: str, doc: sqlite3.Row) -> bool:
        """True bila jawaban menyebut dokumen ini, lewat nama file atau pola seperti "DDR #61" / "DGOS 95"."""
        if doc["file_name"] in answer:
            return True
        if doc["doc_type"] == "GLOSSARY":
            return bool(re.search(r"glos", answer, re.I))
        if not doc["report_no"]:
            return False
        rx = rf"\b{re.escape(doc['doc_type'])}\s*(?:#|no\.?|nomor|report)?\s*{re.escape(doc['report_no'])}\b"
        return bool(re.search(rx, answer, re.I))

    def _finalize(self, data: dict, trace: list[dict], consulted: dict[str, set]) -> ChatResult:
        status = data.get("status", "answered")
        lang = data.get("language") if data.get("language") in ("id", "en") else "id"

        if status == "answered" and not trace:
            # guardrail: jawaban yang tidak pernah menyentuh data tidak mungkin berdasar dokumen
            status = "out_of_scope"
        if status == "out_of_scope":
            return ChatResult("out_of_scope", REFUSAL[lang], [], lang, tool_calls=trace)
        if status == "not_found":
            return ChatResult("not_found", NOT_FOUND[lang], [], lang, tool_calls=trace)

        answer = str(data.get("answer") or "").strip()
        docs = self._documents()
        sources, seen = [], set()
        for s in data.get("sources") or []:
            if isinstance(s, dict) and s.get("file") in docs and (s["file"], s.get("page")) not in seen:
                seen.add((s["file"], s.get("page")))
                sources.append(s)
        if not sources:  # model tidak mencantumkan sumber: pakai file hasil tool, utamakan yang disebut di jawaban
            retrieved = [f for f in consulted if f in docs]
            files = [f for f in retrieved if self._mentioned(answer, docs[f])] or retrieved
            sources = [{"file": f, "page": min(consulted[f]) if consulted[f] else None, "section": "retrieved"}
                       for f in files]
        if not sources:
            return ChatResult("not_found", NOT_FOUND[lang], [], lang, tool_calls=trace)
        return ChatResult("answered", answer, sources, lang, tool_calls=trace)
