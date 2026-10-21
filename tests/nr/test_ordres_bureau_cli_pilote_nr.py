"""NR -- une demande admin d'un CLI pilote PROUVE se pose dans SA session, sans dialogue qui expire.

Owner 17/10 : « les demandes admin doivent monter du CLI utilise pour Nokido ». Carte AGY job_04ab2eb5
(docs/audit/identite_cli_pilote_20261019.md) : l'identite prouvee existe (forge_videur.resolve_identity) mais
demander_ordre ne recoit qu'une chaine. Ici, la decision cote ordres_bureau : prouve ET surface interactive ->
A_DEMANDER (question + commande que l'owner lancera lui-meme) ; sinon le dialogue reste la regle.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_ordres_bureau as OB  # noqa: E402


class _Dialogue:
    def __init__(self):
        self.appels = 0

    async def __call__(self, titre, detail):
        self.appels += 1
        return {"etat": "REFUSE"}


def _demander(monkeypatch, demandeur, prouve, surface):
    monkeypatch.setattr(OB, "_surface_de", lambda agent: surface)
    monkeypatch.setattr(OB, "_consigner", lambda *_a, **_k: None)
    d = _Dialogue()
    r = asyncio.run(OB.demander_ordre(demandeur, "pair-approuver", raison="relecture", cible="pair_abc",
                                      confirmer=d, demandeur_prouve=prouve))
    return r, d


def test_cli_pilote_prouve_demande_dans_sa_session(monkeypatch):
    r, d = _demander(monkeypatch, "CLAUDE", True, "interactive")
    assert d.appels == 0
    assert r.get("etat") == "A_DEMANDER" and r.get("a_demander_dans_la_session") is True
    assert "forge_pair_quarantaine" in (r.get("commande") or "") and "pair_abc" in r.get("commande", "")
    assert r.get("question")


def test_identite_declaree_non_prouvee_garde_le_dialogue(monkeypatch):
    r, d = _demander(monkeypatch, "CLAUDE", False, "interactive")
    assert d.appels == 1 and r.get("etat") != "A_DEMANDER"


def test_executeur_autonome_prouve_garde_le_dialogue(monkeypatch):
    r, d = _demander(monkeypatch, "AGY_HEADLESS", True, "autonomous")
    assert d.appels == 1 and r.get("etat") != "A_DEMANDER"


def test_relance_de_pile_demandee_par_le_cli_pilote_prouve_aussi(monkeypatch):
    # Le cas D'ORIGINE (owner 17/10 : « reboot stack ») : demander_ordre sortait tot vers redemarrer_stack.
    monkeypatch.setattr(OB, "_surface_de", lambda agent: "interactive")
    monkeypatch.setattr(OB, "_consigner", lambda *_a, **_k: None)
    d = _Dialogue()
    r = asyncio.run(OB.demander_ordre("CLAUDE", "restart", raison="RAM", confirmer=d, demandeur_prouve=True))
    assert d.appels == 0 and r.get("a_demander_dans_la_session") is True
    assert "nokido_launcher" in (r.get("commande") or "")


def test_registre_illisible_garde_le_dialogue(monkeypatch):
    r, d = _demander(monkeypatch, "CLAUDE", True, None)
    assert d.appels == 1
