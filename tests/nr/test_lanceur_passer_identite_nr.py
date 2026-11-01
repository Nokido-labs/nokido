"""NR -- `forge_secours_lanceur.passer()` appele DEPUIS LE SWARM parle sous l'identite SWARM_LANCEUR ; copies ignorees.

Recette reelle 29/10 12 h 40 (job_96523e25f50c) : le passage enchaine au swarm a depose sous le jeton GENERIQUE
(« GATE_DENIED ring 4 ») car l'identite n'etait installee que dans le `__main__` du lanceur ; et la copie
`cli_swarm_ptr_20261029_114347.avant_reparation.json` a ete traitee comme un resultat. Faux appels, tmp_path."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import forge_cli_swarm as sw  # noqa: E402
from tools import forge_secours_lanceur as lz  # noqa: E402


def _demande(d: Path, nom: str) -> Path:
    p = d / nom
    p.write_text(json.dumps({"task": "q", "demande_synthese": {"pointeur": "x", "consigne": "c",
                                                               "executeurs": ["CLAUDE_HEADLESS"], "raison": "r"}}),
                 encoding="utf-8")
    return p


def test_passer_installe_l_identite_si_client_generique(tmp_path, monkeypatch):
    """Client hub generique du module -> le passage passe par _appel_identite, puis le client est restaure."""
    vus = []
    monkeypatch.setattr(lz, "_appel_identite", lambda outil, args: vus.append(outil) or json.dumps({"task_id": "T"}))
    generique = sw._appel_hub
    _demande(tmp_path, "cli_swarm_ptr_20261029_123955.json")
    lz.passer(tmp_path)
    assert vus == ["task"]
    assert sw._appel_hub is generique


def test_deja_integre_dit_deja_integre():
    """29/10 12 h 43 : un resultat deja integre s'affichait « attente »."""
    assert lz._etat({"secours_integre": {"task_id": "T"}}, {"secours_integre": {"task_id": "T"}}) == "déjà intégré"


def test_copie_de_sauvegarde_ignoree(tmp_path, monkeypatch):
    """Seuls les noms cli_swarm_ptr_AAAAMMJJ_HHMMSS.json sont traites."""
    vus = []
    monkeypatch.setattr(lz, "_appel_identite", lambda outil, args: vus.append(outil) or json.dumps({"task_id": "T"}))
    _demande(tmp_path, "cli_swarm_ptr_20261029_114347.avant_reparation.json")
    lz.passer(tmp_path)
    assert vus == []
