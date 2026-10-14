"""NR -- UNE seule icone « Nokido » au Bureau : elle lance la stack ET le tray (owner 2026-10-13).

Historique : l'icone « Nokido START » lancait nokido_start.ps1 en direct -> stack SANS tray ;
133d918ac l'a fait passer par le Control Panel, en gardant six icones. Owner, le soir meme : « non
je te redemande pas de rajouter encore des icones a Nokido, mais de simplifier le lancement avec une
seule icone Nokido qui lance la stack et le tray ». Contrat :
  - install_shortcuts.ps1 ne cree QU'UN raccourci au Bureau, « Nokido », vers
    `Nokido Control Panel.bat --action lancer` ; les six anciennes icones sont RANGEES, pas supprimees ;
  - `--action lancer` : hub debout -> rien n'est relance, seul le tray est assure ; hub absent ->
    nokido_start.ps1, attente du hub, puis le tray ; un echec constate rend 1, jamais un faux 0 ;
  - l'icone du raccourci est ecrite par le tray (`--ecrire-ico`), seule source du rendu.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s : sous-processus python (point d'entree --ecrire-ico du tray).
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
OUTILS = ROOT / "tools"
for _p in (str(ROOT), str(OUTILS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

L = pytest.importorskip("nokido_launcher")

PS1 = (OUTILS / "install_shortcuts.ps1").read_text(encoding="utf-8")
TRAY = OUTILS / "nokido_tray.py"
ANCIENNES = ("Nokido START.lnk", "Nokido - Restart stack.lnk", "Nokido STOP.lnk",
             "Nokido Control Panel.lnk", "Nokido Tray.lnk", "Nokido Network.lnk")


def test_une_seule_icone_au_bureau_vers_lancer():
    lignes = [l for l in PS1.splitlines()
              if l.strip().startswith("New-NokidoShortcut") and '"$Desktop\\' in l]
    assert len(lignes) == 1, "le Bureau doit porter UNE icone Nokido, pas %d : %s" % (len(lignes), lignes)
    l = lignes[0]
    assert '"$Desktop\\Nokido.lnk"' in l and "$panneau" in l and "--action lancer" in l, l
    assert "nokido_start.ps1" not in l, l


def test_les_anciennes_icones_sont_rangees_pas_supprimees():
    for nom in ANCIENNES:
        assert '"%s"' % nom in PS1, "%s n'est plus range hors du Bureau" % nom
    assert "Move-Item" in PS1
    # Seul Remove-Item permis : celui de New-NokidoShortcut sur SON .lnk avant de le recreer.
    assert PS1.count("Remove-Item") == 1


def test_le_panneau_vise_existe_et_relaie_ses_arguments():
    m = re.search(r'\$panneau\s*=\s*"\$ROOT\\tools\\([^"]+)"', PS1)
    assert m, "variable $panneau introuvable"
    bat = OUTILS / m.group(1)
    assert bat.exists(), bat
    assert "%*" in bat.read_text(encoding="utf-8", errors="replace")


def test_le_lanceur_relance_le_tray_en_start_et_en_restart():
    src = (OUTILS / "nokido_launcher.py").read_text(encoding="utf-8")
    for fn in ("def _action_start", "def _action_restart"):
        i = src.index(fn)
        corps = src[i:src.index("\ndef ", i + 10)]
        assert "_start_tray()" in corps, "%s ne relance pas le tray" % fn


def _sans_effets(monkeypatch, hub_up, wait_ok=True, tray_ok=True):
    vus = []
    monkeypatch.setattr(L, "_compte_de_service", lambda: False)
    monkeypatch.setattr(L, "_hub_status", lambda: {"up": hub_up, "version": "t"})
    monkeypatch.setattr(L, "_run_stack_script", lambda nom, *a: vus.append(nom) or True)
    monkeypatch.setattr(L, "_wait_hub", lambda *a, **k: vus.append("wait") or wait_ok)
    monkeypatch.setattr(L, "_start_tray", lambda: vus.append("tray") or tray_ok)
    monkeypatch.setattr(L, "_input_builtin", lambda *_a: "")
    monkeypatch.setattr(L.time, "sleep", lambda _s: None)
    return vus


def test_lancer_hub_debout_ne_relance_pas_la_stack(monkeypatch):
    vus = _sans_effets(monkeypatch, hub_up=True)
    assert L._cli("lancer") == 0
    assert vus == ["tray"], vus


def test_lancer_hub_absent_demarre_la_stack_puis_le_tray(monkeypatch):
    vus = _sans_effets(monkeypatch, hub_up=False)
    assert L._cli("lancer") == 0
    assert vus == ["nokido_start.ps1", "wait", "tray"], vus


def test_lancer_hub_qui_ne_monte_pas_rend_1_sans_tray(monkeypatch):
    vus = _sans_effets(monkeypatch, hub_up=False, wait_ok=False)
    assert L._cli("lancer") == 1
    assert "tray" not in vus, vus


def test_lancer_tray_mort_rend_1(monkeypatch):
    _sans_effets(monkeypatch, hub_up=True, tray_ok=False)
    assert L._cli("lancer") == 1


def test_lancer_refuse_hors_session_owner(monkeypatch):
    vus = _sans_effets(monkeypatch, hub_up=False)
    monkeypatch.setattr(L, "_compte_de_service", lambda: True)
    assert L._cli("lancer") == 3
    assert vus == []


def test_chemin_reel_ecrire_ico_par_le_point_d_entree_du_tray(tmp_path):
    """Le drapeau que lance install_shortcuts.ps1, traverse tel quel (pas la fonction seule)."""
    for mod in ("pystray", "PIL", "fitz"):
        pytest.importorskip(mod)
    ico = tmp_path / "sous" / "nokido.ico"
    r = subprocess.run([sys.executable, str(TRAY), "--ecrire-ico", str(ico)],
                       capture_output=True, text=True, errors="replace", timeout=90)
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00", "pas un fichier ICO"


def test_ecrire_ico_sans_chemin_rend_2():
    for mod in ("pystray", "PIL"):
        pytest.importorskip(mod)
    r = subprocess.run([sys.executable, str(TRAY), "--ecrire-ico"],
                       capture_output=True, text=True, errors="replace", timeout=90)
    assert r.returncode == 2, r.stdout[-500:] + r.stderr[-500:]


def test_install_shortcuts_reste_ascii():
    """Le gate .ps1 refuse le non-ASCII (PowerShell 5.1 mal decode)."""
    assert all(ord(ch) < 128 for ch in PS1)
