"""Non-regression : le routeur en SHADOW ne peut PAS modifier le ranking.

MANDAT OWNER 2026-09-01. Le verrou de la baseline porte sur les CONCLUSIONS et sur
l'ACTIVATION, pas sur le developpement : le routeur peut donc etre construit, instrumente
et teste, a condition d'etre inerte. La condition posee est verifiee ici :

    routeur en SHADOW  =>  ordre et scores finaux STRICTEMENT identiques a l'actuel

On le prouve par IDENTITE D'OBJET (`is`), pas par egalite de valeurs : une copie egale
laisserait passer une modification ulterieure du dict, l'identite non. Et le test 3
verifie qu'en ACTIVE le resultat DIFFERE -- sans quoi l'equivalence serait vraie
trivialement, pour la mauvaise raison (un mecanisme mort passe tous les tests d'inertie).

Les fixtures ci-dessous testent la MECANIQUE (le routeur reagit-il aux signaux ?), JAMAIS
la qualite. Aucune ne vaut benchmark : la qualite se mesure contre la baseline reelle,
qui n'existe pas encore. Les melanger fabriquerait un verdict.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.125)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app",):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_retrieval_router as rr  # noqa: E402


@pytest.fixture(autouse=True)
def _shadow_par_defaut(monkeypatch):
    monkeypatch.delenv("LAFORGE_ROUTER_MODE", raising=False)


def test_shadow_est_le_defaut():
    """L'activation est une DONNEE explicite, jamais un etat par defaut."""
    assert rr.mode() == rr.SHADOW


def test_en_shadow_la_fusion_rend_l_objet_D_ENTREE(monkeypatch):
    """Identite d'objet : aucune modification du ranking n'est possible."""
    combined = {0: 0.9, 1: 0.4, 2: 0.1}
    d = rr.decider("forge_tier_guard", {"vector": "AVAILABLE"})
    rangs = {0: (1, 5), 1: (2, 1), 2: (9, 9)}

    sortie = rr.fusionner(combined, d, rangs)

    assert sortie is combined, "le routeur SHADOW a produit un autre objet"
    assert combined == {0: 0.9, 1: 0.4, 2: 0.1}, "l'entree a ete mutee"


def test_en_active_la_fusion_change_bien_le_resultat(monkeypatch):
    """Sans ce test, l'inertie du SHADOW serait vraie pour la mauvaise raison."""
    monkeypatch.setenv("LAFORGE_ROUTER_MODE", "ACTIVE")
    combined = {0: 0.9, 1: 0.4}
    d = rr.decider("comment eviter les regressions", {"vector": "AVAILABLE",
                                                     "structure_branche": True})
    assert d.mode == rr.ACTIVE

    sortie = rr.fusionner(combined, d, {0: (10, 1), 1: (1, 10)})

    assert sortie is not combined
    assert sortie != combined, "le mode ACTIVE n'a rien change : mecanisme mort"


def test_bascule_sans_changement_architectural(monkeypatch):
    """Meme appel, meme signature : seule la DONNEE de mode change."""
    combined, rangs = {0: 0.5}, {0: (1, 1)}
    d_shadow = rr.decider("app/forge_rag_engine.py")
    monkeypatch.setenv("LAFORGE_ROUTER_MODE", "ACTIVE")
    d_active = rr.decider("app/forge_rag_engine.py")

    assert rr.fusionner(combined, d_shadow, rangs) is combined
    assert rr.fusionner(combined, d_active, rangs) is not combined


def test_requete_identifiant_donne_un_profil_lexical_dominant():
    d = rr.decider("forge_tier_guard", {"vector": "AVAILABLE", "structure_branche": True})
    assert d.profil == "exact"
    assert d.lexical_weight > d.vector_weight
    assert d.reason


def test_requete_conceptuelle_donne_un_profil_vectoriel_dominant():
    d = rr.decider("comment eviter les regressions dans un systeme autonome",
                   {"vector": "AVAILABLE", "structure_branche": True})
    assert d.profil == "conceptuel"
    assert d.vector_weight > d.lexical_weight


def test_vecteur_indisponible_est_REPORTE_et_non_penalise():
    """PENDING veut dire « pas pu voir », jamais « pas pertinent ».

    Penaliser sur cette base condamnerait un chunk pour un signal que la politique lui
    interdit d'avoir -- 626 646 chunks sont dans ce cas (mesure 2026-09-01).
    """
    dispo = rr.decider("comment eviter les regressions dans un systeme autonome",
                       {"vector": "AVAILABLE", "structure_branche": True})
    absent = rr.decider("comment eviter les regressions dans un systeme autonome",
                        {"vector": "PENDING", "structure_branche": True})

    assert absent.vector_weight == 0.0
    assert absent.lexical_weight > dispo.lexical_weight, "le poids n'a pas ete reporte"
    somme_d = dispo.lexical_weight + dispo.vector_weight + dispo.structure_weight
    somme_a = absent.lexical_weight + absent.vector_weight + absent.structure_weight
    assert abs(somme_d - somme_a) < 1e-6, "la masse totale a ete PERDUE, donc penalisee"
    assert "reporte" in absent.reason


def test_le_canal_structurel_non_branche_est_reporte_et_dit():
    """`forge_graph_rag_hops` existe mais n'est branche nulle part dans le moteur."""
    d = rr.decider("forge_tier_guard", {"vector": "AVAILABLE"})
    assert d.structure_weight == 0.0
    assert "structurel non branche" in d.reason


def test_le_journal_ne_transforme_jamais_un_signal_absent_en_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "_JOURNAL", tmp_path / "obs.jsonl")
    d = rr.decider("forge_tier_guard", {"vector": "PENDING"})

    rr.observer("q1", "forge_tier_guard", d, [{"chunk_id": "c1", "rank": 1,
                                               "final_score": 0.8}])

    import json

    ligne = json.loads((tmp_path / "obs.jsonl").read_text(encoding="utf-8").strip())
    r0 = ligne["resultats"][0]
    assert r0["lexical_score"] == "NOT_OBSERVABLE"
    assert r0["vector_score"] == "NOT_OBSERVABLE"
    assert r0["structure_score"] == "NOT_OBSERVABLE"
    assert ligne["mode"] == rr.SHADOW


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
