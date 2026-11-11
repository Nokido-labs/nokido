"""NR -- l'outil `web_search` DIT par quel etage il a repondu et quels etages ont echoue (10/11 soir).

Mesure : SearXNG :8080 en TIMEOUT (Docker endormi) ; la cascade T2a a bascule sur Tavily (correct, payant) et
l'outil n'a rendu que les resultats, etiquetes `[tavily]`, sans dire que SearXNG avait echoue ni pourquoi : le
repli payant passait pour le regime nominal. Contrat de `rendre_diag` :
  1. resultats + erreurs -> les resultats, PUIS une ligne nommant la source et chaque etage en erreur ;
  2. resultats sans erreur ni alerte -> rendu historique inchange (format_results seul) ;
  3. aucune resultat + erreurs -> « RECHERCHE NON FAITE », jamais « aucun resultat » ;
  4. rien et aucune erreur -> « Aucun resultat » ;
  5. une alerte (budget Tavily 80 %) est rendue meme sans erreur.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_web_fallback as W  # noqa: E402

_R = [{"title": "t", "url": "https://ex.org/a", "content": "c", "_source": "tavily"}]


def test_repli_nomme_source_et_etages_en_erreur():
    d = {"results": _R, "erreurs": ["default/TimeoutError: timed out"], "source": "tavily"}
    txt = W.rendre_diag(d)
    assert txt.startswith(W.format_results(_R))
    assert "source=tavily" in txt
    assert "default/TimeoutError: timed out" in txt


def test_nominal_sans_erreur_rendu_inchange():
    d = {"results": _R, "erreurs": [], "source": "searxng"}
    assert W.rendre_diag(d) == W.format_results(_R)


def test_echec_total_jamais_aucun_resultat():
    txt = W.rendre_diag({"results": [], "erreurs": ["default/URLError: refused"], "source": None})
    assert txt.startswith("RECHERCHE NON FAITE")
    assert "refused" in txt


def test_rien_trouve_sans_erreur():
    assert W.rendre_diag({"results": [], "erreurs": [], "source": None}).startswith("Aucun resultat")


def test_alerte_rendue_sans_erreur():
    d = {"results": _R, "erreurs": [], "source": "tavily", "alertes": ["tavily: 80 % du budget mensuel (800/1000)"]}
    assert "80 % du budget" in W.rendre_diag(d)
