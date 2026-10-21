"""NR -- un cache qu'on ne peut pas ecrire ne jette jamais la reponse d'Artificial Analysis (16/10).

RED ecrit par Claude. Mesure 16/10 (job_8d8cb2c7c672, compte du job en ligne) : fetch_llms rendait
« [Errno 13] Permission denied: ...data/artificialanalysis_cache.json », 0 modele -- l'appel API v2 avait repondu, mais
l'echec d'ECRITURE du cache tombait dans le meme except que les erreurs reseau et la reponse etait jetee. Toute la
« degradation » d'Artificial Analysis venait de la. Le cache est une commodite : son echec se DIT dans meta.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_artificialanalysis as AA  # noqa: E402


class _Rep(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_un_cache_non_inscriptible_ne_jette_pas_les_modeles(monkeypatch):
    monkeypatch.setattr(AA, "_load_api_key", lambda: "cle-de-test")
    monkeypatch.setattr(AA.urllib.request, "urlopen",
                        lambda req, timeout=30: _Rep(json.dumps({"data": [{"slug": "a"}, {"slug": "b"}]}).encode()))

    def _refus(payload):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(AA, "_save_cache", _refus)
    p = AA.fetch_llms(force=True)
    assert not p.get("error"), p
    assert [m["slug"] for m in p["models"]] == ["a", "b"], p
    assert "PermissionError" in str(p["meta"].get("cache")), p["meta"]


# --- RED 2 du plan AGY (16/10) : API en erreur -> repli sur le cache PERIME, et le dire --------------------------------
# STALE n'est pas DEAD : un classement d'hier ordonne encore les fournisseurs. Rendre 0 modele parce que l'API ne repond
# pas ce soir vidait best_for_use_case alors que data/ portait 652 modeles. Le repli se DIT (meta.perime, meta.repli).
import os  # noqa: E402
import urllib.error  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def cache_perime(monkeypatch, tmp_path):
    def poser(modeles):
        chemin = tmp_path / "artificialanalysis_cache.json"
        chemin.write_text(json.dumps({"models": modeles, "meta": {"fetched_utc": "2026-10-14T08:00:00Z"}}),
                          encoding="utf-8")
        vieux = chemin.stat().st_mtime - 48 * 3600
        os.utime(chemin, (vieux, vieux))
        monkeypatch.setattr(AA, "CACHE_PATH", chemin)
        monkeypatch.setattr(AA, "_save_cache", lambda payload: None)
        return chemin
    return poser


def _api_en_erreur(monkeypatch):
    monkeypatch.setattr(AA, "_load_api_key", lambda: "cle-de-test")

    def _503(req, timeout=30):
        raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(AA.urllib.request, "urlopen", _503)


def test_une_api_en_erreur_se_replie_sur_le_cache_perime_et_le_dit(monkeypatch, cache_perime):
    cache_perime([{"slug": "a"}])
    _api_en_erreur(monkeypatch)
    p = AA.fetch_llms()
    assert [m["slug"] for m in p["models"]] == ["a"], p
    assert p["meta"].get("perime") is True and "503" in str(p["meta"].get("repli")), p["meta"]


def test_sans_cle_le_cache_perime_sert_aussi(monkeypatch, cache_perime):
    cache_perime([{"slug": "a"}])
    monkeypatch.setattr(AA, "_load_api_key", lambda: None)
    p = AA.fetch_llms()
    assert [m["slug"] for m in p["models"]] == ["a"] and p["meta"].get("repli") == "no_api_key", p


def test_sans_cache_l_erreur_reste_dite(monkeypatch, tmp_path):
    monkeypatch.setattr(AA, "CACHE_PATH", tmp_path / "absent.json")
    _api_en_erreur(monkeypatch)
    p = AA.fetch_llms()
    assert p["models"] == [] and "503" in str(p.get("error")), p


def test_best_for_use_case_classe_encore_sur_le_cache_perime(monkeypatch, cache_perime):
    from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS

    fournisseur = next(iter(PROVIDER_SPECS))
    monkeypatch.setattr(AA, "PROVIDER_AA_MAP", {fournisseur: "slug-temoin"})
    cache_perime([{"slug": "slug-temoin", "evaluations": {"artificial_analysis_coding_index": 42.0}}])
    _api_en_erreur(monkeypatch)
    classement = AA.best_for_use_case("code")
    assert [(c["provider"], c["metric_value"]) for c in classement] == [(fournisseur, 42.0)], classement
