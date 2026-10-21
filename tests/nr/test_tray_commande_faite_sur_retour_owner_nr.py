# -*- coding: utf-8 -*-
"""NR -- une commande du tray dont l'owner a COLLE le retour est retiree par l'agent (consigne owner 19/10, ancree).

Owner, 19/10 ~00 h 45 : « si je te donne des retours de commandes envoyees au tray, merci de les enlever ensuite du
tray ! » puis « ancre-le ». `marquer_commande` refusait tout agent (« un agent ne la fait pas disparaitre a la place de
l'owner ») : juste quand l'owner n'a PAS fait la commande, pas quand il en a donne le retour.

Contrat : un agent hors des consommateurs du tray marque une commande FAITE seulement s'il joint un EXTRAIT du retour
colle par l'owner (non vide) ; la trace dit « faite par l'owner, rapportee par <agent> » et garde l'extrait borne ;
sans extrait, refus comme avant ; commande inconnue, refus.
"""
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_ordres_bureau as B  # noqa: E402


@pytest.fixture()
def tray(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "COMMANDES", tmp_path / "commandes.jsonl")
    return B.deposer_commande("CLAUDE", "Get-Service mtkbtsvc", "lecture")["id"]


def test_retour_owner_colle_l_agent_retire_la_commande(tray):
    r = B.marquer_commande("CLAUDE", tray, extrait_retour="MTKBTSVC Stopped Disabled")
    assert r["etat"] == "FAITE"
    assert tray not in {c["id"] for c in B.commandes_en_attente()}
    derniere = json.loads(B.COMMANDES.read_text(encoding="utf-8").splitlines()[-1])
    assert derniere["par"] == "OWNER" and derniere["rapporte_par"] == "CLAUDE"
    assert "Stopped" in derniere["extrait_retour"]


def test_sans_extrait_un_agent_reste_refuse(tray):
    assert B.marquer_commande("CLAUDE", tray)["etat"] == B.REFUSE
    assert tray in {c["id"] for c in B.commandes_en_attente()}


def test_commande_inconnue_refusee(tray):
    assert B.marquer_commande("CLAUDE", "cmd-inexistante", extrait_retour="x")["etat"] == B.REFUSE
