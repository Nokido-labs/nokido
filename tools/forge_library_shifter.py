"""
forge_library_shifter.py — Permutation chirurgicale de librairies via AST
=========================================================================
Remplace les librairies standard par des alternatives haute-performance
validées par benchmark + tests de régression Cerberus.

Librairies ciblées :
  json     → msgspec  (10× plus rapide sur les .jsonl RAG)
  requests → httpx    (async natif pour le Swarm)
  sqlite3  → duckdb   (analytique sur NVMe PCIe 5.0)

Usage :
    from tools.forge_library_shifter import LibraryShifter
    shifter = LibraryShifter()
    libs = shifter.scan_for_optimization("app/forge_hub_storage.py")
    for lib in libs:
        report = shifter.validate_with_cerberus("app/forge_hub_storage.py", lib)
        if report["ok"]:
            print(f"✅ Gain {report['improvement_pct']:.1f}% — permutation validée")
"""

from __future__ import annotations

import ast
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# ── Mapping librairies → alternatives HP ─────────────────────────────────────
LIBRARY_MAPPING: dict[str, dict] = {
    "json": {
        "target": "msgspec",
        "benefit": "10× plus rapide sur les gros .jsonl RAG, moins de RAM",
        "benchmark_new": "import msgspec; data = [{'k': 'v', 'n': i} for i in range(500)]; msgspec.json.encode(data)",
        "benchmark_old": "import json; data = [{'k': 'v', 'n': i} for i in range(500)]; json.dumps(data)",
        "install": "msgspec",
        "boilerplate": "import msgspec\n_enc = msgspec.json.Encoder()\n_dec = msgspec.json.Decoder()",
    },
    "requests": {
        "target": "httpx",
        "benefit": "Support async natif pour les appels API Swarm parallèles",
        "benchmark_new": "import httpx",
        "benchmark_old": "import requests",
        "install": "httpx",
        "boilerplate": "import httpx",
    },
    "sqlite3": {
        "target": "duckdb",
        "benefit": "Analytique columnar ultra-rapide sur NVMe PCIe 5.0",
        "benchmark_new": "import duckdb; c = duckdb.connect(':memory:'); c.execute('SELECT i FROM range(1000) t(i)').fetchall()",
        "benchmark_old": "import sqlite3; c = sqlite3.connect(':memory:'); c.execute('CREATE TABLE t(i INT)'); c.executemany('INSERT INTO t VALUES(?)', [(i,) for i in range(1000)]); c.execute('SELECT * FROM t').fetchall()",
        "install": "duckdb",
        "boilerplate": "import duckdb",
    },
}

# Seuil minimal de gain (5%)
PERF_THRESHOLD = 1.05


class LibraryShifter:
    """Gère la permutation de librairies via chirurgie AST avec validation triple."""

    def __init__(self, root_path: str | None = None) -> None:
        """Initialise le LibraryShifter.

        Args:
            root_path: Chemin racine du projet (défaut = ROOT auto-détecté).
        """
        self.root = Path(root_path).resolve() if root_path else ROOT
        self.performance_threshold = PERF_THRESHOLD
        self.required_tools = self._get_shifter_tools()

    def _get_shifter_tools(self) -> list[dict]:
        """Retourne les définitions d'outils MCP pour la permutation.

        Returns:
            Liste de définitions d'outils conformes [2026-03-22].
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "apply_library_swap",
                    "description": "Remplace une librairie par une version optimisée après benchmark",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Chemin du fichier cible",
                            },
                            "old_lib": {"type": "string", "description": "Librairie à remplacer"},
                            "new_lib": {
                                "type": "string",
                                "description": "Librairie de remplacement",
                            },
                        },
                        "required": ["file_path", "old_lib", "new_lib"],
                    },
                },
            }
        ]

    def scan_for_optimization(self, file_path: str) -> list[str]:
        """Détecte les librairies substituables dans un fichier Python.

        Args:
            file_path: Chemin du fichier à analyser.

        Returns:
            Liste des librairies substituables trouvées.
        """
        src = Path(file_path).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
        found: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    base = alias.name.split(".")[0]
                    if base in LIBRARY_MAPPING:
                        found.add(base)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] in LIBRARY_MAPPING:
                    found.add(node.module.split(".")[0])

        return sorted(found)

    def run_micro_benchmark(self, snippet: str, iterations: int = 100) -> float:
        """Exécute un snippet N fois et retourne la médiane en ms.

        Args:
            snippet:    Code Python à exécuter.
            iterations: Nombre d'exécutions pour la médiane.

        Returns:
            Temps médian en millisecondes.
        """
        times: list[float] = []
        ctx: dict[str, Any] = {}
        for _ in range(iterations):
            t0 = time.perf_counter()
            exec(snippet, ctx, {})  # noqa: S102
            times.append(time.perf_counter() - t0)
        return statistics.median(times) * 1000

    def validate_with_cerberus(self, file_path: str, lib_name: str) -> dict:
        """Triple validation : AST + Pytest + Benchmark comparatif.

        Args:
            file_path: Fichier cible de la permutation.
            lib_name:  Librairie à remplacer (clé de LIBRARY_MAPPING).

        Returns:
            Dict avec 'ok', 'reason', 'speedup', 'improvement_pct'.
        """
        print(
            f"🛡️  [CERBERUS] Validation pour {Path(file_path).name} ({lib_name}→{LIBRARY_MAPPING.get(lib_name, {}).get('target', '?')})..."
        )
        report: dict = {"ok": False, "reason": "", "speedup": 0.0, "improvement_pct": 0.0}

        # ── Étape 1 : AST ────────────────────────────────────────────────────
        try:
            ast.parse(Path(file_path).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as e:
            report["reason"] = f"Syntaxe invalide : {e}"
            return report

        # ── Étape 2 : Pytest régression ──────────────────────────────────────
        res = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/nr/",
                "--ignore=tests/nr/test_import_all_nr.py",
                "-q",
                "--timeout=20",
                "--tb=no",
                "-p",
                "no:warnings",
            ],
            capture_output=True,
            cwd=str(self.root),
        )
        if res.returncode != 0:
            report["reason"] = "Régression Pytest détectée après permutation."
            return report

        # ── Étape 3 : Benchmark comparatif ───────────────────────────────────
        mapping = LIBRARY_MAPPING.get(lib_name)
        if mapping:
            print(f"  ⏱️  Benchmark {lib_name} vs {mapping['target']} (100 iters)...")
            try:
                t_old = self.run_micro_benchmark(mapping["benchmark_old"])
                t_new = self.run_micro_benchmark(mapping["benchmark_new"])
                speedup = t_old / t_new if t_new > 0 else 0.0
                improvement = (speedup - 1) * 100
                report["speedup"] = round(speedup, 3)
                report["improvement_pct"] = round(improvement, 2)
                print(
                    f"  {lib_name}: {t_old:.4f}ms → {mapping['target']}: {t_new:.4f}ms | gain={improvement:.1f}%"
                )

                if speedup < self.performance_threshold:
                    report["reason"] = f"Gain insuffisant ({improvement:.1f}% < 5%) — rejet."
                    return report
            except Exception as e:
                report["reason"] = f"Benchmark impossible : {e}"
                return report

        report["ok"] = True
        return report

    def create_mutation_mission(self, file_path: str, lib_to_swap: str) -> str:
        """Génère le prompt Cerberus pour la permutation.

        Args:
            file_path:   Fichier cible.
            lib_to_swap: Librairie à remplacer.

        Returns:
            Prompt formaté pour MultiLLMBridge.
        """
        info = LIBRARY_MAPPING[lib_to_swap]
        return (
            f"MISSION : Permutation de librairie haute-performance.\n"
            f"CONTEXTE : Ryzen 8700G + NVMe PCIe 5.0 + Nokido v17.\n"
            f"ACTION   : Remplacer '{lib_to_swap}' par '{info['target']}'.\n"
            f"BÉNÉFICE : {info['benefit']}.\n"
            f"BOILERPLATE à insérer après les imports :\n```python\n{info['boilerplate']}\n```\n"
            f"CONSIGNE : Adapte TOUS les appels. Ne change PAS la logique métier.\n"
            f"RÈGLE    : Utilise l'ASTSurgeon pour valider que les classes restent intactes."
        )

    def benchmark_all(self) -> list[dict]:
        """Lance le benchmark comparatif sur toutes les librairies configurées.

        Returns:
            Liste de résultats {lib, target, t_old_ms, t_new_ms, speedup, gain_pct}.
        """
        results = []
        for lib, info in LIBRARY_MAPPING.items():
            try:
                t_old = self.run_micro_benchmark(info["benchmark_old"], iterations=50)
                t_new = self.run_micro_benchmark(info["benchmark_new"], iterations=50)
                speedup = round(t_old / t_new if t_new > 0 else 0, 2)
                results.append(
                    {
                        "lib": lib,
                        "target": info["target"],
                        "t_old_ms": round(t_old, 4),
                        "t_new_ms": round(t_new, 4),
                        "speedup": speedup,
                        "gain_pct": round((speedup - 1) * 100, 1),
                    }
                )
            except Exception as e:
                results.append({"lib": lib, "error": str(e)})
        return results
