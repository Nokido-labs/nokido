# -*- coding: utf-8 -*-
"""NR -- une PROTHESE (LM Studio) est du corps, pas du non-soi (owner 30/10 « rien ne doit t'echapper »).

Mesure du 30/10 11:19 : node.exe 25184 (5,36 Go) = worker LM Studio (`llmworker.js`), parent `llmster.exe` (demon
headless). Le regulateur le rangeait `non-soi, service=ILLISIBLE` : RAM 99 %, eviction « manque 4,24 Go », rien
d'evince. Contrat : l'enfant d'une prothese connue est identifie avec la preuve `prothese`, et l'attribution de
pression le compte SOI (evincable par son reclaimer), jamais NON_SOI.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_process_inventory as inv  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_enfant_de_llmster_est_une_prothese():
    vivants = {100: {"nom": "llmster.exe", "ppid": 1, "cree": 1.0},
               200: {"nom": "node.exe", "ppid": 100, "cree": 2.0, "rss_mo": 5400}}
    ids, non = inv.identifier_processus(vivants, {}, {}, {})
    assert ids.get(200, {}).get("preuve") == "prothese", (ids, non)
    assert "lmstudio" in ids[200]["identite"].lower()
    assert not any(n["pid"] == 200 for n in non)


@pytest.mark.parametrize("parent", ["ollama.exe", "qdrant.exe", "agy.exe", "opencode.exe", "com.docker.backend.exe"])
def test_les_autres_protheses_sont_reconnues(parent):
    # 6f600aa68 (MISTRAL, 30/10) : protheses ajoutees sans NR -- couvertes ici
    vivants = {100: {"nom": parent, "ppid": 1, "cree": 1.0}, 200: {"nom": "node.exe", "ppid": 100, "cree": 2.0}}
    ids, _ = inv.identifier_processus(vivants, {}, {}, {})
    assert ids.get(200, {}).get("preuve") == "prothese", (parent, ids)


def test_un_client_reste_hors_corps():
    vivants = {100: {"nom": "bash.exe", "ppid": 1, "cree": 1.0},
               200: {"nom": "node.exe", "ppid": 100, "cree": 2.0}}
    ids, _ = inv.identifier_processus(vivants, {}, {}, {})
    assert ids.get(200, {}).get("preuve") == "parent"


def test_l_attribution_compte_la_prothese_comme_soi():
    src = (ROOT / "app" / "forge_resource_manager.py").read_text(encoding="utf-8")
    corps = src.split("def attribuer_pression", 1)[1].split("\ndef ", 1)[0]
    assert '"prothese"' in corps, "la preuve `prothese` doit classer SOI dans attribuer_pression"
