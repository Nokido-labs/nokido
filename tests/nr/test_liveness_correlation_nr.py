# -*- coding: utf-8 -*-
"""NR — un pouls d'ORPHELIN ne rehabilite pas son organe.

Defaut ferme le 2026-09-05. `autorites()` derivait la vie de la seule FRAICHEUR du
pouls, si bien que `tdr_sentinel` et `docker_keeper` sortaient vivants pendant que
`forge_process_inventory` disait, au meme instant, « bat encore alors que le pid declare
est mort ». Deux instruments se contredisaient et le plus OPTIMISTE gagnait.

Le pouls n'est pas supprime : le signal d'un orphelin est une preuve de DYSFONCTIONNEMENT,
pas de sante. C'est l'inference qu'on corrige, pas la mesure.

SYMETRIE A TENIR — l'absence de pid n'est PAS la mort. 24 pouls sur 49 n'ecrivent aucun
pid ; les declarer morts remplacerait une sur-deduction par une autre, et fabriquerait
24 pannes fictives. D'ou le troisieme etat.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus schtasks (code appele, Windows)
#   (l.85)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_nervous_map as N  # noqa: E402

FRAIS = {"present": True, "alive": True, "age_s": 12}
PERIME = {"present": True, "alive": False, "age_s": 999999}
ILLISIBLE = {"present": True, "alive": None, "err": "JSONDecodeError"}


def _pid_libre() -> int:
    """Un pid que le systeme ne porte PAS — cherche, pas invente.

    Fabriquer ce cas par monkeypatch testerait le mock ; on veut que la sonde reelle
    reponde « ce porteur n'existe plus ».
    """
    psutil = pytest.importorskip("psutil")
    for candidat in range(999_999, 900_000, -7):
        if not psutil.pid_exists(candidat):
            return candidat
    pytest.skip("aucun pid libre trouve : la sonde ne peut pas etre exercee")


def test_pouls_frais_sous_pid_mort_ne_vaut_JAMAIS_vivant():
    """L'invariant qui ferme le trou. Tout le reste en decoule."""
    vivant, preuve = N.liveness(FRAIS, _pid_libre())
    assert vivant == N.VIVANT_NON, (vivant, preuve)
    assert "ORPHELIN" in preuve, preuve


def test_pouls_frais_sous_pid_vivant_vaut_vivant():
    """Le test miroir : un garde qui rend tout suspect ne discrimine plus rien."""
    vivant, preuve = N.liveness(FRAIS, os.getpid())
    assert vivant == N.VIVANT_OUI, (vivant, preuve)


def test_absence_de_pid_rend_INCERTAIN_et_non_mort():
    vivant, preuve = N.liveness(FRAIS, None)
    assert vivant == N.VIVANT_INCERTAIN, (vivant, preuve)
    assert "identity_unbound" in preuve, preuve


def test_pouls_perime_ne_vaut_jamais_vivant_quel_que_soit_le_pid():
    for pid in (None, os.getpid()):
        vivant, preuve = N.liveness(PERIME, pid)
        assert vivant != N.VIVANT_OUI, (pid, vivant, preuve)
        assert preuve == "heartbeat_stale"


def test_pouls_illisible_ou_absent_reste_INCONNU():
    """Trois etats, jamais deux : « je n'ai pas pu lire » n'est pas « il est mort »."""
    assert N.liveness(ILLISIBLE, os.getpid())[0] == N.VIVANT_INCONNU
    assert N.liveness({}, os.getpid())[0] == N.VIVANT_INCONNU


def test_sur_la_flotte_REELLE_aucun_vivant_sans_porteur():
    """La regle doit tenir sur les donnees vivantes, pas seulement sur des cas ecrits."""
    psutil = pytest.importorskip("psutil")
    try:
        organes = N.autorites()["organes"]
    except Exception as exc:  # noqa: BLE001
        pytest.skip("topologie illisible (%s) — on ne conclut pas d'une source qui se "
                    "tait" % exc)
    fautifs = []
    for f in organes:
        if f.get("producteur_vivant") != N.VIVANT_OUI:
            continue
        pid = f.get("pid")
        # `producteur_vivant == OUI` EXIGE un porteur : sans pid, l'inference aurait
        # du s'arreter a INCERTAIN.
        if pid is None or not psutil.pid_exists(int(pid)):
            fautifs.append((f["organe"], pid, f.get("producteur_preuve")))
    assert not fautifs, (
        "organe(s) declare(s) VIVANTS sans porteur existant — le pouls d'un orphelin "
        "rehabilite encore son organe : %s" % fautifs)
