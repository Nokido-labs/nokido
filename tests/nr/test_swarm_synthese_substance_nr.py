"""NR -- une synthese sans SUBSTANCE compte comme vide : la cascade passe au redacteur suivant, motif dit.

Recette reelle 29/10 11 h 40 (cli_swarm_ptr_20261029_114023.json) : gpt-oss:120b, redacteur fort, rend « We need to fetch
the file. » (26 car., planification de modele a raisonnement) ; non vide, elle a ete ACCEPTEE comme synthese. Faux
synthetiseur, aucun reseau."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_cli_swarm as S  # noqa: E402

LONG = "- mecanisme A : source x, desaccord aucun\n" * 8


def test_synthese_trop_courte_passe_au_suivant(monkeypatch):
    """Premier redacteur : 26 car. -> rejete (motif), second : texte substantiel -> retenu."""
    vus = []

    def faux(membre, _mat, _cons, max_tours=1):
        vus.append(membre)
        return {"text": "We need to fetch the file." if membre == "a:x" else LONG, "post_flight": {"vus": 1}}

    monkeypatch.setattr(S, "_synthetiser", faux)
    monkeypatch.setattr(S, "REDACTEURS_FORTS", ("a:x", "b:y"))
    ok_ans = [{"provider": "a:x", "outils_appeles": ["t", "t"], "text": "A"},
              {"provider": "b:y", "outils_appeles": ["t"], "text": "B"}]
    s, par, essais = S._synthese_cascade(ok_ans, "materiau")
    assert vus == ["a:x", "b:y"] and par == "b:y" and s["text"] == LONG
    assert essais[0]["ok"] is False and "trop courte" in (essais[0]["motif"] or "")


def test_synthese_substantielle_acceptee_directement(monkeypatch):
    """Texte substantiel du premier -> retenu, pas d'essai supplementaire."""
    monkeypatch.setattr(S, "_synthetiser", lambda m, *_a, **_k: {"text": LONG, "post_flight": {"vus": 1}})
    monkeypatch.setattr(S, "REDACTEURS_FORTS", ("a:x",))
    s, par, essais = S._synthese_cascade([{"provider": "a:x", "outils_appeles": ["t"], "text": "A"}], "m")
    assert par == "a:x" and len(essais) == 1
