"""UI chat Streamlit. Jalankan dengan:  streamlit run app.py"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from wellchat import config, models
from wellchat.agent import WellChatAgent
from wellchat.ingest import ingest
from wellchat.store import open_db

st.set_page_config(page_title="Well Data Chat", page_icon="🛢️", layout="wide")

EXAMPLES = [
    "Dimana letak lokasi sumur?",
    "Berapa Total NPT sumur?",
    "Wireline run apa yang direncanakan?",
    "Apa arti BHA?",
]


def run_ingest() -> dict:
    return ingest(config.RAW_DIR, config.PARSED_DIR, config.DB_PATH, log=lambda *_: None)


def documents() -> list[dict]:
    if not config.DB_PATH.exists():
        return []
    with open_db(config.DB_PATH) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM documents ORDER BY doc_type, report_date")]


def _doc_id_by_name() -> dict[str, str]:
    """Ambil semua nama sekali query, supaya tabel tidak dibaca ulang untuk setiap baris sumber."""
    return {d["file_name"]: d["doc_id"] for d in documents()}


def source_path(file_name: str, doc_ids: dict[str, str] | None = None) -> Path | None:
    doc_id = (doc_ids or _doc_id_by_name()).get(file_name)
    if not doc_id:
        return None
    p = config.RAW_DIR / doc_id
    return p if p.exists() else None


@st.cache_data(ttl=600, show_spinner=False)
def endpoint_models(base_url: str | None) -> list[str]:
    """Daftar model endpoint, di-cache per base URL. Kegagalan tidak di-cache karena exception tidak disimpan."""
    return models.endpoint_models()


def pick_model() -> str:
    """Pilihan model untuk sesi ini (`model` atau `model@effort`): dropdown bila MODEL_ALLOWLIST diisi, selain itu OPENAI_MODEL."""
    if config.MODEL_ALLOWLIST:
        try:
            choices = models.model_choices(endpoint_models(config.OPENAI_BASE_URL))
        except Exception:
            choices = []
        if choices:
            # key membuat pilihan tersimpan per sesi browser, tidak memengaruhi pengguna lain
            return st.selectbox("Model", choices, format_func=models.choice_label, key="model_choice")
        st.caption("Daftar model tidak bisa diambil atau tidak ada yang cocok dengan MODEL_ALLOWLIST; memakai OPENAI_MODEL.")
    st.caption(f"Model: `{config.OPENAI_MODEL}`")
    return config.OPENAI_MODEL


def render_sources(sources: list[dict], key: str) -> None:
    if not sources:
        return
    with st.expander(f"Sumber / Sources ({len(sources)})", expanded=True):
        doc_ids = _doc_id_by_name()
        for i, s in enumerate(sources):
            page = f" — page {s['page']}" if s.get("page") else ""
            section = f" — {s['section']}" if s.get("section") and s["section"] != "retrieved" else ""
            cols = st.columns([5, 1])
            cols[0].markdown(f"📄 `{s['file']}`{page}{section}")
            path = source_path(s["file"], doc_ids)
            if path:
                cols[1].download_button("Unduh", path.read_bytes(), file_name=path.name, key=f"dl-{key}-{i}")


# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Data")
    docs = documents()
    if not docs:
        st.warning("Belum ada data terparsing. Letakkan dataset di folder `data/raw/` lalu klik tombol di bawah.")
    for d in docs:
        if d["doc_type"] == "GLOSSARY":
            st.markdown(f"**Glossary** · `{d['file_name']}`")
        else:
            st.markdown(f"**{d['doc_type']} #{d['report_no']}** · {d['report_date']}  \n`{d['file_name']}`")
            for w in json.loads(d["warnings"] or "[]"):
                st.caption(f"⚠️ {w}")

    uploaded = st.file_uploader("Tambah PDF/DOCX baru", type=["pdf", "docx"], accept_multiple_files=True)
    if uploaded and st.button("Simpan & parse file baru"):
        target = config.RAW_DIR / "uploads"
        target.mkdir(parents=True, exist_ok=True)
        for f in uploaded:
            (target / Path(f.name).name).write_bytes(f.getvalue())
        with st.spinner("Parsing..."):
            stats = run_ingest()
        st.success(f"Selesai: {stats}")
        st.rerun()

    if st.button("Parse ulang folder data"):
        with st.spinner("Parsing..."):
            stats = run_ingest()
        st.success(f"Selesai: {stats}")
        st.rerun()

    st.divider()
    model = pick_model()
    if st.button("Hapus percakapan"):
        st.session_state.messages = []
        st.rerun()

# ---------------- chat ----------------
st.title("🛢️ Well Data Chat")
st.caption("Tanya jawab berdasarkan laporan sumur (DDR, DGOS) dan glosarium Oil & Gas.")

if not (config.OPENAI_API_KEY or config.OPENAI_BASE_URL):
    st.error("OPENAI_API_KEY belum diisi. Salin `.env.example` menjadi `.env`, isi key, lalu jalankan ulang.")
    st.stop()
if not docs:
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []

for i, m in enumerate(st.session_state.messages):
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m["role"] == "assistant":
            render_sources(m.get("sources", []), f"h{i}")
            if m.get("meta"):
                st.caption(m["meta"])

clicked = None
if not st.session_state.messages:
    cols = st.columns(len(EXAMPLES))
    for col, q in zip(cols, EXAMPLES):
        if col.button(q, use_container_width=True):
            clicked = q

question = st.chat_input("Tulis pertanyaan tentang data sumur...") or clicked
if question:
    history = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Mencari di dokumen..."):
            try:
                with open_db(config.DB_PATH) as conn:
                    model_name, effort = models.split_choice(model)
                    result = WellChatAgent(conn, model=model_name, reasoning_effort=effort).ask(question, history)
                answer, sources = result.answer, result.sources
                meta = f"{result.status} · {result.seconds}s · {len(result.tool_calls)} tool calls"
            except Exception as exc:  # tampilkan error API/konfigurasi, bukan stack trace
                answer, sources, meta = f"⚠️ Error: {exc}", [], "error"
        st.markdown(answer)
        render_sources(sources, f"n{len(st.session_state.messages)}")
        st.caption(meta)
    st.session_state.messages.append({"role": "assistant", "content": answer, "sources": sources, "meta": meta})
