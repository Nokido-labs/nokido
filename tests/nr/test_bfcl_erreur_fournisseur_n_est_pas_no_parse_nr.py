"""NR : un appel fournisseur rate est une `llm_error`, jamais un `no_parse` (mesure 26/10).

Relance BFCL du 26/10 13:18 : 0/50, les 50 en `no_parse` en 0,16 s, LiteLLM en erreur -- `_router_call` rendait
« [ERR] router cloud KO » comme TEXTE, `errors` restait a 0 (seule une exception comptait) et le parseur classait
l'erreur en reponse illisible. Le fichier passait pour une mesure (0 %) et eval_fitness ouvrait une fausse
regression 94 -> 0. Une erreur d'appel doit etre NOMMEE pour que validite_mesure la reconnaisse.
"""
import json
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools"), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_bfcl_runner as fr  # noqa: E402
import nokido_agent.app.forge_benchmark_adapter as ad  # noqa: E402


def _poser(monkeypatch, tmp_path, reponse):
    monkeypatch.setattr(fr, "ensure_dataset", lambda path, cat: ([{"id": "q1"}, {"id": "q2"}], {}))
    monkeypatch.setattr(fr, "_build_prompt", lambda e, c: "prompt")
    monkeypatch.setattr(fr, "_get_ground_truth", lambda e, a: {"f": {"x": [1]}})
    monkeypatch.setattr(fr, "call_llm", lambda p, prov="groq": reponse)
    bfcl = tmp_path / "bfcl"
    bfcl.mkdir()
    monkeypatch.setattr(fr, "BFCL_DIR", bfcl)
    return bfcl


def test_une_erreur_d_appel_rendue_en_texte_est_une_llm_error(monkeypatch, tmp_path):
    bfcl = _poser(monkeypatch, tmp_path, "[ERR] router cloud KO (gpt-oss: litellm.APIError)")
    s = fr.run(provider="router", max_entries=2, category="simple", tag="nr")
    assert s["errors"] == 2
    assert s["fail_reasons"] == {"llm_error": 2}
    assert all(str(r.get("reason", "")).startswith("llm_error") for r in s["results"])
    # bout en bout : le garde de validite reconnait ce fichier comme une NON-mesure
    monkeypatch.setattr(ad, "RAG", tmp_path)
    v = ad.validite_mesure("bfcl")
    assert v["valide"] is False and "NON_MESURE" in v["raison"]
    assert len(list(bfcl.glob("*.json"))) == 1


def test_une_vraie_reponse_illisible_reste_no_parse(monkeypatch, tmp_path):
    _poser(monkeypatch, tmp_path, "je ne sais pas appeler cette fonction")
    s = fr.run(provider="router", max_entries=2, category="simple", tag="nr")
    assert s["errors"] == 0 and "llm_error" not in s["fail_reasons"]
