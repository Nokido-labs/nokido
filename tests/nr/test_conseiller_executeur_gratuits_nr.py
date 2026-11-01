"""NR -- conseiller souverain cote executeur (P1 etape 2) : voie OpenCode. Faux client ACP, faux conseiller, depot git
temporaire, aucun reseau. Plan injecte ; NON LIVRE -> 1 revue + 1 relance ; conseiller KO -> sans conseil, dit ;
LAFORGE_CONSEILLER=0 -> aucun appel."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as T  # noqa: E402

OK_TXT = '{"intent":"OK_DONE","pointer_ref":"commit:abc1234","commit_message":"feat: x"}'


class Client:
    prompts: list = []

    def __init__(self, cmd=None, cwd=None, agent=None, env=None):
        pass

    def start(self): pass
    def initialize(self): pass
    def session_new(self): return "sid"
    def set_model(self, sid, m): pass
    def close(self): pass

    def prompt(self, sid, text, timeout=None):
        Client.prompts.append(text)
        return {"text": OK_TXT}


@pytest.fixture
def banc(tmp_path, monkeypatch):
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    Client.prompts = []
    monkeypatch.setattr(T, "ACPClient", Client)
    monkeypatch.setenv("LAFORGE_OPENCODE_GPTOSS_WORKDIR", str(wt))
    monkeypatch.setenv("LAFORGE_CONSEILLER", "1")
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda i: "tok")
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "")
    clos = {}
    monkeypatch.setattr(T, "_clore_delegation", lambda tid, tok, ok, d, intent=None: clos.update(ok=ok, d=d))
    efs = {}
    monkeypatch.setattr(T, "_finaliser_effet", lambda tid, ok, effet: efs.update(effet=effet) or ok)
    appels = []
    monkeypatch.setattr(T, "_CONSEIL_COMPTEUR", {})
    return wt, clos, efs, appels


def _juge(monkeypatch, verdicts):
    it = iter(verdicts)
    monkeypatch.setattr(T, "_juger_livraison", lambda ok, d, wt, avant, autorises=None, desc=None: next(it))


TASK = {"id": "t1", "agent": "OPENCODE_GPTOSS", "description": "Corrige tools/foo.py"}


def test_plan_injecte_dans_le_prompt_et_trace(banc, monkeypatch):
    wt, clos, efs, appels = banc
    monkeypatch.setattr(T, "_appeler_conseiller", lambda t, e, c: appels.append((e, c)) or
                        {"avis": "faire A puis B", "fournisseur": "ollama_cloud_ultra", "escalade": []})
    _juge(monkeypatch, [(True, "commits produits : 1", "OK_DONE")])
    T._delegate_to_opencode(dict(TASK), "tk")
    assert Client.prompts[0].startswith("Plan conseille : faire A puis B")
    assert appels[0][0] == "plan" and "tools/foo.py" in appels[0][1]
    assert "conseil: ollama_cloud_ultra (escalade 0)" in efs["effet"]
    assert T._CONSEIL_COMPTEUR["opencode"] == {"avec": 1, "sans": 0}


def test_non_livre_une_revue_une_relance(banc, monkeypatch):
    wt, clos, efs, appels = banc
    monkeypatch.setattr(T, "_appeler_conseiller", lambda t, e, c: appels.append(e) or
                        {"avis": "avis-" + e, "fournisseur": "f", "escalade": []})
    _juge(monkeypatch, [(False, "[NON LIVRE] x", None), (False, "[NON LIVRE] encore", None)])
    T._delegate_to_opencode(dict(TASK), "tk")
    assert appels == ["plan", "revue"]          # jamais plus d'une revue
    assert len(Client.prompts) == 2
    assert "avis-revue" in Client.prompts[1] and "Plan conseille" not in Client.prompts[1]
    assert clos["ok"] is False


def test_conseiller_ko_delegation_sans_conseil_et_dit(banc, monkeypatch):
    wt, clos, efs, appels = banc
    monkeypatch.setattr(T, "_appeler_conseiller", lambda t, e, c: {"avis": "", "fournisseur": None, "escalade": []})
    _juge(monkeypatch, [(True, "commits produits : 1", "OK_DONE")])
    T._delegate_to_opencode(dict(TASK), "tk")
    assert "Plan conseille" not in Client.prompts[0]
    assert "SANS conseil" in efs["effet"]
    assert T._CONSEIL_COMPTEUR["opencode"] == {"avec": 0, "sans": 1}
    assert clos["ok"] is True


def test_interrupteur_zero_aucun_appel(banc, monkeypatch):
    wt, clos, efs, appels = banc
    monkeypatch.setenv("LAFORGE_CONSEILLER", "0")
    monkeypatch.setattr(T, "_appeler_conseiller", lambda t, e, c: appels.append(e) or {})
    _juge(monkeypatch, [(False, "[NON LIVRE] x", None)])
    T._delegate_to_opencode(dict(TASK), "tk")
    assert appels == [] and len(Client.prompts) == 1
