# -*- coding: utf-8 -*-
"""NR — quota journalier epuise -> bascule sur ollama_cloud FREE (24/10). Aucun reseau."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_provider_catalogue as C  # noqa: E402
import forge_task_executor as T  # noqa: E402

QUOTA = "Rate limit exceeded: free-models-per-day"


def test_equivalent_free():
    assert C.equivalent_ollama_cloud("openrouter/nvidia/nemotron-3-super-120b-a12b:free") == "nemotron-3-super"
    assert C.equivalent_ollama_cloud("groq/openai/gpt-oss-120b") == "gpt-oss:120b"
    assert C.equivalent_ollama_cloud("") is None
    assert C.equivalent_ollama_cloud("zai/glm-4.7-flash") is None


def test_hors_liste_jamais_choisi(monkeypatch):
    monkeypatch.setattr(C, "OLLAMA_CLOUD_FREE", ("gpt-oss:20b",))
    assert C.equivalent_ollama_cloud("groq/openai/gpt-oss-120b") is None


class Doublure:
    vus: list = []

    def __init__(self, cmd=None, cwd=None, on_log=None, agent="gemini", env=None):
        self.cfg = json.loads((env or {}).get("OPENCODE_CONFIG_CONTENT", "{}"))
        self.env = env or {}

    def start(self): return None
    def initialize(self): return {}
    def session_new(self): return "sid"
    def request(self, m, p, timeout=30): return {}

    def prompt(self, sid, text, timeout=30):
        Doublure.vus.append((self.cfg.get("model"), "OLLAMA_API_KEY" in self.env))
        if (self.cfg.get("model") or "").startswith("openrouter/"):
            raise RuntimeError(QUOTA)
        return {"text": 'fait {"intent":"OK_DONE","pointer_ref":"x"}'}

    def close(self): return None


def test_quota_bascule_ollama_cloud(tmp_path, monkeypatch):
    table = {"OPENCODE_NEMOTRON": {"modele": "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
                                   "repli_ollama_cloud": "nemotron-3-super", "worktree": "w"}}
    f = tmp_path / "i.json"
    f.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setenv("LAFORGE_OPENCODE_INSTANCES_FILE", str(f))
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_NEMOTRON_WORKDIR", str(wt))
    Doublure.vus = []
    monkeypatch.setattr(T, "ACPClient", Doublure)
    monkeypatch.setattr(T, "_etat_git", lambda w: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "ok")
    # **_k : la signature reelle a gagne `consigne_servie` (contexte servi, 9/11) ; un double fige casse a chaque ajout.
    monkeypatch.setattr(T, "_juger_livraison", lambda ok, d, w, a, autorises=None, desc=None, **_k: (ok, "c", None))
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda i: "j")
    monkeypatch.setattr(T, "_lire_cle_fournisseur", lambda n: "cle_fabriquee")
    monkeypatch.setattr(T, "_battement_delegation", lambda a, t: __import__("contextlib").nullcontext())
    monkeypatch.setattr(T, "_clore_delegation", lambda *a, **k: None)
    T._delegate_to_opencode({"id": "job_oc_01", "agent": "OPENCODE_NEMOTRON",
                             "description": "Consigne de test assez longue pour etre extraite."}, "jx")
    assert len(Doublure.vus) == 2
    assert Doublure.vus[1] == ("ollama_cloud/nemotron-3-super", True)
