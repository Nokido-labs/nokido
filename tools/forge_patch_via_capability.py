"""Patch du middleware SHADOW : distinguer un jeton a bail d'un inconnu.

`nokido_hub.py` est CRITICAL_FILE et volumineux : `governed_edit` y a deja
coupe le hub (memoire du 2026-08-27). Le chemin sur : un patch COMMITE, lance
par `run action=trusted_script`, qui verifie son ancre, valide l'AST et ecrit
atomiquement.

CE QUE CE PATCH CORRIGE, et pourquoi maintenant (mesure du 2026-09-02) : la
classification du `via` rangeait en `bearer_inconnu` tout ce qui n'etait ni le
maitre ni un credential statique. Un jeton a bail VALIDE (HTTP 200, ring
resolu identique au statique du meme organe) sortait donc avec le meme mot que
le `bad_token` refuse 18 fois dans la meme fenetre. Cabler les organes sur des
jetons a bail AVANT ce correctif aurait rendu leur trafic legitime
indistinguable d'un intrus -- un durcissement qui degrade la tracabilite.

La logique vit dans `app/forge_authz_shadow.classer_porteur` (testee hors hub,
sans secret) ; le hub n'injecte que les comparateurs, parce que c'est lui qui
detient les secrets. Le jeton n'est ni journalise ni retourne.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

CIBLE = Path(__file__).resolve().parents[1] / "tools" / "nokido_hub.py"

ANCRE = '''                    if _auth.lower().startswith("bearer "):
                        _tok = _auth[7:].strip()
                        try:
                            if HUB_TOKEN and hmac.compare_digest(
                                    _tok.encode(), HUB_TOKEN.encode()):
                                _via = "bearer_maitre"
                            elif any(hmac.compare_digest(_tok.encode(), str(_t).encode())
                                     for _t in _AGENT_TOKENS.values() if _t):
                                _via = "bearer_derive"
                            else:
                                _via = "bearer_inconnu"
                        except Exception:  # muet-ok : comparaison best-effort, la FORME reste juste
                            _via = "bearer"
                        finally:
                            _tok = ""
'''

REMPLACEMENT = '''                    if _auth.lower().startswith("bearer "):
                        # Le classement vit dans forge_authz_shadow : le hub
                        # n'injecte que les comparateurs, parce que lui seul
                        # detient les secrets. Le jeton n'est jamais ecrit.
                        #
                        # Le decodeur separe un jeton a bail VERIFIE d'un
                        # jeton de la bonne forme mais REFUSE (expire, revoque,
                        # signature). Sans lui, les deux se lisaient comme un
                        # `bad_token` -- mesure du 2026-09-02.
                        def _est_maitre(_t: str) -> bool:
                            return bool(HUB_TOKEN) and hmac.compare_digest(
                                _t.encode(), HUB_TOKEN.encode())

                        def _est_statique(_t: str) -> bool:
                            return any(
                                hmac.compare_digest(_t.encode(), str(_s).encode())
                                for _s in _AGENT_TOKENS.values() if _s)

                        try:
                            import forge_integrity as _fi

                            _decodeur = _fi.get_manager().decode_raw
                        except Exception:
                            # Pas de verdict possible : `classer_porteur` rendra
                            # `bearer_indecidable`, jamais un faux « inconnu ».
                            _decodeur = None
                        _via = _az.classer_porteur(
                            _auth, est_maitre=_est_maitre,
                            est_statique=_est_statique, decoder=_decodeur)
'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    if REMPLACEMENT in src:
        print("DEJA APPLIQUE : le middleware appelle deja classer_porteur.")
        return 0
    if src.count(ANCRE) != 1:
        print("ANCRE INTROUVABLE ou multiple (%d occurrence(s)). Rien ecrit."
              % src.count(ANCRE))
        return 2

    neuf = src.replace(ANCRE, REMPLACEMENT)
    try:
        ast.parse(neuf)
    except SyntaxError as exc:
        print("AST REFUSE : %s ligne %s. Rien ecrit." % (exc.msg, exc.lineno))
        return 3

    dossier = str(CIBLE.parent)
    fd, tmp = tempfile.mkstemp(dir=dossier, suffix=".patch.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(neuf)
        os.replace(tmp, CIBLE)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    relu = CIBLE.read_text(encoding="utf-8")
    if REMPLACEMENT not in relu:
        print("ECRITURE NON CONFIRMEE a la relecture.")
        return 4
    print("PATCH APPLIQUE : %d octets. Effet au prochain redemarrage du hub."
          % len(relu))
    return 0


if __name__ == "__main__":
    sys.exit(main())
