# -*- coding: utf-8 -*-
"""NR (28/10) : la regulation REVEILLE ce qu'elle a endormi quand la pression retombe.

Mesure 28/10 (laforge-master.log) : 11:36:35 RAM 90 % -> sommeil des non-essentiels, 11:37:11-15
POST /supervisor/sleep sur une quinzaine de services dont les NokidoTaskExecutor* (eviction Hamilton,
_sleep_service_verdict). RAM a 52 % des 11:51, une tache en attente : personne ne les a rendus, toute la
surface a l'arret 47 min (reveil manuel 12:23). Trois defauts : (1) le reveil ne tournait que Hamilton
DESARME ; (2) rien ne retenait ce que l'eviction endormait ; (3) le reveil appelait /wake/<svc>, route
absente du superviseur (404, cf. 93f3c5fac) -- la bonne est /service/start/<svc>.
"""
# pylint: disable=protected-access,missing-function-docstring  # un NR de regulation exerce ses primitives privees
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_resource_manager as rm  # noqa: E402


class _Rep:
    """Reponse urlopen factice (gestionnaire de contexte)."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capturer(monkeypatch):
    urls = []

    def urlopen(req, timeout=None):
        urls.append(req.full_url)
        return _Rep()

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(rm, "_supervisor_auth_headers", lambda *a, **k: {})
    return urls


def test_aucun_reveil_par_la_route_wake_absente(monkeypatch):
    urls = _capturer(monkeypatch)
    monkeypatch.setattr(rm, "services_tenus_par_un_bail", lambda: set())
    rm._supervisor_wake_non_essential()
    rm._ordre_superviseur("NokidoX", "REPRENDRE")
    assert urls and not [u for u in urls if "/wake/" in u], urls
    assert all("/service/start/" in u for u in urls)


def test_l_eviction_retient_ce_qu_elle_endort(monkeypatch, tmp_path):
    _capturer(monkeypatch)
    monkeypatch.setattr(rm, "_EVINCES_PATH", tmp_path / "evinces.json")
    ok, _ = rm._sleep_service_verdict("NokidoTaskExecutorOpencodeGptoss")
    assert ok and "NokidoTaskExecutorOpencodeGptoss" in rm._evinces()


def test_pression_retombee_reveille_les_evinces(monkeypatch, tmp_path):
    urls = _capturer(monkeypatch)
    monkeypatch.setattr(rm, "_EVINCES_PATH", tmp_path / "evinces.json")
    monkeypatch.setattr(rm, "services_tenus_par_un_bail", lambda: {"NokidoTenu"})
    rm._retenir_evince("NokidoTaskExecutor")
    rm._retenir_evince("NokidoTenu")
    assert rm._reveiller_les_evinces(rm._SUPERVISOR_WAKE_RAM_THRESHOLD + 5) == []  # pression encore haute
    assert urls == []
    reveilles = rm._reveiller_les_evinces(rm._SUPERVISOR_WAKE_RAM_THRESHOLD - 10)
    assert reveilles == ["NokidoTaskExecutor"]
    assert urls == [f"{rm._SUPERVISOR_URL}/service/start/NokidoTaskExecutor"]
    assert set(rm._evinces()) == {"NokidoTenu"}  # tenu par un bail : garde, pas rendu


def test_un_test_n_ecrit_jamais_le_vrai_registre(monkeypatch):
    """Mesure 28/10 : apres le job de 391 tests, le VRAI sandbox/regulation_evinces.json contenait {"Ok": ...} --
    un test appelant _sleep_service_verdict("Ok") sous urlopen simule. Meme classe que les vetos (b180bdb8e)."""
    monkeypatch.setattr(rm, "_EVINCES_PATH", rm._EVINCES_PATH_DEFAUT)
    monkeypatch.delenv("LAFORGE_REGULATION_EVINCES_PATH", raising=False)
    assert rm._evinces_path() is None  # sous pytest, sans emplacement fourni : aucune persistance
    monkeypatch.setenv("LAFORGE_REGULATION_EVINCES_PATH", "C:/ailleurs/evinces.json")
    assert str(rm._evinces_path()).replace("\\", "/") == "C:/ailleurs/evinces.json"


def test_le_sampler_appelle_le_reveil_des_evinces_hamilton_arme_ou_non():
    src = (ROOT / "app" / "forge_resource_manager.py").read_text(encoding="utf-8")
    assert "_reveiller_les_evinces(ram_pct)" in src, "aucun appelant : le reveil des evinces serait du code mort"
