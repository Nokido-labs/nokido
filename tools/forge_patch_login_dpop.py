"""Patch de `/api/login` : transporter la cle du porteur (RFC 9449).

Sans ce maillon, `cnf.jkt` n'est atteignable qu'en appelant `login_agent`
in-process : les organes qui passent par HTTP -- dont tous les organes Deno --
n'auraient AUCUN chemin vers le lien. Un mecanisme sans chemin est une dette
de cablage, jamais une securite.

`nokido_hub.py` est CRITICAL_FILE et volumineux : `governed_edit` y a deja
coupe le hub (2026-08-27). Chemin sur : patch COMMITE, lance par
`run action=trusted_script`, qui verifie son ancre, valide l'AST et ecrit
atomiquement.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

CIBLE = Path(__file__).resolve().parents[1] / "tools" / "nokido_hub.py"

ANCRE_1 = '''    secret_id = body.get("secret_id")
    timestamp = body.get("timestamp")
    signature = body.get("signature")
'''

REMPLACEMENT_1 = '''    secret_id = body.get("secret_id")
    timestamp = body.get("timestamp")
    signature = body.get("signature")
    # LIEN AU PORTEUR (RFC 9449). Le demandeur peut presenter la cle publique
    # dont il prouvera la possession a chaque requete : le jeton emis porte
    # alors son empreinte (`cnf.jkt`, RFC 7638) et devient inutilisable sans la
    # cle privee correspondante. Un bearer non lie, lui, est rejouable par
    # quiconque le vole -- il prouve la connaissance d'un secret, jamais
    # l'identite du porteur.
    #
    # Champ OPTIONNEL, et volontairement : l'exiger avant qu'un seul appelant
    # sache le produire ne durcirait rien, ca rendrait le corps muet.
    dpop_jwk = body.get("dpop_jwk")
    if dpop_jwk is not None and not isinstance(dpop_jwk, dict):
        return JSONResponse(
            {"error": "dpop_jwk doit etre un objet JWK"}, status_code=400)
'''

ANCRE_2 = '''            agent_tokens=_AGENT_TOKENS
        )
        return JSONResponse({"token": token, "expires_in": 1800})
'''

REMPLACEMENT_2 = '''            agent_tokens=_AGENT_TOKENS,
            dpop_jwk=dpop_jwk,
        )
        # RFC 9449 §6 exige qu'on puisse identifier DE FACON FIABLE si un jeton
        # est lie. `bound` n'est pas decoratif : un porteur qui croit son jeton
        # lie alors qu'il ne l'est pas se croit protege pour rien, et c'est
        # exactement le genre de croyance qu'on ne detecte qu'apres coup.
        return JSONResponse({"token": token, "expires_in": 1800,
                             "bound": bool(dpop_jwk)})
'''


def main() -> int:
    src = CIBLE.read_text(encoding="utf-8")
    if REMPLACEMENT_2 in src:
        print("DEJA APPLIQUE : /api/login transporte deja dpop_jwk.")
        return 0

    for nom, ancre in (("ANCRE_1", ANCRE_1), ("ANCRE_2", ANCRE_2)):
        if src.count(ancre) != 1:
            print("%s introuvable ou multiple (%d occurrence(s)). Rien ecrit."
                  % (nom, src.count(ancre)))
            return 2

    neuf = src.replace(ANCRE_1, REMPLACEMENT_1).replace(ANCRE_2, REMPLACEMENT_2)
    try:
        ast.parse(neuf)
    except SyntaxError as exc:
        print("AST REFUSE : %s ligne %s. Rien ecrit." % (exc.msg, exc.lineno))
        return 3

    fd, tmp = tempfile.mkstemp(dir=str(CIBLE.parent), suffix=".patch.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(neuf)
        os.replace(tmp, CIBLE)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    if REMPLACEMENT_2 not in CIBLE.read_text(encoding="utf-8"):
        print("ECRITURE NON CONFIRMEE a la relecture.")
        return 4
    print("PATCH APPLIQUE. Effet au prochain redemarrage du hub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
