"""NR 2026-10-01 : `forge_supervisor_ctl restart` n'a plus de course stop/start, et mesure l'etat ATTEINT.

Mesure qui l'a motive (NokidoPairMCP) : le start partait 12 ms apres le stop, pendant que l'ancien process
tenait encore son port ; le superviseur ne relancait rien, l'exit de l'ancien laissait le service `stopped`,
le garde anti-double-demarrage ignorait les relances ~90 s -- et ctl affichait « starting ». Chemin reel :
`main()` avec `restart <svc>`, superviseur simule (machine a etats), horloge simulee.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "forge_supervisor_ctl_restart_nr", ROOT / "tools" / "forge_supervisor_ctl.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Superviseur:
    """Simule l'arret LENT de l'ancien process : 3 sondes « running + port tenu » apres le stop."""

    def __init__(self, demarre=True):
        self.statut, self.port_tenu, self.appels, self.sondes_avant_arret = "running", True, [], 3
        self.demarre = demarre
        self.start_pendant_port_tenu = False

    def call(self, path, method="GET"):
        self.appels.append(path)
        if path.endswith("/supervisor/status"):
            if self.statut == "stopping":
                self.sondes_avant_arret -= 1
                if self.sondes_avant_arret <= 0:
                    self.statut, self.port_tenu = "stopped", False
            vue = "running" if self.statut == "stopping" else self.statut
            return 200, json.dumps({"services": {"NokidoX": {"status": vue, "port": 8999, "pid": 42}}})
        if "/service/stop/" in path:
            self.statut = "stopping"
            return 200, '{"ok": true}'
        if "/service/start/" in path:
            if self.port_tenu:
                self.start_pendant_port_tenu = True
            elif self.demarre:
                self.statut, self.port_tenu = "running", True
            return 200, '{"ok": true, "starting": "NokidoX"}'
        return 404, "{}"


def _brancher(monkeypatch, m, sup):
    monkeypatch.setattr(m, "_call", sup.call)
    monkeypatch.setattr(m, "_port_ouvert", lambda port: sup.port_tenu)
    monkeypatch.setattr(m, "_sous_system", lambda: True)  # pas de detour par le hub
    horloge = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: horloge[0])
    monkeypatch.setattr(time, "sleep", lambda s: horloge.__setitem__(0, horloge[0] + s))
    monkeypatch.setattr(sys, "argv", ["forge_supervisor_ctl.py", "restart", "NokidoX"])


def test_le_start_attend_l_arret_effectif(monkeypatch, capsys):
    m = _module()
    sup = _Superviseur()
    _brancher(monkeypatch, m, sup)
    assert m.main() == 0
    assert not sup.start_pendant_port_tenu, "le start est parti pendant que l'ancien tenait le port"
    sortie = capsys.readouterr().out
    assert "arret CONSTATE" in sortie and "relance ATTEINTE" in sortie, sortie


def test_un_superviseur_illisible_donne_non_mesurable_sans_attendre(monkeypatch, capsys):
    """UNKNOWN n'est pas NO : statut illisible -> ni echec, ni 2 min de sondes, et c'est DIT."""
    m = _module()
    sup = _Superviseur()
    _brancher(monkeypatch, m, sup)
    vrai = sup.call
    monkeypatch.setattr(m, "_call", lambda path, method="GET": (
        (200, "pas du json") if path.endswith("/supervisor/status") else vrai(path, method)))
    assert m.main() == 0
    sortie = capsys.readouterr().out
    assert "NON MESURABLE" in sortie and "ATTEINTE" not in sortie.replace("NON ATTEINTE", ""), sortie
    assert sup.appels.count("/supervisor/status") <= 8, "sondes inutiles sur un superviseur muet"


def test_une_relance_non_atteinte_est_dite_et_echoue(monkeypatch, capsys):
    m = _module()
    sup = _Superviseur(demarre=False)
    _brancher(monkeypatch, m, sup)
    assert m.main() == 1
    assert "relance NON ATTEINTE" in capsys.readouterr().out
