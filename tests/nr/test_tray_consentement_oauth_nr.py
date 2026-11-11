"""NR 3/11 — E4 du plan OAuth MCP : le TRAY affiche le consentement d'un client OAuth et RENVOIE la decision au hub.

Contrat : un ordre `oauth-consentement` (decision, pas action du panneau) ouvre la fenetre Oui/Non ; la reponse part
au hub par `demander_ordre ordre=decision-oui|decision-non cible=<id de l'ordre>` ; le panneau n'est JAMAIS lance ;
fenetre impossible = NON (rien n'est accorde). Fonction extraite par AST (convention des NR du tray).
"""
from __future__ import annotations

import ast
import types
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[2] / "tools" / "nokido_tray.py").read_text(encoding="utf-8")


def _fonction_du_tray(nom: str, globales: dict):
    noeud = next(n for n in ast.parse(_SRC).body if isinstance(n, ast.FunctionDef) and n.name == nom)
    module = compile(ast.Module(body=[noeud], type_ignores=[]), "nokido_tray.py", "exec")
    code = next(c for c in module.co_consts if isinstance(c, types.CodeType) and c.co_name == nom)
    globales.setdefault("__builtins__", __builtins__)
    return types.FunctionType(code, globales, nom)


def _tray(oui, eleves=False, action="oauth-consentement"):
    appels, lances, vues, notes = [], [], [], []
    demandes_eleves = []
    ordre = {"id": "ordre-oauth1", "action": action, "demandeur": "HUB", "a_valider": True,
             "cible": "demande-9", "raison": "VS Code (http://127.0.0.1:40123/cb) demande mcp:hub"}

    def _mcp(outil, args=None):
        appels.append(dict(args or {}))
        if (args or {}).get("action") == "ordre_bureau":
            return {"etat": "ORDRE", "ordre": ordre}
        return {"etat": "DECIDE", "oui": oui}

    g = {"_state": {"hub_up": True}, "_mcp": _mcp, "lancer_panneau": lambda a, **k: lances.append(a),
         "_notify": lambda m, *a, **k: notes.append(m),
         "_valider_par_fenetre": lambda o: vues.append(o["id"]) or oui,
         "_droits_eleves_par_fenetre": lambda o: demandes_eleves.append(o["id"]) or eleves,
         "ACTIONS_PANNEAU": ("start", "stop", "restart", "restart-hub", "status"),
         "DECISIONS_TRAY": ("oauth-consentement", "oauth-revocation")}
    _fonction_du_tray("_prendre_ordre", g)()
    _tray.demandes_eleves = demandes_eleves
    return appels, lances, vues, notes


def test_oui_et_droits_eleves_renvoie_decision_oui_ring1():
    # 3/11 (decision owner « ring choisi au tray + inscrit au registre ») : 2e fenetre apres le Oui
    appels, lances, vues, notes = _tray(True, eleves=True)
    assert {"action": "demander_ordre", "ordre": "decision-oui-ring1", "cible": "ordre-oauth1"} in appels
    assert _tray.demandes_eleves == ["ordre-oauth1"] and lances == []


def test_revocation_une_seule_fenetre_jamais_les_droits_eleves():
    appels, lances, vues, notes = _tray(True, eleves=True, action="oauth-revocation")
    assert {"action": "demander_ordre", "ordre": "decision-oui", "cible": "ordre-oauth1"} in appels
    assert _tray.demandes_eleves == [] and lances == []


def test_non_ne_demande_pas_les_droits_eleves():
    _tray(False, eleves=True)
    assert _tray.demandes_eleves == []


def test_oui_renvoie_decision_oui_au_hub_sans_lancer_le_panneau():
    appels, lances, vues, notes = _tray(True)
    assert vues == ["ordre-oauth1"] and lances == []
    assert {"action": "demander_ordre", "ordre": "decision-oui", "cible": "ordre-oauth1"} in appels
    assert any("AUTORIS" in n.upper() for n in notes)


def test_non_renvoie_decision_non():
    appels, lances, vues, notes = _tray(False)
    assert lances == []
    assert {"action": "demander_ordre", "ordre": "decision-non", "cible": "ordre-oauth1"} in appels
