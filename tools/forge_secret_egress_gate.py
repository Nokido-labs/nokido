#!/usr/bin/env python3
"""__FORGE_COLOR__ = 'immunitaire/egress'

forge_secret_egress_gate — detecte les chemins ou une VALEUR de secret peut
partir en sortie : print, logging, exception, f-string, formatage.

POURQUOI CE GARDE EXISTE
========================
Le 2026-09-21, dans une sonde de diagnostic que j'ecrivais moi-meme, j'ai ecrit
`print(resolve(NOM))`. `forge_key_rotation.resolve` rend `(managed, key)` : la
VALEUR de la cle est partie vers la sortie. Le firewall du hub l'a masquee
(`[BASE64_SUSPECT_1]`) et rien n'a fuite.

Mais le garde de production n'est pas une excuse pour l'instrument. Un NR joue
sous pytest, un outil d'audit s'execute en CI locale, un script de diagnostic
tourne dans une console : AUCUN de ces chemins ne traverse le firewall du hub.
La meme ligne, jouee par `pytest`, aurait imprime la cle en clair.

    INVARIANT : aucun NR, outil d'audit, diagnostic, exception ou sortie CLI
    ne doit pouvoir emettre une valeur secrete -- MEME quand le garde de
    production la masquerait.

CE QUE CE GARDE N'EST PAS
=========================
Il ne remplace pas le scan de SECRETS EN DUR du pre-commit, qui cherche des
LITTERAUX. Ici la valeur n'existe qu'au runtime : aucun scan de texte ne peut
la voir. On ne cherche donc pas un secret, on cherche un CHEMIN.

Et il ne pretend pas etre complet : une valeur passee par trois variables
intermediaires lui echappe. Il attrape l'appel DIRECT en sortie, qui est la
faute reelle qui a ete commise. Une couverture partielle qui le DIT vaut mieux
qu'une exhaustivite supposee.

LE FAUX POSITIF QU'IL EVITE, ET POURQUOI IL EST NOMME
=====================================================
`resolve` est aussi `pathlib.Path.resolve`. Le meme jour, un recensement a moi
a compte 1956 « sites » dont 1955 etaient des `Path(__file__).resolve()`. Ce
garde ne compte donc `resolve` que comme NOM NU (`resolve(...)`), jamais comme
attribut (`X.resolve()`). Un garde qui crie a faux se fait desarmer.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent

# Fonctions dont la valeur de retour EST (ou contient) un secret.
# `resolve` rend un tuple (managed, key) -- d'ou son inclusion.
RENDENT_UN_SECRET = frozenset({
    "get_secret", "vault_get", "_secret", "resolve", "healthy_key",
    "_machine_vault", "_wcm", "_dotenv", "_hmac_key",
})
# `sign_identity` a d'abord figure ici : c'etait FAUX. Il rend une SIGNATURE,
# qui est faite pour etre publiee -- c'est `_hmac_key`, la cle qui la produit,
# qui est le secret. Premier passage du garde sur le depot : 3 findings, 3 faux
# positifs, dont celui-la. Le corriger AVANT de le cabler, parce qu'un garde
# qui crie a faux se fait desarmer.
# Celles qui portent un homonyme courant et ne comptent qu'en NOM NU.
AMBIGUES = frozenset({"resolve"})

SORTIES = frozenset({"print", "warn", "warning", "info", "error", "debug",
                     "critical", "exception", "log", "write", "echo"})

# REDUCTEURS : ce qui sort d'eux ne permet pas de reconstituer la valeur.
# Sans eux le garde signalerait `print(_fp(get_secret(k)))` -- c'est-a-dire
# exactement le REMEDE qu'il recommande. Un garde qui condamne son propre
# remede n'est pas applicable, et se fait desarmer dans la semaine.
# `str` et `list` n'en sont PAS : ils preservent la valeur.
REDUCTEURS = frozenset({"_fp", "bool", "len", "hash", "sha256", "md5",
                        "masquer", "type", "id", "isinstance", "any", "all"})


class _Visiteur(ast.NodeVisitor):
    """Repere un appel « qui rend un secret » DANS un appel « qui sort »."""

    def __init__(self, rel: str):
        self.rel = rel
        self.trouves: list = []

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _nom_appele(node: ast.Call):
        f = node.func
        if isinstance(f, ast.Name):
            return f.id, False           # nom nu
        if isinstance(f, ast.Attribute):
            return f.attr, True          # attribut : X.attr(...)
        return None, False

    def _secret_dedans(self, node) -> str | None:
        """Nom de la fonction-secret sous `node`, en s'arretant aux REDUCTEURS.

        Descente MANUELLE et non `ast.walk`, precisement pour pouvoir ne pas
        entrer dans une branche reduite : sous `_fp(...)` ou `bool(...)`, la
        valeur ne ressort plus, et ce qui s'y trouve ne nous regarde pas.
        """
        if isinstance(node, ast.Compare):
            # `get_secret(k) == url` rend un BOOLEEN. Mesure du 2026-09-21 :
            # `print("relecture %s" % ("CONFORME" if get_secret(k) == url
            # else "DIVERGENTE"))` etait signale a tort -- la valeur sert de
            # comparande, elle ne sort pas.
            return None
        if isinstance(node, ast.IfExp):
            # Le TEST d'un ternaire ne sort pas ; ses BRANCHES, si.
            for branche in (node.body, node.orelse):
                trouve = self._secret_dedans(branche)
                if trouve:
                    return trouve
            return None
        if isinstance(node, ast.Call):
            nom, est_attr = self._nom_appele(node)
            if nom in REDUCTEURS:
                return None              # la valeur ne sort pas d'ici
            if nom in RENDENT_UN_SECRET and not (nom in AMBIGUES and est_attr):
                return nom               # `Path(...).resolve()` exclu ici
        for enfant in ast.iter_child_nodes(node):
            trouve = self._secret_dedans(enfant)
            if trouve:
                return trouve
        return None

    # -- visite ------------------------------------------------------------
    def visit_Call(self, node: ast.Call):
        nom, _attr = self._nom_appele(node)
        if nom in SORTIES:
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                dedans = self._secret_dedans(arg)
                if dedans:
                    self.trouves.append((node.lineno, nom, dedans))
                    break
        self.generic_visit(node)

    # PAS de `visit_JoinedStr`. Une f-string n'est pas une sortie : elle
    # CONSTRUIT une chaine. Mesure du 2026-09-21 :
    # `f"Bearer {get_secret('FORGE_MCP_TOKEN')}"` batissait un en-tete HTTP --
    # l'usage exactement prevu, signale a tort.
    # Une f-string passee a `print`/`logger` est deja attrapee par `visit_Call`,
    # qui descend dans ses arguments. Une f-string rangee dans une variable
    # puis sortie plus loin echappe : c'est la COUVERTURE PARTIELLE annoncee.


def analyser_source(source: str, rel: str = "<memoire>") -> list:
    """[(ligne, sortie, fonction_secret)] — sur du TEXTE, testable sans fichier."""
    try:
        arbre = ast.parse(source)
    except SyntaxError:
        return []
    v = _Visiteur(rel)
    v.visit(arbre)
    return v.trouves


def analyser(chemins) -> tuple:
    """(findings, stats). Un fichier illisible est COMPTE, jamais ignore."""
    findings, lus, illisibles = [], 0, []
    for p in chemins:
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            illisibles.append("%s (%s)" % (p.name, type(e).__name__))
            continue
        lus += 1
        rel = str(p.relative_to(RACINE)).replace("\\", "/")
        if rel == "tools/forge_secret_egress_gate.py":
            continue                     # un instrument ne se lit pas lui-meme
        for ln, sortie, secret in analyser_source(src, rel):
            findings.append((rel, ln, sortie, secret))
    return findings, {"lus": lus, "illisibles": illisibles}


def _cibles(portees) -> list:
    out = []
    for sous in portees:
        d = RACINE / sous
        if d.is_dir():
            out.extend(sorted(d.glob("*.py")))
            out.extend(sorted(d.glob("*/*.py")))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("--portees", nargs="*", default=["tools", "tests"],
                    help="repertoires a scanner (defaut : tools tests)")
    ap.add_argument("--strict", action="store_true",
                    help="rc=1 s'il reste un chemin d'emission")
    a = ap.parse_args(argv)

    findings, st = analyser(_cibles(a.portees))
    print("portees : %s | %d fichier(s) lu(s) | %d ILLISIBLE(s)"
          % (" ".join(a.portees), st["lus"], len(st["illisibles"])))
    for x in st["illisibles"]:
        print("   ILLISIBLE %s  (son etat est INCONNU, pas sain)" % x)
    if not findings:
        print("\naucun chemin d'emission directe trouve.")
        print("COUVERTURE PARTIELLE, et c'est dit : une valeur passee par des")
        print("variables intermediaires echappe a ce garde. Il attrape l'appel")
        print("DIRECT en sortie -- la faute reellement commise le 2026-09-21.")
        return 0
    print("\n%d chemin(s) ou une VALEUR de secret peut partir en sortie :\n"
          % len(findings))
    for rel, ln, sortie, secret in findings:
        print("  %s:%d  %s(... %s(...) ...)" % (rel, ln, sortie, secret))
    print("\nRemede : ne sortir que l'EMPREINTE (`_fp`), un booleen de presence,")
    print("ou un compte. Jamais la valeur, meme tronquee.")
    return 1 if a.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
