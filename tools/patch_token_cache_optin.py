"""Patcher : cache de lecture conditionnelle en OPT-IN STRICT dans app/forge_mcp_registry.py (CRITICAL_FILE :
governed_edit le refuse ; chemin officiel = patcher committe + run action=trusted_script).

Defaut du branchement livre (AGY, 499b16c09 cherry-pick) : SANS si_etag ni depuis_etag, chaque `read`,
`read_function_body`, `get_file_skeleton` (1) prefixait sa reponse d'une ligne `etag: ...` -- un script qui lit un
JSON par le hub cassait sur json.loads -- et (2) ecrivait un instantane dans sandbox/token_cache a CHAQUE lecture.
Correctif : sans etag fourni, la reponse est IDENTIQUE a avant et rien n'est ecrit. Pour apprendre l'etag d'un
fichier, le client envoie une premiere fois si_etag="0" (aucun etag reel ne vaut "0") : PLEIN + en-tete etag.

--verifier : ancre unique + AST apres patch, n'ecrit rien. Idempotent. Fins de ligne du fichier conservees.
Retour arriere : `git checkout -- app/forge_mcp_registry.py`.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

__FORGE_COLOR__ = "immunitaire/maintenance-gouvernee"

CIBLE = Path(__file__).resolve().parents[1] / "app" / "forge_mcp_registry.py"
ANCRE = ('        """Applique forge_token_cache.lecture_conditionnelle de manière sûre (opt-in strict)."""\n'
         '        racine = self._resoudre_racine_git(chemin_abs)\n')
NOUVEAU = ('        """Applique forge_token_cache.lecture_conditionnelle de manière sûre (opt-in strict).\n'
           '        Sans si_etag ni depuis_etag : reponse IDENTIQUE et aucune ecriture (un client lit du JSON par `read`).\n'
           '        Premier appel pour apprendre l\'etag : si_etag="0" -> PLEIN avec en-tete mode/etag."""\n'
           '        if not si_etag and not depuis_etag:\n'
           '            return texte_rendu\n'
           '        racine = self._resoudre_racine_git(chemin_abs)\n')


def main() -> int:
    verifier = "--verifier" in sys.argv
    with open(CIBLE, encoding="utf-8", newline="") as f:
        src = f.read()
    eol = "\r\n" if "\r\n" in src else "\n"
    ancre, nouveau = ANCRE.replace("\n", eol), NOUVEAU.replace("\n", eol)
    if nouveau in src:
        print("deja applique : rien a faire")
        return 0
    n = src.count(ancre)
    if n != 1:
        print(f"ANCRE introuvable ou ambigue ({n} occurrence(s)) : rien ecrit")
        return 2
    neuf = src.replace(ancre, nouveau)
    ast.parse(neuf)
    if verifier:
        print("verifier : ancre unique, AST OK apres patch ; rien ecrit")
        return 0
    with open(CIBLE, "w", encoding="utf-8", newline="") as f:
        f.write(neuf)
    ast.parse(CIBLE.read_text(encoding="utf-8"))
    print("applique : opt-in strict, AST OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
