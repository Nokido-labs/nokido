# -*- coding: utf-8 -*-
"""NR — `action=python` : sous-processus a PARITE avec `run shell` sous le compte bac a sable.

Avant (27/09), l'audit hook WORKSPACE_GUARD refusait tout `subprocess.Popen` en `action=python`,
avec un motif FAUX (« sous un compte distinct ») : mesure, python et shell tournent sous le MEME
compte bac a sable (LaForgeSbxOffline), et le shell n'applique aucun filtre de contenu -- son
garde est le confinement OS du compte. Deux trous en plus : `os.system` n'etait PAS dans la
liste (le refus « binaire » laissait une porte ouverte), et la liste des zones etait un GLOBAL
que le code de l'agent -- qui partage les globals du header -- pouvait reassigner.

Contrat verrouille ici, sur le CHEMIN REEL (le header est prefixe a un script execute dans un
processus frais, comme `_run_sandboxed_python`) :
  1. sans parite : Popen ET os.system refuses, avec le motif vrai ;
  2. avec parite : l'enfant tourne ;
  3. reassigner `_GZ` ne desarme plus la zone d'ecriture ;
  4. la parite se decide COTE HUB (`ToolRegistry._parite_sous_processus`) : compte bac a sable
     oui ; gVisor, agent untrusted ou SANDBOX_EXEC coupe : non.
"""
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.37)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_workspace_guard as wg  # noqa: E402


def _jouer(tmp_path, code: str, sous_processus: bool):
    zone = tmp_path / "zone"
    zone.mkdir(exist_ok=True)
    script = tmp_path / "agent.py"
    script.write_text(wg.build_run_guard_header([str(zone)], sous_processus=sous_processus)
                      + "\n" + code, encoding="utf-8")
    return subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                          errors="replace", timeout=120, cwd=str(zone))


ENFANT = "import subprocess, sys\nsubprocess.run([sys.executable, '-c', \"print('ENFANT_OK')\"], check=True)\n"
SYSTEME = "import os\nprint('RC_SYSTEM', os.system('exit 0'))\n"


def test_sans_parite_popen_est_refuse_avec_le_motif_vrai(tmp_path):
    r = _jouer(tmp_path, ENFANT, sous_processus=False)
    assert r.returncode != 0 and "ENFANT_OK" not in r.stdout
    assert "WORKSPACE_GUARD: subprocess.Popen interdit ICI" in r.stderr
    assert "compte distinct" not in r.stderr


def test_sans_parite_os_system_n_est_plus_une_porte_ouverte(tmp_path):
    r = _jouer(tmp_path, SYSTEME, sous_processus=False)
    assert r.returncode != 0 and "RC_SYSTEM" not in r.stdout
    assert "WORKSPACE_GUARD: os.system interdit ICI" in r.stderr


def test_avec_parite_l_enfant_tourne(tmp_path):
    r = _jouer(tmp_path, ENFANT + SYSTEME, sous_processus=True)
    assert r.returncode == 0, r.stderr
    assert "ENFANT_OK" in r.stdout and "RC_SYSTEM 0" in r.stdout


def test_reassigner_la_zone_ne_desarme_plus_le_garde(tmp_path):
    dehors = tmp_path / "dehors.txt"
    code = ("open('dedans.txt', 'w').write('x')\n"
            "_GZ = [%r]\n" % str(tmp_path).lower()
            + "open(%r, 'w').write('x')\n" % str(dehors))
    r = _jouer(tmp_path, code, sous_processus=True)
    assert (tmp_path / "zone" / "dedans.txt").exists()
    assert "WORKSPACE_GUARD: ecriture hors zone agent" in r.stderr
    assert not dehors.exists()


def test_la_parite_se_decide_cote_hub(monkeypatch):
    import forge_mcp_registry as reg

    obj = reg.ToolRegistry.__new__(reg.ToolRegistry)
    obj.root = RACINE
    monkeypatch.setenv("SANDBOX_EXEC", "1")
    assert obj._parite_sous_processus({}, "CLAUDE", 0) is True
    assert obj._parite_sous_processus({"network": True}, "CLAUDE", 0) is True
    assert obj._parite_sous_processus({"sandbox": "gvisor"}, "CLAUDE", 0) is False
    assert obj._parite_sous_processus({}, "INCONNU", 5) is False
    monkeypatch.delenv("SANDBOX_EXEC")
    assert obj._parite_sous_processus({}, "CLAUDE", 0) is False  # pool du hub : compte plus large


def test_la_branche_python_passe_la_decision_au_header():
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    assert "sous_processus=self._parite_sous_processus(args, agent, ring)" in src
