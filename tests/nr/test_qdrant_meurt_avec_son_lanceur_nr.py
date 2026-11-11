"""NR 6/11 : tuer le lanceur de Qdrant laissait qdrant.exe orphelin, et le port tenu.

Mesure : pid 20368, parent 14240 mort juste apres `ensure_service restarted`, etat NON_ATTEINT « port encore en ecoute ». Le
superviseur ne peut plus l'arreter et un nouveau lanceur ne peut pas ecouter. L'enfant doit mourir avec son lanceur.
"""
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = textwrap.dedent("""
    import subprocess, sys, time
    sys.path.insert(0, r"{tools}")
    import forge_qdrant_server as q
    enfant = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    job = q._lier_au_lanceur(enfant.pid)
    print(enfant.pid, bool(job), flush=True)
    time.sleep(60)
""")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Job Object : Windows")
def test_l_enfant_meurt_avec_son_lanceur():
    lanceur = subprocess.Popen([sys.executable, "-c", SCRIPT.format(tools=ROOT / "tools")], stdout=subprocess.PIPE, text=True, errors="replace")
    enfant = None
    try:
        pid, lie = lanceur.stdout.readline().split()
        enfant = psutil.Process(int(pid))
        assert lie == "True", "le lien au lanceur n'a pas ete pose"
        assert enfant.is_running()
        lanceur.kill()  # comme le superviseur : TerminateProcess, aucun nettoyage possible
        lanceur.wait(10)
        enfant.wait(10)  # leve TimeoutExpired si l'enfant survit
        assert not enfant.is_running()
    finally:
        lanceur.kill()
        if enfant and enfant.is_running():
            enfant.kill()


def test_sans_pywin32_le_lanceur_demarre_quand_meme(monkeypatch):
    """Un lien impossible se dit, il n'empeche jamais Qdrant de demarrer."""
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_qdrant_server as q

    monkeypatch.setitem(sys.modules, "win32job", None)
    assert q._lier_au_lanceur(1) is None
