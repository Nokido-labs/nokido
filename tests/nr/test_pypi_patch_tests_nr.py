#!/usr/bin/env python3
"""NR — reaccorder les `sys.modules` patches, sans desarmer aucun garde.

DEFAUT MESURE le 2026-09-10, apres la migration des imports.

    monkeypatch.setitem(sys.modules, "forge_npsc", None)   # import -> ImportError

Le code teste importe desormais `nokido_agent.tools.forge_npsc` — une entree
DIFFERENTE de `sys.modules`. Le patch n'a plus aucune prise : le test croit
simuler une panne, execute le chemin REEL, et passe pour la mauvaise raison.

Mesure : 63 NR touchent `sys.modules`, 42 visent un nom PLAT du depot.
Cas prouve : `test_le_handler_ne_leve_jamais` devait verifier qu'un handler
survit a un import casse ; il executait un vrai scan de 33 s et rendait
`npsc: 'OK'`, depassant au passage le timeout de la CI.

LA REGLE DE CETTE CORRECTION : on AJOUTE le nom namespace a cote du nom plat, on
ne REMPLACE jamais. Un patch qui garde les deux formes reste valide quel que soit
le chemin d'import — et on ne retire rien a un garde existant, conformement a
« on ne supprime pas l'ancien garde ; on corrige son domaine de validite ».
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tout tests/nr
#   (code appele) (l.57)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

pt = pytest.importorskip("forge_pypi_patch_tests")

_CARTE = {"forge_npsc": "tools", "forge_secrets": "app"}


def test_le_nom_namespace_est_deduit_de_la_zone_reelle():
    assert pt.jumeau("forge_npsc", _CARTE) == "nokido_agent.tools.forge_npsc"
    assert pt.jumeau("forge_secrets", _CARTE) == "nokido_agent.app.forge_secrets"


def test_un_module_hors_depot_n_a_pas_de_jumeau():
    """`numpy` ou un module inconnu ne doit recevoir aucun patch supplementaire :
    l'inconnu ne va jamais du cote favorable."""
    assert pt.jumeau("numpy", _CARTE) is None
    assert pt.jumeau("inconnu_total", _CARTE) is None


def test_un_nom_deja_namespace_n_est_pas_redouble():
    """Idempotence : repasser l'outil ne doit pas empiler les patches."""
    assert pt.jumeau("nokido_agent.tools.forge_npsc", _CARTE) is None


def test_le_denominateur_des_cibles_est_non_vide():
    """Regle owner : un instrument au denominateur vide est NON-CERTIFIANT. Sans
    cibles, l'outil declarerait la suite saine sans avoir rien regarde."""
    cibles = pt.fichiers_candidats()
    assert len(cibles) >= 20, f"seulement {len(cibles)} NR candidats : perimetre suspect"


# ------------------------------- MOTIFS D'IMPORT DANS LES ASSERTIONS
#
# Mesure du 2026-09-10 : 15 tests verifient un CABLAGE par motif TEXTUEL —
#
#     assert "from forge_ports import probe" in src
#
# Ils s'assurent qu'un module DELEGUE au lieu de dupliquer. La migration a change
# la forme de l'import : le cablage existe toujours, le garde ne le reconnait
# plus. Meme classe que les 42 patches `sys.modules` devenus inertes.


def test_l_oracle_VISE_la_nouvelle_forme_et_ne_garde_pas_l_ancienne():
    """CORRECTION DE METHODE (owner, 2026-09-10).

    Ma premiere version ELARGISSAIT :

        assert "from forge_x import y" in src or "from nokido_agent...x import y" in src

    Un tel oracle passe QUELLE QUE SOIT la forme — il ne protege donc plus rien.
    « Ne transforme jamais un test simplement pour le faire passer. Transforme son
    oracle pour qu'il verifie la nouvelle propriete reellement voulue. »

    Le code source ne porte plus qu'UNE forme apres migration : l'oracle doit
    viser CELLE-LA. Si le code revenait au chemin plat, le test DOIT rougir —
    c'est precisement son role.
    """
    ligne = '    assert "from forge_secrets import get_secret" in src\n'
    nouveau, faits = pt.viser_la_cible(ligne, _CARTE)
    assert faits, "aucune transformation proposee"
    assert "nokido_agent.app.forge_secrets" in nouveau
    assert '"from forge_secrets import get_secret"' not in nouveau, (
        "l'ancienne forme est conservee : l'oracle ne protege plus la cible")
    assert " or " not in nouveau


def test_un_oracle_deja_cible_n_est_pas_retouche():
    """Idempotence."""
    ligne = '    assert "from nokido_agent.app.forge_secrets import get_secret" in src\n'
    _nouveau, faits = pt.viser_la_cible(ligne, _CARTE)
    assert not faits


def test_une_disjonction_heritee_est_RESSERREE_sur_la_cible():
    """Les deux fichiers elargis par la v1 doivent revenir a un oracle qui vise."""
    ligne = ('    assert ("from forge_secrets import get_secret" in src or '
             '"from nokido_agent.app.forge_secrets import get_secret" in src)\n')
    nouveau, faits = pt.viser_la_cible(ligne, _CARTE)
    assert faits, "la disjonction heritee n'a pas ete resserree"
    assert " or " not in nouveau
    assert '"from forge_secrets import get_secret"' not in nouveau


def test_un_module_hors_depot_n_est_pas_touche():
    ligne = '    assert "from numpy import array" in src\n'
    _nouveau, faits = pt.viser_la_cible(ligne, _CARTE)
    assert not faits


def test_une_forme_INCONNUE_est_declaree_NON_TRANSFORMEE():
    """Regle owner : quatre formes d'assertion sont semantiquement differentes.

        assert CONDITION
        assert CONDITION, "message"
        assert "X" in src
        assert {"a", "b"} <= imports

    Le codemod doit soit savoir exactement transformer, soit le DIRE et laisser
    le cas a instruire. Un transformateur syntaxique correct sur le corps peut
    etre faux sur la semantique particuliere des tests.
    """
    ligne = '    assert {"_cos", "echantillon"} <= importes_de("forge_secrets")\n'
    nouveau, faits = pt.viser_la_cible(ligne, _CARTE)
    assert nouveau == ligne, "une forme non reconnue a ete transformee quand meme"
    assert not faits
    assert "forge_secrets" in pt.NON_TRANSFORMES or not faits


def test_une_assertion_AVEC_MESSAGE_ne_devient_JAMAIS_un_tuple():
    """LE FAUX VERT LE PLUS DANGEREUX, produit par cet outil meme (2026-09-10).

        assert X in src, "message"
        -> assert (X in src, "message" or Y in src)     # TUPLE -> TOUJOURS VRAI

    Python le signale par un `SyntaxWarning: assertion is always true`, mais un
    warning ne fait echouer aucune CI. Le garde aurait ete desarme en silence —
    exactement ce que ce chantier existe pour empecher.

    La condition doit etre enveloppee SEULE, le message reste dehors.
    """
    import warnings
    ligne = '    assert "from forge_secrets import get" in src, "le module doit deleguer"\n'
    nouveau, faits = pt.viser_la_cible(ligne, _CARTE)
    assert faits, "l'elargissement n'a pas eu lieu"
    assert '"le module doit deleguer"' in nouveau, "le message a ete perdu"
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(nouveau.strip(), "<test>", "exec")   # leve si l'assert est un tuple


def test_une_forme_non_reecrivable_est_laissee_INTACTE():
    """On ne devine pas : si la transformation ne compile pas, la ligne d'origine
    est conservee telle quelle et le cas est declare NON_TRANSFORME.

    ⚠️ Premiere version de CE test : elle utilisait `# noqa: E501 (` — un
    COMMENTAIRE, que le compilateur ignore. La ligne etait donc parfaitement
    reecrivable, et le test verifiait le contraire de ce qu'il croyait. Il faut
    une forme qui casse REELLEMENT la compilation.
    """
    ligne = '    assert "from forge_secrets import get" in src and (\n'
    nouveau, faits = pt.viser_la_cible(ligne, _CARTE)
    assert nouveau == ligne, "une forme non compilable a ete transformee quand meme"
    assert not faits


def test_le_resultat_reste_du_python_valide():
    import ast
    ligne = 'assert "from forge_npsc import charger_registre" in src\n'
    nouveau, faits = pt.viser_la_cible(ligne, {"forge_npsc": "tools"})
    assert faits
    ast.parse(nouveau)


def test_la_carte_des_modules_est_partagee_avec_le_codemod():
    """Deux cartes qui divergeraient produiraient deux verites sur la zone d'un
    module — et un patch pose sur la mauvaise."""
    import forge_pypi_codemod as cm
    assert pt.carte() == cm.carte_modules()


# ------------------------------- CE QUE L'OUTIL NE DOIT PAS FAIRE


def test_l_outil_n_analyse_PAS_son_propre_NR():
    """UN INSTRUMENT NE LIT JAMAIS SON PROPRE VOCABULAIRE (regle du corps).

    Ce fichier porte des FIXTURES : des chaines `"from forge_x import y"`
    fabriquees pour eprouver la transformation. Les reecrire ne corrige aucun
    cablage — ca detruit le banc d'essai, et le banc se met alors a valider la
    transformation sur son propre resultat.

    Mesure du 2026-09-10 : le premier balayage `--motifs` proposait de modifier
    ce fichier (`forge_secrets -> nokido_agent.app.forge_secrets`).
    """
    assert Path(__file__).name in pt.AUTO_EXCLUS


def test_la_virgule_D_UN_IMPORT_ne_coupe_pas_la_condition():
    """La virgule de `import punish, reward` vit DANS la chaine.

    Un decoupage condition/message qui ignore les litteraux coupe apres
    `punish` et produit `assert "from ... import punish` — non compilable. La
    ligne sortait alors en NON_TRANSFORME alors que sa forme est parfaitement
    connue. Mesure du 2026-09-10 : 1 oracle perdu sur ce seul defaut.
    """
    ligne = '    assert "from forge_secrets import punish, reward" in bloc\n'
    nouveau, faits = pt.viser_la_cible(ligne, _CARTE)
    assert faits, "un import multi-symboles a ete refuse a tort"
    assert "nokido_agent.app.forge_secrets import punish, reward" in nouveau


def test_un_MESSAGE_multiligne_ne_fait_pas_refuser_la_condition():
    """Forme reelle, mesuree sur 3 NR :

        assert "from forge_x import" in CODE, (
            "message sur les lignes suivantes")

    La ligne ENTIERE ne compile pas — la parenthese du message reste ouverte —
    alors que la transformation ne touche que la condition. Valider la ligne
    entiere faisait refuser une forme connue ; on valide la CONDITION SEULE.
    """
    ligne = '    assert "from forge_secrets import get" in CODE, (\n'
    nouveau, faits = pt.viser_la_cible(ligne, _CARTE)
    assert faits, "la forme `assert X, (` a ete refusee a tort"
    assert nouveau.endswith(", (\n"), "le message a ete ampute"
    assert "nokido_agent.app.forge_secrets" in nouveau


def test_les_refus_sont_RAPPORTES_et_pas_seulement_collectes():
    """Un refus MUET ne se distingue pas d'un succes. `NON_TRANSFORMES` etait
    rempli et jamais lu : un fichier que l'outil ne savait pas traiter sortait
    comme un fichier « rien a faire »."""
    import inspect
    src = inspect.getsource(pt.main)
    assert "non_transformes" in src, "les refus ne remontent pas dans le rapport"
    assert "NON_TRANSFORME :" in src, "les refus ne sont pas imprimes"
