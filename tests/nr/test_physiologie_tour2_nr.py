# -*- coding: utf-8 -*-
"""NR (owner 3/11, debat 1 tour 2 Claude x AGY, 07ffe15b5) : le corps comble ses trous de physiologie et son code les
garde.

1. Une lacune physiologique cherche du TEXTE INTEGRAL (EuropePMC, acces libre) : mesure 3/11, la veille par theme ne
   ramenait que des resumes DOI (1-2 chunks) sur les cytokines. Apres 2 pistes sans fermeture -> escalade
   (irresolution_proposee), pas une 3e veille.
2. arXiv compte comme reference pour un homologue de CONTROLE, jamais de BIOLOGIE.
3. NR 3 : le NR de l'homologue d'un module entre d'office (en tete) dans le perimetre du juge du RSI.
4. Aucun homologue declare sans NR existant (sinon c'est du vocabulaire).
"""
import json
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

EPMC = {"resultList": {"result": [
    {"pmcid": "PMC2329767", "isOpenAccess": "Y", "inEPMC": "Y", "title": "From inflammation to sickness"},
    {"pmcid": None, "isOpenAccess": "N", "title": "resume seul"},
    {"pmcid": "PMC9000001", "isOpenAccess": "Y", "inEPMC": "Y", "title": "Cytokines and behavior"},
]}}


# --- 1. texte integral ----------------------------------------------------------------------------------------------
def test_urls_texte_integral_depuis_europepmc():
    vus = []
    urls = V.urls_texte_integral("sickness behavior cytokines", _get=lambda url: vus.append(url) or EPMC)
    assert urls == ["https://pmc.ncbi.nlm.nih.gov/articles/PMC2329767/",
                    "https://pmc.ncbi.nlm.nih.gov/articles/PMC9000001/"]
    assert "OPEN_ACCESS" in vus[0] and "sickness" in vus[0]


def test_europepmc_injoignable_rien_et_pas_d_exception():
    def _casse(url):
        raise OSError("hors ligne")
    assert V.urls_texte_integral("x y z", _get=_casse) == []


@pytest.fixture
def lacune_physio(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "LACUNES", tmp_path / "soif_lacunes.json")
    monkeypatch.setattr(V, "corps_sous_tension", lambda: (False, "test"))
    monkeypatch.setattr(V, "theme_autorise", lambda theme: (True, ""))
    lac = {"etat": sorted(V.ACTIVES)[0], "instrument": "physiologie_fts:maladie", "question": "sickness behavior",
           "remesures_sans_effet": V.PISTES_SEUIL_STAGNATION, "pistes": ["sickness behavior cytokines"],
           "critere": {"termes": "sickness behavior cytokines"}, "historique": []}
    V._ecrire_lacunes({"k": lac})
    return "k"


def test_une_lacune_physiologique_lance_la_veille_par_urls_de_texte_integral(lacune_physio, monkeypatch):
    monkeypatch.setattr(V, "urls_texte_integral", lambda termes, **k: ["https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"])
    appels = []
    r = V.lancer_pistes(lacune_physio, lambda theme, urls=None: appels.append((theme, urls)) or "c1", maintenant=1e9)
    assert r["lancees"] == 1 and appels == [("sickness behavior cytokines",
                                             ["https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"])], (r, appels)


def test_apres_deux_pistes_sans_fermeture_escalade(lacune_physio, monkeypatch):
    d = V.lire_lacunes()
    d["k"]["historique"] = [{"evenement": "pistes_lancees", "t": 1.0, "chaines": ["a"]},
                            {"evenement": "pistes_lancees", "t": 2.0, "chaines": ["b"]}]
    V._ecrire_lacunes(d)
    appels = []
    r = V.lancer_pistes(lacune_physio, lambda theme, urls=None: appels.append(theme) or "c", maintenant=1e9)
    assert r["lancees"] == 0 and r.get("escalade") and appels == []
    assert V.lire_lacunes()["k"]["irresolution_proposee"] is True


def test_le_demon_passe_les_urls_au_workflow_officiel(monkeypatch):
    import types
    vus = {}
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_watch_agent",
                        types.SimpleNamespace(create_job=lambda **k: vus.update(k) or "wj_x"))
    assert D._creer_veille_soif("t", urls=["https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"]) == "wj_x"
    assert vus["urls"] == ["https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"] and vus["theme"] == "t"


# --- 2. nature de l'homologue -------------------------------------------------------------------------------------
def test_arxiv_reference_pour_un_mecanisme_de_controle_seulement():
    compte = {"https://arxiv.org/abs/1410.6064v5": 49, "https://doi.org/10.1/x": 1}
    assert V.verdict_couverture_physio(compte, nature="controle")["gap"] is False
    assert V.verdict_couverture_physio(compte, nature="biologie")["gap"] is True
    assert V.verdict_couverture_physio(compte)["gap"] is True                     # defaut = biologie


# --- 3. NR 3 : perimetre du juge ----------------------------------------------------------------------------------
def test_le_nr_de_l_homologue_entre_en_tete_du_perimetre(tmp_path):
    import forge_mutation_judge as J
    (tmp_path / "app").mkdir()
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tests" / "nr" / "test_invariant_x_nr.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (tmp_path / "app" / "forge_x.py").write_text(
        '__FORGE_HOMOLOGUE__ = {"mecanisme": "m", "termes": "t", "nr": "tests/nr/test_invariant_x_nr.py"}\n',
        encoding="utf-8")
    det = J.perimetre_mesure_detail("app/forge_x.py", racine=tmp_path)
    assert det["retenus"][0] == "tests/nr/test_invariant_x_nr.py" and det.get("par_homologue")


def test_le_nr_lui_meme_n_est_pas_son_propre_perimetre(tmp_path):
    import forge_mutation_judge as J
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tests" / "nr" / "test_invariant_x_nr.py").write_text("x = 1\n", encoding="utf-8")
    det = J.perimetre_mesure_detail("tests/nr/test_invariant_x_nr.py", racine=tmp_path)
    assert not det.get("par_homologue")


# --- 4. aucun homologue sans NR existant --------------------------------------------------------------------------
def test_tout_homologue_declare_a_un_nr_qui_existe():
    fautifs = []
    for sous in ("app", "tools"):
        for p in (ROOT / sous).glob("*.py"):
            h = C.homologue_de_texte(p.read_text(encoding="utf-8", errors="replace")[:C.HEAD_CHARS])
            if h and not (h.get("nr") and (ROOT / h["nr"]).is_file()):
                fautifs.append("%s/%s" % (sous, p.name))
    assert fautifs == []
