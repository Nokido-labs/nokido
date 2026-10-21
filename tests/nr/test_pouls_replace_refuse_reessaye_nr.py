"""NR -- un os.replace refuse (partage Windows, antivirus) est REESSAYE avant le repli qui tronque ; le pytest imbrique
de mesurer() ne touche pas au .pytest_cache du depot.

Mesure 20/10 (CI de reference 63a63a812, et deja 477e02f93) : test_delegation_declare_son_travail_au_superviseur lisait
un pouls VIDE (JSONDecodeError) -- reproductible DEPUIS le worktree de reference, jamais dans l'arbre principal. Le
repli de beat_daemon (0bb4e8b99) sur un os.replace refuse est write_text : il TRONQUE puis ecrit, et un lecteur voit
un fichier vide -- un superviseur y lirait une mort. Meme passe : mesurer() lancait pytest SANS -p no:cacheprovider ;
sous la charge de la reference, l'lstat du .pytest_cache du depot principal levait FileNotFoundError
(test_capsule_autopsie).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_heartbeat as HB  # noqa: E402
import forge_mutation_judge as J  # noqa: E402


def test_un_replace_refuse_deux_fois_est_reessaye_sans_tronquer(tmp_path, monkeypatch):
    monkeypatch.setattr(HB, "_ROOT", tmp_path)
    vrai_replace = HB.os.replace
    essais = []

    def replace(src, dst):
        essais.append(1)
        if len(essais) <= 2:
            raise PermissionError(32, "fichier utilise par un autre processus")
        return vrai_replace(src, dst)

    monkeypatch.setattr(HB.os, "replace", replace)
    monkeypatch.setattr(HB.time, "sleep", lambda s: None)
    ecritures_directes = []
    vrai_write = Path.write_text

    def write_text(self, *a, **k):
        if self.suffix == ".heartbeat":
            ecritures_directes.append(self)
        return vrai_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", write_text)
    assert HB.beat_daemon("pouls_essai", n=1) is True
    assert len(essais) == 3, "le replace refuse doit etre REESSAYE"
    assert ecritures_directes == [], "repli tronquant emprunte alors qu'un reessai suffisait"
    assert json.loads((tmp_path / "sandbox" / "pouls_essai.heartbeat").read_text(encoding="utf-8"))["n"] == 1


def test_mesurer_desactive_le_cache_de_pytest(tmp_path, monkeypatch):
    vus = []

    class _R:
        returncode, stdout, stderr = 0, "1 passed", ""

    monkeypatch.setattr(J.subprocess, "run", lambda cmd, **k: vus.append(cmd) or _R())
    J.mesurer([str(tmp_path / "test_x.py")], cwd=str(tmp_path))
    assert vus and "no:cacheprovider" in vus[0], vus
