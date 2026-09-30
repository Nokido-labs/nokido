"""forge_publication_gate.py — porte d'autorisation FAIL-CLOSED du push PUBLIC.

Refuse TOUT push public sauf si, cumulativement :
  1. la decision BREVET/IP de l'owner est ENREGISTREE
     (`docs/ip/DECISION_PUBLICATION.json`, champ `brevet_ip_tranche` = true) ;
  2. la DOUBLE confirmation owner est presente : les deux variables d'environnement
     `NOKIDO_GO_PUBLIC_1` et `NOKIDO_GO_PUBLIC_2`, posees aux phrases attendues
     (deux actes deliberes DISTINCTS que l'agent ne peut pas defaulter).

Aucun defaut ne l'ouvre. Un signal manquant -> refus NOMME. Cablee au point de push
de `forge_dist_publish` et `launch_public_mirror`. Owner 2026-09-15.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : porte d'autorisation fail-closed du push public"

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECISION = ROOT / "docs" / "ip" / "DECISION_PUBLICATION.json"
CONFIRM_1 = "je-confirme-la-publication-publique"
CONFIRM_2 = "oui-vraiment-publier-maintenant"


def _decision_ip() -> tuple[bool, str]:
    if not DECISION.exists():
        return False, ("decision BREVET/IP ABSENTE — creer docs/ip/DECISION_PUBLICATION.json "
                       '{"brevet_ip_tranche": true, "date": "...", "par": "owner"}')
    try:
        d = json.loads(DECISION.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - illisible = fail-closed, nomme
        return False, "decision BREVET/IP ILLISIBLE (%s)" % type(e).__name__
    if not d.get("brevet_ip_tranche"):
        return False, "decision BREVET/IP NON TRANCHEE (brevet_ip_tranche != true)"
    return True, "decision IP OK (%s)" % d.get("date", "?")


def _double_confirmation() -> tuple[bool, str]:
    if os.environ.get("NOKIDO_GO_PUBLIC_1", "") != CONFIRM_1:
        return False, "1re confirmation owner ABSENTE/incorrecte (env NOKIDO_GO_PUBLIC_1)"
    if os.environ.get("NOKIDO_GO_PUBLIC_2", "") != CONFIRM_2:
        return False, "2e confirmation owner ABSENTE/incorrecte (env NOKIDO_GO_PUBLIC_2)"
    return True, "double confirmation owner OK"


def porte_publique() -> tuple[bool, str]:
    """FAIL-CLOSED. Rend (ok, motif). TOUTES les conditions doivent tenir."""
    ok_ip, m_ip = _decision_ip()
    if not ok_ip:
        return False, "PUBLICATION BLOQUEE — " + m_ip
    ok_c, m_c = _double_confirmation()
    if not ok_c:
        return False, "PUBLICATION BLOQUEE — " + m_c
    return True, "AUTORISATION PUBLIQUE accordee (IP tranchee + double confirmation)"


if __name__ == "__main__":
    ok, motif = porte_publique()
    print(("OK : " if ok else "REFUS : ") + motif)
    raise SystemExit(0 if ok else 1)
