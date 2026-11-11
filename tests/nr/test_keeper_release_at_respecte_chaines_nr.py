"""NR 2/11 -- l'arret DIFFERE du keeper respecte les chaines actives, comme la relache de secours.

Mesure du 2/11 soir (NokidoDockerKeeper.log) : Docker demarre 19:29, coupe 19:34, relance 19:35, coupe 19:41, pendant
que 5 veilles tournaient. `_tick_release_at` coupait des que `docker.claims.json` etait vide -- or une veille ne pose
sa reclamation qu'a l'etape de RECHERCHE : la premiere veille finie rendait la sienne, les autres (encore aux
mots-cles) n'avaient rien reclame -> arret 90 s plus tard sous leurs pieds (SearXNG absent, crawl4ai 10061, Rau non
ingere). `_maybe_release` lisait deja `get_active_intents()` ; `_tick_release_at` non.
"""
import json
import time

import pytest

from nokido_agent.tools import forge_docker_keeper as K
from nokido_agent.app import forge_resource_manager as RM


@pytest.fixture
def cadre(tmp_path, monkeypatch):
    p = tmp_path / "docker.release_at"
    p.write_text(json.dumps({"debut": time.time() - 500, "echeance": time.time() - 10, "delai": 90}),
                 encoding="utf-8")
    monkeypatch.setattr(K, "_release_at_path", lambda: p)
    monkeypatch.setattr(K, "_lire_claims", lambda: [])
    monkeypatch.setattr(K, "palier_courant", lambda: "NORMAL")
    monkeypatch.setattr(K, "intentions_docker_en_attente", lambda: 0)
    monkeypatch.setattr(K, "_audit", lambda *a, **k: None)
    arrets = []
    monkeypatch.setattr(K, "_arreter_apres_grace", lambda motif: arrets.append(motif) or {"arrete": True})
    return p, arrets


def test_chaine_active_interdit_l_arret_differe(cadre, monkeypatch):
    p, arrets = cadre
    monkeypatch.setattr(RM, "get_active_intents", lambda: {"chains_active": 3})
    assert K._tick_release_at(time.time()) is None
    assert arrets == [], "Docker coupe alors que des veilles demarrees vont chercher"


def test_sans_chaine_l_arret_differe_a_lieu(cadre, monkeypatch):
    p, arrets = cadre
    monkeypatch.setattr(RM, "get_active_intents", lambda: {"chains_active": 0})
    K._tick_release_at(time.time())
    assert len(arrets) == 1


def test_intentions_illisibles_fail_closed(cadre, monkeypatch):
    p, arrets = cadre

    def ko():
        raise OSError("base verrouillee")
    monkeypatch.setattr(RM, "get_active_intents", ko)
    assert K._tick_release_at(time.time()) is None
    assert arrets == [], "sans lecture d'intention, on ne coupe pas (meme regle que _maybe_release)"
