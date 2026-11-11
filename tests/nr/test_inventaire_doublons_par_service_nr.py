# -*- coding: utf-8 -*-
"""NR -- owner 9/11 « visibilite parfaite sur les processus de Nokido, sinon pas d'autoregulation ».
Mesure du 9/11 (job_ca6b20a20a84) : forge_process_inventory rangeait 9 `forge_task_executor.py` en DOUBLONS parce
qu'il groupait par NOM DE SCRIPT ; or chacun porte un `--agent` (et un service) distinct. Un doublon = meme script ET
meme service (ou meme agent) ; deux organes differents ne sont jamais un doublon."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_process_inventory as inv  # noqa: E402


def test_deux_executeurs_d_agents_differents_ne_sont_pas_doublons():
    a = inv.cle_doublon("forge_task_executor.py", "python forge_task_executor.py --agent OPENCODE_GLM", None)
    b = inv.cle_doublon("forge_task_executor.py", "python forge_task_executor.py --agent OPENCODE_DEFAUT2", None)
    assert a != b


def test_meme_agent_deux_fois_est_un_doublon():
    a = inv.cle_doublon("forge_task_executor.py", "x forge_task_executor.py --agent OPENCODE_GLM", None)
    b = inv.cle_doublon("forge_task_executor.py", "y forge_task_executor.py --agent opencode_glm", None)
    assert a == b


def test_le_service_du_registre_prime_sur_la_ligne_de_commande():
    # ligne de commande ILLISIBLE (None) : le service attribue par le registre suffit a distinguer
    a = inv.cle_doublon("forge_task_executor.py", None, "NokidoTaskExecutorOpencodeGlm")
    b = inv.cle_doublon("forge_task_executor.py", None, "NokidoTaskExecutorOpencodeDefaut2")
    c = inv.cle_doublon("forge_task_executor.py", None, "NokidoTaskExecutorOpencodeGlm")
    assert a != b and a == c


def test_sans_service_ni_agent_on_retombe_sur_le_script():
    assert inv.cle_doublon("forge_logboot.py", "python forge_logboot.py", None) == "forge_logboot.py"
