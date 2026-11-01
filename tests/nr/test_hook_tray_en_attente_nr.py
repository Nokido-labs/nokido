"""NR 28/10 (owner : « tu feras du clean dans les commandes tray si elles sont deja passees ! tu oublies souvent,
ancre-le en post ») : a chaque message de l'owner, le hook rappelle les commandes du tray encore en attente, pour que
celles dont la sortie vient d'etre collee soient retirees (commande-faite) au lieu de s'accumuler.
Mesure du jour : 3 commandes passees restaient « deposees » au tray.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import hook_tray_en_attente as H  # noqa: E402


def test_rien_en_attente_rien_dit():
    assert H.rappel([], maintenant=1000.0) == ""


def test_chaque_commande_en_attente_est_rappelee_avec_la_consigne():
    cmds = [{"evt": "depose", "id": "cmd-aaa", "raison": "ACP, sonde longue : colle la sortie", "depose_a": 400.0},
            {"evt": "depose", "id": "cmd-bbb", "raison": "ACL 3/3", "depose_a": 940.0}]
    t = H.rappel(cmds, maintenant=1000.0)
    assert "cmd-aaa" in t and "cmd-bbb" in t
    assert "commande-faite" in t
    assert "10 min" in t and "1 min" in t


def test_le_hook_ne_casse_jamais(monkeypatch, capsys):
    def boom():
        raise RuntimeError("journal illisible")
    monkeypatch.setattr(H, "_lire_en_attente", boom)
    assert H.main() == 0
    assert "ILLISIBLE" in capsys.readouterr().out
