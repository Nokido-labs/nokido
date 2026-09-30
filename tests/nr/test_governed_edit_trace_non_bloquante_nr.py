"""NR -- la trace d'une ecriture CRITIQUE ne passe plus par stderr (2026-09-28).

Mesure du 2026-09-28 06:23:08 : WEDGE KILL du hub (logs/loop_lag.log), event-loop gelee
60 s. Pile du fil de la boucle : `mcp_post` -> `handle_governed_edit` ->
`governed_write`, ligne de la trace `print(..., file=sys.stderr, flush=True)`.
`governed_write` tourne SUR la boucle ; le stderr du hub est un pipe vers le superviseur,
qui peut ne pas etre vide : une ecriture synchrone y bloque, et le garde anti-gel tue le
hub. Toute derogation `allow_critical` pouvait donc abattre le hub.

Ce que ce NR verrouille :
  - `governed_write` n'ecrit jamais sur `sys.stderr` ;
  - la derogation est tracee dans un JOURNAL fichier (`sandbox/governed_edit_critique.jsonl`) ;
  - une derogation qu'on ne peut pas tracer est REFUSEE, jamais accordee en silence.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = (ROOT / "tools" / "forge_governed_edit.py").read_text(encoding="utf-8")


def _governed_write():
    for n in ast.walk(ast.parse(SRC)):
        if isinstance(n, ast.FunctionDef) and n.name == "governed_write":
            return n
    raise AssertionError("governed_write introuvable")


def _ecrit_sur_stderr(noeud) -> bool:
    for n in ast.walk(noeud):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "print":
            for kw in n.keywords:
                if kw.arg == "file" and "stderr" in ast.unparse(kw.value):
                    return True
        if isinstance(n, ast.Attribute) and n.attr == "write" and "stderr" in ast.unparse(n.value):
            return True
    return False


def test_governed_write_n_ecrit_jamais_sur_stderr():
    assert not _ecrit_sur_stderr(_governed_write()), (
        "ecriture synchrone sur stderr dans governed_write : elle gele la boucle du hub")


def test_la_derogation_critique_est_tracee_dans_un_journal():
    corps = ast.unparse(_governed_write())
    assert "governed_edit_critique.jsonl" in corps


def test_une_derogation_non_tracee_est_refusee():
    corps = ast.unparse(_governed_write())
    assert "NON tracee" in corps, "l'echec de la trace doit refuser la derogation"
