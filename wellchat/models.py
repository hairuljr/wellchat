"""Pilihan model untuk dropdown di UI (opsional).

Aplikasi bergantung pada *tool calling* dan *structured output* ber-JSON schema,
padahal endpoint OpenAI-compatible bisa mengembalikan ratusan model, termasuk model
embedding, gambar, atau audio yang tidak bisa dipakai. Karena itu dropdown hanya
menawarkan model di `config.MODEL_ALLOWLIST` yang benar-benar tersedia di endpoint.
Allowlist kosong (default) berarti dropdown tidak ditampilkan dan aplikasi memakai
`OPENAI_MODEL` saja.

Setiap entri allowlist boleh membawa reasoning effort sendiri, misalnya `gpt-5-nano@low`,
karena model berbeda menerima nilai effort yang berbeda (ada yang hanya menerima `none`
bersama tool, ada yang justru menolak `none`).
"""

from __future__ import annotations

from collections.abc import Iterable

from openai import OpenAI

from . import config


def endpoint_models(timeout: float = 15.0) -> list[str]:
    """ID model dari `GET /v1/models`. Exception sengaja diteruskan ke pemanggil."""
    client = OpenAI(api_key=config.OPENAI_API_KEY or None, base_url=config.API_BASE_URL,
                    timeout=timeout, max_retries=0)
    return sorted(m.id for m in client.models.list().data if m.id)


def split_choice(choice: str) -> tuple[str, str | None]:
    """`"gpt-5-nano@low"` -> `("gpt-5-nano", "low")`; tanpa `@`, effort-nya `None` (pakai default)."""
    model, _, effort = choice.partition("@")
    return model.strip(), effort.strip() or None


def choice_label(choice: str) -> str:
    model, effort = split_choice(choice)
    return f"{model} (effort: {effort})" if effort else model


def model_choices(available: Iterable[str]) -> list[str]:
    """`OPENAI_MODEL` lebih dulu, lalu isi allowlist sesuai urutannya; hanya yang modelnya ada di endpoint."""
    have = set(available)
    wanted = dict.fromkeys([config.OPENAI_MODEL, *config.MODEL_ALLOWLIST])
    return [c for c in wanted if split_choice(c)[0] in have]
