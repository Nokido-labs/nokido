#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_jeton_lanceur.py -- le jeton COURT d'une identite, pour le superviseur qui lance son service.

Decision owner du 2026-09-28 : le superviseur (LocalSystem) ne fait plus heriter son
environnement -- jeton maitre compris -- a chaque enfant ; il injecte le jeton court de
l'identite du service (`NOKIDO_JETON_COURT` + `NOKIDO_IDENTITE`), que le service renouvelle
par echange de jeton RFC 8693 (`forge_agent_credential`).
Plan : C:/tmp/plan_jeton_court_lanceur_2026-09-28.md, etape B.

Chaine de preuve, dans l'ordre :
  1. TPM (consigne owner : le TPM dans la chaine) -- assertion `IDENTITE:horodatage` signee
     par la cle TPM (ECDSA P-256, non exportable), verifiee par `login_agent` avec sa fenetre
     anti-rejeu de 5 min. AUCUN secret statique n'est lu. `creer=False` : le lanceur ne
     fabrique jamais de cle en passant.
  2. TPM indisponible : le secret statique de l'identite, echange au hub -- DIT sur stderr.
  3. Sinon : refus. Jamais le maitre, jamais un jeton invente.
Ce que ceci n'est PAS : l'assertion n'a pas la forme d'un JWT bearer (RFC 7523) ; c'est le
chemin de connexion signe deja en place (`/api/login`), non normalise. Le jeton emis est un
CapabilityToken signe par le hub, renouvelable par echange de jeton RFC 8693.

Sortie : le jeton SEUL sur stdout (lu par le superviseur par un tube) ; diagnostics sans
aucune valeur sur stderr. Codes : 0 emis, 2 hors SYSTEM, 3 identite refusee (inconnue du
registre, ou ring <= DEV : l'owner ne passe jamais par le lanceur), 4 aucun chemin de preuve.

Usage : forge_jeton_lanceur.py <IDENTITE>
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

__FORGE_COLOR__ = "immunitaire/jeton-lanceur : jeton court d'une identite pour le superviseur qui lance son service"


def _dire(message: str) -> None:
    print(f"[jeton_lanceur] {message}", file=sys.stderr)


def _login_par_le_hub(corps: dict) -> str:
    """POST JSON sur `/api/login` du hub, boucle locale seulement ; le jeton, ou ''."""
    import json
    import urllib.request

    from nokido_agent.app import forge_agent_credential as cred

    url = cred._url_login_du_hub()
    if not url:
        return ""
    req = urllib.request.Request(url, data=json.dumps(corps).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as rep:
            d = json.loads(rep.read().decode("utf-8", "replace") or "{}")
        return str(d.get("token") or "")
    except Exception:  # noqa: BLE001 -- refus ou hub injoignable : '' et c'est dit
        return ""


def emettre(identite: str) -> tuple:
    """(code, jeton, chemin de preuve). Aucune valeur secrete dans `chemin`."""
    from nokido_agent.app import forge_agent_credential as cred
    from nokido_agent.app import forge_auth_tokens as at
    from nokido_agent.app import forge_persona_tpm as tpm

    ident = (identite or "").upper().strip()
    if not cred._sous_system():
        return 2, "", "hors SYSTEM"
    if ident not in {str(a).upper() for a in at._agents_connus()}:
        return 3, "", "identite absente du registre"
    ring = at._ring_de(ident)
    if int(ring) < int(at.RING_MIN_RENOUVELABLE):
        return 3, "", f"ring {ring.label()} <= DEV : l'owner ne passe jamais par le lanceur"

    horodatage = time.time()
    signature = tpm.sign(f"{ident}:{horodatage}".encode("utf-8"), creer=False)
    if signature:
        jeton = _login_par_le_hub({"role_id": ident, "timestamp": horodatage,
                                   "signature": signature.hex()})
        if jeton:
            return 0, jeton, "TPM (assertion signee, aucun secret lu)"
        _dire("assertion TPM refusee ou hub injoignable -- essai du secret statique")

    statique = cred._statique(ident)
    if statique:
        jeton = cred._echanger_par_le_hub(ident, statique)
        if jeton:
            return 0, jeton, "secret statique (TPM indisponible) -- a remplacer"
    return 4, "", "aucun chemin de preuve (ni TPM, ni secret statique echange)"


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        _dire("usage : forge_jeton_lanceur.py <IDENTITE>")
        return 3
    code, jeton, chemin = emettre(args[0])
    if code:
        _dire(f"REFUS ({code}) pour {args[0].upper()} : {chemin}")
        return code
    _dire(f"jeton court emis pour {args[0].upper()} par : {chemin}")
    print(jeton)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
