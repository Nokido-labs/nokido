# -*- coding: utf-8 -*-
"""Jeton des hooks Claude : coffre DPAPI, puis variable du PROCESSUS, puis rien.

Source unique de session_start et session_stop (cliquet clones, 4/11). Chaque hook prend SON marqueur,
FORGE_TOKEN_CLAUDE_HOOK (ring 4), jamais FORGE_TOKEN_CLAUDE (credential ring 1 d'un voisin) ni Nokido.env. Coffre d'abord
(regle DPAPI) ; la variable sert a l'injection voulue par un parent ; sans jeton, le hook se degrade et la session continue.
Les deux lectures restent dans UNE fonction : le repli n'a de sens qu'a cote du coffre. NR test_hooks_claude_jeton_coffre_seul_nr.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunite/jetons : jeton des hooks Claude, coffre puis variable du processus"

import os
import sys


def jeton_du_hook(racine) -> str:
    try:
        sys.path.insert(0, str(racine))
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        propre = get_secret("FORGE_TOKEN_CLAUDE_HOOK")
        if propre:
            return propre
    except Exception:  # muet-ok : coffre indisponible -> repli ci-dessous, un hook ne casse jamais la session
        pass
    return os.environ.get("FORGE_TOKEN_CLAUDE_HOOK", "")
