"""NR 18/10 -- defaut d'orchestration n°2 MESURE : 90bc00bee (correctif archive, GPTOSS) = « commit executeur de 8
fichier(s) » pour une consigne qui en autorisait 2 : les restes de deux taches coupees par timeout sont entres dans le
commit. `_committer_pour_agent` sait exclure ce qui etait sale AVANT la tache (`exclus`, 16/10), mais seul le chemin AGY
le lui passait ; Codex, MISTRAL et les instances OpenCode committaient tout le worktree.

Contrat : CHAQUE appel a `_committer_pour_agent` passe `exclus=` (l'etat sale releve avant de lancer l'agent).
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "tools" / "forge_task_executor.py").read_text(
    encoding="utf-8", errors="replace")


def test_chaque_commit_executeur_exclut_les_fichiers_sales_d_avant_la_tache():
    # Une ligne par appel (les arguments contiennent eux-memes des parentheses : un motif [^)]* coupait trop tot).
    appels = [(n, l) for n, l in enumerate(SRC.splitlines(), 1)
              if "_committer_pour_agent(" in l and not re.match(r"\s*def ", l)]
    assert len(appels) >= 4, "instrument : moins de 4 appels vus, le motif ne suit plus le code"
    fautifs = [n for n, l in appels if "exclus=" not in l]
    assert not fautifs, "appel(s) sans exclus= (le commit balaierait le worktree) aux lignes %s" % fautifs
