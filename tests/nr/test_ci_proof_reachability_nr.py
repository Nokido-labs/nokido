"""NR de REACHABILITY — la preuve est ecrite sur TOUS les chemins de sortie.

Mesure du 2026-09-19, et c'est la raison d'etre de ce fichier : les NR de A3
appelaient `_ecrire_ci_proof()` DIRECTEMENT et passaient 24/24, pendant que la
production ne l'atteignait jamais — `main` rend 1 au premier gate bloquant, bien
avant `_inscrire_generation`. Sur 90 executions : ZERO `ci_proof.json`, y compris
pour un run qui avait mesure 10 892 tests et nomme trois blocs coupes.

    un NR qui appelle la fonction prouve qu'elle MARCHE si on l'appelle.
    il ne prouve pas qu'elle EST appelee. Deux affirmations differentes.

A ne pas confondre avec `tools/forge_reachability_ledger.py` (phase 8), qui est un
registre d'atteignabilite de SERVICES — objet different, meme mot.

Ce fichier garde la SECONDE affirmation. Deux moyens, et leurs limites sont dites :

  1. AST sur les chemins de sortie de `main` et `_inscrire_generation` —
     structurel, donc robuste au renommage des messages, mais il prouve les SITES
     d'appel, pas leur execution ;
  2. traversee REELLE du caller `_inscrire_generation` jusqu'a l'artefact ecrit —
     executee, mais elle n'englobe pas `main`.

Ensemble elles couvrent la chaine ; separement, aucune ne suffit. La traversee de
`main` de bout en bout reste le fait d'une CI complete, et c'est DIT ici plutot
que sous-entendu.
"""
import ast
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
cl = importlib.import_module("ci_local")
fcp = importlib.import_module("forge_ci_proof")

SOURCE = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
ARBRE = ast.parse(SOURCE)


def _fonction(nom):
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.FunctionDef) and n.name == nom:
            return n
    raise AssertionError("fonction %s introuvable dans ci_local.py" % nom)


def _ecrit_la_preuve(stmt) -> bool:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
        return False
    f = stmt.value.func
    return isinstance(f, ast.Name) and f.id == "_ecrire_ci_proof"


def _sorties_non_couvertes(fn, garde):
    """Lignes des `return` retenus par `garde` qui ne sont PAS precedes d'une
    ecriture de preuve. Parcourt TOUS les blocs, pas seulement le corps."""
    nus = []

    def _bloc(corps):
        for i, s in enumerate(corps):
            if isinstance(s, ast.Return) and garde(s):
                if not (i and _ecrit_la_preuve(corps[i - 1])):
                    nus.append(s.lineno)
            for champ in ("body", "orelse", "finalbody"):
                sous = getattr(s, champ, None)
                if isinstance(sous, list):
                    _bloc(sous)
            for h in getattr(s, "handlers", []) or []:
                _bloc(h.body)

    _bloc(fn.body)
    return nus


# ─────────────────────────── 1. les SITES d'appel ───────────────────────────

def test_chaque_sortie_ROUGE_de_main_ecrit_sa_preuve():
    """`return 1` = la CI refuse. C'est precisement la que l'artefact manquait."""
    def _rouge(s):
        return isinstance(s.value, ast.Constant) and s.value.value == 1

    nus = _sorties_non_couvertes(_fonction("main"), _rouge)
    assert nus == [], (
        "return 1 sans ecriture de preuve, lignes %s — un run rouge ne laisserait "
        "aucun artefact, et l'absence de fichier redeviendrait la representation "
        "de l'echec" % nus)


def test_chaque_sortie_du_juge_ecrit_sa_preuve():
    """`_inscrire_generation` rend `None` sur TOUS ses refus : partiel, proof
    absent, tests hors proof, capture refusee. Aucune exception : une regle sans
    exception est un garde plus fort qu'une regle avec une liste blanche."""
    def _nu(s):
        return s.value is None

    nus = _sorties_non_couvertes(_fonction("_inscrire_generation"), _nu)
    assert nus == [], "return nu sans ecriture de preuve, lignes %s" % nus


def test_le_garde_MORD_si_on_retire_un_appel():
    """Contre-epreuve : sans elle, un detecteur qui ne trouve jamais rien passerait
    aussi bien sur un code sans aucun appel."""
    faux = ast.parse("def main():\n    if x:\n        return 1\n    return 0\n")
    fn = [n for n in faux.body if isinstance(n, ast.FunctionDef)][0]
    nus = _sorties_non_couvertes(
        fn, lambda s: isinstance(s.value, ast.Constant) and s.value.value == 1)
    assert nus, "le detecteur doit voir un return 1 nu, sinon il ne garde rien"


# ─────────────────── 2. la traversee REELLE jusqu'a l'artefact ───────────────

def _echantillon(stmt) -> bool:
    """Vrai si `stmt` EST un appel direct a `_telemetrie`.

    Pas « contient » : un appel enfoui dans une branche voisine ne garantit
    rien, puisque la branche peut ne pas s'executer. Un encadrement
    CONDITIONNEL n'est pas un encadrement — la contre-epreuve ci-dessous a
    trouve ce trou dans la premiere version de ce detecteur.
    """
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name)
            and stmt.value.func.id == "_telemetrie")


# Un statement COMPOSE contient le site d'appel sans etre le site d'appel.
# Defaut mesure le 2026-09-19 : la premiere version de ce detecteur rendait 8
# « blocs nus » dont 7 etaient des englobants (`def main`, `if present`, `for
# _chemin ...`) — elle mesurait la CONTENANCE, pas le SITE. Un instrument qui
# confond ce qu'il peut voir et ce qu'il pretend decrire fabrique des pannes.
_COMPOSES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With,
             ast.AsyncWith, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _lance_pytest(stmt) -> bool:
    """Vrai si `stmt` EST le site d'appel de `_run` pour un bloc de tests.

    On reconnait le bloc a son ETIQUETTE (1er argument litteral commencant par
    « pytest »), pas a la forme de la commande : un gate qui lancerait pytest
    sous un autre nom n'est pas un bloc de tests au sens de la preuve par bloc.
    """
    if isinstance(stmt, _COMPOSES):
        return False
    for n in ast.walk(stmt):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_run" and n.args
                and isinstance(n.args[0], (ast.Constant, ast.BinOp))):
            texte = ast.unparse(n.args[0])
            if texte.strip().strip("'\"").startswith("pytest"):
                return True
    return False


def test_chaque_bloc_de_tests_est_ENCADRE_par_la_telemetrie():
    """D — un echantillon qui n'est pas PRIS ne mesure rien.

    La sonde pourrait exister, etre juste, et n'etre jamais appelee : c'est une
    dette de cablage, jamais une instrumentation. Mesure qui motive D : meme
    sha, meme runtime certifiant, meme suite, 3 timeouts sur 4 runs avec une
    victime differente a chaque fois -- sans etat de la machine AUTOUR du bloc
    coupe, rien n'est attribuable.
    """
    nus = []
    for noeud in ast.walk(ARBRE):
        for champ in ("body", "orelse", "finalbody"):
            corps = getattr(noeud, champ, None)
            if not isinstance(corps, list):
                continue
            for i, stmt in enumerate(corps):
                if not _lance_pytest(stmt):
                    continue
                voisins = corps[max(0, i - 1):i] + corps[i + 1:i + 3]
                if not any(_echantillon(v) for v in voisins):
                    nus.append(getattr(stmt, "lineno", "?"))
    assert not nus, (
        "bloc(s) de tests lance(s) SANS echantillon encadrant, ligne(s) %s"
        % nus)


def test_le_garde_de_telemetrie_MORD_si_on_retire_l_encadrement():
    """Contre-epreuve : sans elle, un detecteur qui ne trouve jamais rien
    passerait pour une preuve d'encadrement."""
    faux = ast.parse(
        "def f():\n"
        "    _telemetrie('avant: x')\n"
        "    a = _run('pytest (suite pure)', cmd)\n"
        "    b = _run('pytest [isole] y', cmd)\n"
        "    if z:\n"
        "        _telemetrie('avant: w')\n"
        "        c = _run('pytest [isole] w', cmd)\n")
    nus = []
    for noeud in ast.walk(faux):
        corps = getattr(noeud, "body", None)
        if not isinstance(corps, list):
            continue
        for i, stmt in enumerate(corps):
            if not _lance_pytest(stmt):
                continue
            voisins = corps[max(0, i - 1):i] + corps[i + 1:i + 3]
            if not any(_echantillon(v) for v in voisins):
                nus.append(i)
    assert nus, ("le detecteur doit voir le second _run laisse NU -- un "
                 "echantillon place dans une branche voisine ne l'encadre pas")


def _sans_proof_worktree(monkeypatch, tmp_path):
    monkeypatch.setenv("NOKIDO_PROOF_DIR", str(tmp_path))
    monkeypatch.delenv("NOKIDO_PROOF_WORKTREE", raising=False)
    monkeypatch.setenv("NOKIDO_TARGET_SHA", "4e044668eabd")
    monkeypatch.setattr(cl, "_PROOF_DIR", None)
    monkeypatch.setattr(cl, "_ETAT_SUITE", None)


def test_le_juge_ecrit_une_preuve_NEGATIVE_quand_le_proof_manque(monkeypatch, tmp_path):
    """Chemin reel du CALLER : `_inscrire_generation` -> `_ecrire_ci_proof`.
    Avant ce correctif, ce chemin rendait `None` sans rien ecrire."""
    _sans_proof_worktree(monkeypatch, tmp_path)

    cl._inscrire_generation([("un-gate", True)], partiel=False)

    cible = tmp_path / "ci_proof.json"
    assert cible.is_file(), "aucune preuve ecrite sur le chemin PROOF_SETUP_FAILURE"
    m = json.loads(cible.read_text(encoding="utf-8"))
    assert m["schema_version"] == 2
    assert m["process_state"] == "NO_CAPTURE"
    assert "PROOF_SETUP_FAILURE" in (m["failure_stage"] or "")
    assert m["observed_head"] is None, \
        "sans capture on ne sait PAS quel arbre a tourne : le taire serait pretendre le savoir"
    assert m["target_sha"] == "4e044668eabd", "la cible DEMANDEE reste connue"
    assert not fcp.certifie(m)[0]


def test_un_run_PARTIEL_laisse_aussi_sa_trace(monkeypatch, tmp_path):
    """Sinon « pas de fichier » signifierait a la fois --fast et rien n'a tourne."""
    _sans_proof_worktree(monkeypatch, tmp_path)

    cl._inscrire_generation([("un-gate", True)], partiel=True)

    m = json.loads((tmp_path / "ci_proof.json").read_text(encoding="utf-8"))
    assert m["process_state"] == "NO_CAPTURE"
    assert "PARTIAL_RUN" in (m["failure_stage"] or "")


def test_aucun_repli_sur_l_arbre_juge(monkeypatch, tmp_path, capsys):
    """`PROOF_DIR` existe pour dissocier la preuve de l'arbre juge (defaut 09/09).
    Sans lui, on n'ecrit PAS — on ne se rabat pas sur le worktree."""
    monkeypatch.delenv("NOKIDO_PROOF_DIR", raising=False)
    monkeypatch.setattr(cl, "_PROOF_DIR", None)
    monkeypatch.setattr(cl, "_ETAT_SUITE", None)

    cl._ecrire_ci_proof("NO_CAPTURE", failure_stage="x",
                        ctx={"proof_root": str(tmp_path)})

    assert not (tmp_path / "ci_proof.json").exists()
    assert "NON ECRIT" in capsys.readouterr().out


def test_une_suite_COMPLETE_sans_capture_est_une_INCOHERENCE(monkeypatch, tmp_path):
    """L'etat de PREUVE prime sur l'etat de TEST, et la contradiction est DITE
    plutot que corrigee en douce."""
    _sans_proof_worktree(monkeypatch, tmp_path)
    monkeypatch.setattr(cl, "_ETAT_SUITE", "SUITE_COMPLETE")

    cl._inscrire_generation([("un-gate", True)], partiel=False)
    m = json.loads((tmp_path / "ci_proof.json").read_text(encoding="utf-8"))

    assert m["certification_state"] != "SUITE_COMPLETE"
    assert not fcp.certifie(m)[0]
