# -*- coding: utf-8 -*-
"""NR (bb:P1_demandes_admin_par_le_cli_pilote_20261017, reste « depot automatique quand le dialogue expire ») -- un
dialogue d'accord qui EXPIRE ou est INDISPONIBLE laisse au tray la COMMANDE que l'owner lancera lui-meme.

Mesure 19/10 ~20 h 20 : `hub demander_ordre ordre=pair-approuver` a ouvert un dialogue MCP expire a 120 s ; rien n'a
ete depose (forge_ordres_bureau : EXPIRE / INDISPONIBLE « ne deposent RIEN ») et CLAUDE a du deposer a la main
`forge_pair_quarantaine.py --approuver <id>` au tray. Le consentement reste celui de l'owner : il EXECUTE la commande
lui-meme ; on ne depose jamais un ORDRE executable sans ACCEPTE. Contrat de `demander_ordre` :
  1. EXPIRE ou INDISPONIBLE -> rien d'execute, une commande deposee (`repli_commande`) : pair-approuver ->
     `forge_pair_quarantaine.py --approuver <cible>` ; action du tray -> `nokido_launcher.py --action <ordre>` ;
  2. REFUSE ou ANNULE (l'owner a dit non) -> aucune commande ;
  3. un texte portant un secret n'est jamais depose (meme scanner que commande-deposer).
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app import forge_ordres_bureau as ob  # noqa: E402


@pytest.fixture()
def commandes(tmp_path, monkeypatch):
    f = tmp_path / "commandes.jsonl"
    monkeypatch.setattr(ob, "COMMANDES", f)
    monkeypatch.setattr(ob, "JOURNAL", tmp_path / "ordres_bureau.jsonl")   # jamais le vrai journal du hub
    return f


def _deposees(f):
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def _demander(ordre, etat, **kw):
    async def confirmer(titre, detail):
        return {"etat": etat}
    return asyncio.run(ob.demander_ordre("CLAUDE", ordre, confirmer=confirmer, **kw))


@pytest.mark.parametrize("etat", ["EXPIRE", "INDISPONIBLE"])
def test_dialogue_expire_depose_la_commande_owner(commandes, monkeypatch, etat):
    monkeypatch.setattr(ob, "_executer_hub", lambda *a, **k: pytest.fail("execute sans ACCEPTE"))
    monkeypatch.setattr(ob, "_resume_depot", lambda cible: "resume")
    r = _demander("pair-approuver", etat, cible="pair_4fae9d1471ea4310")
    assert r.get("depose") is False and r.get("repli_commande"), r
    textes = [c["texte"] for c in _deposees(commandes)]
    assert any("forge_pair_quarantaine.py" in t and "--approuver pair_4fae9d1471ea4310" in t for t in textes), textes


def test_action_du_tray_expiree_depose_le_lanceur(commandes, monkeypatch):
    action = sorted(a for a in ob.ACTIONS if a not in ob.SANS_CONFIRMATION)[0]
    r = _demander(action, "EXPIRE")
    assert r.get("repli_commande"), r
    assert any("nokido_launcher.py" in c["texte"] and "--action %s" % action in c["texte"]
               for c in _deposees(commandes))


@pytest.mark.parametrize("etat", ["REFUSE", "ANNULE"])
def test_un_refus_owner_ne_depose_rien(commandes, monkeypatch, etat):
    monkeypatch.setattr(ob, "_resume_depot", lambda cible: "resume")
    r = _demander("pair-approuver", etat, cible="pair_x")
    assert not r.get("repli_commande") and _deposees(commandes) == []


def test_un_secret_n_est_jamais_depose(commandes, monkeypatch):
    import nokido_agent.tools.forge_governed_edit as ge
    monkeypatch.setattr(ge, "_scan_secrets", lambda t: ["motif"])
    r = _demander("pair-repondre", "EXPIRE", cible="client_x", pointeur="pair-reponse:apr_1", texte="x")
    assert not r.get("repli_commande") and _deposees(commandes) == [], r
