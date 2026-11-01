# -*- coding: utf-8 -*-
"""NR (31/10, choix owner) : rendre les EVINCES suit la meme regle que la reprise Hamilton.

`_reveiller_les_evinces` (28/10) rendait TOUS les services endormis par l'eviction des que la RAM passait sous 65 %
-- meme classe de defaut que l'oscillation Hamilton du 31/10 (42 services repris d'un coup, d7bdddce4). Owner : « la
cognition doit nourrir le reveil utile des surfaces utiles ». Meme admission (_admettre_reprises) : demande prouvee
d'abord, ABSENCE prouvee = reste evince, budget RAM projete (forfait prudent : le registre ne retient pas de poids),
RAM totale illisible = rien ; interrupteur NOKIDO_HAMILTON_REPRISE_BUDGET=0 = comportement d'avant.
"""
# pylint: disable=protected-access,missing-function-docstring  # un NR de regulation exerce ses primitives privees
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_resource_manager as rm  # noqa: E402

TOTAL_GB = 23.7


class _Rep:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _env(monkeypatch, tmp_path, n, total_gb=TOTAL_GB, demandes=None):
    urls = []

    def urlopen(req, timeout=None):
        urls.append(req.full_url.rsplit("/", 1)[-1])
        return _Rep()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(rm, "_supervisor_auth_headers", lambda *a, **k: {})
    monkeypatch.setattr(rm, "_EVINCES_PATH", tmp_path / "evinces.json")
    monkeypatch.setattr(rm, "services_tenus_par_un_bail", lambda: set())
    monkeypatch.setattr(rm, "_ram_totale_gb", lambda: total_gb)
    monkeypatch.setattr(rm, "_demande_du_service", lambda s: (demandes or {}).get(s))
    monkeypatch.delenv("NOKIDO_HAMILTON_REPRISE_BUDGET", raising=False)
    for i in range(n):
        rm._retenir_evince("Svc%02d" % i)
    return urls


def test_le_reveil_des_evinces_tient_dans_le_budget(monkeypatch, tmp_path):
    urls = _env(monkeypatch, tmp_path, 42)
    r = rm._reveiller_les_evinces(64.0)
    assert 0 < len(r) < 42 and urls == r
    plafond = rm._SUPERVISOR_SLEEP_RAM_THRESHOLD - rm._HAMILTON_MARGE_REPRISE_PCT
    assert 64.0 + len(r) * rm._HAMILTON_POIDS_INCONNU_MB / (TOTAL_GB * 1024 / 100) <= plafond + 1e-9
    assert len(rm._evinces()) == 42 - len(r)  # le reste attend le passage suivant, RAM relue


def test_demande_prouvee_d_abord_absence_prouvee_reste_evincee(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, 3, demandes={"Svc00": False, "Svc02": True})
    r = rm._reveiller_les_evinces(30.0)
    assert r[0] == "Svc02" and "Svc00" not in r
    assert set(rm._evinces()) == {"Svc00"}


def test_ram_totale_illisible_rien_n_est_rendu(monkeypatch, tmp_path):
    urls = _env(monkeypatch, tmp_path, 3, total_gb=None)
    assert rm._reveiller_les_evinces(30.0) == [] and urls == []


def test_interrupteur_rend_le_comportement_d_avant(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, 42)
    monkeypatch.setenv("NOKIDO_HAMILTON_REPRISE_BUDGET", "0")
    assert len(rm._reveiller_les_evinces(64.0)) == 42
