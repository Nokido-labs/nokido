"""NR -- l'audit pip-audit des manifestes livres ne depend plus du profil du compte, et dit pourquoi il echoue.

Mesure 25/10 00:30 : `dist_promotion --audit-manifestes` (prerequis de la CI de reference) rendait les 4 manifestes
« ILLISIBLE ou absent » ; la cause n'apparaissait nulle part, `auditer_snapshot` jetait stderr. Sonde dans
l'interpreteur des jobs : pip-audit 2.10.0 present, mais `PermissionError: [WinError 5] Acces refuse:
'C:\\Users\\Default\\AppData\\Local\\pip-audit'` -- le compte des jobs a pour HOME le profil Default. Contrat :
pip-audit recoit un `--cache-dir` inscriptible, et un rapport absent journalise rc + fin de stderr.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import dist_promotion as D  # noqa: E402


def _snapshot(tmp_path):
    for f in D.MANIFESTES_LIVRES:
        (tmp_path / f).write_text("requests==2.32.3\n", encoding="utf-8")
    return tmp_path


def test_pip_audit_recoit_un_cache_inscriptible(tmp_path):
    vus = []

    def executer(cmd, **kw):
        vus.append(cmd)
        sortie = Path(cmd[cmd.index("-o") + 1])
        sortie.write_text(json.dumps({"dependencies": []}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    D.auditer_snapshot(_snapshot(tmp_path), executer=executer)
    assert vus
    for cmd in vus:
        assert "--cache-dir" in cmd, cmd
        cache = cmd[cmd.index("--cache-dir") + 1]
        assert "Default" not in cache, cache


def test_un_rapport_absent_dit_pourquoi(tmp_path, capsys):
    def executer(cmd, **kw):
        return SimpleNamespace(returncode=1, stdout="", stderr="PermissionError: [WinError 5] Acces refuse")

    D.auditer_snapshot(_snapshot(tmp_path), executer=executer)
    sortie = capsys.readouterr().out
    assert "rc=1" in sortie and "WinError 5" in sortie, sortie
