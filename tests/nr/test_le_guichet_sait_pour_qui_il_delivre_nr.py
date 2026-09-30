"""NR — le guichet doit savoir POUR QUI il delivre, sinon aucune politique n'est possible.

PHASE 6 du mandat « organe de secretion securisee » :
« Mesurer separement : DEMANDE -> AUTORISATION -> DELIVRANCE -> CONSOMMATION. »

SEARCH BEFORE BUILD, fait avant d'ecrire
========================================
La politique d'autorisation EXISTE deja, en plusieurs briques eprouvees :

    forge_mcp_rbac        outil MCP -> ring minimal
    forge_authz_shadow    distingue un jeton A BAIL d'un jeton inconnu
    forge_separation      TRANSPORTE le ring au lieu de le recalculer
    forge_integrity       CapabilityToken, rings, scopes, revoke
    forge_agent_credential jeton COURT plutot que secret permanent

Il ne manque donc PAS un moteur de politique -- il manque son RACCORD a la
delivrance d'un secret. Creer un « broker » de plus ici serait ajouter une
abstraction qui ne ferme aucune transition, c'est-a-dire une dette.

LE TROU MESURE
==============
`get_secret(key, required=False)` ne prend NI identite, NI organe, NI contexte.
Il rend la valeur a quiconque l'appelle dans le process. Consequence directe :
on ne peut pas evaluer une politique, parce qu'on ne sait meme pas QUI demande.
DEMANDE et DELIVRANCE sont confondues.

CE MAILLON NE POSE PAS DE POLITIQUE. Il rend la DEMANDE attribuable, ce qui en
est le prealable strict : une politique branchee sur un demandeur inconnu ne
deciderait rien.

POURQUOI L'ATTRIBUTION EST DEDUITE, ET NON DEMANDEE
===================================================
`get_secret` a 159 appelants. Ajouter un parametre obligatoire les casserait
tous, et un parametre optionnel serait omis partout -- donc jamais mesure.
L'appelant est donc LU dans la pile, puis croise avec la carte d'organes deja
tenue par le corps (`organ_map_full.json`, 1755 modules classes, phase 3).

INVARIANT : un module hors carte rend organe INCONNU. Jamais un organe invente,
jamais un defaut « autorise ». On ne transforme pas une ignorance en permission.
"""
import importlib

import pytest

MOD = "nokido_agent.app.forge_secrets"
CLE = "NOKIDO_NR_CLE_ATTRIBUTION"
VALEUR = "sentinelle-attribution-ne-doit-pas-sortir"


@pytest.fixture()
def secrets(monkeypatch):
    mod = importlib.import_module(MOD)
    mod.invalidate_cache()
    if hasattr(mod, "_vider_observations"):
        mod._vider_observations()
    monkeypatch.setattr(mod, "_machine_vault", lambda k: VALEUR)
    monkeypatch.setattr(mod, "_wcm", lambda k: None)
    monkeypatch.setattr(mod, "_dotenv", lambda k: None)
    yield mod
    mod.invalidate_cache()
    if hasattr(mod, "_vider_observations"):
        mod._vider_observations()


def test_la_demande_est_attribuee_a_un_demandeur(secrets):
    secrets.get_secret(CLE)
    obs = secrets.observees()[CLE]
    assert "demandeurs" in obs, (
        "sans demandeur, DEMANDE et DELIVRANCE sont confondues et aucune "
        "politique ne peut etre evaluee"
    )
    assert obs["demandeurs"], "au moins un demandeur doit etre enregistre"


def test_le_demandeur_nomme_le_module_appelant(secrets):
    """L'attribution est LUE dans la pile : ce fichier de test doit apparaitre."""
    secrets.get_secret(CLE)
    obs = secrets.observees()[CLE]
    modules = " ".join(obs["demandeurs"].keys())
    assert "test_le_guichet_sait_pour_qui_il_delivre_nr" in modules, (
        "le demandeur mesure est %r" % modules
    )


def test_le_guichet_ne_s_attribue_jamais_a_lui_meme(secrets):
    """`forge_secrets` s'appelle en interne : il doit remonter jusqu'au premier
    frame HORS de lui, sinon tous les appels seraient attribues au guichet --
    un instrument qui se lit lui-meme."""
    secrets.get_secret(CLE)
    modules = " ".join(secrets.observees()[CLE]["demandeurs"].keys())
    assert "forge_secrets" not in modules


def test_les_demandes_sont_COMPTEES_par_demandeur(secrets):
    """Un DEBIT se mesure par comptage. Savoir QUI demande sans savoir COMBIEN
    ne permet pas de distinguer un usage normal d'une rafale."""
    for _ in range(3):
        secrets.get_secret(CLE)
    total = sum(secrets.observees()[CLE]["demandeurs"].values())
    assert total == 3


def test_l_organe_est_resolu_ou_declare_INCONNU(secrets):
    """On ne transforme jamais une ignorance en permission."""
    secrets.get_secret(CLE)
    obs = secrets.observees()[CLE]
    assert "organes_demandeurs" in obs
    for organe in obs["organes_demandeurs"]:
        assert organe, "un organe vide serait ambigu ; il doit valoir INCONNU"
    # Ce fichier de test n'est pas dans la carte d'organes du depot.
    assert "INCONNU" in obs["organes_demandeurs"], (
        "un module hors carte doit rendre INCONNU, jamais un organe invente"
    )


def test_une_carte_illisible_ne_fabrique_pas_d_organe(secrets, monkeypatch):
    """Meme invariant qu'en phase 3 : une panne d'instrument ne cree pas de
    fait. Si la carte ne peut pas etre lue, TOUT est INCONNU."""
    monkeypatch.setattr(secrets, "_CARTE_ORGANES_DEMANDEURS", None, raising=False)
    if hasattr(secrets, "_vider_carte_organes"):
        secrets._vider_carte_organes()
    monkeypatch.setattr(secrets, "_charger_carte_organes", lambda: {})
    secrets.get_secret(CLE)
    obs = secrets.observees()[CLE]
    assert set(obs["organes_demandeurs"]) == {"INCONNU"}


def test_l_attribution_ne_fuit_aucune_valeur(secrets):
    import json

    secrets.get_secret(CLE)
    assert VALEUR not in json.dumps(secrets.observees(), default=str)


def test_la_signature_reste_compatible_avec_les_159_appelants(secrets):
    """Le maillon ne doit casser aucun appelant : `get_secret(cle)` et
    `get_secret(cle, required=...)` doivent continuer de fonctionner tels
    quels."""
    import inspect

    sig = inspect.signature(secrets.get_secret)
    params = list(sig.parameters.values())
    assert params[0].name == "key"
    for p in params[1:]:
        assert p.default is not inspect.Parameter.empty, (
            "%s est obligatoire : les 159 appelants existants casseraient" % p.name
        )
    assert secrets.get_secret(CLE) == VALEUR
    assert secrets.get_secret(CLE, required=True) == VALEUR
