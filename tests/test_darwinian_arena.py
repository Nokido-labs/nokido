import pytest
from app import forge_darwinian_arena as fda


def test_submit_and_quarantine_ring4():
    cand = fda.submit_candidate("test_safe_math", "def solve(x, y): return x + y", author="pytest")
    cid = cand["candidate_id"]
    
    assert cand["status"] == "quarantine"
    assert cand["ring"] == 4
    assert cand["trust_score"] == 0.0
    assert cand["test_runs"] == 0


def test_ast_security_rejection():
    # Code essayant d'importer un module système interdit en Ring 4
    with pytest.raises(fda.SecurityError):
        fda.submit_candidate("evil_import", "import os\ndef solve(): return os.listdir('.')")

    # Code essayant d'utiliser eval/exec
    with pytest.raises(fda.SecurityError):
        fda.submit_candidate("evil_exec", "def solve(s): return eval(s)")


def test_synthetic_test_execution_and_score():
    cand = fda.submit_candidate("test_multiplier", "def solve(x): return x * 2", author="pytest")
    cid = cand["candidate_id"]

    # Test 1 : Réussite
    res1 = fda.run_synthetic_test(cid, test_input=[5], expected_output=10)
    assert res1["test_passed"] is True
    assert res1["test_runs"] == 1
    assert res1["trust_score"] == 1.0

    # Test 2 : Échec volontaire
    res2 = fda.run_synthetic_test(cid, test_input=[5], expected_output=99)
    assert res2["test_passed"] is False
    assert res2["test_runs"] == 2
    assert res2["test_passes"] == 1
    assert res2["trust_score"] == 0.5  # 1 pass / 2 runs


def test_promotion_success():
    cand = fda.submit_candidate("test_promo", "def solve(x): return x ** 2", author="pytest")
    cid = cand["candidate_id"]

    fda.run_synthetic_test(cid, test_input=[3], expected_output=9)
    fda.run_synthetic_test(cid, test_input=[4], expected_output=16)
    fda.run_synthetic_test(cid, test_input=[5], expected_output=25)

    # 3 tests réussis -> trust_score = 1.0 >= 0.85
    promo = fda.evaluate_promotion(cid, min_test_runs=3, min_trust_score=0.85, ignore_time_lock=True)
    assert promo["promoted"] is True
    assert promo["ring"] == 1
    assert promo["status"] == "promoted"


def test_promotion_rejection():
    cand = fda.submit_candidate("test_reject", "def solve(x): return 0", author="pytest")
    cid = cand["candidate_id"]

    # 1 réussite, 2 échecs -> trust_score = 0.33 < 0.85
    fda.run_synthetic_test(cid, test_input=[0], expected_output=0)
    fda.run_synthetic_test(cid, test_input=[1], expected_output=1)
    fda.run_synthetic_test(cid, test_input=[2], expected_output=2)

    promo = fda.evaluate_promotion(cid, min_test_runs=3, min_trust_score=0.85, ignore_time_lock=True)
    assert promo["promoted"] is False
    assert promo["reason"].startswith("Score de confiance insuffisant")
