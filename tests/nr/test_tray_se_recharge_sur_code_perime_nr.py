"""NR -- une relance de stack recharge le code du tray quand il est perime.

Mesure 16/10 (bb:active_bugs/tray_jamais_recharge_et_mode_dev_illisible_20261016) : logs/tray.log -- tray demarre a
06:23:28, puis aux relances de 10:27 et 13:55 la nouvelle instance sortait « deja actif (code 3) » : nokido_stop.ps1
epargne le tray (UI) et le lanceur s'arrete sur l'instance unique. Le tray tournait sur le code d'avant le bouton DEV
et les commandes owner. Primitive reutilisee : tools/forge_code_identity (snapshot / drifted, deja portee par 5 keepers).
"""
import os
import sys
import types

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_code_identity as C  # noqa: E402

SRC_TRAY = open(os.path.join(_TOOLS, "nokido_tray.py"), encoding="utf-8").read()


def test_seuls_les_modules_du_depot_sont_suivis(tmp_path):
    dedans = tmp_path / "depot" / "a.py"
    dehors = tmp_path / "ailleurs" / "b.py"
    mods = [types.SimpleNamespace(__file__=str(dedans)), types.SimpleNamespace(__file__=str(dehors)),
            types.SimpleNamespace(__file__=None), types.SimpleNamespace()]
    assert C.fichiers_du_depot(mods, tmp_path / "depot") == [str(dedans)]


def test_un_fichier_modifie_depuis_son_premier_releve_est_perime(tmp_path):
    f = tmp_path / "mod_tray_essai.py"
    f.write_text("x = 1\n", encoding="utf-8")
    avant = C.perimes([str(f)])
    f.write_text("x = 2\n", encoding="utf-8")
    assert (avant, C.perimes([str(f)])) == ([], ["mod_tray_essai.py"])


def test_la_relance_de_stack_recharge_un_tray_perime():
    panneau = SRC_TRAY.split("def lancer_panneau", 1)[1].split("\ndef ", 1)[0]
    assert "_relancer_si_perime(" in panneau


def test_la_nouvelle_instance_attend_la_sortie_de_l_ancienne():
    main = SRC_TRAY.split("\ndef main", 1)[1].split("\ndef ", 1)[0]
    assert "--attendre-pid" in main and main.index("--attendre-pid") < main.index("_instance_unique()")
