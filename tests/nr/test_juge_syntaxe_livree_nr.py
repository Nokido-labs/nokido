"""NR -- un .py livre qui ne compile pas n'est pas une livraison reussie (20/10).

Mesure 20/10 (rejeu de job_499ed100 sous Vibe 3.0.1 / codestral) : Vibe ecrit app/forge_docker_agent.py avec trois
lignes mal indentees, sans la fonction demandee, et conclut OK_DONE. Le juge ne lisait que le NOMBRE de commits, la
liste des fichiers et les tests touches : un fichier qui ne compile meme pas aurait ete committe, compte comme une
reussite, et recompense.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402

CASSE = "def release():\n    try:\n        if A:\n    A.unlink()\n            A.unlink()\n    except Exception:\n        pass\n"


def _git(repo, *a):
    subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo), *a], check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")


def _depot(tmp_path):
    repo = tmp_path / "wt"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "app").mkdir()
    (repo / "app" / "agent.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _livrer(repo, texte):
    (repo / "app" / "agent.py").write_text(texte, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "chore(MISTRAL): livraison")


def test_un_py_qui_ne_compile_pas_est_refuse(tmp_path):
    repo = _depot(tmp_path)
    avant = E._etat_git(str(repo))
    _livrer(repo, CASSE)
    ok, effet, _ = E._juger_livraison(True, '{"intent":"OK_DONE","pointer_ref":"app/agent.py"}', str(repo), avant)
    assert ok is False and "[SYNTAXE INVALIDE]" in effet and "app/agent.py" in effet, effet


def test_un_py_valide_passe(tmp_path):
    repo = _depot(tmp_path)
    avant = E._etat_git(str(repo))
    _livrer(repo, "x = 2\n")
    ok, effet, _ = E._juger_livraison(True, '{"intent":"OK_DONE","pointer_ref":"app/agent.py"}', str(repo), avant)
    assert ok is True and "SYNTAXE" not in effet, effet


def test_le_verdict_d_une_syntaxe_invalide_est_rejetee():
    effet = "[effet observe] commits produits : 1 (a..b) ; fichiers non commites : 0 ; [SYNTAXE INVALIDE] app/agent.py:4"
    assert E.verdict_automatique(False, effet, "", None) == "REJETEE"
