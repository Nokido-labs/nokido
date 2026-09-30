"""NR — ce lanceur est ORPHELIN de son organe, et il doit le dire FRANCHEMENT.

DETTE INSTRUITE. Le cliquet `test_aucun_module_nouveau_sans_test` refuse la CI
en nommant `forge_veille_campagne_run`, ajoute sans aucun NR, et sa consigne est
« ecrire un test qui verifie son EFFET (pas son import) ». L'EFFET mesure est
qu'il n'en a aucun.

CE QUE LA MESURE A ETABLI, sur le chemin reel (2026-09-21)
==========================================================
    $ LAFORGE_PYTHON tools/forge_veille_campagne_run.py
    ModuleNotFoundError: No module named
        'nokido_agent.tools.forge_veille_github_direct'

Le module importe n'existe NI dans tools/ NI dans app/, et `CAMPAGNE_2026_08_30`
n'est defini nulle part -- il n'est qu'importe, par ce seul fichier.

L'HISTOIRE, lue dans git et non devinee :

    fab6fcca5  chore(veille): supprimer l ingesteur de documents de tete
               -- decision owner
               tools/forge_veille_github_direct.py   [SUPPRIME]

L'organe a ete retire SUR DECISION OWNER. Son lanceur est reste. Ce n'est donc
pas un bug d'ecriture : c'est un RESIDU de suppression.

POURQUOI CE FICHIER N'EST PAS SUPPRIME ICI
==========================================
« Geler, jamais supprimer » -- et le mandat V8 interdit nommement de rendre la
CI verte en supprimant ce qu'elle denonce. Retirer ce lanceur serait le
COMPLEMENT d'une decision owner deja prise, pas une decision d'agent. Elle lui
revient.

CE QUE CE NR VERROUILLE EN ATTENDANT, et c'est utile tout de suite
=================================================================
Un lanceur orphelin lance par `run_job` produit le pire des etats : le spawn
REUSSIT, donc `ok: true`, et le job meurt a l'import sans avoir rien fait.
C'est ACCEPTED pris pour PRODUCED -- l'invariant meme de ce mandat. Le NR fige
donc que l'echec reste FRANC et NOMME : si un jour l'import se met a passer
silencieusement (module re-cree a moitie, stub vide), ce test le dira.

Il ne celebre pas un defaut : il empeche ce defaut de devenir SILENCIEUX, et il
garde sa cause attachee a son constat.
"""
import ast
import importlib
import pathlib

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les
#   tools/*.py et app/*.py (l.102)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

MOD = "nokido_agent.tools.forge_veille_campagne_run"
DEPENDANCE = "nokido_agent.tools.forge_veille_github_direct"
SRC = pathlib.Path(__file__).resolve().parents[2] / "tools" / "forge_veille_campagne_run.py"


def test_l_organe_lance_a_bien_ete_retire():
    """Le constat de base, mesure et non suppose."""
    racine = SRC.parent.parent
    for rel in ("tools/forge_veille_github_direct.py", "app/forge_veille_github_direct.py"):
        assert not (racine / rel).exists(), (
            "%s est REVENU : ce NR decrit un orphelinage qui n'existe plus, "
            "il faut le reecrire pour tester le lanceur pour de vrai" % rel
        )


def test_le_lanceur_echoue_FRANCHEMENT_et_nomme_ce_qui_manque():
    """Le coeur : l'echec doit rester bruyant.

    Un lanceur orphelin lance par run_job donne ok:true au spawn puis meurt a
    l'import. Si cet import se mettait a passer en silence -- stub vide, module
    a moitie recree -- le job repartirait en rendant « reussi » sans rien
    produire. On exige donc une erreur, et qu'elle NOMME le module absent.
    """
    with pytest.raises(ModuleNotFoundError) as exc:
        importlib.import_module(MOD)
    assert "forge_veille_github_direct" in str(exc.value), (
        "l'erreur doit nommer le module manquant, sinon le diagnostic coute "
        "une enquete entiere"
    )


def test_le_lanceur_ne_porte_aucune_logique_propre():
    """S'il portait de la logique, la supprimer PERDRAIT quelque chose et la
    decision ne serait plus un simple complement de fab6fcca5."""
    arbre = ast.parse(SRC.read_text(encoding="utf-8", errors="replace"))
    fonctions = [n.name for n in arbre.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    assert fonctions == [], (
        "ce lanceur definit %s : il n'est plus un simple wrapper, et le retirer "
        "perdrait du code" % fonctions
    )


def test_il_reste_le_SEUL_a_nommer_cette_campagne():
    """Si un autre module reprenait la campagne, le lanceur serait rattachable
    et la decision changerait."""
    racine = SRC.parent.parent
    porteurs = []
    for sous in ("tools", "app"):
        d = racine / sous
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.py")):
            try:
                if "CAMPAGNE_2026_08_30" in p.read_text(encoding="utf-8", errors="replace"):
                    porteurs.append("%s/%s" % (sous, p.name))
            except OSError:
                # ILLISIBLE n'est pas ABSENT : on ne conclut pas sur un fichier
                # qu'on n'a pas pu lire, on le dit.
                porteurs.append("%s/%s [ILLISIBLE]" % (sous, p.name))
    assert porteurs == ["tools/forge_veille_campagne_run.py"], (
        "la campagne est nommee ailleurs (%s) : le lanceur serait alors "
        "rattachable, et ce NR ne decrit plus la bonne situation" % porteurs
    )


def test_la_decision_reste_ouverte_et_documentee():
    """Le fichier doit porter la trace de son etat, sinon le prochain lecteur
    refera l'enquete entiere."""
    txt = SRC.read_text(encoding="utf-8", errors="replace")
    assert "__FORGE_COLOR__" in txt, "tout forge_*.py declare son organe"
