# -*- coding: utf-8 -*-
"""NR — RFC 9309 : le crawl de Nokido demande la permission, et s'identifie.

Ecrit apres que l'audit NPSC du 2026-09-04 a rendu RFC-9309 en VIOLATION :
33 modules recuperaient des pages web arbitraires, `robotparser` /
`robots.txt` / `can_fetch` n'apparaissaient dans AUCUN fichier versionne, et
le crawleur se declarait `Mozilla/5.0 (Windows NT 10.0; Win64; x64)`.

Le point le plus contre-intuitif de la norme, et celui que ce garde protege en
priorite : **404 AUTORISE, 500 INTERDIT** (section 2.3.1.3). « Il n'y a pas de
robots.txt » et « je n'ai pas pu lire robots.txt » sont deux choses opposees.
Un fail-open sur l'erreur serveur passerait inapercu en test comme en prod,
puisqu'il produit exactement le comportement d'avant.

Hermetique : aucun acces reseau, `urlopen` est remplace dans chaque cas.
"""
from __future__ import annotations

import io
import re
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_robots as rb  # noqa: E402


class _Reponse(io.BytesIO):
    """Reponse HTTP minimale utilisable en gestionnaire de contexte."""

    def __init__(self, corps: bytes, status: int = 200, entetes=None):
        super().__init__(corps)
        self.status = status
        self.headers = entetes or {}

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        self.close()
        return False


def _servir(monkeypatch, corps=b"", status=200, exc=None, entetes=None):
    def faux(_requete, timeout=None):
        if exc is not None:
            raise exc
        return _Reponse(corps, status, entetes)
    monkeypatch.setattr(rb.urllib.request, "urlopen", faux)


@pytest.fixture(autouse=True)
def _cache_propre():
    rb.purger_cache()
    yield
    rb.purger_cache()


# --------------------------------------------------------------------------
# Section 2.2.1 — identification du crawleur
# --------------------------------------------------------------------------

def test_product_token_est_conforme_et_ne_se_deguise_pas():
    """Un product token : lettres, tiret, underscore. Et surtout pas un navigateur."""
    assert re.fullmatch(r"[A-Za-z_-]+", rb.PRODUCT_TOKEN), rb.PRODUCT_TOKEN
    assert "Mozilla" not in rb.USER_AGENT, "le crawleur se deguise en navigateur"
    assert "AppleWebKit" not in rb.USER_AGENT
    assert rb.PRODUCT_TOKEN in rb.USER_AGENT


def test_le_crawl_du_hub_n_annonce_plus_un_navigateur():
    """EFFET : plus aucun User-Agent mensonger dans le module de crawl.

    Un site ne peut pas nous adresser une directive s'il ne peut pas nous
    nommer : se declarer Chrome rend les regles du site inapplicables.
    """
    source = (ROOT / "app" / "forge_crawl_tool.py").read_text(encoding="utf-8")
    lignes_ua = [l for l in source.splitlines()
                 if "User-Agent" in l and not l.lstrip().startswith("#")]
    for ligne in lignes_ua:
        assert "Mozilla" not in ligne, "User-Agent mensonger : %s" % ligne.strip()


# --------------------------------------------------------------------------
# Section 2.3.1.3 — ce que vaut le RESULTAT de la recuperation
# --------------------------------------------------------------------------

def test_404_autorise_le_crawl(monkeypatch):
    """« Unavailable » : aucun robots.txt ne nous restreint, l'acces est libre."""
    _servir(monkeypatch, exc=urllib.error.HTTPError("u", 404, "Not Found", {}, None))
    d = rb.decision("https://exemple.test/page")
    assert d["autorise"] is True
    assert d["statut_robots"] == rb.ROBOTS_ABSENT


def test_500_interdit_le_crawl(monkeypatch):
    """LE point de la norme : « unreachable » -> interdiction supposee.

    Un fail-open ici serait invisible, puisqu'il reproduit le comportement
    d'avant le correctif.
    """
    _servir(monkeypatch, exc=urllib.error.HTTPError("u", 503, "Unavailable", {}, None))
    d = rb.decision("https://exemple.test/page")
    assert d["autorise"] is False, "un 5xx a laisse passer le crawl"
    assert d["statut_robots"] == rb.ROBOTS_INJOIGNABLE
    assert "interdiction" in d["motif"]


def test_erreur_reseau_interdit_le_crawl(monkeypatch):
    """Timeout, DNS, TLS : traites comme unreachable, donc refus."""
    _servir(monkeypatch, exc=TimeoutError("delai depasse"))
    d = rb.decision("https://exemple.test/page")
    assert d["autorise"] is False
    assert d["statut_robots"] == rb.ROBOTS_INJOIGNABLE


# --------------------------------------------------------------------------
# Section 2.2.2 — application des regles
# --------------------------------------------------------------------------

def test_disallow_est_respecte(monkeypatch):
    _servir(monkeypatch, corps=b"User-agent: *\nDisallow: /prive\n")
    assert rb.decision("https://exemple.test/prive/x")["autorise"] is False
    assert rb.decision("https://exemple.test/public/x")["autorise"] is True


def test_regle_ciblant_notre_token_prime(monkeypatch):
    """Une regle nommant NokidoBot doit s'appliquer a NokidoBot."""
    corps = ("User-agent: *\nDisallow:\n\n"
             "User-agent: %s\nDisallow: /\n" % rb.PRODUCT_TOKEN).encode("utf-8")
    _servir(monkeypatch, corps=corps)
    d = rb.decision("https://exemple.test/quoi-que-ce-soit")
    assert d["autorise"] is False, "la regle nominative a ete ignoree"


def test_url_non_http_reste_hors_portee(monkeypatch):
    """RFC 9309 ne couvre pas file:// ou data: — y repondre non serait invente."""
    _servir(monkeypatch, exc=AssertionError("aucun reseau ne doit etre touche"))
    d = rb.decision("file:///C:/tmp/x.html")
    assert d["autorise"] is True
    assert d["statut_robots"] == "HORS_PORTEE"


# --------------------------------------------------------------------------
# Section 2.4 — cache
# --------------------------------------------------------------------------

def test_robots_est_mis_en_cache(monkeypatch):
    """Un robots.txt par origine, pas un par URL : sinon le crawl le martele."""
    appels = {"n": 0}

    def faux(_requete, timeout=None):
        appels["n"] += 1
        return _Reponse(b"User-agent: *\nDisallow: /x\n", 200, {})
    monkeypatch.setattr(rb.urllib.request, "urlopen", faux)
    for _ in range(5):
        rb.decision("https://exemple.test/page")
    assert appels["n"] == 1, "robots.txt recupere %d fois" % appels["n"]


def test_ttl_borne_a_24h(monkeypatch):
    """La norme dit « SHOULD NOT be longer than 24 hours »."""
    _servir(monkeypatch, corps=b"User-agent: *\nDisallow:\n", status=200,
            entetes={"Cache-Control": "max-age=999999"})
    rb.decision("https://exemple.test/p")
    entree = rb._cache["https://exemple.test"]
    import time as _t
    assert entree["expire"] - _t.time() <= rb.TTL_DEFAUT_S + 5


# --------------------------------------------------------------------------
# Effet sur le crawl reel
# --------------------------------------------------------------------------

def test_le_crawl_refuse_et_le_DIT(monkeypatch):
    """EFFET bout en bout : un refus robots arrete le crawl, avec son motif.

    Et il sort en qualite `refus`, pas `erreur` : le crawl n'a pas echoue, il
    n'a pas eu le droit. Confondre les deux ferait chercher une panne la ou il
    y a une regle.
    """
    import forge_crawl_tool as ct
    monkeypatch.setattr(ct, "_robots_decision", lambda url: {
        "autorise": False, "statut_robots": rb.ROBOTS_OK, "origine": "https://exemple.test",
        "motif": "INTERDIT par robots.txt pour NokidoBot"})
    res = ct.crawl_url_detail("https://exemple.test/interdit")
    assert res["qualite"] == "refus", res
    assert "robots.txt" in res["text"]
    assert res["backend"] == "aucun"


def test_module_de_conformite_absent_ferme_le_crawl():
    """Le repli d'import est FERME : sans le module, on refuse au lieu de crawler.

    Un garde qui s'efface quand sa dependance manque ne garde rien. Ici le
    fichier declare explicitement ce comportement — on le verifie a la source
    plutot que de desinstaller un module pendant les tests.
    """
    source = (ROOT / "app" / "forge_crawl_tool.py").read_text(encoding="utf-8")
    bloc = source.split("except Exception as _exc_robots")[1][:600]
    assert '"autorise": False' in bloc, "le repli d'import laisse passer le crawl"
