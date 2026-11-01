"""NR -- synthese du swarm : reprise `length` a max_tokens double, puis membre suivant ; motif avec finish_reason.

Recette reelle 29/10 09 h 56 (cli_swarm_ptr_20261029_095645.json) : 3/3 membres ok, synthese confiee a
nemotron-3-ultra -> VIDE (« reponse vide »), sans finish_reason ni reprise : un seul tour, budget probablement
consomme par le raisonnement. Faux _boucle_membre / faux _synthetiser, aucun reseau."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_cli_swarm as S  # noqa: E402
import forge_tool_call_probe as P  # noqa: E402


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _membres_factices_forts(monkeypatch):
    """ARBITRAGE 29/10 : les membres factices sont declares forts (regle REDACTEURS_FORTS) ; assertions inchangees."""
    monkeypatch.setattr(S, "REDACTEURS_FORTS", ("a:x", "b:y"))
    monkeypatch.setattr(S, "SYNTHESE_MIN_CAR", 0)  # 29/10 : syntheses factices courtes ; substance testee a part


def test_synthetiser_reprend_length_a_max_tokens_double(monkeypatch):
    """Vide + finish_reason=length -> 1 reprise sous max_tokens_double ; texte retenu ; reprise dite."""
    doubles = []

    def faux(_hf, _agent, _texte, _max, trace):
        doubles.append(P.max_tokens_double_actif())
        if len(doubles) == 1:
            trace["finish_reason"], trace["raisonnement_car"] = "length", 3000
            return [{"role": "assistant", "content": ""}], 1
        return [{"role": "assistant", "content": "synthese"}], 1

    monkeypatch.setattr(S, "_boucle_membre", faux)
    r = S._synthetiser("p:m", "materiau", "consigne")
    assert doubles == [False, True]
    assert r["text"] == "synthese" and r.get("reprise_length") is True


def test_synthetiser_vide_porte_le_finish_reason(monkeypatch):
    """Vide sans length : pas de reprise ; le motif dit finish_reason et raisonnement."""
    def faux(_hf, _agent, _texte, _max, trace):
        trace["finish_reason"], trace["raisonnement_car"] = "stop", 12
        return [{"role": "assistant", "content": ""}], 1

    monkeypatch.setattr(S, "_boucle_membre", faux)
    r = S._synthetiser("p:m", "materiau", "consigne")
    assert r["text"] == "" and "finish_reason=stop" in r.get("error", "")


def test_cascade_passe_au_membre_suivant(monkeypatch):
    """1er choisi (le plus lu) vide -> membre suivant ; synthese_par = celui qui a rendu ; essais dits."""
    vus = []

    def faux_synth(membre, _mat, _cons, max_tours=1):
        vus.append(membre)
        return {"text": "" if membre == "a:x" else "ok", "post_flight": {"vus": 1}, "error": "vide"}

    monkeypatch.setattr(S, "_synthetiser", faux_synth)
    ok_ans = [{"provider": "b:y", "outils_appeles": ["t"], "text": "B"},
              {"provider": "a:x", "outils_appeles": ["t", "t", "t"], "text": "A"}]
    s, par, essais = S._synthese_cascade(ok_ans, "materiau")
    assert vus == ["a:x", "b:y"] and par == "b:y" and s["text"] == "ok"
    assert [e["membre"] for e in essais] == ["a:x", "b:y"]
