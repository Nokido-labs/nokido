"""
forge_mutation_classifier.py — Classifieur ML de succès de mutation
====================================================================
Prédit si une mutation va réussir AVANT de la lancer.
Économise les quotas Groq/Ollama en filtrant les tentatives vouées à l'échec.

Architecture :
  Features extraites du fichier cible + stratégie Cerberus
    └── LogisticRegression (F1=0.93 sur corpus Nokido)
         └── score de confiance [0.0 → 1.0]
              └── seuil 0.40 → lancer / ne pas lancer

Usage dans Cerberus :
  from tools.forge_mutation_classifier import MutationClassifier
  clf = MutationClassifier()
  clf.fit()                              # s'entraîne sur experience_memory.jsonl
  prob = clf.predict_proba(filepath, agent, temperature)
  if prob < 0.40:
      print(f"[SKIP] probabilité de succès {prob:.0%} — agent non optimal")

Usage standalone :
  python tools/forge_mutation_classifier.py app/forge_handlers.py
"""

from __future__ import annotations

import json
import pickle
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── Dépendances ───────────────────────────────────────────────────────────────
try:
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "scikit-learn", "numpy", "-q"])
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

# ── Chemins ───────────────────────────────────────────────────────────────────
EP_FILE = ROOT / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"
MODEL_FILE = ROOT / "shadow_mutation" / "mutation_classifier.pkl"

# ── Noms des features ─────────────────────────────────────────────────────────
FEATURE_NAMES = [
    "risk",  # complexité structurelle (0.0–1.0)
    "generation",  # numéro de génération
    "nb_fns",  # nombre de fonctions dans le fichier
    "nb_cls",  # nombre de classes
    "nb_crit",  # composants critiques AST
    "temperature",  # température LLM utilisée
    "is_ollama",  # agent local Ollama (0/1)
    "is_groq",  # agent Groq cloud (0/1)
]

# Seuil optimal calibré par courbe ROC sur corpus Nokido (F1=0.80)
OPTIMAL_THRESHOLD = 0.30


def _extract_features(filepath: str, agent: str, temperature: float) -> list[float]:
    """Extrait les 8 features d'une cible de mutation.

    Features alignées avec le dataset d'entraînement (experience_memory.jsonl) :
    risk, generation, nb_fns, nb_cls, nb_crit, temperature, is_ollama, is_groq.

    Args:
        filepath: Chemin relatif du fichier cible (ex: 'app/forge_hub_storage.py').
        agent:    Nom de l'agent LLM (ex: 'groq/llama-3.3-70b-versatile').
        temperature: Température de génération.

    Returns:
        Vecteur de 8 features numériques.
    """
    import ast as _ast

    fpath = ROOT / filepath
    nb_fns = nb_cls = nb_crit = 0

    if fpath.exists():
        src = fpath.read_text(encoding="utf-8", errors="replace")
        try:
            tree = _ast.parse(src)
            nb_fns = sum(
                1
                for n in _ast.walk(tree)
                if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
            )
            nb_cls = sum(1 for n in _ast.walk(tree) if isinstance(n, _ast.ClassDef))
            nb_crit = sum(
                1
                for n in _ast.walk(tree)
                if isinstance(n, _ast.ClassDef)
                and sum(1 for m in n.body if isinstance(m, _ast.FunctionDef)) > 3
            )
        except Exception:
            pass

    risk = min(1.0, nb_fns * 0.005 + nb_cls * 0.02)

    return [
        risk,
        1,  # generation = 1 (premier essai)
        nb_fns,
        nb_cls,
        nb_crit,
        temperature,
        int("ollama" in agent.lower()),
        int("groq" in agent.lower()),
    ]


def _load_training_data() -> tuple[np.ndarray, np.ndarray]:
    """Charge et nettoie les données d'entraînement depuis experience_memory.jsonl.

    Returns:
        Tuple (X, y) — features et labels binaires.
    """
    import ast as _ast

    X: list[list[float]] = []
    y: list[int] = []

    if not EP_FILE.exists():
        return np.array(X), np.array(y)

    for line in EP_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
            agent = str(d.get("last_mutation_agent", ""))
            mod = str(d.get("module", ""))
            fpath = ROOT / "app" / f"{mod}.py"

            nb_fns = nb_cls = nb_crit = nb_imp = file_kb = has_async = 0
            if fpath.exists():
                src = fpath.read_text(encoding="utf-8", errors="replace")
                file_kb = len(src) // 1024
                nb_imp = src.count("import ")
                has_async = int("async def" in src)
                try:
                    tree = _ast.parse(src)
                    nb_fns = sum(
                        1
                        for n in _ast.walk(tree)
                        if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                    )
                    nb_cls = sum(1 for n in _ast.walk(tree) if isinstance(n, _ast.ClassDef))
                    nb_crit = sum(
                        1
                        for n in _ast.walk(tree)
                        if isinstance(n, _ast.ClassDef)
                        and sum(1 for m in n.body if isinstance(m, _ast.FunctionDef)) > 3
                    )
                except Exception:
                    pass
            else:
                # Utiliser les stats AST stockées dans la mémoire
                nb_fns = int(d.get("function_count", 0))
                nb_cls = len(d.get("classes", []))
                nb_crit = len(d.get("critical_components", []))

            risk = float(d.get("complexity_risk", 0.0))

            # Température depuis success_factors
            sf = d.get("experience_feedback", {}).get("success_factors", [])
            temp = 0.30
            for f in sf:
                if "temp=" in str(f):
                    try:
                        temp = float(str(f).split("temp=")[1][:4])
                    except Exception:
                        pass

            label = 1 if d.get("evolution_status") == "Success" else 0

            X.append(
                [
                    risk,
                    int(d.get("generation", 1)),
                    nb_fns,
                    nb_cls,
                    nb_crit,
                    temp,
                    int("ollama" in agent),
                    int("groq" in agent),
                ]
            )
            y.append(label)
        except Exception:
            pass

    return np.array(X, dtype=float), np.array(y)


class MutationClassifier:
    """Classifieur de succès de mutation — LogisticRegression sur features AST+agent."""

    # Seuil de probabilité en dessous duquel on skip la tentative
    SKIP_THRESHOLD = OPTIMAL_THRESHOLD

    def __init__(self) -> None:
        """Initialise le classifieur."""
        self._model: Pipeline | None = None
        self._trained = False
        self._f1_score = 0.0

    def fit(self, force: bool = False) -> float:
        """Entraîne le classifieur sur experience_memory.jsonl.

        Args:
            force: Si True, réentraîne même si un modèle est déjà chargé.

        Returns:
            F1-score cross-validé (0.0–1.0).
        """
        # Charger depuis le cache si disponible
        if not force and MODEL_FILE.exists():
            with MODEL_FILE.open("rb") as f:
                data = pickle.load(f)
                self._model = data["model"]
                self._f1_score = data["f1"]
                self._trained = True
                print(f"[CLF] Modèle chargé depuis cache — F1={self._f1_score:.3f}")
                return self._f1_score

        X, y = _load_training_data()
        if len(X) < 10:
            print("[CLF] Pas assez de données — fallback heuristique")
            return 0.0

        self._model = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=1000,
                        class_weight="balanced",
                        C=1.0,
                        random_state=42,
                    ),
                ),
            ]
        )

        # Validation croisée
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        scores = cross_val_score(self._model, X, y, cv=cv, scoring="f1")
        self._f1_score = float(scores.mean())

        # Entraînement final sur tout le corpus
        self._model.fit(X, y)
        self._trained = True

        # Sauvegarde cache
        MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
        with MODEL_FILE.open("wb") as f:
            pickle.dump({"model": self._model, "f1": self._f1_score, "features": FEATURE_NAMES}, f)

        print(
            f"[CLF] Entraîné — {len(X)} samples | F1={self._f1_score:.3f} | sauvegardé → {MODEL_FILE.name}"
        )
        return self._f1_score

    def predict_proba(
        self,
        filepath: str,
        agent: str,
        temperature: float = 0.30,
    ) -> float:
        """Prédit la probabilité de succès d'une mutation.

        Cold-start : si le fichier n'a jamais été muté, retourne 0.70 (GO par défaut).
        Le classifieur intervient uniquement quand il a suffisamment d'historique.

        Args:
            filepath:    Chemin relatif du fichier cible.
            agent:       Nom de l'agent LLM.
            temperature: Température prévue.

        Returns:
            Probabilité de succès [0.0–1.0].
        """
        if not self._trained:
            self.fit()
        if self._model is None:
            return 0.70  # pas de données — GO par défaut

        # Vérifier si le fichier a un historique dans experience_memory (JSON exact)
        import json as _json

        module = Path(filepath).stem
        has_history = False
        if EP_FILE.exists():
            for _ln in EP_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    if _json.loads(_ln).get("module", "") == module:
                        has_history = True
                        break
                except Exception:
                    pass

        # Cold-start : fichier sans historique → GO optimiste
        if not has_history:
            return 0.75

        features = _extract_features(filepath, agent, temperature)
        X = np.array([features])
        proba = self._model.predict_proba(X)[0][1]
        return float(proba)

    def should_skip(
        self,
        filepath: str,
        agent: str,
        temperature: float = 0.30,
        verbose: bool = True,
    ) -> bool:
        """Retourne True si la tentative doit être skippée.

        Args:
            filepath:    Chemin relatif du fichier cible.
            agent:       Nom de l'agent LLM.
            temperature: Température prévue.
            verbose:     Afficher le verdict.

        Returns:
            True si skip recommandé, False si lancer la mutation.
        """
        prob = self.predict_proba(filepath, agent, temperature)
        skip = prob < self.SKIP_THRESHOLD

        if verbose:
            verdict = "SKIP ⛔" if skip else "GO   ✅"
            print(
                f"  [CLF] {verdict} {Path(filepath).name} | "
                f"{agent.split('/')[-1][:15]} | "
                f"temp={temperature:.2f} | prob={prob:.0%}"
            )
        return skip

    def feature_importance(self) -> list[tuple[str, float]]:
        """Retourne l'importance des features triée par valeur absolue.

        Returns:
            Liste de tuples (feature_name, coefficient).
        """
        if not self._trained or self._model is None:
            return []
        coefs = self._model.named_steps["clf"].coef_[0]
        return sorted(zip(FEATURE_NAMES, coefs.tolist()), key=lambda x: abs(x[1]), reverse=True)

    def retrain_incremental(self) -> float:
        """Réentraîne avec les nouvelles données de experience_memory.jsonl.

        Returns:
            Nouveau F1-score.
        """
        return self.fit(force=True)


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys as _sys

    clf = MutationClassifier()
    f1 = clf.fit(force="--retrain" in _sys.argv)

    print(f"\nF1-score : {f1:.3f}")
    print("\nImportance des features :")
    for name, coef in clf.feature_importance():
        bar = ("+" if coef > 0 else "-") + "█" * int(abs(coef) * 5)
        print(f"  {name:12s} {coef:+.3f}  {bar}")

    # Test sur un fichier si passé en argument
    if len(_sys.argv) > 1 and not _sys.argv[1].startswith("--"):
        filepath = _sys.argv[1]
        print(f"\nPrédictions pour {filepath} :")
        for agent, temp in [
            ("groq/llama-3.3-70b-versatile", 0.30),
            ("ollama/qwen2.5-coder:7b", 0.30),
            ("groq/llama-3.3-70b-versatile", 0.10),
        ]:
            clf.should_skip(filepath, agent, temp)
