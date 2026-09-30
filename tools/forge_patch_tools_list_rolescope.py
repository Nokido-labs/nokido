"""Patch CRITICAL_FILE : `tools/list` peut deriver son perimetre du ROLE.

__FORGE_COLOR__ = "immunitaire/maintenance-gouvernee"

Etat mesure le 2026-09-02 avant ce patch :
  - `get_tool_list` ne consultait que `active_tools_for` = le scope DECLARE par
    l'agent (opt-in, TTL). Un agent qui ne declare rien voit tout.
  - `expected_scope_for` -- qui ajoute le repli system-owned « derive du role »,
    ecrit precisement pour « fermer le bypass opt-out » -- n'avait qu'UN seul
    consommateur, `forge_intention_gate`, c'est-a-dire le controle a l'APPEL.
    La VISIBILITE, elle, n'en beneficiait pas.

Ce patch branche `expected_scope_for` sur `tools/list`, derriere un drapeau
DESARME par defaut (`LAFORGE_TOOLS_LIST_ROLESCOPE`). Le drapeau n'est pas une
timidite : reduire ce que voient tous les clients MCP change leur comportement,
et la mesure du jour montre que le perimetre derive pour CLAUDE (`code_recon`,
17 tools) N'INCLUT PAS `governed_edit` -- l'agent qui edite le plus ne verrait
pas l'outil d'edition. C'est un arbitrage owner, pas une evidence technique.

Le `except Exception: pass` d'origine devient un log : un scope qui disparait
sur une erreur d'import doit se voir, meme si le fail-open reste le bon defaut.

Usage :
    run action=trusted_script path=tools/forge_patch_tools_list_rolescope.py
    run action=trusted_script path=tools/forge_patch_tools_list_rolescope.py script_args="--apply"
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

ANCRE = '''            from forge_tool_scope import active_tools_for as _ts_active
            _scope = _ts_active(agent)
            if _scope:
                visible = [t for t in visible if t["name"] in _scope]
        except Exception:
            pass  # scope best-effort : jamais casser tools/list
'''

REMPLACEMENT = '''            import forge_tool_scope as _ts
            # Perimetre DECLARE par defaut. Avec LAFORGE_TOOLS_LIST_ROLESCOPE,
            # on prend `expected_scope_for` : declare d'abord, sinon DERIVE du
            # role (profil system-owned) -- ce qui ferme le bypass opt-out, un
            # agent ne pouvant plus elargir sa vue en ne declarant rien.
            # Desarme par defaut : le perimetre derive peut masquer un outil
            # dont l'agent a besoin (mesure : `code_recon` n'inclut pas
            # `governed_edit`). Le dispatch, lui, reste ouvert dans les deux cas.
            if os.environ.get("LAFORGE_TOOLS_LIST_ROLESCOPE", "").strip().lower() in (
                "1", "true", "on", "yes"
            ):
                _scope, _src = _ts.expected_scope_for(agent)
            else:
                _scope, _src = _ts.active_tools_for(agent), "declared"
            if _scope:
                visible = [t for t in visible if t["name"] in _scope]
        except Exception as _se:
            # fail-open volontaire (ne jamais casser tools/list), mais PAS muet :
            # un scope qui s'evapore sur une erreur d'import doit laisser une trace.
            logger.debug("[tool_scope] perimetre indisponible (fail-open) : %s", _se)
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    a = ap.parse_args()

    if not CIBLE.exists():
        print("ABSENT : %s" % CIBLE)
        return 2

    src = CIBLE.read_text(encoding="utf-8")

    if "LAFORGE_TOOLS_LIST_ROLESCOPE" in src:
        print("DEJA PATCHE. Rien a faire.")
        return 0

    n = src.count(ANCRE)
    if n != 1:
        print("ANCRE TROUVEE %d FOIS (attendu 1) -- refus d'ecrire." % n)
        return 3

    neuf = src.replace(ANCRE, REMPLACEMENT, 1)

    try:
        compile(neuf, str(CIBLE), "exec")
    except SyntaxError as e:
        print("AST INVALIDE apres patch (%s) -- refus d'ecrire." % e)
        return 4

    # `os` doit etre importe au module, sinon le patch introduit un NameError
    # qui ne se verrait qu'a l'execution de tools/list.
    if "\nimport os" not in neuf and "\nimport os," not in neuf:
        print("`import os` introuvable au module -- refus (NameError a l'execution).")
        return 6

    print("ancre unique OK | AST OK | import os present | delta = +%d octets"
          % (len(neuf) - len(src)))

    if not a.apply:
        print("DRY-RUN : rien ecrit. Relancer avec --apply.")
        return 0

    fd, tmp = tempfile.mkstemp(dir=str(CIBLE.parent), suffix=".patchtmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(neuf)
        os.replace(tmp, str(CIBLE))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:  # muet-ok : nettoyage best-effort, l'erreur reelle est relancee
            pass
        raise

    relu = CIBLE.read_text(encoding="utf-8")
    ok = "LAFORGE_TOOLS_LIST_ROLESCOPE" in relu and len(relu) == len(neuf)
    print("ECRIT | relecture disque : %s" % ("identique" if ok else "DIVERGENTE"))
    print("Drapeau DESARME : poser LAFORGE_TOOLS_LIST_ROLESCOPE=1 pour l'activer.")
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
