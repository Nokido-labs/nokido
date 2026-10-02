"""Organe gap épistémique → veille. Logique pure + spec déportable, sans RAG ni réseau."""
import importlib

ev = importlib.import_module("forge_epistemic_veille")


def test_is_gap_thresholds():
    assert ev._is_gap(0, 50.0) is True            # zéro match = gap
    assert ev._is_gap(2, 50.0) is True            # < MIN_RESULTS = gap
    assert ev._is_gap(5, 2.0) is True             # score sous le plancher = gap
    assert ev._is_gap(5, 99.0) is False           # large + score haut = couvert


def test_domain_key_stable():
    assert ev._domain_key("Codex Config") == ev._domain_key("codex config ")  # case/trim insensible
    assert ev._domain_key("a") != ev._domain_key("b")


def test_veille_on_gap_spec_deport_par_defaut():
    spec = ev.veille_on_gap("doc codex model_providers")
    assert spec["deport"] is True                  # ne bloque jamais : déport par défaut
    assert spec["engine"] == "forge_research_agent.research_agent"
    assert spec["objective"] == "doc codex model_providers"
    # 2026-09-25 : « groq » force menait a un modele MORT (code en dur, plus servi) ; la veille
    # passe desormais par le routeur (chaines strategy/synthesis). cf. test_veille_modele_vivant_nr.
    assert spec["provider"] == "auto"


def test_coverage_score_failsafe(monkeypatch):
    # RAG indispo simulé -> gap=None (INCONNU), jamais d'exception. Jusqu'au 2026-10-01 ce test
    # figeait gap=True « par prudence » : une source muette devenait une lacune, et feel_gap
    # emettait evenement critique + cortisol sur une panne (UNKNOWN != NO, constitution).
    # La doublure visait aussi le nom NU `forge_self_correction` alors que coverage_score
    # importe `nokido_agent.app.forge_self_correction` : elle ne mordait pas.
    from nokido_agent.app import forge_self_correction as sc

    def _boom(*a, **k):
        raise RuntimeError("rag down")

    monkeypatch.setattr(sc, "preflight_check_verbose", _boom)
    cov = ev.coverage_score("n'importe quoi")
    assert cov["ok"] is False
    assert cov["gap"] is None
    assert cov["verdict"] == "rag_indisponible"
    assert cov["n_results"] is None


def test_manifold_error_thresholds():
    import numpy as np

    # Force PCA calculation or load
    pca = ev._load_or_compute_pca()
    assert pca is not None, "PCA should be computed and loaded"

    components = pca["components"]  # (1024, 64)
    mean = pca["mean"]  # (1024,)

    np.random.seed(42)

    # 3 on-domain vectors (reconstruction error < 0.76)
    for i in range(3):
        y = np.random.normal(0, 1, 64).astype(np.float32)
        x_rec = np.dot(y, components.T)

        # Add perpendicular noise with norm = 0.4 (< 0.76)
        noise = np.random.normal(0, 1, 1024).astype(np.float32)
        noise = noise - np.dot(np.dot(noise, components), components.T)
        noise = noise / np.linalg.norm(noise) * 0.4

        v = x_rec + noise + mean
        err = ev.manifold_error(v)
        assert err is not None
        assert err < 0.76, f"On-domain vector {i} should be < 0.76, got {err:.4f}"

    # 2 off-domain vectors (reconstruction error > 0.76)
    for i in range(2):
        y = np.random.normal(0, 1, 64).astype(np.float32)
        x_rec = np.dot(y, components.T)

        # Add perpendicular noise with norm = 0.9 (> 0.76)
        noise = np.random.normal(0, 1, 1024).astype(np.float32)
        noise = noise - np.dot(np.dot(noise, components), components.T)
        noise = noise / np.linalg.norm(noise) * 0.9

        v = x_rec + noise + mean
        err = ev.manifold_error(v)
        assert err is not None
        assert err > 0.76, f"Off-domain vector {i} should be > 0.76, got {err:.4f}"

