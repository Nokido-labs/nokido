# -*- coding: utf-8 -*-
"""NR : le catalogue du gateway Docker MCP se lit depuis le cache SANS reveiller Docker.

ABSENT n'est pas vide, un cache perime ou illisible le dit, et la lecture n'appelle jamais
ensure_daemon ni spawn_gateway_stdio (lister les outils ne doit pas allumer Docker).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_docker_supervisor as fds  # noqa: E402


def _interdire_le_reveil(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("la lecture du cache a tente de reveiller Docker")
    monkeypatch.setattr(fds.DockerSupervisor, "ensure_daemon", boom)
    monkeypatch.setattr(fds.DockerSupervisor, "spawn_gateway_stdio", boom)
    monkeypatch.setattr(fds, "_demander_docker", boom)


def _ecrire(chemin, horodatage, outils):
    data = {"outils": outils}
    if horodatage is not None:
        data["horodatage"] = horodatage
    chemin.write_text(json.dumps(data), encoding="utf-8")


def test_absent(tmp_path, monkeypatch):
    _interdire_le_reveil(monkeypatch)
    assert fds.catalogue_en_cache(tmp_path / "absent.json") == {"etat": "ABSENT", "outils": []}


def test_frais(tmp_path, monkeypatch):
    _interdire_le_reveil(monkeypatch)
    c = tmp_path / "cat.json"
    _ecrire(c, datetime.now(timezone.utc).isoformat(), [{"name": "fetch"}])
    r = fds.catalogue_en_cache(c)
    assert r["etat"] == "FRAIS" and r["outils"] == [{"name": "fetch"}]


def test_perime_apres_le_delai(tmp_path, monkeypatch):
    _interdire_le_reveil(monkeypatch)
    c = tmp_path / "cat.json"
    vieux = datetime.now(timezone.utc) - timedelta(hours=fds.CATALOG_MAX_AGE_HOURS + 1)
    _ecrire(c, vieux.isoformat(), [{"name": "fetch"}])
    r = fds.catalogue_en_cache(c)
    assert r["etat"] == "PERIME" and r["outils"] == [{"name": "fetch"}]


def test_perime_sans_horodatage_ou_illisible(tmp_path, monkeypatch):
    _interdire_le_reveil(monkeypatch)
    c = tmp_path / "cat.json"
    _ecrire(c, None, [])
    assert fds.catalogue_en_cache(c)["etat"] == "PERIME"
    c.write_text("{pas du json", encoding="utf-8")
    assert fds.catalogue_en_cache(c) == {"etat": "PERIME", "outils": []}
