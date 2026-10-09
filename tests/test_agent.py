"""Loop agen dan guardrail, diuji dengan LLM palsu yang jawabannya sudah diskenariokan (tanpa API key)."""

import json
from types import SimpleNamespace as NS

import pytest

from wellchat import config
from wellchat.agent import WellChatAgent
from wellchat.prompts import NOT_FOUND, REFUSAL

DDR_32 = "NAGA-2_BARAKUDA-1_DDR_32_19_07_2026_Drill_17_5in_x_20in_Hole.pdf"


def _tool_call(name, args, id_="call_1"):
    return NS(id=id_, function=NS(name=name, arguments=json.dumps(args)))


def _reply(content=None, tool_calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=tool_calls))])


class FakeClient:
    """`research` dipakai untuk ronde tool, `answers` untuk panggilan akhir yang membawa response_format."""

    def __init__(self, research=(), answers=()):
        self.research, self.answers = list(research), list(answers)
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if "response_format" in kwargs:
            return self.answers.pop(0)
        return self.research.pop(0) if self.research else _reply("selesai")


def _final(status, answer="", sources=(), language="id"):
    return _reply(json.dumps({"status": status, "language": language, "answer": answer, "sources": list(sources)}))


def _agent(db_conn, client, model="gpt-4.1-mini"):
    return WellChatAgent(db_conn, client=client, model=model)


def test_answer_with_tool_and_citation(db_conn):
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("get_report_fields", {"field": "country"})])],
        answers=[_final("answered", "Malaysia", [{"file": "BARAKUDA-1_DGOS_72_20260829.pdf", "page": 1, "section": "WELL DATA"}])],
    )
    r = _agent(db_conn, client).ask("Dimana letak lokasi sumur?")
    assert r.status == "answered" and r.answer == "Malaysia"
    assert r.sources[0]["file"] == "BARAKUDA-1_DGOS_72_20260829.pdf"
    tool_msg = client.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "MALAYSIA" in tool_msg["content"]


def test_schema_is_sent_only_with_the_final_answer(db_conn):
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("lookup_glossary", {"term": "BHA"})])],
        answers=[_final("answered", "Bottom Hole Assembly")],
    )
    _agent(db_conn, client).ask("Apa itu BHA?")
    *research, final = client.calls
    assert all("response_format" not in c and "tool_choice" not in c for c in research)
    assert final["response_format"]["type"] == "json_schema" and final["tool_choice"] == "none"


def test_out_of_scope_uses_fixed_message(db_conn):
    client = FakeClient(answers=[_final("out_of_scope", "whatever the model says", language="en")])
    r = _agent(db_conn, client).ask("Who won the 2022 world cup?")
    assert r.status == "out_of_scope" and r.answer == REFUSAL["en"] and r.sources == []


def test_answer_without_any_tool_call_is_refused(db_conn):
    client = FakeClient(answers=[_final("answered", "Paris is the capital of France", [{"file": "x.pdf", "page": 1, "section": ""}])])
    r = _agent(db_conn, client).ask("Ibu kota Prancis?")
    assert r.status == "out_of_scope" and r.answer == REFUSAL["id"]


def test_hallucinated_source_replaced_by_consulted_file(db_conn):
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("lookup_glossary", {"term": "BHA"})])],
        answers=[_final("answered", "Bottom Hole Assembly", [{"file": "made_up.pdf", "page": 3, "section": ""}])],
    )
    r = _agent(db_conn, client).ask("Apa itu BHA?")
    assert [s["file"] for s in r.sources] == ["Glossaries.docx"]


def test_not_found_message(db_conn):
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("search_reports", {"query": "helicopter crash"})])],
        answers=[_final("not_found")],
    )
    r = _agent(db_conn, client).ask("Ada kecelakaan helikopter?")
    assert r.status == "not_found" and r.answer == NOT_FOUND["id"]


def test_not_found_without_searching_forces_a_tool_round(db_conn):
    client = FakeClient(
        research=[_reply("tidak ada"), _reply(tool_calls=[_tool_call("lookup_glossary", {"term": "BHA"})])],
        answers=[_final("not_found"), _final("answered", "Bottom Hole Assembly")],
    )
    r = _agent(db_conn, client).ask("Apa itu BHA?")
    assert r.status == "answered" and r.answer == "Bottom Hole Assembly"
    assert any(c.get("tool_choice") == "required" for c in client.calls)


def test_fenced_json_answer_is_parsed(db_conn):
    fenced = "```json\n" + json.dumps({"status": "not_found", "language": "en", "answer": "", "sources": []}) + "\n```"
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("search_reports", {"query": "helicopter"})])],
        answers=[_reply(fenced)],
    )
    r = _agent(db_conn, client).ask("Any helicopter incident?")
    assert r.status == "not_found" and r.answer == NOT_FOUND["en"]


def test_empty_answer_is_not_found(db_conn):
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("search_reports", {"query": "helicopter"})])],
        answers=[_reply("")],
    )
    r = _agent(db_conn, client).ask("Ada kecelakaan helikopter?")
    assert r.status == "not_found" and r.answer == NOT_FOUND["id"]


def test_plain_text_answer_cites_only_the_reports_it_names(db_conn):
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("get_report_fields", {"field": "Daily Cost"})])],
        answers=[_reply("Daily cost pada DDR #32 adalah 348,640.02.")],
    )
    r = _agent(db_conn, client).ask("Berapa daily cost tanggal 19 Juli 2026?")
    assert r.status == "answered" and [s["file"] for s in r.sources] == [DDR_32]


@pytest.mark.parametrize("model,has_effort", [("gpt-5.4-mini", True), ("gpt-4.1-mini", False)])
def test_reasoning_effort_only_for_reasoning_models(db_conn, model, has_effort):
    client = FakeClient(answers=[_final("out_of_scope")])
    _agent(db_conn, client, model=model).ask("hi")
    assert ("reasoning_effort" in client.calls[0]) == has_effort


@pytest.mark.parametrize("question,lang", [("Berapa NPT sumur TAPIS-F?", "id"), ("What is the NPT of tapis-c?", "en")])
def test_offset_well_question_is_not_found_without_llm(db_conn, question, lang):
    client = FakeClient()
    r = _agent(db_conn, client).ask(question)
    assert r.status == "not_found" and r.answer == NOT_FOUND[lang] and client.calls == []


def test_question_naming_the_reported_well_still_reaches_llm(db_conn):
    client = FakeClient(answers=[_final("out_of_scope")])
    _agent(db_conn, client).ask("Seberapa jauh BARAKUDA-1 dari TAPIS-F?")
    assert client.calls


def test_tool_rounds_stop_at_the_answer_deadline(db_conn, monkeypatch):
    monkeypatch.setattr(config, "ANSWER_DEADLINE_S", 40)  # kurang dari 2x cadangan waktu ronde akhir
    client = FakeClient(answers=[_final("out_of_scope")])
    _agent(db_conn, client).ask("Berapa NPT?")
    assert len(client.calls) == 1 and client.calls[0]["tool_choice"] == "none"
    assert client.calls[0]["timeout"] <= 40


def test_tool_round_keeps_time_for_the_final_answer(db_conn):
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("lookup_glossary", {"term": "BHA"})])],
        answers=[_final("answered", "Bottom Hole Assembly")],
    )
    _agent(db_conn, client).ask("Apa itu BHA?")
    first = client.calls[0]
    assert "tool_choice" not in first
    assert first["timeout"] * 2 <= config.ANSWER_DEADLINE_S - config.FINAL_ROUND_RESERVE_S


def test_hung_model_call_is_cut_at_the_wall_clock_deadline(db_conn, monkeypatch):
    import time
    from wellchat.agent import AnswerTimeout
    monkeypatch.setattr(config, "ANSWER_DEADLINE_S", 0.6)
    monkeypatch.setattr(config, "FINAL_ROUND_RESERVE_S", 0.2)
    client = FakeClient()
    client.chat.completions.create = lambda **kw: time.sleep(5)  # provider yang terus "memproses"
    started = time.monotonic()
    with pytest.raises(AnswerTimeout):
        _agent(db_conn, client).ask("Apa itu BHA?")
    assert time.monotonic() - started < 1.5


def test_json_with_raw_newlines_in_strings_is_parsed(db_conn):
    raw = '{"status": "answered", "language": "id", "answer": "BHA adalah\nBottom Hole Assembly", "sources": []}'
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("lookup_glossary", {"term": "BHA"})])],
        answers=[_reply(raw)],
    )
    r = _agent(db_conn, client).ask("Apa itu BHA?")
    assert r.answer == "BHA adalah\nBottom Hole Assembly" and not r.answer.startswith("{")


@pytest.fixture()
def reload_config():
    """Muat ulang config setelah env diubah, lalu kembalikan ke kondisi semula."""
    import importlib
    yield lambda: importlib.reload(config)
    importlib.reload(config)


def test_empty_base_url_in_env_still_targets_openai(db_conn, monkeypatch, reload_config):
    monkeypatch.setenv("OPENAI_BASE_URL", "")  # baris `OPENAI_BASE_URL=` tanpa nilai di .env
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # tanpa .env, SDK menolak dibuat bila key kosong
    reload_config()
    assert config.API_BASE_URL == "https://api.openai.com/v1"
    assert str(WellChatAgent(db_conn).client.base_url).startswith("https://api.openai.com/v1")


def test_ready_signal_in_the_final_answer_is_not_shown(db_conn):
    client = FakeClient(
        research=[_reply(tool_calls=[_tool_call("search_reports", {"query": "helicopter"})])],
        answers=[_reply("READY")],
    )
    r = _agent(db_conn, client).ask("Ada kecelakaan helikopter?")
    assert r.status == "not_found" and r.answer == NOT_FOUND["id"]


def test_endpoint_without_required_tool_choice_keeps_not_found(db_conn):
    from openai import BadRequestError

    class NoRequired(FakeClient):
        def _create(self, **kwargs):
            if kwargs.get("tool_choice") == "required":
                raise BadRequestError("tool_choice required not supported", response=NS(status_code=400, request=None, headers={}), body=None)
            return super()._create(**kwargs)

    client = NoRequired(answers=[_final("not_found")])
    r = _agent(db_conn, client).ask("Apa itu XYZ?")
    assert r.status == "not_found" and r.answer == NOT_FOUND["id"]
