"""NR 18/10 : `forge_roadmap_verif_appliquer` plantait en JSONDecodeError quand le rapport du lot
n'existait pas encore au commit donne (git show vide). Un rapport absent se DIT (rc=2), il ne plante pas."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "forge_roadmap_verif_appliquer_nr", ROOT / "tools" / "forge_roadmap_verif_appliquer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_rapport_absent_rend_2_et_le_dit(capsys):
    rc = _module().main(["HEAD", "lot_inexistant_nr", "--fichier-date", "19000101"])
    assert rc == 2
    assert "RAPPORT ABSENT" in capsys.readouterr().out
