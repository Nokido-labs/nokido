"""NR -- sous Windows, la recette mesure Docker par WSL2 au lieu de le declarer indisponible (2026-10-20).

Mesure du 20/10 (run 39423950182, sonde .github/workflows/sonde-wsl2-windows.yml) : sur windows-latest, WSL2 est
fonctionnel, docker.io s'installe dans Ubuntu-24.04 et systemd le demarre, `docker run alpine` tourne, et le CLI
Windows pilote ce daemon par DOCKER_HOST=tcp://127.0.0.1:2375 (Server=linux/amd64). L'etape `docker` de la recette
rendait pourtant NON_TESTE avec « conteneurs Linux indisponibles » : une affirmation d'impossibilite jamais mesuree.

Ce qui est garde :
  * daemon Linux joignable sous Windows -> l'etape docker MESURE (elle ne rend plus NON_TESTE) ;
  * pas de daemon Linux sous Windows -> NON_TESTE qui nomme WSL2, jamais « indisponibles » ;
  * le workflow monte Docker Engine dans WSL2 sur le runner Windows et exporte DOCKER_HOST avant la recette.
Limite DITE : c'est Docker Engine dans WSL2, pas Docker Desktop.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
WORKFLOW = RACINE / ".github" / "workflows" / "installation-complete.yml"


def _module():
    spec = importlib.util.spec_from_file_location("acceptance_wsl2_nr", RACINE / "tools" / "forge_install_acceptance.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.R.clear()
    return m


def _faux_sh(ostype):
    appels = []

    def sh(cmd, timeout=1800, **kw):
        appels.append(list(cmd))
        if cmd[:2] == ["docker", "info"]:
            return (0, ostype + "\n") if ostype else (1, "error during connect")
        if cmd[:2] == ["docker", "compose"]:
            return 0, "ollama\nsearxng\n"
        return 0, ""
    return sh, appels


def test_sous_windows_un_daemon_linux_joignable_est_mesure(monkeypatch):
    m = _module()
    sh, appels = _faux_sh("linux")
    monkeypatch.setattr(m, "WIN", True)
    monkeypatch.setattr(m, "sh", sh)
    monkeypatch.setattr(m.shutil, "which", lambda nom: "C:/docker.exe")
    m._docker()
    assert m.R["docker"]["etat"] == "PASS", m.R["docker"]
    assert ["docker", "compose", "-f", "docker-compose.yml", "config", "--services"] in appels


def test_sous_windows_sans_daemon_linux_l_etape_nomme_wsl2(monkeypatch):
    m = _module()
    sh, _ = _faux_sh("windows")
    monkeypatch.setattr(m, "WIN", True)
    monkeypatch.setattr(m, "sh", sh)
    monkeypatch.setattr(m.shutil, "which", lambda nom: "C:/docker.exe")
    m._docker()
    assert m.R["docker"]["etat"] == "NON_TESTE", m.R["docker"]
    assert "WSL2" in m.R["docker"]["detail"]
    assert "indisponibles" not in m.R["docker"]["detail"]


def test_le_workflow_monte_docker_dans_wsl2_avant_la_recette_windows():
    texte = WORKFLOW.read_text(encoding="utf-8")
    job = texte.split("\n  installation:", 1)[1].split("\n  paquet", 1)[0]
    assert "wsl --install" in job and "Ubuntu-24.04" in job
    assert "docker.io" in job
    assert "DOCKER_HOST=tcp://127.0.0.1:2375" in job and "GITHUB_ENV" in job
    assert job.index("wsl --install") < job.index("forge_install_acceptance.py")
