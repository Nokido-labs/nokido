"""NR -- la fusion multi-capteurs sonde les ports EN PARALLELE, sans changer ce qu'elle en conclut.

Mesure du 2026-09-24 (job_4b71d0923ef2, apres la purge des preuves) : la phase health tenait
44,9 s, dont 21,5 s pour `audit_meta_sante`. Sur ces 21,5 s, 18,1 s venaient de
`_port_listens` appele EN SERIE : 12 ports de services endormis, chacun jusqu'au delai de
1,50 s (sur la boucle locale Windows, un port ferme ne se refuse qu'apres les reemissions du
SYN, soit au-dela du delai). Les 46 autres sondes ne coutaient rien.

Le correctif ne touche pas au capteur : `probe_all` pre-sonde les ports connus en parallele et
passe chaque resultat a `probe`. Ce qui est garde ici :

  1. le cout ne croit plus avec le nombre de ports fermes (serie -> parallele) ;
  2. le chemin REEL de l'audit (`coverage()`, appele par `audit_meta_sante`) en profite ;
  3. une sonde ILLISIBLE (None) reste illisible -- jamais convertie en « ferme » (False),
     et jamais re-sondee en serie derriere le dos de la pre-sonde ;
  4. `probe()` appele seul (CLI, autres appelants) sonde encore lui-meme.
"""
from __future__ import annotations

import os
import sys
import time

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_sensor_fusion_probe as sf  # noqa: E402

LENT = 0.4   # duree d'une sonde de port simulee (un port ferme reel en coute 1,50 s)
N = 6        # ports declares ; en serie : N * LENT = 2,4 s


def _cabler(monkeypatch, resultat, appels):
    monkeypatch.setattr(sf, "_registry", lambda: {})
    monkeypatch.setattr(sf, "_fleet", lambda: {})
    monkeypatch.setattr(sf, "_heartbeat_age", lambda s: None)
    monkeypatch.setattr(sf, "_declared_services",
                        lambda: {"Svc%d" % i: {"port": 9100 + i} for i in range(N)})

    def lent(port, timeout=1.5):
        appels.append(int(port))
        time.sleep(LENT)
        return resultat

    monkeypatch.setattr(sf, "_port_listens", lent)


def test_probe_all_sonde_les_ports_en_parallele(monkeypatch):
    appels: list[int] = []
    _cabler(monkeypatch, False, appels)
    t0 = time.perf_counter()
    res = sf.probe_all()
    duree = time.perf_counter() - t0
    assert len(res) == N
    assert sorted(appels) == [9100 + i for i in range(N)], "chaque port est sonde exactement une fois"
    assert duree < N * LENT / 2, (
        "probe_all a dure %.2f s pour %d ports a %.1f s : les sondes sont encore en SERIE" % (duree, N, LENT))


def test_coverage_chemin_reel_de_l_audit(monkeypatch):
    """`audit_meta_sante` appelle `coverage()` : c'est ce chemin-la qui coutait 21,5 s."""
    appels: list[int] = []
    _cabler(monkeypatch, False, appels)
    t0 = time.perf_counter()
    c = sf.coverage()
    duree = time.perf_counter() - t0
    assert c["services_sondes"] == N and c["observables"] == N
    assert c["par_verdict"] == {"arrete": N}
    assert duree < N * LENT / 2, "coverage() a dure %.2f s : pre-sonde non parallele" % duree


def test_une_sonde_illisible_reste_illisible(monkeypatch):
    """UNKNOWN n'est pas NO : None ne devient ni False, ni une seconde sonde en serie."""
    appels: list[int] = []
    _cabler(monkeypatch, None, appels)
    res = sf.probe_all()
    assert {r["verdict"] for r in res} == {"indeterminable"}
    assert all(r["capteurs"]["port"]["ecoute"] is None for r in res)
    assert len(appels) == N, "une sonde illisible a ete refaite en serie (%d appels pour %d ports)" % (len(appels), N)


def test_probe_seul_sonde_encore_lui_meme(monkeypatch):
    """Les appelants de `probe()` hors `probe_all` (CLI, organes) ne sont pas changes."""
    appels: list[int] = []
    monkeypatch.setattr(sf, "_registry", lambda: {})
    monkeypatch.setattr(sf, "_fleet", lambda: {})
    monkeypatch.setattr(sf, "_heartbeat_age", lambda s: None)
    monkeypatch.setattr(sf, "_port_listens", lambda p, timeout=1.5: appels.append(int(p)) or True)
    r = sf.probe("Seul", port=9200)
    assert appels == [9200]
    assert r["verdict"] == "vivant_non_revendique"
