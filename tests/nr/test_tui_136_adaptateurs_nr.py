"""NR -- la TUI 13.6 (tools/nokido_tui.py) charge ses adaptateurs au lancement REEL, et dit leur absence.

MESURE du 2026-09-25 (owner : « la TUI textual ne fonctionne toujours pas ») : lancee comme en
production (`python tools/nokido_tui.py`, donc sys.path[0] = tools/), `from tui_adapters import`
levait ModuleNotFoundError -- le paquet vit dans app/, que le script n'ajoutait pas au chemin (son
commentaire affirmait le contraire). L'exception etait AVALEE : les 8 adaptateurs a None, donc la
fenetre SSH en PTY, les commandes slash heritees de la v13.6 et les vues services / taches / sante
/ RBAC etaient mortes, et `/ssh` ne repondait RIEN. Les NR TUI existants inserent eux-memes app/
dans sys.path : ils masquaient le defaut. Celui-ci passe par le chemin du lanceur.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SCRIPT = RACINE / "tools" / "nokido_tui.py"
ADAPTATEURS = ("_cmd_a", "_pty_a", "_svc_a", "_tsk_a", "_hlt_a", "_evt_a", "_fge_a", "_rbac_a")

# Comme `python tools/nokido_tui.py` : seul le dossier du script en tete du chemin. run_name
# different de __main__ : le module s'execute entierement, sans lancer l'application.
SONDE = """
import json, runpy, sys
sys.path[0] = {outils!r}
g = runpy.run_path({script!r}, run_name="nokido_tui_nr")
etat = {{n: g.get(n) is not None for n in {noms!r}}}
etat["erreur"] = g.get("_ADAPTERS_ERREUR")
print("RESULTAT " + json.dumps(etat))
"""


# BORNE (26/09). La CI impose `--timeout=30` PAR TEST ; ce test attendait jusqu'a 120 s son sous-processus. Sous
# la charge de la suite complete (CI de reference 706c68e4a), l'enfant a depasse 30 s et pytest-timeout (methode
# thread) a tue TOUT le processus pytest : suite pure sans JUnit, 1 561 s perdues. Seul, le test prend 0,5 s.
# Borne du test > borne de l'enfant : un enfant lent fait echouer CE test en le disant, jamais la suite. stdin
# ferme : l'enfant n'herite plus du stdin du job, sur lequel une lecture bloquerait sans fin.
@pytest.mark.timeout(150)
def test_lancement_reel_charge_les_huit_adaptateurs():
    code = SONDE.format(outils=str(SCRIPT.parent), script=str(SCRIPT), noms=ADAPTATEURS)
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=str(RACINE), capture_output=True,
                           stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                           timeout=120)
    except subprocess.TimeoutExpired as exc:
        pytest.fail("lancement reel de la TUI > 120 s ; fin de la sortie d'erreur de l'enfant :\n%s"
                    % str(exc.stderr or "")[-1500:])
    ligne = next((l for l in r.stdout.splitlines() if l.startswith("RESULTAT ")), None)
    assert ligne, "sonde muette (rc=%s) :\n%s" % (r.returncode, r.stderr[-1500:])
    etat = json.loads(ligne[len("RESULTAT "):])
    erreur = etat.pop("erreur")
    absents = [n for n, charge in etat.items() if not charge]
    assert not absents, "adaptateurs absents au lancement reel : %s (%s)" % (absents, erreur)


def test_absence_du_pty_est_dite_a_l_ecran(monkeypatch, tmp_path):
    for _p in (str(RACINE), str(RACINE / "tools")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import nokido_tui as nt

    monkeypatch.setattr(nt, "status_services", lambda: {"hub": "🟢"})
    monkeypatch.setattr(nt, "opsec_state", lambda: {"level": "STANDARD", "locked": False, "by": None})
    monkeypatch.setattr(nt, "fetch_recent", lambda *a, **k: [])
    monkeypatch.setattr(nt, "M2M", tmp_path / "absente.db")
    monkeypatch.setattr(nt, "_pty_a", None)
    monkeypatch.setattr(nt, "_ADAPTERS_ERREUR", "ModuleNotFoundError: tui_adapters", raising=False)

    async def scenario():
        app = nt.NokidoTUI()
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause(0.5)
            saisie = app.query_one("#compose", nt.Input)
            app.set_focus(saisie)
            saisie.value = "/ssh 127.0.0.1 22 user"
            await pilot.press("enter")
            await pilot.pause(2.5)  # au-dela d'un tour de la boucle de statut
            statut = "\n".join(getattr(l, "text", str(l))
                               for l in app.query_one("#status_pane", nt.RichLog).lines)
            assert "PTY indisponible" in statut, "absence du PTY TUE en silence :\n" + statut
            assert "tui_adapters" in statut, "la cause n'est pas nommee :\n" + statut

    asyncio.run(scenario())
