"""Patch CRITICAL_FILE : cable l'injection des annotations MCP dans le registre.

__FORGE_COLOR__ = "immunitaire/maintenance-gouvernee"

`app/forge_mcp_registry.py` est un CRITICAL_FILE : `governed_edit` le refuse, et
`allow_critical` a deja COUPE le hub sur un fichier de cette taille (memoire du
2026-08-27). Le chemin sur : un script git-tracke -- donc du code revu -- lance
par `run action=trusted_script`, qui ecrit de facon ATOMIQUE et refuse d'ecrire
un fichier qui ne compile pas.

Usage :
    run action=trusted_script path=tools/forge_patch_tool_annotations.py
    run action=trusted_script path=tools/forge_patch_tool_annotations.py script_args="--apply"

Sans `--apply` : n'ecrit rien, dit ce qui serait fait.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIBLE = ROOT / "app" / "forge_mcp_registry.py"

ANCRE = (
    "        return self._inject_explanation_field("
    "self._raw_tool_catalog() + self._forge_dynamic_catalog())\n"
)

REMPLACEMENT = '''        tools = self._inject_explanation_field(
            self._raw_tool_catalog() + self._forge_dynamic_catalog())
        return self._inject_annotations(tools)

    def _inject_annotations(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Injecte `annotations` (spec MCP 2026-07-28) depuis `forge_tool_annotations`.

        Le catalogue presentait `run` et `read` avec la meme neutralite : rien n'y
        disait lequel des deux peut detruire. Ces annotations le disent -- sans
        rien BLOQUER : ce qui bloque reste le videur, `forge_tool_gate` et les
        guards d'action. C'est une signaletique, pas une securite, et la spec
        elle-meme interdit d'y fonder une decision de securite.

        Un echec d'import ne passe PAS en silence : sans annotations, la spec
        presume chaque tool destructeur -- bon defaut, mais qui masquerait la
        disparition de la table. On le journalise une fois, puis on sert le
        catalogue : `tools/list` ne doit jamais casser pour un ornement.
        """
        try:
            from forge_tool_annotations import annoter
        except Exception as _ae:  # table absente ou cassee : le DIRE, une fois
            if not getattr(self, "_annotations_signalees", False):
                self._annotations_signalees = True
                logger.warning(
                    "[annotations] table indisponible (%s) : le catalogue sort SANS "
                    "annotations -- chaque tool sera presume destructeur par defaut", _ae)
            return tools
        try:
            return annoter(tools)
        except Exception as _ae:
            if not getattr(self, "_annotations_signalees", False):
                self._annotations_signalees = True
                logger.warning(
                    "[annotations] injection echouee (%s) : catalogue brut servi", _ae)
            return tools
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    a = ap.parse_args()

    if not CIBLE.exists():
        print("ABSENT : %s" % CIBLE)
        return 2

    src = CIBLE.read_text(encoding="utf-8")

    if "_inject_annotations" in src:
        print("DEJA PATCHE : `_inject_annotations` present. Rien a faire.")
        return 0

    n = src.count(ANCRE)
    if n != 1:
        # Ni 0 ni 2 ne se rattrapent : a 0 l'ancre a bouge, a 2 on ne sait pas
        # laquelle viser. Dans les deux cas, ecrire serait deviner.
        print("ANCRE TROUVEE %d FOIS (attendu 1) -- refus d'ecrire." % n)
        return 3

    neuf = src.replace(ANCRE, REMPLACEMENT, 1)

    try:
        compile(neuf, str(CIBLE), "exec")
    except SyntaxError as e:
        print("AST INVALIDE apres patch (%s) -- refus d'ecrire." % e)
        return 4

    delta = len(neuf) - len(src)
    print("ancre unique OK | AST OK | delta = +%d octets" % delta)

    if not a.apply:
        print("DRY-RUN : rien ecrit. Relancer avec --apply.")
        return 0

    # Ecriture atomique : un hub qui lit le fichier pendant l'ecriture ne doit
    # jamais voir un fichier a moitie ecrit.
    fd, tmp = tempfile.mkstemp(dir=str(CIBLE.parent), suffix=".patchtmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(neuf)
        os.replace(tmp, str(CIBLE))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:  # muet-ok : nettoyage best-effort, l'erreur reelle est relancee juste apres
            pass
        raise

    relu = CIBLE.read_text(encoding="utf-8")
    ok = "_inject_annotations" in relu and len(relu) == len(neuf)
    print("ECRIT | relecture disque : %s" % ("identique" if ok else "DIVERGENTE"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
