# -*- coding: utf-8 -*-
"""NR (28/10) : le catalogue des outils du gateway Docker MCP a une voie de REMPLISSAGE.

Sans elle, tools/list (qui lit le cache) ne montrait rien : le cache ne s'ecrivait qu'apres un appel
docker_* reussi, et personne n'appelle un outil invisible. `--rafraichir-catalogue` reveille Docker par
la voie dynamique (docker.wanted via ensure_daemon), liste les outils, ecrit le cache, puis rend la main
au gateway (shutdown) -- et le dit en une ligne JSON, echec compris (jamais un vide muet)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_docker_supervisor as fds  # noqa: E402


class _FauxSup:
    def __init__(self, outils=None, erreur=None):
        self.outils, self.erreur, self.force, self.arrete = outils or [], erreur, None, False

    async def list_tools(self, force=False):
        self.force = force
        if self.erreur:
            raise self.erreur
        return self.outils

    def shutdown(self):
        self.arrete = True


def test_rafraichit_ecrit_et_rend_la_main(monkeypatch, capsys):
    sup = _FauxSup([{"name": "fetch"}, {"name": "search"}])
    monkeypatch.setattr(fds, "get_supervisor", lambda: sup)
    rc = fds.main(["--rafraichir-catalogue"])
    ligne = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and sup.force is True and sup.arrete is True
    assert ligne["etat"] == "RAFRAICHI" and ligne["outils"] == ["fetch", "search"]


@pytest.mark.timeout(150)   # sous-processus a 120 s > borne de la suite (30 s) : borne explicite (cliquet 31/10)
def test_le_keeper_s_importe_sur_le_chemin_reel_du_script():
    """CHEMIN REEL (28/10) : lance en script, le module n'a que app/ sur sys.path. `from tools.forge_docker_keeper`
    y echouait (« No module named ») -- les NR ci-dessus simulaient _demander_docker et ne le voyaient pas."""
    import subprocess
    code = ("import sys; sys.path[:] = [p for p in sys.path if 'Script python IA' not in p]; "
            "sys.path.insert(0, %r); import forge_docker_supervisor as f; "
            "print(f._importer_ensure_docker().__module__)" % str(ROOT / "app"))
    env = {k: v for k, v in __import__("os").environ.items() if k != "PYTHONPATH"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, errors="replace",
                       cwd=str(ROOT.parent.parent), env=env, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.strip().endswith("forge_docker_keeper"), r.stdout


def test_echec_dit_bloque_par_dependance(monkeypatch, capsys):
    sup = _FauxSup(erreur=fds.DockerSupervisorError("BLOQUE_PAR_DEPENDANCE : docker non réveillé"))
    monkeypatch.setattr(fds, "get_supervisor", lambda: sup)
    rc = fds.main(["--rafraichir-catalogue"])
    ligne = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 2 and sup.arrete is True
    assert ligne["etat"] == "ECHEC" and "BLOQUE_PAR_DEPENDANCE" in ligne["motif"]
