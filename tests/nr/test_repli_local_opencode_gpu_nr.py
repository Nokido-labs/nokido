"""NR -- un executeur OpenCode ne replie plus en silence sur un modele LOCAL (GPU) quand Ollama Cloud est epuise (8/11).

Mesure : 12 h 42, qwen3:8b charge par Ollama (5,2 Go VRAM) a la relance OpenCode d'OPENCODE_DEFAUT2 ; owner : « pourquoi
le GPU s'enflamme encore ». Cause : _repli_du rendait REPLI_LOCAL_OPENCODE (ollama/qwen3:8b) sans garde (introduit par
07874eb5a le 3/11, NR test_delegation_prevol_lmstudio_nr). Le local devient un opt-in explicite.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
import forge_task_executor as te  # noqa: E402

CFG = {"repli_ollama_cloud": "gpt-oss:120b"}


def _cloud(monkeypatch, epuise):
    monkeypatch.setattr(te, "surface_est_indisponible",
                        lambda s, *a, **k: ("epuise" if (epuise and s == "OLLAMA_CLOUD") else None))


def test_cloud_epuise_ne_replie_pas_en_local_par_defaut(monkeypatch):
    monkeypatch.delenv("LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE", raising=False)
    _cloud(monkeypatch, True)
    assert te._repli_du(CFG) is None


def test_opt_in_explicite_autorise_le_local(monkeypatch):
    monkeypatch.setenv("LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE", "1")
    _cloud(monkeypatch, True)
    assert te._repli_du(CFG) == te.REPLI_LOCAL_OPENCODE


def test_cloud_disponible_reste_le_repli(monkeypatch):
    monkeypatch.delenv("LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE", raising=False)
    _cloud(monkeypatch, False)
    assert te._repli_du(CFG) == "ollama_cloud/gpt-oss:120b"


def test_repli_modele_explicite_inchange(monkeypatch):
    monkeypatch.delenv("LAFORGE_OPENCODE_REPLI_LOCAL_AUTORISE", raising=False)
    _cloud(monkeypatch, True)
    assert te._repli_du({"repli_ollama_cloud": "x", "repli_modele": "groq/llama"}) == "groq/llama"
