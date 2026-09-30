# -*- coding: utf-8 -*-
"""NR - restart full-stack SANS couper les clients MCP (demande owner 2026-09-26).

Mesure du jour : Claude Code retente la connexion HTTP d'un serveur MCP 5 fois en
15 s (+0/+1/+2/+4/+8 s) puis abandonne (« Max reconnection attempts (5) reached »).
L'arret complet laissait le hub a terre ~4 min 20 (16:54:48 -> 16:59:11) : le stop
abattait le superviseur en Tier 0, puis tout le reste, puis 2e UAC, preflights, boot
=> `/mcp` a la main. Un redemarrage du seul superviseur, lui, avait rendu le hub en
~9 s et le client s'etait reconnecte seul.

Le restart du panneau (`Nokido Control Panel.bat` -> nokido_launcher --action
restart) enchaine desormais :
  nokido_stop.ps1  -GarderHub  : flotte arretee par l'API du superviseur (un enfant
                                 tue de l'exterieur est RELANCE), hub + superviseur
                                 debout, process externes comme avant ;
  nokido_start.ps1 -RelanceHub : au Tier 0, apres les preflights, LaForge-Master
                                 redemarre -- il ne tient plus que le hub.
Ce NR fige le cablage de bout en bout. La reconnexion reelle reste un E2E owner.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus cmd.exe (.bat); sous-processus
#   powershell (code appele) (l.237)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
OUTILS = ROOT / "tools"
for _p in (str(ROOT), str(OUTILS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

L = pytest.importorskip("nokido_launcher")

STOP = OUTILS / "nokido_stop.ps1"
START = OUTILS / "nokido_start.ps1"
BAT = OUTILS / "Nokido Control Panel.bat"
TRAY = OUTILS / "nokido_tray.py"

_PS = shutil.which("powershell") or shutil.which("pwsh")


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _param(src: str) -> str:
    m = re.search(r"^param\((.*?)\)\s*$", src, re.M)
    assert m, "bloc param() introuvable"
    return m.group(1)


def _fonction(chemin: Path, nom: str) -> ast.FunctionDef:
    arbre = ast.parse(_src(chemin))
    return next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == nom)


# --- les deux ps1 : drapeaux declares ET relayes a l'auto-elevation -------------

def test_le_stop_declare_garderhub_et_le_relaie_a_l_elevation():
    s = _src(STOP)
    assert "[switch]$GarderHub" in _param(s)
    # Le script s'auto-eleve (RunAs) : un drapeau non relaye est PERDU dans la copie
    # elevee, et le stop redevient l'arret complet sans le dire.
    assert 'if ($GarderHub) { $relArgs += " -GarderHub" }' in s


def test_le_start_declare_relancehub_et_le_relaie_a_l_elevation():
    s = _src(START)
    assert "[switch]$RelanceHub" in _param(s)
    assert 'if ($RelanceHub) { $relArgs += " -RelanceHub" }' in s
    assert "-ArgumentList $relArgs" in s, "l'ancienne elevation perdait tout argument"


# --- le stop en mode garde -------------------------------------------------------

def test_le_stop_ne_coupe_le_tier0_que_hors_mode_garde():
    s = _src(STOP)
    m = re.search(r'\nif \(\$GarderHub\) \{\n\s*Write-Host "  --- Tier 0 : GARDE[^\n]*\n\} else \{\n(.*?)\n\}', s, re.S)
    assert m, "branche Tier 0 garde / non garde introuvable"
    sinon = m.group(1)
    assert 'Stop-Svc "NokidoMCP"' in sinon and 'Stop-Svc "LaForge-Master"' in sinon
    assert s.count('Stop-Svc "LaForge-Master"') == 1, "un second arret du superviseur contournerait le mode garde"


def test_le_stop_garde_arrete_la_flotte_par_l_api_du_superviseur():
    s = _src(STOP)
    assert "/supervisor/service/stop/" in s
    assert 'Authorization = "Bearer $supTok"' in s, "la route est authentifiee : sans jeton, 401"
    assert "($_.Name -ne 'NokidoMCP')" in s, "le hub ne s'arrete pas avec la flotte"
    # Ni jeton ni superviseur : garder le hub est impossible -> on le DIT et on fait
    # l'arret complet, jamais un demi-arret silencieux.
    assert "if (-not $garde) { $GarderHub = $false }" in s
    assert "hub NON gardable" in s


def test_le_stop_garde_epargne_superviseur_wrapper_nssm_et_hub():
    s = _src(STOP)
    # LaForge-Master tourne sous nssm.exe (parent du superviseur deno, mesure du jour).
    assert re.search(r"if \(\$GarderHub\) \{[^}]*wrappers NSSM epargnes", s)
    assert "foreach ($sp in $denoSup) { $denoVus[[int]$sp.ProcessId] = $true }" in s
    assert "Get-NokidoDescendants -RootPids @($hubPid)" in s
    assert "-notlike '*nokido_hub*'" in s


# --- le start : rebond du superviseur, au Tier 0 ---------------------------------

def test_le_start_rebondit_le_superviseur_avant_de_le_demarrer():
    s = _src(START)
    i_rebond = s.index("if ($RelanceHub -and $master.Status -eq 'Running')")
    i_start = s.index("Start-Svc $master 4")
    assert i_rebond < i_start, "le rebond doit preceder le demarrage du Tier 0"
    bloc = s[i_rebond:i_start]
    assert 'Stop-Service -Name "LaForge-Master"' in bloc
    # Un hub survivant tiendrait :8766 : on n'arrete que l'ecouteur qui se dit nokido_hub.
    assert "-LocalPort 8766 -State Listen" in bloc and "-like '*nokido_hub*'" in bloc
    assert s.count('Stop-Service -Name "LaForge-Master"') == 1


@pytest.mark.skipif(not _PS, reason="powershell absent de cette machine")
def test_les_deux_scripts_parsent():
    gate = pytest.importorskip("forge_git_gate")
    assert gate._ps1_parse_gate(["tools/nokido_stop.ps1", "tools/nokido_start.ps1"]) == 0


# --- le panneau enchaine les deux temps et attend un VRAI rebond -----------------

def test_le_panneau_enchaine_stop_garde_puis_start_rebond():
    fn = _fonction(OUTILS / "nokido_launcher.py", "_action_restart")
    appels = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    scripts = {}
    for c in appels:
        if getattr(c.func, "id", None) == "_run_stack_script":
            args = [a.value for a in c.args if isinstance(a, ast.Constant)]
            scripts[args[0]] = args[1:]
    assert set(scripts["nokido_stop.ps1"]) == {"-NoWait", "-GarderHub"}
    assert scripts["nokido_start.ps1"] == ["-RelanceHub"]
    noms = {getattr(c.func, "id", None) for c in appels}
    # Le hub est garde pendant le stop : `_wait_hub` le verrait « UP » avant le rebond
    # (REQUESTED pris pour ACHIEVED).
    assert "_attendre_rebond_hub" in noms and "_wait_hub" not in noms


def test_le_rebond_exige_un_nouveau_pid(monkeypatch):
    sequence = iter([(True, 100), (False, None), (False, None), (True, 200)])
    courant = {}

    def statut():
        up, pid = next(sequence)
        courant["pid"] = pid
        return {"up": up}

    monkeypatch.setattr(L, "_hub_status", statut)
    monkeypatch.setattr(L, "_pid_hub", lambda: courant["pid"])
    monkeypatch.setattr(L.time, "sleep", lambda _s: None)
    assert L._attendre_rebond_hub(100, delai_max=60) is True


def test_un_hub_qui_ne_rebondit_pas_n_est_pas_un_succes(monkeypatch):
    monkeypatch.setattr(L, "_hub_status", lambda: {"up": True})
    monkeypatch.setattr(L, "_pid_hub", lambda: 100)
    monkeypatch.setattr(L.time, "sleep", lambda _s: None)
    assert L._attendre_rebond_hub(100, delai_max=0.2) is False


def test_superviseur_illisible_avant_ne_suffit_pas_sans_chute(monkeypatch):
    """pid d'avant inconnu : un pid lu apres ne prouve un rebond que si la chute a ete vue."""
    monkeypatch.setattr(L, "_hub_status", lambda: {"up": True})
    monkeypatch.setattr(L, "_pid_hub", lambda: 100)
    monkeypatch.setattr(L.time, "sleep", lambda _s: None)
    assert L._attendre_rebond_hub(None, delai_max=0.2) is False


# --- restart du hub SEUL : jeton du superviseur, et un refus n'est pas un silence ----

def _faux_urlopen(code, vus):
    def urlopen(req, timeout=None):
        vus.append((req.full_url, req.get_header("Authorization")))
        if code:
            raise L.urllib.error.HTTPError(req.full_url, code, "refus", {}, None)
        return None
    return urlopen


def _sans_effets(monkeypatch, jeton, code, vus):
    monkeypatch.setattr(L, "_supervisor_token", lambda: jeton)
    monkeypatch.setattr(L, "_hub_status", lambda: {"up": True})
    monkeypatch.setattr(L, "_wait_hub", lambda *_a, **_k: True)
    monkeypatch.setattr(L.urllib.request, "urlopen", _faux_urlopen(code, vus))
    monkeypatch.setattr(L.time, "sleep", lambda _s: None)
    # le lanceur a SON `input` (l'interactif s'eteint hors console) : c'est lui qu'on neutralise
    monkeypatch.setattr(L, "input", lambda *_a: "")


def test_restart_hub_seul_envoie_le_jeton_du_superviseur(monkeypatch):
    """401 mesure le 2026-09-26 sur un POST sans en-tete : le geste echouait TOUJOURS."""
    vus = []
    _sans_effets(monkeypatch, "jeton-de-test", None, vus)
    L._action_restart_hub()
    assert [u.rsplit("/", 2)[-2] for u, _ in vus] == ["stop", "start"]
    assert all(h == "Bearer jeton-de-test" for _, h in vus)


def test_restart_hub_seul_dit_le_refus_et_pas_superviseur_muet(monkeypatch, capsys):
    vus = []
    _sans_effets(monkeypatch, "", 401, vus)
    L._action_restart_hub()
    sortie = capsys.readouterr().out
    assert "REFUSE" in sortie and "401" in sortie
    assert "muet" not in sortie
    assert len(vus) == 1, "un refus sur 'stop' ne doit pas enchainer 'start'"


# --- le .bat du Bureau est l'entree, et le tray l'ouvre ---------------------------

def test_le_bat_relaie_ses_arguments_et_le_tray_l_ouvre():
    lignes = [ligne for ligne in _src(BAT).splitlines() if "nokido_launcher.py" in ligne]
    assert len(lignes) == 1 and lignes[0].rstrip().endswith("%*"), lignes
    arbre = ast.parse(_src(TRAY))
    consts = {n.value for n in ast.walk(arbre) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "Nokido Control Panel.bat" in consts
    fn = _fonction(TRAY, "lancer_panneau")
    noms = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "PANNEAU_BAT" in noms and "LANCEUR" not in noms


def test_chemin_reel_le_bat_transmet_l_action_au_panneau():
    """Chemin REEL : le .bat lance le panneau avec ses arguments (`--action list` -> 0).
    Le .bat vise %USERPROFILE%\\miniforge3 : sous un compte sans cet interpreteur, NON verifie."""
    py = Path.home() / "miniforge3" / "python.exe"
    if not py.exists():
        pytest.skip("NON verifie : %s absent sous ce compte" % py)
    r = subprocess.run(["cmd.exe", "/c", str(BAT), "--action", "list"], capture_output=True,
                       text=True, errors="replace", timeout=60)
    assert r.returncode == 0, (r.returncode, r.stdout[-300:], r.stderr[-300:])
    assert "restart" in r.stdout
