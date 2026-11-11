# -*- coding: utf-8 -*-
"""NR (owner 3/11 « est-ce que le RSI rend enfin qqch ? ») : chaque cycle horaire du self-patcher voyait 5 propositions
et n'en traitait AUCUNE -- le rejeu du test REL (contrat F2P) levait FileNotFoundError, donc « illisible », donc en
attente, pour toujours (patches_applied 0, cycles 9 -> 12 du journal). Cause : LAFORGE_PY = expanduser("~/miniforge3/
python.exe") se resout dans le profil du compte qui EXECUTE le service, ou ce chemin n'existe pas. L'interpreteur du
RSI doit exister quel que soit le compte."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_self_patcher as sp  # noqa: E402


def test_l_interpreteur_du_rsi_existe_quel_que_soit_le_compte():
    assert os.path.exists(sp.LAFORGE_PY), sp.LAFORGE_PY


def test_le_python_de_base_derive_du_depot_est_candidat(monkeypatch, tmp_path):
    # Le profil est redirige comme sous le compte du service : sans cela, sous le compte des jobs, ~ == profil owner
    # et le test passait SANS le correctif (1er essai 3/11 23 h 48 : 3 verts, aucun rouge -- NR non discriminant).
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    # sous pytest, sys.executable EST le python de base ; sous le service c'est envs\nokido_services (2e essai : vert
    # sans correctif) -> on le redirige aussi
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nokido_services_python.exe"))
    # forge_python_bin se calcule a l'IMPORT d'apres l'interpreteur qui l'importe (3e essai : vert sans correctif)
    import types
    monkeypatch.setitem(sys.modules, "forge_python_bin",
                        types.SimpleNamespace(LAFORGE_PYTHON=str(tmp_path / "nokido_services_python.exe")))
    # 3/11 23 h 41 (cycle 0 prouve) : sous le compte du service, ~ ne pointe pas vers le profil owner ; les candidats
    # (forge_python_bin -> envs\nokido_services, sys.executable idem) n'avaient pas pytest. Le python de BASE de
    # miniforge, derive de l'emplacement du depot (ROOT -> dossier utilisateur), doit figurer parmi les candidats.
    attendu = str(sp.ROOT.parents[1] / "miniforge3" / "python.exe")
    assert attendu in sp._candidats_interpreteur()


def test_un_profil_sans_miniforge_retombe_sur_un_interpreteur_existant(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert os.path.exists(sp._interpreteur())
