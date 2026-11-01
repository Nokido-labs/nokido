"""NR juge d'ancrage des chiffres du swarm pointeur (faux membres, aucun reseau)."""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import forge_cli_swarm as sw  # noqa: E402


def test_sans_source_et_ancre_normalise():
    j = sw._juger_ancrage("gain -30 % et 34 055 lignes", ["le fichier a 34055 lignes"])
    assert j["chiffres"] == 2 and j["ancres"] == 1 and j["sans_source"] == ["30%"]
    assert j["taux"] == 0.5


def test_taux_none_si_aucun_chiffre():
    assert sw._juger_ancrage("rien", ["x"]) == {"chiffres": 0, "ancres": 0, "sans_source": [], "taux": None}


def test_exclusions():
    t = "voir ligne 42, annee 2026, port :8766, sha deadbeef12 et job_20261029_100240, § 12, foo.py:77"
    assert sw._chiffres(t) == []


def test_formes_significatives():
    assert sw._chiffres("0,10× puis ×2 puis 3,5 puis 7") == ["0.1x", "2x", "3.5"]
    # assertion REMPLACEE le 29/10 (ex ["15", "20%"]) : le « 15 » nu d'une plage de pourcentages s'ancrait sur
    # n'importe quel 15 des sources et laissait passer une synthese fabriquee (recette 10 h 02) ; une plage = 2 pourcentages
    assert sw._chiffres("−15–20 %") == ["15%", "20%"]


def test_membre_expose_ancrage_sans_modifier_texte(monkeypatch):
    msgs = [{"role": "user", "content": "consigne 99"},
            {"role": "tool", "name": "lire", "content": "total 34055"},
            {"role": "assistant", "content": "34 055 et 77 %"}]
    monkeypatch.setattr(sw, "_boucle_membre", lambda *a, **k: (msgs, 2))
    r = sw._tourner_membre("groq:m", "consigne 99", 3)
    assert r["text"] == "34 055 et 77 %"
    assert r["ancrage"]["sans_source"] == ["77%"] and r["ancrage"]["ancres"] == 1


@pytest.fixture(autouse=True)
def _membres_factices_forts(monkeypatch):
    """ARBITRAGE 29/10 : les membres factices sont declares forts (regle REDACTEURS_FORTS) ; assertions inchangees."""
    monkeypatch.setattr(sw, "REDACTEURS_FORTS", ("a", "b", "c", "x"))
    monkeypatch.setattr(sw, "SYNTHESE_MIN_CAR", 0)  # 29/10 : syntheses factices courtes ; substance testee a part


def _membre(nom, outils, sans=0, extraits=()):
    return {"provider": nom, "ok": True, "text": f"rep {nom}", "tours": 2, "outils_appeles": list(outils),
            "chars_envoyes": 1, "ms": 1, "post_flight": {"vus": 0}, "extraits": list(extraits),
            "ancrage": {"chiffres": sans, "ancres": 0, "sans_source": ["1%"] * sans, "taux": 0.0}}


@pytest.fixture
def monde(monkeypatch, tmp_path):
    monkeypatch.setattr(sw, "_membres_pointeur", lambda membres, sonde=None: (list(membres), []))
    monkeypatch.setattr(sw, "SORTIE_DIR", tmp_path)

    def installer(reponses, texte_synth):
        monkeypatch.setattr(sw, "_tourner_membre", lambda m, t, n: dict(reponses[m]))
        vus = {}

        def synth(membre, materiau, consigne, max_tours=1):
            vus["membre"] = membre
            return {"text": texte_synth, "post_flight": {"vus": 0}}
        monkeypatch.setattr(sw, "_synthetiser", synth)
        return vus
    return installer


def test_synthese_ligne_fabriquee_retiree_avec_mention(monde):
    monde({"a": _membre("a", ["x"], extraits=["il y a 34055 lignes"])},
          "ancree : 34 055 lignes\ninventee : -30 % de latence\nsans chiffre")
    res = asyncio.run(sw.swarm_pointeur("q", ["p"], membres=["a"]))
    lignes = res["synthesis"].splitlines()
    assert "inventee" not in res["synthesis"] and "ancree" in res["synthesis"]
    assert res["synthese_ancrage"]["lignes_retirees"] == 1
    assert lignes[-1] == "[juge d'ancrage : 1 ligne(s) retirée(s), chiffres sans source : 30%]"


def test_synthese_tout_retire_donne_none(monde):
    monde({"a": _membre("a", ["x"])}, "inventee 55 %")
    res = asyncio.run(sw.swarm_pointeur("q", ["p"], membres=["a"]))
    assert res["synthesis"] is None and "ancrage" in res["synthese_motif"]


def test_redacteur_moins_de_sans_source_meme_si_moins_lu(monde):
    vus = monde({"a": _membre("a", ["x", "y", "z"], sans=3), "b": _membre("b", ["x"], sans=0)}, "f")
    res = asyncio.run(sw.swarm_pointeur("q", ["p"], membres=["a", "b"]))
    assert vus["membre"] == "b" and res["synthese_par"] == "b"
