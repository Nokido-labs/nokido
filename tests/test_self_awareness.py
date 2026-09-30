from __future__ import annotations

import pytest
from app.forge_self_awareness import self_snapshot

def test_self_snapshot_structure():
    snapshot = self_snapshot()
    assert isinstance(snapshot, dict)
    
    # 6 sections obligatoires
    required_sections = ["identity", "body_local", "cloud_llm", "compute", "agentic", "budget"]
    for sec in required_sections:
        assert sec in snapshot, f"Section manquante: {sec}"
        assert isinstance(snapshot[sec], dict)

    # Section 1: identity
    assert "hub" in snapshot["identity"]
    assert "version" in snapshot["identity"]

    # Section 2: body_local
    assert "n_organes" in snapshot["body_local"]
    assert "ram_pct" in snapshot["body_local"]
    assert "services_up" in snapshot["body_local"]

    # Section 3: cloud_llm (étendu nvidia, cerebras, sambanova, cohere, hf)
    cloud_llm = snapshot["cloud_llm"]
    for provider in ["nvidia", "cerebras", "sambanova", "cohere", "hf"]:
        assert provider in cloud_llm, f"Provider étendu manquant dans cloud_llm: {provider}"

    # Section 4: compute
    assert "kaggle" in snapshot["compute"]
    assert "hf_jobs" in snapshot["compute"]

    # Section 5: agentic
    assert "agy" in snapshot["agentic"]
    assert "available" in snapshot["agentic"]["agy"]
    assert isinstance(snapshot["agentic"]["agy"]["available"], bool)
    assert "swarm" in snapshot["agentic"]

    # Section 6: budget
    assert "cost_usd_today" in snapshot["budget"]
    assert "cortisol_quota_cloud" in snapshot["budget"]
