"""NR 2/11 — E1 du plan OAuth MCP (docs/PLAN_OAUTH_MCP_HUB_20261102.md) : passerelle d'habilitations du HUB.

Contrat :
  * audience, portee et ressource PROPRES au hub ; la ressource est l'URL du point MCP (RFC 8707 : un indicateur de
    ressource est une URI absolue), reglable pour la version distribuable ;
  * une habilitation du hub est REFUSEE par le pont GitHub et par la passerelle des pairs, et inversement
    (cloisonnement par audience) ;
  * la passerelle declare l'indicateur de ressource STRICT (RFC 8707), que les pairs n'activent pas ;
  * aucun controle recopie : sceau, expiration, revocation viennent de la mecanique commune.
"""
import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]


def _charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / fichier)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def cle(monkeypatch):
    monkeypatch.setenv("NOKIDO_BRIDGE_CAPABILITY_KEY", "cle-de-test-" + "x" * 40)
    monkeypatch.delenv("NOKIDO_HUB_RESSOURCE_MCP", raising=False)


def _charge(m, **sur):
    c = {"sub": "client-test", "aud": m.AUDIENCE, "scope": m.SCOPE, "resource": next(iter(m.DEPOTS_AUTORISES)),
         "exp": int(time.time()) + 600, "jti": "jti-test", "replay": "multi"}
    c.update(sur)
    return c


def test_valeurs_propres_et_ressource_url(cle):
    hub = _charger("pass_hub", "forge_passerelle_hub.py")
    assert hub.AUDIENCE == "nokido-hub" and hub.SCOPE == "mcp:hub"
    assert hub.DEPOTS_AUTORISES == frozenset({"http://127.0.0.1:8766/mcp"})
    assert hub.RESSOURCE_STRICTE is True


def test_ressource_reglable_pour_la_distribution(cle, monkeypatch):
    monkeypatch.setenv("NOKIDO_HUB_RESSOURCE_MCP", "http://localhost:9999/mcp")
    hub = _charger("pass_hub2", "forge_passerelle_hub.py")
    assert hub.DEPOTS_AUTORISES == frozenset({"http://localhost:9999/mcp"})


def test_ressource_non_absolue_refusee(cle, monkeypatch):
    monkeypatch.setenv("NOKIDO_HUB_RESSOURCE_MCP", "nokido:hub")
    with pytest.raises(SystemExit):
        _charger("pass_hub3", "forge_passerelle_hub.py")


def test_habilitation_du_hub_lue_par_le_hub(cle):
    hub = _charger("pass_hub4", "forge_passerelle_hub.py")
    charge, motif = hub._lire_capacite(hub.forger_capacite(_charge(hub)))
    assert motif is None and charge["sub"] == "client-test"


def test_cloisonnement_par_audience(cle):
    hub = _charger("pass_hub5", "forge_passerelle_hub.py")
    pair = _charger("pass_pair5", "forge_passerelle_pair.py")
    j_hub = hub.forger_capacite(_charge(hub))
    j_pair = pair.forger_capacite(_charge(pair))
    assert pair._lire_capacite(j_hub)[0] is None
    assert hub._lire_capacite(j_pair)[0] is None


def test_ressource_etrangere_refusee(cle):
    hub = _charger("pass_hub6", "forge_passerelle_hub.py")
    charge, motif = hub._lire_capacite(hub.forger_capacite(_charge(hub, resource="http://127.0.0.1:9200/mcp")))
    assert charge is None and "ressource" in motif


def test_pairs_ne_passent_pas_en_strict(cle):
    pair = _charger("pass_pair7", "forge_passerelle_pair.py")
    assert getattr(pair, "RESSOURCE_STRICTE", False) is False


def test_aucun_controle_recopie():
    src = (RACINE / "tools" / "forge_passerelle_hub.py").read_text(encoding="utf-8")
    for interdit in ("hmac", "compare_digest", "hashlib", "time.time"):
        assert interdit not in src, interdit
