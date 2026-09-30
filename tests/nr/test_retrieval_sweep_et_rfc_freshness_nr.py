"""NR — les deux gardes ecrits le 2026-09-03 refusent de conclure d'un silence.

Motif paye ce jour-la : « aucune RFC ingeree », affirme TROIS fois, alors que
2 582 chunks etaient en base et qu'`audit_rfc_compliance` rendait 36/36 en
150 ms. Puis, dans le correctif lui-meme, un namespace ecrit en `http` au lieu
de `https` a rendu 36/36 « INCONNUE_AMONT » — RFC 791 comprise.

Ces tests verifient l'EFFET des deux invariants, pas l'import des modules :

  - `forge_retrieval_sweep` : ABSENT n'est rendu que si TOUTES les surfaces sont
    lisibles et vides ; une seule illisible -> INDETERMINE.
  - `forge_rfc_freshness_gate` : un amont injoignable ne devient jamais A_JOUR,
    et une absence TOTALE d'appariement accuse l'INSTRUMENT, pas le corpus.

Chaque test doit pouvoir ECHOUER : les contre-epreuves sont explicites.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _charger(nom):
    """Charge un module de tools/ sans dependre du sys.path du lanceur."""
    chemin = ROOT / "tools" / (nom + ".py")
    if not chemin.exists():
        pytest.skip("%s absent" % chemin)
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- sweep ----

def test_forge_retrieval_sweep_une_surface_illisible_interdit_absent():
    """Le coeur de l'invariant : ne pas transformer « pas vu » en « pas la »."""
    sweep = _charger("forge_retrieval_sweep")
    surfaces = [{"surface": "rag_fts", "etat": "vide"},
                {"surface": "outils", "etat": "vide"},
                {"surface": "memoires", "etat": "illisible",
                 "raison": "PermissionError"}]
    assert sweep.verdict_global(surfaces) == "INDETERMINE"


def test_forge_retrieval_sweep_absent_exige_toutes_les_surfaces_lues():
    """Contre-epreuve : sans trou, ABSENT reste possible — sinon le garde ne
    dirait jamais rien et deviendrait inutile."""
    sweep = _charger("forge_retrieval_sweep")
    surfaces = [{"surface": "rag_fts", "etat": "vide"},
                {"surface": "outils", "etat": "vide"}]
    assert sweep.verdict_global(surfaces) == "ABSENT"


def test_forge_retrieval_sweep_un_seul_hit_suffit_a_dire_present():
    sweep = _charger("forge_retrieval_sweep")
    surfaces = [{"surface": "rag_fts", "etat": "vide"},
                {"surface": "outils", "etat": "hits", "n": 1},
                {"surface": "memoires", "etat": "illisible"}]
    assert sweep.verdict_global(surfaces) == "PRESENT"


def test_forge_retrieval_sweep_interroge_les_deux_index_lexicaux():
    """`rag_fts` et `rag_chunks_fts` ne portent pas le meme contenu (mesure
    2026-09-01 : `litellm` -> 84 980 vs 16 517). En interroger un seul et
    conclure pour les deux est le faux negatif que ce module existe pour tuer."""
    source = (ROOT / "tools" / "forge_retrieval_sweep.py").read_text(
        encoding="utf-8", errors="replace")
    assert "rag_chunks_fts" in source and "rag_fts" in source
    assert "source:" in source, "la colonne source porte les conventions de nommage"


# ------------------------------------------------------------- freshness ----

def test_forge_rfc_freshness_gate_amont_injoignable_nest_pas_a_jour(monkeypatch):
    """Un reseau coupe ne doit jamais faire passer le gate au vert."""
    gate = _charger("forge_rfc_freshness_gate")
    monkeypatch.setattr(gate, "_amont", lambda url=None: (None, "URLError: coupe"))
    res = gate.evaluer()
    assert res["etat"] == "AMONT_INJOIGNABLE"
    assert not res["verdicts"], "aucun verdict ne peut etre rendu sans amont"


def test_forge_rfc_freshness_gate_accuse_son_instrument_si_rien_ne_sapparie(
        monkeypatch):
    """36/36 « inconnues », RFC 791 comprise, c'est le parseur qui est faux.

    Mesure 2026-09-03 : le namespace de `rfc-index.xml` est en `https` ; ecrit
    en `http`, tous les findall echouaient en silence.
    """
    gate = _charger("forge_rfc_freshness_gate")
    monkeypatch.setattr(gate, "_amont", lambda url=None: ({}, None))
    res = gate.evaluer()
    assert res["etat"] == "INSTRUMENT_SUSPECT"


def test_forge_rfc_freshness_gate_distingue_obsolete_et_mise_a_jour(monkeypatch):
    """Contre-epreuve : avec un amont credible, le gate rend de VRAIS verdicts."""
    gate = _charger("forge_rfc_freshness_gate")
    cibles = gate._rfcs_ingerees()
    assert cibles, "la liste ciblee vient d'audit_rfc_compliance"
    premier = cibles[0][2]
    faux_amont = {n: {"statut": "PROPOSED STANDARD", "obsoleted_by": [],
                      "updated_by": []} for _, _, n in cibles}
    faux_amont[premier] = {"statut": "HISTORIC", "obsoleted_by": [9999],
                           "updated_by": []}
    monkeypatch.setattr(gate, "_amont", lambda url=None: (faux_amont, None))
    res = gate.evaluer()
    assert res["etat"] == "MESURE"
    assert res["compte"].get("OBSOLETE") == 1
    obs = [v for v in res["verdicts"] if v["verdict"] == "OBSOLETE"][0]
    assert obs["remplacee_par"] == [9999]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
