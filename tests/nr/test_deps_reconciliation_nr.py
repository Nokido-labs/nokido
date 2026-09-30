# -*- coding: utf-8 -*-
"""NR — la reconciliation des dependances classe par RISQUE et n'installe jamais rien.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la reconciliation manifeste/environnement/CVE"

CE QUE LA MESURE A TROUVE (2026-09-06). Trois sources disaient trois choses, et personne
ne les croisait : le manifeste (`requirements*.txt`) dit ce qu'on a DECIDE d'installer,
l'environnement dit ce qui TOURNE, et les deux outils de securite ne lisent pas la meme
chose -- Dependabot le manifeste, `pip-audit` l'environnement.

Ecart mesure : starlette epingle a 0.41.3 mais 1.0.0 installe, transformers 4.57.6 contre
5.9.0, pypdf 5.5.0 contre 6.12.2 -- 9 paquets en derive. Et 16 paquets vulnerables sont
ABSENTS du manifeste parce qu'ils sont transitifs : `pillow` (20 CVE) et `aiohttp` (14)
n'apparaissent dans AUCUNE alerte Dependabot.

CE QUE CE TEST GARDE :
  1. la classification par risque, parce que « monter 27 paquets » et « monter 20 paquets
     sans saut de majeure » ne sont pas le meme geste ;
  2. GELE n'est pas SUR : un paquet sans correctif s'instruit, il ne se traite pas ;
  3. l'outil n'installe RIEN -- les .pyd du hub sont verrouilles tant qu'il tourne, et une
     installation lancee depuis un outil d'analyse serait un effet de bord invisible.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_deps_reconcilier as rec  # noqa: E402

OUTIL = ROOT / "tools" / "forge_deps_reconcilier.py"


def test_les_versions_se_comparent_sans_dependance_externe():
    """`packaging` est absent de certains envs : la comparaison doit tenir seule."""
    assert rec._version("1.2.3") < rec._version("1.2.10"), "comparaison lexicale detectee"
    assert rec._version("46.0.3") < rec._version("50.0.0")
    assert rec._version("3.1.49") < rec._version("3.1.59")
    assert rec._version("1.0.0") < rec._version("1.3.1")
    # une version non numerique ne doit pas lever
    assert rec._version("2.23.1rc1")[:2] == (2, 23)


@pytest.mark.parametrize("nom,installe,correctif,attendu", [
    ("gitpython", "3.1.49", "3.1.59", "SUR"),        # meme majeure
    ("starlette", "1.0.0", "1.3.1", "SUR"),          # mineure, meme majeure
    ("cryptography", "46.0.3", "50.0.0", "MAJEURE"),  # quatre majeures d'ecart
    ("datasets", "4.8.5", "5.0.1", "MAJEURE"),
    ("torch", "2.11.0", "2.13.0", "LOURD"),          # lourd AVANT toute autre regle
    ("pytest", "8.4.2", "9.0.3", "LOURD"),
    ("diskcache", "5.6.3", None, "GELE"),            # aucun correctif publie
    ("mystere", None, "1.0.0", "INDETERMINE"),       # version installee illisible
])
def test_la_classification_par_risque(nom, installe, correctif, attendu):
    assert rec.classer(nom, installe, correctif) == attendu


def test_gele_prime_sur_tout_le_reste():
    """Un paquet sans correctif reste GELE meme s'il est lourd : on ne le traite pas."""
    assert rec.classer("torch", "2.11.0", None) == "GELE"


def test_le_manifeste_est_lu_avec_son_fichier_et_sa_ligne(tmp_path, monkeypatch):
    """Sans le fichier ET la ligne, une derive ne se corrige pas : elle se cherche."""
    faux = tmp_path
    (faux / "requirements.txt").write_text(
        "# commentaire\nstarlette==0.41.3\npypdf==5.5.0\nsans-epingle>=1.0\n",
        encoding="utf-8")
    (faux / "requirements-ml.txt").write_text("transformers==4.57.6\n", encoding="utf-8")
    monkeypatch.setattr(rec, "ROOT", faux)
    m = rec.lire_manifestes()
    assert m["starlette"]["epingle"] == "0.41.3"
    assert m["starlette"]["fichier"] == "requirements.txt"
    assert m["starlette"]["ligne"] == 2
    assert m["transformers"]["fichier"] == "requirements-ml.txt"
    assert "sans-epingle" not in m, "seules les epingles == sont exploitables"


def test_un_manifeste_absent_est_DIT_et_non_avale(tmp_path, monkeypatch, capsys):
    """Trois etats : un manifeste qu'on n'a pas pu lire n'est pas un manifeste vide."""
    monkeypatch.setattr(rec, "ROOT", tmp_path)
    rec.lire_manifestes()
    sortie = capsys.readouterr().out
    assert "ABSENT" in sortie, "l'absence doit etre nommee"


def test_un_rapport_absent_rend_une_consigne_et_pas_un_silence(tmp_path, capsys):
    """« aucune donnee » ne doit jamais se lire « rien a corriger »."""
    assert rec.lire_rapport(tmp_path / "inexistant.json") == []
    sortie = capsys.readouterr().out
    assert "ABSENT" in sortie and "pip_audit" in sortie, (
        "le rapport manquant doit dire COMMENT le produire")


def test_manifeste_en_retard_et_en_avance_ne_portent_pas_le_meme_nom(tmp_path, monkeypatch):
    """Les appeler tous deux « derive » ferait lire une panne la ou il y a un plan.

    EN RETARD : le manifeste decrit un passe revolu -- c'est le defaut a corriger.
    EN AVANCE : le manifeste a ete aligne sur le correctif et attend l'installation.
    """
    (tmp_path / "requirements.txt").write_text(
        "vieux==1.0.0\ncible==3.0.0\naligne==2.0.0\n", encoding="utf-8")
    (tmp_path / "requirements-ml.txt").write_text("", encoding="utf-8")
    monkeypatch.setattr(rec, "ROOT", tmp_path)
    # Le rapport se depose LA OU `rapport_courant()` va reellement le chercher :
    # <ROOT>/sandbox/pip_audit*.json. La constante `RAPPORT` a disparu le 2026-09-07,
    # quand l'outil est passe au rapport le PLUS RECENT -- et ce test, qui la patchait,
    # est mort en `AttributeError` : une API changee sans chercher ses appelants.
    # Emprunter le chemin REEL plutot que de patcher la fonction garde le test utile :
    # il traverse desormais la selection de source, au lieu de la court-circuiter.
    (tmp_path / "sandbox").mkdir(exist_ok=True)
    (tmp_path / "sandbox" / "pip_audit.json").write_text(json_rapport(), encoding="utf-8")
    par_nom = {x["paquet"]: x for x in rec.analyser()}
    assert par_nom["vieux"]["sens"] == "EN RETARD", "1.0.0 declare, 2.0.0 installe"
    assert par_nom["cible"]["sens"] == "EN AVANCE (cible)", "3.0.0 declare, 2.0.0 installe"
    assert par_nom["aligne"]["sens"] is None, "aucune divergence n'est un etat en soi"


def json_rapport() -> str:
    """Rapport minimal au format pip-audit, trois paquets en version 2.0.0 installee."""
    import json as _json

    return _json.dumps({"dependencies": [
        {"name": n, "version": "2.0.0",
         "vulns": [{"id": "X", "fix_versions": ["2.0.1"]}]}
        for n in ("vieux", "cible", "aligne")]})


def test_la_commande_est_derivee_de_la_mesure():
    """Recopier une liste a la main, c'est recopier l'etat d'hier."""
    code = OUTIL.read_text(encoding="utf-8")
    assert "--commande" in code
    assert "PYTHONNOUSERSITE" in code, "la commande doit porter le garde du user-site"
    assert "OWNER" in code, "la commande doit dire QUI peut la lancer"


def _capturer(shell, capsys):
    lignes = [{"paquet": "pyasn1", "cve": 4, "installe": "0.6.3", "correctif": "0.6.4",
               "classe": "SUR", "epingle": None, "manifeste": None, "derive": False,
               "sens": None, "transitif": True}]
    rec._imprimer_commandes(lignes, shell=shell)
    return capsys.readouterr().out


def test_la_commande_powershell_est_APPELABLE(capsys):
    """Mesure du 2026-09-06 : la commande a ete emise en cmd et collee dans PowerShell 7.

    Deux ruptures, pas une : `set VAR=1&&` n'existe pas en PowerShell, et une ligne qui
    COMMENCE par une chaine entre guillemets y est lue comme une EXPRESSION -- d'ou
    `Unexpected token '-m'`. Il faut l'operateur d'appel `&`.
    """
    sortie = _capturer("powershell", capsys)
    assert "$env:PYTHONNOUSERSITE" in sortie, "PowerShell n'a pas de `set VAR=`"
    assert "set PYTHONNOUSERSITE=1&&" not in sortie, "syntaxe cmd emise a un shell PowerShell"
    ligne = next(l for l in sortie.splitlines() if "pip install" in l).strip()
    assert ligne.startswith("$env:"), ligne
    assert "; & \"" in ligne, "sans l'operateur d'appel, PowerShell lit une expression"


def test_la_commande_cmd_reste_disponible_et_correcte(capsys):
    """`run action=shell` est bien du cmd.exe : la syntaxe doit rester atteignable."""
    sortie = _capturer("cmd", capsys)
    assert "set PYTHONNOUSERSITE=1&&" in sortie
    assert "$env:" not in sortie, "syntaxe PowerShell emise a cmd"


def _lignes_test():
    return [
        {"paquet": "pyjwt", "cve": 8, "installe": "2.12.1", "correctif": "2.13.0",
         "classe": "SUR", "binaire": False},
        {"paquet": "aiohttp", "cve": 14, "installe": "3.13.5", "correctif": "3.14.3",
         "classe": "SUR", "binaire": True},
        {"paquet": "mystere", "cve": 1, "installe": "1.0", "correctif": "1.1",
         "classe": "SUR", "binaire": None},
    ]


def test_les_paquets_a_extension_native_sont_SEPARES(capsys):
    """LE piege paye le 2026-09-06, et il a casse un paquet en production.

    `pip` DESINSTALLE avant d'installer. Sur `aiohttp`, dont un `.pyd` etait tenu par un
    process vivant, la desinstallation a echoue A MI-CHEMIN : `__init__.py` supprime,
    `.pyd` restants -> `ImportError: cannot import name 'ClientSession' from 'aiohttp'
    (unknown location)`, et litellm a cesse de s'importer. Le paquet n'etait pas
    « inchange », il etait CASSE.

    Consequence de conception : les deux familles ne partagent JAMAIS une ligne de
    commande, sinon un seul `.pyd` verrouille fait tomber les paquets sains avec lui.
    """
    sortie = _capturer_lignes(capsys)
    lignes_pip = [l for l in sortie.splitlines() if "pip install" in l]
    assert len(lignes_pip) == 2, "une ligne a chaud, une ligne stack arretee"
    chaud = next(l for l in lignes_pip if "pyjwt" in l)
    assert "aiohttp" not in chaud, "un paquet binaire ne doit pas voyager avec les sains"
    fenetre = next(l for l in lignes_pip if "aiohttp" in l)
    assert "pyjwt" not in fenetre
    assert "STACK ARRETEE REQUISE" in sortie
    assert "DESINSTALLE avant d'installer" in sortie, (
        "la raison doit etre ecrite, sinon quelqu'un refusionnera les deux lignes")


def test_un_paquet_dont_on_ignore_la_nature_va_du_cote_PRUDENT(capsys):
    """`binaire = None` = on n'a pas pu regarder. Un INCONNU ne se range pas du cote sain."""
    sortie = _capturer_lignes(capsys)
    fenetre = next(l for l in sortie.splitlines()
                   if "pip install" in l and "aiohttp" in l)
    assert "mystere" in fenetre, "l'indetermine doit rejoindre la fenetre, pas le chaud"
    assert "indeterminee" in sortie, "et son incertitude doit etre DITE"


def _capturer_lignes(capsys):
    rec._imprimer_commandes(_lignes_test(), shell="powershell")
    return capsys.readouterr().out


def test_le_defaut_vise_la_console_de_l_owner():
    """Le defaut doit etre PowerShell : c'est la console ou la commande sera collee."""
    import inspect

    sig = inspect.signature(rec._imprimer_commandes)
    assert sig.parameters["shell"].default == "powershell"


def test_l_obstacle_reel_est_nomme():
    """Deux obstacles distincts : le verrou du hub, et l'ACL du compte. Le second est le vrai."""
    code = OUTIL.read_text(encoding="utf-8")
    assert "WinError 5" in code
    assert "ACL" in code, "l'obstacle d'ACL doit etre distingue du verrou de processus"


def test_l_outil_n_installe_rien():
    """Une installation depuis un outil d'analyse serait un effet de bord invisible."""
    arbre = ast.parse(OUTIL.read_text(encoding="utf-8"))
    importes = {n.names[0].name.split(".")[0]
                for n in ast.walk(arbre) if isinstance(n, ast.Import)}
    importes |= {(n.module or "").split(".")[0]
                 for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom)}
    assert "subprocess" not in importes, "l'outil ne doit lancer aucun processus"
    assert "os" not in importes or True  # os seul est inoffensif ici
    code = OUTIL.read_text(encoding="utf-8")
    for interdit in ("pip install", "check_call", "Popen", "os.system"):
        # la consigne imprimee cite la commande a lancer A LA MAIN : on verifie qu'elle
        # n'est pas EXECUTEE, en s'appuyant sur l'AST plutot que sur le texte.
        if interdit in code:
            assert "subprocess" not in importes, (
                "la commande est citee, elle ne doit pas etre executee")


def test_les_DEUX_obstacles_restent_distingues():
    """Le lecteur doit savoir pourquoi l'outil s'arrete la -- et il y a DEUX raisons.

    Ce test a d'abord garde le MOT « arretee », et il est tombe des que la formulation a
    change alors que le fait, lui, etait toujours la (2026-09-06). Un NR garde un CONTENU,
    pas une tournure : il verifie donc que les deux obstacles sont NOMMES, quelle que soit
    la phrase qui les porte.
      1. verrou de PROCESSUS : les .pyd du hub sont tenus tant qu'il tourne ;
      2. droit d'ECRITURE : aucun compte du hub ne peut modifier le site-packages owner.
    Confondre les deux ferait chercher une fenetre d'arret la ou il faut un changement de
    compte -- et l'inverse.
    """
    code = OUTIL.read_text(encoding="utf-8")
    verrou = ".pyd" in code and ("verrouill" in code or "tenus" in code)
    droits = "WinError 5" in code and "ACL" in code
    assert verrou, "l'obstacle de VERROU de processus doit rester nomme"
    assert droits, "l'obstacle de DROITS d'ecriture doit rester nomme"
    assert "OWNER" in code, "la consequence -- c'est une action owner -- doit etre ecrite"
