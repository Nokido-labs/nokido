# -*- coding: utf-8 -*-
"""NR — la migration de la memoire ne peut pas la perdre.

Ce script deplace 776 fiches de memoire episodique. Un `move` suivi d'un
`mklink` qui echoue laisse les fiches ailleurs et Claude Code repart de zero :
c'est la seule operation de la journee dont l'echec detruirait de la
connaissance accumulee. Les proprietes ci-dessous sont donc gardees a la source,
pas seulement testees a l'execution.

Proprietes :

1. Les droits `mklink` sont EPROUVES avant tout deplacement — sur un dossier
   jetable. Decouvrir l'absence de droits apres avoir bouge la memoire serait
   trop tard.
2. On COPIE, on ne deplace pas : la source reste le filet jusqu'a la toute fin.
3. La copie est PROUVEE par empreinte, fichier par fichier — un comptage egal ne
   dit rien du contenu.
4. La source est RENOMMEE, jamais supprimee (« n'enterre rien »).
5. Tout echec restaure le nom d'origine.
6. Le dossier cible est ignore par git : ces fiches portent des chemins systeme
   et des empreintes, les versionner declencherait le gate egress a chaque push.
7. Le dry-run est le DEFAUT.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (l.137)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_memory_junction as mj  # noqa: E402


def test_le_dry_run_est_le_defaut():
    """Une operation destructrice ne part jamais toute seule."""
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    assert "def migrer(dry: bool = True)" in source, "le dry-run n'est pas le defaut"
    assert '"--executer"' in source, "l'execution reelle doit etre EXPLICITE"


def test_les_droits_sont_eprouves_avant_de_bouger():
    """PROPRIETE 1 : mklink est teste sur un dossier jetable, en premier.

    L'ordre compte : dans le corps de `migrer`, l'epreuve des droits doit
    apparaitre AVANT la premiere copie.
    """
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    corps = source[source.find("def migrer("):]
    i_droits = corps.find("_eprouver_les_droits")
    i_copie = corps.find("shutil.copy2")
    assert i_droits > 0, "aucune epreuve des droits"
    assert i_copie > 0, "aucune copie"
    assert i_droits < i_copie, "les droits sont testes APRES la copie : trop tard"


def test_le_dry_run_eprouve_VRAIMENT_les_droits():
    """ANTI-REGRESSION 2026-09-04 : le dry-run affichait « OK (non teste) ».

    Il rendait True sans rien eprouver, et l'imprimait comme un OK. L'owner
    aurait decide d'executer sur une mesure qui n'avait pas eu lieu — le defaut
    exact traque partout ailleurs aujourd'hui : afficher un acquittement sans
    l'avoir mesure.

    Le test de droits ne coute qu'un dossier temporaire aussitot defait : il n'y
    a aucune raison de l'esquiver en dry-run.
    """
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    i = source.find("def _eprouver_les_droits")
    corps = source[i:source.find("def ", i + 10)]
    assert 'return True, "non teste' not in corps, (
        "le dry-run rend un OK sans mesure")
    # Et l'appelant ne doit plus lui passer le drapeau dry.
    appel = source[source.find("ok_droits, detail = _eprouver_les_droits"):][:60]
    assert "_eprouver_les_droits()" in appel, (
        "les droits sont encore conditionnes au mode : %s" % appel.strip())


def test_un_refus_de_droits_arrete_aussi_le_dry_run():
    """Annoncer des etapes qui ne pourraient pas aboutir, c'est promettre a vide."""
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    corps = source[source.find("def migrer("):]
    i_refus = corps.find("if not ok_droits")
    i_dryrun = corps.find("if dry:\n        print")
    assert i_refus > 0, "aucun garde sur le refus de droits"
    assert "and not dry" not in corps[i_refus:i_refus + 60], (
        "le refus de droits ne s'applique pas au dry-run")


def test_on_copie_on_ne_deplace_pas():
    """PROPRIETE 2 : aucun `shutil.move` — la source reste intacte."""
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    corps = source[source.find("def migrer("):]
    assert "shutil.move" not in corps, (
        "un move rend la source irrecuperable si la suite echoue")
    assert "shutil.copy2" in corps


def test_la_copie_est_prouvee_par_empreinte():
    """PROPRIETE 3 : un comptage egal ne dit rien du contenu."""
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    assert "sha256" in source, "la copie n'est pas verifiee par empreinte"
    corps = source[source.find("def migrer("):]
    assert "manquants" in corps and "return 4" in corps, (
        "une copie non conforme doit interrompre AVANT le renommage")


def test_la_source_est_renommee_jamais_supprimee():
    """PROPRIETE 4 et 5 : « n'enterre rien », et tout echec restaure."""
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    corps = source[source.find("def migrer("):]
    assert "avant_jonction" in corps, "aucun dossier de secours"
    assert ".rmdir()" not in corps or "secours" in corps, (
        "la source ne doit jamais etre supprimee")
    assert "secours.rename(SOURCE)" in corps, "aucune restauration en cas d'echec"


def test_l_effet_de_la_jonction_est_relu():
    """Le code retour de mklink ne suffit pas : on relit la jonction.

    Meme discipline que partout ailleurs dans le projet — un rc ne prouve pas
    l'effet, et cette operation-la ne se rejoue pas.
    """
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    i = source.find("def _mklink")
    corps = source[i:i + 900]
    assert "_est_jonction(lien)" in corps, "le resultat de mklink n'est pas relu"


def test_le_dossier_memoire_est_ignore_par_git():
    """PROPRIETE 6 : lisible par le hub, invisible a git.

    Verifie par `git check-ignore`, pas par la presence d'une ligne : une regle
    plus haut dans le fichier pourrait la desamorcer.
    """
    r = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), "check-ignore", "-q", "memory/x.md"],
        capture_output=True, timeout=30)
    assert r.returncode == 0, (
        "memory/ n'est PAS ignore : 776 fiches de chemins systeme et d'empreintes "
        "partiraient au push et declencheraient le gate egress")


def test_une_jonction_deja_en_place_ne_refait_rien():
    """Idempotence : relancer ne doit pas empiler des dossiers de secours."""
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    corps = source[source.find("def migrer("):]
    i_test = corps.find("_est_jonction(SOURCE)")
    i_copie = corps.find("shutil.copy2")
    assert 0 < i_test < i_copie, "la jonction existante n'est pas detectee en premier"


def test_le_chemin_source_n_est_pas_code_en_dur():
    """Le script doit suivre le profil de qui le lance, pas une machine."""
    source = (ROOT / "tools" / "forge_memory_junction.py").read_text(encoding="utf-8")
    lignes = [l for l in source.splitlines()
              if "SOURCE =" in l and not l.lstrip().startswith("#")]
    assert lignes, "SOURCE introuvable"
    assert "Path.home()" in lignes[0], "le chemin source est code en dur : %s" % lignes[0]
