# -*- coding: utf-8 -*-
"""NR -- la file owner du pont ombre est DITE au demarrage de chaque session du CLI pilote.

Item SSoT p1_auto_amelioration_boucle_non_fermee. `forge_autonomous_loops.file_owner_ombre` (905401dc3) rend les
dossiers A_TRAITER dont le traitement revient a l'owner (ECART_DOC_CODE, RELANCE_OU_OWNER) ; elle etait DORMANTE --
seul son NR l'appelait. Enquete AGY job_06b6bdb4 (verifiee) : la seule surface vue a CHAQUE session sans action de
l'owner est tools/claude_session_start.py, sur le modele d'alerte_prs_dependabot.

Contrats :
  1. un dossier ECART_DOC_CODE A_TRAITER au dernier reexamen -> « [arbitrage] 1 dossier(s) owner ... » nommant
     le dossier et son traitement ;
  2. dernier reexamen RESOLU -> None (on n'invente pas de travail) ;
  3. registre absent ou illisible -> ILLISIBLE, jamais « rien » (UNKNOWN n'est pas NO) ;
  4. une ligne corrompue est comptee et DITE, les autres restent lues ;
  5. main() appelle l'alerte (chemin reel, lecture AST).
"""
import ast
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import claude_session_start as S  # noqa: E402


def _triage(dossier, treatment, verdict="A_TRAITER", ts="2026-10-18T10:00:00"):
    return {"kind": "triage", "dossier": dossier, "treatment": treatment, "organ": "o", "motif": "m", "ts": ts,
            "reexamen": {"verdict": verdict, "par_cible": {"cible": verdict}}}


def _ecrire(chemin, entrees, brut=()):
    chemin.write_text("\n".join([json.dumps(e) for e in entrees] + list(brut)) + "\n", encoding="utf-8")


def test_un_dossier_owner_est_dit(tmp_path):
    reg = tmp_path / "evolution_experiences.jsonl"
    _ecrire(reg, [_triage("doc1", "ECART_DOC_CODE"), _triage("mut1", "MUTATION_CODE_JUGEE")])
    texte = S.alerte_file_owner(reg)
    assert texte and texte.startswith("[arbitrage] 1 dossier(s) owner")
    assert "doc1" in texte and "ECART_DOC_CODE" in texte and "mut1" not in texte


def test_un_dossier_resolu_ne_dit_rien(tmp_path):
    reg = tmp_path / "evolution_experiences.jsonl"
    _ecrire(reg, [_triage("doc1", "ECART_DOC_CODE"),
                  _triage("doc1", "ECART_DOC_CODE", verdict="RESOLU", ts="2026-10-18T12:00:00")])
    assert S.alerte_file_owner(reg) is None


def test_registre_absent_est_illisible(tmp_path):
    texte = S.alerte_file_owner(tmp_path / "absent.jsonl")
    assert texte and "ILLISIBLE" in texte


def test_ligne_corrompue_comptee_et_dite(tmp_path):
    reg = tmp_path / "evolution_experiences.jsonl"
    _ecrire(reg, [_triage("doc1", "RELANCE_OU_OWNER")], brut=["{pas du json"])
    texte = S.alerte_file_owner(reg)
    assert "doc1" in texte and "1 ligne(s) illisible(s)" in texte


def test_main_appelle_l_alerte():
    arbre = ast.parse((RACINE / "tools" / "claude_session_start.py").read_text(encoding="utf-8", errors="replace"))
    main = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    assert any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "alerte_file_owner" for n in ast.walk(main))
