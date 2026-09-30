#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_mutation_test.py — mutation testing natif : tester les TESTS.

Un taux de couverture dit quelles lignes ont ete EXECUTEES, jamais si un test
aurait crie en cas d'erreur. Mesure du 2026-08-15 : `tests/nr/test_tous_modules_nr.py`
couvre 1138 modules avec deux invariants — PARSE et PAS DE DOUBLON — et le dit
lui-meme : « ils ne remplacent pas un test metier ». Une couverture de
surveillance, donc, qu'aucune mutation de comportement ne ferait rougir.

Principe : introduire UNE faute a la fois dans le code de production, relancer
les tests, et regarder s'ils protestent.
  * mutant TUE       -> un test a crie : cette ligne est vraiment protegee.
  * mutant SURVIVANT -> personne n'a rien vu : la ligne est couverte sur le
                        papier et libre en pratique.

Pourquoi natif plutot que mutmut : le reseau est ferme dans la sandbox
(WinError 10013) et `site-packages` n'est pas inscriptible, donc l'installation
atterrirait dans le user-site d'un compte de service — invisible du hub et de la
CI. C'est exactement ce qui a rendu le gate semgrep aveugle (voir
tools/forge_golden_rules_ast.py). Zero dependance, donc.

Usage :
    forge_mutation_test.py app/forge_videur.py --tests tests/nr/test_reliability_kernel_nr.py
    forge_mutation_test.py tools/forge_dup_detector.py --tests tests/nr/test_dup_detector_nr.py
    [--max-mutants 30] [--json]

SURETE : le fichier cible est REECRIT puis restaure. Il doit etre propre au sens
de git avant de commencer (sinon on ecraserait du travail non commite), et la
restauration est verifiee octet par octet en sortie, y compris apres erreur.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.path.insert(0, ROOT)
    from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON  # type: ignore
except Exception:  # noqa: BLE001 - repli documente : jamais `python` nu
    LAFORGE_PYTHON = os.path.expanduser(r"~\miniforge3\python.exe")

# Le chemin canonique peut ne pas EXISTER pour le compte courant : sous
# LaForgeTrusted, `~` vaut C:\Users\Default et le lancement echouait en
# `FileNotFoundError [WinError 2]`. L'interpreteur qui execute ce script, lui,
# existe forcement — et c'est le meme environnement que celui des tests.
_PY = LAFORGE_PYTHON if os.path.exists(LAFORGE_PYTHON) else sys.executable

# Operateurs de comparaison : l'erreur de frontiere est LA faute la plus
# frequente et la plus couteuse (un `<` pour un `<=` sur une expiration de
# jeton, et l'authentification laisse passer une seconde de trop).
_CMP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
        ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Is: ast.IsNot,
        ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In}
_BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}


class _Recenseur(ast.NodeVisitor):
    """Inventorie les sites mutables, sans rien modifier."""

    def __init__(self) -> None:
        self.sites: list[tuple[str, int, int]] = []  # (genre, id_noeud, ligne)
        self._n = 0

    def generic_visit(self, node: ast.AST) -> None:
        # L'identite d'un site est son RANG en parcours prefixe. Le recenseur et
        # le muteur doivent donc numeroter EXACTEMENT pareil : prendre le rang
        # avant de descendre, des deux cotes. Un decalage d'une seule unite, et
        # aucune cible ne correspond -- ce qui rendait « 0 mutant », un vert
        # aussi vide que celui du gate semgrep.
        self._n += 1
        ident = self._n
        genre = _genre(node)
        if genre:
            self.sites.append((genre, ident, getattr(node, "lineno", 0)))
        super().generic_visit(node)


def _genre(node: ast.AST) -> str:
    """Nature mutable d'un noeud, ou chaine vide s'il n'y a rien a fausser."""
    if isinstance(node, ast.Compare) and node.ops and type(node.ops[0]) in _CMP:
        return "comparaison"
    if isinstance(node, ast.BoolOp):
        return "et_ou"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return "negation"
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return "arithmetique"
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return "booleen"
    return ""


class _Muteur(ast.NodeTransformer):
    """Applique UNE seule mutation, celle du site vise."""

    def __init__(self, genre: str, cible: int) -> None:
        self.genre, self.cible, self._n = genre, cible, 0
        self.applique = False

    def generic_visit(self, node: ast.AST):
        self._n += 1
        ident = self._n
        node = super().generic_visit(node)
        if ident != self.cible:
            return node
        if self.genre == "comparaison" and isinstance(node, ast.Compare):
            node.ops[0] = _CMP[type(node.ops[0])]()
            self.applique = True
        elif self.genre == "et_ou" and isinstance(node, ast.BoolOp):
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            self.applique = True
        elif self.genre == "negation" and isinstance(node, ast.UnaryOp):
            self.applique = True
            return node.operand  # `not x` devient `x`
        elif self.genre == "arithmetique" and isinstance(node, ast.BinOp):
            node.op = _BIN[type(node.op)]()
            self.applique = True
        elif self.genre == "booleen" and isinstance(node, ast.Constant):
            node.value = not node.value
            self.applique = True
        return node


def _git_propre(rel: str) -> tuple[bool, str]:
    """(propre, motif). Un echec de git n'est PAS la preuve d'un fichier sale.

    Le script tourne sous un compte de service, ou git repond « detected dubious
    ownership » : confondre ce refus avec « fichier modifie » rendait le garde
    bloquant en permanence, pour une raison qui n'a rien a voir. `safe.directory`
    est pose par commande, jamais dans la config globale.
    """
    try:
        r = subprocess.run(["git", "-c", f"safe.directory={ROOT}",
                            "status", "--porcelain", "--", rel],
                           capture_output=True, text=True, errors="replace",
                           cwd=ROOT, timeout=60)
    except Exception as exc:  # noqa: BLE001 - git absent du PATH
        return False, f"git introuvable ({exc})"
    if r.returncode != 0:
        return False, f"git n'a pas pu repondre (rc={r.returncode}) : {(r.stderr or '').strip()[:200]}"
    if (r.stdout or "").strip():
        return False, "le fichier a des modifications non commitees"
    return True, ""


def _tests_passent(cmd_tests: list[str], timeout: int) -> tuple[bool, str]:
    """(vert, queue de sortie). La QUEUE est indispensable : sans elle, « la suite
    est deja rouge » est un verdict sans motif, et le cliquet de mutation est
    reste INDETERMINE en CI pendant des semaines sans que personne puisse savoir
    pourquoi (mesure 2026-08-18)."""
    r = subprocess.run(cmd_tests, capture_output=True, text=True,
                       errors="replace", cwd=ROOT, timeout=timeout)
    queue = ((r.stdout or "") + (r.stderr or "")).strip().replace("\n", " | ")[-400:]
    return r.returncode == 0, queue


def executer(cible: str, tests: str, max_mutants: int, timeout: int = 300) -> dict:
    chemin = cible if os.path.isabs(cible) else os.path.join(ROOT, cible)
    rel = os.path.relpath(chemin, ROOT).replace("\\", "/")
    # Les OCTETS d'origine, pas seulement le texte. `open` en mode texte traduit
    # les fins de ligne DANS LES DEUX SENS (a la lecture CRLF -> \n, a l'ecriture
    # \n -> CRLF sous Windows) : la restauration rendait donc un fichier au
    # contenu identique mais aux fins de ligne CONVERTIES. `git status` le voit
    # modifie, `_git_propre` refuse alors toute campagne suivante, et le cliquet
    # restait INDETERMINE apres son premier passage — un garde qui se sabote
    # lui-meme au premier usage (mesure 2026-08-19).
    # La verification d'apres-coup ne pouvait pas le voir : elle relisait en mode
    # texte, donc avec la traduction meme qu'elle aurait du detecter. Un
    # controle qui emprunte le canal fautif atteste toujours du succes.
    octets = open(chemin, "rb").read()
    original = octets.decode("utf-8")

    # Ecrire EST le geste central de la mutation. Sans ce droit, la premiere
    # ecriture leve PermissionError, le `finally` retente et leve a son tour :
    # le script meurt avec rc=1 -- exactement le code que le cliquet interprete
    # comme « NOUVELLE FAIBLESSE ». Un refus d'ACL se lisait donc comme une
    # regression de test. Mesure du 2026-08-18 : `LaForgeSbxOffline` n'a que
    # `(R)` sur `tools/`, donc TOUT job detache offline tombait la.
    # `os.access` ne suffit pas sous Windows (il ne lit que l'attribut
    # lecture-seule, pas l'ACL) : on ouvre reellement en `r+`, sans rien ecrire.
    try:
        with open(chemin, "r+", encoding="utf-8"):
            pass
    except OSError as exc:
        return {"cible": rel,
                "erreur": "fichier NON INSCRIPTIBLE sous le compte %s (%s) -- "
                          "la mutation ne peut pas avoir lieu, donc INDETERMINE, "
                          "surtout pas 'aucun survivant'"
                          % (os.environ.get("USERNAME", "?"), type(exc).__name__)}

    arbre = ast.parse(original, filename=chemin)

    rec = _Recenseur()
    rec.visit(arbre)
    sites = rec.sites[:max_mutants]

    # `--basetemp` : TEMP est PARTAGE entre comptes (owner, runner, services) et
    # pytest balaie les anciens `pytest-of-<user>` au demarrage -- il meurt en
    # PermissionError AVANT le premier test si le dossier appartient a un autre
    # compte. Lecon deja payee par le gate pytest de ci_local (2026-07-28) ; le
    # mutateur, lui, ne l'avait pas apprise et jugeait la suite « deja rouge ».
    # `NOKIDO_PROOF_DIR` en tete (2026-09-11) : quand un juge declare un repertoire
    # de preuve, aucune sortie temporaire ne doit rester dans l'arbre qu'il mesure.
    # Mesure de la CI de reference complete : `?? sandbox/pytest_mutation_tmp/`
    # subsistait dans le worktree juge. La liste blanche le tolerait -- `sandbox/`
    # est une sortie declaree -- mais une tolerance n'est pas une justification, et
    # l'arbre juge doit rester exclusivement le CODE juge.
    _rt = os.environ.get("NOKIDO_PROOF_DIR") or os.environ.get("RUNNER_TEMP")
    _btmp = os.path.join(_rt or os.path.join(ROOT, "sandbox"), "pytest_mutation_tmp")
    cmd = [_PY, "-m", "pytest", *tests.split(), "-q", "--no-header",
           "-x", "-p", "no:cacheprovider", "--basetemp=%s" % _btmp]

    # Un mutant SURVIVANT n'a de sens que si la suite est VERTE au depart :
    # sur une suite deja rouge, tout mutant serait « tue » par la panne d'a cote.
    vert, queue = _tests_passent(cmd, timeout)
    if not vert:
        return {"cible": rel,
                "erreur": "la suite de tests est DEJA rouge sans mutation -- aucun "
                          "verdict de mutation n'aurait de sens. Sortie : " + queue}

    if not sites:
        return {"cible": rel, "erreur": "aucun site mutable trouve — un rapport de "
                                        "mutation sans mutant ne prouve rien"}

    tues, survivants = 0, []
    try:
        for genre, ident, ligne in sites:
            muteur = _Muteur(genre, ident)
            mute = muteur.visit(ast.parse(original, filename=chemin))
            if not muteur.applique:
                continue
            ast.fix_missing_locations(mute)
            try:
                source = ast.unparse(mute)
            except Exception:  # noqa: BLE001 - mutation non reecrivable
                continue
            open(chemin, "w", encoding="utf-8").write(source)
            try:
                survit, _ = _tests_passent(cmd, timeout)
            except subprocess.TimeoutExpired:
                survit = False  # boucle infinie induite = faute detectee
            if survit:
                survivants.append({"genre": genre, "ligne": ligne})
            else:
                tues += 1
    finally:
        # Restauration inconditionnelle, puis VERIFICATION : un outil qui laisse
        # une mutation dans le depot est pire que pas d'outil du tout.
        with open(chemin, "wb") as _fh:
            _fh.write(octets)
        if open(chemin, "rb").read() != octets:
            raise SystemExit(f"CRITIQUE: {rel} n'a PAS ete restaure -- git checkout -- {rel}")

    total = tues + len(survivants)
    return {"cible": rel, "tests": tests, "mutants": total, "tues": tues,
            "survivants": survivants,
            "score": round(100.0 * tues / total, 1) if total else None}


def main() -> int:
    ap = argparse.ArgumentParser(description="Mutation testing natif Nokido")
    ap.add_argument("cible", help="module de production a muter")
    ap.add_argument("--tests", required=True, help="cible pytest (fichier ou expression)")
    ap.add_argument("--max-mutants", type=int, default=30)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rel = os.path.relpath(
        args.cible if os.path.isabs(args.cible) else os.path.join(ROOT, args.cible),
        ROOT).replace("\\", "/")
    propre, motif = _git_propre(rel)
    if not propre:
        print(f"ABORT: {rel} — {motif}. Ce script REECRIT le fichier ; il exige "
              "un etat propre et verifiable pour pouvoir le restaurer.")
        return 2

    res = executer(args.cible, args.tests, args.max_mutants, args.timeout)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if res.get("erreur"):
        print("ABORT: " + res["erreur"])
        return 3
    print(f"[mutation] {res['cible']} — {res['mutants']} mutants, "
          f"{res['tues']} tues, {len(res['survivants'])} survivants "
          f"(score {res['score']}%)")
    for s in res["survivants"][:25]:
        print(f"  SURVIVANT  {res['cible']}:{s['ligne']}  ({s['genre']})")
    if res["survivants"]:
        print("  ^ ces lignes sont couvertes par les tests mais pas PROTEGEES : "
              "les modifier ne fait rougir personne.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
