"""NR : l'executeur signale LIVRAISON SANS NR / RED NON OBSERVE (observation, non bloquant)."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import forge_task_executor as fte  # noqa: E402


def _git(d, *a):
    return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t",
                           "-c", "core.hooksPath=NUL", "-c", "commit.gpgsign=false", *a],
                          capture_output=True, text=True)


def _depot(tmp_path):
    _git(tmp_path, "init", "-q")
    # identite LOCALE au depot temporaire : le compte bac a sable n'en a pas de globale (« Author identity unknown »)
    _git(tmp_path, "config", "user.email", "nr@nokido.local")
    _git(tmp_path, "config", "user.name", "nr")
    (tmp_path / "README").write_text("x")
    _git(tmp_path, "add", "README")
    _git(tmp_path, "commit", "-qm", "init", "--no-verify")
    return tmp_path


def _ecrire(d, rel, txt):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt)


def _livrer(d, monkeypatch, etat):
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_scorecard", None)  # juge hors sujet ici
    monkeypatch.setattr(fte, "_rejouer_tests_sur_commit", lambda *a, **k: etat)
    return fte._committer_pour_agent(str(d), "t1", "fait", "X")


def test_code_sans_test(tmp_path, monkeypatch):
    d = _depot(tmp_path)
    _ecrire(d, "app/m.py", "A = 1\n")
    assert "LIVRAISON SANS NR" in (_livrer(d, monkeypatch, ("ROUGE", "x")) or "")


def test_red_ne_rougit_pas(tmp_path, monkeypatch):
    d = _depot(tmp_path)
    _ecrire(d, "app/m.py", "A = 1\n")
    _ecrire(d, "tests/nr/test_m.py", "def test_a():\n    assert True\n")
    assert "RED NON OBSERVE" in (_livrer(d, monkeypatch, ("VERT", "1 passed")) or "")


def test_red_vide(tmp_path, monkeypatch):
    d = _depot(tmp_path)
    _ecrire(d, "app/m.py", "A = 1\n")
    _ecrire(d, "tests/nr/test_m.py", "def test_a():\n    assert False\n")
    assert "RED NON OBSERVE" in (_livrer(d, monkeypatch, ("ROUGE", "")) or "")


def test_red_rouge_rien_signale(tmp_path, monkeypatch):
    d = _depot(tmp_path)
    _ecrire(d, "app/m.py", "A = 1\n")
    _ecrire(d, "tests/nr/test_m.py", "def test_a():\n    assert False\n")
    note = _livrer(d, monkeypatch, ("ROUGE", "1 failed")) or ""
    assert "RED NON OBSERVE" not in note and "SANS NR" not in note
