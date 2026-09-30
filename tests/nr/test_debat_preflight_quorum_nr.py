# -*- coding: utf-8 -*-
"""NR — un debat ne produit une synthese que s'il a vraiment eu lieu.

TROIS ECHECS INDEPENDANTS, mesures le 2026-09-05 sur un SEUL run. Chacun suffit a
vider un debat, et aucun n'etait visible dans le resultat : la synthese sortait quand
meme, batie sur un avis unique.

  1. DISPONIBILITE — 2 des 3 participants du panel FIGE rendaient une reponse vide.
     `gemini_cli` et `sambanova` ne figurent meme pas dans `provider_scores` : leur
     etat n'etait pas « down », il etait NON MESURE.
  2. PERTINENCE — les roles de `DEFAULT_PARTICIPANTS` portaient encore le cadrage d'un
     debat de juin (cristallisation transient, Ring 4). Un cadrage metier fige survit a
     l'objectif qu'il servait et rend une sortie techniquement valide mais
     EPISTEMIQUEMENT hors sujet, meme avec des providers parfaitement sains.
  3. STRUCTURE — le seul agent qui a repondu n'a produit aucune ligne `AXE:`.
     RESPONDED = 1, STRUCTURED = 0.

L'invariant qui les chapeaute : **un provider disponible n'est pas un participant
eligible, et un participant qui a repondu n'est pas un contributeur structure.**
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_debate_job as D  # noqa: E402


def _sans_rag(monkeypatch):
    monkeypatch.setattr(D, "_rag_context", lambda *a, **k: "(contexte neutralise)")


# ── 1. DISPONIBILITE ─────────────────────────────────────────────────────────

def test_une_mesure_absente_ou_illisible_ne_rend_jamais_eligible():
    """Trois etats, jamais deux : ELIGIBLE exige une mesure `ok` ET fraiche."""
    assert D._age_mesure("pas une date") is None
    assert D._age_mesure("") is None
    assert D._age_mesure(None) is None

    pf = D.preflight_providers()
    if not pf["lisible"]:
        pytest.skip("provider_scores illisible (%s) — on ne conclut pas d'une source "
                    "qui se tait" % pf["raison"])
    for d in pf["detail"]:
        if d["etat"] == "ELIGIBLE":
            assert d["statut"] == "ok", d
            assert d["age_s"] is not None and d["age_s"] <= D.FRAICHEUR_MAX_S, d
        else:
            assert d["motif"], ("un provider ecarte doit dire POURQUOI, sinon il est "
                                "exclu en silence : %s" % d)


def test_le_quorum_bloque_AVANT_de_bruler_du_quota(monkeypatch):
    """Decouvrir en plein debat qu'on est seul coute des appels payants pour rien."""
    _sans_rag(monkeypatch)
    monkeypatch.setattr(D, "panel_pour", lambda obj, **k: ([], {"lisible": True}))

    async def _interdit(*a, **k):
        raise AssertionError("aucun appel provider ne doit avoir lieu sous quorum")

    monkeypatch.setattr(D, "_turn", _interdit)
    r = asyncio.run(D.run_debate("objectif", "contrainte", None, 1))
    assert r["verdict"] == "NEEDS_MEASUREMENT", r
    assert r["transcript"] == [] and r["synthesis"] is None
    assert "quorum d'eligibles" in r["verdict_motif"]


# ── 2. PERTINENCE ────────────────────────────────────────────────────────────

def test_le_role_ne_porte_plus_un_cadrage_metier_fige():
    """Anti-regression du cadrage de juin ressorti dans un debat de septembre."""
    fossiles = ("cristallisation", "transient", "ring 4", "blackboard")
    for _nom, role in D._ROLES:
        bas = role.lower()
        for f in fossiles:
            assert f not in bas, (
                "le role porte un cadrage metier fige (%r) : il survivra a l'objectif "
                "qu'il servait et produira du hors-sujet" % f)
        assert "objectif" in bas, (
            "le role ne renvoie pas a l'objectif courant : %r" % role)


# ── 3. STRUCTURE ─────────────────────────────────────────────────────────────

def test_pas_de_synthese_quand_personne_ne_prend_position(monkeypatch):
    """RESPONDED n'est pas STRUCTURED : sans ligne AXE:, rien a synthetiser."""
    _sans_rag(monkeypatch)

    async def _poli(provider, prompt, **k):
        return ("Je suis d'accord avec tout le monde, sans prendre position.", True)

    monkeypatch.setattr(D, "_turn", _poli)
    parts = [("A", "p1", "role A"), ("B", "p2", "role B")]
    r = asyncio.run(D.run_debate("objectif", "contrainte", parts, 1))
    assert r["n_repondus"] == 2, r
    assert r["n_structures"] == 0, r
    assert r["synthesis"] is None, "une synthese a ete produite sans aucune position"
    assert r["verdict"] == "NEEDS_MEASUREMENT"


def test_la_synthese_revient_des_que_deux_positions_existent(monkeypatch):
    """Le test MIROIR : un garde qui bloque tout ne discrimine plus rien."""
    _sans_rag(monkeypatch)

    async def _structure(provider, prompt, **k):
        if "SECRÉTAIRE" in prompt or "SECRETAIRE" in prompt:
            return ("CONSENSUS: ok", True)
        return ("AXE: cablage | candidat | mesure a l'appui", True)

    monkeypatch.setattr(D, "_turn", _structure)
    parts = [("A", "p1", "role A"), ("B", "p2", "role B")]
    r = asyncio.run(D.run_debate("objectif", "contrainte", parts, 1))
    assert r["n_structures"] == 2, r
    assert r["verdict"] == "ADOPTE" and r["synthesis"], r
    # la filiation doit avoir suivi : deux positions sur le meme axe
    pos = (r.get("deliberation") or {}).get("positions") or []
    assert len(pos) == 2 and pos[1]["supersedes"] == pos[0]["id"], pos
