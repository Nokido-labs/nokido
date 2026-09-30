# -*- coding: utf-8 -*-
"""Non-regression — prendre le pouls ne doit pas fatiguer le patient.

Mesure 2026-08-26 : `all_vitals()` recalcule 14 signaux et coute de 5 a 50 s selon la
charge (`parietal_percept` en represente l'essentiel, via `forge_organ_pulse` et
`get_anatomy_state`). Or `/api/vitals/sse` le redemandait **toutes les 5 secondes**, et
une fois **par client** : ce flux alimente le fond ambiant du Design System, donc il
s'ouvre des qu'une page est affichee. Sans cache, N pages ouvertes = N recalculs.

Deux exigences opposees, et c'est leur tension qui est verrouillee ici :
  1. servir vite (ne pas refaire le travail pour chaque demandeur) ;
  2. ne JAMAIS faire passer un vieux snapshot pour une mesure de maintenant — d'ou
     `age_s`, rendu a chaque appel. Un cache muet est un cache qui ment.

Hermetique : `VITAL_SIGNALS` est remplace par des compteurs en memoire ; aucun service
n'est sollicite, aucun chiffre de la machine reelle n'intervient.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

V = pytest.importorskip("forge_vitals_tools")


@pytest.fixture
def signaux_stub(monkeypatch):
    """Remplace les signaux reels par un compteur d'appels."""
    appels = {"n": 0}

    def _signal():
        appels["n"] += 1
        return {"valeur": appels["n"]}

    monkeypatch.setattr(V, "VITAL_SIGNALS", {"stub": _signal}, raising=True)
    monkeypatch.setattr(V, "_cache", {"ts": 0.0, "valeur": None}, raising=True)
    return appels


def test_premier_appel_calcule(signaux_stub):
    out = V.all_vitals()
    assert signaux_stub["n"] == 1
    assert out["stub"]["valeur"] == 1


def test_deuxieme_appel_ne_recalcule_pas(signaux_stub):
    """LE test : c'est ce qui evite N recalculs pour N clients."""
    V.all_vitals()
    V.all_vitals()
    assert signaux_stub["n"] == 1, "le second appel a recalcule malgre le cache"


def test_frais_force_le_recalcul(signaux_stub):
    V.all_vitals()
    out = V.all_vitals(frais=True)
    assert signaux_stub["n"] == 2
    assert out["stub"]["valeur"] == 2


def test_age_est_rendu_et_croit(signaux_stub):
    """Un cache muet ferait passer une mesure d'il y a 5 s pour une mesure de maintenant."""
    premier = V.all_vitals()
    assert premier["age_s"] == 0.0, "un calcul frais a un age nul"
    time.sleep(0.05)
    second = V.all_vitals()
    assert second["age_s"] > 0.0, "le snapshot servi depuis le cache doit dire son age"
    assert signaux_stub["n"] == 1


def test_expiration_recalcule(signaux_stub, monkeypatch):
    """TTL depasse : on refait le travail plutot que servir un etat perime."""
    monkeypatch.setattr(V, "_CACHE_TTL_S", 0.05, raising=True)
    V.all_vitals()
    time.sleep(0.08)
    V.all_vitals()
    assert signaux_stub["n"] == 2


def test_le_cache_ne_renvoie_pas_l_objet_interne(signaux_stub):
    """Muter la reponse ne doit pas corrompre le cache du prochain demandeur."""
    a = V.all_vitals()
    a["stub"] = "MUTE"
    a["age_s"] = 999
    b = V.all_vitals()
    assert b["stub"] != "MUTE" and b["age_s"] != 999


def test_les_cles_des_signaux_sont_preservees(signaux_stub):
    out = V.all_vitals()
    assert "stub" in out and "age_s" in out


def test_le_flux_sse_ne_bloque_plus_la_boucle():
    """Garde d'alignement : `all_vitals` est synchrone, donc le generateur SSE doit le
    deporter. Appele directement, il gelait le serveur ENTIER a chaque tour."""
    app_py = ROOT / "app" / "web_hub" / "app.py"
    if not app_py.exists():
        pytest.skip("app.py absent de cette copie")
    src = app_py.read_text(encoding="utf-8", errors="replace")
    i = src.find("async def vitals_sse")
    if i < 0:
        pytest.skip("route vitals_sse absente")
    # La fin de la fonction, pas une fenetre FIXE. A 2500 caracteres, ce garde a crie
    # a faux le 2026-08-29 : borner les flux SSE a ajoute 1219 octets en tete et
    # repousse l'appel a 3076 chars, alors qu'il etait toujours la et au bon endroit.
    # Un garde qui crie a faux se fait desarmer — on le borne sur la structure.
    fin = src.find("@app.get(", i + 10)
    bloc = src[i:fin] if fin > i else src[i:]
    assert "asyncio.to_thread(all_vitals)" in bloc, (
        "all_vitals() appele directement dans le generateur SSE : il s'executerait "
        "dans la boucle d'evenements et gelerait tout le serveur")
