"""NR -- identite PROUVEE du client de la passerelle (`forge_openai_proxy`).

La passerelle croyait l'en-tete `LaForge-Agent-Name` sur parole. Avec le jeton
maitre, cela donnait a tout appelant de :7777 l'identite ET le ring de son
choix. Le maitre est parti, mais la CREDULITE restait : un appelant anonyme
choisissait encore son nom, simplement borne par le plancher de delegation.

Desormais le client presente son `FORGE_TOKEN_<AGENT>` dans
`Authorization: Bearer` -- la ou une API OpenAI attend une clef -- et la
passerelle le VALIDE. L'en-tete de nom redevient un indice de journalisation.

Chaque test ci-dessous a ete MESURE avant d'etre ecrit : les proprietes
verifiees ne sont pas des intentions, ce sont des constats qu'on empeche de
regresser.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import forge_openai_proxy as pr  # noqa: E402


class _H(dict):
    """Mime l'objet headers de Starlette (get insensible a la casse cote appel)."""

    def get(self, k, d=None):
        return dict.get(self, k, d)


@pytest.fixture(autouse=True)
def _cache_neuf():
    pr._CACHE_CLES.update({"ts": 0.0, "par_jeton": {}})
    yield
    pr._CACHE_CLES.update({"ts": 0.0, "par_jeton": {}})


@pytest.fixture
def table(monkeypatch):
    """Table controlee : le test ne depend pas du coffre reel."""
    monkeypatch.setattr(pr, "_table_clients", lambda: {"jeton-de-claude": "CLAUDE"})


# --------------------------------------------------------------------------- #
# La regle centrale : un NOM ne vaut rien sans PREUVE
# --------------------------------------------------------------------------- #

def test_jeton_reconnu_donne_l_identite(table):
    nom, prouve = pr._identite_client(_H({"Authorization": "Bearer jeton-de-claude"}))
    assert (nom, prouve) == ("CLAUDE", True)


def test_nom_declare_sans_jeton_ne_vaut_rien(table):
    """LE test de cette phase : c'est ce chemin qui donnait le hub entier."""
    nom, prouve = pr._identite_client(_H({"LaForge-Agent-Name": "LAFORGE"}))
    assert (nom, prouve) == ("OPENAI_PROXY", False)


def test_nom_declare_avec_jeton_inconnu_ne_vaut_rien(table):
    nom, prouve = pr._identite_client(_H({
        "LaForge-Agent-Name": "LAFORGE", "Authorization": "Bearer sk-invente"}))
    assert (nom, prouve) == ("OPENAI_PROXY", False)


def test_aucun_en_tete_donne_la_passerelle(table):
    assert pr._identite_client(_H({})) == ("OPENAI_PROXY", False)


@pytest.mark.parametrize("entete", ["LaForge-Agent-Name", "Agent-Name", "X-Agent-Name"])
def test_aucune_variante_d_en_tete_n_est_une_preuve(table, entete):
    """Les trois noms d'en-tete existent pour la transition ; AUCUN n'authentifie."""
    assert pr._identite_client(_H({entete: "CLAUDE"})) == ("OPENAI_PROXY", False)


# --------------------------------------------------------------------------- #
# Fail-closed : ne pas pouvoir verifier n'autorise pas
# --------------------------------------------------------------------------- #

def test_coffre_indisponible_n_accorde_aucune_identite(monkeypatch):
    """Mesure : coffre muet -> table vide -> identite refusee. « Je n'ai pas pu
    verifier » ne doit jamais valoir « c'est bon »."""
    monkeypatch.setattr(pr, "_table_clients", dict)
    assert pr._identite_client(
        _H({"Authorization": "Bearer jeton-de-claude"})) == ("OPENAI_PROXY", False)


def test_table_vide_sur_erreur_de_lecture(monkeypatch):
    def _casse():
        raise OSError("coffre illisible")

    monkeypatch.setattr(pr, "_table_clients", _casse)
    with pytest.raises(OSError):
        pr._identite_client(_H({"Authorization": "Bearer x"}))


# --------------------------------------------------------------------------- #
# Comparaison en temps constant
# --------------------------------------------------------------------------- #

def test_la_comparaison_est_en_temps_constant():
    src = inspect.getsource(pr._identite_client)
    assert "compare_digest" in src, (
        "un `dict.get` sort des l'octet qui differe : le temps de reponse "
        "trahit alors le prefixe correct")


def test_pas_de_sortie_anticipee_dans_la_boucle():
    """Sortir au premier succes reintroduirait la fuite qu'on vient de fermer :
    le temps depend alors de la POSITION du jeton dans la table."""
    src = inspect.getsource(pr._identite_client)
    boucle = src.split("for _tok, _nom in")[1].split("if trouve")[0]
    assert "break" not in boucle
    assert "return" not in boucle


# --------------------------------------------------------------------------- #
# Revocation : le TTL du cache EST le delai de revocation
# --------------------------------------------------------------------------- #

def test_le_ttl_de_cache_reste_court():
    """Pendant ce delai, un credential retire du coffre ouvre encore son
    identite. 60 s etait un choix de confort ; le cout d'une lecture de coffre
    est sans commune mesure avec une identite revoquee qui survit une minute."""
    assert pr._TTL_CLES <= 15, pr._TTL_CLES


def test_le_ttl_est_reglable_sans_toucher_au_code():
    src = inspect.getsource(pr).split("_TTL_CLES =")[1][:120]
    assert "environ" in src, "le delai de revocation doit etre reglable a chaud"


# --------------------------------------------------------------------------- #
# Le nom n'est plus relaye tel quel
# --------------------------------------------------------------------------- #

def test_le_handler_utilise_l_identite_prouvee():
    """Garde de CABLAGE : la fonction peut etre parfaite et n'etre appelee par
    personne -- c'est le defaut le plus courant du corps."""
    src = (ROOT / "tools" / "forge_openai_proxy.py").read_text(
        encoding="utf-8", errors="replace")
    i = src.find("_CLIENT_AGENT.set(")
    assert i > 0
    zone = src[max(0, i - 400):i + 200]
    assert "_identite_client(" in zone, (
        "le handler pose encore l'identite sans passer par la validation")


def test_l_en_tete_de_nom_n_alimente_plus_directement_l_identite():
    src = (ROOT / "tools" / "forge_openai_proxy.py").read_text(
        encoding="utf-8", errors="replace")
    # Viser l'ARGUMENT de `.set(` uniquement : l'en-tete est encore lu juste
    # apres, pour JOURNALISER une transition -- usage legitime qu'une fenetre
    # trop large confondait avec la faute.
    i = src.find("_CLIENT_AGENT.set(")
    argument = src[i + len("_CLIENT_AGENT.set("):].split(")")[0]
    assert "Agent-Name" not in argument, (
        "l'en-tete de nom alimente de nouveau l'identite sans preuve : %r"
        % argument[:80])
    assert "_nom" in argument, "l'identite ne vient plus de la validation"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
