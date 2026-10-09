from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data")).resolve()
RAW_DIR = Path(os.getenv("RAW_DIR", DATA_DIR / "raw")).resolve()
PARSED_DIR = Path(os.getenv("PARSED_DIR", DATA_DIR / "parsed")).resolve()
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "wellchat.db")).resolve()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None  # any OpenAI-compatible endpoint
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
# only sent to reasoning models (gpt-5*, o*); leave empty to omit
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "none")
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "8"))
REQUEST_TIMEOUT_S = float(os.getenv("REQUEST_TIMEOUT_S", "120"))
