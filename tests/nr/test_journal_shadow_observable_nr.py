"""Non-regression : le journal SHADOW porte de quoi justifier l'activation.

DEFAUT MESURE le 2026-09-08, en soudant le point de bascule (cf.
`test_bascule_routeur_soudee_nr`). Le schema d'observation du routeur est BIEN
concu : il prevoit `lexical_score` et `vector_score` par resultat, avec un
troisieme etat explicite `NOT_OBSERVABLE` -- jamais un zero, qui ferait conclure
a la non-pertinence de ce qu'on n'a pas pu voir.

Mesure : le moteur n'emet NI l'un NI l'autre. Il passe `chunk_id`, `rank`,
`final_score`, `availability`, et rien de plus. Donc TOUTE observation ecrite
depuis le 2026-09-01 porte `NOT_OBSERVABLE` sur les deux canaux.

C'est la TROISIEME instance du meme motif dans ce dossier -- un mecanisme
branche sur un signal que PERSONNE n'emet. La consequence est precise et couteuse :
le shadow existe pour qu'a l'ouverture de la fenetre nominale, "la calibration
dispose deja d'observations reelles au lieu de partir de zero". Un journal sans
signal par canal ne permet de calculer AUCUNE alternative : on ne peut pas savoir
ce qu'aurait donne un autre poids sans savoir ce que chaque canal a dit. Le
shadow accumulait donc du volume, pas de la preuve.

CE QUE CE FICHIER PROUVE.
  - EMISSION (test 1) : le site d'appel du moteur transmet bien les deux signaux.
    Lecture AST du chemin reel : l'emission EST une propriete de l'appelant.
  - HONNETETE (test 2) : un canal reellement indisponible reste `NOT_OBSERVABLE`
    et ne devient JAMAIS 0.0. Sans ce test, "corriger" l'emission en remplissant
    des zeros passerait le test 1 en fabriquant des mesures fausses -- le remede
    serait pire que le mal.
  - BOUT EN BOUT (test 3) : une observation a la forme reelle, ecrite puis RELUE
    depuis le journal, porte des nombres exploitables.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.106)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app",):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_retrieval_router as rr  # noqa: E402

MOTEUR = RACINE / "app" / "forge_rag_engine.py"
CANAUX = ("lexical_score", "vector_score")


def _arbre():
    if not MOTEUR.exists():
        pytest.fail(f"ILLISIBLE : {MOTEUR} absent -- ce test n'a rien pu regarder")
    return ast.parse(MOTEUR.read_text(encoding="utf-8", errors="replace"))


def _noms_locaux(arbre, cible: str) -> set:
    """Resout les alias d'import : chercher le nom BRUT rate `observer as _rt_observer`."""
    noms = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("forge_retrieval_router"):
            for a in n.names:
                if a.name == cible:
                    noms.add(a.asname or a.name)
    return noms


def _cles_emises(arbre) -> set:
    """Les cles construites dans le dict de resultats passe a `observer`."""
    locaux = _noms_locaux(arbre, "observer")
    cles = set()
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        nom = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
        if nom not in locaux:
            continue
        for arg in list(n.args) + [k.value for k in n.keywords]:
            for sous in ast.walk(arg):
                if isinstance(sous, ast.Dict):
                    for c in sous.keys:
                        if isinstance(c, ast.Constant) and isinstance(c.value, str):
                            cles.add(c.value)
    return cles


def test_le_moteur_emet_les_signaux_par_canal():
    """Sans eux, le journal ne peut pas repondre a la question qu'il prepare."""
    cles = _cles_emises(_arbre())
    assert cles, (
        f"aucun appel a `observer` trouve dans {MOTEUR.name} : le journal n'est plus "
        "alimente, ce test ne mesure plus ce qu'il croit mesurer")
    manquants = [c for c in CANAUX if c not in cles]
    assert not manquants, (
        f"{MOTEUR.name} n'emet pas {manquants} -- le journal les ecrira "
        "NOT_OBSERVABLE pour toujours, et aucune alternative de ponderation ne "
        f"pourra etre calculee. Cles emises : {sorted(cles)}")


def test_un_canal_indisponible_reste_NOT_OBSERVABLE(tmp_path, monkeypatch):
    """Garde anti-remede-pire-que-le-mal : remplir des zeros passerait le test 1."""
    monkeypatch.setattr(rr, "_JOURNAL", tmp_path / "obs.jsonl")
    d = rr.decider("forge_tier_guard", {})
    rr.observer("q1", "forge_tier_guard", d,
                [{"chunk_id": "c1", "rank": 1, "final_score": 0.42}])
    ligne = json.loads((tmp_path / "obs.jsonl").read_text(encoding="utf-8").strip())
    r0 = ligne["resultats"][0]
    for canal in CANAUX:
        assert r0[canal] == "NOT_OBSERVABLE", (
            f"{canal} vaut {r0[canal]!r} alors qu'aucun signal n'a ete fourni : "
            "un signal absent devenu nombre est une mesure INVENTEE")


def test_une_observation_a_la_forme_reelle_est_relisible(tmp_path, monkeypatch):
    """Bout en bout : ecrite puis RELUE, elle porte des nombres exploitables."""
    monkeypatch.setattr(rr, "_JOURNAL", tmp_path / "obs.jsonl")
    d = rr.decider("qu'est-ce qu'une couverture de Markov", {})
    rr.observer("q2", "qu'est-ce qu'une couverture de Markov", d, [
        {"chunk_id": "c1", "rank": 1, "final_score": 0.42,
         "lexical_score": 12.0, "vector_score": 0.91},
        {"chunk_id": "c2", "rank": 2, "final_score": 0.31,
         "lexical_score": 0.0, "vector_score": "NOT_OBSERVABLE"},
    ])
    ligne = json.loads((tmp_path / "obs.jsonl").read_text(encoding="utf-8").strip())
    res = ligne["resultats"]
    assert res[0]["lexical_score"] == 12.0 and res[0]["vector_score"] == 0.91
    assert res[1]["lexical_score"] == 0.0, (
        "un ZERO MESURE doit survivre au journal : c'est une valeur, pas une absence")
    assert res[1]["vector_score"] == "NOT_OBSERVABLE"
    assert ligne["mode"] == d.mode and ligne["engine_commit"]
