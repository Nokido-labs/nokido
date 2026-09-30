# -*- coding: utf-8 -*-
"""NR — la commande injectee dans le terminal doit rejoindre l'historique (fleche haut).

Apres une injection, `dispatch_ai` pousse la commande et ses alternatives dans la
file d'autocompletion du terminal. Quand le moteur n'est pas deja memorise sur
`app`, il le cherchait par `app.query_one("#chat-input", AutocompleteInput)` --
classe du monolithe jamais liee dans l'extrait : NameError avale, moteur `None`,
et aucune suggestion n'etait enregistree. Releve par l'audit « noms non definis »
(mesures/audits/noms_non_definis.md).

Correctif : `_g("AutocompleteInput")`, comme `forge_events` (l.140). Test
statique : le chemin demande la TUI Textual et un terminal SSH.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_la_classe_du_champ_de_saisie_est_liee():
    assert "AutocompleteInput" not in noms_globaux_non_lies("app/forge_dispatch_ai.py", "dispatch_ai")
