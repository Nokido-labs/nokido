# -*- coding: utf-8 -*-
"""NR -- Mistral Vibe autonome ne passe plus sa session a lire des skills (question owner 18/10 « pourquoi vibe ne marche pas ? »).

Mesure du 18/10 23:08-23:10 (sandbox/harness_jobs/vibe_job_9aca3c9a_*.result.json) : mode programmatique OK
(--prompt-file, correctif 6e688cb7f du 17/10), mais 62 appels d'outils = 31 `skill.read` + 31 `read_file`, presque
tous sur les skills du worktree (.agents/skills : forge-code-governance, forge-tdd, nokido/SKILL.md de 2000 lignes)
et celles des plugins Vibe (create-plugin) ; le fichier vise n'a JAMAIS ete ouvert ; --max-turns 30 epuise ; le
dernier message est une skill recopiee. 6e livraison vide.

Contrat : les arguments de Vibe desactivent l'outil de lecture de skills, en plus des shells deja retires.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as X  # noqa: E402


def _desactives(args):
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == "--disabled-tools"]


def test_vibe_ne_lit_plus_les_skills():
    d = _desactives(X._args_vibe("C:/wt", "C:/p.md"))
    assert any(x.startswith("skill") for x in d), d


def test_les_shells_restent_retires():
    d = _desactives(X._args_vibe("C:/wt"))
    assert {"bash*", "git_bash*", "powershell*"} <= set(d)
