# -*- coding: utf-8 -*-
"""NR 4/11 : importer le keeper ne doit pas ouvrir son journal.

`_journal_fichier()` tournait au niveau du module. Tout importeur (admission des lanes, agent de veille, superviseur
Docker, forge_ensure_service) posait alors un RotatingFileHandler sur SON logger racine, vers le meme fichier. Sous
Windows, un second processus qui tient le fichier fait echouer la rotation en WinError 32 : a 2 Mo, chaque ligne du
keeper part en erreur et n'est plus ecrite (journal fige a 11:16 le 4/11, generations .1 et .2 perdues).
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "tools")]


@pytest.mark.timeout(150)
def test_importer_le_keeper_n_ouvre_pas_son_journal():
    """Chemin reel : un processus neuf importe le module, comme le fait un importeur en production.

    On compte les TENTATIVES d'ouverture, pas les handlers poses : sous un compte sans droit d'ecriture sur le journal
    (bac a sable des jobs), l'ouverture echoue et est avalee, et un comptage de handlers rendait un faux vert.
    """
    code = (
        "import logging.handlers as lh, sys\n"
        "ouvertures = []\n"
        "class Faux(lh.RotatingFileHandler):\n"
        "    def __init__(self, nom, *a, **k):\n"
        "        ouvertures.append(str(nom))\n"
        "        raise PermissionError('sonde du NR')\n"
        "lh.RotatingFileHandler = Faux\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import forge_docker_keeper\n"
        "print('OUVERTURES=%d' % sum('docker_keeper.log' in o for o in ouvertures))\n"
    )
    env = dict(os.environ, PYTHONNOUSERSITE="1")
    r = subprocess.run([sys.executable, "-c", code, str(RACINE / "tools")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120, env=env, cwd=str(RACINE))
    assert r.returncode == 0, r.stderr[-1500:]
    assert "OUVERTURES=0" in r.stdout, r.stdout[-500:]


def test_le_service_ouvre_toujours_son_journal(monkeypatch):
    """Le keeper reste bavard : main() ouvre le journal, sinon le correctif le rendrait muet (mesure du 5/09)."""
    import forge_docker_keeper as K

    class Arret(Exception):
        pass

    def _stop(*_a, **_k):
        raise Arret()   # premiere ligne de main() : la vraie boucle du keeper ne demarre jamais sous test

    ouvert = []
    monkeypatch.setattr(K, "_journal_fichier", lambda: ouvert.append(True))
    monkeypatch.setattr(K.log, "info", _stop)
    with pytest.raises(Arret):
        K.main()
    assert ouvert, "main() demarre sans ouvrir son journal"
