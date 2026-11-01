"""NR : le correctif est GENERE par un modele fort gratuit, le local ne fait que le repli (owner 26/10).

Owner : « si laforge-qwen est trop bete, faire le jugement par un modele fort ». Le JUGE (thymus,
forge_mutation_judge.juger_module_avec_gain) est deterministe -- tests, import reel, gain -- et reste tel quel ;
le maillon faible est la GENERATION (laforge-qwen local : 3 reponses sans correctif le 26/10 12:55).
Cascade LAFORGE_PATCHER_PROVIDERS (defaut groq = gpt-oss-120b gratuit, puis ollama) ; une panne passe au suivant.
"""
import json
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools"), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_self_patcher as sp  # noqa: E402

SPEC = '{"target_file": "app/x.py", "patch_search": "a", "patch_replace": "b", "description": "d"}'


def _reponse(texte):
    return {"result": {"content": [{"text": texte}]}}


def test_le_fort_est_appele_d_abord(monkeypatch):
    monkeypatch.delenv("LAFORGE_PATCHER_PROVIDERS", raising=False)
    vus = []
    monkeypatch.setattr(sp, "_hub_call", lambda tool, args, timeout=90: (vus.append(args["provider"]) or _reponse(SPEC)))
    spec = sp._llm_generate_patch(["bfcl"], "")
    assert vus == ["groq"] and spec["target_file"] == "app/x.py"


def test_panne_du_fort_repli_local(monkeypatch):
    monkeypatch.delenv("LAFORGE_PATCHER_PROVIDERS", raising=False)
    vus = []

    def hub(tool, args, timeout=90):
        vus.append(args["provider"])
        return {"error": "HTTP 429"} if args["provider"] == "groq" else _reponse(SPEC)

    monkeypatch.setattr(sp, "_hub_call", hub)
    spec = sp._llm_generate_patch(["bfcl"], "")
    assert vus == ["groq", "ollama"] and spec["target_file"] == "app/x.py"


def test_tous_en_panne_reste_un_echec_amont(monkeypatch):
    monkeypatch.setenv("LAFORGE_PATCHER_PROVIDERS", "groq,ollama")
    monkeypatch.setattr(sp, "_hub_call", lambda tool, args, timeout=90: {"error": "panne"})
    assert "echec_amont" in sp._llm_generate_patch(["bfcl"], "")


def test_cascade_configurable(monkeypatch):
    monkeypatch.setenv("LAFORGE_PATCHER_PROVIDERS", "ollama")
    vus = []
    monkeypatch.setattr(sp, "_hub_call", lambda tool, args, timeout=90: (vus.append(args["provider"]) or _reponse(SPEC)))
    sp._llm_generate_patch(["bfcl"], "")
    assert vus == ["ollama"]
