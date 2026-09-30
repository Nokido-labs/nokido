# -*- coding: utf-8 -*-
"""NR A2 — `/api/recon/run` doit CONSOMMER la portee du CapabilityToken.

    DENY  -> 403 ET forge_swarm_bus.publish == 0
    ALLOW -> la route passe ET publish > 0

    UN 403 NE PROUVE PAS L'ABSENCE D'EFFET. C'est le compteur qui la prouve.

POURQUOI CE FICHIER EXISTE
    La chaine d'emission a portee reduite est construite et certifiee (A1) :
    `login_agent(scopes_demandes=...)` -> `attenuer_ou_refuser` ->
    CapabilityToken signe, `sub`/`ring`/`seq`/`iss`/`cnf` conserves. Mais
    `/api/recon/run` ne la consomme pas : elle teste l'appartenance du bearer a
    un ENSEMBLE DE CHAINES STATIQUES.

        EXISTS != CALLED — `has_scope`/`_scope_allows` avaient DEUX occurrences
        dans tout le corps : leur definition et leur propre appel interne.

    Consultation prealable : aucun NR n'eprouve l'autorisation par scope d'une
    route en comptant ses effets. Rien a reutiliser, tout est neuf ici.

QUEL SCOPE, ET POURQUOI CELUI-LA
    Aucun scope `recon` n'existe : les rings accordent `fs`, `rag`, `sql`,
    `tasks`, `system`, `master`. Plutot que d'en inventer un -- ce qui serait
    une modification de produit hors du strict necessaire -- on exige celui qui
    correspond a l'EFFET REEL : `recon.run` lance `research_agent`, dont le
    travail est d'INGERER dans le RAG. D'ou `rag:ingest`.

    Un jeton atténué a `rag:query` est alors legitime, authentifie, non revoque
    -- et INSUFFISANT pour cette capacite. C'est exactement le cas negatif
    voulu : le refus vient de la PORTEE, pas de l'identite.

DEUX PIEGES QUE CE HARNAIS EVITE, ET C'EST LEUR RAISON D'ETRE
 1. `TestClient` s'annonce `client.host == "testclient"`, donc HORS loopback.
    L'ancienne garde rendrait 401 et le cas negatif passerait POUR LA MAUVAISE
    RAISON -- un vert qui ne mesure pas le scope. On force le client en
    loopback : l'ancienne garde laisse alors passer, et SEULE la portee decide.
 2. Le cas POSITIF irait jusqu'a `_tool_call("research_agent")` : SearXNG, LLM,
    ingest RAG. On substitue `_tool_call` (module-level, donc vu par la cloture
    `recon_run`) : la decision est mesuree, l'effet de production ne part pas.

AUCUN CREDENTIAL DE PRODUCTION. Le jeton est emis par `login_agent` avec un
secret fabrique dans ce fichier -- cryptographiquement valide, sans valeur.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (_RACINE, _RACINE / "app", _RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# CONSTRUIT, jamais ecrit en dur : un litteral de cette forme est ce que le
# gate d'egress traque, et il a bloque tout push du depot 24 h durant.
_JETON_INVENTE = "q" * 40


@pytest.fixture(scope="module")
def hub():
    import nokido_hub as _h  # noqa: PLC0415 — livrable, jamais d'importorskip
    return _h


@pytest.fixture(scope="module")
def app(hub):
    """Mesure du 2026-09-22 : `_build_app()` monte 91 routes en 0,1 s, sans
    effet de demarrage -- elle ne fait que definir, assembler et rendre."""
    return asyncio.run(hub._build_app())


@pytest.fixture()
def compteurs(hub, monkeypatch):
    """Compte les EFFETS. Le cas ALLOW prouve que ces compteurs savent bouger :
    sans lui, les zeros du cas DENY seraient vrais par impuissance de la sonde.
    """
    etat = {"publish": 0, "tool_call": 0}
    bus = importlib.import_module("nokido_agent.app.forge_swarm_bus")

    def _publish(*a, **k):
        etat["publish"] += 1

    async def _tool_call(*a, **k):
        etat["tool_call"] += 1
        return "{}"

    # `recon_run` fait son `from ...forge_swarm_bus import publish` DANS son
    # corps : l'import se refait a chaque appel, donc la substitution est vue.
    monkeypatch.setattr(bus, "publish", _publish)
    monkeypatch.setattr(hub, "_tool_call", _tool_call)
    return etat


def _jeton(scopes):
    import forge_auth_tokens as ja  # noqa: PLC0415
    return ja.login_agent("CLAUDE", secret_id=_JETON_INVENTE,
                          agent_tokens={"CLAUDE": _JETON_INVENTE},
                          scopes_demandes=scopes)


def _appeler(app, jeton):
    from starlette.testclient import TestClient  # noqa: PLC0415
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        return c.post("/api/recon/run",
                      headers={"Authorization": "Bearer " + jeton},
                      json={"objective": "sonde NR, aucun effet attendu"})


# ── NEGATIF : le refus doit EMPECHER l'effet, pas seulement le signaler ──

def test_scope_INSUFFISANT_refuse_ET_n_atteint_aucun_effet(app, compteurs):
    r = _appeler(app, _jeton({"rag": ["query"]}))
    assert r.status_code == 403, (
        "un porteur authentifie SANS `rag:ingest` a ete accepte (status %d) : "
        "la route ne consomme pas la portee" % r.status_code)
    assert compteurs["publish"] == 0, (
        "REFUSE mais %d publication(s) sur le bus : le refus ne protege pas "
        "l'effet, il le commente" % compteurs["publish"])
    assert compteurs["tool_call"] == 0, (
        "REFUSE mais `research_agent` appele %d fois" % compteurs["tool_call"])


# ── POSITIF : et la contre-epreuve que les compteurs savent bouger ──────

def test_scope_EXACT_passe_ET_produit_l_effet(app, compteurs):
    r = _appeler(app, _jeton({"rag": ["ingest"]}))
    assert r.status_code != 403, (
        "un porteur avec `rag:ingest` a ete REFUSE (status %d) : le "
        "durcissement coupe le trajet legitime" % r.status_code)
    assert compteurs["publish"] > 0, (
        "ALLOW mais AUCUNE publication : les compteurs ne mesurent rien, et "
        "les zeros du cas negatif seraient vrais par impuissance de la sonde")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
