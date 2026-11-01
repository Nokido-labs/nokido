"""NR -- le juge cherche un rapport relatif dans le workdir de l'executeur (worktree) avant l'arbre partage.

22/10 (job_e82e3efd, job_d53ed584, job_e140415a, job_678eddc1) : depuis 3039e0526 le rapport vit dans
nokido_worktrees/<agent>/sandbox/workspace/ ; pointer_ref composite « <commit> + chemin » mal lu.
"""
from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402


def _detail(p):
    return '{"intent":"OK_DONE","pointer_ref":"%s"}' % p


def _wd(tmp_path):
    wd = tmp_path / "wt"
    wd.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(wd), *a], check=True, capture_output=True)
    (wd / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(wd), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(wd), "commit", "-q", "-m", "i"], check=True, capture_output=True)
    sha = subprocess.run(["git", "-C", str(wd), "rev-parse", "HEAD"], capture_output=True, text=True,
                         errors="replace").stdout.strip()
    return wd, sha


def _rel():
    return "sandbox/workspace/rapport_nr_%s.md" % uuid.uuid4().hex


def _ecrit(wd):
    rel = _rel()
    (wd / rel).parent.mkdir(parents=True)
    (wd / rel).write_text("r", encoding="utf-8")
    return rel


def test_rapport_dans_le_workdir_seul_nest_pas_absent(tmp_path):
    wd, _ = _wd(tmp_path)
    assert E._artefact_declare_absent(_detail(_ecrit(wd)), str(wd)) is None


def test_rapport_absent_partout_reste_absent(tmp_path):
    wd, _ = _wd(tmp_path)
    assert "absent" in (E._artefact_declare_absent(_detail(_rel()), str(wd)) or "")


def test_composite_commit_plus_chemin(tmp_path):
    wd, sha = _wd(tmp_path)
    rel = _ecrit(wd)
    assert E._artefact_declare_absent(_detail("%s + %s" % (sha, rel)), str(wd)) is None
    assert E._artefact_declare_absent(
        _detail("worktree claude_headless (commit %s) + %s" % (sha, rel)), str(wd)) is None


def test_composite_un_morceau_absent_suffit(tmp_path):
    wd, sha = _wd(tmp_path)
    assert "absent" in (E._artefact_declare_absent(_detail("%s + %s" % (sha, _rel())), str(wd)) or "")
    rel = _ecrit(wd)
    assert E._artefact_declare_absent(_detail("%s + %s" % ("deadbeef" * 5, rel)), str(wd))


def test_texte_libre_nest_pas_un_chemin(tmp_path):
    wd, _ = _wd(tmp_path)
    assert E._artefact_declare_absent(_detail("commit par l'executeur + %s" % _ecrit(wd)), str(wd)) is None


def test_evasion_hors_workdir_et_depot_jamais_lue(tmp_path, monkeypatch):
    # 26/10 : sous fast_test_runner (et sous le compte bac a sable, dont TEMP est sandbox/workspace/tmp), tmp_path
    # vit DANS le depot -- secret.md y etait lu legitimement et le test rougissait sans defaut de code (REL du 26/10 :
    # _artefact_declare_absent, abstention juste). Un FAUX depot rend le cas hermetique, ou que tourne pytest.
    depot = tmp_path / "depot"
    depot.mkdir()
    monkeypatch.setattr(E, "ROOT", depot)
    wd, _ = _wd(tmp_path)
    (tmp_path / "secret.md").write_text("s", encoding="utf-8")
    assert "absent" in (E._artefact_declare_absent(_detail("../secret.md"), str(wd)) or "")
    assert "absent" in (E._artefact_declare_absent(_detail(str(tmp_path / "secret.md").replace("\\", "/")), str(wd)) or "")
