#!/usr/bin/env python3
"""forge_ui_repo_cover.py — couvre TOUT le dépôt : 1 form UI fidèle par tool hub.

Vision user : "couvrir l'ensemble du dépôt Nokido pour créer facilement les interfaces
fidèles au code existant fonctionnel". Chaque tool hub a déjà un JSON Schema (contrat exact
des params) -> forge_ui_moulinette.form_from_jsonschema en dérive un formulaire FIDÈLE PAR
CONSTRUCTION, DÉTERMINISTE, 0 token cloud. Ce script les génère TOUS d'un coup.

Source des contrats : forge_mcp_registry.ToolRegistry.get_tool_list(ring, agent) (format MCP).
Sortie : un module `render_<tool>_form()` par tool + un registry FORMS{name->fn}.

Déterministe (pas de LLM) -> rapide. Stage dans sandbox/workspace (le sandbox ne peut écrire
dans app/) puis transfert via Write gouverné, OU run_job owner qui écrit directement.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))


def generate(ring: int = 0, agent: str = "claude") -> dict:
    from nokido_agent.tools import forge_ui_moulinette as M
    from nokido_agent.app.forge_mcp_registry import get_registry
    reg = get_registry()
    tools = reg.get_tool_list(ring=ring, agent=agent) or []
    fns, names, skipped = [], [], []
    for t in tools:
        name = t.get("name") if isinstance(t, dict) else None
        sch = (t.get("inputSchema") or t.get("input_schema") or t.get("parameters") or {}) if isinstance(t, dict) else {}
        if not name:
            continue
        safe = re.sub(r"\W", "_", name)
        try:
            skel = M.form_from_jsonschema(safe, sch if isinstance(sch, dict) else {}, action=f"/hub/tool/{name}")
            ast.parse(skel["code"])           # garde-fou par tool
            fns.append(skel["code"])
            names.append((name, safe))
        except Exception as e:                # un tool malformé ne casse pas le lot
            skipped.append({"tool": name, "err": str(e)[:80]})
    registry = "FORMS = {\n" + "".join(f"    {n!r}: render_{s}_form,\n" for n, s in names) + "}\n"
    header = ("# GÉNÉRÉ par forge_ui_repo_cover — 1 form fidèle par tool hub (contrat JSON Schema).\n"
              "# DÉTERMINISTE, 0 token cloud. Régén: LAFORGE_PYTHON tools/forge_ui_repo_cover.py\n"
              "from __future__ import annotations\n\n\n")
    module = header + "\n\n".join(fns) + "\n\n" + registry
    ast.parse(module)                          # le module entier compile ?
    ns: dict = {}
    exec(module, ns)                           # et s'exécute ?
    assert "FORMS" in ns and len(ns["FORMS"]) == len(names)
    return {"module": module, "count": len(names), "skipped": skipped, "tools": [n for n, _ in names]}


def main(argv: list) -> int:
    import json
    res = generate()
    stage = ROOT / "sandbox" / "workspace" / "tool_forms_out.py"
    stage.write_text(res["module"], encoding="utf-8")
    print(json.dumps({"forms_generated": res["count"], "skipped": res["skipped"],
                      "bytes": len(res["module"]), "staged": str(stage),
                      "sample_tools": res["tools"][:15]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
