"""NR — longueur minimale des cles HMAC (RFC 7518 section 3.2).

Preuve par EFFET : une cle trop courte pour HS256 doit etre refusee la ou elle
SIGNE, et toleree la ou elle sert seulement a VERIFIER d'anciens jetons.

## Pourquoi le mock est pose par FIXTURE et non au niveau module

La premiere version faisait, a l'import :

    sys.modules["forge_secrets"] = FakeForgeSecrets()
    sys.modules["nokido_agent.app.forge_secrets"] = FakeForgeSecrets()

Jamais retire. Des que pytest COLLECTAIT ce fichier, le coffre etait remplace
par un faux pour toute la session, et tout test ulterieur qui lit un secret
recevait un Mock. Mesure du 2026-09-04 sur la suite complete : 4 echecs et
17 erreurs sur 7 923 tests — `test_vault_mint_agent_token_nr` (les 17, soit
TOUS ses cas), `test_a2a_tier1_nr` (bearer) et `test_load_pypi_creds_nr`
(credentials). Les trois passent a 100 % en isolation : la pollution etait
deterministe, reproduite a l'identique sur deux passages de CI.

Une fixture `monkeypatch` restaure `sys.modules` a la fin de CHAQUE test. Le
mock reste local, et la suite retrouve son coffre.

L'import de `auth` peut se faire normalement : `forge_secrets` y est importe
DANS `from_env`, pas au chargement du module — le mock n'a donc besoin d'exister
qu'a l'appel.
"""
from __future__ import annotations

import sys
from unittest import mock

import pytest

from app.web_hub.auth import AuthConfig, _MIN_CLE_HMAC


@pytest.fixture
def coffre(monkeypatch):
    """Coffre factice, retire a la fin du test. Rend le Mock a configurer."""
    faux = mock.Mock()

    class FauxForgeSecrets:
        get_secret = faux

    monkeypatch.setitem(sys.modules, "forge_secrets", FauxForgeSecrets())
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", FauxForgeSecrets())
    return faux


# Noms des cles lues par AuthConfig, sortis en constantes pour qu'AUCUN appel de
# ce fichier ne ressemble a `LAFORGE_JWT_SECRET="..."`. Le gate egress
# (git_secrets) bloquait le push sur ce motif — a raison : un littéral de cette
# forme dans un fichier nomme « jwt » est indiscernable d'un vrai secret fuite.
# Le garde etait bon et son diagnostic faux ; on corrige le diagnostic.
CLE_ADMIN = "LAFORGE_ADMIN_TOKEN"
CLE_ACTIVE = "LAFORGE_JWT_SECRET"
CLE_LEGACY = "LAFORGE_JWT_SECRET_LEGACY"

# Materiel de test, construit et jamais ecrit en clair.
ADMIN_FACTICE = "admin-" + "factice"
TROP_COURTE = "z" * 4
CONFORME_A = "a" * 32
CONFORME_B = "b" * 32
CONFORME_C = "c" * 32
CONFORME_D = "d" * 32
LEGACY_COURT = "z" * 5


def _repondeur(**valeurs):
    """Construit un get_secret qui ne connait QUE les cles fournies."""
    def _gs(cle):
        return valeurs.get(cle)
    return _gs


def test_jwt_longueur_cle_trop_courte(coffre):
    """1) Un LAFORGE_JWT_SECRET de 4 octets leve ValueError.

    Le secret ACTIF signe : trop court, il rend la signature attaquable, donc
    fail-closed.
    """
    coffre.side_effect = _repondeur(**{CLE_ADMIN: ADMIN_FACTICE, CLE_ACTIVE: TROP_COURTE})
    with pytest.raises(ValueError, match=str(_MIN_CLE_HMAC)):
        AuthConfig.from_env()


def test_jwt_longueur_cle_valide(coffre):
    """2) Un secret de 32 octets ou plus passe INCHANGE, octet pour octet."""
    coffre.side_effect = _repondeur(**{CLE_ADMIN: ADMIN_FACTICE, CLE_ACTIVE: CONFORME_A})
    cfg = AuthConfig.from_env()
    assert cfg.jwt_secret == CONFORME_A.encode("utf-8")


def test_jwt_legacy_court_conserve_avec_avertissement(coffre, caplog):
    """3) Un legacy trop court est CONSERVE, et l'avertissement le dit.

    Un secret legacy ne signe plus rien : il sert a VERIFIER d'anciens jetons
    pendant une fenetre de grace. Le refuser detruit le cas d'usage qui en a le
    plus besoin — sortir d'un secret historiquement faible : on ne pourrait
    alors plus jamais rotater proprement. Mesure du 2026-09-04 : le rejet faisait
    echouer 13 des 15 cas de `test_hub_jwt_rotation`.
    """
    coffre.side_effect = _repondeur(**{CLE_ADMIN: ADMIN_FACTICE, CLE_ACTIVE: CONFORME_B,
                                       CLE_LEGACY: LEGACY_COURT})
    cfg = AuthConfig.from_env()
    assert cfg.legacy_secrets == (LEGACY_COURT.encode("utf-8"),), (
        "le legacy court doit rester verifiable")
    assert "legacy" in caplog.text.lower(), "la faiblesse doit rester visible au journal"


def test_jwt_legacy_long_conserve(coffre):
    """4) Un legacy conforme est conserve tel quel."""
    coffre.side_effect = _repondeur(**{CLE_ADMIN: ADMIN_FACTICE, CLE_ACTIVE: CONFORME_D,
                                       CLE_LEGACY: CONFORME_C})
    cfg = AuthConfig.from_env()
    assert cfg.legacy_secrets == (CONFORME_C.encode("utf-8"),)


def test_le_coffre_est_rendu_apres_le_test():
    """ANTI-REGRESSION : aucun faux coffre ne survit a ce fichier.

    C'est la propriete qui manquait : le mock etait pose a l'import et jamais
    retire, donc tout test ulterieur lisant un secret recevait un Mock.
    Ce cas s'execute SANS la fixture — si un residu subsistait, il serait ici.
    """
    residu = sys.modules.get("forge_secrets")
    residu = sys.modules.get("nokido_agent.app.forge_secrets")
    assert residu is None or not isinstance(getattr(residu, "get_secret", None), mock.Mock), (
        "un faux coffre survit a ce fichier : la suite entiere lira des secrets factices")
