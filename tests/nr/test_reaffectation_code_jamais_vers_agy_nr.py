# -*- coding: utf-8 -*-
"""NR -- une tache d'un agent DELEGUE (OpenCode*, CODEX, MISTRAL : du code) n'est jamais reaffectee a AGY.

Mesure du 18/10 : job_cec98d75 assignee a OPENCODE_DEFAUT2 ; son worktree n'existe pas (creation = geste owner) ->
`_reaffecter(task, "... autonome INDISPONIBLE ...")` SANS `ordre` -> repli sur `_ORDRE_REPLI`, qui commence par
ANTIGRAVITY -> AGY a « livre » du code dont il n'a lance aucun test (sa sandbox ne lance pas de commande), commit
1edb516b8 rejete a la relecture. Les autres sites passent deja `ordre=_palier_executeurs("M", ecrit=True)`
(OpenCode qui ecrivent, jamais AGY).

Contrat (lecture AST du chemin reel) : les appels a `_reaffecter` dont le motif parle d'un agent delegue
(« autonome INDISPONIBLE », « quota Codex ») passent un `ordre` ; et ce palier « ecrit » ne contient pas ANTIGRAVITY.
"""
import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SRC = RACINE / "tools" / "forge_task_executor.py"


def _appels_delegues():
    texte = SRC.read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(texte)
    out = []
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_reaffecter" and len(n.args) >= 2:
            motif = ast.get_source_segment(texte, n.args[1]) or ""
            if "autonome INDISPONIBLE" in motif or "quota Codex" in motif:
                out.append((n.lineno, {k.arg for k in n.keywords}))
    return out


def test_les_reaffectations_d_agents_delegues_passent_un_ordre():
    appels = _appels_delegues()
    assert len(appels) >= 2, "sites introuvables : le NR ne mesurerait rien (%r)" % appels
    sans_ordre = [ligne for ligne, kws in appels if "ordre" not in kws]
    assert not sans_ordre, "lignes %s : repli sur _ORDRE_REPLI (AGY en tete) pour une tache de code" % sans_ordre


def test_le_palier_qui_ecrit_exclut_agy():
    for p in (str(RACINE), str(RACINE / "tools")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import forge_task_executor as X  # noqa: PLC0415
    assert "ANTIGRAVITY" not in X._palier_executeurs("M", ecrit=True)
