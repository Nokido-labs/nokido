"""NR -- capacite OBSERVEE des fournisseurs : les en-tetes x-ratelimit-* que le routeur recoit.

bb:p2_capacite_fournisseur_observee_0925 (retenu le 25/09) : connaitre ce qui reste au lieu
de le deduire des 429. `record_response_headers` n'avait AUCUN appelant. Par le CHEMIN REEL
(`LLMRouter.call`, litellm remplace par un faux module qui rend des reponses FABRIQUEES) :
  * en-tetes presents -> compteurs CONNUS, reinitialisation, etat FRAICHE ;
  * en-tetes absents  -> rien d'invente : INCONNU ;
  * en-tetes mal formes -> MAL_FORME, valeur brute gardee ;
  * une 429 porte aussi les en-tetes ; une mesure vieille ou rechargee est PERIMEE ;
  * le routage ne change pas, et aucune autre cle que la liste blanche n'est stockee.
Aucune cle d'API reelle : la cle factice du test est un leurre, et elle ne doit apparaitre
nulle part dans ce qui est stocke.
"""
from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

from nokido_agent.app import forge_llm_router as flr
from nokido_agent.app import forge_quota_tracker as fqt

pytestmark = pytest.mark.timeout(120)

LEURRE = "gsk_LEURRE_DE_TEST_PAS_UNE_CLE"


class _Reponse:
    def __init__(self, entetes):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content="bonjour"))]
        self.usage = SimpleNamespace(total_tokens=3)
        self._hidden_params = {"additional_headers": entetes}


class _Erreur429(Exception):
    def __init__(self, entetes):
        super().__init__("429 rate_limit_exceeded")
        self.response = SimpleNamespace(headers=entetes, status_code=429)


@pytest.fixture
def capteur(tmp_path, monkeypatch):
    monkeypatch.setattr(fqt, "CAPACITE_DIR", tmp_path / "capacite")
    monkeypatch.setattr(fqt, "_HEADER_CACHE", {})
    return tmp_path / "capacite"


def _routeur(monkeypatch, comportement):
    """Un LLMRouter reel, un slot 'groq', et litellm remplace par `comportement`."""
    faux = types.ModuleType("litellm")
    faux.completion = comportement
    monkeypatch.setitem(sys.modules, "litellm", faux)
    r = flr.LLMRouter.__new__(flr.LLMRouter)
    slot = flr.ProviderSlot("groq", {"models": ["groq/llama-3.1-8b-instant"], "env_key": ""})
    r._slots = {}
    monkeypatch.setattr(r, "_select_slot", lambda use_case, exclure=(): slot, raising=False)
    monkeypatch.setattr(r, "_garde_sortante", lambda p, s, n: (p, None), raising=False)
    return r


GROQ = {"x-ratelimit-remaining-tokens": "5800", "x-ratelimit-limit-tokens": "6000",
        "llm_provider-x-ratelimit-remaining-requests": "14370",
        "llm_provider-x-ratelimit-limit-requests": "14400",
        "llm_provider-x-ratelimit-reset-requests": "2m59.56s",
        "llm_provider-x-ratelimit-reset-tokens": "2s",
        "llm_provider-authorization": "Bearer " + LEURRE,
        "llm_provider-x-request-id": "req_123"}


# ── chemin reel ───────────────────────────────────────────────────────────────────────
def test_en_tetes_presents_capacite_connue_et_fraiche(capteur, monkeypatch):
    r = _routeur(monkeypatch, lambda **k: _Reponse(dict(GROQ)))
    out = r.call("bonjour", "general")
    assert out["ok"] is True and out["provider"] == "groq"      # le routage rend comme avant
    c = fqt.capacite_observee("groq")
    assert c["etat"] == fqt.FRAICHE
    assert c["compteurs"]["restant_tokens"] == {"etat": fqt.CONNU, "valeur": 5800}
    assert c["compteurs"]["restant_requetes"]["valeur"] == 14370
    assert c["reinitialisation"]["reinit_requetes"]["etat"] == fqt.CONNU
    assert abs(c["reinitialisation"]["reinit_tokens"]["dans_s"] - 2.0) < 0.5
    stocke = (capteur / "groq.json").read_text(encoding="utf-8")
    assert LEURRE not in stocke and "x-request-id" not in stocke     # liste blanche
    assert fqt.get_quota("groq")["headers"]["ok"] is True             # cache existant nourri


def test_en_tetes_absents_rien_d_invente(capteur, monkeypatch):
    r = _routeur(monkeypatch, lambda **k: _Reponse({"llm_provider-x-request-id": "r"}))
    assert r.call("bonjour", "general")["ok"] is True
    assert not capteur.exists() or not list(capteur.iterdir())
    c = fqt.capacite_observee("groq")
    assert c["etat"] == fqt.INCONNU and "aucune capture" in c["raison"]


def test_en_tetes_mal_formes_sont_dits(capteur, monkeypatch):
    r = _routeur(monkeypatch, lambda **k: _Reponse({
        "x-ratelimit-remaining-tokens": "beaucoup",
        "x-ratelimit-remaining-requests": "12",
        "llm_provider-x-ratelimit-reset-tokens": "bientot"}))
    r.call("bonjour", "general")
    c = fqt.capacite_observee("groq")
    assert c["compteurs"]["restant_tokens"] == {"etat": fqt.MAL_FORME, "brut": "beaucoup"}
    assert c["reinitialisation"]["reinit_tokens"]["etat"] == fqt.MAL_FORME
    assert c["compteurs"]["limite_tokens"]["etat"] == fqt.INCONNU
    assert c["etat"] == fqt.FRAICHE        # un compteur reste lisible (requetes)


def test_une_429_porte_aussi_la_capacite(capteur, monkeypatch):
    def _refus(**k):
        raise _Erreur429({"x-ratelimit-remaining-tokens": "0", "retry-after": "7"})
    r = _routeur(monkeypatch, _refus)
    out = r.call("bonjour", "general")
    assert out["ok"] is False                                     # comportement inchange
    c = fqt.capacite_observee("groq")
    assert c["capture_sur_erreur"] is True and c["compteurs"]["restant_tokens"]["valeur"] == 0
    assert c["reinitialisation"]["retry_after"]["etat"] == fqt.CONNU


def test_un_capteur_qui_casse_ne_casse_pas_l_appel(capteur, monkeypatch):
    def _boum(*a, **k):
        raise RuntimeError("capteur en panne")
    monkeypatch.setattr(fqt, "capturer_reponse", _boum)
    r = _routeur(monkeypatch, lambda **k: _Reponse(dict(GROQ)))
    assert r.call("bonjour", "general")["ok"] is True


# ── peremption ────────────────────────────────────────────────────────────────────────
def test_mesure_vieille_ou_rechargee_est_perimee(capteur):
    t0 = 1_000_000.0
    fqt.capturer_reponse("groq", {"x-ratelimit-remaining-tokens": "10",
                                  "x-ratelimit-reset-tokens": "30s"}, maintenant=t0)
    assert fqt.capacite_observee("groq", maintenant=t0 + 5)["etat"] == fqt.FRAICHE
    recharge = fqt.capacite_observee("groq", maintenant=t0 + 31)
    assert recharge["etat"] == fqt.PERIMEE and "reinitialisation" in recharge["raison"]
    fqt.capturer_reponse("groq", {"x-ratelimit-remaining-tokens": "10"}, maintenant=t0)
    vieille = fqt.capacite_observee("groq", maintenant=t0 + fqt.PEREMPTION_S + 1)
    assert vieille["etat"] == fqt.PERIMEE


def test_capture_illisible_est_inconnue(capteur):
    capteur.mkdir(parents=True)
    (capteur / "groq.json").write_text("{tronque", encoding="utf-8")
    assert fqt.capacite_observee("groq")["etat"] == fqt.INCONNU


@pytest.mark.parametrize("brut,attendu", [("2m59.56s", 179.56), ("2s", 2.0), ("120ms", 0.12),
                                           ("1h2m3s", 3723.0), ("30", 30.0), ("6m0s", 360.0),
                                           ("bientot", None), ("2s3", None)])
def test_durees_de_reinitialisation(brut, attendu):
    d = fqt._duree_s(brut)
    assert (d is None and attendu is None) or abs(d - attendu) < 1e-6


def test_pas_de_cle_d_api_dans_les_journaux_des_fichiers(capteur):
    fqt.capturer_reponse("groq", {"Authorization": "Bearer " + LEURRE,
                                  "x-ratelimit-remaining-tokens": "1"})
    assert all(LEURRE not in f.read_text(encoding="utf-8") for f in capteur.iterdir())
    assert json.loads((capteur / "groq.json").read_text())["entetes"] == {
        "x-ratelimit-remaining-tokens": "1"}
