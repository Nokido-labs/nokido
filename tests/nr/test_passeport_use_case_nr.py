"""NR 30/10 -- tranche 2 du passeport d'appel (P1_passeport_appel_3_axes_20261024) : le CAS D'USAGE du routeur arrive
jusqu'a la ligne de passeport (il valait toujours « direct » : le routeur ne le transmettait pas au proxy).

Porte par une ContextVar de forge_trace_context (meme patron que get_actor), posee par router_call autour de l'appel,
et TRANSPORTEE dans le fil de _demander_au_proxy (un ThreadPoolExecutor ne copie pas le contexte : copy_context).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_agent_proxy as AP  # noqa: E402
import forge_llm_router as R  # noqa: E402
import forge_trace_context as trace  # noqa: E402


class _Prov:
    name = "factice_prov"
    model = "factice-modele"


def test_le_passeport_lit_le_cas_d_usage_du_contexte(monkeypatch, tmp_path):
    journal = tmp_path / "passeport.jsonl"
    monkeypatch.setattr(AP, "_PASSEPORT_JOURNAL_PATH", str(journal))
    jeton = trace.set_use_case("code")
    try:
        AP._ecrire_passeport(_Prov(), usage={})
    finally:
        trace.reset_use_case(jeton)
    assert json.loads(journal.read_text(encoding="utf-8").strip())["use_case"] == "code"
    assert trace.get_use_case() == ""


def test_router_call_expose_son_cas_d_usage_pendant_l_appel(monkeypatch):
    vus = []

    class _Routeur:
        def call(self, prompt, use_case, max_tokens, **kw):
            vus.append(trace.get_use_case())
            return {"ok": True}

    monkeypatch.setattr(R, "get_router", lambda: _Routeur())
    R.router_call("bonjour", use_case="conseil", max_tokens=10, timeout=5)
    assert vus == ["conseil"]
    assert trace.get_use_case() == "", "le cas d'usage ne doit pas fuir apres l'appel"


def test_le_fil_du_pont_proxy_recoit_le_contexte():
    src = (RACINE / "app" / "forge_llm_router.py").read_text(encoding="utf-8")
    corps = src.split("def _demander_au_proxy(", 1)[1].split("\ndef ", 1)[0]
    assert "copy_context()" in corps and ".run" in corps, "le fil du pont perd la ContextVar du cas d'usage"
