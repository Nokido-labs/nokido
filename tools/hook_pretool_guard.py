"""
hook_pretool_guard.py — Hook PreToolUse anti-regression Nokido.
==================================================================
Branche sur Edit|Write. Quand un fichier CRITIQUE est touche :
  - injecte l'avertissement ancre dans le contexte du modele
    (additionalContext) ;
  - si l'edit reintroduit un bug ANCRE (mean-pooling bge-m3, override
    _AGENT) -> permissionDecision "ask" : force une confirmation humaine.

Fail-open : toute erreur du hook => aucune sortie => l'edit passe.
Un garde qui casse tous les edits serait pire que pas de garde.

Cable dans .claude/settings.local.json :
  hooks.PreToolUse[matcher="Edit|Write"]
"""

import json
import re
import sys

# basename -> (avertissement, [(regex_regression, raison)])
CRITICAL = {
    "forge_npu.py": (
        "bge-m3 = CLS pooling — pooled = hidden[:, 0]. JAMAIS mean pooling. "
        "Bug ancre 2026-05-20 : le mean-pooling herite de MiniLM donnait "
        "cosine 0.77 vs bge-m3 canonique = RAG casse. cf ancre RAG domain=rag.",
        [
            (
                r"\(\s*hidden\s*\*\s*mask\s*\)",
                "Cet edit reintroduit le MEAN POOLING dans forge_npu.py. bge-m3 "
                "exige CLS pooling (hidden[:, 0]). Regression ancree 2026-05-20 "
                "(cosine 0.77, RAG casse). Confirmer seulement si volontaire.",
            )
        ],
    ),
    "forge_npu_embedder.py": (
        "Embedder NPU. bge-m3 = CLS pooling. NPU XDNA1 = impasse pour un "
        "embedder transformer (0.56% GOPs offloadees, ancre 2026-05-20). "
        "Embedding local rapide = llama.cpp Vulkan (forge_rebuild_local.py).",
        [],
    ),
    "mcp_stdio_bridge.py": (
        "_AGENT doit rester HARDCODE a 'BRIDGE'. Bug ancre 2026-05-20 : un "
        "override LAFORGE_AGENT=CLAUDE via os.environ causait 401 Hub auth.",
        [
            (
                r"_AGENT\s*=\s*os\.environ",
                "Cet edit refait dependre _AGENT de l'environnement dans "
                "mcp_stdio_bridge.py. Doit rester _AGENT = 'BRIDGE' hardcode "
                "(ancre 2026-05-20, sinon 401). Confirmer seulement si volontaire.",
            )
        ],
    ),
    "forge_nlu.py": (
        "Routeur d'intention Nokido (Thalamus NLU — tri chat/action/rag). "
        "Apres modif, verifier que la classification d'intention reste "
        "coherente — c'est le tri d'entree de tout le hub.",
        [],
    ),
    "forge_intent_parser.py": (
        "Parseur d'intention Nokido — composant du routage des requetes. "
        "Modif = verifier que le routage vers les bons handlers tient.",
        [],
    ),
}


def main() -> None:
    data = json.loads(sys.stdin.read())
    if data.get("tool_name") not in ("Edit", "Write"):
        return
    ti = data.get("tool_input", {}) or {}
    # `file_path` = Write/Edit natifs ; `path` = governed_edit (relatif au depot).
    # Ne lire que le premier rendait ce garde INJOIGNABLE des que l'enforce
    # thin-client est ON : forge_tool_gate deny alors Edit/Write sur Nokido, donc
    # l'anti-regression ne voyait plus AUCUNE edition du depot. Le basename suffit
    # ici (CRITICAL est indexe dessus), un chemin relatif convient donc.
    fp = str(ti.get("file_path") or ti.get("path") or "").replace("\\", "/")
    base = fp.rsplit("/", 1)[-1]
    if base not in CRITICAL:
        return

    warn, regressions = CRITICAL[base]
    new = str(ti.get("new_string", "") or ti.get("content", "") or "")

    for rx, reason in regressions:
        if re.search(rx, new):
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "ask",
                            "permissionDecisionReason": f"[ANTI-REGRESSION] {reason}",
                        }
                    }
                )
            )
            return

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": f"[GARDE ANTI-REGRESSION] {base} = fichier "
                    f"critique. {warn}",
                }
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail-open : ne jamais bloquer un edit sur une erreur du hook
