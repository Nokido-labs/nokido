# -*- coding: utf-8 -*-
"""
tests/nr/test_new_modules_nr.py
================================
NR pour les 6 modules créés en session 0.13.0 :
  forge_version       — source de vérité version
  forge_rag_qualify   — qualification intrinsèque chunks
  forge_rag_truth     — filtre de vérité / CoVe / ShadowIndex
  forge_hot_ingest    — fast-track ingestion humaine
  forge_promotion_queue — file d'attente adaptative
  forge_mcp_security  — _resolve_role / check_rights

Critères NR (6 règles) :
  C1 Modulaire        : 1 classe = 1 module fonctionnel
  C2 Comportement     : assert sur décisions, pas floats précis
  C3 Edge cases       : inputs vides, None, corrompus
  C4 Tolérant         : assert isinstance / in [] / True|False
  C5 Versionné        : datasets dans data_nr/
  C6 Probabiliste     : rang / top-N si applicable
"""
from __future__ import annotations
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

# ── Chemins ───────────────────────────────────────────────────────────────────
_ROOT    = Path(__file__).resolve().parent.parent.parent
_APP     = _ROOT / "app"
_DATA_NR = _ROOT / "data_nr"

sys.path.insert(0, str(_APP))
sys.path.insert(0, str(_ROOT / "tools"))


# =============================================================================
# BLOC 1 — forge_version
# =============================================================================

class TestForgeVersion:
    """C1 — forge_version : source de vérité unique pour la version."""

    def test_get_returns_string(self):
        import forge_version as fv
        fv.invalidate_cache()
        v = fv.get()
        assert isinstance(v, str)
        assert "." in v

    def test_get_matches_semver_pattern(self):
        import re, forge_version as fv
        fv.invalidate_cache()
        assert re.match(r"^\d+\.\d+\.\d+$", fv.get())

    def test_label_has_prefix(self):
        import forge_version as fv
        assert fv.label().startswith("v")

    def test_semver_returns_tuple(self):
        import forge_version as fv
        s = fv.semver()
        assert isinstance(s, tuple) and len(s) == 3
        assert all(isinstance(x, int) for x in s)

    def test_get_from_manager_none_fallback(self):
        import forge_version as fv
        r = fv.get_from_manager(None)
        assert isinstance(r, str) and "." in r

    def test_get_from_manager_broken_fallback(self):
        import forge_version as fv
        class _Bad:
            @property
            def current_version(self): raise RuntimeError("crash")
        r = fv.get_from_manager(_Bad())
        assert isinstance(r, str)

    def test_get_from_manager_valid(self):
        import forge_version as fv
        class _Good:
            current_version = "1.2.3"
        assert fv.get_from_manager(_Good()) == "1.2.3"

    def test_display_always_string(self):
        import forge_version as fv
        assert isinstance(fv.display(None), str)
        assert fv.display(None).startswith("v")

    def test_invalidate_cache_rerereads(self):
        import forge_version as fv
        fv.invalidate_cache()
        v1 = fv.get()
        fv.invalidate_cache()
        v2 = fv.get()
        assert v1 == v2   # stable après double invalidation

    def test_module_version_attribute(self):
        import forge_version as fv
        assert hasattr(fv, "__version__")
        assert isinstance(fv.__version__, str)

    # C3 — edge cases
    def test_get_from_manager_empty_string(self):
        import forge_version as fv
        class _Empty:
            current_version = ""
        # version vide → fallback
        r = fv.get_from_manager(_Empty())
        assert isinstance(r, str) and len(r) > 0

    def test_display_with_broken_vm(self):
        import forge_version as fv
        class _Boom:
            @property
            def current_version(self): raise ValueError
        result = fv.display(_Boom())
        assert result.startswith("v")


# =============================================================================
# BLOC 2 — forge_rag_qualify
# =============================================================================

class TestForgeRagQualify:
    """C1 — forge_rag_qualify : qualification intrinsèque des chunks."""

    def test_qualify_system_author(self):
        from forge_rag_qualify import qualify_chunk
        q = qualify_chunk(source="nr_report:x", author="system:nr_runner")
        assert q["ring"] == 0
        assert q["consensus_level"] == "gold"
        assert q["trust_score"] == 1.0
        assert q["mutable"] is False

    def test_qualify_pdf_source(self):
        from forge_rag_qualify import qualify_chunk
        q = qualify_chunk(source="guide.pdf", author="")
        assert q["ring"] == 2
        assert q["consensus_level"] == "verified"
        assert q["trust_score"] == 0.8

    def test_qualify_session_source(self):
        from forge_rag_qualify import qualify_chunk
        q = qualify_chunk(source="session:default", author="")
        assert q["ring"] == 3
        assert q["consensus_level"] == "draft"
        assert q["trust_score"] == 0.5

    def test_qualify_workflow_author(self):
        from forge_rag_qualify import qualify_chunk
        q = qualify_chunk(source="anything", author="workflow:audit")
        assert q["ring"] == 2
        assert q["consensus_level"] == "verified"

    def test_qualify_collab_author(self):
        from forge_rag_qualify import qualify_chunk
        q = qualify_chunk(source="x", author="collab:gpt4")
        assert q["ring"] == 3
        assert q["consensus_level"] == "draft"

    def test_apply_trust_weight_gold_higher(self):
        from forge_rag_qualify import apply_trust_weight
        wg, _ = apply_trust_weight(0.8, {"trust_score": 1.0, "consensus_level": "gold"})
        wd, _ = apply_trust_weight(0.8, {"trust_score": 0.5, "consensus_level": "draft"})
        assert wg > wd

    def test_apply_trust_min_consensus_filter(self):
        from forge_rag_qualify import apply_trust_weight
        _, include = apply_trust_weight(
            0.8, {"trust_score": 0.5, "consensus_level": "draft"},
            min_consensus="verified"
        )
        assert include is False

    def test_qualify_already_qualified_stable(self):
        """Chunk déjà qualifié → pas de régression."""
        from forge_rag_qualify import qualify_chunk
        existing = {"ring": 0, "consensus_level": "gold", "trust_score": 1.0,
                    "mutable": False, "verified_by": ["nr"]}
        q = qualify_chunk(source="any", author="", meta=existing)
        assert q["ring"] == 0
        assert q["trust_score"] == 1.0

    # C3 — edge cases
    def test_qualify_empty_source_and_author(self):
        from forge_rag_qualify import qualify_chunk
        q = qualify_chunk(source="", author="")
        assert isinstance(q["ring"], int)
        assert isinstance(q["consensus_level"], str)

    def test_qualify_unknown_prefix(self):
        from forge_rag_qualify import qualify_chunk
        q = qualify_chunk(source="unknown_source_xyz", author="unknown:agent")
        # Fallback → draft
        assert q["consensus_level"] == "draft"

    def test_rings_golden_dataset(self):
        """C5 — vérifie le dataset integrity_rings.json."""
        from forge_rag_qualify import RING_CONSENSUS, CONSENSUS_TRUST
        data = json.loads((_DATA_NR / "input/integrity_rings.json")
                           .read_text(encoding="utf-8"))
        rings = (data["rings"] if isinstance(data.get("rings"), list) else data.get("rings_list", list(data.get("rings", {}).values())))
        for r in rings:
            ring_id = r["ring"]
            if ring_id not in RING_CONSENSUS:
                continue  # Ring MASTER (-1) optionnel dans RING_CONSENSUS
            assert RING_CONSENSUS[ring_id] == r["consensus"]
            assert CONSENSUS_TRUST[r["consensus"]] == r.get("trust", CONSENSUS_TRUST[r["consensus"]])


# =============================================================================
# BLOC 3 — forge_rag_truth
# =============================================================================

class TestForgeRagTruth:
    """C1 — forge_rag_truth : filtre de vérité, CoVe, ShadowIndex."""

    def test_jaccard_identical(self):
        from forge_rag_truth import jaccard_similarity
        assert jaccard_similarity("python flask api", "python flask api") == 1.0

    def test_jaccard_different(self):
        from forge_rag_truth import jaccard_similarity
        score = jaccard_similarity("python flask api", "voiture rouge paris")
        assert score < 0.1

    def test_validate_semantic_ok(self):
        from forge_rag_truth import validate_semantic
        ok, score, _ = validate_semantic(
            "python est un langage interprété orienté objet",
            "python est un langage interprété orienté objet",
        )
        assert ok is True
        assert score >= 0.8

    def test_validate_authority_system_over_collab(self):
        from forge_rag_truth import validate_authority
        ok, _ = validate_authority(chunk_ring=3, validator_ring=0)
        assert ok is True

    def test_validate_authority_collab_cant_validate_system(self):
        from forge_rag_truth import validate_authority
        ok, _ = validate_authority(chunk_ring=0, validator_ring=3)
        assert ok is False

    def test_calculate_trust_gold_vote_max(self):
        from forge_rag_truth import calculate_trust_score
        sigs = [{"agent": "a", "ring": 0, "check": "authority", "score": 1.0}]
        assert calculate_trust_score(sigs) == 1.0

    def test_calculate_trust_collab_capped(self):
        from forge_rag_truth import calculate_trust_score
        sigs = [{"agent": f"c{i}", "ring": 3, "check": "cove", "score": 0.5}
                for i in range(10)]
        assert calculate_trust_score(sigs) <= 0.5

    def test_truth_state_labels(self):
        from forge_rag_truth import TruthState
        assert TruthState.GOLD.label() == "GOLD"
        assert TruthState.VERIFIED.consensus_level() == "verified"
        assert TruthState.DRAFT.trust_score() == 0.2

    def test_cove_normal_text(self):
        from forge_rag_truth import cove_validate
        r = cove_validate(
            "Python est un langage interprété populaire pour le web et la data science",
            {}, "collab:claude", source_exists=True
        )
        assert r.hallucination_check == "PASSED"
        assert r.trust_score <= 0.75   # C2 : plafonné en mono-mode

    def test_cove_ring_enforcement(self):
        from forge_rag_truth import cove_validate
        r = cove_validate("x", {}, "system:nr_runner", source_exists=False)
        assert r.ring_enforced is True   # system: forcé en collab: en mono-mode

    def test_cove_short_text_flagged(self):
        from forge_rag_truth import cove_validate
        r = cove_validate("x", {}, "collab:claude", source_exists=True)
        assert r.hallucination_check == "FLAGGED"

    def test_shadow_classify_prod(self):
        from forge_rag_truth import ShadowIndex
        assert ShadowIndex.classify({"ring": 0}) == "prod"
        assert ShadowIndex.classify({"ring": 2}) == "prod"

    def test_shadow_classify_shadow(self):
        from forge_rag_truth import ShadowIndex
        assert ShadowIndex.classify({"ring": 3}) == "shadow"
        assert ShadowIndex.classify({"ring": 4}) == "shadow"

    def test_shadow_split_warns(self):
        from forge_rag_truth import ShadowIndex
        results = [
            {"score": 0.9, "meta_parsed": {"ring": 0}},
            {"score": 0.7, "meta_parsed": {"ring": 3}},
        ]
        docs, warnings = ShadowIndex.split_results(results)
        assert len(warnings) == 1
        assert any("non vérifi" in w for w in warnings)

    def test_check_promotion_eligibility_mono(self):
        from forge_rag_truth import check_promotion_eligibility
        eligible, reason = check_promotion_eligibility(
            {}, {"hallucination_check": "PASSED", "trust_score": 0.6},
            mono_mode=True
        )
        assert isinstance(eligible, bool)
        assert isinstance(reason, str)

    # C3 — edge cases
    def test_jaccard_empty_strings(self):
        from forge_rag_truth import jaccard_similarity
        assert jaccard_similarity("", "") == 1.0

    def test_validate_semantic_empty(self):
        from forge_rag_truth import validate_semantic
        ok, score, _ = validate_semantic("", "")
        assert isinstance(ok, bool)

    def test_calculate_trust_empty_sigs(self):
        from forge_rag_truth import calculate_trust_score
        assert calculate_trust_score([]) == 0.0


# =============================================================================
# BLOC 4 — forge_hot_ingest
# =============================================================================

class TestForgeHotIngest:
    """C1 — forge_hot_ingest : fast-track ingestion humaine."""

    def test_build_human_meta_ring(self):
        from forge_hot_ingest import _build_human_meta, HUMAN_RING, HUMAN_TRUST
        m = _build_human_meta("test.pdf", "tui_drop")
        assert m["ring"] == HUMAN_RING   # 2 = TRUSTED
        assert m["trust_score"] == HUMAN_TRUST
        assert m["cove_skip"] is True
        assert m["provenance"] == "tui_drop"

    def test_build_human_meta_author(self):
        from forge_hot_ingest import _build_human_meta, HUMAN_AUTHOR
        m = _build_human_meta("x")
        assert m["author"] == HUMAN_AUTHOR
        assert len(m["verified_by"]) == 1
        assert m["verified_by"][0]["check"] == "human_validation"

    def test_detect_domain_pdf_kali(self):
        from forge_hot_ingest import _detect_domain
        assert _detect_domain("kali-linux-revealed.pdf") == "securite"

    def test_detect_domain_python(self):
        from forge_hot_ingest import _detect_domain
        assert _detect_domain("cours-python.pdf") == "code"

    def test_detect_domain_unknown(self):
        from forge_hot_ingest import _detect_domain
        d = _detect_domain("rapport-xyz-inconnu.pdf")
        assert isinstance(d, str) and len(d) > 0   # toujours une string

    def test_human_priority_zero(self):
        from forge_hot_ingest import HUMAN_PRIORITY
        assert HUMAN_PRIORITY == 0   # FLASH — passe devant tout

    def test_hot_ingest_file_not_found(self):
        """C3 — fichier inexistant → résultat ok=False sans crash."""
        import asyncio
        from forge_hot_ingest import hot_ingest_file
        result = asyncio.run(hot_ingest_file(
            Path("/nonexistent/file.pdf"),
            rag_engine=None,
            log_fn=lambda m: None,
        ))
        assert result["ok"] is False
        assert "introuvable" in result["msg"].lower()

    def test_watcher_init(self):
        from forge_hot_ingest import HotFolderWatcher
        w = HotFolderWatcher(rag_dir=_ROOT / "data/rag_files")
        assert not w._running
        assert isinstance(w._seen, set)
        assert w.POLL_INTERVAL > 0

    def test_watcher_supported_ext(self):
        from forge_hot_ingest import HotFolderWatcher
        assert ".pdf" in HotFolderWatcher.SUPPORTED_EXT
        assert ".md"  in HotFolderWatcher.SUPPORTED_EXT
        assert ".txt" in HotFolderWatcher.SUPPORTED_EXT

    # C3
    def test_detect_domain_empty(self):
        from forge_hot_ingest import _detect_domain
        d = _detect_domain("")
        assert isinstance(d, str)


# =============================================================================
# BLOC 5 — forge_promotion_queue
# =============================================================================

class TestForgePromotionQueue:
    """C1 — forge_promotion_queue : file d'attente adaptative CoVe."""

    def test_item_sort_by_priority(self):
        from forge_promotion_queue import PromotionItem
        items = [PromotionItem(10, "c"), PromotionItem(0, "a"), PromotionItem(5, "b")]
        assert sorted(items)[0].chunk_id == "a"
        assert sorted(items)[-1].chunk_id == "c"

    def test_orchestrator_local_workers(self):
        import os
        os.environ.pop("LAFORGE_CLOUD", None)
        from forge_promotion_queue import PromotionOrchestrator
        orch = PromotionOrchestrator()
        assert orch.max_workers == 2

    def test_orchestrator_cloud_workers(self):
        import os, importlib
        os.environ["LAFORGE_CLOUD"] = "true"
        import forge_promotion_queue as fpq
        importlib.reload(fpq)
        orch = fpq.PromotionOrchestrator()
        assert orch.max_workers == 10
        os.environ.pop("LAFORGE_CLOUD")
        importlib.reload(fpq)

    def test_ensure_table_idempotent(self):
        from forge_promotion_queue import _ensure_promo_table
        _ensure_promo_table()
        _ensure_promo_table()   # second appel ne doit pas crasher

    def test_restore_from_db_returns_list(self):
        from forge_promotion_queue import restore_from_db
        items = restore_from_db()
        assert isinstance(items, list)

    def test_stats_has_required_keys(self):
        from forge_promotion_queue import PromotionOrchestrator
        orch = PromotionOrchestrator()
        s = orch.stats()
        assert "enqueued" in s
        assert "promoted" in s
        assert "queue_size" in s

    def test_ram_threshold_default(self):
        from forge_promotion_queue import RAM_THRESHOLD_PCT
        assert 50 <= RAM_THRESHOLD_PCT <= 99   # entre 50 et 99%

    # C3
    def test_item_dataclass_compare_safe(self):
        from forge_promotion_queue import PromotionItem
        a = PromotionItem(priority=5, chunk_id="x")
        b = PromotionItem(priority=5, chunk_id="y")
        # Même priorité → comparaison ne crash pas
        assert (a == b) or (a != b)   # l'un ou l'autre, jamais exception

    def test_persist_unknown_chunk_noop(self):
        """Persister un chunk_id inexistant ne lève pas d'exception."""
        from forge_promotion_queue import _persist_item, PromotionItem
        item = PromotionItem(priority=5, chunk_id="nonexistent_xyz_000")
        _persist_item(item)   # doit passer sans exception


# =============================================================================
# BLOC 6 — forge_mcp_security
# =============================================================================

class TestForgeMcpSecurity:
    """C1 — forge_mcp_security : résolution ring + droits MCP."""

    @pytest.fixture(autouse=True)
    def sec(self):
        import sys
        sys.modules.pop("forge_mcp_security", None)
        sys.modules.pop("nokido_agent.app.forge_mcp_security", None)
        sys.modules.pop("forge_integrity", None)
        sys.modules.pop("nokido_agent.app.forge_integrity", None)
        from forge_mcp_security import MCPSecurity, SecurityConfig
        self._sec = MCPSecurity(SecurityConfig.from_env())

    def test_resolve_system_is_nokido(self):
        assert self._sec._resolve_role("system:nr_runner") == "laforge"

    def test_resolve_dev_is_nokido(self):
        assert self._sec._resolve_role("dev:claude") == "laforge"

    def test_resolve_workflow_is_cline(self):
        assert self._sec._resolve_role("workflow:audit") == "cline"

    def test_resolve_collab_is_ollama(self):
        assert self._sec._resolve_role("collab:gpt4") == "ollama"

    def test_resolve_unknown_is_external(self):
        assert self._sec._resolve_role("unknown_xyz") == "external"

    def test_resolve_nokido_is_nokido(self):
        assert self._sec._resolve_role("laforge") == "laforge"

    def test_system_can_rag_ingest(self):
        ok, _ = self._sec.check_rights("system:nr_runner", "query", "rag_ingest")
        assert ok is True

    def test_external_cannot_rag_ingest(self):
        ok, _ = self._sec.check_rights("external_agent", "query", "rag_ingest")
        assert ok is False

    def test_collab_can_rag_ingest(self):
        """collab → ollama → query → rag_ingest autorisé."""
        ok, _ = self._sec.check_rights("collab:gpt4", "query", "rag_ingest")
        assert ok is True

    def test_external_cannot_write(self):
        ok, _ = self._sec.check_rights("external", "write", "edit")
        assert ok is False

    def test_nokido_can_all(self):
        for action in ["rag_ingest", "rag_search", "sql", "db_status"]:
            ok, _ = self._sec.check_rights("laforge", "query", action)
            assert ok is True, f"nokido doit pouvoir {action}"

    # C3 — edge cases
    def test_resolve_empty_string(self):
        role = self._sec._resolve_role("")
        assert isinstance(role, str)

    def test_check_rights_empty_agent(self):
        ok, reason = self._sec.check_rights("", "query", "rag_search")
        assert isinstance(ok, bool)

    def test_check_rights_unknown_action(self):
        ok, reason = self._sec.check_rights("laforge", "query", "action_inconnue_xyz")
        assert isinstance(ok, bool)
