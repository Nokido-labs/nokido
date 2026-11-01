"""NR (sans reseau) : l'essaim choisit ses membres par force MESUREE, pas par simple vivacite (24/10).

Un vivant fort (4/4) passe devant un vivant faible (2/4) ; un UNKNOWN passe APRES les forts mesures ; le registre ecrit
la force et sa source ; membres_par_defaut rejette un registre sans force mesuree (repli DEFAULT_MEMBERS + raison).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_cli_swarm as cs  # noqa: E402
import forge_free_tier_census as ft  # noqa: E402

PORTEURS = {"groq": ["groq"], "mistral": ["mistral"]}


def _matrice(score_fort=1.0, score_faible=0.5):
    def voie(f, m, s):
        return {"fournisseur": f, "modele": m, "etat": "JOIGNABLE", "competence": {"score": s}}
    return {"familles": {"x": [voie("groq", "fort", score_fort), voie("groq", "faible", score_faible)]}}


def test_le_fort_passe_devant_le_faible():
    r = ft.membres_essaim({"groq": ["faible", "fort"]}, PORTEURS, matrice=_matrice())
    assert r["membres"] == ["groq:fort", "groq:faible"]
    assert r["forces"]["groq:fort"]["force"] == 1.0
    assert r["forces"]["groq:fort"]["source"]


def test_unknown_passe_apres_les_forts_et_jamais_avant():
    r = ft.membres_essaim({"groq": ["inconnu", "faible", "fort"]}, PORTEURS, matrice=_matrice())
    assert r["membres"] == ["groq:fort", "groq:faible", "groq:inconnu"]
    assert r["forces"]["groq:inconnu"]["force"] is None


def test_la_force_vient_des_fiches_du_census():
    census = {"verdicts": {"mistral:a": {"dimensions": {"force": {"code": {"etat": "OBSERVE", "valeur": 0.9}}}},
                           "mistral:b": {"dimensions": {"force": {"code": {"etat": "DECLARE", "valeur": 1.0}}}}}}
    r = ft.membres_essaim({"mistral": ["b", "a"]}, PORTEURS, census=census)
    assert r["membres"] == ["mistral:a", "mistral:b"]      # un DECLARE n'est jamais une mesure
    assert r["forces"]["mistral:b"]["force"] is None


def test_le_registre_garde_les_n_plus_forts_avec_force_et_source(tmp_path):
    chemin = tmp_path / "r.json"
    r = ft.membres_essaim({"groq": ["inconnu", "faible", "fort"]}, PORTEURS, matrice=_matrice())
    verdicts = {m: {"etat": "OK"} for m in r["membres"]}
    doc = ft.ecrire_membres_vivants(verdicts, chemin, maintenant=1000.0, forces=r["forces"], n=2)
    assert doc["membres_ok"] == ["groq:fort", "groq:faible"]
    assert [m["nom"] for m in doc["membres"]] == doc["membres_ok"]
    assert all(m["force"] is not None and m["source"] for m in doc["membres"])
    assert json.loads(chemin.read_text(encoding="utf-8"))["membres"] == doc["membres"]
    membres, raison = cs.membres_par_defaut(chemin, maintenant=1060.0)
    assert membres == ["groq:fort", "groq:faible"] and raison == ""


def test_registre_sans_force_mesuree_repli_dit(tmp_path):
    chemin = tmp_path / "r.json"
    ft.ecrire_membres_vivants({"a:c": {"etat": "OK"}}, chemin, maintenant=1000.0, forces={})
    membres, raison = cs.membres_par_defaut(chemin, maintenant=1060.0)
    assert membres == cs.DEFAULT_MEMBERS and raison == "registre sans force mesurée"
