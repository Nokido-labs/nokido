"""NR 2/11 -- disjoncteur SearXNG jamais referme par une preuve de vie.

Mesure du 2/11 (journaux NokidoChainExecutor / NokidoWatchAgent) : « [SEARCH] n=24 searxng_ensured=True
sources={'academic': 24} » -- SearXNG venait d'etre PROUVE pret (vraie requete JSON, HTTP 200) par
`_ensure_searxng`, et pourtant chaque requete sautait SearXNG (« searxng CB open, skip direct fallback academic ») :
trois echecs pendant le boot avaient ouvert le circuit 15 min, et
  1) `_engine_record(ok=True)` remettait `fails` a 0 sans refermer `opened_until_ts` ;
  2) `_ensure_searxng` ne transmettait pas sa preuve de vie au disjoncteur.
Toutes les veilles thematiques de la journee ont ainsi tourne sur OpenAlex/arXiv seuls.
"""
import pytest

from nokido_agent.app import forge_watch_agent as W
from nokido_agent.tools import forge_docker_keeper as K


@pytest.fixture(autouse=True)
def cb_vierge(monkeypatch):
    monkeypatch.setattr(W, "_ENGINE_CB", {})
    yield


def _ouvrir(nom="searxng"):
    for _ in range(W._ENGINE_CB_THRESHOLD):
        W._engine_record(nom, ok=False)
    assert W._engine_open(nom)


def test_un_succes_referme_le_circuit():
    _ouvrir()
    W._engine_record("searxng", ok=True)
    assert not W._engine_open("searxng")


def test_succes_sur_un_moteur_ne_touche_pas_les_autres():
    _ouvrir("searxng:google")
    _ouvrir("searxng")
    W._engine_record("searxng", ok=True)
    assert W._engine_open("searxng:google")


class _Rep:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ensure_pret_referme_le_circuit(monkeypatch):
    monkeypatch.setattr(K, "claim_docker", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(K, "release_claim", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(W.urllib.request, "urlopen", lambda *a, **k: _Rep())
    _ouvrir()
    assert W._ensure_searxng(wait_s=1, owner="nr_test") is True
    assert not W._engine_open("searxng"), "preuve de vie applicative recue : le circuit doit se refermer"


def test_ensure_non_pret_laisse_le_circuit(monkeypatch):
    monkeypatch.setattr(K, "claim_docker", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(K, "release_claim", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(K, "ensure_docker", lambda *a, **k: None, raising=False)

    def ko(*a, **k):
        raise OSError("refuse")
    monkeypatch.setattr(W.urllib.request, "urlopen", ko)
    monkeypatch.setattr(W, "_SEARX_LAST_ENSURE_TS", W.time.time())  # pas de reveil reel (superviseur)
    _ouvrir()
    assert W._ensure_searxng(wait_s=1, owner="nr_test") is False
    assert W._engine_open("searxng")
