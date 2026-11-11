# -*- coding: utf-8 -*-
"""NR 8/11 (Geste NEUF 2 audit Z.AI) : fail-closed du pare-feu pre_flight vers le cloud
et suppression des slots fantomes dans call_cascade.

Verifie :
1. `detect_injection` qui leve + destination cloud -> `PreFlightResult(ok=False)` (fail-closed)
   et journalisation en WARNING (jamais debug).
2. `is_network_kill` qui leve + destination cloud -> `PreFlightResult(ok=False)` (fail-closed)
   et journalisation en WARNING.
3. Memes pannes + destination locale (`local`, `ollama`) -> comportement d'avant (`ok=True`).
4. Dans `forge_llm_router.call_cascade`, tous les `_cloud_slots` et le repli appartiennent
   a `PROVIDERS` (aucun slot en dur inexistant comme `claude_pro` ou `openai_gpt4`).
"""
from __future__ import annotations

import ast
import logging
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nokido_agent.app.forge_llm_router as R  # noqa: E402
import nokido_agent.app.forge_opsec as OPSEC  # noqa: E402
import nokido_agent.app.forge_prompt_guard as PG  # noqa: E402
import nokido_agent.app.forge_semantic_firewall as FW  # noqa: E402


def test_detect_injection_qui_leve_sur_cloud_est_fail_closed(monkeypatch, caplog):
    def _boom(_task):
        raise RuntimeError("panne detect_injection")

    monkeypatch.setattr(PG, "detect_injection", _boom)
    monkeypatch.setattr(OPSEC, "is_network_kill", lambda: False)

    fw = FW.SemanticFirewall()
    with caplog.at_level(logging.DEBUG, logger=FW.logger.name):
        res = fw.pre_flight("bonjour", context="", ring=3, provider="groq_fast")

    assert res.ok is False, f"attendu fail-closed (ok=False) sur cloud, recu: {res}"
    assert "detect_injection" in res.reason and "RuntimeError" in res.reason
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "detect_injection" in r.getMessage()]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG and "detect_injection" in r.getMessage()]
    assert warnings, "l'echec de detect_injection doit etre journalise en WARNING"
    assert not debugs, "l'echec de detect_injection ne doit jamais etre journalise en DEBUG"


def test_is_network_kill_qui_leve_sur_cloud_est_fail_closed(monkeypatch, caplog):
    def _boom():
        raise OSError("registre opsec illisible")

    monkeypatch.setattr(OPSEC, "is_network_kill", _boom)

    fw = FW.SemanticFirewall()
    with caplog.at_level(logging.WARNING, logger=FW.logger.name):
        res = fw.pre_flight("bonjour", context="", ring=3, provider="auto")

    assert res.ok is False, f"attendu fail-closed (ok=False) sur cloud, recu: {res}"
    assert "kill-switch" in res.reason.lower() and "OSError" in res.reason
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "kill-switch" in r.getMessage()]
    assert warnings, "l'echec de is_network_kill doit etre journalise en WARNING"


@pytest.mark.parametrize("provider_local", ["local", "ollama"])
def test_panne_gardes_sur_destination_locale_conserve_comportement(monkeypatch, caplog, provider_local):
    def _boom_kill():
        raise OSError("registre opsec illisible")

    def _boom_inj(_task):
        raise RuntimeError("panne detect_injection")

    monkeypatch.setattr(OPSEC, "is_network_kill", _boom_kill)
    monkeypatch.setattr(PG, "detect_injection", _boom_inj)

    fw = FW.SemanticFirewall()
    with caplog.at_level(logging.DEBUG, logger=FW.logger.name):
        res = fw.pre_flight("bonjour", context="", ring=3, provider=provider_local)

    assert res.ok is True, f"destination locale ({provider_local}) doit rester ok=True: {res}"
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG and "detect_injection" in r.getMessage()]
    assert not debugs, "jamais de journalisation debug pour detect_injection"


def test_call_cascade_cloud_slots_appartiennent_tous_a_providers(monkeypatch):
    # 1. Verification statique sur l'AST de call_cascade : aucun slot fantome en dur
    src = Path(R.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn_cascade = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "call_cascade"
    )
    constantes_str = {
        n.value for n in ast.walk(fn_cascade)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    for fantome in ("claude_pro", "openai_gpt4"):
        assert fantome not in constantes_str, f"slot fantome {fantome!r} encore en dur dans call_cascade"

    # 2. Verification dynamique : escalade PAT/github sur chaine vide ou locale
    vus = []

    class _FakeSlot:
        def __init__(self, name):
            self.name = name
            self.config = R.PROVIDERS[name]
            self.is_available = False
            self.is_configured = False
            self._cooldown = 0.0
            self._failures = 0
            self._breaker = types.SimpleNamespace(allow=lambda: True)

    router = R.LLMRouter.__new__(R.LLMRouter)
    router._slots = {}

    class _RecordingDict(dict):
        def get(self, k, default=None):
            vus.append(k)
            return _FakeSlot(k) if k in R.PROVIDERS else None

    router._slots = _RecordingDict()
    monkeypatch.setattr(R, "chaine_active", lambda _uc: [])
    monkeypatch.setattr(R, "repli_oauth", lambda *a, **k: None)

    router.call_cascade(
        "ouvre une pull request github avec gh api",
        use_case="general",
        force_local=True,
        inject_persona=False,
        max_attempts=1,
    )
    assert vus, "call_cascade doit tenter au moins un slot cloud en repli sur tache github/PAT"
    inconnus = [s for s in vus if s not in R.PROVIDERS]
    assert not inconnus, f"slots absents de PROVIDERS tentes par call_cascade : {inconnus}"
    for s in vus:
        assert s not in R._LOCAL_SLOTS, f"slot local {s!r} retenu comme repli cloud"
