"""Agent loop and guardrails, with a scripted fake LLM (no API key needed)."""

import json
from types import SimpleNamespace as NS

import pytest

from wellchat.agent import NOT_FOUND, REFUSAL, WellChatAgent


def _tool_call(name, args, id_="call_1"):
    return NS(id=id_, function=NS(name=name, arguments=json.dumps(args)))


def _reply(content=None, tool_calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))])


class FakeClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0)


def _final(status, answer="", sources=(), language="id"):
    return _reply(json.dumps({"status": status, "language": language, "answer": answer, "sources": list(sources)}))


def test_answer_with_tool_and_citation(db_conn):
    client = FakeClient([
        _reply(tool_calls=[_tool_call("get_report_fields", {"field": "country"})]),
        _final("answered", "Malaysia", [{"file": "BARAKUDA-1_DGOS_72_20260829.pdf", "page": 1, "section": "WELL DATA"}]),
    ])
    r = WellChatAgent(db_conn, client=client, model="gpt-4.1-mini").ask("Dimana letak lokasi sumur?")
    assert r.status == "answered" and r.answer == "Malaysia"
    assert r.sources[0]["file"] == "BARAKUDA-1_DGOS_72_20260829.pdf"
    tool_msg = client.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "MALAYSIA" in tool_msg["content"]


def test_out_of_scope_uses_fixed_message(db_conn):
    client = FakeClient([_final("out_of_scope", "whatever the model says", language="en")])
    r = WellChatAgent(db_conn, client=client, model="gpt-4.1-mini").ask("Who won the 2022 world cup?")
    assert r.status == "out_of_scope" and r.answer == REFUSAL["en"] and r.sources == []


def test_answer_without_any_tool_call_is_refused(db_conn):
    client = FakeClient([_final("answered", "Paris is the capital of France", [{"file": "x.pdf", "page": 1, "section": ""}])])
    r = WellChatAgent(db_conn, client=client, model="gpt-4.1-mini").ask("Ibu kota Prancis?")
    assert r.status == "out_of_scope" and r.answer == REFUSAL["id"]


def test_hallucinated_source_replaced_by_consulted_file(db_conn):
    client = FakeClient([
        _reply(tool_calls=[_tool_call("lookup_glossary", {"term": "BHA"})]),
        _final("answered", "Bottom Hole Assembly", [{"file": "made_up.pdf", "page": 3, "section": ""}]),
    ])
    r = WellChatAgent(db_conn, client=client, model="gpt-4.1-mini").ask("Apa itu BHA?")
    assert [s["file"] for s in r.sources] == ["Glossaries.docx"]


def test_not_found_message(db_conn):
    client = FakeClient([
        _reply(tool_calls=[_tool_call("search_reports", {"query": "helicopter crash"})]),
        _final("not_found"),
    ])
    r = WellChatAgent(db_conn, client=client, model="gpt-4.1-mini").ask("Ada kecelakaan helikopter?")
    assert r.status == "not_found" and r.answer == NOT_FOUND["id"]


@pytest.mark.parametrize("model,has_effort", [("gpt-5.4-mini", True), ("gpt-4.1-mini", False)])
def test_reasoning_effort_only_for_reasoning_models(db_conn, model, has_effort):
    client = FakeClient([_final("out_of_scope")])
    WellChatAgent(db_conn, client=client, model=model).ask("hi")
    assert ("reasoning_effort" in client.calls[0]) == has_effort


@pytest.mark.parametrize("question,lang", [("Berapa NPT sumur TAPIS-F?", "id"), ("What is the NPT of tapis-c?", "en")])
def test_offset_well_question_is_not_found_without_llm(db_conn, question, lang):
    client = FakeClient([])
    r = WellChatAgent(db_conn, client=client, model="gpt-4.1-mini").ask(question)
    assert r.status == "not_found" and r.answer == NOT_FOUND[lang] and client.calls == []


def test_question_naming_the_reported_well_still_reaches_llm(db_conn):
    client = FakeClient([_final("out_of_scope")])
    WellChatAgent(db_conn, client=client, model="gpt-4.1-mini").ask("Seberapa jauh BARAKUDA-1 dari TAPIS-F?")
    assert len(client.calls) == 1
