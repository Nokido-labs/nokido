"""NR : l'inventaire de rotation lit l'historique git EN FLUX (mesure 26/10 : job tue a 7,9 Go de RSS).

`_git_history_tokens` capturait d'un bloc `git log --all -p` de tout l'historique (*.json, *.md, *.py...) :
plusieurs Go de texte en memoire pour y chercher des 64-hex. Le flux ligne a ligne ne garde que l'ensemble trouve.
Jeton FACTICE, jamais une vraie valeur.
"""
import subprocess
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_hub_token_rotation as rot  # noqa: E402

FAUX = "ab" * 32


def _depot(tmp_path):
    def g(*a):
        subprocess.run(["git", "-c", "safe.directory=*", "-C", str(tmp_path), *a], check=True,
                       capture_output=True, text=True, errors="replace")
    g("init", "-q")
    g("config", "user.email", "nr@local")
    g("config", "user.name", "nr")
    (tmp_path / "note.md").write_text("cle = %s\n" % FAUX, encoding="utf-8")
    g("add", "note.md")
    g("commit", "-q", "-m", "c1")
    (tmp_path / "note.md").write_text("cle retiree\n", encoding="utf-8")
    g("commit", "-q", "-am", "c2")


def test_trouve_un_jeton_retire_de_l_arbre_mais_present_dans_l_historique(tmp_path):
    _depot(tmp_path)
    etat, trouves = rot._git_history_tokens(tmp_path)
    assert etat == "trouve" and FAUX in trouves


def test_lecture_en_flux_pas_capture_en_bloc(monkeypatch, tmp_path):
    _depot(tmp_path)
    appels = []
    vrai_run = subprocess.run

    def espion_run(cmd, *a, **k):
        if isinstance(cmd, list) and "log" in cmd and k.get("capture_output"):
            appels.append(cmd)
        return vrai_run(cmd, *a, **k)

    monkeypatch.setattr(rot.subprocess, "run", espion_run)
    rot._git_history_tokens(tmp_path)
    assert appels == [], "git log -p capture d'un bloc : la sortie entiere tient en memoire"
