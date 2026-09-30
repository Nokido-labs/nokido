# -*- coding: utf-8 -*-
"""tests/test_planerian_neoblast_manager.py — Tests unitaires de la dynamique planaire.
"""

from __future__ import annotations

import pytest
from sandbox.planerian_neoblast_manager import PlanerianSupervisor, NeoblastAgent


def test_neoblast_differentiation():
    """Vérifie qu'un néoblaste vierge se différencie correctement et exécute son rôle."""
    agent = NeoblastAgent("stem_test")
    assert agent.status == "UNASSIGNED"

    def mock_executor(payload):
        return {"processed": payload["data"].upper()}

    agent.differentiate(
        role="uppercase_worker",
        system_prompt="Convert input to uppercase",
        tools=["uppercase_tool"],
        executor_fn=mock_executor
    )

    assert agent.status == "DIFFERENTIATED"
    assert agent.role == "uppercase_worker"

    res = agent.execute({"data": "hello"})
    assert res["processed"] == "HELLO"


def test_planerian_healing_and_failover():
    """
    Vérifie que :
    1. La topologie se peuple au démarrage à partir du pool de néoblastes.
    2. Si un agent est détruit (blessure), un nouveau néoblaste prend le relais et répare la topologie.
    3. La mémoire distribuée (data_store) reste intacte.
    """
    # Mémoire distribuée émulée (découplée des agents)
    distributed_memory = {"call_count": 0}

    # Blueprint / Gradient Wnt de notre application
    def execute_condenser(payload):
        distributed_memory["call_count"] += 1
        return {"condensed": f"condensed: {payload['text']}"}

    def execute_router(payload):
        distributed_memory["call_count"] += 1
        return {"route": "local_database_workflow"}

    blueprint = {
        "condenser": {
            "system_prompt": "Condense input history",
            "executor_fn": execute_condenser
        },
        "router": {
            "system_prompt": "Route query based on embeddings",
            "executor_fn": execute_router
        }
    }

    # Initialisation du superviseur planaire avec 3 néoblastes en réserve
    supervisor = PlanerianSupervisor(blueprint=blueprint, neoblast_pool_size=3)

    # 1. Démarrage : La topologie est vide. On lance la cicatrisation.
    healed = supervisor.heal_topology()
    assert "condenser" in healed
    assert "router" in healed
    assert len(supervisor.active_topology) == 2

    # Vérification du fonctionnement nominal
    condenser_agent = supervisor.active_topology["condenser"]
    assert condenser_agent.agent_id == "stem_0"
    res = condenser_agent.execute({"text": "Bonjour LaForge"})
    assert res["condensed"] == "condensed: Bonjour LaForge"
    assert distributed_memory["call_count"] == 1

    # 2. Simulation de blessure (le condenser crashe ou devient défaillant)
    supervisor.simulate_failure("condenser")
    assert supervisor.active_topology["condenser"].status == "FAULTY"

    # 3. Cycle de cicatrisation suivant : le superviseur détecte le défaut et régénère le condenser
    healed_again = supervisor.heal_topology()
    assert "condenser" in healed_again
    assert len(healed_again) == 1

    # Vérification que le rôle condenser est maintenant porté par un NOUVEAU néoblaste du pool
    new_condenser_agent = supervisor.active_topology["condenser"]
    assert new_condenser_agent.agent_id == "stem_2"  # stem_0=FAULTY, stem_1=router, donc stem_2 est pris
    assert new_condenser_agent.status == "DIFFERENTIATED"

    # Exécution avec le nouvel agent régénéré
    res_post_heal = new_condenser_agent.execute({"text": "Hello world"})
    assert res_post_heal["condensed"] == "condensed: Hello world"

    # 4. Épimorphose / Mémoire intacte : le compteur d'appels a persisté
    assert distributed_memory["call_count"] == 2
