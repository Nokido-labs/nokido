"""NR -- le juge de l'executeur lit le CONTENU livre, pas seulement le nombre de commits (racine R3, 17/10).

Mesure 17/10 : la « livraison » de Vibe 074957e12, jugee SUCCESS, ne contenait que .vibe/config.toml (ecrit par
l'executeur) et le RED pose par Claude AVANT la tache -- zero ligne d'implementation (auto-commit de ce qui etait deja
la). Et rien n'empechait un delegue de « reussir » en supprimant ou en modifiant un test existant (reward hacking).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402


def _git(repo, *a):
    subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo), *a], check=True, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")


def _depot(tmp_path):
    repo = tmp_path / "wt"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _detail(pointeur):
    return '{"intent":"OK_DONE","pointer_ref":"%s"}' % pointeur


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def test_config_agent_seule_est_une_livraison_vide(tmp_path):
    repo = _depot(tmp_path)
    avant = E._etat_git(str(repo))
    (repo / ".vibe").mkdir()
    (repo / ".vibe" / "config.toml").write_text("active_model = 'x'\n", encoding="utf-8")
    _commit(repo, "livraison")
    ok, effet, _ = E._juger_livraison(True, _detail(".vibe/config.toml"), str(repo), avant)
    assert ok is False and "LIVRAISON VIDE" in effet, effet


def test_le_cas_reel_de_vibe_red_pre_pose_et_config_seuls_est_vide(tmp_path):
    """074957e12 rejoue : le RED est la AVANT la tache (non committe), l'auto-commit l'emporte avec la config."""
    repo = _depot(tmp_path)
    (repo / "tests" / "nr").mkdir()
    (repo / "tests" / "nr" / "test_red.py").write_text("def test_red():\n    assert False\n", encoding="utf-8")
    avant = E._etat_git(str(repo))
    h, n = avant                      # le couple se deballe toujours en deux (lecteurs existants intacts)
    assert n == 1 and "tests/nr/" in "".join(avant.preposes)
    (repo / ".vibe").mkdir()
    (repo / ".vibe" / "config.toml").write_text("active_model = 'x'\n", encoding="utf-8")
    _commit(repo, "chore(MISTRAL): livraison")
    ok, effet, _ = E._juger_livraison(True, _detail(".vibe/config.toml"), str(repo), avant)
    assert ok is False and "LIVRAISON VIDE" in effet, effet


def test_un_test_supprime_n_est_jamais_une_reussite(tmp_path):
    repo = _depot(tmp_path)
    avant = E._etat_git(str(repo))
    _git(repo, "rm", "-q", "tests/test_x.py")
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    _commit(repo, "plus vert")
    ok, effet, _ = E._juger_livraison(True, _detail("app.py"), str(repo), avant)
    assert ok is False and "TESTS TOUCHES" in effet, effet


def test_modifier_un_test_autorise_par_la_tache_reste_une_reussite(tmp_path):
    repo = _depot(tmp_path)
    avant = E._etat_git(str(repo))
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert 1 == 1\n", encoding="utf-8")
    (repo / "app.py").write_text("x = 3\n", encoding="utf-8")
    _commit(repo, "fix")
    ok, effet, _ = E._juger_livraison(True, _detail("app.py"), str(repo), avant, autorises=["tests/test_x.py"])
    assert ok is True and "AUTORISES" in effet, effet
    assert E._tests_autorises("Corrige le NR.\ntests_autorises: tests/test_x.py, tests/nr/test_y.py\n") == [
        "tests/test_x.py", "tests/nr/test_y.py"]


def test_un_artefact_deja_la_n_est_pas_une_production(tmp_path):
    """Revue adverse de Codex (17/10) : sans commit, un pointer_ref vers un fichier PREEXISTANT passait."""
    repo = _depot(tmp_path)
    avant = E._etat_git(str(repo))
    ok, effet, _ = E._juger_livraison(True, _detail("app.py"), str(repo), avant)
    assert ok is False and "ARTEFACT NON PRODUIT" in effet, effet


def test_une_reponse_en_texte_sans_fichier_reste_jugee_comme_avant(tmp_path):
    """Une revue en lecture seule pointe tasks.db, pas un fichier : elle n'est pas concernee."""
    repo = _depot(tmp_path)
    avant = E._etat_git(str(repo))
    ok, effet, _ = E._juger_livraison(True, _detail("tasks.db:revue_x"), str(repo), avant)
    assert "ARTEFACT NON PRODUIT" not in effet, effet


def test_un_test_renomme_hors_de_tests_est_un_test_touche(tmp_path):
    """Revue adverse de Codex (17/10) : pour un renommage, seul le NOUVEAU chemin etait vu."""
    repo = _depot(tmp_path)
    avant = E._etat_git(str(repo))
    (repo / "archive").mkdir()
    _git(repo, "mv", "tests/test_x.py", "archive/x.py")
    (repo / "app.py").write_text("x = 9\n", encoding="utf-8")
    _commit(repo, "range les tests")
    ok, effet, _ = E._juger_livraison(True, _detail("app.py"), str(repo), avant)
    assert ok is False and "TESTS TOUCHES" in effet, effet


def test_une_vraie_livraison_reste_une_reussite(tmp_path):
    repo = _depot(tmp_path)
    avant = E._etat_git(str(repo))
    (repo / "app.py").write_text("x = 2\n\ndef f():\n    return x\n", encoding="utf-8")
    (repo / "tests" / "test_f.py").write_text("def test_f():\n    assert True\n", encoding="utf-8")
    _commit(repo, "feat")
    ok, effet, _ = E._juger_livraison(True, _detail("app.py"), str(repo), avant)
    assert ok is True, effet
