#!/usr/bin/env python3
"""forge_ui_design_cover.py — DÉPORTÉ : génère TOUS les composants design_handoff via la moulinette.

0 TOKEN CLOUD : le modèle LOCAL (Qwen router_local) lit les specs + produit les JSON schemas ;
le générateur DÉTERMINISTE produit les render_X(). Aucun spec ne remonte dans le contexte cloud.
Lancer DÉPORTÉ (run_job) : forge_agent_proxy.ask('router_local') tape le LLM local (souverain).

Sortie : sandbox/workspace/design_components_out.py (render_<comp>() + registry COMPONENTS).
Transfert vers app/web_hub/ ensuite via governed_edit (gouverné, 0 token) ou owner.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))
from nokido_agent.tools import forge_ui_moulinette as M  # noqa

HANDOFF = ROOT / "design_handoff_laforge" / "components"
OUT = ROOT / "sandbox" / "workspace" / "design_components_out.py"


def _kebab(s: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", s).lower()


def main() -> int:
    prompts = sorted(HANDOFF.rglob("*.prompt.md"))
    fns, names, fails = [], [], []
    for pm in prompts:
        comp = pm.stem  # ex ModuleCard
        kb = _kebab(comp)
        spec = pm.read_text(encoding="utf-8", errors="replace")
        for sib_suffix in (".ref.jsx", ".props.d.ts.txt"):
            sib = pm.parent / (kb + sib_suffix)
            if sib.exists():
                spec += f"\n\n// {sib.name}:\n" + sib.read_text(encoding="utf-8", errors="replace")[:4000]
        try:
            schema = M.schema_from_spec(spec)            # LOCAL Qwen -> JSON schema (0 token cloud)
            if "name" not in schema:
                schema["name"] = kb.replace("-", "_")
            skel = M.skeleton_from_schema(schema)        # DÉTERMINISTE -> render_X()
            ast.parse(skel["code"])                      # valide
            ns: dict = {}
            exec(skel["code"], ns)                       # exécute
            fns.append(skel["code"])
            names.append((comp, skel["name"]))
        except Exception as e:
            fails.append({"comp": comp, "err": str(e)[:140]})

    header = ("# GÉNÉRÉ par forge_ui_design_cover — moulinette LOCALE (0 token cloud).\n"
              "# Composants design_handoff_laforge -> render_X() web_hub. Régén: run_job ce script.\n"
              "from __future__ import annotations\n\n\n")
    registry = "COMPONENTS = {\n" + "".join(f"    {c!r}: {fn},\n" for c, fn in names) + "}\n"
    module = header + "\n\n".join(fns) + "\n\n" + registry
    try:
        ast.parse(module)
    except Exception as e:
        return _emit({"error": f"module assemblé invalide: {e}", "failed": fails})
    OUT.write_text(module, encoding="utf-8")
    return _emit({"generated": len(names), "components": [c for c, _ in names],
                  "failed": fails, "bytes": len(module), "out": str(OUT)})


def _emit(d: dict) -> int:
    print(json.dumps(d, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
