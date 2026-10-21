"""NR -- le routeur n'offre plus un modele que le registre free tier PROUVE mort (RED 6 du plan AGY, 16/10).

Mesure 16/10 : Groq llama-3.3-70b / qwen3-32b / llama-3.1-8b-instant (404), NVIDIA llama-3.3-70b (410), DeepSeek (402)
-- des slots que la cascade essayait encore, un echec et un delai a chaque fois. Les verdicts sont desormais GARDES par
`forge_free_tier_census --cible` (sandbox/free_tier_census.json, cle fournisseur:modele).

Asymetrie voulue (RULES_SHARED, « le cout des 2 erreurs n'est jamais symetrique ») : n'ecarte que la preuve DEFINITIVE
et RECENTE. Un 429, un timeout, un 401 (notre cle, pas le modele), un verdict sans mesure ou un registre illisible
n'ecartent RIEN : ecarter a tort tue un slot sain, garder a tort coute un essai.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_llm_router as R  # noqa: E402

MAINTENANT = time.mktime((2026, 10, 17, 0, 0, 0, 0, 0, -1))


def _quand(jours_avant: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(MAINTENANT - jours_avant * 86400))


def _registre(tmp_path, verdicts) -> Path:
    chemin = tmp_path / "free_tier_census.json"
    chemin.write_text(json.dumps({"fournisseurs": [], "verdicts": verdicts}), encoding="utf-8")
    return chemin


def _prouves(chemin):
    return R.injoignables_prouves(chemin, maintenant=MAINTENANT)


def test_un_modele_prouve_absent_ou_retire_ou_payant_est_ecarte(tmp_path):
    chemin = _registre(tmp_path, {
        "groq:llama-3.1-8b-instant": {"joignable": False, "motif": "HTTP 404", "mesure_le": _quand(1)},
        "nvidia:meta/llama-3.3-70b-instruct": {"joignable": False, "motif": "HTTP 410", "mesure_le": _quand(1)},
        "deepseek:deepseek-chat": {"joignable": False, "motif": "HTTP 402", "mesure_le": _quand(1)},
    })
    assert _prouves(chemin) == {"groq:llama-3.1-8b-instant", "nvidia:meta/llama-3.3-70b-instruct",
                                "deepseek:deepseek-chat"}


def test_un_echec_passager_ou_de_cle_n_ecarte_rien(tmp_path):
    chemin = _registre(tmp_path, {
        "mistral:mistral-medium-latest": {"joignable": False, "motif": "HTTP 429", "mesure_le": _quand(0)},
        "cerebras:zai-glm-4.7": {"joignable": False, "motif": "timeout", "mesure_le": _quand(0)},
        "groq:openai/gpt-oss-20b": {"joignable": False, "motif": "HTTP 401", "mesure_le": _quand(0)},
    })
    assert _prouves(chemin) == set()


def test_un_modele_joignable_ou_sans_mesure_n_est_pas_ecarte(tmp_path):
    chemin = _registre(tmp_path, {
        "mistral:codestral-latest": {"joignable": True, "motif": "", "mesure_le": _quand(0)},
        "inconnu:q": {"etat": "FOURNISSEUR_INCONNU", "mesure_le": _quand(0)},
        "groq:x": {"joignable": None, "motif": "HTTP 404", "mesure_le": _quand(0)},
    })
    assert _prouves(chemin) == set()


def test_une_preuve_trop_ancienne_n_ecarte_plus(tmp_path):
    """Un catalogue bouge : un 404 d'il y a un mois ne dit rien de ce soir -- il faut remesurer."""
    chemin = _registre(tmp_path, {
        "groq:qwen/qwen3-32b": {"joignable": False, "motif": "HTTP 404", "mesure_le": _quand(30)},
        "groq:sans-date": {"joignable": False, "motif": "HTTP 404"},
    })
    assert _prouves(chemin) == set()


def _chaine(monkeypatch, morts, chaine):
    monkeypatch.setattr(R, "injoignables_prouves", lambda *a, **k: set(morts), raising=False)
    monkeypatch.setitem(R.USE_CASE_CHAINS, "nr_injoignables", list(chaine))
    return R.chaine_active("nr_injoignables")


def test_chaine_active_n_offre_plus_un_slot_dont_tous_les_modeles_sont_prouves_morts(monkeypatch):
    # groq_fast porte groq/openai/gpt-oss-20b et groq/openai/gpt-oss-120b (mesure 17/10 a l'execution)
    morts = {"groq:%s" % m.split("/", 1)[1] for m in R.PROVIDERS["groq_fast"]["models"]}
    assert _chaine(monkeypatch, morts, ["groq_fast", "mistral_codestral"]) == ["mistral_codestral"]


def test_un_slot_dont_un_seul_modele_est_mort_reste_offert(monkeypatch):
    un_seul = {"groq:%s" % R.PROVIDERS["groq_fast"]["models"][0].split("/", 1)[1]}
    assert _chaine(monkeypatch, un_seul, ["groq_fast", "mistral_codestral"]) == ["groq_fast", "mistral_codestral"]


def test_sans_preuve_la_chaine_est_intacte(monkeypatch):
    assert _chaine(monkeypatch, set(), ["groq_fast", "mistral_codestral"]) == ["groq_fast", "mistral_codestral"]


def test_un_registre_absent_ou_illisible_n_ecarte_rien(tmp_path):
    assert R.injoignables_prouves(tmp_path / "absent.json", maintenant=MAINTENANT) == set()
    casse = tmp_path / "casse.json"
    casse.write_text("{pas du json", encoding="utf-8")
    assert R.injoignables_prouves(casse, maintenant=MAINTENANT) == set()
