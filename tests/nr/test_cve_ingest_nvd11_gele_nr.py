"""NR — `tools/forge_cve_rag_ingest.py` est GELÉ (27/09).

Le flux qu'il visait (`nvd.nist.gov/feeds/json/cve/1.1/...`) rend 403 : mesuré le 27/09
(`sandbox/workspace/mesure_nvd_flux_2026-09-27.json`), alors que l'API 2.0 rend 200. Le successeur
existe déjà : `tools/forge_cve_nvd_download.py`. Un outil gelé refuse EN LE DISANT, avant tout accès
réseau et toute écriture en base, et nomme son successeur — jamais un échec muet ni un zéro silencieux.

Le second test emprunte le chemin réel (`__main__`), réseau coupé dans le processus enfant.
"""
import importlib.util
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.59)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "tools" / "forge_cve_rag_ingest.py"
SUCCESSEUR = "forge_cve_nvd_download"


def _charger():
    spec = importlib.util.spec_from_file_location("forge_cve_rag_ingest_nr", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_run_refuse_avant_reseau_et_base(tmp_path, monkeypatch):
    m = _charger()
    appels = []

    def interdit(*a, **k):
        appels.append(a)
        raise AssertionError("acces reseau interdit a un outil gele")

    monkeypatch.setattr(urllib.request, "urlopen", interdit)
    base = tmp_path / "embeddings.db"
    with pytest.raises(RuntimeError) as exc:
        m.run(db_path=base)
    message = str(exc.value)
    assert "GELÉ" in message
    assert SUCCESSEUR in message
    assert appels == []
    assert not base.exists()


def test_point_d_entree_main_refuse_et_nomme_le_successeur():
    code = (
        "import runpy, urllib.request\n"
        "def interdit(*a, **k):\n"
        "    raise SystemExit('ACCES RESEAU TENTE')\n"
        "urllib.request.urlopen = interdit\n"
        "runpy.run_path(%r, run_name='__main__')\n" % str(MODULE)
    )
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60, cwd=str(ROOT), env=env)
    sortie = r.stdout + r.stderr
    assert r.returncode != 0
    assert "ACCES RESEAU TENTE" not in sortie
    assert "GELÉ" in sortie
    assert SUCCESSEUR in sortie
