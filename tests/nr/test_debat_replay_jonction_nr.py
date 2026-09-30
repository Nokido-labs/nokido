# -*- coding: utf-8 -*-
"""NR — le moteur de debat alimente REELLEMENT l'etat rejouable.

MESURE DU 2026-09-05. `forge_debate_job` produisait un transcript et une synthese, et
rien n'alimentait `forge_m2m_debate_antiregression`, seul substrat capable de rejouer.
La capacite `deliberation.replay` etait pourtant publiee dans la carte A2A : elle ne
couvrait donc AUCUN debat reel. Mecanisme present, non cable — la forme de defaut que
ce corps paie le plus souvent.

CE QUE CE GARDE TIENT, dans l'ordre d'importance :
  1. la jonction EXISTE encore (verification statique — un raccord retire en silence
     rendrait tout le reste vert pour rien) ;
  2. un tour MUET reste au journal : ne pas alimenter le replay depuis les seules
     reponses non vides, sinon le silence d'un agent devient invisible ;
  3. rejouer le meme flux rend le MEME etat, identifiants compris ;
  4. la filiation traverse les tours (`supersedes`).

HERMETIQUE : aucun appel LLM, aucun reseau. On rejoue a la main la sequence d'appels
que `run_debate` effectue, et on lit sa SOURCE pour la verification statique.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

SRC = ROOT / "tools" / "forge_debate_job.py"


def _delta():
    try:
        from forge_m2m_debate_antiregression import _applique_delta
    except Exception as exc:  # noqa: BLE001
        pytest.skip("primitive de delta indisponible : %s" % exc)
    return _applique_delta


# Ce que produit un debat : deux agents, un tour muet au milieu, une revision.
FLUX = [
    (1, "AGY", "AXE: cablage_snn | candidat | le signal manque"),
    (1, "CLAUDE", ""),                                   # tour MUET
    (2, "CLAUDE", "AXE: cablage_snn | rejete | baseline if non battue"),
    (2, "AGY", "TENSION: desaccord sur la mesure"),
]


def _rejouer(flux):
    d = _delta()
    etat = {"tour": 0, "axes": {}, "tensions": [], "acquis": []}
    for tour, qui, texte in flux:
        etat["tour"] = tour
        d(etat, qui, texte)
    return etat


def test_le_moteur_de_debat_alimente_reellement_l_etat():
    """VERIFICATION STATIQUE. Sans elle, ce fichier testerait la primitive seule.

    Les DEUX chemins de tour doivent tracer : le relais latent local et le tour
    cloud. Un seul cable, et la moitie des debats disparaitrait du rejeu.
    """
    src = SRC.read_text(encoding="utf-8", errors="replace")
    assert "_applique_delta" in src, "la jonction vers la primitive a disparu"
    assert '"deliberation": etat_rejouable' in src, (
        "l'etat rejouable n'est plus expose dans le resultat du debat")
    # une trace apres CHAQUE ajout au transcript
    ajouts = len(re.findall(r"transcript\.append\(", src))
    traces = len(re.findall(r"_tracer\(", src))
    assert ajouts >= 2, "les chemins de tour ont change, ce garde doit etre relu"
    assert traces >= ajouts, (
        "%d ajout(s) au transcript pour %d trace(s) : un chemin de tour n'alimente "
        "plus le rejeu" % (ajouts, traces))


def test_un_tour_muet_reste_au_journal():
    """L'invariant qui interdit d'alimenter le replay depuis les seules reponses."""
    etat = _rejouer(FLUX)
    journal = etat.get("journal") or []
    assert len(journal) == len(FLUX), (
        "%d entree(s) au journal pour %d tours : un silence a ete perdu"
        % (len(journal), len(FLUX)))
    muet = [e for e in journal if e["qui"] == "CLAUDE" and not e["texte"]]
    assert muet, "le tour muet n'est pas journalise"


def test_le_rejeu_du_meme_flux_rend_le_meme_etat():
    a, b = _rejouer(FLUX), _rejouer(FLUX)
    assert a == b, "le rejeu n'est pas deterministe"
    ids = [p["id"] for p in a.get("positions", [])]
    assert ids == sorted(set(ids), key=ids.index), "identifiants instables ou dupliques"


def test_la_filiation_traverse_les_tours():
    etat = _rejouer(FLUX)
    positions = [p for p in etat.get("positions", []) if p["axe"] == "cablage_snn"]
    assert len(positions) == 2, positions
    assert positions[1]["supersedes"] == positions[0]["id"], (
        "la revision ne reference pas la position qu'elle remplace")
    assert positions[0]["statut"] == "candidat", "l'antecedent a ete altere"


def test_la_sonde_ne_peut_pas_faire_echouer_le_debat():
    """Invariant transverse : une trace qui casse ne doit pas tuer son porteur."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    bloc = src[src.find("def _tracer"):src.find("for rnd in range")]
    assert "except Exception" in bloc and "pass" in bloc, (
        "la sonde de trace n'est plus protegee : un debat pourrait echouer a cause "
        "de son journal")
