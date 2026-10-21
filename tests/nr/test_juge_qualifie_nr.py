"""NR -- juge QUALIFIE (decision owner 16/10, bb:architecture_rules/decision_owner_juge_qualifie_et_partage_20261016).

Mesure 16/10 : le juge epistemique local (ollama qwen2.5-coder:1.5b) rendait 100 % `supersedes` (28/28) ; les
fermetures sont suspendues (8abee7a74). Decision owner : modele FORT via le routeur pour juger les paires
d'assertions et les resultats de tache (le routeur porte deja SemanticFirewall, 6af854be3) ; LOCAL pour le code du
depot. Le volet « juge de CODE » (app/forge_scorecard.py, module JUGE protege par la separation des pouvoirs) a son
RED a part, confie a un autre agent que Claude.
"""
import os
import sys

_DEPOT = os.environ.get("NOKIDO_DEPOT") or os.path.join(os.path.dirname(__file__), "..", "..")
_TOOLS = os.path.join(_DEPOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_epistemic_extract_claims as E  # noqa: E402
from nokido_agent.app import forge_llm_router as R  # noqa: E402


def test_le_juge_d_assertions_passe_par_le_routeur_en_mode_debat(monkeypatch):
    vus = {}

    def faux_router_call(prompt, use_case="general", max_tokens=500, *, context=None, **kw):
        vus.update(use_case=use_case, contexte=context is not None)
        return {"ok": True, "text": '{"relation": "unrelated", "confidence": 0.9, "rationale": "sujets distincts"}'}

    monkeypatch.setattr(R, "router_call", faux_router_call)
    v = E.juge_backend("routeur")("La CI dure 27 min.", "Le hub est lent.")
    assert (vus, (v or {}).get("relation")) == ({"use_case": "debate", "contexte": True}, "unrelated")


def test_un_routeur_muet_rend_un_juge_muet_jamais_un_verdict(monkeypatch):
    monkeypatch.setattr(R, "router_call", lambda prompt, **kw: {"ok": False, "error": "tous fournisseurs KO"})
    assert E.juge_backend("routeur")("A", "B") is None


def test_un_backend_inconnu_est_refuse_jamais_remplace_en_silence():
    """RED du 16/10 : juge_backend("routeur") retombait SANS LE DIRE sur ollama local (le test a reellement appele
    le modele, 20 s) -- et ce juge a repondu `contradicts` 1.0 pour « A » / « B »."""
    import pytest

    with pytest.raises(ValueError):
        E.juge_backend("inconnu")
