# -*- coding: utf-8 -*-
"""NR — `@ollama status` ne doit pas declarer Ollama hors ligne a tort.

La sous-commande interroge `settings.ollama_tags_url`, mais `settings` n'est pas
lie dans `handle_at_ollama` (global du monolithe) : NameError dans le `try`,
rattrape en « ❌ Ollama hors ligne : name 'settings' is not defined » -- meme
quand Ollama tourne. Un diagnostic qui ment sur l'etat qu'il est cense mesurer.
Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).

Correctif : `settings = get_settings()` (forge_app_context), comme `handle_at_ssh`.
Test statique : le chemin demande un serveur Ollama.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_les_reglages_du_statut_ollama_sont_lies():
    assert "settings" not in noms_globaux_non_lies("app/forge_at_dispatch.py", "handle_at_ollama")
