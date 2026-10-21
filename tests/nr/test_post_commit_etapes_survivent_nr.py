# -*- coding: utf-8 -*-
"""NR (19/10, owner « docset au commit + cliquet ») : une etape du post-commit qui echoue n'emporte plus les suivantes.

Mesure du 19/10 (sandbox/logs/post_commit.log) : depuis que les commits passent par le compte bac a sable, l'etape 3
`update_skill_md` leve PermissionError (docs/skills/nokido/JOURNAL_COMMITS.md non inscriptible) ; l'exception
remontait et tuait main() AVANT l'etape 4.5 -- derniere regeneration des cartes de modules le 17/10 23:01, 73 cartes
derivees sur 1 791, et les etapes 4.55 (instrumentation) et 4.6 (derive d'intentions) muettes elles aussi. Comme ses
voisines, l'etape SKILL.md est desormais non bloquante et DIT son echec.
"""
import logging
import sys
from pathlib import Path

from nokido_agent.tools import forge_post_commit as PC
from nokido_agent.tools import forge_module_cards as MC


def test_l_echec_de_skill_md_n_emporte_pas_les_cartes(monkeypatch, caplog):
    cible = Path(PC.ROOT) / "tools" / "forge_trace_import.py"
    monkeypatch.setattr(sys, "argv", ["forge_post_commit.py", "--no-rag"])
    monkeypatch.setattr(PC, "_get_commit_sha", lambda: "abc1234")
    monkeypatch.setattr(PC, "_get_commit_msg", lambda: "test")
    monkeypatch.setattr(PC, "get_changed_files", lambda commit="HEAD": [cible])
    monkeypatch.setattr(PC, "modules_a_instrumenter", lambda changed, *a, **k: [])
    import nokido_agent.tools.forge_pair_quarantaine as Q
    monkeypatch.setattr(Q, "entretenir", lambda *a, **k: {"clotures": [], "expires": [], "git": "ok"})

    def refuse(*a, **k):
        raise PermissionError(13, "Permission denied", "docs/skills/nokido/JOURNAL_COMMITS.md")
    monkeypatch.setattr(PC, "update_skill_md", refuse)
    vus = []
    monkeypatch.setattr(MC, "refresh_changed", lambda names: vus.append(list(names)) or len(names))
    with caplog.at_level(logging.WARNING):
        PC.main()
    assert vus == [["forge_trace_import.py"]]
    assert any("SKILL.md" in r.getMessage() and "PermissionError" in r.getMessage() for r in caplog.records)
