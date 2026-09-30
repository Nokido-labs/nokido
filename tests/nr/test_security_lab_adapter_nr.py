"""NR adapter sécurité : la capacité offensive est OFF par défaut (fail-closed).

Vérifie l'EFFET (bornage), pas l'import. Aucun module offensif n'est chargé : le
gate coupe AVANT tout import de forge_ctf_*.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
import forge_security_lab_adapter as ad


def test_fail_closed_par_defaut(monkeypatch, tmp_path):
    monkeypatch.delenv("NOKIDO_SECURITY_LAB", raising=False)
    monkeypatch.setattr(ad, "_SENTINEL", tmp_path / "absent.enabled")
    assert ad.lab_authorized() is False
    assert ad.get_ctf_browser_supervisor_gated() is None


def test_run_ctf_solver_disabled_sans_import_offensif(monkeypatch, tmp_path):
    monkeypatch.delenv("NOKIDO_SECURITY_LAB", raising=False)
    monkeypatch.setattr(ad, "_SENTINEL", tmp_path / "absent.enabled")
    r = asyncio.run(ad.run_ctf_solver(intent="x"))
    assert "SECURITY_LAB_DISABLED" in r
    assert "forge_ctf_solver" not in sys.modules  # gate AVANT l'import offensif


def test_autorisation_env(monkeypatch, tmp_path):
    monkeypatch.setattr(ad, "_SENTINEL", tmp_path / "absent.enabled")
    monkeypatch.setenv("NOKIDO_SECURITY_LAB", "1")
    assert ad.lab_authorized() is True


def test_autorisation_sentinel(monkeypatch, tmp_path):
    monkeypatch.delenv("NOKIDO_SECURITY_LAB", raising=False)
    sentinel = tmp_path / "security_lab.enabled"
    sentinel.write_text("ok", encoding="utf-8")
    monkeypatch.setattr(ad, "_SENTINEL", sentinel)
    assert ad.lab_authorized() is True


def test_lab_path_env_prioritaire(monkeypatch, tmp_path):
    lab = tmp_path / "lab"
    lab.mkdir()
    monkeypatch.setenv("NOKIDO_SECURITY_LAB_PATH", str(lab))
    assert ad.lab_path() == lab


def test_lab_path_absent_rend_none(monkeypatch, tmp_path):
    monkeypatch.delenv("NOKIDO_SECURITY_LAB_PATH", raising=False)
    monkeypatch.setattr(ad, "_LAB_PATH_FILE", tmp_path / "absent.path")
    monkeypatch.setattr(ad, "_LAB_DEFAULTS", ())
    assert ad.lab_path() is None


def test_configure_lab_path_ecrit_et_relit(monkeypatch, tmp_path):
    lab = tmp_path / "redteam"
    lab.mkdir()
    monkeypatch.delenv("NOKIDO_SECURITY_LAB_PATH", raising=False)
    monkeypatch.setattr(ad, "_LAB_PATH_FILE", tmp_path / "security_lab.path")
    monkeypatch.setattr(ad, "_LAB_DEFAULTS", ())
    ad.configure_lab_path(lab)
    assert ad.lab_path() == lab.resolve()


def test_configure_n_autorise_pas(monkeypatch, tmp_path):
    # Raccorder le lab (configure_lab_path) ne l'ACTIVE pas : fail-closed maintenu.
    monkeypatch.delenv("NOKIDO_SECURITY_LAB", raising=False)
    monkeypatch.setattr(ad, "_SENTINEL", tmp_path / "absent.enabled")
    monkeypatch.setattr(ad, "_LAB_PATH_FILE", tmp_path / "security_lab.path")
    ad.configure_lab_path(tmp_path / "redteam")
    assert ad.lab_authorized() is False
