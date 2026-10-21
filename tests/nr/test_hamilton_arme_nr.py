# -*- coding: utf-8 -*-
"""NR -- l'executif Hamilton ARME pour la RAM (decision owner 19/10 : « Armer, DIFFERABLE seuls »).

113 observations hamilton_observe (dont 16 en pression SOI, « 36 a ceder, 29 epargnes ») : la serie est la, la
decision est prise. Arme = sous pression memoire portee par le corps (verdict SOI), ce n'est plus la liste figee
_SUPERVISOR_NON_ESSENTIAL qui s'endort, mais les DIFFERABLE du plan Hamilton -- du plus gros au plus petit, et
SEULEMENT jusqu'a couvrir la memoire a rendre (36 services d'un coup serait une seconde panne). UTILE en detresse
(plan_hamilton(detresse=True)), VITAL jamais (deja exclus du plan), vetos de sommeil respectes ; pause avant arret,
reprise apres calme durable (gestes_observes, decision owner 19/10). La regulation tourne a CHAQUE cycle : sans
cela la reprise n'arriverait jamais (le vieux chemin ne s'appelait qu'au-dessus de 78 %). La RAM passee est le
PLANCHER sur 60 s (aacbc6e2f : une garde RAM decide sur une fenetre, pas sur un instant).
Interrupteur NOKIDO_HAMILTON_ARME (defaut 1 ; 0 = ancien comportement, liste figee).
"""
import inspect
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as rm  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def _plan(verdict="SOI"):
    if verdict != "SOI":
        return {"verdict": verdict, "delester": [], "motif": "pression %s : signalee, jamais delestee" % verdict}
    return {"verdict": "SOI", "motif": "pression SOI", "delester": [
        {"service": "Gros", "classe": "DIFFERABLE", "rss_mb": 3000},
        {"service": "Moyen", "classe": "DIFFERABLE", "rss_mb": 2000},
        {"service": "Petit", "classe": "DIFFERABLE", "rss_mb": 500}]}


def _regler(plan, ram_pct, etat=None, t=1000.0, vetos=None):
    return rm.regulation_hamilton_ram(plan, ram_pct, 24.0, etat or {}, t, vetos=vetos or {},
                                      seuil_sommeil=78.0, cible=65.0)


def test_suspend_du_plus_gros_jusqu_a_couvrir_le_besoin():
    r = _regler(_plan(), 85.0)        # besoin = (85 - 65) % de 24 Go = 4,8 Go -> Gros (3) + Moyen (2)
    assert r["gestes"] == {"Gros": "SUSPENDRE", "Moyen": "SUSPENDRE"}
    assert "Petit" not in r["gestes"]


def test_hors_corps_rien_ne_s_endort():
    r = _regler(_plan("NON_SOI"), 92.0)
    assert r["gestes"] == {} and r["motif"]


def test_sous_le_seuil_rien_de_neuf_et_reprise_apres_calme():
    assert _regler(_plan(), 70.0)["gestes"] == {}
    pause = _regler(_plan(), 85.0)["etat"]
    r = _regler(_plan(), 70.0, etat=pause, t=1010.0)
    assert r["gestes"].get("Gros") == "MAINTENIR_PAUSE"
    r = _regler(_plan(), 70.0, etat=r["etat"], t=1010.0 + rm._HAMILTON_CALME_MIN_S + 1)
    assert r["gestes"].get("Gros") == "REPRENDRE"


def test_un_veto_de_sommeil_est_respecte():
    r = _regler(_plan(), 85.0, vetos={"Gros": "bail de priorite"})
    assert "Gros" not in r["gestes"] and r["gestes"].get("Moyen") == "SUSPENDRE"


def test_interrupteur_et_branchement(monkeypatch):
    monkeypatch.delenv("NOKIDO_HAMILTON_ARME", raising=False)
    assert rm._hamilton_arme() is True
    monkeypatch.setenv("NOKIDO_HAMILTON_ARME", "0")
    assert rm._hamilton_arme() is False
    src = inspect.getsource(rm._sampler_loop)
    assert "_regulation_hamilton_tick" in src and "_hamilton_arme()" in src


def test_le_tick_sans_registre_ne_donne_aucun_ordre(monkeypatch):
    ordres = []
    monkeypatch.setattr(rm, "_registre_corps", lambda: None)
    monkeypatch.setattr(rm, "_ordre_superviseur", lambda svc, geste: ordres.append((svc, geste)))
    r = rm._regulation_hamilton_tick()
    assert ordres == [] and r["gestes"] == {} and "ILLISIBLE" in r["motif"]
