"""NR -- la passe de nuit juge les paires d'assertions avec le juge QUALIFIE (routeur), decision owner du 16/10.

RED ecrit par Claude. Mesure 16/10 (job_a72cb58f8523, 42 paires) : juge local qwen2.5-coder:1.5b = supersedes 42/42 ;
juge_backend('routeur') = supports 36, extends 2, qualifies 1, unrelated 3, supersedes 0. Or consolidation_nuit
appelait consolider_fn(limit=...) SANS juge -> juge local par defaut. LAFORGE_EPISTEMIC_JUGE permet un retour explicite.
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_epistemic_extract_claims as E  # noqa: E402


def _nuit(monkeypatch):
    vus = {}
    juges = {"routeur": object(), "local": object(), "cerebras": object()}
    monkeypatch.setattr(E, "juge_backend", lambda backend: juges[backend])
    monkeypatch.setattr(E, "lire_etat_nuit", lambda: {})
    monkeypatch.setattr(E, "ecrire_etat_nuit", lambda maj: None)
    res = E.consolidation_nuit(limit=3, appel=lambda *a, **k: True,
                               consolider_fn=lambda **kw: vus.update(kw) or {"ok": True},
                               decharger=lambda: True, admettre=lambda: {"admit": True}, liberer=lambda: None)
    return res, vus, juges


def test_la_nuit_juge_avec_le_routeur_par_defaut(monkeypatch):
    monkeypatch.delenv("LAFORGE_EPISTEMIC_JUGE", raising=False)
    res, vus, juges = _nuit(monkeypatch)
    assert res["issue"] == "OK", res
    assert vus.get("juge") is juges["routeur"], vus


def test_le_juge_se_choisit_explicitement(monkeypatch):
    monkeypatch.setenv("LAFORGE_EPISTEMIC_JUGE", "local")
    _res, vus, juges = _nuit(monkeypatch)
    assert vus.get("juge") is juges["local"], vus
