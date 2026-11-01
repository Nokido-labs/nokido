"""Tests non-regression pour le cloisonnement du tableau noir et RBAC (S2, S3).

Verifie :
S2. forge_swarm_blackboard :
    - ACL d'ECRITURE par ring :
      * mission ring<=1
      * architecture_rules ring<=1
      * discovered_facts ring<=2
      * active_bugs ring<=2
      * scratch ring<=3
    - Idempotence de la cle (sha256(category + normalized_fact)[:16]) et UPSERT.
    - Base SQLite temporaire (tmp_path).
S3. forge_mcp_rbac :
    - mapping outil -> IntegrityRing :
      * rag, query, blackboard_read_zone accessibles en UNTRUSTED (ring 4).
      * blackboard_propose_fact exige TRUSTED (ring 2).
    - Verification d'absence d'escalade : un appelant UNTRUSTED (ring 4) ou COLLAB (ring 3)
      ne peut pas invoquer blackboard_propose_fact au niveau RBAC (check_tool_capability),
      et meme au sein de blackboard (apply_fact), la zone mission/architecture_rules exige ring<=1.
      TROU: non (blackboard_propose_fact est protege a ring 2 dans app/forge_mcp_rbac.py:154
      et la zone de regles/mission exige ring<=1 dans app/forge_swarm_blackboard.py:63-64).
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import pytest

from nokido_agent.app.forge_swarm_blackboard import (
    apply_fact,
    read_zone,
    _fact_key,
    _normalize,
    _ZONE_WRITE_RING,
)
from nokido_agent.app.forge_mcp_rbac import (
    check_tool_capability,
    tool_required_ring,
    IntegrityRing,
    _TOOL_REQUIRED_RING,
)


@pytest.fixture
def temp_blackboard_db(tmp_path, monkeypatch):
    """Isole forge_swarm_blackboard sur une base SQLite temporaire."""
    import nokido_agent.app.forge_swarm_blackboard as bb

    db_file = tmp_path / "test_swarm.db"
    monkeypatch.setattr(bb, "_DB", db_file)
    monkeypatch.setattr(bb, "_writer_conn", None)
    monkeypatch.setattr(bb, "_write_lock", None)
    bb.init_db()
    yield db_file
    if bb._writer_conn:
        try:
            bb._writer_conn.close()
        except Exception:
            pass
        bb._writer_conn = None


# ============================================================================
# S2. forge_swarm_blackboard — ACL d'écriture par ring & Idempotence
# ============================================================================

def test_s2_blackboard_thresholds_definition():
    """Verifie les seuils d'ACL d'ecriture declares dans _ZONE_WRITE_RING."""
    assert _ZONE_WRITE_RING.get("mission") == 1
    assert _ZONE_WRITE_RING.get("architecture_rules") == 1
    assert _ZONE_WRITE_RING.get("discovered_facts") == 2
    assert _ZONE_WRITE_RING.get("active_bugs") == 2
    assert _ZONE_WRITE_RING.get("scratch") == 3


@pytest.mark.asyncio
async def test_s2_blackboard_acl_mission_and_rules(temp_blackboard_db):
    """Zone de regles et mission exigent ring<=1."""
    # Autorise pour ring 0 (SYSTEM) et ring 1 (DEV)
    res_m1 = await apply_fact("mission", "Mission principale", ring=1)
    assert res_m1.get("ok") is True

    res_r1 = await apply_fact("architecture_rules", "Regle d'or 1", ring=1)
    assert res_r1.get("ok") is True

    # Refuse pour ring 2 (TRUSTED), ring 3 (COLLAB), ring 4 (UNTRUSTED)
    res_m2 = await apply_fact("mission", "Mission pirate", ring=2)
    assert "error" in res_m2
    assert "ACL" in res_m2["error"]

    res_r2 = await apply_fact("architecture_rules", "Regle pirate", ring=2)
    assert "error" in res_r2
    assert "ACL" in res_r2["error"]

    res_m4 = await apply_fact("mission", "Mission untrusted", ring=4)
    assert "error" in res_m4
    assert "ACL" in res_m4["error"]


@pytest.mark.asyncio
async def test_s2_blackboard_acl_discovered_facts_and_active_bugs(temp_blackboard_db):
    """discovered_facts et active_bugs exigent ring<=2."""
    # Autorise pour ring 1 et 2
    res_df2 = await apply_fact("discovered_facts", "Fait decouvert 1", ring=2)
    assert res_df2.get("ok") is True

    res_ab2 = await apply_fact("active_bugs", "Bug critique 1", ring=2)
    assert res_ab2.get("ok") is True

    # Refuse pour ring 3 et 4
    res_df3 = await apply_fact("discovered_facts", "Fait externe", ring=3)
    assert "error" in res_df3
    assert "ACL" in res_df3["error"]

    res_ab4 = await apply_fact("active_bugs", "Bug untrusted", ring=4)
    assert "error" in res_ab4
    assert "ACL" in res_ab4["error"]


@pytest.mark.asyncio
async def test_s2_blackboard_acl_scratch(temp_blackboard_db):
    """scratch exige ring<=3."""
    # Autorise pour ring 1, 2, 3
    res_s3 = await apply_fact("scratch", "Brouillon agent", ring=3)
    assert res_s3.get("ok") is True

    # Refuse pour ring 4 (UNTRUSTED)
    res_s4 = await apply_fact("scratch", "Brouillon untrusted", ring=4)
    assert "error" in res_s4
    assert "ACL" in res_s4["error"]


@pytest.mark.asyncio
async def test_s2_blackboard_idempotence_and_upsert(temp_blackboard_db):
    """Meme fait -> meme cle calculee, et mise a jour (UPSERT) sans doublon."""
    fact_text = "Le RAG repond en moins de 100ms"
    category = "perf"

    # Cle deterministe sha256((category).lower() + \x00 + _normalize(fact))[:16]
    expected_key = hashlib.sha256(
        f"{category.lower()}\x00{_normalize(fact_text)}".encode("utf-8")
    ).hexdigest()[:16]
    assert _fact_key(fact_text, category) == expected_key

    # Premier insert
    res1 = await apply_fact("scratch", fact_text, category=category, trust=0.6, ring=3)
    assert res1.get("ok") is True
    assert res1.get("key") == expected_key

    # Deuxieme insert avec legere variation de casse/espaces normalises -> meme cle, nouvel trust
    fact_variant = "  le  RAG repond en  moins de 100ms  "
    res2 = await apply_fact("scratch", fact_variant, category=category, trust=0.9, ring=3)
    assert res2.get("ok") is True
    assert res2.get("key") == expected_key

    # Verification en base SQLite : une seule ligne, valeur mise a jour (UPSERT)
    facts = read_zone("scratch", category=category)
    assert len(facts) == 1
    assert facts[0]["key"] == expected_key
    assert facts[0]["trust"] == 0.9


# ============================================================================
# S3. forge_mcp_rbac — Mapping RBAC & Cloisonnement blackboard_propose_fact
# ============================================================================

def test_s3_rbac_untrusted_tools_mapping():
    """rag, query, blackboard_read_zone doivent etre accessibles en UNTRUSTED (ring 4)."""
    assert _TOOL_REQUIRED_RING.get("rag") == int(IntegrityRing.UNTRUSTED)
    assert _TOOL_REQUIRED_RING.get("query") == int(IntegrityRing.UNTRUSTED)
    assert _TOOL_REQUIRED_RING.get("blackboard_read_zone") == int(IntegrityRing.UNTRUSTED)

    # Verification via check_tool_capability pour un appelant ring 4
    for tool_name in ["rag", "query", "blackboard_read_zone"]:
        allowed, reason = check_tool_capability(tool_name, agent="untrusted_agent", ring=int(IntegrityRing.UNTRUSTED))
        assert allowed is True, f"{tool_name} devrait etre autorise pour UNTRUSTED"


def test_s3_rbac_blackboard_propose_fact_protection():
    """blackboard_propose_fact exige TRUSTED (ring 2).

    Un appelant UNTRUSTED (ring 4) ou COLLAB (ring 3) ne doit PAS pouvoir
    l'invoquer au niveau RBAC.
    """
    assert _TOOL_REQUIRED_RING.get("blackboard_propose_fact") == int(IntegrityRing.TRUSTED)
    assert tool_required_ring("blackboard_propose_fact") == int(IntegrityRing.TRUSTED)

    # Ring 2 (TRUSTED) : autorise
    allowed_r2, _ = check_tool_capability("blackboard_propose_fact", agent="trusted_agent", ring=int(IntegrityRing.TRUSTED))
    assert allowed_r2 is True

    # Ring 3 (COLLAB) : refuse
    allowed_r3, reason_r3 = check_tool_capability("blackboard_propose_fact", agent="collab_agent", ring=int(IntegrityRing.COLLAB))
    assert allowed_r3 is False
    assert "insufficient ring" in reason_r3  # libelle reel de check_tool_capability (le nom devine portait un _)

    # Ring 4 (UNTRUSTED) : refuse
    allowed_r4, reason_r4 = check_tool_capability("blackboard_propose_fact", agent="untrusted_agent", ring=int(IntegrityRing.UNTRUSTED))
    assert allowed_r4 is False
    assert "insufficient ring" in reason_r4


@pytest.mark.asyncio
async def test_s3_absence_trou_escalade_regles():
    """Verifie qu'un appelant UNTRUSTED ne peut pas ecrire dans la zone des regles.

    Preuve par double barriere :
    1) RBAC bloque au dispatch pour ring 4 / UNTRUSTED (required <= 2).
    2) Meme si la couche RBAC etait contournee, apply_fact bloque l'ecriture
       sur la zone des regles car ring > 1.
    """
    # 1. Barriere RBAC
    allowed, _ = check_tool_capability("blackboard_propose_fact", agent="attacker", ring=4)
    assert allowed is False

    # 2. Barriere apply_fact
    res = await apply_fact("architecture_rules", "Regle malveillante", ring=4)
    assert res.get("error") is not None
    assert "ACL" in res["error"]
