"""NR : HumanEval s'arrete apres 3 cas temoins tous en erreur d'appel, sans ecrire de mesure.

Mesure 26/10 : le « 7,3 % » HumanEval d'octobre etait 152 llm_error sur 164 (pannes Groq), publie comme
une mesure. Meme canari que BFCL (416565d0c) : un fournisseur en panne se voit des les premiers cas.
"""
import sys
import types
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools"), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_humaneval_runner as he  # noqa: E402


def test_trois_pannes_d_entree_arretent_la_passe_sans_mesure(monkeypatch, tmp_path):
    appels = []
    monkeypatch.setattr(he, "ensure_dataset",
                        lambda: [{"task_id": "HumanEval/%d" % i, "prompt": "def f%d():\n" % i,
                                  "entry_point": "f%d" % i, "test": ""} for i in range(10)])
    monkeypatch.setattr(he, "_build_prompt", lambda e: e["prompt"])
    monkeypatch.setattr(he, "call_llm", lambda prompt, provider: appels.append(prompt) or "[ERR] 404 model not found")
    monkeypatch.setattr(he, "_autotest_quarantine", lambda: set())
    monkeypatch.setattr(he, "HE_DIR", tmp_path / "he")
    monkeypatch.setattr(he.time, "sleep", lambda s: None)
    ancres = []
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_self_correction",
                        types.SimpleNamespace(anchor_solution=lambda **k: ancres.append(k)))
    s = he.run(provider="groq", max_entries=10)
    assert len(appels) == he.CANARI_N == 3
    assert s.get("non_mesure") is True and "3/3" in s.get("canari", "")
    assert not (tmp_path / "he").exists() or not list((tmp_path / "he").glob("*.json"))
    assert ancres == []
