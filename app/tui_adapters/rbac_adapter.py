"""Adapter RBAC — lecture seule forge_rbac_mapping."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent


def list_mappings_safe() -> list[dict]:
    """Wrapper qui ne crashe pas si DB absente. Édition reste web :7400/rbac."""
    try:
        sys.path.insert(0, str(_ROOT))
        from nokido_agent.app import forge_rbac_mapping as fm

        return fm.list_mappings()
    except Exception:
        return []
