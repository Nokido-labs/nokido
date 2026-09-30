"""NR — la nature d'une cle doit COMMANDER son masquage, pas seulement l'etiqueter.

PHASE 4 du mandat « organe de secretion securisee » :
« Le classement est fait. Maintenant verifier qu'il produit reellement un
comportement different. »

MESURE ROUGE QUI MOTIVE CE MAILLON (2026-09-21, 1890 fichiers lus, 0 illisible)
==============================================================================
    SECRET_EXTERNE        2 site(s), dont 0 HORS des modules qui le definissent
    CREDENTIAL_INTERNE    2 site(s), dont 0 HORS
    proprietaires(        3 site(s), dont 0 HORS

Le classement des phases 2 et 3 est EXPOSE et ne COMMANDE rien. C'est une
etiquette, pas une politique -- et une abstraction qui ne ferme aucune
transition est une dette, pas une victoire.

Et la fuite est mesuree, pas supposee :

    tools/forge_secret_audit.py:49
        return f"len={len(val)}" if verdict == "OK" else f"{val[:4]}... len={len(val)}"
    tools/forge_secret_audit.py:126
        print(f"  [{verdict:13}] {n}  ({_mask(v, verdict)})")

Quatre caracteres REELS du secret, sur stdout, donc dans tout journal qui le
capture. Meme faute que `val[-4:]` corrigee dans le CLI de `forge_secrets` le
2026-09-20 : la corriger a un endroit ne l'avait pas corrigee a l'autre --
« un garde ne vaut que par le nombre de portes qu'il tient ».

CE QUE CE NR VERROUILLE
=======================
1. UNE SEULE politique de masquage, appelee par les afficheurs. Deux politiques
   divergeraient, et c'est toujours celle qu'on oublie qui fuit.
2. Un SECRET et un CREDENTIAL ne sortent JAMAIS en fragment -- ni prefixe, ni
   suffixe, ni « les 4 premiers ». Une empreinte publique permet de comparer
   deux instances sans rien reveler ; un fragment ne le permet pas et revele.
3. Un CONFIG reste LISIBLE. Le masquer serait le rendre « secret par simple
   convention » -- ce que le mandat interdit explicitement -- et ferait perdre
   la lisibilite d'un parametre de comportement.
4. FAIL-CLOSED sur INDETERMINE : le doute PROTEGE. Une cle qu'on ne sait pas
   classer se masque comme un secret. Le cout des deux erreurs n'est pas
   symetrique -- masquer un reglage gene une lecture, afficher un secret le
   publie.
"""
import re

import pytest

MOD = "nokido_agent.tools.forge_secret_source_audit"

# Chaine de test, injectee par le test. Elle sert a prouver qu'elle NE SORT PAS.
VALEUR = "valeur-de-test-jamais-affichee-0123456789abcdef"


@pytest.fixture()
def audit():
    import importlib

    return importlib.import_module(MOD)


def test_la_politique_de_masquage_est_exposee(audit):
    assert hasattr(audit, "masquer"), (
        "le masquage doit vivre LA OU vit `nature()`, en une seule politique "
        "appelable par tous les afficheurs"
    )


@pytest.mark.parametrize("cle", ["OPENAI_API_KEY", "GEMINI_API_KEY",
                                 "FORGE_TOKEN_CLAUDE", "LAFORGE_ADMIN_TOKEN"])
def test_un_secret_ou_un_credential_ne_sort_jamais_en_fragment(audit, cle):
    rendu = audit.masquer(cle, VALEUR)
    assert VALEUR not in rendu
    # Aucun fragment : ni les 4 premiers, ni les 4 derniers, ni rien de 4+
    for n in (4, 5, 6, 8):
        assert VALEUR[:n] not in rendu, "%s fuit un prefixe de %d car." % (cle, n)
        assert VALEUR[-n:] not in rendu, "%s fuit un suffixe de %d car." % (cle, n)
    assert "sha256" in rendu or re.search(r"\b[0-9a-f]{8,}\b", rendu), (
        "un secret doit rendre une EMPREINTE PUBLIQUE, qui permet de comparer "
        "deux instances sans rien reveler"
    )


@pytest.mark.parametrize("cle", ["LMSTUDIO_MODEL", "GEMINI_MODEL",
                                 "ONNXGENAI_MAX_TOKENS", "LLAMACPP_MAX_TOKENS"])
def test_un_reglage_reste_lisible(audit, cle):
    """« CONFIG doit rester lisible sans mecanisme cryptographique inutile ;
    ne doit pas etre secrete par simple convention. »"""
    rendu = audit.masquer(cle, "gemma-3-31b")
    assert "gemma-3-31b" in rendu, (
        "%s est un PARAMETRE de comportement : le masquer le rendrait secret "
        "par convention et ferait perdre sa lisibilite" % cle
    )


@pytest.mark.parametrize("cle", ["CLE", "NOM_CLE", "SILICONFLOW", "HAS_ONNX"])
def test_le_doute_protege(audit, cle):
    """FAIL-CLOSED : une cle INDETERMINEE se masque comme un secret.

    Masquer un reglage gene une lecture ; afficher un secret le publie. Les
    deux erreurs n'ont pas le meme cout, donc le defaut n'est pas symetrique.
    """
    rendu = audit.masquer(cle, VALEUR)
    assert VALEUR not in rendu
    assert VALEUR[:4] not in rendu


def test_une_valeur_absente_est_dite_et_non_inventee(audit):
    rendu = audit.masquer("OPENAI_API_KEY", None)
    assert VALEUR not in rendu
    assert rendu, "l'absence doit se DIRE, pas rendre une chaine vide ambigue"


def test_le_masquage_dit_la_nature_qu_il_a_appliquee(audit):
    """Un masquage muet empeche de verifier qu'il a applique la bonne regle."""
    rendu = audit.masquer("OPENAI_API_KEY", VALEUR)
    assert "SECRET" in rendu or "secret" in rendu


# ------------------------------------------------- raccord : l'afficheur reel

def test_l_afficheur_du_coffre_utilise_cette_politique():
    """Le cliquet anti-jumeau-mort.

    Une politique juste que l'afficheur n'appelle pas ne protege rien : c'est
    exactement ce qui s'est passe entre le CLI de `forge_secrets` (corrige) et
    `forge_secret_audit` (reste fuyant) le 2026-09-20.
    """
    # Ce test a d'abord ete ecrit comme une LECTURE du fichier : il cherchait le
    # motif fautif dans le texte et virait au rouge sur la docstring qui CITE ce
    # motif pour expliquer la correction. Un instrument ne lit jamais son propre
    # vocabulaire -- et un test se JOUE. On appelle donc l'afficheur.
    # Le cas critique est `verdict != OK` : c'est la branche qui rendait un prefixe.
    import importlib

    ma = importlib.import_module("nokido_agent.tools.forge_secret_audit")
    rendu = ma._mask(VALEUR, "SUSPECT_SHORT", "OPENAI_API_KEY")
    assert VALEUR not in rendu
    for n in (4, 5, 6, 8):
        assert VALEUR[:n] not in rendu, "prefixe de %d car. rendu par _mask" % n
        assert VALEUR[-n:] not in rendu, "suffixe de %d car. rendu par _mask" % n
    assert "empreinte" in rendu or "sha256" in rendu, (
        "l'afficheur doit passer par la politique unique, pas par une regle a lui"
    )
    assert "SUSPECT_SHORT" in rendu, (
        "le verdict sur la valeur (EMPTY/PLACEHOLDER/SUSPECT_SHORT/OK) reste "
        "utile : c'est une propriete de la valeur sans etre la valeur"
    )
