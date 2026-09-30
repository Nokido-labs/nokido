# -*- coding: utf-8 -*-
"""Non-regression — le flux SSE des vitaux reste BORNE.

Mesure 2026-08-29 : le webhub :7400 cessait de repondre apres quelques parcours de
l'interface — LISTENING intact, `/health` qui expire, sockets empilees en
CLOSE_WAIT (5 apres une passe, 21 apres trois).

Ce n'etait PAS un gel de boucle : `forge_loop_sentinel`, armee cote webhub le meme
jour, n'a rien capte pendant que le service etait mort. La boucle tournait ; les
GENERATEURS ne finissaient pas. `/api/vitals/sse` testait la deconnexion APRES un
`all_vitals` de 5 a 50 s passe en `to_thread` : un onglet ferme pendant le calcul
n'etait vu qu'au tour suivant, et le calcul tenait un worker du pool (borne a
min(32, cpu+4)) POUR PERSONNE.

Preuve du remede : les TROIS campagnes UI qui tuaient le service passent
desormais (104-110 s chacune, toutes VERTES) et laissent `health=200 en 108 ms`
avec ZERO CLOSE_WAIT.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

M = pytest.importorskip("forge_patch_vitals_sse")


def test_le_garde_est_present_dans_la_cible():
    """LE test : sans ces lignes dans app.py, rien ne borne les flux."""
    src = M.CIBLE.read_text(encoding="utf-8")
    assert "BORNE DES FLUX SIMULTANES (2026-08-29)" in src, (
        "patch non applique : le flux SSE peut de nouveau saturer le pool")


def test_la_deconnexion_est_testee_AVANT_le_calcul():
    """L'ordre EST le correctif. Testee apres `to_thread`, elle arrive trop tard :
    le worker est deja pris pour un client parti."""
    src = M.CIBLE.read_text(encoding="utf-8")
    debut = src.index("BORNE DES FLUX SIMULTANES (2026-08-29)")
    extrait = src[debut:debut + 3200]
    pos_test = extrait.find("is_disconnected")
    pos_calcul = extrait.find("to_thread(all_vitals)")
    assert pos_test != -1 and pos_calcul != -1, extrait[:200]
    assert pos_test < pos_calcul, (
        "le test de deconnexion doit preceder le calcul couteux")


def test_la_cible_compile_apres_patch():
    compile(M.CIBLE.read_text(encoding="utf-8"), str(M.CIBLE), "exec")


def test_rejouer_le_patch_est_sans_effet():
    r = M.applique(dry_run=True)
    assert r["ok"] and r.get("deja_applique") and not r["modifie"]


def test_la_borne_est_reglable_et_a_un_defaut():
    src = M.CIBLE.read_text(encoding="utf-8")
    assert "LAFORGE_VITALS_SSE_MAX" in src, "borne non reglable"
    assert '"8"' in src, "borne sans defaut : un reglage absent vaudrait zero ou l'infini"


def test_la_saturation_se_DIT_au_client():
    """Une borne muette se decouvre au silence. Le flux refuse doit le nommer."""
    src = M.CIBLE.read_text(encoding="utf-8")
    assert '"type": "sature"' in src or "'type': 'sature'" in src, (
        "le flux refuse doit annoncer la saturation, pas se taire")


def test_ancre_absente_refuse_de_patcher(tmp_path, monkeypatch):
    faux = tmp_path / "sans_ancre.py"
    faux.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(M, "CIBLE", faux)
    r = M.applique(dry_run=False)
    assert not r["ok"] and "ancre" in r["raison"]
    assert faux.read_text(encoding="utf-8") == "x = 1\n", "rien ne doit etre ecrit"


def test_cible_illisible_ne_conclut_pas(tmp_path, monkeypatch):
    """Illisible n'est pas « deja applique » : trois etats, jamais deux."""
    monkeypatch.setattr(M, "CIBLE", tmp_path / "jamais_ecrit.py")
    r = M.applique(dry_run=True)
    assert not r["ok"] and "illisible" in r["raison"]
