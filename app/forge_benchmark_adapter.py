"""
forge_benchmark_adapter.py — lecture programmatique des scores de benchmark
(HumanEval / BFCL / SWE-bench) pour le signal de fitness eval-driven.

ISOLÉ + SÛR : lit seulement les derniers JSON produits par les runners
(RAG/{humaneval,bfcl}/*.json ; SWE-bench : swebench_dir()). NE LANCE PAS les benchmarks (coûteux,
LLM) et ne patche rien. Sert au pattern `eval_fitness` de la boucle autonome
pour DÉTECTER une régression et émettre une proposal (effecteur = self_patcher,
gated séparément). Aligné anti-régression : surveiller, pas dégrader.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `swebench_cache_dir` — Cache repo_map SWE-bench, voisin du dossier de travail ; SWEBENCH_CACHE_DIR le deplace.
- `swebench_dir` — Dossier de travail SWE-bench (clones, predictions, evaluations) -- resolveur UNIQUE.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

RAG = Path(__file__).resolve().parent.parent / "RAG"
_DEPOT = RAG.parent


def swebench_dir() -> Path:
    """Dossier de travail SWE-bench (clones, predictions, evaluations) -- resolveur UNIQUE.

    HORS de RAG/ depuis le 2026-09-27, decision owner : SWE-bench n'a rien a faire dans le
    volume chiffre du savoir. Defaut `sandbox/workspace/swebench` (ignore par git, inscriptible
    par les comptes sandbox) ; SWEBENCH_DIR le deplace. L'historique de mai (0 resolu sur 23
    et sur 10) est archive, verifie au sha256, dans E:\\LaForge_tiede\\swebench.
    Relu a CHAQUE appel : une variable posee apres l'import est vue.
    """
    return Path(os.environ.get("SWEBENCH_DIR") or (_DEPOT / "sandbox" / "workspace" / "swebench"))


def swebench_cache_dir() -> Path:
    """Cache repo_map SWE-bench, voisin du dossier de travail ; SWEBENCH_CACHE_DIR le deplace."""
    return Path(os.environ.get("SWEBENCH_CACHE_DIR") or (swebench_dir().parent / "swebench_cache"))


def _latest(glob: str, key: str, base: Path | None = None):
    try:
        files = list((base or RAG).glob(glob))
        if not files:
            return None
        latest = max(files, key=lambda p: p.stat().st_mtime)
        return json.loads(latest.read_text(encoding="utf-8")).get(key)
    except Exception:
        return None


def humaneval_score(provider: str = "*") -> float | None:
    return _latest(f"humaneval/humaneval_{provider}_*.json", "pass_rate")


def bfcl_score(provider: str = "*", category: str = "*") -> float | None:
    return _latest(f"bfcl/bfcl_{provider}_{category}_*.json", "pass_rate")


def swebench_score(variant: str = "*") -> float | None:
    return _latest(f"eval_{variant}_*.json", "resolve_rate", swebench_dir())


def cognitive_score() -> float | None:
    """Efficacite du RAISONNEMENT, pas seulement du resultat.

    HumanEval, BFCL et SWE mesurent une SORTIE : deux executions rendant toutes
    deux SUCCESS — 8 etapes contre 31 appels dont 12 inutiles — y obtiennent le
    meme verdict. La regression cognitive leur est invisible.

    `tools/forge_cognitive_fitness.py --emit` ecrit ce releve au meme format
    (`pass_rate`), donc `detect_regression` le traite sans une ligne de plus :
    une chute de plus de 5 points declenche la meme proposal que pour les autres.
    """
    return _latest("cognitive/cognitive_*.json", "pass_rate")


def latest_scores() -> dict:
    """Derniers scores disponibles, par benchmark (omet les absents)."""
    cand = {
        "humaneval": humaneval_score(),
        "bfcl": bfcl_score(),
        "swebench": swebench_score(),
        "cognitif": cognitive_score(),
    }
    return {k: float(v) for k, v in cand.items() if v is not None}


def detect_regression(prev: dict, cur: dict, thresh: float = 5.0) -> list[str]:
    """Liste des benchmarks ayant régressé de > thresh points vs prev."""
    out = []
    for b, v in cur.items():
        p = prev.get(b)
        if p is not None and v < p - thresh:
            out.append(f"{b}: {p}% -> {v}% (-{round(p - v, 1)}pts)")
    return out


if __name__ == "__main__":
    s = latest_scores()
    print("latest_scores", s)
