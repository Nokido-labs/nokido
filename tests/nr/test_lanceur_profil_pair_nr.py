"""NR -- profil `pair` du lanceur : les secrets du connecteur des pairs, jamais ceux du pont GitHub.

Connecteur des pairs cloud (2026-09-28). Le lanceur du pont (`forge_bridge_launch`) gagne un profil :
  - `pair` lit NOKIDO_PAIR_OAUTH_APPARIEMENT (code CHOISI par l'owner) et NOKIDO_PAIR_CAPABILITY_KEY
    au coffre, et les pose sous les noms qu'attend le serveur ; il ne lit AUCUN secret du pont ;
  - sans code d'appariement : refus de demarrer, en nommant la bonne variable ;
  - registre des clients OAuth propre (sandbox/pair_oauth_clients.json), commande sans secret ;
  - le profil `github` reste le defaut, inchange.
Valeurs factices ; le coffre est substitue.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lanceur(monkeypatch):
    spec = importlib.util.spec_from_file_location("nr_lanceur_pair", ROOT / "tools/forge_bridge_launch.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    lus = []
    coffre = {"NOKIDO_PAIR_OAUTH_APPARIEMENT": "code-owner-test", "NOKIDO_PAIR_CAPABILITY_KEY": "cle-pair-test",
              "NOKIDO_BRIDGE_OAUTH_APPARIEMENT": "code-du-pont", "GITHUB_TOKEN": "jeton-github-test"}
    monkeypatch.setattr(m, "lire", lambda nom: lus.append(nom) or coffre.get(nom))
    return m, coffre, lus


def test_le_profil_pair_lit_ses_secrets_et_pas_ceux_du_pont(lanceur):
    m, _coffre, lus = lanceur
    valeurs = m.valeurs_pair()
    assert valeurs == {"NOKIDO_BRIDGE_OAUTH_APPARIEMENT": "code-owner-test",
                       "NOKIDO_BRIDGE_CAPABILITY_KEY": "cle-pair-test"}
    assert set(lus) == {"NOKIDO_PAIR_OAUTH_APPARIEMENT", "NOKIDO_PAIR_CAPABILITY_KEY"}


def test_sans_code_owner_le_connecteur_ne_demarre_pas(lanceur, capsys):
    m, coffre, _lus = lanceur
    del coffre["NOKIDO_PAIR_OAUTH_APPARIEMENT"]
    assert m.main(["--passerelle", "pair", "--dry-run"]) == 2
    assert "NOKIDO_PAIR_OAUTH_APPARIEMENT" in capsys.readouterr().err


def test_dry_run_pair_registre_propre_et_commande_sans_secret(lanceur, capsys):
    m, _coffre, _lus = lanceur
    assert m.main(["--passerelle", "pair", "--dry-run"]) == 0
    err = capsys.readouterr().err
    assert "pair_oauth_clients.json" in err and "forge_pair_mcp.py" in err
    for secret in ("code-owner-test", "cle-pair-test"):
        assert secret not in err
    cmd = m.commande(8793, "pair")
    assert cmd[-2:] == ["--port", "8793"] and cmd[1].endswith("forge_pair_mcp.py")


def test_le_profil_github_reste_le_defaut(lanceur):
    m, _coffre, _lus = lanceur
    assert m.commande()[1].endswith("forge_github_bridge_mcp.py")
    assert m.commande(8791)[-2:] == ["--port", "8791"]
