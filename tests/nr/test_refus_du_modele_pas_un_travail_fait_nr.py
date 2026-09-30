"""NR — un refus du modele ne peut pas etre enregistre comme une tache reussie.

Mesure du 2026-09-18. Une revue de code deleguee a ANTIGRAVITY est revenue avec
ce texte, 377 caracteres, et la tache a ete ecrite `status='done'` :

    « Sorry, I cannot fulfill your request. I am unable to perform vulnerability
      scanning or security analysis on specific codebases... »

Le garde-fou du MODELE etait servi comme LIVRABLE. C'est un faux vert au bout de
la chaine de delegation : celui qui lit `done` croit la tache faite, et le
travail n'a jamais eu lieu.

Deuxieme fois en trois jours. Le 2026-09-16, la generation d'interface rendait
« User Safety: safe » comme du HTML — le piege avait ete consigne dans un
commentaire de `web_hub/ui_generate.py`, et nulle part ailleurs. Un piege
consigne dans UN module ne protege que ce module : d'ou un detecteur partage,
pose a cote de son jumeau `_est_accuse_reception`, qui traitait deja « une
reponse qui promet un travail au lieu d'en rendre compte ».

Le sens du garde importe autant que son existence : il ne fait pas echouer plus,
il EMPECHE de croire a un succes. Un refus est une formulation a reprendre, pas
un bug a chercher — et le message le dit, sinon on envoie quelqu'un debugger
quelque chose qui n'a pas plante.
"""

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ⚠️ PAS d'`importorskip` ici. Ce module EST le livrable teste : s'il ne
# s'importe pas, le NR doit ECHOUER, pas se taire. Un test qui se skip
# silencieusement protege ce qu'on croit protege et rien d'autre
# (lecon du 2026-09-08 : « importorskip sur un livrable = faux vert »).
from tools import forge_task_executor as E  # noqa: E402

# Le texte EXACT revenu le 2026-09-18, jamais une paraphrase : un garde se
# verifie sur ce qui l'a pris en defaut.
REFUS_MESURE = (
    "Sorry, I cannot fulfill your request. I am unable to perform vulnerability "
    "scanning or security analysis on specific codebases, applications, or concrete "
    "targets. You may want to search online for secure coding practices regarding web "
    "protocols, authentication, and authorization, or use dedicated static analysis "
    "tools to audit your code for these classes of vulnerabilities."
)


def test_le_refus_mesure_est_reconnu():
    motif = E.est_refus_du_modele(REFUS_MESURE)
    assert motif, (
        "le texte meme qui a produit le faux vert du 2026-09-18 n'est pas reconnu"
    )


def test_le_motif_est_rendu_pas_un_booleen():
    """« refusee » et « plantee » n'appellent pas la meme suite."""
    motif = E.est_refus_du_modele(REFUS_MESURE)
    assert isinstance(motif, str) and motif in REFUS_MESURE.lower(), (
        f"le motif rendu ne se retrouve pas dans le texte : {motif!r}"
    )


@pytest.mark.parametrize(
    "txt",
    [
        "I cannot assist with that.",
        "Sorry, I can't provide this.",
        "Je ne peux pas effectuer cette analyse.",
        "As an AI language model, I must decline.",
    ],
)
def test_les_autres_formes_de_refus_sont_reconnues(txt):
    assert E.est_refus_du_modele(txt), f"forme de refus ratee : {txt!r}"


@pytest.mark.parametrize(
    "txt",
    [
        # un vrai compte rendu, qui se trouve CITER un refus
        "J'ai relu les handlers. Un agent avait repondu « I cannot fulfill your "
        "request » : j'ai reformule la tache et obtenu le tableau demande.",
        # un compte rendu ordinaire
        "| 1 | route publique | app/web_hub/app.py:2105 | confirme |",
        "Nous avons corrige le garde et rejoue 97 tests.",
        "",
    ],
)
def test_aucun_faux_positif_sur_un_vrai_compte_rendu(txt):
    v = E.est_refus_du_modele(txt)
    assert v is None, (
        f"compte rendu pris pour un refus (motif {v!r}) — un garde qui crie a faux "
        "se fait desarmer"
    )


def test_un_texte_long_n_est_pas_un_refus():
    """Un refus ne detaille rien. Un long texte qui contient la formule est un
    document QUI EN PARLE — par exemple ce fichier de test."""
    long = REFUS_MESURE + " " + ("analyse detaillee. " * 120)
    assert len(long) >= 1500
    assert E.est_refus_du_modele(long) is None


def test_un_ACCUSE_de_reception_n_est_pas_un_livrable():
    """Mesure du 2026-09-19 : un audit delegue est revenu en annonçant le
    travail au FUTUR, et a ete enregistre `done` / SUCCESS."""
    accuse = ("I am running the AST scanner in the background to look for all "
              "the deserialization points across the entire Nokido workspace. "
              "I will review the results and write the requested report once "
              "the scan is complete.\n")
    assert E._est_accuse_reception(accuse) is True


def test_le_detecteur_d_accuse_est_CONSOMME_par_le_vrai_ecrivain():
    """Un detecteur sans consommateur ne garde rien.

    `_est_accuse_reception` existait, mordait correctement, et n'avait qu'UN
    appelant : `forge_task_executor`, dont le chemin ecrit `completed`. Les
    taches deleguees passent par `forge_mcp_registry`, qui ecrit `done` — le
    garde tenait une porte, pas l'autre. On verifie donc le CABLAGE, par AST,
    sur le fichier qui ecrit reellement le statut.
    """
    registre = RACINE / "app" / "forge_mcp_registry.py"
    assert registre.exists(), "l'ecrivain reel du statut a disparu"
    arbre = ast.parse(registre.read_text(encoding="utf-8", errors="replace"))
    importe = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and n.module and "forge_task_executor" in n.module:
            importe.update(a.name for a in n.names)
    assert "_est_accuse_reception" in importe, (
        "forge_mcp_registry n'importe pas le detecteur d'accuse : une tache qui "
        "rend un accuse sera ecrite `done`, donc lue comme faite")
    assert "est_refus_du_modele" in importe, (
        "le detecteur de refus a ete debranche du vrai ecrivain")


def test_le_chemin_reel_consulte_le_detecteur_avant_d_ecrire_le_statut():
    """MORSURE SUR LE CHEMIN REEL, pas sur la fonction seule.

    Le defaut n'etait pas l'absence d'un detecteur : c'est que la route qui ECRIT
    le statut posait `done` en dur. Un detecteur qu'aucun ecrivain ne consulte est
    une dette de cablage, jamais une securite. On lit donc l'AST de la route.
    """
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)

    litteraux = [
        n.value
        for n in ast.walk(arbre)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and "UPDATE tasks SET status=" in n.value
    ]
    assert litteraux, "la route qui ecrit le statut d'une tache est introuvable"
    fige = [s for s in litteraux if "status='done'" in s or 'status="done"' in s]
    assert not fige, (
        "le statut de tache est de nouveau ecrit en dur a `done` : un refus du "
        f"modele redeviendrait un succes. Requetes fautives : {fige}"
    )
    assert "est_refus_du_modele" in src, (
        "la route n'appelle plus le detecteur de refus : le garde existe mais "
        "personne ne le consulte"
    )
