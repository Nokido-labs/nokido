"""Allegement des schemas MCP : structure identique, poids plafonne, explanation conserve."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from forge_mcp_registry import ToolRegistry  # type: ignore

sys.path.insert(0, str(Path(__file__).parent))
from _snap_schema import snapshot  # noqa: E402

DATA = Path(__file__).parent / "schemas_mcp_structure.json"
# Cliquet : tokens cl100k du catalogue offline (_all_tools).
# Avant allegement : 11 668 (63 outils offline) ; apres : 9 606. 28-31/10 : +494 voulus (outil acp, si_etag/depuis_etag,
# depend_de) -> 10 100 ; 31/10 phase 1 de l'audit (sandbox/workspace/audit_schemas_mcp_20261031.md) : description
# d'explanation deportee dans les instructions serveur, enums plus recopies dans hub/run -> 8 981 (64 outils) ;
# puis etag x3 raccourcis et phase 2 (plus d'entree dyn_<nom> listee, noms cites par forge_call_dynamic) -> 8 663 (60) ;
# lot A (10 descriptions resserrees, garde-fous conserves) -> 8 222 ; phase 3 (route_dt -> route_task mode=dt,
# react_orchestrate -> orchestrate engine=react, anciens noms appelables) -> 8 122 (58 outils).
# 5/11 : +23 pour l'action hub `fils` (3b3080ad9), mesure 8 145 au run 42010880738.
# 6/11 : +3 pour l'action hub `formes` (4a9f774b3), mesure 8 148 (job_4f016e17580b).
# 6/11 : +3 pour l'action hub `alertes`, mesure 8 151.
# 7/11 : +249 voulus, mesure 8 400 (58 outils) : 233da7ee4 read `offset`/`limit` (~33) + description de la fenetre
# (+78) et task `contrat` {type, chemins} (~109) ; 268725e36 task `allow_critical` (~27). Allegement impossible sans
# toucher app/forge_mcp_registry.py (fichier critique, pas de derogation) : patch propose dans le rendu de la tache.
# 9/11 : +12 pour l'action hub `liberer_ram` et `needed_ram_gb` (f19d450ea), mesure 8 412 (58 outils).
PLAFOND_TOKENS = 8412
EXPLICATION_MAX_CAR = 70


def _poids(tools):
    tiktoken = pytest.importorskip("tiktoken")
    enc = tiktoken.get_encoding("cl100k_base")
    keys = ("name", "description", "inputSchema")
    return sum(len(enc.encode(json.dumps(dict((k, t[k]) for k in keys if k in t),
               ensure_ascii=False, separators=(",", ":")))) for t in tools)


@pytest.fixture
def tools(tmp_path):
    with patch("pathlib.Path.home", return_value=tmp_path):
        reg = ToolRegistry(root_dir=tmp_path)
        reg._event_bus = MagicMock()
        return reg._all_tools()


def test_structure_identique(tools):
    attendu = json.loads(DATA.read_text(encoding="utf-8"))
    assert snapshot(tools) == attendu


def test_explanation_court_optionnel(tools):
    for t in tools:
        p = t["inputSchema"]["properties"]["explanation"]
        assert p["type"] == "string"
        assert len(p.get("description", "")) <= EXPLICATION_MAX_CAR, t["name"]
        assert "explanation" not in (t["inputSchema"].get("required") or [])


def test_cliquet_poids(tools):
    assert _poids(tools) <= PLAFOND_TOKENS
