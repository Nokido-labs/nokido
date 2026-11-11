# -*- coding: utf-8 -*-
"""NR (owner 3/11 « reparer Nemotron Super » pour le generateur des bancs) : la cascade du generateur essaie d'abord
le fort GRATUIT prouve -- nvidia_nemotron_super (nemotron-3.5-super-vl-120b, code correct en 1,8 s, accepte par
`ask`, job_87516ee25c57) -- puis groq, puis le local. Mesure 3/11 : relance des bancs avec « groq,ollama » =
0 amelioration sur 4 bancs (NR casses, noyaux qui ne compilent pas, aucun candidat sur redaction_dlp).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_self_patcher as SP  # noqa: E402


def test_cascade_essaie_nemotron_d_abord(monkeypatch):
    monkeypatch.delenv("LAFORGE_PATCHER_PROVIDERS", raising=False)
    vus = []

    def faux_hub(action, args):
        vus.append(args["provider"])
        return {"result": {"content": [{"text": "proposition"}]}}

    monkeypatch.setattr(SP, "_hub_call", faux_hub)
    texte, echec = SP._ask_cascade("consigne")
    assert texte == "proposition" and echec is None
    assert vus == ["nvidia_nemotron_super"], vus


def test_repli_groq_puis_local_si_nemotron_echoue(monkeypatch):
    monkeypatch.delenv("LAFORGE_PATCHER_PROVIDERS", raising=False)
    vus = []

    def faux_hub(action, args):
        vus.append(args["provider"])
        return {"error": "quota"} if args["provider"] != "ollama" else {"result": {"content": [{"text": "x"}]}}

    monkeypatch.setattr(SP, "_hub_call", faux_hub)
    SP._ask_cascade("consigne")
    assert vus == ["nvidia_nemotron_super", "groq", "lmstudio", "ollama"], vus   # 3/11 : LM Studio avant Ollama
