"""NR (29/10) : une delegation qui a PRODUIT des commits n'est pas un echec d'authentification du CLI.

Mesure : job_3a3347e0 (chantier securite, CLAUDE_HEADLESS) a livre 2 commits (b60b56247..54e0319ad), puis
`_motif_reaffectation_apres` a rendu « ECHEC AUTHENTIFICATION : [effet observe] commits produits : 2 ... » : la regex
d'echec d'auth a mordu sur l'EFFET (observation de l'executeur, qui cite les fichiers declares d'une tache portant sur
l'authentification). Consequence : surface marquee indisponible, tache reaffectee a MISTRAL, RIEN_PRODUIT.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ex():
    nom = "forge_task_executor_nr_auth_commits"
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, ROOT / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


EFFET_LIVRE = ("[effet observe] commits produits : 2 (b60b56247..54e0319ad) ; fichiers non commites : 0 ; "
               "[artefact ABSENT] fichier declare absent : tests/nr/test_jeton_tpm_401_unauthorized_nr.py")


def test_commits_produits_jamais_echec_auth():
    m = _ex()
    motif = m._motif_reaffectation_apres(False, EFFET_LIVRE, "Le chantier est livre en partie.")
    assert not (motif or "").startswith("ECHEC AUTHENTIFICATION")


def test_vrai_echec_auth_sans_commit_reste_detecte():
    m = _ex()
    effet = "[effet observe] commits produits : 0 (aaa..aaa) ; fichiers non commites : 0"
    motif = m._motif_reaffectation_apres(False, effet, "Error: authentication failed, please run /login")
    assert (motif or "").startswith("ECHEC AUTHENTIFICATION")
