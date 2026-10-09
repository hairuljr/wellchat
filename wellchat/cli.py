"""Chat lewat terminal, praktis untuk cek cepat dan dipakai skrip evaluasi.

    python -m wellchat.cli "Dimana letak lokasi sumur?"
    python -m wellchat.cli            # mode interaktif
"""

from __future__ import annotations

import sys

from . import config
from .agent import ChatResult, WellChatAgent
from .store import connect


def format_result(r: ChatResult) -> str:
    lines = [r.answer]
    if r.sources:
        lines.append("\nSources:")
        for s in r.sources:
            page = f", page {s['page']}" if s.get("page") else ""
            section = f" ({s['section']})" if s.get("section") and s["section"] != "retrieved" else ""
            lines.append(f"  - {s['file']}{page}{section}")
    lines.append(f"\n[{r.status}, {r.seconds}s, {len(r.tool_calls)} tool calls]")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not config.DB_PATH.exists():
        print("No database yet. Run: python -m wellchat.ingest", file=sys.stderr)
        return 1
    if not config.OPENAI_API_KEY and not config.OPENAI_BASE_URL:
        print("OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 1
    agent = WellChatAgent(connect(config.DB_PATH))
    if argv:
        print(format_result(agent.ask(" ".join(argv))))
        return 0
    history: list[dict] = []
    print("Well data chat. Empty line to quit.")
    while True:
        try:
            q = input("\n> ").strip()
        except EOFError:
            break
        if not q:
            break
        try:
            r = agent.ask(q, history)
        except Exception as exc:  # error API / batas waktu: tampilkan, lalu lanjut ke pertanyaan berikutnya
            print(f"Error: {exc}")
            continue
        print(format_result(r))
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": r.answer}]
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
