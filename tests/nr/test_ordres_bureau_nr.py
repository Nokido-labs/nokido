"""NR — ordres confies a la session de l'owner (app/forge_ordres_bureau.py, 26/09).

Contrat :
  - un ordre de redemarrage n'existe QUE si l'owner a repondu ACCEPTE au dialogue
    d'elicitation ; REFUSE, ANNULE, EXPIRE, INDISPONIBLE ne deposent rien ;
  - un ordre est pris UNE fois, par un consommateur admis (TRAY, MASTER), avant son echeance ;
    un ordre echu disparait et le journal le dit ;
  - chaque action confirmable existe dans le panneau (nokido_launcher.ACTIONS) et dans le tray ;
  - `redemarrer_stack` ouvre le flux SSE qui porte la question (`sse_requis`) ;
  - rings decides par l'owner le meme jour : MASTER 2 (seed du videur), TRAY 2 (registre).
"""
from __future__ import annotations

import ast
import asyncio
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))
sys.path.insert(0, str(RACINE / "tools"))

import forge_ordres_bureau as ob  # noqa: E402  (import strict)


@pytest.fixture(autouse=True)
def etat_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "JOURNAL", tmp_path / "ordres_bureau.jsonl")
    ob._ORDRES.clear()
    yield
    ob._ORDRES.clear()


def _journal():
    if not ob.JOURNAL.exists():
        return []
    return [json.loads(l) for l in ob.JOURNAL.read_text(encoding="utf-8").splitlines() if l.strip()]


def _confirmer(etat):
    appels = []

    async def confirmer(action, detail=""):
        appels.append((action, detail))
        return {"etat": etat, "contenu": {"confirmer": etat == "ACCEPTE"}}

    return confirmer, appels


# ── elicitation -> ordre ───────────────────────────────────────────────────────────

def test_un_ordre_n_existe_qu_apres_accepte():
    confirmer, appels = _confirmer("ACCEPTE")
    r = asyncio.run(ob.redemarrer_stack("CLAUDE", "module recharge", confirmer=confirmer))
    assert r["etat"] == ob.DEPOSE and r["depose"] is True
    assert len(appels) == 1 and "CLAUDE" in appels[0][1] and "module recharge" in appels[0][1]
    attente = ob.en_attente()
    assert [o["action"] for o in attente] == ["restart"] and attente[0]["id"] == r["ordre"]


@pytest.mark.parametrize("etat", ["REFUSE", "ANNULE", "EXPIRE", "INDISPONIBLE"])
def test_tout_autre_etat_ne_depose_rien(etat):
    confirmer, _ = _confirmer(etat)
    r = asyncio.run(ob.redemarrer_stack("CLAUDE", confirmer=confirmer))
    assert r["etat"] == etat and r["depose"] is False
    assert ob.en_attente() == []
    assert [e["evenement"] for e in _journal()] == ["non_depose"]


# ── prise par le tray ──────────────────────────────────────────────────────────────

def test_usage_unique():
    ob.deposer("restart", "CLAUDE", maintenant=1000.0)
    r = ob.prendre("TRAY", maintenant=1001.0)
    assert r["etat"] == ob.ORDRE and r["ordre"]["action"] == "restart"
    assert ob.prendre("TRAY", maintenant=1002.0) == {"etat": ob.RIEN}


def test_le_panneau_maitre_peut_aussi_prendre():
    ob.deposer("restart", "CLAUDE", maintenant=1000.0)
    assert ob.prendre("master", maintenant=1001.0)["etat"] == ob.ORDRE


def test_un_ordre_echu_disparait_et_le_journal_le_dit():
    ob.deposer("restart", "CLAUDE", maintenant=1000.0)
    assert ob.prendre("TRAY", maintenant=1000.0 + ob.ECHEANCE_S + 1)["etat"] == ob.RIEN
    assert [e["evenement"] for e in _journal()] == ["depose", "echu"]


def test_un_consommateur_non_admis_ne_prend_rien():
    ob.deposer("restart", "CLAUDE", maintenant=1000.0)
    r = ob.prendre("CLAUDE", maintenant=1001.0)
    assert r["etat"] == ob.REFUSE and "CLAUDE" in r["raison"]
    assert len(ob.en_attente(maintenant=1001.0)) == 1, "le refus a consomme l'ordre"
    assert ob.prendre("", maintenant=1001.0)["etat"] == ob.REFUSE


def test_une_action_non_confirmable_est_refusee():
    with pytest.raises(ValueError):
        ob.deposer("stop", "CLAUDE")
    assert ob.en_attente() == []


# ── coherence avec le panneau, le tray et le transport ─────────────────────────────

def _litteral(chemin: Path, nom: str):
    for n in ast.parse(chemin.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == nom for t in n.targets):
            return n.value
    raise AssertionError("%s absent de %s" % (nom, chemin.name))


def test_chaque_action_confirmable_existe_dans_le_panneau_et_le_tray():
    actions_panneau = {k.value for k in _litteral(RACINE / "tools" / "nokido_launcher.py", "ACTIONS").keys}
    actions_tray = set(ast.literal_eval(_litteral(RACINE / "tools" / "nokido_tray.py", "ACTIONS_PANNEAU")))
    for action in ob.ACTIONS:
        assert action in actions_panneau, "%s inconnue du panneau" % action
        assert action in actions_tray, "%s inconnue du tray" % action


def test_redemarrer_stack_ouvre_le_flux_qui_porte_la_question():
    import forge_mcp_elicitation as me

    assert me.sse_requis("hub", {"action": "redemarrer_stack"}) is True
    assert me.sse_requis("hub", {"action": "confirmer_owner"}) is True
    assert me.sse_requis("hub", {"action": "ordre_bureau"}) is False


# ── rings decides par l'owner le 2026-09-26 ────────────────────────────────────────

def test_le_maitre_qui_se_dit_maitre_est_ring_2():
    import forge_videur as V

    maitre = "maitre-de-test-sans-valeur"
    ident = V.resolve_identity("MASTER", maitre, local=True, agent_tokens={}, hub_token=maitre)
    assert ident["via"] == "master_token" and ident["ring"] == 2


def test_le_tray_est_ring_2_au_registre():
    registre = json.loads((RACINE / "config" / "agent_identities.json").read_text(encoding="utf-8"))
    assert registre["agents"]["TRAY"]["ring"] == 2
