"""NR -- --govern gouverne la config que Vibe LIT : VIBE_HOME/config.toml quand la variable est posee, ~/.vibe sinon.

Mesure 2026-10-24 : VIBE_HOME de l'owner (HKCU\\Environment) = Nokido/config/clients/vibe ; ~/.vibe n'est pas lu
(meme piege que le 16/10 dans forge_provision_clients._patch_vibe : ecrire ~/.vibe affichait un succes sans effet).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_connect_clients as C  # noqa: E402


def test_vibe_home_pose_prime_sur_le_profil():
    assert C.vibe_config({"VIBE_HOME": "D:/x/vibe"}, Path("C:/Users/o")) == Path("D:/x/vibe") / "config.toml"


def test_sans_vibe_home_c_est_le_dossier_point_vibe():
    assert C.vibe_config({}, Path("C:/Users/o")) == Path("C:/Users/o") / ".vibe" / "config.toml"


def test_vibe_home_vide_ignore():
    assert C.vibe_config({"VIBE_HOME": "  "}, Path("C:/Users/o")) == Path("C:/Users/o") / ".vibe" / "config.toml"
