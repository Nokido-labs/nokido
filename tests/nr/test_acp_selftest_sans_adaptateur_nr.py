"""NR : le selftest ACP vise forge_acp_server (stdio), plus le PoC forge_acp_adapter retire."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
NOM = "forge_acp_" + "adapter"


def test_adaptateur_retire():
    assert not (TOOLS / (NOM + ".py")).exists()


def test_aucun_import_ni_selftest_vers_adaptateur():
    motif = re.compile(rf"(import|from)\s+{NOM}|{NOM}\.py")
    for rel in ("tools", "app"):
        for p in (ROOT / rel).rglob("*.py"):
            assert not motif.search(p.read_text(encoding="utf-8", errors="ignore")), p


def test_selftest_client_lance_le_serveur():
    src = (TOOLS / "forge_acp_client.py").read_text(encoding="utf-8")
    assert "forge_acp_server.py" in src and NOM not in src


def test_selftest_reel_passe():
    # 7/11 : borne SOUS le --timeout=30 de la suite (cliquet test_sous_processus_borne_sous_la_suite_nr) ; mesure 0,3 s.
    # Un selftest bloque est un ROUGE local nomme (notre propre serveur ACP), jamais la suite entiere abattue.
    try:
        r = subprocess.run([sys.executable, str(TOOLS / "forge_acp_client.py"), "--selftest"],
                           capture_output=True, text=True, errors="replace", timeout=20, cwd=str(ROOT))
    except subprocess.TimeoutExpired as e:
        raise AssertionError("selftest ACP sans reponse en 20 s (forge_acp_server bloque ?)") from e
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["ok"] is True
