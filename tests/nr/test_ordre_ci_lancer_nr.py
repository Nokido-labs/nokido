"""NR 6/11 : Route gouvernee de lancement CI (ci-lancer).

Contrats verifiables :
1. Cible mal formee refusee (exige <workflow>.yml@<ref>).
2. Rien n'est lance avant la decision (aucun appel reseau/declencher).
3. Un agent qui appelle decision-oui est refuse (consommateur non admis, pas d'auto-approbation).
4. Non = aucun appel a declencher.
5. Oui = un seul appel, avec le bon workflow et la bonne ref (HTTP 204 -> etat ACCEPTE).
6. Decision a usage unique (un 2e appel sur le meme ordre_id est refuse).
7. Le vrai decideur importe teste directement un refus (oui=False) et un accept (oui=True).
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import MagicMock

from nokido_agent.app import forge_ordres_bureau as ob
from nokido_agent.tools.forge_ci_check import decideur_ci


@pytest.fixture(autouse=True)
def _reset_ordres_bureau():
    with ob._VERROU:
        ob._ORDRES.clear()
        ob._A_DECIDER.clear()
        ob._DECIDEURS.clear()
    yield
    with ob._VERROU:
        ob._ORDRES.clear()
        ob._A_DECIDER.clear()
        ob._DECIDEURS.clear()


def test_cible_mal_formee_refusee():
    """Une cible invalide est rejetee sans depot d'ordre."""
    for mauvaise_cible in ["", "ci.yml", "ci.yml@", "@alpha", "bad cible@ref", "ci.txt@alpha"]:
        res = asyncio.run(ob.demander_ordre("agt_test", "ci-lancer", cible=mauvaise_cible))
        assert res.get("etat") == ob.REFUSE
        assert "ci-lancer exige `cible` de forme <workflow>.yml@<ref>" in res.get("raison", "")


def test_decideur_ci_fonction_extraite_directe():
    """Le vrai decideur importe repond conformement au contrat sur oui=False et oui=True."""
    # Test refus direct
    refus = decideur_ci("ci.yml@alpha", False)
    assert refus == "lancement CI refuse par l'owner"

    # Test acceptation directe avec mock_declencher
    mock_declencher = MagicMock(return_value={"ok": True, "http": 204, "workflow": "ci.yml", "ref": "alpha"})
    res = decideur_ci("ci.yml@alpha", True, declencher_fn=mock_declencher)
    assert isinstance(res, dict)
    assert res.get("etat") == "ACCEPTE"
    assert "HTTP 204" in res.get("detail", "")
    mock_declencher.assert_called_once_with("Nokido-labs/nokido-private", "ci.yml", ref="alpha")


def test_rien_lance_avant_decision():
    """Au depot, l'ordre est place a_valider et aucune execution n'a eu lieu."""
    mock_declencher = MagicMock()
    def _decideur_wrap(cible, oui):
        return decideur_ci(cible, oui, declencher_fn=mock_declencher)
    ob.enregistrer_decideur("ci-lancement", _decideur_wrap)

    res = asyncio.run(ob.demander_ordre("agt_test", "ci-lancer", cible="ci.yml@alpha", raison="test run"))
    assert res.get("etat") == ob.DEPOSE
    assert res.get("a_valider") is True
    ordre_id = res.get("ordre")
    assert ordre_id

    # Aucun appel effectue
    assert mock_declencher.call_count == 0


def test_agent_auto_approbation_refusee():
    """Un agent qui tente de valider decision-oui est refuse (consommateur non admis)."""
    res = asyncio.run(ob.demander_ordre("agt_test", "ci-lancer", cible="ci.yml@alpha"))
    ordre_id = res["ordre"]

    # Le tray prend l'ordre pour qu'il soit dans _A_DECIDER
    pris = ob.prendre("TRAY")
    assert pris.get("etat") == ob.ORDRE

    # L'agent tente decision-oui
    res_agent = asyncio.run(ob.demander_ordre("agt_test", "decision-oui", cible=ordre_id))
    assert res_agent.get("etat") == ob.REFUSE
    assert "ne peut pas decider" in res_agent.get("raison", "")


def test_decision_non_aucun_appel():
    """Si l'owner dit Non au tray, le vrai decideur est appele, refus retourne et aucun appel a declencher."""
    mock_declencher = MagicMock()
    def _decideur_wrap(cible, oui):
        return decideur_ci(cible, oui, declencher_fn=mock_declencher)
    ob.enregistrer_decideur("ci-lancement", _decideur_wrap)

    res = asyncio.run(ob.demander_ordre("agt_test", "ci-lancer", cible="ci.yml@alpha"))
    ordre_id = res["ordre"]

    # Le tray prend l'ordre
    pris = ob.prendre("TRAY")
    assert pris.get("etat") == ob.ORDRE

    # Decision Non du tray
    res_dec = ob.decider("TRAY", ordre_id, False)
    assert res_dec.get("etat") == "DECIDE"
    assert res_dec.get("oui") is False
    assert res_dec.get("retour") == "lancement CI refuse par l'owner"
    assert mock_declencher.call_count == 0


def test_decision_oui_un_seul_appel_et_usage_unique():
    """Oui au tray = un seul appel avec workflow et ref, HTTP 204 -> ACCEPTE, usage unique."""
    mock_declencher = MagicMock(return_value={"ok": True, "http": 204, "workflow": "ci.yml", "ref": "alpha"})
    def _decideur_wrap(cible, oui):
        return decideur_ci(cible, oui, declencher_fn=mock_declencher)
    ob.enregistrer_decideur("ci-lancement", _decideur_wrap)

    res = asyncio.run(ob.demander_ordre("agt_test", "ci-lancer", cible="ci.yml@alpha"))
    ordre_id = res["ordre"]

    # Pris par le tray
    ob.prendre("TRAY")

    # Decision Oui
    res_dec = ob.decider("TRAY", ordre_id, True)
    assert res_dec.get("etat") == "DECIDE"
    assert res_dec.get("oui") is True
    assert res_dec.get("retour", {}).get("etat") == "ACCEPTE"
    mock_declencher.assert_called_once_with("Nokido-labs/nokido-private", "ci.yml", ref="alpha")

    # Re-decision sur le meme ordre_id (usage unique)
    res_dec_2 = ob.decider("TRAY", ordre_id, True)
    assert res_dec_2.get("etat") == ob.REFUSE
    assert "ordre inconnu, deja decide ou sans decision" in res_dec_2.get("raison", "")
    assert mock_declencher.call_count == 1
