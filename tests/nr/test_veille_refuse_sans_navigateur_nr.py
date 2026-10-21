"""NR -- Poka-Yoke de la veille : sans crawl4ai, l'ingestion REFUSE de demarrer (sauf repli demande explicitement).

16/10 (owner : « je ne t'ai pas vu faire les veilles avec crawl4ai ») : 129 pages ingerees par repli urllib malgre
« CRAWL4AI INJOIGNABLE » imprime a chaque lot ; rattrapage mesure le meme jour : 123/129 pages ENRICHIES par
crawl4ai (Three Amigos 4 -> 86 fragments). Un avertissement qu'on peut ignorer ne protege rien : le refus rend
l'erreur impossible, et le remede est dans le message.
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_ingest_llms_txt as I  # noqa: E402


def _lancer(monkeypatch, joignable, *drapeaux):
    appels = []
    monkeypatch.setattr(I, "_crawl4ai_joignable", lambda: joignable)
    monkeypatch.setattr(I, "ingerer", lambda *a, **k: appels.append(a) or {"pages_total": 1})
    monkeypatch.setattr(sys, "argv", ["forge_ingest_llms_txt.py", "--urls", "https://exemple.invalid/p", *drapeaux])
    return I.main(), appels


def test_sans_navigateur_la_veille_refuse_de_demarrer(monkeypatch):
    rc, appels = _lancer(monkeypatch, False)
    assert (rc, appels) == (4, [])


def test_le_repli_urllib_reste_possible_sur_demande_explicite(monkeypatch):
    rc, appels = _lancer(monkeypatch, False, "--sans-navigateur")
    assert (rc, len(appels)) == (0, 1)


def test_navigateur_joignable_la_veille_demarre(monkeypatch):
    rc, appels = _lancer(monkeypatch, True)
    assert (rc, len(appels)) == (0, 1)
