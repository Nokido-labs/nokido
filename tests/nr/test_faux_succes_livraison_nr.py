"""NR -- faux succes de livraison mesures le 6/11 (job_2e450653, job_441754a9).

1. Une tache `done` dont le resultat porte « [artefact ABSENT] » s'affichait SUCCESS dans le guet des delegations :
   `_livraison` passe ok=(statut == "done") a `_statut_livraison`, qui promouvait ok en SUCCESS.
2. Un artefact qui RECOPIE la consigne passait SUCCESS : le juge ne mesurait aucun recouvrement.
Un vrai rendu reste SUCCESS. Par les vraies fonctions ; les textes de rendu sont SYNTHETIQUES (la mesure sur
`git show 06978f2cf:debat_rings_ANTIGRAVITY_20261106.md` reste a faire a la relecture).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
CONSIGNE = (
    "Debat sur les rings des agents : pour chaque agent du swarm, dis quel ring lui convient, pourquoi, et quel "
    "risque une elevation ferait courir au depot. Compare au moins trois agents, cite les gardes concernes, "
    "propose une regle de decision et ecris le rendu dans debat_rings_NOM_20261106.md a la racine du worktree."
)
RENDU_REEL = (
    "# Rings : ma position\n\nLe ring 1 suffit a un executeur delegue : il ecrit sous app/ et tests/, "
    "jamais dans les gardes. Une elevation au ring 0 donnerait la main sur forge_videur et ruinerait l'audit.\n"
    "OPENCODE reste ring 2 faute de preuve de fiabilite ; CODEX monte seulement apres trois livraisons relues.\n"
    "Regle proposee : un ring ne s'obtient que par decision owner inscrite dans config/agent_identities.json, "
    "puis se verifie par whoami, jamais de memoire. Risque principal : une elevation ecrite a la main dans un "
    "repli legacy reste sans effet et hors canal du hub, donc invisible a l'audit.\n"
)


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def executeur():
    return _charger("faux_succes_executeur_nr", RACINE / "tools" / "forge_task_executor.py")


@pytest.fixture(scope="module")
def guet(executeur):
    tools = str(RACINE / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    sys.modules["forge_task_executor"] = executeur   # repli checkout de `_livraison` : les vraies fonctions
    return _charger("faux_succes_guet_nr", RACINE / "tools" / "forge_job_watch_cli.py")


# --- cas 1 : FAILURE ne s'affiche jamais SUCCESS -------------------------------------------------------------

RESULTAT_CAS1 = ("[effet observe] commits produits : 0 (aaa..aaa) ; fichiers non commites : 0 ; "
                 "[artefact ABSENT] debat_rings_OPENCODE_NEMOTRON_20261106.md | "
                 '{"intent": "ERR_INTERNAL", "pointer_ref": "debat_rings_OPENCODE_NEMOTRON_20261106.md"}')


def test_cas1_done_avec_artefact_absent_est_failure(guet):
    assert guet._livraison(RESULTAT_CAS1, "done") == "FAILURE"


def test_cas1_la_ligne_du_guet_ne_dit_pas_success(guet):
    ev = {"task_id": "job_2e450653", "genre": "STATUT", "de": "running", "vers": "done",
          "livraison": guet._livraison(RESULTAT_CAS1, "done")}
    ligne = guet.ligne_evenement(ev)
    assert "[FAILURE]" in ligne and "SUCCESS" not in ligne, ligne


def test_statut_livraison_ok_vrai_ne_promeut_pas_un_artefact_absent(executeur):
    assert executeur._statut_livraison(True, RESULTAT_CAS1) == "FAILURE"


def test_vrai_succes_reste_success(guet, executeur):
    resultat = "[effet observe] commits produits : 1 (aaa..bbb) ; fichiers non commites : 0 | OK_DONE"
    assert guet._livraison(resultat, "done") == "SUCCESS"
    assert executeur._statut_livraison(True, resultat) == "SUCCESS"


# --- cas 2 : recopie de la consigne --------------------------------------------------------------------------

def test_cas2_mesure_separe_recopie_et_vrai_rendu(executeur):
    recopie = "# Debat\n\n" + CONSIGNE
    assert executeur.mesurer_recopie(recopie, CONSIGNE) >= executeur.SEUIL_RECOPIE
    assert executeur.mesurer_recopie(RENDU_REEL, CONSIGNE) < executeur.SEUIL_RECOPIE / 2


def test_cas2_recopie_partielle_reelle_passe_le_seuil(executeur):
    """Mesure du 6/11 : la vraie recopie (job_441754a9) reprend 39 % et le 0.6 d'origine la laissait passer."""
    assert 0.135 < executeur.SEUIL_RECOPIE < 0.39
    partielle = CONSIGNE + "\n\n" + RENDU_REEL
    mesure = executeur.mesurer_recopie(partielle, CONSIGNE)
    assert executeur.SEUIL_RECOPIE <= mesure < 0.6, mesure
    assert executeur._recopie_consigne({"a.md": partielle}, CONSIGNE)


def test_texte_court_dicte_par_la_consigne_ne_se_juge_pas(executeur):
    """Cas reel job_45b4edc0 : la consigne dicte un fichier de 227 octets, recouvrement 0.529 sans faute."""
    court = "Debat sur les rings des agents : pour chaque agent du swarm, dis quel ring lui convient."
    assert executeur.mesurer_recopie(court, CONSIGNE) >= executeur.SEUIL_RECOPIE
    assert executeur._recopie_consigne({"a.md": court}, CONSIGNE) is None


def test_marque_citee_par_l_agent_ne_frappe_pas_le_verdict(executeur):
    """Seul le constat de l'executeur, avant « | », compte ; l'agent peut parler des marques."""
    resultat = ("[effet observe] commits produits : 1 (aaa..bbb) ; fichiers non commites : 0 | "
                "le juge pose [artefact ABSENT] et [RECOPIE CONSIGNE] : corrige et teste")
    assert executeur._statut_livraison(True, resultat) == "SUCCESS"


def _git(wd, *a):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                           "-C", str(wd), *a], check=True, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)


def _depot(tmp_path, contenu):
    _git(tmp_path, "init", "-q")
    (tmp_path / "base.txt").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    h_av = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    (tmp_path / "debat_rings_20261106.md").write_text(contenu, encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "rendu")
    return (h_av, 0)


def test_cas2_juge_refuse_la_recopie_de_la_consigne(executeur, tmp_path):
    avant = _depot(tmp_path, "# Debat\n\n" + CONSIGNE)
    motif = executeur._contenu_recopie(str(tmp_path), avant, CONSIGNE)
    assert motif and "[RECOPIE CONSIGNE]" in motif, motif
    assert executeur._statut_livraison(False, "commits produits : 1 (a..b) ; fichiers non commites : 0 ; " + motif) != "SUCCESS"


def test_vrai_rendu_n_est_pas_une_recopie(executeur, tmp_path):
    avant = _depot(tmp_path, RENDU_REEL)
    assert executeur._contenu_recopie(str(tmp_path), avant, CONSIGNE) is None
