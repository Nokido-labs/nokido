"""NR -- les membres par defaut du swarm cloud ne contiennent ni client mort ni abonnement owner.

Mesure 2026-10-24 : registre des membres vivants perime -> repli sur DEFAULT_MEMBERS = claude_cli (abonnement, quota
owner), gemini_cli (client mort depuis le 04/07), groq, cerebras : 1 reponse utile sur 4. Le census exclut deja ces
fournisseurs du proxy (EXCLUS_PROXY, 3676d6e14) : une seule source de verite, le swarm la suit.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_cli_swarm as S  # noqa: E402
import forge_free_tier_census as C  # noqa: E402


def test_defaut_sans_exclus_du_census():
    exclus = set(C.EXCLUS_PROXY)
    assert not exclus & set(S.DEFAULT_MEMBERS), sorted(exclus & set(S.DEFAULT_MEMBERS))


def test_defaut_sans_client_mort_ni_abonnement():
    for mort in ("gemini_cli", "claude_cli", "codex_cli", "copilot_cli", "claude_agent_sdk"):
        assert mort not in S.DEFAULT_MEMBERS


def test_defaut_garde_au_moins_trois_membres():
    assert len(S.DEFAULT_MEMBERS) >= 3
