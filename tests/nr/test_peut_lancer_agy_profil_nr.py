"""7/11 : le controle du profil agy cherchait AppData/Local/agy, qui ne porte que le binaire : un profil valide etait refuse."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as ex  # noqa: E402


def _binaire(tmp_path, monkeypatch):
    b = tmp_path / "agy.exe"
    b.write_text("x", encoding="utf-8")
    monkeypatch.setenv("LAFORGE_AGY_BIN", str(b))


def test_profil_gemini_accepte(tmp_path, monkeypatch):
    _binaire(tmp_path, monkeypatch)
    h = tmp_path / "exec"
    (h / ".gemini" / "antigravity-cli").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_AGY_HOME", str(h))
    assert ex._peut_lancer_agy()[0] is True


def test_ancienne_forme_acceptee(tmp_path, monkeypatch):
    _binaire(tmp_path, monkeypatch)
    h = tmp_path / "ancien"
    (h / "AppData" / "Local" / "agy").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_AGY_HOME", str(h))
    assert ex._peut_lancer_agy()[0] is True


def test_profil_absent_refuse_et_dit(tmp_path, monkeypatch):
    _binaire(tmp_path, monkeypatch)
    h = tmp_path / "vide"
    h.mkdir()
    monkeypatch.setenv("LAFORGE_AGY_HOME", str(h))
    ok, motif = ex._peut_lancer_agy()
    assert ok is False and "profil agy absent" in motif
