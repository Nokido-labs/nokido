"""NR -- l'executeur consigne SEUL le verdict d'une delegation ratee, sans relecteur (owner 18/10 : « le corps doit
avoir la notion de recompense par resultat »).

Constitution : on classe par liste BLANCHE. Seul un vide PROUVE par le juge de livraison ([AUCUN EFFET],
[LIVRAISON VIDE], [ACCUSE DE RECEPTION], [artefact ABSENT]) devient VIDE ; une panne d'INFRASTRUCTURE (harness muet,
delai ACP, quota 429, session occupee) n'est pas la faute du repondeur : INCONNU, ni recompense ni punition. Un test
existant touche = REJETEE. Une reussite n'est jamais notee seule : INTEGREE/PARTIELLE exigent une relecture.
Mesure 19/10 : GPTOSS/NEMOTRON/GLM en echec depuis 18/10 22:21 sur des 429 et des sessions muettes -- les punir
aurait appris au planner que des modeles qui livraient la veille sont mauvais.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


def test_une_reussite_n_est_jamais_notee_seule():
    assert T.verdict_automatique(True, "commits produits : 2", "OK_DONE", None) is None


@pytest.mark.parametrize("detail", [
    "harness MUET apres 1680 s (NokidoHarnessWorker arrete ou occupe ?) -- job vibe_x",
    "erreur ACP OpenCode (TimeoutError): timeout en attente id=3",
    "erreur ACP OpenCode (RuntimeError): HTTP 429 Too Many Requests",
    "erreur ACP OpenCode (RuntimeError): 402 Payment Required",
])
def test_une_panne_d_infrastructure_est_inconnue(detail):
    effet = "commits produits : 0 ; [AUCUN EFFET] 0 commit et aucun pointer_ref verifiable"
    assert T.verdict_automatique(False, effet, detail, None) == "INCONNU"


@pytest.mark.parametrize("marque", ["[AUCUN EFFET] 0 commit", "[LIVRAISON VIDE] 1 fichier(s) committe(s)",
                                    "[ACCUSE DE RECEPTION] promesse sans compte rendu", "[artefact ABSENT] x.py"])
def test_un_vide_prouve_par_le_juge_est_vide(marque):
    assert T.verdict_automatique(False, "commits produits : 0 ; " + marque, "fini", None) == "VIDE"


def test_un_test_existant_touche_est_rejete():
    effet = "commits produits : 1 ; [TESTS TOUCHES] D tests/nr/test_a.py"
    assert T.verdict_automatique(False, effet, "fini", None) == "REJETEE"


def test_un_refus_honnete_n_est_pas_puni():
    assert T.verdict_automatique(False, "commits produits : 0", "...", "NEED_CLARIFY") == "INCONNU"


def test_un_echec_sans_marque_connue_reste_inconnu():
    """Liste blanche : une valeur inattendue ne tombe jamais dans VIDE par defaut."""
    assert T.verdict_automatique(False, "commits produits : 0 ; [QUELQUE CHOSE DE NEUF]", "?", None) == "INCONNU"


def test_le_rejet_du_scorecard_n_est_pas_consigne_deux_fois():
    detail = "fini\n[executeur] commit executeur REFUSE par le scorecard : IndentationError"
    assert T.verdict_automatique(False, "commits produits : 0 ; [AUCUN EFFET]", detail, None) is None


def _sans_tableau_noir(monkeypatch):
    """Le verdict emet aussi un transient (19/10) : jamais d'ecriture dans le vrai tableau noir depuis un test."""
    import nokido_agent.app.forge_swarm_blackboard as B
    monkeypatch.setattr(B, "apply_fact_sync", lambda *a, **k: {"ok": True})
    monkeypatch.setenv("NOKIDO_VERDICT_AUTO", "1")    # le conftest le coupe pour tous les autres tests


def test_consigner_appelle_la_motivation(monkeypatch):
    vus = []
    _sans_tableau_noir(monkeypatch)
    import nokido_agent.app.forge_motivation as M
    monkeypatch.setattr(M, "recompenser_resultat", lambda *a, **k: vus.append((a, k)))
    T._consigner_verdict_auto("OPENCODE_GPTOSS", "job_x", False, "[AUCUN EFFET]", "fini", None)
    assert vus and vus[0][0][:3] == ("OPENCODE_GPTOSS", "M:ecrit", "VIDE")


def test_consigner_ne_casse_jamais_l_executeur(monkeypatch):
    _sans_tableau_noir(monkeypatch)
    import nokido_agent.app.forge_motivation as M

    def boom(*a, **k):
        raise OSError("registre illisible")
    monkeypatch.setattr(M, "recompenser_resultat", boom)
    T._consigner_verdict_auto("OPENCODE_GPTOSS", "job_x", False, "[AUCUN EFFET]", "fini", None)
