# -*- coding: utf-8 -*-
"""NR - le lanceur Nokido est appelable depuis n'importe quel CLI (2026-09-06).

Owner : « il devra etre appelable enfin depuis n'importe quel CLI ». Le panneau
(`Nokido Control Panel.bat` -> tools/nokido_launcher.py) etait un menu interactif :
chaque action finissait par `input()`, impossible a piloter depuis un hub ou un job.

Contrats :
  1. en mode `--action`, `input()` ne bloque jamais (rend "") ;
  2. `--action list` enumere les actions et rend 0 ; une action inconnue rend 2 ;
  3. start/stop/restart (scripts auto-eleves, UAC) sont REFUSES depuis un compte de
     service, avec le geste owner nomme, code 3 -- jamais un faux depart silencieux ;
  4. le repli `Restart-Service NokidoMCP` a disparu : le hub est un enfant du
     superviseur, le service NSSM est arrete par design (collision :8766 sinon).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python x2 (l.57)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

L = pytest.importorskip("nokido_launcher")


def test_input_ne_bloque_pas_en_mode_cli(monkeypatch):
    monkeypatch.setattr(L, "INTERACTIF", False)
    assert L.input("Entree pour continuer") == ""


def test_list_et_action_inconnue(capsys):
    assert L._cli("list") == 0
    out = capsys.readouterr().out
    assert "status" in out and "restart-hub" in out
    assert L._cli("n_existe_pas") == 2


def test_les_actions_bureau_sont_refusees_sous_un_compte_de_service(monkeypatch, capsys):
    monkeypatch.setenv("USERNAME", "LaForgeSbxOffline")
    appels = []
    monkeypatch.setitem(L.ACTIONS, "start", lambda: appels.append("start"))
    assert L._cli("start") == 3 and appels == [], "le script auto-eleve ne doit pas etre lance"
    assert "REFUS" in capsys.readouterr().out
    monkeypatch.setenv("USERNAME", "user")
    assert L._cli("start") == 0 and appels == ["start"]


def test_le_point_d_entree_reel_rend_le_code_de_retour():
    """Chemin REEL (sous-processus, pas l'appel de fonction) : mesure du matin meme,
    `check()` passait ses NR pendant que `--check` mourait au __main__. Ici : le code
    de _cli doit traverser main() jusqu'a SystemExit, sinon tout CLI lira 0."""
    import subprocess
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "nokido_launcher.py"), "--action", "n_existe_pas"],
                       capture_output=True, text=True, errors="replace", timeout=60)
    assert r.returncode == 2, (r.returncode, r.stdout[-300:], r.stderr[-300:])
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "nokido_launcher.py"), "--action", "list"],
                       capture_output=True, text=True, errors="replace", timeout=60)
    assert r.returncode == 0 and "status" in r.stdout


def test_le_repli_nssm_a_disparu():
    src = (ROOT / "tools" / "nokido_launcher.py").read_text(encoding="utf-8")
    import re
    corps = re.search(r"def _action_restart_hub\(\):(.*?)\ndef ", src, re.S).group(1)
    assert "_service_action(" not in corps, "Restart-Service NokidoMCP relancerait un 2e hub sur :8766"
    assert "Restart stack" in corps
