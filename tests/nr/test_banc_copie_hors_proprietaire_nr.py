"""NR (29/10) : la copie isolee du banc d'amelioration doit marcher sous un compte qui ne possede pas le depot.

Mesure du 29/10 (job_b766def5086e, sonde job_bd7ee2c4fde5) : sous LaForgeSbxOnline, `git worktree add` rend 128
(« detected dubious ownership ») et la recette reelle meurt avant la reference. `git -c safe.directory=<depot>
archive HEAD` passe en lecture seule (rc 0) : la copie se replie sur l'archive, sans rien ecrire dans `.git/`.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _banc():
    spec = importlib.util.spec_from_file_location("forge_banc_amelioration_nr_copie",
                                                  ROOT / "tools" / "forge_banc_amelioration.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m  # @dataclass resout son module par sys.modules
    spec.loader.exec_module(m)
    return m


def _depot(tmp_path: Path) -> Path:
    d = tmp_path / "depot"
    (d / "tools").mkdir(parents=True)
    (d / "tools" / "x.py").write_text("A = 1\n", encoding="utf-8")
    for argv in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git", "-C", str(d), *argv], check=True, capture_output=True)
    return d


def test_copie_par_archive_sans_toucher_git(tmp_path):
    m = _banc()
    d = _depot(tmp_path)
    dest = tmp_path / "copies" / "c1"
    m._copier_archive(d, dest)
    assert (dest / "tools" / "x.py").read_text(encoding="utf-8") == "A = 1\n"
    assert not (d / ".git" / "worktrees").exists()


def test_repli_sur_archive_quand_worktree_refuse(tmp_path, monkeypatch):
    m = _banc()
    d = _depot(tmp_path)

    def refus(racine, dest):
        raise subprocess.CalledProcessError(128, ["git", "worktree", "add"], stderr="fatal: detected dubious ownership")

    monkeypatch.setattr(m, "_worktree_add", refus)
    dest = tmp_path / "copies" / "c2"
    m._copier_worktree(d, dest)
    assert (dest / "tools" / "x.py").exists()
