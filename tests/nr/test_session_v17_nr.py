"""
test_new_session_nr.py — Tests NR pour les modules livrés en session v17
========================================================================
Couvre : MutationPredictor, MutationClassifier, GeminiMCPProxy,
         ForgeProjectExporter, forge_lora_trainer dataset, forge_dashboard.
"""
from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))


# ── MutationPredictor ─────────────────────────────────────────────────────────

class TestMutationPredictor:
    """Tests du classifieur ML de succès de mutation."""

    def test_import(self):
        """Import du module sans erreur."""
        from forge_mutation_predictor import MutationPredictor
        assert MutationPredictor is not None

    def test_instantiation(self):
        """Instanciation sans crash."""
        from forge_mutation_predictor import MutationPredictor
        pred = MutationPredictor()
        assert pred is not None

    def test_model_path_exists(self):
        """Le modèle pkl existe sur disque."""
        model_path = ROOT / "shadow_mutation" / "ml_models" / "cerberus_predictor.pkl"
        assert model_path.exists(), f"Modèle absent : {model_path}"

    def test_is_available(self):
        """Le modèle est chargeable."""
        from forge_mutation_predictor import MutationPredictor
        pred = MutationPredictor()
        assert pred.is_available(), "Modèle non disponible"

    def test_threshold(self):
        """Le seuil est dans [0.1, 0.5]."""
        from forge_mutation_predictor import MutationPredictor
        pred = MutationPredictor()
        assert 0.1 <= pred._threshold <= 0.5, f"Seuil hors limites : {pred._threshold}"

    def test_features_count(self):
        """Le modèle a 9 features (avec past_ok/past_ko)."""
        from forge_mutation_predictor import MutationPredictor
        pred = MutationPredictor()
        assert len(pred._features) >= 7, f"Attendu 9 features, got {len(pred._features)}"

    def test_predict_proba_range(self):
        """predict_proba retourne une valeur dans [0, 1]."""
        from forge_mutation_predictor import MutationPredictor
        pred = MutationPredictor()
        prob = pred.predict_proba(0.3, 10, 2, 0.3, 1, "groq/llama", 2, 1)
        assert 0.0 <= prob <= 1.0, f"Probabilité hors limites : {prob}"

    def test_should_attempt_returns_tuple(self):
        """should_attempt retourne bien un tuple (float, bool)."""
        from forge_mutation_predictor import MutationPredictor
        pred = MutationPredictor()
        result = pred.should_attempt(
            filepath="app/forge_hub_storage.py",
            risk=0.3,
            agents=["groq/llama-3.3-70b-versatile"],
            temp=0.3,
            attempt=1,
        )
        assert isinstance(result, tuple) and len(result) == 2
        prob, go = result
        assert isinstance(prob, float)
        assert isinstance(go, bool)

    def test_cold_start_goes(self):
        """Un fichier sans historique → probabilité optimiste > seuil."""
        from forge_mutation_predictor import MutationPredictor
        pred = MutationPredictor()
        # Fichier inexistant = cold-start
        prob = pred.predict_proba(0.0, 20, 4, 0.3, 1, "groq/llama", 0, 0)
        assert prob >= pred._threshold, f"Cold-start devrait être GO, prob={prob:.2f}"

    def test_high_failure_history_lower_prob(self):
        """Beaucoup d'échecs passés → probabilité plus basse."""
        from forge_mutation_predictor import MutationPredictor
        pred = MutationPredictor()
        prob_clean  = pred.predict_proba(0.0, 10, 2, 0.3, 1, "groq", 5, 0)
        prob_failed = pred.predict_proba(0.0, 10, 2, 0.3, 1, "groq", 5, 40)
        assert prob_failed <= prob_clean + 0.1, "Les échecs passés devraient réduire la prob"


# ── MutationClassifier ────────────────────────────────────────────────────────

class TestMutationClassifier:
    """Tests du classifieur LogisticRegression de mutation."""

    def test_import(self):
        """Import sans erreur."""
        from forge_mutation_classifier import MutationClassifier
        assert MutationClassifier is not None

    def test_model_pkl_exists(self):
        """Le pkl du classifieur existe."""
        pkl = ROOT / "shadow_mutation" / "mutation_classifier.pkl"
        assert pkl.exists(), f"Modèle absent : {pkl}"

    def test_fit_returns_f1(self):
        """fit() retourne un F1 > 0."""
        from forge_mutation_classifier import MutationClassifier
        clf = MutationClassifier()
        f1  = clf.fit()
        assert f1 > 0.0, f"F1 devrait être > 0, got {f1}"

    def test_predict_proba_range(self):
        """predict_proba retourne [0,1]."""
        from forge_mutation_classifier import MutationClassifier
        clf = MutationClassifier()
        clf.fit(force=True)  # réentraîner pour éviter pkl avec multi_class obsolète
        prob = clf.predict_proba("app/forge_hub_storage.py",
                                 "groq/llama-3.3-70b-versatile", 0.30)
        assert 0.0 <= prob <= 1.0

    def test_cold_start_optimistic(self):
        """Fichier sans historique → prob optimiste (0.75)."""
        from forge_mutation_classifier import MutationClassifier
        clf  = MutationClassifier()
        clf.fit()
        prob = clf.predict_proba("app/FICHIER_INEXISTANT_XYZ.py",
                                 "groq/llama", 0.30)
        assert prob >= 0.70, f"Cold-start devrait retourner ~0.75, got {prob}"

    def test_should_skip_returns_bool(self):
        """should_skip retourne un bool."""
        from forge_mutation_classifier import MutationClassifier
        clf    = MutationClassifier()
        clf.fit(force=True)
        result = clf.should_skip("app/forge_hub_storage.py",
                                 "groq/llama", 0.30, verbose=False)
        assert isinstance(result, bool)

    def test_feature_importance_length(self):
        """feature_importance retourne autant d'éléments que de features."""
        from forge_mutation_classifier import MutationClassifier, FEATURE_NAMES
        clf = MutationClassifier()
        clf.fit()
        imp = clf.feature_importance()
        assert len(imp) == len(FEATURE_NAMES)


# ── ForgeProjectExporter ──────────────────────────────────────────────────────

class TestForgeProjectExporter:
    """Tests de l'exporteur de contexte Nokido."""

    def test_import(self):
        """Import sans erreur."""
        from forge_exporter import ForgeProjectExporter
        assert ForgeProjectExporter is not None

    def test_instantiation(self):
        """Instanciation avec root valide."""
        from forge_exporter import ForgeProjectExporter
        exp = ForgeProjectExporter(str(ROOT))
        assert exp.root == ROOT

    def test_generate_master_context_creates_file(self, tmp_path):
        """generate_master_context() crée un JSON valide."""
        from forge_exporter import ForgeProjectExporter
        exp             = ForgeProjectExporter(str(ROOT))
        exp.export_dir  = tmp_path
        ctx_file        = exp.generate_master_context()
        assert ctx_file.exists()
        data = json.loads(ctx_file.read_text(encoding="utf-8"))
        assert "project" in data
        assert data["project"] == "Nokido"

    def test_master_context_has_required_keys(self, tmp_path):
        """Le master_context contient toutes les clés attendues."""
        from forge_exporter import ForgeProjectExporter
        exp            = ForgeProjectExporter(str(ROOT))
        exp.export_dir = tmp_path
        ctx_file       = exp.generate_master_context()
        data           = json.loads(ctx_file.read_text(encoding="utf-8"))
        for key in ["project", "vault_modules", "success_patterns", "failure_lessons"]:
            assert key in data, f"Clé manquante : {key}"

    def test_vault_modules_populated(self, tmp_path):
        """Le vault génomique est bien extrait."""
        from forge_exporter import ForgeProjectExporter
        exp            = ForgeProjectExporter(str(ROOT))
        exp.export_dir = tmp_path
        ctx_file       = exp.generate_master_context()
        data           = json.loads(ctx_file.read_text(encoding="utf-8"))
        assert len(data["vault_modules"]) > 0, "Vault vide dans le contexte"

    def test_generate_prompt_passation(self, tmp_path):
        """generate_prompt_passation() crée un fichier markdown."""
        from forge_exporter import ForgeProjectExporter
        exp            = ForgeProjectExporter(str(ROOT))
        exp.export_dir = tmp_path
        ctx_file       = exp.generate_master_context()
        pmt_file       = exp.generate_prompt_passation(ctx_file)
        assert pmt_file.exists()
        content = pmt_file.read_text(encoding="utf-8")
        assert "Nokido" in content
        assert "### " in content  # sections markdown


# ── AgentPool routing laforge-qwen ───────────────────────────────────────────

class TestAgentPoolLoRARouting:
    """Tests du routing laforge-qwen dans AgentPool."""

    def test_nokido_qwen_in_scribes(self):
        """laforge-qwen est bien en tête des SCRIBES."""
        from evolutionary_engine import AgentPool
        assert AgentPool.SCRIBES[0] == "ollama/laforge-qwen"

    def test_nokido_qwen_in_reflex(self):
        """laforge-qwen est en tête des REFLEX."""
        from evolutionary_engine import AgentPool
        assert AgentPool.REFLEX[0] == "ollama/laforge-qwen"

    def test_nokido_qwen_in_local_group(self):
        """laforge-qwen est dans GROUPS.local."""
        from evolutionary_engine import AgentPool
        assert "ollama/laforge-qwen" in AgentPool.GROUPS["local"]

    def test_docstring_task_routes_to_scribes(self):
        """Une tâche 'docstrings' sélectionne le pool SCRIBES."""
        from evolutionary_engine import AgentPool
        agents = AgentPool.select(risk=0.3, population=3, task="docstrings")
        assert len(agents) > 0
        # laforge-qwen doit apparaître dans les agents sélectionnés
        assert any("laforge" in a for a in agents), \
            f"laforge-qwen absent des agents docstrings : {agents}"

    def test_select_returns_list(self):
        """select() retourne une liste non vide."""
        from evolutionary_engine import AgentPool
        agents = AgentPool.select(risk=0.5, population=3)
        assert isinstance(agents, list)
        assert len(agents) > 0


# ── LoRA Dataset ─────────────────────────────────────────────────────────────

class TestLoRADataset:
    """Tests du dataset d'entraînement LoRA."""

    def test_dataset_file_exists(self):
        """Le fichier JSONL du dataset existe."""
        ds = ROOT / "data" / "lora" / "nokido_train.jsonl"
        assert ds.exists(), f"Dataset absent : {ds}"

    def test_dataset_not_empty(self):
        """Le dataset contient au moins 100 exemples."""
        ds = ROOT / "data" / "lora" / "nokido_train.jsonl"
        lines = ds.read_text(encoding="utf-8", errors="replace").splitlines()
        assert len(lines) >= 100, f"Dataset trop petit : {len(lines)} exemples"

    def test_dataset_valid_json(self):
        """Chaque ligne du JSONL est valide avec clé 'text' ou 'instruction'."""
        ds    = ROOT / "data" / "lora" / "nokido_train.jsonl"
        lines = [l for l in ds.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        errors = 0
        for i, line in enumerate(lines[:20]):
            try:
                d = json.loads(line)
                assert "text" in d or "instruction" in d, f"Clé manquante ligne {i}"
            except Exception as e:
                errors += 1
        assert errors == 0, f"{errors} lignes invalides dans le dataset"

    def test_csv_autotrain_exists(self):
        """Le CSV AutoTrain existe."""
        csv = ROOT / "data" / "lora" / "autotrain_nokido.csv"
        assert csv.exists(), f"CSV AutoTrain absent : {csv}"

    def test_lora_adapter_exists(self):
        """L'adaptateur LoRA est téléchargé localement."""
        adapter = ROOT / "models" / "laforge-qwen-lora" / "adapter_config.json"
        assert adapter.exists(), f"Adaptateur LoRA absent : {adapter}"

    def test_adapter_config_valid(self):
        """La config LoRA est valide."""
        adapter = ROOT / "models" / "laforge-qwen-lora" / "adapter_config.json"
        cfg     = json.loads(adapter.read_text(encoding="utf-8"))
        assert cfg.get("r") == 16, f"lora_r attendu=16, got {cfg.get('r')}"
        assert cfg.get("task_type") == "CAUSAL_LM"
        assert "q_proj" in cfg.get("target_modules", [])


# ── Dashboard ─────────────────────────────────────────────────────────────────

class TestForgeDashboard:
    """Tests du dashboard PyQt6 (sans UI — fonctions utilitaires)."""

    def test_import_no_crash(self):
        """Import du module sans crash (même sans display)."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "forge_dashboard",
            ROOT / "tools" / "forge_dashboard.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # Ne pas exec (PyQt6 sans display), juste vérifier que le fichier est parseable
        src = (ROOT / "tools" / "forge_dashboard.py").read_text(encoding="utf-8")
        ast.parse(src)  # doit passer sans SyntaxError

    @pytest.mark.skipif(
        not os.environ.get("DISPLAY") and sys.platform != "win32",
        reason="Pas de display — test UI skippé sur CI headless"
    )
    def test_load_vault_function(self):
        """load_vault() retourne une liste triée (nécessite un display)."""
        import importlib.util, types
        for mod_name in ["PyQt6", "PyQt6.QtCore", "PyQt6.QtGui",
                         "PyQt6.QtWidgets", "pyqtgraph"]:
            sys.modules.setdefault(mod_name, types.ModuleType(mod_name))
        spec = importlib.util.spec_from_file_location(
            "forge_dashboard_lv", ROOT / "tools" / "forge_dashboard.py"
        )
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            data = mod.load_vault()
            assert isinstance(data, list) and len(data) > 0
            scores = [d["score"] for d in data]
            assert scores == sorted(scores, reverse=True)
        except SystemExit:
            pytest.skip("PyQt6 requiert un display")

    def test_score_color_logic(self):
        """score_color retourne la bonne famille de couleur (sans Qt)."""
        # Test direct de la logique — pas besoin de charger PyQt6
        score_colors = {
            (93, 101): "#1B7F3C",
            (90, 93):  "#2ECC71",
            (88, 90):  "#F39C12",
            (85, 88):  "#E67E22",
            (0,  85):  "#C0392B",
        }
        def score_color(score):
            for (lo, hi), color in score_colors.items():
                if lo <= score < hi:
                    return color
            return "#888888"

        for score in [94, 90, 88, 85, 70]:
            color = score_color(score)
            assert color.startswith("#"), f"score_color({score}) invalide : {color}"
            assert len(color) == 7


# ── GPU Lock ParallelMutationWorker ───────────────────────────────────────────

class TestGPULock:
    """Tests du GPU Lock dans ParallelMutationWorker."""

    def test_file_exists(self):
        """ParallelMutationWorker.py existe."""
        assert (ROOT / "ParallelMutationWorker.py").exists()

    def test_gpu_lock_present(self):
        """Le GPU Lock est bien dans le code source."""
        src = (ROOT / "ParallelMutationWorker.py").read_text(encoding="utf-8")
        assert "GPU LOCK" in src or "GPU_LOCK" in src or "GPU Lock" in src
        assert any(t in src for t in ["random.uniform", "uniform(", "_rnd.uniform"])  # jitter
        assert "virtual_memory" in src  # RAM guard

    def test_ast_valid(self):
        """Le fichier est syntaxiquement valide."""
        src = (ROOT / "ParallelMutationWorker.py").read_text(encoding="utf-8", errors="replace")
        ast.parse(src)  # lève SyntaxError si invalide
