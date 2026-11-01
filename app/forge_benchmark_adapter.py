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


# Validite d'une MESURE (owner 26/10). Mesure : HumanEval « 7,3 % » = 152 llm_error sur 164 (les 12 cas executes ont
# tous reussi), BFCL date du 31/05, cognitif du 14/08 -- et eval_fitness proposait des correctifs sur ces chiffres.
AGE_MAX_JOURS = 30.0      # au-dela, le score decrit un corps qui n'existe plus
SEUIL_PANNE = 0.5         # part des cas perdus par panne de fournisseur au-dela de laquelle ce n'est plus une mesure
_PANNES = ("llm_error", "provider_error", "api_error", "timeout", "rate_limit", "quota")
# MEMES motifs que les lecteurs de latest_scores (defauts « * ») : on juge le fichier qui a donne le score.
_SOURCES = {
    "humaneval": "humaneval/humaneval_*_*.json",
    "bfcl": "bfcl/bfcl_*_*_*.json",
    "swebench": "eval_*_*.json",
    "cognitif": "cognitive/cognitive_*.json",
}


def validite_mesure(banc: str, now: float | None = None) -> dict:
    """{valide, raison, age_j, fichier} : un score n'est une MESURE que s'il est FRAIS et pas DOMINE par des pannes.

    ABSENT / ILLISIBLE / PERIME / NON_MESURE -> valide False, raison dite ; jamais un score tenu pour vrai par defaut."""
    import time as _time

    motif = _SOURCES.get(banc)
    if motif is None:
        return {"valide": False, "raison": "INCONNU : banc %r sans source declaree" % banc}
    base = swebench_dir() if banc == "swebench" else RAG
    try:
        files = list(base.glob(motif))
    except Exception as e:  # noqa: BLE001 - dossier illisible
        return {"valide": False, "raison": "ILLISIBLE : %s" % type(e).__name__}
    if not files:
        return {"valide": False, "raison": "ABSENT : aucun resultat %s" % motif}
    f = max(files, key=lambda p: p.stat().st_mtime)
    age_j = round(((now or _time.time()) - f.stat().st_mtime) / 86400, 1)
    out = {"fichier": f.name, "age_j": age_j}
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {**out, "valide": False, "raison": "ILLISIBLE : %s (%s)" % (f.name, type(e).__name__)}
    if age_j > AGE_MAX_JOURS:
        return {**out, "valide": False, "raison": "PERIME : %s j > %s j (%s)" % (age_j, AGE_MAX_JOURS, f.name)}
    res = doc.get("results") if isinstance(doc.get("results"), list) else []
    n = int(doc.get("n_total") or len(res) or 0)
    raisons = doc.get("fail_reasons") or {}
    pannes = sum(int(v or 0) for k, v in raisons.items() if any(p in str(k).lower() for p in _PANNES))
    pannes = max(pannes, sum(1 for r in res if any(p in str((r or {}).get("reason", "")).lower() for p in _PANNES)))
    if n and pannes / n >= SEUIL_PANNE:
        return {**out, "valide": False,
                "raison": "NON_MESURE : %d/%d cas perdus par panne de fournisseur (%s)" % (pannes, n, f.name)}
    return {**out, "valide": True, "raison": "mesure fraiche (%s j)" % age_j}


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
