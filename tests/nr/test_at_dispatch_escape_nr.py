# -*- coding: utf-8 -*-
"""NR — les handlers `@` de forge_at_dispatch doivent pouvoir afficher leurs erreurs.

Six chemins d'erreur (@ssh save, reconnexion @ssh, @scan, alertes @ids, @agentic,
@evolve) appelaient `escape(...)` -- `rich.markup.escape` -- que le module
n'importait pas : le monolithe l'importait, l'extrait non. Chaque `except` levait
donc NameError a son tour : le message d'erreur disparaissait, et dans les taches
`create_task` la tache mourait sans rien afficher. Les alertes IDS (callback
`_ids_alert`) etaient toutes perdues ainsi. Releve par l'audit « noms non
definis » (mesures/audits/noms_non_definis.md).

Test statique : ces chemins demandent la TUI, SSH, nmap, scapy...
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_non_lies_du_module  # noqa: E402


def test_escape_est_lie_dans_tout_le_module():
    assert "escape" not in noms_non_lies_du_module("app/forge_at_dispatch.py")
