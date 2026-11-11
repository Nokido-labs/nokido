"""NR (owner 2/11, levier 1) : le keeper vide le cache Linux de la VM Docker quand son SURCOUT le justifie.

Mesure du 2/11 : conteneurs ~1,0 Gio (searxng 227 Mio + crawl4ai 778 Mio) pour vmmemWSL 4,56 Go ; un drop_caches
manuel -> 3,99 Go (gain progressif, autoMemoryReclaim). Regle : surcout (vmmem - conteneurs) > seuil -> vidage, au
plus une fois par periode refractaire ; mesure illisible -> rien (UNKNOWN != 0). Le vidage ne touche pas aux
conteneurs : il n'attend pas la fin des veilles (c'est pendant elles que la RAM bloque leur admission)."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]


def _k():
    spec = importlib.util.spec_from_file_location("keeper_vidage_nr", RACINE / "tools" / "forge_docker_keeper.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_decision_selon_le_surcout_et_la_refraction():
    k = _k()
    s = k._VIDAGE_SEUIL_MO
    assert k.decider_vidage_cache(4560, 1000, None, 1000.0)[0] is True
    assert k.decider_vidage_cache(1000 + s - 1, 1000, None, 1000.0)[0] is False, "sous le seuil"
    assert k.decider_vidage_cache(4560, 1000, 1000.0 - 10, 1000.0)[0] is False, "periode refractaire"
    assert k.decider_vidage_cache(4560, 1000, 1000.0 - k._VIDAGE_REFRACTAIRE_S - 1, 1000.0)[0] is True
    for illisible in ((None, 1000), (4560, None)):
        ok, motif = k.decider_vidage_cache(*illisible, None, 1000.0)
        assert ok is False and "illisible" in motif


def test_memoire_des_conteneurs_lue_dans_docker_stats():
    k = _k()
    sortie = "226.6MiB / 9.714GiB\n777.7MiB / 3GiB\n1.2GiB / 3GiB\n"
    assert round(k.memoire_conteneurs_mo(sortie)) == round(226.6 + 777.7 + 1.2 * 1024)
    assert k.memoire_conteneurs_mo("") == 0.0
    assert k.memoire_conteneurs_mo(None) is None


def test_le_tick_vide_le_cache_et_journalise_l_avant(monkeypatch):
    k = _k()
    appels, audits = [], []
    monkeypatch.setattr(k, "mesurer_surcout_vm", lambda: (4560.0, 1000.0))
    monkeypatch.setattr(k, "_vider_cache_wsl", lambda: appels.append(1) or (0, ""))
    monkeypatch.setattr(k, "_audit", lambda action, reason, **extra: audits.append((action, extra)))
    monkeypatch.setattr(k, "_dernier_vidage", None, raising=False)
    r = k._tick_vidage_cache(1000.0)
    assert appels == [1] and r["vidage"] is True and r["surcout_mo"] == 3560
    assert audits and audits[0][0] == "vidage_cache_wsl" and audits[0][1]["vmmem_avant_mo"] == 4560
    r2 = k._tick_vidage_cache(1010.0)
    assert appels == [1] and r2["vidage"] is False, "refractaire : pas de 2e vidage 10 s apres"


def test_le_vidage_vise_la_vm_docker_sans_arret():
    k = _k()
    cmd = k._commande_vidage_cache()
    assert cmd[-1] == "sync; echo 1 > /proc/sys/vm/drop_caches"
    assert "docker-desktop" in cmd and "root" in cmd
    assert "--shutdown" not in cmd and "--terminate" not in cmd
