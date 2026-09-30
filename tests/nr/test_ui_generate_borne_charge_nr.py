"""NR : la generation de widgets ne peut plus saturer le webhub.

Cause mesuree le 2026-09-17 (wedge `:7400`, deja paye deux fois) : le service
restait LISTENING, le process vivant, et `/health` MUET ~20 s apres une page LLM.
Trois faits de source l'expliquent entierement :

  1. `/health` est declare `def` (app.py) : un handler SYNCHRONE consomme un
     jeton du threadpool anyio, plafonne a 40 par defaut ;
  2. les widgets `/ui/auto/*` sont `def` et tiennent leur jeton jusqu'a 25 s ;
  3. `generate_ui` creait un ThreadPoolExecutor NEUF par appel et faisait
     `shutdown(wait=False)` au timeout : le thread de fond continuait `cascade`
     SANS BORNE. Chaque generation expiree fuyait un thread.

Assez de generations en vol saturent les jetons, `/health` se met en FILE
derriere elles, et on lit une SATURATION comme une PANNE.

Ce NR verrouille le remede par le COMPORTEMENT, pas par la forme :
  * sature -> la main est rendue TOUT DE SUITE (pas apres `timeout_s`), sinon
    l'appelant garderait son jeton anyio et le gel reviendrait a l'identique ;
  * un slot n'est rendu que quand le travail FINIT REELLEMENT, pas quand
    l'appelant renonce -- sinon un `cascade` qui pend serait compte libre tout
    en tenant son ouvrier ;
  * les refus sont COMPTES, pour qu'un plafond se releve un jour sur un chiffre
    et non sur une impression ;
  * plus aucun executeur cree DANS `generate_ui` (controle AST + son controle
    negatif) : c'est la regression precise qui ferait revenir la fuite.

Aucun LLM n'est appele : `cascade` est remplacee par une fonction qui bloque sur
un evenement, ce qui simule exactement un fournisseur qui pend.
"""
from __future__ import annotations

import ast
import importlib
import sys
import threading
import time
import types
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE / "app") not in sys.path:
    sys.path.insert(0, str(RACINE / "app"))

SOURCE = RACINE / "app" / "web_hub" / "ui_generate.py"
MODULE_CASCADE = "nokido_agent.app.forge_frugal_cascade"


@pytest.fixture()
def ui(monkeypatch):
    """Module charge, cascade remplacee par un bloqueur, globals remis a zero."""
    faux = types.ModuleType(MODULE_CASCADE)
    bloqueur = threading.Event()
    entres = threading.Semaphore(0)

    def _cascade_qui_pend(prompt, use_case="general", max_tokens=2000):
        entres.release()
        # borne dure : meme si le test se trompe, rien ne pend indefiniment
        bloqueur.wait(timeout=20.0)
        return {"response": "<div>ok</div>", "model_used": "faux"}

    faux.cascade = _cascade_qui_pend
    monkeypatch.setitem(sys.modules, MODULE_CASCADE, faux)

    mod = importlib.import_module("web_hub.ui_generate")
    # les bornes sont des singletons de module : sans remise a zero, un test
    # heriterait des slots du precedent et mesurerait autre chose que lui-meme
    monkeypatch.setattr(mod, "_GEN_EXECUTEUR", None, raising=False)
    monkeypatch.setattr(mod, "_GEN_SLOTS", None, raising=False)
    monkeypatch.setattr(mod, "_GEN_REFUS", 0, raising=False)

    mod._test_bloqueur = bloqueur
    mod._test_entres = entres
    try:
        yield mod
    finally:
        bloqueur.set()


def _occuper_tous_les_slots(mod) -> list:
    """Lance _GEN_MAX generations qui pendent, et attend qu'elles soient ENTREES."""
    fils = []
    for _ in range(mod._GEN_MAX):
        f = threading.Thread(
            target=lambda: mod.generate_ui("widget test", timeout_s=0.4), daemon=True)
        f.start()
        fils.append(f)
    for _ in range(mod._GEN_MAX):
        assert mod._test_entres.acquire(timeout=10.0), (
            "les generations de remplissage ne sont jamais entrees dans cascade"
        )
    return fils


# ------------------------------------------------------------- comportement


def test_sature_rend_la_main_immediatement(ui):
    _occuper_tous_les_slots(ui)

    debut = time.monotonic()
    res = ui.generate_ui("widget de trop", timeout_s=5.0)
    ecoule = time.monotonic() - debut

    assert res.get("sature") is True, f"attendu un refus de saturation, recu {res!r}"
    assert ecoule < 1.0, (
        f"refus rendu en {ecoule:.2f} s : un refus qui ATTEND garde un jeton du "
        "threadpool, c'est exactement le mecanisme du gel qu'on repare"
    )


def test_le_refus_est_compte(ui):
    _occuper_tous_les_slots(ui)
    avant = ui.generation_saturation()["refus"]
    ui.generate_ui("widget de trop", timeout_s=5.0)
    apres = ui.generation_saturation()["refus"]
    assert apres == avant + 1, (
        "un plafond dont les refus ne sont pas comptes ne pourra jamais etre "
        "releve sur une mesure"
    )


def test_le_slot_n_est_rendu_qu_a_la_FIN_du_travail(ui):
    """Un appelant qui renonce ne libere pas l'ouvrier : il travaille encore."""
    _occuper_tous_les_slots(ui)
    # les generations de remplissage ont deja expire (timeout_s=0.4) ; si le slot
    # etait rendu au renoncement, la place serait libre alors que cascade pend
    time.sleep(0.8)
    res = ui.generate_ui("widget de trop", timeout_s=5.0)
    assert res.get("sature") is True, (
        "le slot a ete rendu alors que le travail de fond PEND toujours : un "
        "ouvrier occupe compterait comme libre"
    )


def test_le_slot_revient_quand_le_travail_finit(ui):
    _occuper_tous_les_slots(ui)
    ui._test_bloqueur.set()          # les cascades finissent
    for _ in range(50):              # laisse les slots revenir
        if ui.generation_saturation()["refus"] == 0:
            break
        time.sleep(0.05)
    time.sleep(0.3)
    res = ui.generate_ui("widget apres degel", timeout_s=5.0)
    assert not res.get("sature"), (
        "les slots ne reviennent pas apres la fin du travail : la borne se "
        "refermerait definitivement sur elle-meme"
    )


# ------------------------------------------------------------- structure


def _cree_un_executeur(source: str, fonction: str) -> bool:
    arbre = ast.parse(source)
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == fonction:
            for interne in ast.walk(noeud):
                if isinstance(interne, ast.Call):
                    cible = interne.func
                    nom = (cible.attr if isinstance(cible, ast.Attribute)
                           else getattr(cible, "id", ""))
                    if nom == "ThreadPoolExecutor":
                        return True
    return False


def test_plus_aucun_executeur_cree_dans_generate_ui():
    assert not _cree_un_executeur(SOURCE.read_text(encoding="utf-8"), "generate_ui"), (
        "un ThreadPoolExecutor cree PAR APPEL laisse un thread de fond sans "
        "borne a chaque timeout : c'est la fuite d'origine"
    )


def test_le_controle_de_l_executeur_sait_refuser():
    faux = ("def generate_ui(d):\n"
            "    _ex = ThreadPoolExecutor(max_workers=1)\n"
            "    return _ex\n")
    assert _cree_un_executeur(faux, "generate_ui"), (
        "le controle AST laisse passer un executeur cree par appel : il ne "
        "discrimine rien, et un test qui ne sait pas echouer ne prouve rien"
    )
