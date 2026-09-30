"""
test_8770_dead_zone_removal.py
------------------------------
Vérifie que la zone morte :8770 (forge_cli_daemon.py) a été supprimée
et que les artefacts résiduels ont été nettoyés.

Job: job_32fe596a | Agent: ANTIGRAVITY | Date: 2026-07-14
"""
import os
import re
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob tools+app + lecture
#   (l.50)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent


def test_forge_cli_daemon_deleted():
    """forge_cli_daemon.py ne doit plus exister — stub orphelin supprimé."""
    dead_file = ROOT / "app" / "forge_cli_daemon.py"
    assert not dead_file.exists(), (
        f"ZONE MORTE: {dead_file} existe encore — supprimer (job_32fe596a)"
    )


def test_state_ports_no_8770():
    """_STATE_PORTS dans forge_roadmap_synth ne doit plus contenir 8770."""
    synth = ROOT / "tools" / "forge_roadmap_synth.py"
    assert synth.exists(), f"{synth} introuvable"
    content = synth.read_text(encoding="utf-8")
    # Cherche la ligne _STATE_PORTS = (...)
    match = re.search(r"_STATE_PORTS\s*=\s*\(([^)]+)\)", content)
    assert match, "_STATE_PORTS non trouvé dans forge_roadmap_synth.py"
    ports_str = match.group(1)
    ports = [int(p.strip()) for p in ports_str.split(",") if p.strip()]
    assert 8770 not in ports, (
        f"8770 encore dans _STATE_PORTS: {ports} — retirer (zone morte daemon V14)"
    )


def test_no_v1_ask_8770_in_active_code():
    """Aucune référence active à http://127.0.0.1:8770/v1/ask ne doit exister
    dans les fichiers non-forbidden (hors forge_agent_proxy.py qui est escaladé)."""
    pattern = re.compile(r"127\.0\.0\.1:8770/v1/ask")
    # Fichiers actifs à vérifier (exclut forge_agent_proxy.py = forbidden/escaladé)
    scan_dirs = [ROOT / "tools", ROOT / "app"]
    skip_files = {"forge_agent_proxy.py"}  # forbidden — escaladé en follow-up
    hits = []
    for scan_dir in scan_dirs:
        if not scan_dir.is_dir():
            continue
        for py in scan_dir.rglob("*.py"):
            if py.name in skip_files:
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{py.relative_to(ROOT)}:{i}")
    assert not hits, (
        f"Références résiduelles à :8770/v1/ask: {hits}"
    )
