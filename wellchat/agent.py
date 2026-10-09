"""Tool-calling chat agent: the model may only answer from what the tools return."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field

from openai import OpenAI

from . import config
from .tools import TOOL_SPECS, call_tool

REFUSAL = {
    "id": ("Maaf, saya hanya dapat menjawab pertanyaan seputar laporan sumur yang tersedia "
           "(Daily Operation Report / DDR dan Daily Geological Operations Summary / DGOS) "
           "serta istilah Oil & Gas di glosarium. Silakan ajukan pertanyaan tentang data sumur, "
           "misalnya lokasi sumur, NPT, operasi wireline, kedalaman, casing, atau arti sebuah singkatan."),
    "en": ("Sorry, I can only answer questions about the available well reports "
           "(Daily Operation Report / DDR and Daily Geological Operations Summary / DGOS) "
           "and Oil & Gas terms in the glossary. Please ask about the well data, for example "
           "the well location, NPT, wireline operations, depths, casing, or what an abbreviation means."),
}
NOT_FOUND = {
    "id": ("Informasi tersebut tidak ditemukan di laporan sumur maupun glosarium yang tersedia. "
           "Coba tanyakan hal lain tentang data sumur atau istilah di glosarium."),
    "en": ("That information is not in the available well reports or glossary. "
           "Try asking about another aspect of the well data or a glossary term."),
}

SYSTEM_PROMPT = """You are a question-answering assistant for an oil & gas well-data repository.
Your ONLY knowledge source is what your tools return: parsed daily well reports
(DDR = Daily Drilling / Daily Operation Report, DGOS = Daily Geological Operations Summary)
and the project glossary. Never use outside knowledge to state facts about the well.

Scope
- In scope: anything about the wells/reports in the repository (location, dates, depths, NPT,
  costs, operations, wireline/logging, casing, mud, BHA, formation tops, personnel, safety...)
  and meanings of oil & gas terms/abbreviations that are in the glossary.
- Out of scope: everything else (general knowledge, other companies/wells not in the data,
  coding, chit-chat, opinions, predictions). Return status "out_of_scope". Do not answer it.
- In scope but the tools return nothing relevant after a reasonable search: status "not_found".
  Never guess.
- A question about a well that is not in list_reports `wells` (for example an offset well or
  platform that is only mentioned by name in a report) has no data: status "not_found".
  Do not answer it with data from another well. Use "not_found" even when you could explain why
  the data is missing; the application shows a standard message.

How to work
1. Always call tools before answering an in-scope question. Start with list_reports when you
   need to know which reports exist. Reports are written in English; search with English terms
   and abbreviations even when the user writes Indonesian.
2. Questions about "the well" refer to the well(s) in the reports (currently one well; check list_reports).
3. Values differ between daily reports (they are snapshots on different dates). When a question
   does not name a report or date and the reports give different values, the user may mean any
   of them, so do not pick one or call one of them "the total". Open the answer with one short
   line per report ("<type> #<no> (<date>): <value as written>"), oldest first, then note which
   report is the most recent. Do not add values together.
   - NPT: DDR header has "Daily NPT" and "Cumm NPT"; the DDR OPERATION SUMMARY flags NPT rows;
     DGOS has an "NPT:" line in the last-24-hours block. Use get_report_fields(field="NPT").
   - "Planned"/"next"/"forecast"/"rencana" questions: call get_planned_operations and report the
     plan from every report, copying run numbers and tool names exactly (e.g. "WL Run #1: PEX-QAIT").
4. Report data-quality warnings from list_reports when they affect the answer (e.g. a spud date
   later than the report date). Present the value as written in the source and flag it.
5. Glossary entries marked to_be_confirmed or "Unknown" must be presented as uncertain.
6. Answer in the user's language (Indonesian or English). When there is one value, lead with it in
   one line, then short supporting detail. When the value differs between reports, follow rule 3
   instead: never open with a single number and never label one report's value as "total",
   "resmi" or "official". Keep technical terms, numbers and units exactly as in the source.
   Example for "Berapa NPT sumur?" (dummy values):
     NPT per laporan:
     - DDR #10 (2030-01-01): Daily NPT 2.00 hr, Cumm NPT 2.00 hr
     - DDR #15 (2030-01-06): Daily NPT 0.00 hr, Cumm NPT 9.50 hr
     - DGOS #20 (2030-01-11): 1.00 hrs due to pump repair
     Laporan terbaru: DGOS #20 (2030-01-11).
7. Cite every report/glossary file you used in `sources`, with page numbers from tool results.

Final output: JSON matching the provided schema. For out_of_scope / not_found, `answer` may be
empty; the application shows a standard message."""

ANSWER_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "well_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["answered", "out_of_scope", "not_found"]},
                "language": {"type": "string", "enum": ["id", "en"]},
                "answer": {"type": "string"},
                "sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file": {"type": "string"},
                            "page": {"type": ["integer", "null"]},
                            "section": {"type": "string"},
                        },
                        "required": ["file", "page", "section"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["status", "language", "answer", "sources"],
            "additionalProperties": False,
        },
    },
}


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


class WellChatAgent:
    def __init__(self, conn: sqlite3.Connection, client: OpenAI | None = None, model: str | None = None):
        self.conn = conn
        self.model = model or config.OPENAI_MODEL
        self.client = client or OpenAI(api_key=config.OPENAI_API_KEY or None, base_url=config.OPENAI_BASE_URL,
                                       timeout=config.REQUEST_TIMEOUT_S)

    def _create(self, messages: list[dict], final: bool = False):
        kwargs = dict(model=self.model, messages=messages, tools=TOOL_SPECS, response_format=ANSWER_SCHEMA)
        if final:
            kwargs["tool_choice"] = "none"
        if config.OPENAI_REASONING_EFFORT and _is_reasoning_model(self.model):
            kwargs["reasoning_effort"] = config.OPENAI_REASONING_EFFORT
        elif not _is_reasoning_model(self.model):
            kwargs["temperature"] = 0
        return self.client.chat.completions.create(**kwargs)

    def _offset_well_only(self, question: str) -> bool:
        """True when the question names an offset well (no reports) and none of the reported wells."""
        q = question.upper()
        wells = {r[0].upper() for r in self.conn.execute(
            "SELECT DISTINCT well_name FROM documents WHERE doc_type != 'GLOSSARY' AND well_name IS NOT NULL")}
        offsets = set()
        for (value,) in self.conn.execute("SELECT value FROM fields WHERE label LIKE 'OFFSET WELL%'"):
            offsets |= {m.upper() for m in re.findall(r"([A-Z0-9]+(?:-[A-Z0-9]+)+)", value.upper())}
        named = lambda name: re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", q)
        return any(named(o) for o in offsets - wells) and not any(named(w) for w in wells)

    def ask(self, question: str, history: list[dict] | None = None) -> ChatResult:
        started = time.time()
        if self._offset_well_only(question):
            lang = "en" if re.search(r"\b(what|which|how|where|who|when|is|are|the|of)\b", question, re.I) else "id"
            return ChatResult("not_found", NOT_FOUND[lang], [], lang, seconds=round(time.time() - started, 1))
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in (history or [])[-6:]:  # short memory for follow-up questions
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": question})

        trace: list[dict] = []
        consulted: dict[str, set] = {}
        response = None
        for round_no in range(config.MAX_TOOL_ROUNDS + 1):
            response = self._create(messages, final=round_no == config.MAX_TOOL_ROUNDS)
            msg = response.choices[0].message
            if not msg.tool_calls:
                break
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

        result = self._finalize(response.choices[0].message.content or "", trace, consulted)
        result.seconds = round(time.time() - started, 1)
        return result

    @staticmethod
    def _collect_sources(output: str, consulted: dict[str, set]) -> None:
        """Remember which files/pages tools actually returned (fallback citations)."""
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

    def _valid_files(self) -> set[str]:
        return {r["file_name"] for r in self.conn.execute("SELECT file_name FROM documents")}

    def _finalize(self, content: str, trace: list[dict], consulted: dict[str, set]) -> ChatResult:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            data = {"status": "answered", "language": "id", "answer": content, "sources": []}
        status = data.get("status", "answered")
        lang = data.get("language") if data.get("language") in ("id", "en") else "id"

        if status == "answered" and not trace:
            # guardrail: an answer that never touched the data cannot be grounded
            status = "out_of_scope"
        if status == "out_of_scope":
            return ChatResult("out_of_scope", REFUSAL[lang], [], lang, tool_calls=trace)
        if status == "not_found":
            return ChatResult("not_found", NOT_FOUND[lang], [], lang, tool_calls=trace)

        valid = self._valid_files()
        sources, seen = [], set()
        for s in data.get("sources", []):
            if s.get("file") in valid and (s["file"], s.get("page")) not in seen:
                seen.add((s["file"], s.get("page")))
                sources.append(s)
        if not sources:  # model forgot to cite: fall back to what the tools returned
            sources = [{"file": f, "page": min(p) if p else None, "section": "retrieved"} for f, p in consulted.items() if f in valid]
        if not sources:
            return ChatResult("not_found", NOT_FOUND[lang], [], lang, tool_calls=trace)
        return ChatResult("answered", data.get("answer", "").strip(), sources, lang, tool_calls=trace)
