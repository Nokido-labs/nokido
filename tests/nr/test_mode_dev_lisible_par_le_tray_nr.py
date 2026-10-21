"""NR -- l'owner lit l'etat REEL du mode DEV dans le tray, meme quand le jeton lui est illisible.

Mesure 16/10 (bb:active_bugs/tray_jamais_recharge_et_mode_dev_illisible_20261016) : le jeton sandbox/.dev_mode_token
est ACL SYSTEM+Administrateurs ; le tray tourne sous le compte owner NON eleve, le VOIT (exists) sans pouvoir le LIRE,
et `is_armed` avale l'exception -> « jeton present mais non valide (expire ou illisible) » pendant que le garde etait
ARME (ps_clm accepte). L'horodatage du jeton, lui, se lit sans ACL : echeance = horodatage + TTL. Seul un admin ecrit
ce jeton, donc un compte sandbox ne peut pas fabriquer un faux « arme ».
"""
import os
import sys
import time
import types

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_dev_mode as dm  # noqa: E402


class _JetonProtege:
    """Visible et horodate, illisible : ce que voit le compte owner non eleve."""

    def __init__(self, age_s):
        self._mtime = time.time() - age_s

    def exists(self):
        return True

    def read_text(self, *a, **k):
        raise PermissionError("Acces refuse")

    def stat(self):
        return types.SimpleNamespace(st_mtime=self._mtime)


class _Absent:
    def exists(self):
        return False


def test_jeton_absent_rend_absent(monkeypatch):
    monkeypatch.setattr(dm, "TOKEN_FILE", _Absent())
    assert dm.etat_lisible()["etat"] == "ABSENT"


def test_jeton_protege_recent_rend_arme_avec_son_echeance(monkeypatch):
    monkeypatch.setattr(dm, "TOKEN_FILE", _JetonProtege(age_s=60))
    e = dm.etat_lisible()
    assert (e["etat"], dm.TTL_S - 120 < e["reste_s"] <= dm.TTL_S - 60) == ("ARME", True)


def test_jeton_protege_trop_vieux_rend_expire(monkeypatch):
    monkeypatch.setattr(dm, "TOKEN_FILE", _JetonProtege(age_s=dm.TTL_S + 5))
    assert dm.etat_lisible()["etat"] == "EXPIRE"


def test_le_tray_delegue_l_etat_a_forge_dev_mode():
    src = open(os.path.join(_TOOLS, "nokido_tray.py"), encoding="utf-8").read()
    mode_dev = src.split("def _mode_dev", 1)[1].split("\ndef ", 1)[0]
    assert "etat_lisible(" in mode_dev
