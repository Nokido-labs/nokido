"""NR -- l'aide de la TUI multi-CLI (tools/nokido_tui.py) reste LISIBLE.

Mesure du 2026-09-24 (Pilot Textual headless, chantier UI) : apres F1, l'aide est visible, puis
EFFACEE en moins d'une seconde. `action_help` ecrit dans `#status_pane` ; `_poll_loop` appelle
`_render_status()` toutes les 2 s, qui vide ce meme panneau pour y reecrire le statut. Meme sort
pour le message d'usage de `/ssh`. L'aide existait, personne ne pouvait la lire.

Ce qui est garde, par le chemin reel (touche F1, saisie `/help`, boucle de la TUI qui tourne) :
  1. l'aide survit a plusieurs tours de boucle ;
  2. Ctrl+R (rafraichir) rend la main au statut, sans attendre ;
  3. le gel expire : le statut revient seul.
Capteurs de la TUI bouchonnes (services, OPSEC, historique) : ce test juge l'AFFICHAGE, pas le reseau.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import DIRECT, jamais importorskip : Textual est une dependance du livrable, son absence doit
# faire ROUGIR ce test (un skip ici serait un faux vert).
import nokido_tui as nt  # noqa: E402


@pytest.fixture(autouse=True)
def _capteurs_simules(monkeypatch, tmp_path):
    monkeypatch.setattr(nt, "status_services", lambda: {"hub": "🟢"})
    monkeypatch.setattr(nt, "opsec_state", lambda: {"level": "STANDARD", "locked": False, "by": None})
    monkeypatch.setattr(nt, "fetch_recent", lambda *a, **k: [])
    monkeypatch.setattr(nt, "M2M", tmp_path / "absente.db")


def _statut(app) -> str:
    return "\n".join(getattr(l, "text", str(l)) for l in app.query_one("#status_pane", nt.RichLog).lines)


def test_aide_f1_survit_a_la_boucle_puis_ctrl_r_rend_le_statut():
    async def scenario():
        app = nt.NokidoTUI()
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause(0.5)
            app.set_focus(None)
            await pilot.press("f1")
            await pilot.pause(4.5)  # au moins deux tours de la boucle de 2 s
            assert "HELP" in _statut(app), "l'aide F1 a ete effacee par la boucle de statut"
            await pilot.press("ctrl+r")
            await pilot.pause(0.5)
            assert "STATUS" in _statut(app) and "HELP" not in _statut(app), "Ctrl+R ne rend pas le statut"
    asyncio.run(scenario())


def test_aide_par_la_saisie_et_expiration_du_gel():
    async def scenario():
        app = nt.NokidoTUI()
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause(0.5)
            saisie = app.query_one("#compose", nt.Input)
            app.set_focus(saisie)
            saisie.value = "/help"
            await pilot.press("enter")
            await pilot.pause(2.5)
            assert "HELP" in _statut(app), "/help : aide effacee par la boucle"
            app._statut_fige_jusqua = time.time() - 1  # le gel expire
            await pilot.pause(2.5)
            assert "STATUS" in _statut(app), "gel expire : le statut ne revient pas"
    asyncio.run(scenario())
