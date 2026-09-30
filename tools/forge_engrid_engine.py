"""
tools/forge_engrid_engine.py — Re-export depuis app/
=====================================================
Le moteur Engrid réside dans app/ pour rester dans le path Nokido.
Ce fichier permet l'import depuis tools/ (compatibilité spec).
"""

import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from app.forge_engrid_engine import (  # noqa: F401
    CognitiveShard,
    CycleResult,
    ForgeEngridEngine,
    ShardLatencyEntry,
)

__all__ = ["ForgeEngridEngine", "CognitiveShard", "ShardLatencyEntry", "CycleResult"]
