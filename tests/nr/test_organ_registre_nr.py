# -*- coding: utf-8 -*-
"""Tests NR — le registre d'organes ne doit mentir dans AUCUN des deux sens.

Mesure du 2026-08-21 : forge_organ_agents a declare `cortisol_to_throttle`
« a cabler » pendant trois semaines APRES son cablage du 29/07, a quatre
endroits. Une analyse externe a lu le registre, l'a cru, et a recommande de
passer en P0 un travail deja fait -- dans la forme (veto) precisement mesuree
comme nuisible. Le module annoncait pourtant le risque lui-meme :
« une carte declarative vieillit sans prevenir ».

D'ou un cliquet BIDIRECTIONNEL :
  - un cablage DONE dont la sonde ne mord plus  -> REGRESSION ;
  - un cablage a faire dont la sonde mord       -> registre PERIME.

Un registre qu'aucun test ne confronte au code redevient une intention.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_organ_agents as oa  # noqa: E402


def _wirings():
    return {n: p for p, n, _w in oa.ESSENTIAL_WIRINGS}


# ── le registre confronte au code ───────────────────────────────────────────


def test_toute_sonde_declaree_pointe_un_fichier_existant():
    """Une sonde qui vise un fichier disparu ne mesure plus rien et se tait."""
    for name in oa.WIRING_PROBES:
        r = oa.probe(name)
        assert r["etat"] != "fichier_absent", (
            f"sonde {name} -> fichier introuvable ({r.get('file')})"
        )


def test_un_cablage_done_doit_etre_prouvable_dans_le_code():
    """Sens 1 : declarer fait ce qui a disparu du code est une regression."""
    for name, prio in _wirings().items():
        if prio != "DONE" or name not in oa.WIRING_PROBES:
            continue
        r = oa.probe(name)
        assert r["etat"] == "present", (
            f"{name} est declare DONE mais sa sonde ne mord plus ({r}). "
            "Soit le cablage a saute, soit la sonde vise le mauvais endroit."
        )


def test_un_cablage_a_faire_ne_doit_pas_deja_exister():
    """Sens 2 : le defaut exact du 21/08. Un registre perime envoie refaire
    un travail fait -- et parfois le refaire MAL."""
    perimes = []
    for name, prio in _wirings().items():
        if prio == "DONE" or name not in oa.WIRING_PROBES:
            continue
        if oa.probe(name)["etat"] == "present":
            perimes.append(name)
    assert not perimes, (
        f"registre perime : {perimes} sont declares a faire mais leur sonde mord deja. "
        "Passer la fiche en DONE avec la date et la mesure."
    )


def test_aucune_famille_ne_reclame_un_cablage_deja_marque_done():
    """ORGAN_MAP et ESSENTIAL_WIRINGS sont deux vues du meme etat : elles ne
    doivent pas se contredire. C'est par cette contradiction que le registre
    a menti quatre fois sur cortisol_to_throttle."""
    faits = {n for p, n, _w in oa.ESSENTIAL_WIRINGS if p == "DONE"}
    contradictions = []
    for fam, _organs, _role, _tier, _statut, wiring in oa.ORGAN_MAP:
        texte = (wiring or "").lower()
        for nom in faits:
            cle = nom.replace("_", " ").split()[0]
            if cle in texte and "câbler" in texte:
                contradictions.append((fam, nom))
    assert not contradictions, (
        f"familles reclamant un cablage deja DONE : {contradictions}"
    )


def test_probe_distingue_absent_et_sans_sonde():
    """« Pas mesurable » n'est pas « pas la » : trois etats, jamais deux."""
    assert oa.probe("nom_qui_n_existe_pas")["etat"] == "sans_sonde"
    assert oa.probe("cortisol_to_throttle")["etat"] in ("present", "absent")


# ── la regression que la revue du 21/08 recommandait ────────────────────────


def _forcer_cortisol(monkeypatch, niveau: float) -> None:
    """Impose un niveau de cortisol ET VERIFIE que should_throttle le voit.

    tests/conftest.py redirige `forge_endocrine.DB` vers une base temp VIDE
    (fixture autouse `_isolate_endocrine_blood`). Un mock qui ne mordrait pas
    laisserait donc lire 0.0 partout -- et un test « cortisol eleve -> pas de
    veto » passerait alors qu'aucun cortisol n'a jamais ete lu : vert pour la
    mauvaise raison. On controle le mock avant de s'en servir.
    """
    import forge_endocrine

    monkeypatch.setattr(
        forge_endocrine, "read",
        lambda h, *a, **k: niveau if str(h).startswith("CORTISOL") else 0.0,
    )
    from forge_endocrine import read as _lu

    assert _lu("CORTISOL_FRUSTRATION") == pytest.approx(niveau), (
        "le mock endocrinien n'est pas vu : le test ne mesurerait rien"
    )


def test_le_cortisol_module_les_seuils_mais_n_oppose_pas_de_veto(monkeypatch):
    """Regression du 2026-07-29, a ne JAMAIS refaire.

    Rendu en veto, le cortisol avait refuse 471 spawns a RAM 60 %/CPU 6 %, puis
    382 a RAM 37,8 % apres avoir survecu au restart. Le frein empechait la
    guerison au lieu de proteger : les organes manquants etaient precisement
    ceux qu'il refusait.
    """
    import forge_resource_manager as rm

    sain = {"ram_pct": 40.0, "cpu_pct": 10.0, "gpu_pct": 5.0,
            "disk_pct": 50.0, "tdr_recent": 0}
    monkeypatch.setattr(rm, "get_snapshot", lambda *a, **k: dict(sain))
    _forcer_cortisol(monkeypatch, 0.99)

    assert rm.should_throttle() is False, (
        "cortisol a 0.99 sur un corps SAIN doit moduler, pas paralyser"
    )


def test_sous_cortisol_le_frein_mord_plus_tot(monkeypatch):
    """L'autre moitie de la meme regle : si le cortisol ne changeait RIEN, le
    cablage serait decoratif. Il doit durcir les seuils, donc freiner plus tot."""
    import os

    import forge_resource_manager as rm

    tighten = float(getattr(rm, "CORTISOL_TIGHTEN_PTS", 10.0))
    # Le seuil vient de LAFORGE_RAM_THRESHOLD quand il est pose, sinon du defaut
    # de la signature. Le coder en dur (85) faisait echouer ce test sous pytest :
    # tests/conftest.py charge le .env, qui pose une autre valeur. Un test doit
    # lire le seuil A LA MEME SOURCE que le code, sinon il mesure une constante
    # imaginaire (meme famille que le 46-tests-en-401 du 20/08).
    import inspect

    nominal = float(os.environ.get(
        "LAFORGE_RAM_THRESHOLD",
        inspect.signature(rm.should_throttle).parameters["ram_pct_threshold"].default,
    ))
    # RAM juste SOUS le seuil nominal, mais au-dessus du seuil durci.
    ram = nominal - (tighten / 2.0)
    etat = {"ram_pct": ram, "cpu_pct": 10.0, "gpu_pct": 5.0,
            "disk_pct": 50.0, "tdr_recent": 0}
    monkeypatch.setattr(rm, "get_snapshot", lambda *a, **k: dict(etat))

    _forcer_cortisol(monkeypatch, 0.0)
    calme = rm.should_throttle()
    _forcer_cortisol(monkeypatch, 0.99)
    stresse = rm.should_throttle()

    assert calme is False, (
        f"a RAM {ram:.1f} % (seuil nominal {nominal}) sans stress, pas de frein attendu"
    )
    assert stresse is True, (
        f"a RAM {ram:.1f} % sous cortisol, le seuil nominal {nominal} durci de "
        f"{tighten} pts doit freiner"
    )


def test_un_corps_reellement_sature_freine_sans_avoir_besoin_d_hormone(monkeypatch):
    """Le frein ressource ne depend pas de l'endocrinien : une glande muette ne
    doit pas desarmer la protection."""
    import forge_endocrine
    import forge_resource_manager as rm

    monkeypatch.setattr(rm, "get_snapshot", lambda *a, **k: {
        "ram_pct": 99.0, "cpu_pct": 10.0, "gpu_pct": 5.0,
        "disk_pct": 50.0, "tdr_recent": 0})
    monkeypatch.setattr(forge_endocrine, "read", lambda h, *a, **k: 0.0)
    assert rm.should_throttle() is True


def test_endocrinien_en_panne_ne_bloque_pas_le_frein(monkeypatch):
    """Fail-safe : si forge_endocrine leve, should_throttle doit continuer sur
    les seuils ressources au lieu de propager l'erreur."""
    import forge_endocrine
    import forge_resource_manager as rm

    def _boom(*a, **k):
        raise RuntimeError("endocrinien injoignable")

    monkeypatch.setattr(forge_endocrine, "read", _boom)
    monkeypatch.setattr(rm, "get_snapshot", lambda *a, **k: {
        "ram_pct": 99.0, "cpu_pct": 10.0, "gpu_pct": 5.0,
        "disk_pct": 50.0, "tdr_recent": 0})
    assert rm.should_throttle() is True
