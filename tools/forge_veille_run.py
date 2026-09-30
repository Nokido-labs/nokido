#!/usr/bin/env python3
"""forge_veille_run.py — veille approfondie déportée GÉNÉRIQUE : ingère TOUS les modules `*_eco`.

Remplace les wrappers par-source : ajouter un module `<x>_eco` dans forge_curriculum_ingest puis
relancer ce job suffit (ré-ingestion idempotente, ids déterministes). RAG domain=reference, embed
daemon vectorise. SearXNG down -> crawl direct des URLs. Online. Jetable.
"""

__FORGE_COLOR__ = "digestif/veille : veille approfondie deportee generique (*_eco)"  # organe declare le 2026-09-06 (audit de raccordement)
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_curriculum_ingest as ci  # noqa: E402

ecos = [k for k in ci.MODULES if k.endswith("_eco")]
out = {"ecos": ecos, "results": {e: ci.ingest_module(e) for e in ecos}}
out["chunks_total"] = sum(r["chunks_total"] for r in out["results"].values())
print(json.dumps(out, ensure_ascii=False, indent=2))
