"""NR -- le routeur donne au registre de confiance un TTFT MESURE apres une reponse reussie, jamais une estimation.

Reste de p2_capacite_fournisseur_observee_0925 (owner 25/09 : « et le TTFT aux 3 sites d'appel »). Lecture 20/10 :
les 3 sites (call_cascade, call, _call_slot) appellent slot.record_call() AVANT litellm.completion, et record_call passe
au registre la latence de CONFIGURATION (`latency`, 1000 par defaut) -- une estimation posee comme une mesure, et un
succes compte meme quand l'appel echoue. Le contrat du registre le dit pourtant : « Appeler APRES chaque reponse reussie
avec le TTFT mesure » (forge_trust_score.TrustScoreRegistry.record_success).
"""
from __future__ import annotations

import sys
import time
import types
from types import SimpleNamespace

import pytest

from nokido_agent.app import forge_llm_router as flr
from nokido_agent.app import forge_trust_score as fts

pytestmark = pytest.mark.timeout(60)


class _Reponse:
    def __init__(self):
        self.choices = [SimpleNamespace(message=SimpleNamespace(content="bonjour"))]
        self.usage = SimpleNamespace(total_tokens=3)
        self._hidden_params = {"additional_headers": {}}


def _lent(**_k):
    time.sleep(0.03)
    return _Reponse()


def _panne(**_k):
    raise RuntimeError("fournisseur en panne")


@pytest.fixture
def mesures(monkeypatch):
    vues = []
    monkeypatch.setattr(fts.TrustScoreRegistry, "get",
                        classmethod(lambda cls: SimpleNamespace(record_success=lambda n, ms: vues.append((n, ms)),
                                                                record_failure=lambda *a, **k: None)))
    return vues


def _routeur(monkeypatch, comportement):
    faux = types.ModuleType("litellm")
    faux.completion = comportement
    monkeypatch.setitem(sys.modules, "litellm", faux)
    r = flr.LLMRouter.__new__(flr.LLMRouter)
    slot = flr.ProviderSlot("groq", {"models": ["groq/llama-3.1-8b-instant"], "env_key": "", "latency": 1000})
    r._slots = {}
    monkeypatch.setattr(r, "_select_slot", lambda use_case, exclure=(): slot, raising=False)
    monkeypatch.setattr(r, "_garde_sortante", lambda p, s, n: (p, None), raising=False)
    return r, slot


def test_call_reussi_enregistre_une_latence_mesuree(monkeypatch, mesures):
    r, _ = _routeur(monkeypatch, _lent)
    assert r.call("bonjour", "general")["ok"] is True
    assert len(mesures) == 1 and mesures[0][0] == "groq"
    assert 25 <= mesures[0][1] < 1000, mesures      # mesuree (~30 ms), pas la latence de configuration


def test_call_slot_reussi_enregistre_une_latence_mesuree(monkeypatch, mesures):
    r, slot = _routeur(monkeypatch, _lent)
    assert r._call_slot(slot, "bonjour", "", 50, 0.2, 10, "general")["ok"] is True
    assert len(mesures) == 1 and 25 <= mesures[0][1] < 1000, mesures


def test_un_appel_en_echec_n_enregistre_aucun_succes(monkeypatch, mesures):
    r, _ = _routeur(monkeypatch, _panne)
    r.call("bonjour", "general")
    assert mesures == []


def test_record_call_seul_ne_fabrique_aucune_latence(mesures):
    flr.ProviderSlot("groq", {"models": ["m"], "env_key": "", "latency": 1000}).record_call()
    assert mesures == []
