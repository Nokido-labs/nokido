"""NR 30/10 : un restart demande par le CLI pilote fait MONTER une fenetre de validation ; rien sans le Oui de l'owner.

Owner 30/10 (« non , tu fait juste monter une fenetre de validation a la rigeur pour valider l ordre ») : pour un CLI
interactif prouve, `demander_ordre restart` rendait A_DEMANDER (question + commande a coller) ; l'elicitation MCP, elle,
expirait sans s'afficher (19/10). L'ordre est desormais DEPOSE marque `a_valider` ; le tray ouvre une fenetre Oui/Non au
premier plan et n'execute que sur Oui. Fenetre impossible = NON (jamais une execution sans validation).
"""
from __future__ import annotations

import ast
import asyncio
import sys
import types
from pathlib import Path

from nokido_agent.app import forge_ordres_bureau as OB

# Convention des NR du tray : il sort (sys.exit) a l'import hors bureau interactif (pystray). On EXTRAIT ses fonctions
# par AST et on construit chacune depuis son objet code, avec des doublures : le comportement reel, sans le tray.
_SRC = (Path(__file__).resolve().parents[2] / "tools" / "nokido_tray.py").read_text(encoding="utf-8")


def _fonction_du_tray(nom: str, globales: dict):
    noeud = next(n for n in ast.parse(_SRC).body if isinstance(n, ast.FunctionDef) and n.name == nom)
    module = compile(ast.Module(body=[noeud], type_ignores=[]), "nokido_tray.py", "exec")
    code = next(c for c in module.co_consts if isinstance(c, types.CodeType) and c.co_name == nom)
    globales.setdefault("__builtins__", __builtins__)
    return types.FunctionType(code, globales, nom)


def test_restart_du_cli_pilote_depose_un_ordre_a_valider(monkeypatch):
    monkeypatch.setattr(OB, "_surface_de", lambda agent: "interactive")
    monkeypatch.setattr(OB, "_consigner", lambda *_a, **_k: None)
    appels = []

    async def _dialogue(titre, detail):
        appels.append(1)
        return {"etat": "REFUSE"}

    r = asyncio.run(OB.redemarrer_stack("CLAUDE", raison="charger 1c4ce13a7", confirmer=_dialogue,
                                        demandeur_prouve=True))
    assert appels == [], "pas d'elicitation qui expire"
    assert r.get("depose") is True and r.get("a_valider") is True
    assert any(o.get("id") == r.get("ordre") and o.get("a_valider") is True for o in OB._ORDRES)


def _ordre(a_valider):
    o = {"id": "ordre-x", "action": "restart", "demandeur": "CLAUDE", "raison": "essai"}
    if a_valider:
        o["a_valider"] = True
    return {"etat": "ORDRE", "ordre": o}


def _tray(monkeypatch, reponse_hub, oui):
    lances, vues = [], []
    g = {"_state": {"hub_up": True}, "_mcp": lambda *a, **k: reponse_hub,
         "lancer_panneau": lambda action, **k: lances.append(action), "_notify": lambda *a, **k: None,
         "_valider_par_fenetre": lambda ordre: vues.append(ordre["id"]) or oui,
         "ACTIONS_PANNEAU": ("start", "stop", "restart", "restart-hub", "status"),
         # 3/11 : nouvelle dependance de _prendre_ordre (decisions OAuth, test_tray_consentement_oauth_nr)
         "DECISIONS_TRAY": ("oauth-consentement",)}
    _fonction_du_tray("_prendre_ordre", g)()
    return lances, vues


def test_fenetre_impossible_vaut_non(monkeypatch):
    class _User32:
        def MessageBoxW(self, *a):
            raise OSError("pas de bureau")

    faux_ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(user32=_User32()))
    monkeypatch.setitem(sys.modules, "ctypes", faux_ctypes)
    notes = []
    valider = _fonction_du_tray("_valider_par_fenetre", {"_notify": lambda m, **k: notes.append(m)})
    assert valider({"id": "ordre-x", "action": "restart", "demandeur": "CLAUDE"}) is False
    assert notes


def test_ordre_a_valider_execute_sur_oui(monkeypatch):
    lances, vues = _tray(monkeypatch, _ordre(True), True)
    assert vues == ["ordre-x"] and lances == ["restart"]


def test_ordre_a_valider_refuse_sur_non(monkeypatch):
    lances, vues = _tray(monkeypatch, _ordre(True), False)
    assert vues == ["ordre-x"] and lances == []


def test_ordre_deja_confirme_ne_redemande_pas(monkeypatch):
    lances, vues = _tray(monkeypatch, _ordre(False), False)
    assert vues == [] and lances == ["restart"]
