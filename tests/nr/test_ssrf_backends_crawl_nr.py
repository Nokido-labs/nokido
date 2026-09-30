"""NR — les back-ends de récupération web refusent les adresses internes.

Audit du 2026-09-19, classe « SSRF et egress non gouverné », mené par un agent
local puis VÉRIFIÉ ici.

## Ce qui a été mesuré

`tools/forge_web_egress._ssrf_blocked` existe et fonctionne : il refuse
loopback, `localhost`, les plages privées, le lien-local et
`169.254.169.254`, et laisse passer le web public. Mais deux back-ends ne
passaient pas par ce gateway :

    app/forge_crawl_tool.py   2 urlopen
    app/forge_web_fetch.py    1 urlopen

et **neuf appelants** les invoquent directement — dont `forge_mcp_registry`
(surface MCP) et la veille, qui traite des URL de tiers par nature. Le garde
était sur le site d'appel, pas sur l'organe qui AGIT. Troisième occurrence du
même motif dans la même journée.

L'enjeu est concret : Nokido déclare 37 ports en boucle locale, dont le hub
`:8766` et le webhub `:7400`.

## Ce que ce test NE dit pas

Il ne prouve pas qu'un SSRF était exploitable de bout en bout : il faudrait
qu'une URL hostile atteigne ces fonctions par un chemin complet. Il verrouille
le garde, pas un scénario.

## ⚠️ Le contrôle négatif est ESSENTIEL ici

`CRAWL4AI_URL` vise `127.0.0.1:11235` — le service qui CRAWLE. Un garde qui
bloquerait tout trafic local casserait le crawl. Le garde porte donc sur l'URL
CIBLE, et les tests le vérifient dans les deux sens.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : resolution DNS reelle (code appele) (l.73)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app import forge_crawl_tool as CT  # noqa: E402
from app import forge_web_fetch as WF  # noqa: E402

INTERNES = [
    "http://127.0.0.1:8766/health",
    "http://localhost:7400/admin",
    "http://169.254.169.254/latest/meta-data/",
    "http://localhost/",
    "http://localhost/",
]
PUBLIQUES = [
    "https://example.com/page",
    "https://arxiv.org/abs/2401.00001",
]


@pytest.mark.parametrize("url", INTERNES)
def test_les_adresses_internes_sont_refusees_par_les_deux_backends(url):
    assert CT._url_interdite(url), "crawl_tool laisse passer %s" % url
    assert WF._url_interdite(url), "web_fetch laisse passer %s" % url


@pytest.mark.parametrize("url", PUBLIQUES)
def test_le_web_public_PASSE_toujours(url):
    """Contrôle négatif : un garde qui ferme tout serait desactive des demain."""
    assert not CT._url_interdite(url), "crawl_tool refuse a tort %s" % url
    assert not WF._url_interdite(url), "web_fetch refuse a tort %s" % url


def test_le_chemin_REEL_du_crawl_refuse_sans_toucher_au_reseau():
    """`crawl_url_detail`, pas seulement le helper : c'est la fonction publique."""
    r = CT.crawl_url_detail("http://127.0.0.1:8766/health", timeout=3)
    assert r.get("qualite") == "refus"
    assert r.get("backend") == "aucun"


def test_le_chemin_REEL_du_fetch_refuse_et_NOMME_l_hote():
    """Et il ne doit pas lever : ce module n'avait aucun `logger`, le premier
    declenchement du garde a produit un NameError — un garde qui casse a son
    premier tir est une panne, pas une protection."""
    r = WF.fetch_and_ingest("http://localhost:7400/")
    assert r.get("ok") is False
    msg = str(r.get("error", ""))
    assert "interdite" in msg
    assert "localhost" in msg, (
        "le refus doit NOMMER l'hote, sinon il n'est pas diagnosticable")


def test_le_garde_indisponible_ne_fait_pas_passer_le_loopback(monkeypatch):
    """Fail-CLOSED sur le cas dangereux.

    Si le gateway devient inimportable, on refuse quand meme l'hote local. Un
    fail-open sur une verification SSRF ouvrirait les ports en boucle locale.
    """
    import builtins

    vrai_import = builtins.__import__

    def import_casse(nom, *a, **k):
        if "forge_web_egress" in nom:
            raise ImportError("indisponible (simule)")
        return vrai_import(nom, *a, **k)

    monkeypatch.setattr(builtins, "__import__", import_casse)
    # Garde de morsure : la substitution doit reellement casser l'import.
    with pytest.raises(ImportError):
        __import__("nokido_agent.tools.forge_web_egress")

    assert CT._url_interdite("http://127.0.0.1:8766/"), "repli trop permissif (crawl)"
    assert WF._url_interdite("http://localhost:7400/"), "repli trop permissif (fetch)"
    # et le public passe toujours, meme en mode degrade
    assert not CT._url_interdite("https://example.com/")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
