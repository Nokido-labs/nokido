"""NR -- la soif epistemique ne s'eteint plus sur la panne d'UN fournisseur (2026-10-13).

Cycle reel du 13/10 (job_5ca50549f6c1) : 32 min de scan, 50 gaps detectes, puis Cerebras -> HTTP 402 Payment Required,
0 theme genere, 0 veille poussee, rc=0. La generation des themes de corpus ne connaissait qu'un fournisseur (et lui
envoyait meme la cle Groq a defaut de la sienne).

Invariants :
- Cerebras en echec HTTP -> les themes viennent du repli local (forge_watch_agent._llm_local : Ollama puis Groq) ;
- sans cle Cerebras -> repli local directement, jamais une cle Groq envoyee a l'URL Cerebras ;
- repli local indisponible aussi -> themes de SOI seuls, et le volet corpus eteint est DIT (log ERROR).
"""
# pylint: disable=protected-access
import json
import logging
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_curiosity_driver as C  # noqa: E402
from nokido_agent.app import forge_secrets as S  # noqa: E402
from nokido_agent.app import forge_watch_agent as W  # noqa: E402

_GAPS = [{"type": "domain_stale", "domain": "ia", "age_days": 40}]
_REPONSE = json.dumps({"themes": [{"theme": "agents autonomes regulation memoire 2026", "rationale": "r",
                                   "gap_type": "domain_stale"}]})


def _cles(monkeypatch, cerebras):
    monkeypatch.setattr(S, "get_secret", lambda nom: cerebras if nom == "CEREBRAS_API_KEY" else "cle-groq")


def _cerebras_402(*_a, **_k):
    raise urllib.error.HTTPError("https://api.cerebras.ai", 402, "Payment Required", {}, None)


def test_cerebras_en_402_le_repli_local_genere_les_themes(monkeypatch):
    """Le cas mesure : 402, et le repli local rend un theme exploitable."""
    _cles(monkeypatch, "cle-cerebras")
    monkeypatch.setattr(C, "_cerebras_call", _cerebras_402)
    monkeypatch.setattr(W, "_llm_local", lambda prompt: _REPONSE)
    themes = C.generate_themes_for_gaps(_GAPS, n=3)
    assert [t["theme"] for t in themes] == ["agents autonomes regulation memoire 2026"]


def test_sans_cle_cerebras_pas_d_appel_cerebras_et_repli_local(monkeypatch):
    """Pas de cle Cerebras : Cerebras n'est pas appele (la cle Groq n'y part plus), le repli local l'est."""
    _cles(monkeypatch, None)
    appels = []
    monkeypatch.setattr(C, "_cerebras_call", lambda prompt, key, **_k: appels.append(key) or _REPONSE)
    monkeypatch.setattr(W, "_llm_local", lambda prompt: _REPONSE)
    themes = C.generate_themes_for_gaps(_GAPS, n=3)
    assert appels == []
    assert len(themes) == 1


def test_tout_en_panne_themes_de_soi_seuls_et_c_est_dit(monkeypatch, caplog):
    """Cerebras 402 et repli local muet : on rend les themes de SOI et on DIT le volet corpus eteint."""
    _cles(monkeypatch, "cle-cerebras")
    monkeypatch.setattr(C, "_cerebras_call", _cerebras_402)
    monkeypatch.setattr(W, "_llm_local", lambda prompt: "ERR:no_llm")
    with caplog.at_level(logging.ERROR):
        themes = C.generate_themes_for_gaps(_GAPS, n=3)
    assert themes == C._self_gap_themes(_GAPS)[:3]
    assert any("volet CORPUS eteint" in r.getMessage() for r in caplog.records)
