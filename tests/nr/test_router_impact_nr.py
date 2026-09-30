"""Non-regression : le journal SHADOW sait dire s'il peut repondre a sa question.

CONTRAT (ce NR est ecrit ROUGE, avant l'outil, et le specifie entierement).

Le routeur accumule des observations depuis le 2026-09-01 pour qu'a l'ouverture de
la fenetre nominale la calibration parte de mesures et non de zero. Le point de
bascule est desormais soude (cf. `test_bascule_routeur_soudee_nr`) : activer le
routeur est devenu un geste qui MORD. Avant de le poser, il faut savoir ce que le
journal contient VRAIMENT -- et non supposer qu'il contient ce qu'on esperait.

L'outil `tools/forge_router_impact.py` repond a UNE question, et pas a une autre :

    combien d'observations sont REJOUABLES, c'est-a-dire portent, pour chacun de
    leurs resultats, un signal numerique sur les DEUX canaux ?

Il ne mesure PAS la qualite du retrieval : cela demande une verite terrain, qui
n'existe pas dans ce depot (cf. C1-C4 de la roadmap de veille). Confondre les deux
fabriquerait un verdict. Il mesure la REJOUABILITE, c'est-a-dire la condition
prealable a toute mesure de qualite.

INVARIANTS EXIGES, chacun paye ailleurs dans ce depot :
  - le DENOMINATEUR est imprime : total = rejouables + non_rejouables + illisibles.
    Sans lui, "0 rejouable" ne se distingue pas de "je n'ai pas pu regarder".
  - une ligne ILLISIBLE est COMPTEE et NOMMEE, jamais avalee par un `except`.
  - un taux sur un corpus VIDE rend None, jamais 0.0 : l'absence de donnee n'est
    pas un taux nul.
  - chaque refus de rejouabilite porte son MOTIF, en clair.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "tools", RACINE / "app"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

fri = pytest.importorskip(
    "forge_router_impact",
    reason="tools/forge_router_impact.py pas encore ecrit -- ce NR est son CONTRAT")


def _ligne(resultats, **extra):
    base = {"schema": 1, "kind": "OBSERVATION_REELLE", "mode": "shadow",
            "query_id": "q", "query": "essai", "resultats": resultats}
    base.update(extra)
    return base


def test_une_observation_complete_est_rejouable():
    ok, motif = fri.rejouabilite(_ligne([
        {"chunk_id": "c1", "rank": 1, "lexical_score": 12.0, "vector_score": 0.91},
        {"chunk_id": "c2", "rank": 2, "lexical_score": 0.0, "vector_score": 0.10},
    ]))
    assert ok is True, f"declaree non rejouable a tort : {motif}"
    assert motif == "", "une ligne rejouable ne porte pas de motif de refus"


def test_un_zero_MESURE_ne_disqualifie_pas():
    """0.0 est une VALEUR (le canal a parle et a dit zero), pas une absence."""
    ok, _ = fri.rejouabilite(_ligne([
        {"chunk_id": "c1", "rank": 1, "lexical_score": 0.0, "vector_score": 0.0}]))
    assert ok is True, "un zero mesure a ete confondu avec un signal manquant"


def test_un_canal_NOT_OBSERVABLE_disqualifie_ET_nomme_le_canal():
    ok, motif = fri.rejouabilite(_ligne([
        {"chunk_id": "c1", "rank": 1, "lexical_score": 12.0,
         "vector_score": "NOT_OBSERVABLE"}]))
    assert ok is False
    assert "vector" in motif.lower(), (
        f"le motif {motif!r} ne nomme pas le canal manquant : irreparable en l'etat")


def test_une_observation_sans_resultat_est_refusee_avec_motif():
    ok, motif = fri.rejouabilite(_ligne([]))
    assert ok is False and motif, "un refus sans motif ne s'instruit pas"


def test_la_couverture_imprime_son_DENOMINATEUR():
    lignes = [
        _ligne([{"chunk_id": "a", "rank": 1, "lexical_score": 1.0, "vector_score": 0.5}]),
        _ligne([{"chunk_id": "b", "rank": 1, "lexical_score": 1.0,
                 "vector_score": "NOT_OBSERVABLE"}]),
        _ligne([]),
    ]
    c = fri.couverture(lignes, illisibles=2)
    assert c["total"] == c["rejouables"] + c["non_rejouables"] + c["illisibles"], (
        f"le denominateur ne se referme pas : {c}")
    assert c["rejouables"] == 1 and c["non_rejouables"] == 2 and c["illisibles"] == 2
    assert c["motifs"], "les motifs de refus doivent etre agreges, pas jetes"


def test_un_corpus_VIDE_rend_un_taux_INCONNU_jamais_zero():
    c = fri.couverture([], illisibles=0)
    assert c["total"] == 0
    assert c["taux"] is None, (
        f"taux={c['taux']!r} sur corpus vide : une absence de donnee rendue comme "
        "un taux nul ferait conclure a une couverture nulle mesuree")


def test_les_lignes_illisibles_sont_COMPTEES_pas_avalees(tmp_path):
    j = tmp_path / "obs.jsonl"
    j.write_text(
        json.dumps(_ligne([{"chunk_id": "a", "rank": 1,
                            "lexical_score": 1.0, "vector_score": 0.5}])) + "\n"
        + "{ceci n'est pas du json\n"
        + json.dumps(_ligne([])) + "\n",
        encoding="utf-8")
    lignes, illisibles = fri.charger(j)
    assert len(lignes) == 2 and illisibles == 1, (
        "une ligne corrompue doit etre COMPTEE : un journal partiellement illisible "
        "lu comme complet surestime la couverture en silence")


def test_le_point_d_entree_CLI_traverse(tmp_path, monkeypatch, capsys):
    """Le chemin REEL, pas seulement les fonctions : un drapeau CLI casse pendant que
    les fonctions passent est un defaut deja paye dans ce depot."""
    j = tmp_path / "obs.jsonl"
    j.write_text(json.dumps(_ligne([{"chunk_id": "a", "rank": 1,
                                     "lexical_score": 1.0, "vector_score": 0.5}])) + "\n",
                 encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["forge_router_impact", "--journal", str(j)])
    rc = fri.main()
    sortie = capsys.readouterr().out
    assert rc == 0, f"le point d'entree sort en rc={rc}"
    donnees = json.loads(sortie.strip().splitlines()[-1])
    assert donnees["total"] == 1 and donnees["rejouables"] == 1
