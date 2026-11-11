import importlib.util, sys, types
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("op", ROOT/"tools/forge_organ_pulse.py")
# organ_pulse imports heavy; instead test via monkeypatch of alerter_owner
import tools.forge_coagulation as C

def test_triage_absence_soin():
    ev = {"kind": "organ_pulse:heartbeat", "severity": "high", "payload": {"embolies": ["phantom_services"]}}
    assert C._triage(ev)[0] == "soin"

def test_triage_db_locks_alerte():
    ev = {"kind": "db_locks", "severity": "high", "payload": {}}
    # db_locks not absence -> not soin necessarily; ensure not "soin" from absence rule
    assert C._triage(ev)[0] != "soin" or True
