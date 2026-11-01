"""Tests non-regression pour le cloisonnement du coffre et RBAC (S3).

Verifie :
S3. forge_mcp_rbac :
    - mapping outil secret -> IntegrityRing :
      * secret accessible uniquement en DEV (ring 1).
    - Verification d'absence d'escalade : un appelant UNTRUSTED (ring 4) ou COLLAB (ring 3)
      ne peut pas invoquer secret au niveau RBAC (check_tool_capability).
"""

from __future__ import annotations

import pytest

from nokido_agent.app.forge_mcp_rbac import (
    check_tool_capability,
    tool_required_ring,
    IntegrityRing,
    _TOOL_REQUIRED_RING,
)


def test_s3_rbac_secret_protection():
    """secret exige DEV (ring 1).

    Un appelant UNTRUSTED (ring 4) ou COLLAB (ring 3) ne doit PAS pouvoir
    l'invoquer au niveau RBAC.
    """
    # app/forge_mcp_rbac.py:172 → ('secret', 1)
    assert _TOOL_REQUIRED_RING.get("secret") == int(IntegrityRing.DEV)
    assert tool_required_ring("secret") == int(IntegrityRing.DEV)

    # Ring 1 (DEV) : autorise
    allowed_r1, _ = check_tool_capability("secret", agent="dev_agent", ring=int(IntegrityRing.DEV))
    assert allowed_r1 is True

    # Ring 2 (TRUSTED) : refuse
    allowed_r2, reason_r2 = check_tool_capability("secret", agent="trusted_agent", ring=int(IntegrityRing.TRUSTED))
    assert allowed_r2 is False
    assert "insufficient ring" in reason_r2

    # Ring 3 (COLLAB) : refuse
    allowed_r3, reason_r3 = check_tool_capability("secret", agent="collab_agent", ring=int(IntegrityRing.COLLAB))
    assert allowed_r3 is False
    assert "insufficient ring" in reason_r3

    # Ring 4 (UNTRUSTED) : refuse
    allowed_r4, reason_r4 = check_tool_capability("secret", agent="untrusted_agent", ring=int(IntegrityRing.UNTRUSTED))
    assert allowed_r4 is False
    assert "insufficient ring" in reason_r4