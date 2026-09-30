# -*- coding: utf-8 -*-
"""NR — la jauge d'entropie du monolithe doit connaitre ses seuils.

`EntropyGauge.refresh_entropy` (Nokido.py) classe le niveau par
`ENTROPY_THRESHOLDS["green"/"orange"]`, constante definie dans
`forge_agentic_engine` mais jamais importee par le monolithe (qui importe pourtant
`AgenticEngine` du meme module) : NameError a chaque rafraichissement de la
jauge. Releve par l'audit « noms non definis » (mesures/audits/noms_non_definis.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _noms_lies import noms_globaux_non_lies  # noqa: E402


def test_les_seuils_d_entropie_sont_lies():
    assert "ENTROPY_THRESHOLDS" not in noms_globaux_non_lies(
        "app/Nokido.py", "EntropyGauge.refresh_entropy")
