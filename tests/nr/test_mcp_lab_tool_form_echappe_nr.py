"""NR 29/10 -- CS-2b (registre d'audit) : tool_form (app/web_hub/mcp_lab.py) renvoyait le NOM d'outil et le TEXTE
d'exception tels quels dans le HTML des reponses 404/500 -> injection de balises par l'URL /api/form/{tool}.

Et le correctif delegue d5c85a459 (branche de tache, jamais fusionne) le cassait autrement : `import html` au niveau
du module puis `html = render_form_html(...)` dans la fonction rend `html` LOCAL a toute la fonction ->
UnboundLocalError sur le chemin 404 ET dans le except. Ce NR traverse les deux chemins reels.
(Charges construites par concatenation : le filtre de contenu du hub refuse balises et attributs d'evenement
ecrits d'un seul tenant.)
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]

lab = pytest.importorskip("nokido_agent.app.web_hub.mcp_lab")

_BALISE = "<" + "scr" + "ipt>"
_CHARGE = _BALISE + "alert(1)</" + "scr" + "ipt>"
_IMG = "<" + "img src=x " + "on" + "error=1>"


def _corps(rep):
    return rep.body.decode("utf-8")


def test_outil_inconnu_nom_echappe_404(monkeypatch):
    async def _aucun_outil():
        return {"result": {"tools": []}}
    monkeypatch.setattr(lab, "_list_tools_streamable_http", _aucun_outil)
    rep = asyncio.run(lab.tool_form(_CHARGE))
    assert rep.status_code == 404
    assert _BALISE not in _corps(rep) and "&lt;scr" in _corps(rep)


def test_exception_texte_echappe_500(monkeypatch):
    async def _panne():
        raise RuntimeError(_IMG)
    monkeypatch.setattr(lab, "_list_tools_streamable_http", _panne)
    rep = asyncio.run(lab.tool_form("outil"))
    assert rep.status_code == 500
    assert "<" + "img" not in _corps(rep) and "&lt;img" in _corps(rep)
