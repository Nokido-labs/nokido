# -*- coding: utf-8 -*-
"""NR (owner 3/11, debat Claude x AGY, commit AGY 72d10a76e) : le corps detecte seul ses manques de physiologie.

Synthese : l'homologue biologique est DECLARE dans le module (`__FORGE_HOMOLOGUE__`, lu par le census comme
`__FORGE_COLOR__` : aucun registre parallele) ; l'instrument `physiologie_fts` (FTS indexe, remesurable) dit
« couvert » seulement avec DIVERSITE et PROFONDEUR (mesure 3/11 : 5 resumes DOI de 1-2 chunks sur les cytokines ne
couvrent rien ; une source unique de 65 chunks non plus) ; un trou ouvre une lacune EXTERNE dont la piste est la veille
(budget + arbitre de saillance) ; un homologue sans NR est du vocabulaire, signale par le census.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_epistemic_daemon as D  # noqa: E402
import forge_module_census as C  # noqa: E402

V = D.ev

ENTETE = '''"""Module de test."""
__FORGE_COLOR__ = "immunitaire/regulation"
__FORGE_HOMOLOGUE__ = {"mecanisme": "comportement de maladie", "termes": "sickness behavior cytokines lethargy",
                       "sources": ["openstax:m46058"], "invariant": "sous cytokine la soif se tait", "nr": "tests/nr/x.py"}
'''


# --- census : declaration lue SANS execution --------------------------------------------------------------------
def test_le_census_lit_l_homologue_declare():
    h = C.homologue_de_texte(ENTETE)
    assert h["mecanisme"] == "comportement de maladie" and h["termes"].startswith("sickness")


def test_une_declaration_non_litterale_n_est_jamais_executee(tmp_path):
    temoin = tmp_path / "execute.txt"
    texte = '__FORGE_HOMOLOGUE__ = open(%r, "w").write("x")\n' % str(temoin)
    assert C.homologue_de_texte(texte) is None and not temoin.exists()


def test_sans_declaration_rien():
    assert C.homologue_de_texte('"""doc"""\n__FORGE_COLOR__ = "x/y"\n') is None


def test_homologue_sans_nr_est_signale():
    homs = [{"module": "app/a.py", "mecanisme": "m", "termes": "t", "nr": "tests/nr/a.py"},
            {"module": "app/b.py", "mecanisme": "m", "termes": "t"}]
    assert C.homologues_sans_nr(homs) == ["app/b.py"]


# --- instrument : diversite ET profondeur --------------------------------------------------------------------
@pytest.mark.parametrize("compte, couvert", [
    ({"https://pmc.ncbi.nlm.nih.gov/articles/PMC7046449/": 65}, False),                 # une seule source
    ({"https://doi.org/a": 1, "https://doi.org/b": 2, "https://doi.org/c": 1}, False),  # resumes : pas de profondeur
    ({"https://pmc.ncbi.nlm.nih.gov/articles/PMC7046449/": 65, "https://blog.example/x": 3}, True),
    ({"https://blog.example/x": 30, "https://blog.example/y": 20}, False),               # aucune reference
    ({"github:openstax/osbooks-anatomy-physiology/modules/m46058/index.cnxml": 6, "https://doi.org/a": 1}, True),
])
def test_couvert_exige_diversite_et_profondeur(compte, couvert):
    v = V.verdict_couverture_physio(compte)
    assert v["gap"] is (not couvert), v


def test_les_sources_de_code_ne_comptent_pas():
    v = V.verdict_couverture_physio({"app/forge_x.py": 50, "mcp_result:POST_COMMIT:x": 40,
                                     "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/": 9})
    assert v["sources_distinctes"] == 1 and v["gap"] is True


def test_mesure_illisible_n_est_pas_un_trou(monkeypatch):
    monkeypatch.setattr(V, "_sources_physio", lambda fts: None)        # plan sans index / base illisible
    cov = V.mesurer_physiologie("sickness behavior cytokines")
    assert cov["ok"] is False and "gap" not in cov


def test_instrument_remesurable_par_son_nom(monkeypatch):
    monkeypatch.setattr(V, "_sources_physio", lambda fts: {"https://pmc.ncbi.nlm.nih.gov/articles/PMC1/": 9,
                                                           "https://doi.org/z": 1})
    lac = {"instrument": "physiologie_fts:comportement", "critere": {"termes": "sickness behavior cytokines"}}
    cov = V.mesurer_selon_instrument(lac)
    assert cov["ok"] is True and cov["gap"] is False and cov["instrument"].startswith("physiologie_fts")


# --- soif : un trou ouvre une lacune EXTERNE dont la piste est la veille ------------------------------------------
@pytest.fixture
def registre(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "LACUNES", tmp_path / "soif_lacunes.json")
    return tmp_path


def test_un_trou_ouvre_une_lacune_dont_la_piste_est_la_veille(registre, monkeypatch):
    monkeypatch.setattr(V, "_sources_physio", lambda fts: {"https://doi.org/a": 1})
    homs = registre / "homologues.json"
    homs.write_text('{"homologues": [{"module": "app/a.py", "mecanisme": "comportement de maladie", '
                    '"termes": "sickness behavior cytokines lethargy"}]}', encoding="utf-8")
    r = D._mesurer_homologues(chemin=homs)
    assert r["ouvertes"] == 1, r
    lac = next(iter(V.lire_lacunes().values()))
    assert lac["instrument"].startswith("physiologie_fts") and V.pistes_pour_lacune(lac) == [
        "sickness behavior cytokines lethargy"]


def test_couvert_rien_n_est_ouvert(registre, monkeypatch):
    monkeypatch.setattr(V, "_sources_physio", lambda fts: {"https://pmc.ncbi.nlm.nih.gov/articles/PMC1/": 9,
                                                           "https://doi.org/z": 1})
    homs = registre / "homologues.json"
    homs.write_text('{"homologues": [{"module": "app/a.py", "mecanisme": "m", "termes": "sleep consolidation"}]}',
                    encoding="utf-8")
    assert D._mesurer_homologues(chemin=homs)["ouvertes"] == 0 and V.lire_lacunes() == {}


def test_registre_absent_est_dit_illisible(registre):
    r = D._mesurer_homologues(chemin=registre / "absent.json")
    assert r["ouvertes"] == 0 and r.get("illisible")


def test_une_lacune_physiologique_prend_la_voie_des_pistes_pas_l_enquete_de_code():
    lac = {"instrument": "physiologie_fts:m", "question": "sickness behavior cytokines",
           "remesures_sans_effet": V.PISTES_SEUIL_STAGNATION, "pistes": ["sickness behavior cytokines"]}
    vus = []
    r = D._traiter_lacune_stagnante("k", lac, 1e9, 0, creer=lambda theme: vus.append(theme) or "c")
    assert r["voie"] == "pistes"
