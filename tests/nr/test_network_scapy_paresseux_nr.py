"""NR -- importer app/forge_network ne charge PAS scapy ; scapy se charge au premier sniff.

MESURE du 2026-09-25 (sonde chemin reel du bridge TUI :7440, `forge_tui_sonde --chemin-reel
--pile-apres`) : la TUI v13 (app/Nokido.py) n'affichait RIEN -- aucun octet en 120 s, sans
fermeture. Pile a 18 s : Nokido.py:451 -> forge_network.py:65 `from scapy.all import ...` ->
scapy.arch -> conf.ifaces.reload -> `load_winpcapy` (libpcap.py:207), encore la a 45 s en mesure
isolee. Une bibliotheque de CAPTURE chargee a l'import d'un module que l'interface importe au
demarrage : l'ecran attendait Npcap. La sonde Pilot (laforge_py314, SANS scapy) disait PROUVE.

Faux paquet `scapy` en tete de chemin : son chargement ecrit un temoin. Sous-processus : aucun
etat partage avec le reste de la suite (un vrai scapy deja importe fausserait le verdict).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.61)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
MODULE = RACINE / "app" / "forge_network.py"

SONDE = """
import importlib.util, json, sys
from pathlib import Path
sys.path.insert(0, {faux!r})
temoin = Path({temoin!r})
spec = importlib.util.spec_from_file_location("forge_network_nr", {module!r})
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod  # @dataclass lit le module dans sys.modules pendant l'execution
spec.loader.exec_module(mod)
etat = {{"charge_a_l_import": temoin.exists(), "has_scapy": mod.HAS_SCAPY}}
charger = getattr(mod, "_scapy", None)
noms = charger() if charger else []
etat["charge_au_besoin"] = temoin.exists()
etat["noms"] = [getattr(n, "__name__", str(n)) for n in noms]
print("RESULTAT " + json.dumps(etat))
"""


def _faux_scapy(racine: Path, temoin: Path) -> None:
    paquet = racine / "scapy"
    paquet.mkdir()
    (paquet / "__init__.py").write_text("", encoding="utf-8")
    (paquet / "all.py").write_text(
        "from pathlib import Path\n"
        "Path(%r).write_text('charge', encoding='utf-8')\n"
        "def sniff(*a, **k): return None\n"
        "class IP: pass\n"
        "class TCP: pass\n"
        "class Ether: pass\n" % str(temoin),
        encoding="utf-8")


def test_scapy_n_est_charge_qu_au_premier_besoin(tmp_path):
    faux = tmp_path / "faux"
    faux.mkdir()
    temoin = tmp_path / "scapy_charge.txt"
    _faux_scapy(faux, temoin)
    code = SONDE.format(faux=str(faux), temoin=str(temoin), module=str(MODULE))
    r = subprocess.run([sys.executable, "-c", code], cwd=str(RACINE), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=120)
    ligne = next((l for l in r.stdout.splitlines() if l.startswith("RESULTAT ")), None)
    assert ligne, "sonde muette (rc=%s) :\n%s" % (r.returncode, r.stderr[-1500:])
    etat = json.loads(ligne[len("RESULTAT "):])
    assert etat["charge_a_l_import"] is False, "scapy charge a l'IMPORT de forge_network"
    assert etat["has_scapy"] is True, "capacite non declaree alors que le paquet est present"
    assert etat["charge_au_besoin"] is True
    assert etat["noms"] == ["sniff", "IP", "TCP", "Ether"]
