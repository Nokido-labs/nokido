"""NR — IP-007 : admission par voie exclusive + bail réconciliable (dette 0 NR comblée).

Verrouille l'effet de `forge_lane_admission` :
  1. une lane n'admet qu'UN holder à la fois (refus réactif — pas d'empilement) ;
  2. `release` libère ; un bail EXPIRÉ (TTL) est auto-nettoyé à l'acquisition ;
  3. un bail dont le détenteur est MORT est réconcilié avec le réel (libéré) SANS
     attendre le TTL — le cas où l'hôte meurt au milieu (mesure 2026-08-16) ;
  4. fail-SAFE : un bail JEUNE (<60 s) ou un détenteur VIVANT est CONSERVÉ ;
  5. saturation RAM -> refus fail-closed.

Hermétique : DB en tmp, santé et liveness monkeypatchées, aucun réseau, aucun psutil réel.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_lane_admission as L  # noqa: E402

SAIN = {"cpu_pct": 10.0, "ram_pct": 10.0, "ram_dispo_gb": 16.0, "source": "test"}


@pytest.fixture
def lanes(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "_DB_PATH", tmp_path / "lanes.db")
    monkeypatch.setattr(L, "_get_system_health", lambda: dict(SAIN))
    monkeypatch.setattr(L, "_holder_termine", lambda h: False)  # défaut : nul n'est mort
    return L


def _inserer(mod, lane, holder, acquired, expiry):
    c = mod._conn()
    try:
        c.execute("INSERT INTO lane_leases (lane, holder, acquired, expiry) VALUES (?,?,?,?)",
                  (lane, holder, acquired, expiry))
    finally:
        c.close()


def test_admission_exclusive(lanes):
    assert lanes.acquire("gpu", "job_a") is True
    assert lanes.acquire("gpu", "job_b") is False          # refus réactif
    assert lanes.acquire("gpu", "job_a") is True           # même holder = refresh
    assert lanes.current("gpu")["holder"] == "job_a"


def test_release_libere(lanes):
    assert lanes.acquire("gpu", "job_a") is True
    lanes.release("gpu", "job_a")
    assert lanes.current("gpu") is None
    assert lanes.acquire("gpu", "job_b") is True


def test_bail_expire_auto_libere(lanes):
    now = time.time()
    _inserer(lanes, "gpu", "job_vieux", now - 100, now - 1)   # déjà expiré
    assert lanes.acquire("gpu", "job_b") is True


def test_bail_reconcilie_si_holder_mort(lanes, monkeypatch):
    monkeypatch.setattr(L, "_holder_termine", lambda h: h == "job_mort")
    now = time.time()
    _inserer(lanes, "gpu", "job_mort", now - 120, now + 9999)  # âgé + non expiré
    assert lanes.current("gpu") is None                        # réconcilié avec le réel
    assert lanes.acquire("gpu", "job_neuf") is True


def test_failsafe_bail_jeune_conserve(lanes, monkeypatch):
    monkeypatch.setattr(L, "_holder_termine", lambda h: True)  # détenteur mort...
    now = time.time()
    _inserer(lanes, "gpu", "job_jeune", now - 5, now + 9999)   # ...mais bail JEUNE (<60 s)
    assert (lanes.current("gpu") or {}).get("holder") == "job_jeune"  # conservé


def test_failsafe_holder_vivant_conserve(lanes, monkeypatch):
    monkeypatch.setattr(L, "_holder_termine", lambda h: False)  # détenteur vivant
    now = time.time()
    _inserer(lanes, "gpu", "job_vivant", now - 120, now + 9999)  # âgé mais vivant
    assert (lanes.current("gpu") or {}).get("holder") == "job_vivant"  # conservé


def test_ram_saturee_refuse_fail_closed(lanes, monkeypatch):
    monkeypatch.setattr(L, "_get_system_health",
                        lambda: {"cpu_pct": 10.0, "ram_pct": 95.0, "ram_dispo_gb": 0.5,
                                 "source": "test"})
    assert lanes.acquire("gpu", "job_a") is False           # embolie RAM -> refus
