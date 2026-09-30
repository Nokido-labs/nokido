#!/usr/bin/env python3
"""forge_veille_gemini_run.py — veille approfondie déportée : écosystème Gemini/Gemma.

run_job ne passe pas d'args -> wrapper qui appelle forge_curriculum_ingest.ingest_module('gemini_eco')
(docs Gemini API sous-pages + cookbooks google-gemini/google-gemma) -> RAG domain=reference.
SearXNG down (Docker) -> crawl DIRECT des URLs connues (pas de search-discovery). Online. Jetable.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_curriculum_ingest as ci  # noqa: E402

print(json.dumps(ci.ingest_module("gemini_eco"), ensure_ascii=False, indent=2))
