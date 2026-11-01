"""NR : lanceur Codex coffre seul (jeton lu au coffre, pose dans l'env du seul enfant)."""
import os
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_R))
sys.path.insert(0, str(_R / "tools"))

import nokido_codex  # noqa: E402

FAUX = "valeur-factice-xyz"


def _lance(coffre):
    appels = []

    def faux_call(cmd, env=None):
        appels.append((cmd, env))
        return 7

    rc = nokido_codex.main(["exec", "--x"], coffre=coffre, appel=faux_call)
    return rc, appels


def test_env_enfant_porte_jeton_parent_inchange(monkeypatch):
    monkeypatch.delenv("FORGE_TOKEN_CODEX", raising=False)
    avant = dict(os.environ)
    rc, appels = _lance(lambda nom: FAUX)
    assert rc == 7
    cmd, env = appels[0]
    assert env["FORGE_TOKEN_CODEX"] == FAUX
    assert cmd[1:] == ["exec", "--x"]
    assert dict(os.environ) == avant
    assert "FORGE_TOKEN_CODEX" not in os.environ


def test_aucun_fichier_ecrit(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _lance(lambda nom: FAUX)
    assert list(tmp_path.iterdir()) == []


def test_coffre_vide_rc_non_nul_codex_non_lance(capsys):
    rc, appels = _lance(lambda nom: "")
    assert rc != 0
    assert appels == []
    assert "FORGE_TOKEN_CODEX" in capsys.readouterr().err


def test_jamais_jeton_maitre(monkeypatch):
    monkeypatch.setenv("FORGE_MCP_TOKEN", "maitre-factice")
    demandes = []

    def coffre(nom):
        demandes.append(nom)
        return FAUX

    _, appels = _lance(coffre)
    assert demandes == ["FORGE_TOKEN_CODEX"]
    assert "FORGE_MCP_TOKEN" not in appels[0][1]


def test_coffre_illisible_n_est_pas_absent(capsys):
    """UNKNOWN != NO : un coffre qui leve n'est pas un jeton absent ; le dire, code distinct, codex non lance."""
    def coffre(nom):
        raise PermissionError("acces refuse")

    rc, appels = _lance(coffre)
    err = capsys.readouterr().err
    assert appels == [] and rc == 3
    assert "ILLISIBLE" in err and "PermissionError" in err


def test_coffre_vide_ne_replie_pas_sur_maitre(monkeypatch):
    monkeypatch.setenv("FORGE_MCP_TOKEN", "maitre-factice")
    rc, appels = _lance(lambda nom: None)
    assert rc != 0 and appels == []
