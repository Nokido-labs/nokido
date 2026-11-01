"""NR -- le site utilisateur est masque UNIQUEMENT pour la base miniforge (P1_site_utilisateur_masque_env_certifie_20261021, etape 1).

POURQUOI. Un python lance sans `-s` ni PYTHONNOUSERSITE=1 met le site utilisateur AVANT le site-packages de
l'env certifie : le verrou ne decrit plus ce que les services chargent.

DECISION OWNER 22/10 (« par etapes, mesure ») :
  - base miniforge (${PYTHON}) : ONLY_USER = pipx, userpath, aucune version differente -> masque SANS risque ;
  - ${PY314} / ${PY312_RYZEN} INCHANGES : 77 paquets ONLY_USER + 47 versions plus anciennes dans le site
    utilisateur de laforge_py314. Ce NR EXIGE qu'ils ne soient PAS masques tant que la liste minimale du rapport
    etape 2 n'est pas installee dans l'env (il faudra alors retourner ce garde-fou, explicitement).
  - lanceurs (forge_services_launcher.spawn_detached, forge_bridge_launch.environnement) : meme regle, selon
    l'interprete reellement lance (cmd[0] / sys.executable).

PERIMETRE (pur : texte/TOML, Popen remplace, aucun reseau, aucun service).
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

ROOT = Path(__file__).resolve().parents[2]
TOML = ROOT / "proxy_deno" / "core" / "services.toml"
LOADER = ROOT / "proxy_deno" / "core" / "service_loader.ts"

BASE = "%USERPROFILE%/miniforge3/python.exe"
PY314 = "%USERPROFILE%/miniforge3/envs/laforge_py314/python.exe"
RYZEN = "%USERPROFILE%/miniforge3/envs/ryzen-ai-final/python.exe"

# Cliquet (constate 22/10 dans services.toml, ANTERIEUR a cette livraison) : services ${PY314} deja masques par
# leur propre env TOML. Ne grandit pas ; le hub NokidoMCP n'en fait PAS partie.
DEJA_MASQUES_PY314 = {
    "NokidoHomeostasis", "NokidoHebbian", "NokidoGraph", "NokidoGeminiDaemon", "NokidoAutonomousLoops",
    "NokidoRSSWatcher", "NokidoTraceCollectorRich", "NokidoCowork", "NokidoGraphExplorer",
}

EXCEPTIONS_NOMMEES = {
    "tools/nokido_launcher.py::_start_tray": "pystray/pillow peut vivre hors env ; owner decide",
    "tools/schtasks/register_autopoiesis_cp.ps1": "python BASE miniforge ; owner decide",
}


def _services():
    return tomllib.loads(TOML.read_text(encoding="utf-8"))["service"]


def _masque_toml(s) -> bool:
    return "-s" in s.get("args", [])[:3] or (s.get("env") or {}).get("PYTHONNOUSERSITE") == "1"


def _bloc_loader() -> str:
    src = LOADER.read_text(encoding="utf-8")
    return src.split("Site utilisateur masque", 1)[1].split("s.deps", 1)[0]


def test_loader_masque_seulement_la_base_miniforge():
    bloc = _bloc_loader()
    assert "svc.env.PYTHONNOUSERSITE" in bloc
    assert "${PYTHON}" in bloc and "miniforge3" in bloc
    # l'ancien critere generique (tout python*) ne doit plus decider
    assert "python[\\d.tw]*" not in bloc
    # aucun test de code ne nomme PY314 / RYZEN comme condition (seulement le commentaire)
    code = "\n".join(ln for ln in bloc.splitlines() if not ln.strip().startswith("//"))
    assert "PY314" not in code and "RYZEN" not in code


def test_loader_defaut_respecte_un_choix_explicite_du_toml():
    assert re.search(r"PYTHONNOUSERSITE === undefined", _bloc_loader())


def test_services_toml_py314_et_ryzen_restent_non_masques():
    masques = {s["name"] for s in _services()
               if str(s.get("cmd", "")).strip() in ("${PY314}", "${PY312_RYZEN}") and _masque_toml(s)}
    nouveaux = masques - DEJA_MASQUES_PY314
    assert not nouveaux, "env pas encore autorise a masquer (installer d'abord les ONLY_USER) : %s" % sorted(nouveaux)
    # NokidoMCP (hub) et les autres ${PY314} non masques aujourd'hui doivent le rester a cette etape
    for s in _services():
        if s["name"] in ("NokidoMCP", "NokidoBrainWorker", "NokidoWebEgress"):
            assert not _masque_toml(s), s["name"]


def test_services_toml_au_moins_un_service_base_beneficie_du_defaut():
    base = [s for s in _services() if str(s.get("cmd", "")).strip() == "${PYTHON}"]
    assert base, "au moins un service ${PYTHON} attendu"


def _charger_lanceur():
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_services_launcher as lanceur
    return lanceur


class _P:
    pid = 1


@pytest.mark.parametrize("exe,attendu", [
    (BASE, True),
    (BASE.replace("/", "\\"), True),
    (PY314, False),
    (RYZEN, False),
])
def test_spawn_detached_masque_selon_l_interpreteur(monkeypatch, tmp_path, exe, attendu):
    lanceur = _charger_lanceur()
    vus = {}

    def faux_popen(cmd, **kw):
        vus.update(kw["env"])
        return _P()

    monkeypatch.delenv("PYTHONNOUSERSITE", raising=False)
    monkeypatch.setattr(lanceur.subprocess, "Popen", faux_popen)
    lanceur.spawn_detached([exe, "x.py"], tmp_path, tmp_path / "l.log")
    assert (vus.get("PYTHONNOUSERSITE") == "1") is attendu


def test_spawn_detached_respecte_un_env_explicite(monkeypatch, tmp_path):
    lanceur = _charger_lanceur()
    vus = {}

    def faux_popen(cmd, **kw):
        vus.update(kw["env"])
        return _P()

    monkeypatch.setattr(lanceur.subprocess, "Popen", faux_popen)
    lanceur.spawn_detached([BASE], tmp_path, tmp_path / "l.log", env={"PYTHONNOUSERSITE": "0"})
    assert vus["PYTHONNOUSERSITE"] == "0"


@pytest.mark.parametrize("exe,attendu", [(BASE, True), (PY314, False)])
def test_environnement_du_pont_masque_selon_sys_executable(monkeypatch, exe, attendu):
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_bridge_launch as pont
    monkeypatch.setattr(pont.sys, "executable", exe)
    env = pont.environnement({}, base={})
    assert (env.get("PYTHONNOUSERSITE") == "1") is attendu


def test_exceptions_nommees_ne_grandissent_pas():
    assert len(EXCEPTIONS_NOMMEES) <= 2, "ajouter une exception exige de l'ecrire et de la justifier au rapport"
    tray = (ROOT / "tools" / "nokido_launcher.py").read_text(encoding="utf-8")
    assert "def _start_tray" in tray
