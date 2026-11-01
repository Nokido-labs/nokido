"""NR -- le petit modele reste MEMBRE, jamais REDACTEUR (regle owner 29/10) ; cascade fort -> Claude -> AGY -> aucune.
Faux redacteurs, faux envoi, aucun reseau."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_cli_swarm as S  # noqa: E402

FORT = "ollama_cloud_gptoss:gpt-oss:120b"
PETIT = "ollama_cloud_mistral:ministral-8b"


@pytest.fixture(autouse=True)
def _seuil_substance_neutre(monkeypatch):
    """29/10 : syntheses factices courtes ; le garde de substance a son propre NR (test_swarm_synthese_substance_nr)."""
    monkeypatch.setattr(S, "SYNTHESE_MIN_CAR", 0)


def _m(nom, lus=1):
    return {"provider": nom, "ok": True, "text": f"rep {nom}", "tours": 1, "outils_appeles": ["t"] * lus,
            "chars_envoyes": 1, "ms": 1, "post_flight": {"vus": 0}, "extraits": [],
            "ancrage": {"chiffres": 0, "ancres": 0, "sans_source": [], "taux": None}}


@pytest.fixture
def monde(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "_membres_pointeur", lambda membres, sonde=None: (list(membres), []))
    monkeypatch.setattr(S, "SORTIE_DIR", tmp_path)

    def installer(reponses, fort_texte="", voies=None, pf_ok=True):
        appels = {"membres": [], "voies": [], "pf": []}
        monkeypatch.setattr(S, "_tourner_membre", lambda m, t, n: dict(reponses[m]))

        def synth(membre, materiau, consigne, max_tours=1):
            appels["membres"].append(membre)
            return {"text": fort_texte, "post_flight": {"vus": 0}, "error": "vide"}
        monkeypatch.setattr(S, "_synthetiser", synth)

        def pf(texte, voie):
            appels["pf"].append(voie)
            return (pf_ok, "refus" if not pf_ok else None)
        monkeypatch.setattr(S, "_pre_flight_envoi", pf)

        def voie(nom, prompt, timeout=180):
            appels["voies"].append(nom)
            r = (voies or {}).get(nom)
            return {"text": r, "error": None} if r else {"text": "", "error": "ILLISIBLE: hors job"}
        monkeypatch.setattr(S, "_appeler_voie", voie)
        return appels
    return installer


def _run(membres):
    return asyncio.run(S.swarm_pointeur("q", ["p"], membres=membres))


def test_petit_modele_jamais_choisi(monde):
    a = monde({PETIT: _m(PETIT, lus=9), FORT: _m(FORT, lus=1)}, fort_texte="fusion")
    res = _run([PETIT, FORT])
    assert a["membres"] == [FORT] and res["synthese_par"] == FORT


def test_fort_vide_passe_a_claude(monde):
    a = monde({FORT: _m(FORT)}, fort_texte="", voies={"claude_cli": "synthese claude"})
    res = _run([FORT])
    assert a["voies"] == ["claude_cli"] and res["synthesis"] == "synthese claude"
    assert res["synthese_par"] == "claude:claude_cli"
    assert [e["membre"] for e in res["synthese_essais"]] == [FORT, "claude:claude_cli"]


def test_seul_petit_ok_va_a_claude_sans_synthese_petit(monde):
    a = monde({PETIT: _m(PETIT)}, voies={"claude_cli": "par claude"})
    res = _run([PETIT])
    assert a["membres"] == [] and res["synthese_par"] == "claude:claude_cli"


def test_claude_illisible_passe_a_agy(monde):
    a = monde({FORT: _m(FORT)}, voies={"gemini_cli": "par agy"})
    res = _run([FORT])
    assert a["voies"] == ["claude_cli", "gemini_cli"] and res["synthese_par"] == "agy:gemini_cli"
    assert "ILLISIBLE" in res["synthese_essais"][1]["motif"]


def test_tout_vide_publie_les_reponses(monde):
    monde({FORT: _m(FORT), PETIT: _m(PETIT)})
    res = _run([FORT, PETIT])
    assert res["synthesis"] is None and res["synthese_motif"]
    assert {a["provider"] for a in res["answers"]} == {FORT, PETIT}
    assert all("ancrage" in a for a in res["answers"])


def test_pre_flight_refuse_aucun_envoi(monde):
    a = monde({FORT: _m(FORT)}, voies={"claude_cli": "x", "gemini_cli": "y"}, pf_ok=False)
    res = _run([FORT])
    assert a["voies"] == [] and a["pf"] == ["claude_cli", "gemini_cli"] and res["synthesis"] is None


def test_gardes_appliquees_a_claude(monde):
    monde({FORT: _m(FORT)}, voies={"claude_cli": "ancree rep\ninventee 77 %"})
    res = _run([FORT])
    assert "inventee" not in res["synthesis"] and "ancree" in res["synthesis"]
    assert res["synthese_ancrage"]["lignes_retirees"] == 1
    monde({FORT: _m(FORT)}, voies={"claude_cli": "\n".join(["meme ligne"] * 6)})
    res = _run([FORT])
    assert res["synthese_garde"]["lignes_ecartees"] == 4


def test_forts_est_une_liste_explicite():
    assert "ollama_cloud_gptoss:gpt-oss:120b" in S.REDACTEURS_FORTS
    assert "ollama_cloud_ultra:nemotron-3-ultra" in S.REDACTEURS_FORTS
