"""NR : `token_usage` n'a QU'UN SEUL proprietaire — P0-A A3.

Regle arretee par l'owner le 2026-09-12 :

    UNIQUE_WRITER(token_usage) = forge_token_monitor.log_call

Pourquoi la liste des verbes ne s'arrete pas a INSERT : on peut retirer les
cinq `INSERT` et laisser un writer secondaire muter la table autrement. UPDATE,
DELETE, CREATE et ALTER sont donc surveilles au meme titre. Un `ALTER TABLE`
depuis un ADAPTER est le cas reel qui a motive la regle : un module cense
normaliser des formats fournisseurs n'a aucune raison de toucher la base.

Mesure du 2026-09-12 (inventaire A1) : 6 ecrivains, dont 5 vers
`embeddings.db` et 1 vers `m2m.db` — la destination n'etait pas une decision,
c'etait un accident reparti sur six fichiers. Tant que l'ecriture est
dupliquee, le contrat de provenance devrait etre re-pose a chaque site, et il
se re-fracturerait au premier ajout.

DEUX GARDES CONTRE LE FAUX VERT, sans lesquels ce NR passerait au vert le jour
ou l'instrument casse :
  - le scan doit VOIR des fichiers (denominateur affirme) ;
  - le proprietaire doit LUI-MEME ecrire (temoin positif) : un depot ou plus
    personne n'ecrit satisferait « aucun writer hors du proprietaire ».
Et un fichier illisible ou non parsable FAIT ECHOUER : on ne peut pas affirmer
l'unicite sur un corpus qu'on n'a pas pu lire entierement.
"""
import ast
import re
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les app/*.py
#   et tools/*.py (l.111)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
PROPRIETAIRE = "app/forge_token_monitor.py"
TABLE = "token_usage"
# Clauses SQL COMPLETES, et rien d'autre. Trois versions ont ete necessaires,
# chacune payee par une mesure du 2026-09-12 :
#   1. `INSERT INTO` litteral -> ratait `INSERT OR IGNORE INTO` (la forme du
#      proprietaire lui-meme), donc le temoin positif declarait qu'il n'ecrivait
#      plus. Un instrument qui SOUS-detecte ne rend pas un NR prudent : il rend
#      un faux vert des que les writers emploient la forme qu'il ignore.
#   2. Verbes nus + presence de la table -> deux FAUX POSITIFS : une docstring
#      disant "Journaux INSERT-only" puis citant le FICHIER
#      `sandbox/token_usage.db` (qui porte la table `token_events`, sans rapport)
#      etait comptee comme une ecriture. Un instrument ne doit pas inferer
#      depuis de la PROSE -- meme raison qui a fait retirer le filet docstring
#      du census d'organes.
# D'ou : la table doit suivre un mot-cle SQL, et les docstrings sont exclues.
_CLAUSES = (
    ("INSERT", r"\b(?:INSERT|REPLACE)\b(?:\s+OR\s+\w+)?\s+INTO\s+TOKEN_USAGE\b"),
    ("UPDATE", r"\bUPDATE\s+TOKEN_USAGE\b"),
    ("DELETE", r"\bDELETE\s+FROM\s+TOKEN_USAGE\b"),
    ("CREATE TABLE", r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?TOKEN_USAGE\b"),
    ("ALTER TABLE", r"\bALTER\s+TABLE\s+TOKEN_USAGE\b"),
    ("DROP TABLE", r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?TOKEN_USAGE\b"),
)
_CLAUSES = tuple((nom, re.compile(motif)) for nom, motif in _CLAUSES)


def _verbe_mutant(texte):
    """Le verbe d'une clause SQL mutante VISANT la table, ou None.

    `SELECT ... FROM token_usage` et la mention d'un fichier nomme
    `token_usage.db` ne sont pas des mutations : la table doit suivre
    immediatement un mot-cle SQL.
    """
    u = " ".join(texte.upper().split())
    if TABLE.upper() not in u:
        return None
    for nom, motif in _CLAUSES:
        if motif.search(u):
            return nom
    return None


def _docstrings(arbre):
    """Les noeuds de docstring, a EXCLURE : de la prose n'est pas du SQL."""
    vus = set()
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            corps = getattr(n, "body", None)
            if (corps and isinstance(corps[0], ast.Expr)
                    and isinstance(corps[0].value, ast.Constant)
                    and isinstance(corps[0].value.value, str)):
                vus.add(id(corps[0].value))
    return vus


def _chaines(arbre):
    """Chaines litterales, f-strings comprises, docstrings EXCLUES."""
    prose = _docstrings(arbre)
    for n in ast.walk(arbre):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if id(n) in prose:
                continue
            yield n.lineno, n.value
        elif isinstance(n, ast.JoinedStr):
            morceaux = [v.value for v in n.values
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            if morceaux:
                yield n.lineno, " ".join(morceaux)


def _scanner(inclure_proprietaire=False):
    """(violations, vus, illisibles) — trois etats, jamais deux."""
    violations, vus, illisibles = [], 0, []
    for dossier in ("app", "tools"):
        racine = RACINE / dossier
        if not racine.is_dir():
            illisibles.append((dossier, "DOSSIER ABSENT"))
            continue
        for p in sorted(racine.glob("*.py")):
            rel = "%s/%s" % (dossier, p.name)
            if rel == PROPRIETAIRE and not inclure_proprietaire:
                continue
            if inclure_proprietaire and rel != PROPRIETAIRE:
                continue
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                illisibles.append((rel, type(e).__name__))
                continue
            vus += 1
            if TABLE not in src:
                continue
            try:
                arbre = ast.parse(src)
            except SyntaxError as e:
                illisibles.append((rel, "SyntaxError l.%s" % e.lineno))
                continue
            for ligne, texte in _chaines(arbre):
                v = _verbe_mutant(texte)
                if v:
                    violations.append((rel, ligne, v))
    return violations, vus, illisibles


def test_le_scan_voit_reellement_le_depot():
    _, vus, illisibles = _scanner()
    assert vus > 500, (
        "denominateur trop faible (%d fichiers lus) : l'instrument ne voit pas "
        "le depot, un vert ne prouverait rien" % vus)
    assert not illisibles, (
        "fichiers illisibles ou non parsables : %r — l'unicite ne peut pas "
        "etre affirmee sur un corpus partiellement lu" % illisibles)


def test_le_proprietaire_ecrit_bien_lui_meme():
    """Temoin positif : sans lui, un depot ou plus personne n'ecrit passerait."""
    violations, _, _ = _scanner(inclure_proprietaire=True)
    verbes = {v for _, _, v in violations}
    assert "INSERT" in verbes, (
        "%s n'ecrit plus dans %s : le NR mesurerait alors le vide"
        % (PROPRIETAIRE, TABLE))


def test_aucun_ecrivain_hors_du_proprietaire():
    violations, _, _ = _scanner()
    detail = "\n".join("  %s:%s  %s" % v for v in violations)
    assert not violations, (
        "UNIQUE_WRITER(%s) = %s est viole par %d site(s) :\n%s\n"
        "Tout DDL/DML sur cette table passe par le recorder canonique ; un "
        "adapter ou un broker qui ecrit re-fracture la provenance."
        % (TABLE, PROPRIETAIRE, len(violations), detail))
