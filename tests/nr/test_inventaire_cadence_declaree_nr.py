"""NR -- l'inventaire lit la cadence que services.toml DECLARE (cycle_s, heartbeat_max_s), pas seulement les drapeaux.

Mesure 19/10 23:25 (forge_process_inventory --json) : NokidoDeportEmbed « fige » a 138 min (seuil 60) alors que son
bloc declare `cycle_s = 3600` (« PROUVE ») et `heartbeat_max_s = 10800` ; NokidoMemoryConsolidator « fige » a 647 min
pour un cycle de 12 h. L'inventaire ne lisait que --interval/--sleep/--period : il fabriquait deux fausses pannes
(STALE n'est pas DEAD -- un organe qui digere n'est pas un organe mort).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_process_inventory as I  # noqa: E402

TOML = '''
[[service]]
name = "OrganeVague"
args = ["tools/forge_x.py", "--embed-only", "--watch", "3600"]
heartbeat = "sandbox/x.heartbeat"
# cycle_s dans un commentaire ne compte pas
cycle_s = 3600
heartbeat_max_s = 10800
heartbeat_tier = "slow"

[[service]]
name = "OrganeSansCadence"
args = ["tools/forge_y.py"]
heartbeat = "sandbox/y.heartbeat"
'''


def test_cycle_et_borne_declares_sont_lus(tmp_path, monkeypatch):
    f = tmp_path / "services.toml"
    f.write_text(TOML, encoding="utf-8")
    monkeypatch.setattr(I, "SERVICES_TOML", f)
    p = I._prevus()
    assert p["OrganeVague"]["interval_s"] == 3600
    assert p["OrganeVague"]["heartbeat_max_s"] == 10800
    assert p["OrganeSansCadence"]["interval_s"] is None
    assert p["OrganeSansCadence"]["heartbeat_max_s"] is None


def test_le_consolidateur_declare_son_cycle_de_12_h():
    p = I._prevus()
    assert p["NokidoMemoryConsolidator"]["interval_s"] == 43200
