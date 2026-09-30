#!/usr/bin/env python3
"""forge_ingest_rfc_run.py — déporte l'ingestion docset RFC + snippets canoniques.

run_job ne passe pas d'args ; ce wrapper appelle forge_curriculum_ingest.ingest_module('rfc')
+ ingest_snippets() et sort un JSON consolidé. Online (fetch rfc-editor.org). Idempotent
(ids déterministes ; un re-run écrase/skip). Jetable.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_curriculum_ingest as ci  # noqa: E402

out = {"rfc": ci.ingest_module("rfc"), "snippets": ci.ingest_snippets()}
out["total"] = out["rfc"]["chunks_total"] + out["snippets"]["chunks_total"]
print(json.dumps(out, ensure_ascii=False, indent=2))
