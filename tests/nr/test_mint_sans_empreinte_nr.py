"""NR -- l'outil de frappe des jetons d'agent n'affiche JAMAIS d'empreinte de la valeur (16/10).

RED ecrit par Claude, code par Mistral Vibe (premiere tache de l'executeur MISTRAL). Regle owner : d'un secret on
n'affiche que des booleens, pas meme une empreinte. tools/forge_vault_mint_agent_token.py imprimait
« empreinte_sha256_8 » avant et apres l'ecriture ; la verification de rotation (« l'empreinte n'a PAS change »)
doit rester INTERNE -- comparer sans jamais imprimer.
Integre le 9/11 (lot 6, preserve/mistral-20261019-003551, porte par OPENCODE_DEFAUT2 e8b4a8ef6, relu par Claude).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import forge_vault_mint_agent_token as M  # noqa: E402


@pytest.fixture
def coffre(monkeypatch):
    from nokido_agent.app import forge_secrets as s

    store = {}
    monkeypatch.setattr(s, "get_secret", lambda k: store.get(k))
    monkeypatch.setattr(s, "set_secret", lambda k, v: store.__setitem__(k, v) or True)
    monkeypatch.setattr(s, "invalidate_cache", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(M, "_ring_declare", lambda agent: 2)
    return store


def _empreinte(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()[:8]


def test_la_frappe_n_affiche_ni_valeur_ni_empreinte(coffre, capsys):
    assert M.main(["--agent", "ESSAI_NR"]) == 0
    v = coffre["FORGE_TOKEN_ESSAI_NR"]
    out = capsys.readouterr().out
    assert v not in out and _empreinte(v) not in out, "valeur ou empreinte affichee"
    assert "empreinte" not in out.lower()


def test_la_rotation_se_verifie_sans_rien_afficher(coffre, capsys):
    coffre["FORGE_TOKEN_ESSAI_NR"] = "a" * 64
    assert M.main(["--agent", "ESSAI_NR", "--rotate"]) == 0
    v = coffre["FORGE_TOKEN_ESSAI_NR"]
    assert v != "a" * 64, "la rotation n'a rien remplace"
    out = capsys.readouterr().out
    for x in ("a" * 64, v):
        assert _empreinte(x) not in out
    assert "empreinte" not in out.lower()


def test_une_rotation_sans_effet_reste_dite(coffre, monkeypatch, capsys):
    """Le garde existant ne se perd pas en route : ecriture rapportee OK mais valeur inchangee -> rc 1."""
    from nokido_agent.app import forge_secrets as s

    coffre["FORGE_TOKEN_ESSAI_NR"] = "b" * 64
    monkeypatch.setattr(s, "set_secret", lambda k, v: True)
    assert M.main(["--agent", "ESSAI_NR", "--rotate"]) == 1
    assert _empreinte("b" * 64) not in capsys.readouterr().out
