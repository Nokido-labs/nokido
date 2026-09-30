#!/usr/bin/env python3
"""forge_veille_codex_run.py — veille déportée : écosystème OpenAI/Codex.

Wrapper run_job (pas d'args) -> ingest_module('codex_eco') -> RAG domain=reference.
SearXNG down -> crawl DIRECT (SPA JS éventuel = contenu partiel, best-effort). Online. Jetable.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_curriculum_ingest as ci  # noqa: E402

print(json.dumps(ci.ingest_module("codex_eco"), ensure_ascii=False, indent=2))
