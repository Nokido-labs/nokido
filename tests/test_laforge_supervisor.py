# -*- coding: utf-8 -*-
"""tests/test_laforge_supervisor.py — Suite de tests asynchrones pour le Superviseur d'acteurs.
"""

from __future__ import annotations

import asyncio
import pytest
from sandbox.laforge_supervisor import LaForgeSupervisor


@pytest.mark.asyncio
async def test_supervisor_nominal_execution():
    """Test de la différenciation et de l'exécution nominale in-process."""
    supervisor = LaForgeSupervisor()
    
    # 1. Différenciation d'un organe
    await supervisor.differentiate_organ(
        role="adder",
        module="sandbox.scratch_test_module",
        function="add_numbers"
    )
    
    # 2. Exécution asynchrone
    res = await supervisor.execute_with_healing(
        role="adder",
        kwargs={"x": 5, "y": 7}
    )
    assert res == {"sum": 12}
    
    # 3. Arrêt
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_supervisor_epimorphosis_on_timeout():
    """Test du mécanisme d'auto-cicatrisation (épimorphose) lors d'un timeout."""
    supervisor = LaForgeSupervisor()
    
    # 1. Différenciation de l'organe configuré pour appeler la fonction lente
    await supervisor.differentiate_organ(
        role="llm_caller",
        module="sandbox.scratch_test_module",
        function="slow_function"
    )
    
    # Configuration de secours (fallback)
    fallback_plan = {
        "module": "sandbox.scratch_test_module",
        "function": "fallback_numbers"
    }
    
    # 2. Exécution avec timeout serré à 1.0s (déclenchera l'auto-cicatrisation)
    res = await supervisor.execute_with_healing(
        role="llm_caller",
        kwargs={"x": 5, "y": 5},
        fallback_config=fallback_plan,
        timeout=1.0
    )
    
    # Le résultat doit être celui de la fonction de secours (x+y)*10 = 100
    assert res == {"sum": 100}
    
    # Vérification que le rôle a bien été ré-affecté à la fonction de secours
    assert supervisor.organs["llm_caller"]["function"] == "fallback_numbers"
    
    # 3. Arrêt
    await supervisor.shutdown()


@pytest.mark.asyncio
async def test_supervisor_epimorphosis_on_crash():
    """Test de l'auto-cicatrisation (épimorphose) lors du crash brutal du processus."""
    supervisor = LaForgeSupervisor()
    
    await supervisor.differentiate_organ(
        role="calculator",
        module="sandbox.scratch_test_module",
        function="add_numbers"
    )
    
    # Simulation d'un crash brutal externe en tuant le processus via l'OS
    organ_proc = supervisor.organs["calculator"]["process"]
    organ_proc.terminate()
    await organ_proc.wait()  # Le processus est mort
    
    fallback_plan = {
        "module": "sandbox.scratch_test_module",
        "function": "fallback_numbers"
    }
    
    # Exécution : le superviseur doit détecter le crash (le canal d'écriture échoue ou ne répond pas),
    # déclencher l'épimorphose et rejouer la tâche
    res = await supervisor.execute_with_healing(
        role="calculator",
        kwargs={"x": 2, "y": 3},
        fallback_config=fallback_plan,
        timeout=2.0
    )
    
    assert res == {"sum": 50}
    
    await supervisor.shutdown()
