# -*- coding: utf-8 -*-
"""NR -- mesure owner 1/11 (cmd-9f9bc3f7898f) : Bash natif = 1er poste du contexte relu (9,2 M car. x tours), git
surtout. Le compacteur existait mais son motif `-C\\s+\\S+` ne reconnaissait pas un chemin ENTRE GUILLEMETS avec espaces
(`git -C "C:/.../Script python IA/Nokido" log`) : aucun git -C de la session n'a ete compacte. Couverts desormais :
-C entre guillemets, progression de `worktree add`, avertissements git (could not open directory, CRLF), grep/show
bornes ; chaque passage est JOURNALISE (brut -> garde, observation owner « 1 j ») et le brut est ARCHIVE quand une coupe
a lieu (zero perte). Le hook pose `set -o pipefail` : un pipe ne masque pas le code de sortie de la commande."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_cmd_compactor as C  # noqa: E402

Q = 'git -C "%NOKIDO_ROOT%" '


def test_le_chemin_entre_guillemets_est_reconnu():
    assert C.match(Q + "log -9 --stat", C.load_filters())[0] == "git-log"
    assert C.match(Q + "status -sb", C.load_filters())[0] == "git-status"


def test_progression_de_worktree_add_retiree():
    sortie = "Preparing worktree (detached HEAD f6ae085c3)\n" + "".join(
        "Updating files:  %d%% (%d/7801)\r" % (i, i * 78) for i in range(100)) + "\nHEAD is now at f6ae085c3 feat\n"
    r = C.compact(Q + 'worktree add --detach "C:/tmp/wt" f6ae085c3', sortie)
    assert "Updating files" not in r["filtered"] and "HEAD is now at f6ae085c3" in r["filtered"]


def test_bruit_git_retire_sur_stash_et_cherry_pick():
    bruit = "".join("warning: could not open directory 'sandbox/x/%d/': Permission denied\n" % i for i in range(3000))
    sortie = bruit + "warning: in the working copy of 'a.py', CRLF will be replaced by LF\nDropped refs/stash@{0}\n"
    for verbe in ("stash pop", "cherry-pick a88334a30"):
        r = C.compact(Q + verbe, sortie)
        assert "could not open directory" not in r["filtered"] and "CRLF" not in r["filtered"]
        assert "Dropped refs/stash@{0}" in r["filtered"]


def test_grep_et_show_bornes_et_brut_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ARCHIVE_DIR", tmp_path)
    sortie = "".join("tools/f%04d.py:12:ligne\n" % i for i in range(500))
    r = C.compact(Q + "grep -n motif -- tools", sortie)
    assert r["kept_chars"] < r["raw_chars"] / 4
    assert r.get("archive") and Path(r["archive"]).read_text(encoding="utf-8") == sortie
    assert r["archive"] in r["filtered"]
    assert C.match(Q + "show HEAD:tests/x.py", C.load_filters())[0] == "git-show"


def test_chaque_passage_est_journalise(tmp_path, monkeypatch):
    journal = tmp_path / "cmd_compactor.jsonl"
    monkeypatch.setattr(C, "JOURNAL", journal)
    monkeypatch.setattr(C, "ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("Preparing worktree\nUpdating files: 1%\n"))
    assert C.main(["--cmd", Q + "worktree add x"]) == 0
    e = json.loads(journal.read_text(encoding="utf-8").splitlines()[-1])
    assert e["filtre"] == "git-worktree" and e["brut"] > e["garde"]


def test_le_hook_pose_pipefail():
    src = (ROOT / "tools" / "hook_bash_compact.py").read_text(encoding="utf-8")
    assert "set -o pipefail;" in src


def test_chemin_reel_le_compacteur_parle_utf8(tmp_path):
    """Mesure 1/11 en prod : le marqueur « … — brut » arrivait en `�` -- le compacteur ecrivait en cp1252 (console
    Windows) ce que Claude Code lit en UTF-8. Entree git UTF-8 (accents, guillemets) -> sortie UTF-8 intacte."""
    import os
    import subprocess
    entree = ("commit é « guillemets »\n" * 200).encode("utf-8")
    env = dict(os.environ, PYTHONIOENCODING="")
    env.pop("PYTHONUTF8", None)
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "forge_cmd_compactor.py"), "--cmd", Q + "grep -n x"],
                       input=entree, capture_output=True, timeout=20, env=env)   # < --timeout=30 de la suite
    texte = p.stdout.decode("utf-8")       # leve si la sortie n'est pas de l'UTF-8
    assert "commit é « guillemets »" in texte and "…" in texte


def test_une_commande_a_guillemets_imbriques_passe_intacte(monkeypatch):
    """Mesure 1/11 en prod : `git grep -e "dans \\"README.md\\""` -> `--cmd "..."` mal ferme, le compacteur
    recevait des arguments en trop et la commande ECHOUAIT (« unrecognized arguments »). La commande voyage en base64."""
    import base64
    import io
    import os
    import subprocess
    cmd = Q + 'grep -n -B2 "assert ref, \\"tableau\\"" -- tests'
    env = dict(os.environ)
    env.pop("FORGE_COMPACT_OFF", None)
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "hook_bash_compact.py")],
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
                       capture_output=True, text=True, timeout=20, env=env, errors="replace")
    reecrit = json.loads(p.stdout)["hookSpecificOutput"]["updatedInput"]["command"]
    b64 = reecrit.split("--cmd-b64 ", 1)[1].split()[0]
    assert base64.b64decode(b64).decode("utf-8") == cmd
    monkeypatch.setattr(sys, "stdin", io.StringIO("x\n"))
    monkeypatch.setattr(C, "JOURNAL", Path(os.devnull))
    assert C.main(["--cmd-b64", b64]) == 0


def test_chemin_reel_le_hook_reecrit_un_git_C_entre_guillemets():
    """Le hook appele comme Claude Code l'appelle (stdin JSON). Mesure 1/11 : `SAFE_PREFIXES` portait « git -C » en
    MAJUSCULE compare a la commande mise en minuscules -> aucun `git -C` n'a jamais ete reecrit ; les tests unitaires
    du compacteur passaient pendant que le hook restait muet."""
    import os
    import subprocess
    env = dict(os.environ)
    env.pop("FORGE_COMPACT_OFF", None)
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "hook_bash_compact.py")],
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": Q + "log -12 --stat"}}),
                       capture_output=True, text=True, timeout=20, env=env, errors="replace")
    sortie = json.loads(p.stdout)["hookSpecificOutput"]
    assert sortie["updatedInput"]["command"].startswith("set -o pipefail; " + Q + "log -12 --stat 2>&1 | ")
    assert "--cmd-b64 " in sortie["updatedInput"]["command"]
