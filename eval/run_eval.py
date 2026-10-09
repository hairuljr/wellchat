"""Jalankan set pertanyaan ke agen sungguhan, lalu laporkan akurasi dan waktu respons.

    python -m eval.run_eval                 # semua pertanyaan
    python -m eval.run_eval --only 1 2 3    # hanya nomor tertentu

Pertanyaan dianggap lulus bila status-nya cocok, setiap grup `must` punya minimal satu
alternatif yang muncul di jawaban, tidak ada teks `must_not` di jawaban (tanpa membedakan
huruf besar/kecil), dan tidak ada sumber yang namanya memuat teks `sources_must_not`.
Ringkasan ditulis ke eval/results.md, jawaban utuh beserta sumbernya ke eval/results.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wellchat import config
from wellchat.agent import WellChatAgent
from wellchat.store import connect

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", type=int)
    args = ap.parse_args()

    cases = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    agent = WellChatAgent(connect(config.DB_PATH))
    rows, full, passed, slowest = [], [], 0, 0.0
    for n, case in enumerate(cases, start=1):
        if args.only and n not in args.only:
            continue
        r = agent.ask(case["q"])
        ok_status = r.status in case["status"]
        missing = [g for g in case.get("must", []) if not any(alt in r.answer for alt in g)]
        unwanted = [t for t in case.get("must_not", []) if t.lower() in r.answer.lower()]
        wrong_sources = [s["file"] for s in r.sources if any(t in s["file"] for t in case.get("sources_must_not", []))]
        ok = ok_status and not missing and not unwanted and not wrong_sources
        passed += ok
        slowest = max(slowest, r.seconds)
        files = ", ".join(sorted({s["file"] for s in r.sources}))
        print(f"[{'PASS' if ok else 'FAIL'}] #{n} {r.seconds:5.1f}s {r.status:12} {case['q']}")
        if not ok:
            print(f"       expected status {case['status']}, missing {missing}, unwanted {unwanted}, "
                  f"wrong sources {wrong_sources}\n       answer: {r.answer[:300]}")
        rows.append((n, ok, r.seconds, r.status, case["q"], r.answer.replace("\n", " ")[:400], files))
        full.append({"no": n, "passed": ok, "seconds": r.seconds, "status": r.status, "question": case["q"],
                     "answer": r.answer, "sources": r.sources, "tool_calls": r.tool_calls})

    total = len(rows)
    lines = [f"# Evaluation results\n", f"Model: `{config.OPENAI_MODEL}`  ",
             f"Passed: **{passed}/{total}**  ", f"Slowest answer: **{slowest:.1f}s** (limit 180s)\n",
             "| # | Result | Time (s) | Status | Question | Answer (truncated) | Sources |",
             "|---|---|---|---|---|---|---|"]
    for n, ok, sec, status, q, ans, files in rows:
        lines.append(f"| {n} | {'✅' if ok else '❌'} | {sec} | {status} | {q} | {ans.replace('|', '/')} | {files} |")
    (HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (HERE / "results.json").write_text(json.dumps(full, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{passed}/{total} passed, slowest {slowest:.1f}s. Details in eval/results.md")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
