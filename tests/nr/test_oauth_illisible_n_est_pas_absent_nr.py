"""NR -- le capteur de connexion des CLI lit le profil de l'OWNER, et un fichier ILLISIBLE n'est jamais un login absent.

Mesure 20/10 : `check_oauth` (hook [sense] oauth_cli_atrophy) annoncait missing=['copilot_cli (gh)'] a chaque tour alors
que `gh auth status` sous l'owner rendait « Logged in to github.com account user (keyring) ». Deux torts : Path.home()
designe le profil du compte qui EXECUTE (un compte de service n'a aucun login), et Path.exists() rend False sur un
acces refuse. Effet paye : l'agent a affirme « gh non connecte » et l'owner s'est reconnecte pour rien.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_remediation as R  # noqa: E402


def _profil(tmp_path, gh=True, gemini=True):
    if gh:
        p = tmp_path / "AppData" / "Roaming" / "GitHub CLI" / "hosts.yml"
        p.parent.mkdir(parents=True)
        p.write_text("github.com:\n  user: x\n", encoding="utf-8")
    if gemini:
        g = tmp_path / ".gemini" / "oauth_creds.json"
        g.parent.mkdir(parents=True)
        g.write_text("{}", encoding="utf-8")
    return tmp_path


def _signaux(monkeypatch):
    vus = []
    monkeypatch.setattr(R, "_signal", lambda nom, *a, **k: vus.append(nom) or True)
    return vus


def test_le_profil_lu_est_celui_de_l_owner_pas_du_compte_qui_execute(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_OWNER_HOME", str(_profil(tmp_path)))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "compte_de_service"))
    vus = _signaux(monkeypatch)
    out = R.check_oauth(False)
    assert out["missing_login"] == [] and "oauth_cli_atrophy" not in vus


def test_un_acces_refuse_est_illisible_et_jamais_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_OWNER_HOME", str(_profil(tmp_path)))
    vrai_stat = Path.stat

    def stat(self, *a, **k):
        if self.name == "hosts.yml":
            raise PermissionError(13, "Acces refuse")
        return vrai_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", stat)
    vus = _signaux(monkeypatch)
    out = R.check_oauth(False)
    assert "copilot_cli (gh)" not in out["missing_login"]
    assert "copilot_cli (gh)" in out.get("illisible", [])
    assert "oauth_cli_atrophy" not in vus


def test_un_login_vraiment_absent_reste_signale(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_OWNER_HOME", str(_profil(tmp_path, gh=False)))
    vus = _signaux(monkeypatch)
    out = R.check_oauth(False)
    assert out["missing_login"] == ["copilot_cli (gh)"] and "oauth_cli_atrophy" in vus


def test_profil_owner_introuvable_rend_tout_illisible(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_OWNER_HOME", str(tmp_path / "n_existe_pas"))
    vus = _signaux(monkeypatch)
    out = R.check_oauth(False)
    assert out["missing_login"] == [] and len(out.get("illisible", [])) == 2 and "oauth_cli_atrophy" not in vus
