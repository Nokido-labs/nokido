"""
forge_mutation_predictor.py — Classifieur ML de succès de mutation
==================================================================
RandomForest entraîné sur experience_memory.jsonl (F1=0.937).

Prédit si une mutation va réussir AVANT de la lancer.
Économise les quotas Groq en skippant les mutations à faible probabilité.

Usage dans Cerberus :
    from tools.forge_mutation_predictor import MutationPredictor
    pred = MutationPredictor()
    prob, go = pred.should_attempt(filepath, risk, agents, temperature, attempt)
    if not go:
        print(f"[ML-SKIP] P={prob:.2f} < seuil — skip tentative")
        continue
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "shadow_mutation" / "ml_models" / "cerberus_predictor.pkl"


class MutationPredictor:
    """Prédit la probabilité de succès d'une mutation avant exécution.

    Features :
        risk       — score de complexité structurelle (0-1)
        fn_count   — nombre de fonctions dans le fichier
        cls_count  — nombre de classes
        temp       — température LLM utilisée
        attempt    — numéro de la tentative (1-5)
        agent_local — 1 si Ollama, 0 sinon
        agent_groq  — 1 si Groq, 0 sinon
    """

    FEATURES = ["risk", "fn_count", "cls_count", "temp", "attempt", "agent_local", "agent_groq"]
    THRESHOLD = 0.45  # P(succès) minimum pour tenter la mutation

    def __init__(self) -> None:
        """Charge le modèle pré-entraîné depuis le disque."""
        if not MODEL_PATH.exists():
            self._model = None
            self._threshold = self.THRESHOLD
            return
        with open(MODEL_PATH, "rb") as f:
            data = pickle.load(f)
        self._model = data["model"]
        self._threshold = data.get("threshold", self.THRESHOLD)
        self._features = data.get("features", self.FEATURES)

    def is_available(self) -> bool:
        """Vérifie si le modèle est chargé.

        Returns:
            True si le modèle est disponible.
        """
        return self._model is not None

    def predict_proba(
        self,
        risk: float,
        fn_count: int,
        cls_count: int,
        temp: float,
        attempt: int,
        agent: str,
        past_ok: int = 0,
        past_ko: int = 0,
    ) -> float:
        """Probabilité de succès de la mutation.

        Args:
            risk:      Score de complexité structurelle (0.0-1.0).
            fn_count:  Nombre de fonctions dans le fichier.
            cls_count: Nombre de classes dans le fichier.
            temp:      Température LLM (0.0-1.0).
            attempt:   Numéro de la tentative courante (1-5).
            agent:     Identifiant de l'agent LLM.
            past_ok:   Succès passés pour ce module dans experience_memory.
            past_ko:   Échecs passés pour ce module dans experience_memory.

        Returns:
            Probabilité de succès entre 0.0 et 1.0.
            Retourne 0.7 si le modèle n'est pas disponible (permissif).
        """
        if not self.is_available():
            return 0.7  # défaut permissif si pas de modèle

        agent_lower = agent.lower()
        n_features = len(self._features) if self._features else 7

        base_feats = [
            float(risk),
            min(float(fn_count), 100),
            float(cls_count),
            float(temp),
            float(attempt),
            1.0 if "ollama" in agent_lower else 0.0,
            1.0 if "groq" in agent_lower else 0.0,
        ]

        # Ajouter past_ok/past_ko si le modèle les supporte (9 features)
        if n_features >= 9:
            base_feats.extend([float(past_ok), float(past_ko)])

        feats = np.array([base_feats[:n_features]])
        return float(self._model.predict_proba(feats)[0][1])

    def should_attempt(
        self,
        filepath: str,
        risk: float,
        agents: list[str],
        temp: float,
        attempt: int,
    ) -> tuple[float, bool]:
        """Décide si Cerberus doit tenter la mutation.

        Args:
            filepath: Chemin du fichier cible.
            risk:     Score de risque structurel.
            agents:   Liste des agents LLM sélectionnés.
            temp:     Température courante.
            attempt:  Numéro de tentative courante.

        Returns:
            Tuple (probabilité, go) où go=True si la mutation est recommandée.
        """
        import ast as _ast

        # Compter fn et classes dans le fichier cible
        fn_count = cls_count = 0
        try:
            p = Path(filepath)
            if not p.is_absolute():
                p = ROOT / filepath
            src = p.read_text(encoding="utf-8", errors="replace")
            tree = _ast.parse(src)
            fn_count = sum(
                1
                for n in _ast.walk(tree)
                if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
            )
            cls_count = sum(1 for n in _ast.walk(tree) if isinstance(n, _ast.ClassDef))
        except Exception:
            pass

        # Historique du module depuis experience_memory
        import json as _json

        module = Path(filepath).stem
        past_ok = past_ko = 0
        ep_file = ROOT / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"
        if ep_file.exists():
            for _ln in ep_file.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    _d = _json.loads(_ln)
                    if _d.get("module", "") != module:
                        continue
                    if _d.get("evolution_status") == "Success":
                        past_ok += 1
                    else:
                        past_ko += 1
                except Exception:
                    pass

        # Agent dominant
        agent = agents[0] if agents else "unknown"

        prob = self.predict_proba(
            risk, fn_count, cls_count, temp, attempt, agent, past_ok=past_ok, past_ko=past_ko
        )
        go = prob >= self._threshold
        return prob, go

    def update(
        self,
        success: bool,
        risk: float,
        fn_count: int,
        cls_count: int,
        temp: float,
        attempt: int,
        agent: str,
    ) -> None:
        """Met à jour le modèle avec une nouvelle observation (online learning partiel).

        Args:
            success:   True si la mutation a réussi.
            risk:      Score de risque structurel.
            fn_count:  Nombre de fonctions.
            cls_count: Nombre de classes.
            temp:      Température utilisée.
            attempt:   Numéro de tentative.
            agent:     Agent LLM utilisé.
        """
        # Sauvegarder l'observation pour le prochain entraînement batch
        obs_file = ROOT / "shadow_mutation" / "ml_models" / "pending_observations.jsonl"
        import json

        obs = {
            "label": 1 if success else 0,
            "risk": risk,
            "fn_count": fn_count,
            "cls_count": cls_count,
            "temp": temp,
            "attempt": attempt,
            "agent_local": 1 if "ollama" in agent.lower() else 0,
            "agent_groq": 1 if "groq" in agent.lower() else 0,
        }
        with open(obs_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(obs) + "\n")

    @classmethod
    def retrain(cls) -> float:
        """Ré-entraîne le modèle avec experience_memory + pending_observations.

        Returns:
            Score F1 du nouveau modèle (cross-validation 5-fold).
        """
        import json
        import pickle
        import warnings

        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_score

        warnings.filterwarnings("ignore")

        ep = ROOT / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"
        obs = ROOT / "shadow_mutation" / "ml_models" / "pending_observations.jsonl"

        records: list[list[float]] = []

        def _parse_ep(line: str) -> list[float] | None:
            d = json.loads(line)
            label = 1 if d.get("evolution_status") == "Success" else 0
            factors = d.get("experience_feedback", {}).get("success_factors", []) or []
            temp = next((float(f.split("=")[1]) for f in factors if "temp=" in f), 0.3)
            attempt = next((int(f.split("=")[1]) for f in factors if "attempt=" in f), 1)
            return [
                float(d.get("complexity_risk", 0.5)),
                min(d.get("function_count", 0), 100),
                len(d.get("classes", [])),
                temp,
                attempt,
                1 if "ollama" in str(d.get("last_mutation_agent", "")).lower() else 0,
                1 if "groq" in str(d.get("last_mutation_agent", "")).lower() else 0,
                label,
            ]

        for src_file, parser in [(ep, _parse_ep), (obs, lambda l: list(json.loads(l).values()))]:
            if not src_file.exists():
                continue
            for line in src_file.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    records.append(parser(line))
                except Exception:
                    pass

        if len(records) < 10:
            return 0.0

        data = np.array(records)
        X, y = data[:, :-1], data[:, -1].astype(int)

        clf = RandomForestClassifier(
            n_estimators=200, class_weight="balanced", random_state=42, min_samples_leaf=2
        )
        cv = StratifiedKFold(n_splits=min(5, int(y.sum())), shuffle=True, random_state=42)
        f1 = cross_val_score(clf, X, y, cv=cv, scoring="f1").mean()

        clf.fit(X, y)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({"model": clf, "features": cls.FEATURES, "threshold": cls.THRESHOLD}, f)

        print(f"[ML] Modèle ré-entraîné — {len(records)} obs — F1={f1:.3f}")
        return f1


# ── CLI de test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    pred = MutationPredictor()
    if not pred.is_available():
        print("❌ Modèle absent — lance d'abord MutationPredictor.retrain()")
    else:
        print(f"✅ Modèle chargé — seuil={pred._threshold}")
        test_cases = [
            ("app/forge_hub_storage.py", 0.10, ["ollama/qwen7b"], 0.30, 1),
            ("app/forge_rag_engine.py", 1.00, ["groq/llama-70b"], 0.30, 1),
            ("app/LaForge.py", 0.80, ["ollama/qwen7b"], 0.50, 4),
        ]
        print("\nPrédictions :")
        for fp, risk, agents, temp, attempt in test_cases:
            prob, go = pred.should_attempt(fp, risk, agents, temp, attempt)
            status = "✅ GO" if go else "⛔ SKIP"
            print(f"  {fp:35s} P={prob:.2f}  {status}")
