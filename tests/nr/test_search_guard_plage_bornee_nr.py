"""NR -- hook_search_guard : une plage Read sur le depot n'est bornee que si limit <= 150.

Mesure 9/11 (session a 720K jetons) : 33 des 41 Read natifs etaient des lectures du depot
portant limit/offset, 71 % du volume des Read (max 13 715 car.) ; le garde laissait passer
toute lecture munie de limit/offset, quelle que soit la plage. La regle des 150 lignes
(CLAUDE.md) n'etait executee nulle part. On garde l'acces : la petite plage reste permise.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
HOOK = RACINE / "tools" / "hook_search_guard.py"


def _appel(entree: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_name": "Read", "tool_input": entree}),
                          capture_output=True, text=True, errors="replace", timeout=30)


def _gros_fichier(dossier: Path) -> Path:
    f = dossier / "gros.py"
    f.write_text("x = 1\n" * 5000, encoding="utf-8")
    return f


def test_plage_large_sur_le_depot_bloquee_et_forme_permise_nommee():
    r = _appel({"file_path": str(HOOK), "offset": 1, "limit": 400})
    assert r.returncode == 2
    assert "150" in r.stderr and "read_function_body" in r.stderr


def test_petite_plage_sur_le_depot_permise():
    assert _appel({"file_path": str(HOOK), "offset": 1, "limit": 150}).returncode == 0


def test_offset_seul_sur_gros_fichier_du_depot_bloque(tmp_path):
    # offset sans limit = jusqu'a 2 000 lignes : non borne.
    cible = RACINE / "tools" / "forge_contexte_par_source.py"
    assert cible.stat().st_size > 14000
    assert _appel({"file_path": str(cible), "offset": 10}).returncode == 2


def test_depot_reconnu_par_l_emplacement_du_garde_pas_par_son_nom():
    # Rouge du 11/11 (run self-hosted 42933251418) : checkout sous .../nokido-private/nokido-private/,
    # aucun segment « /nokido/ » dans le chemin -> le garde laissait tout passer (rc 0 au lieu de 2).
    import shutil
    base = Path("C:/tmp/nr_search_guard_checkout")
    (base / "tools").mkdir(parents=True, exist_ok=True)
    copie = base / "tools" / "hook_search_guard.py"
    shutil.copyfile(HOOK, copie)
    f = _gros_fichier(base / "tools")
    entree = json.dumps({"tool_name": "Read", "tool_input": {"file_path": str(f), "offset": 1, "limit": 400}})
    r = subprocess.run([sys.executable, str(copie)], input=entree, capture_output=True, text=True,
                       errors="replace", timeout=20)
    assert r.returncode == 2 and "150" in r.stderr


def test_hors_depot_comportement_inchange():
    # Pas tmp_path : le TEMP du compte bac vit sous Nokido/ (rouge constate le 9/11).
    dossier = Path("C:/tmp/nr_search_guard")
    dossier.mkdir(parents=True, exist_ok=True)
    f = _gros_fichier(dossier)
    assert _appel({"file_path": str(f), "offset": 1, "limit": 400}).returncode == 0
    assert _appel({"file_path": str(f)}).returncode == 2
