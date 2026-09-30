# -*- coding: utf-8 -*-
"""NR — la procedure de preuve ne doit pas prendre ses propres sorties pour une alteration.

MESURE 2026-09-09, quatre echecs de capture d'affilee sur des arbres pourtant sains :

    [generation] 1 fichier(s) SUIVI(s) modifie(s) — pas de capture
                 (le sha ne representerait pas l'etat teste)

Le fichier en cause etait `tests/nr/vitalite_gardes.json` — LE REGISTRE QUE LA CI
VIENT D'ECRIRE. Le serpent se mord la queue :

    la CI mesure un SHA dans un worktree detache
      -> elle ecrit son registre de vitalite DANS ce worktree
        -> `git status` n'est plus vide
          -> elle refuse de capturer ce qu'elle vient de mesurer

La capture T0 etait donc IMPOSSIBLE PAR CONSTRUCTION, quel que soit le code teste.
Ce n'est pas un arbre mal prepare : c'est une erreur de DEFINITION DE L'OBJET MESURE.
`git status == clean` est intrinsequement incompatible avec une procedure qui produit
ses preuves dans son propre worktree.

LE CRITERE JUSTE (arrete par l'owner le 2026-09-09) separe trois natures :

    PRODUIT     modification INTERDITE  — c'est l'objet mesure
    PREUVE      modification AUTORISEE  — sortie declaree du protocole
    INATTENDU   capture REFUSEE         — ni l'un ni l'autre, donc on ne sait pas

Le troisieme etat n'est pas un detail : sans lui on remplace « tout auto-output est
rejete » par « tout ce qui RESSEMBLE a un output est accepte », et le second est
bien plus dangereux. La liste est donc BLANCHE et DECLAREE — le defaut est le refus.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "app"))

import ci_local  # noqa: E402


def test_la_classification_des_modifications_existe():
    assert hasattr(ci_local, "classer_modification"), (
        "la nature d'une modification (PRODUIT / PREUVE / INATTENDU) doit etre une "
        "decision NOMMEE, pas un `git status == clean` implicite"
    )
    assert hasattr(ci_local, "capture_autorisee")


# --- PRODUIT : ce qui est mesure ne bouge pas -------------------------------

def test_un_fichier_du_produit_MODIFIE_refuse_la_capture():
    ok, motif = ci_local.capture_autorisee([(" M", "app/foo.py")])
    assert ok is False
    assert "app/foo.py" in motif, "le refus doit NOMMER le fichier : %r" % motif


def test_un_fichier_du_produit_NON_SUIVI_refuse_aussi():
    """CONTRE-EPREUVE. Sans elle, le garde accepterait n'importe quel intrus.

    Un `?? app/foo.py` est du code qui n'etait pas dans le SHA : le capturer
    dirait que le sha represente un etat qu'il ne represente pas.
    """
    ok, motif = ci_local.capture_autorisee([("??", "app/foo.py")])
    assert ok is False
    assert "app/foo.py" in motif


def test_un_test_quelconque_reste_du_PRODUIT():
    """`tests/nr/` n'est pas une zone de preuve : seul le registre l'est."""
    assert ci_local.classer_modification(" M", "tests/nr/test_foo_nr.py") == "PRODUIT"
    ok, _ = ci_local.capture_autorisee([(" M", "tests/nr/test_foo_nr.py")])
    assert ok is False


# --- PREUVE : ce que la mesure produit -------------------------------------

def test_le_registre_de_vitalite_est_une_sortie_de_PREUVE():
    assert ci_local.classer_modification(
        " M", "tests/nr/vitalite_gardes.json") == "PREUVE"


def test_une_generation_est_une_sortie_de_PREUVE():
    assert ci_local.classer_modification(
        "??", "docs/generations/GEN-00013.json") == "PREUVE"


def test_le_cas_REEL_du_2026_09_09_autorise_desormais_la_capture():
    """Les quatre lignes exactes que `git status` rendait dans le worktree."""
    reel = [(" M", "tests/nr/vitalite_gardes.json"),
            ("??", "docs/generations/GEN-00013.json"),
            ("??", "sandbox/ci_LaForgeSbxOffline/"),
            ("??", "sandbox/pytest_mutation_tmp/")]
    ok, motif = ci_local.capture_autorisee(reel)
    assert ok is True, (
        "l'arbre de reference ne portait QUE des sorties de la mesure : %s" % motif)


def test_un_arbre_strictement_propre_autorise_la_capture():
    ok, _ = ci_local.capture_autorisee([])
    assert ok is True


# --- INATTENDU : ce qu'on ne sait pas classer ------------------------------

def test_un_intrus_AU_MILIEU_de_sorties_legitimes_refuse_quand_meme():
    """Le refus ne doit pas se laisser noyer par des sorties valides."""
    ok, motif = ci_local.capture_autorisee([
        (" M", "tests/nr/vitalite_gardes.json"),
        ("??", "docs/generations/GEN-00013.json"),
        (" M", "app/forge_rag_engine.py"),
    ])
    assert ok is False
    assert "forge_rag_engine" in motif


def test_le_motif_dit_COMBIEN_et_LESQUELS():
    """Une borne qui dit TROP sans dire COMBIEN n'est pas diagnosticable."""
    ok, motif = ci_local.capture_autorisee([(" M", "app/a.py"), ("??", "app/b.py")])
    assert ok is False
    assert "a.py" in motif and "b.py" in motif
