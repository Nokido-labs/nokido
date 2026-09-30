"""Non-regression -- la sonde des tuiles ne range JAMAIS le NON MESURE du cote sain.

CONTRAT, trois etats et jamais deux (meme contrat que `test_ci_gate_trois_etats_nr`,
applique ici a la vitalite des tuiles du portail) :

    MESURE joignable      -> live / degraded         (checked=True)
    MESURE injoignable    -> offline / error         (checked=True)
    PAS MESURE            -> UNKNOWN                 (checked=False)

Pourquoi ce garde, mesure du 2026-09-17 sur `SERVICES` (18 tuiles) :

    avec healthcheck (APPLICATION_UP possible) :  2 / 18
    sur loopback     (reellement mesurees)     :  6 / 18
    NON mesurees -> repliees sur "live"        : 12 / 18   <-- le defaut

Deux tiers des tuiles annoncent `live` sans qu'aucune sonde n'ait eu lieu. Ce n'est
pas « trop binaire » : c'est ranger l'ILLISIBLE du cote SAIN, ce que la constitution
semantique interdit (« un agregat ne range JAMAIS UNKNOWN du cote sain ; on classe
par liste BLANCHE »). Le defaut symetrique -- un organe endormi lu « offline » -- est
couvert ailleurs (`test_tuile_reveil_ondemand_nr`, cote reveil). Ici on couvre la
SONDE, et seulement elle.

Le garde porte sur la PROPRIETE, pas sur la ligne : toute forme de cible non
mesurable (absente, non locale, malformee, route interne) doit rendre le meme
verdict. Sinon le defaut revient par une cible d'une autre forme.
"""
from __future__ import annotations

import importlib.util
import os
import socket

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SRC = os.path.join(ROOT, "app", "web_hub", "dashboard_html.py")


def _mod():
    """Charge le module PAR SON FICHIER : importer `app.web_hub` tirerait le
    portail entier (fastapi, routes), ce qui ferait de ce NR un test d'integration."""
    spec = importlib.util.spec_from_file_location("_dashboard_html_nr", _SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# Cibles qu'aucune sonde ne peut atteindre : la mesure n'a PAS eu lieu.
NON_MESURABLES = [
    pytest.param({}, id="target-absent"),
    pytest.param({"target": ""}, id="target-vide"),
    pytest.param({"target": "/vitals"}, id="route-interne"),
    pytest.param({"target": "https://example.invalid/x"}, id="cible-non-locale"),
    pytest.param({"target": "127.0.0.1:"}, id="port-manquant"),
    pytest.param({"target": "127.0.0.1:abc"}, id="port-non-numerique"),
    pytest.param({"target": "internal"}, id="cible-symbolique"),
]


@pytest.mark.parametrize("cfg", NON_MESURABLES)
def test_une_cible_non_mesurable_ne_vaut_JAMAIS_live(cfg):
    """LE test. Une absence de mesure n'est pas une preuve de disponibilite."""
    r = _mod().probe_service(dict(cfg))
    assert r.get("checked") is False, (
        "cette cible ne peut pas etre sondee, `checked` doit le DIRE : %r" % r)
    assert r.get("state") != "live", (
        "NON MESURE annonce comme `live` -- l'illisible est range du cote sain : %r" % r)


@pytest.mark.parametrize("cfg", NON_MESURABLES)
def test_une_cible_non_mesurable_rend_UNKNOWN(cfg):
    """UNKNOWN est un etat A PART ENTIERE, pas un synonyme d'autre chose."""
    r = _mod().probe_service(dict(cfg))
    assert r.get("state") == "unknown", (
        "trois etats et jamais deux : le non-mesure doit rendre `unknown`, pas %r" % r)


@pytest.mark.parametrize("cfg", NON_MESURABLES)
def test_UNKNOWN_n_est_pas_offline(cfg):
    """Symetrie : ne pas remplacer un faux calme par une fausse panne. Une tuile
    non mesuree ne doit pas devenir un lien mort (cf. `dashboard_html` L70-71, qui
    derive « lien mort » de `state in ("offline", "error")`)."""
    r = _mod().probe_service(dict(cfg))
    assert r.get("state") not in ("offline", "error"), (
        "non mesure transforme en panne -- 24 pouls sans pid donnaient INCERTAIN, "
        "jamais NON : %r" % r)


def test_un_etat_non_mesure_n_est_jamais_un_lien_mort():
    """Le consommateur reel, pas seulement la valeur rendue."""
    m = _mod()
    mort = getattr(m, "est_lien_mort", None) or getattr(m, "_est_lien_mort", None)
    if mort is None:
        pytest.skip("pas de derivation `lien mort` exposee dans ce module")
    assert mort({"target": "/vitals"}) is False


def test_contre_epreuve_une_cible_mesurable_est_bien_MESUREE(monkeypatch):
    """Sans cette contre-epreuve, rendre `unknown` partout ferait passer le garde
    pour une raison qui n'a rien a voir avec ce qu'il protege."""
    m = _mod()

    class _S:
        def close(self):
            return None

    monkeypatch.setattr(m.socket, "create_connection", lambda *a, **k: _S())
    r = m.probe_service({"target": "http://127.0.0.1:7474"})
    assert r.get("checked") is True, "une cible locale DOIT etre sondee : %r" % r
    assert r.get("state") == "live"
    assert r.get("via") == "tcp"


def test_contre_epreuve_une_cible_injoignable_reste_offline(monkeypatch):
    """`offline` garde son sens : il dit qu'on a ESSAYE et echoue."""
    m = _mod()

    def _refus(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(m.socket, "create_connection", _refus)
    r = m.probe_service({"target": "http://127.0.0.1:7474"})
    assert r.get("checked") is True
    assert r.get("state") == "offline", (
        "un refus MESURE est un offline, pas un unknown : %r" % r)


def test_le_vocabulaire_des_etats_est_declare():
    """Un etat qui n'existe nulle part en constante se re-invente a chaque site.
    Le depot porte deja ce contrat pour les gates CI (`test_ci_gate_trois_etats_nr`)."""
    m = _mod()
    etats = getattr(m, "ETATS_SONDE", None)
    if etats is None:
        pytest.skip("vocabulaire non encore extrait en constante")
    assert "unknown" in etats


def test_socket_reste_le_seul_chemin_TCP():
    """Garde de portee : si la sonde changeait de transport, les contre-epreuves
    ci-dessus cesseraient de mesurer quoi que ce soit sans que rien ne rougisse."""
    assert hasattr(_mod(), "socket") and _mod().socket is socket
