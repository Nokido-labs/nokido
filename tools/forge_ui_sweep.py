#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_ui_sweep.py — BALAYAGE moulinette UI sur TOUT le dépôt (déterministe, 0 token).

Couvre l'intégralité de la surface MCP : énumère TOUS les tools du hub (chacun a un
JSON Schema de params) -> forge_ui_moulinette.form_from_jsonschema -> écrit un
render_<tool>_form() dans app/web_hub/forms/. Fidèle par construction (le schéma EST
le contrat). Idempotent. AUCUN appel LLM.

USAGE (déporté) : run_job script=tools/forge_ui_sweep.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
OUTDIR = ROOT / "app" / "web_hub" / "forms"
OUT = r"C:\tmp\forge_ui_sweep.txt"


def _schema_of(t: dict) -> dict:
    for k in ("inputSchema", "input_schema", "parameters", "schema"):
        s = t.get(k)
        if isinstance(s, dict) and s.get("properties"):
            return s
    return {}


def main() -> int:
    log = {"generated": 0, "skipped_noparams": 0, "errors": []}
    try:
        from nokido_agent.tools import forge_ui_moulinette as mou
        from nokido_agent.app.forge_mcp_registry import get_registry
        reg = get_registry()
        tools = reg.get_tool_list(ring=0, agent="LAFORGE_CLI")  # ring0 = surface complète
        log["tools_seen"] = len(tools)
        OUTDIR.mkdir(parents=True, exist_ok=True)
        index = []
        for t in tools:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            schema = _schema_of(t)
            if not schema:
                log["skipped_noparams"] += 1
                continue
            try:
                skel = mou.form_from_jsonschema(name, schema)
                slug = re.sub(r"\W+", "_", name).strip("_").lower()
                code = (f"# GÉNÉRÉ par forge_ui_sweep (moulinette déterministe, 0 token) — tool '{name}'.\n"
                        f"# Régén : run_job tools/forge_ui_sweep.py. Cible web_hub HTMX/Alpine/lf-.\n"
                        "from __future__ import annotations\n\n" + skel["code"])
                (OUTDIR / f"{slug}_form.py").write_text(code, encoding="utf-8")
                index.append(slug)
                log["generated"] += 1
            except Exception as e:  # noqa: BLE001
                log["errors"].append(f"{name}: {type(e).__name__}: {e}")
        # index des forms générés
        (OUTDIR / "__index__.json").write_text(json.dumps(sorted(index), ensure_ascii=False, indent=1), encoding="utf-8")
        open(OUT, "w", encoding="utf-8").write(json.dumps(log, ensure_ascii=False, indent=1))
        print(f"DONE generated={log['generated']} skipped={log['skipped_noparams']} errors={len(log['errors'])}")
    except Exception:
        import traceback
        open(OUT, "w", encoding="utf-8").write(json.dumps(log) + "\nEXC:\n" + traceback.format_exc())
        print("EXC")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
