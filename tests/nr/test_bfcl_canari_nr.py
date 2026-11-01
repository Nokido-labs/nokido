"""NR : BFCL s'arrete apres 3 cas temoins tous en erreur d'appel, sans ecrire de mesure.

Mesure 26/10 : BFCL 0/50 (LiteLLM), puis 28/50 en 429, puis modeles Groq/Cerebras retires (404) --
chaque fois 50 appels brules pour une passe que `validite_mesure` classait NON_MESURE apres coup.
Un fournisseur en panne se voit des les premiers cas : on s'arrete, on ne publie rien.
"""
import sys
import types
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools"), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_bfcl_runner as br  # noqa: E402


def _preparer(monkeypatch, tmp_path, reponses):
    appels = []

    def faux_llm(prompt, provider):
        appels.append(prompt)
        return reponses(len(appels))

    monkeypatch.setattr(br, "ensure_dataset", lambda p, c: ([{"id": i} for i in range(10)], {}))
    monkeypatch.setattr(br, "_build_prompt", lambda e, c: "q%s" % e["id"])
    monkeypatch.setattr(br, "_get_ground_truth", lambda e, a: None)
    monkeypatch.setattr(br, "call_llm", faux_llm)
    monkeypatch.setattr(br, "BFCL_DIR", tmp_path / "bfcl")
    monkeypatch.setattr(br.time, "sleep", lambda s: None)
    ancres = []
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_self_correction",
                        types.SimpleNamespace(anchor_solution=lambda **k: ancres.append(k)))
    return appels, ancres


def test_trois_pannes_d_entree_arretent_la_passe_sans_mesure(monkeypatch, tmp_path):
    appels, ancres = _preparer(monkeypatch, tmp_path, lambda n: "[ERR] 404 model not found")
    s = br.run(provider="groq", max_entries=10)
    assert len(appels) == br.CANARI_N == 3
    assert s.get("non_mesure") is True and "3/3" in s.get("canari", "")
    assert not (tmp_path / "bfcl").exists() or not list((tmp_path / "bfcl").glob("*.json"))
    assert ancres == []


def test_une_reponse_parmi_les_temoins_laisse_courir_la_passe(monkeypatch, tmp_path):
    appels, _ = _preparer(monkeypatch, tmp_path,
                          lambda n: "[ERR] 429" if n in (1, 3) else '{"name": "f", "arguments": {}}')
    s = br.run(provider="groq", max_entries=10)
    assert len(appels) == 10
    assert not s.get("non_mesure")
    assert list((tmp_path / "bfcl").glob("*.json"))
