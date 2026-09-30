"""tools/forge_swebench_strategy_debate.py - debat multi-LLM neuro-symbolique.

Use case : pour decider de la STRATEGIE prochaine sur SWE-bench (10/50
baseline -> objectif 20+), on consulte 3 LLMs cloud divergent via dspy
StrategyHypothesis Signature, puis on arbitre SYMBOLIQUEMENT (pas un 4eme
LLM, pas un vote semantique de richesse rhetorique).

Gouvernance Marcus :
  1. Cloud LLMs (cerebras/groq/github) = GENERATEURS d hypotheses divergentes
  2. signature_call impose schema JSON strict (hypothesis/evidence/
     counter_evidence/confidence_self)
  3. Arbitrage SYMBOLIQUE : Jaccard keyword overlap pour convergence + cap
     confidence_self normalise. Le choix = (a) consensus le plus haut OU
     (b) hypothese avec meilleure confidence pondere par convergence.

Sortie : sandbox/swebench_debate/<timestamp>.json + decision_text.md.

Usage :
  LAFORGE_PYTHON tools/forge_swebench_strategy_debate.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_dspy_router import signature_call  # noqa: E402
from nokido_agent.app.forge_machine_vault import vault_get  # noqa: E402

DEBATE_DIR = ROOT / "sandbox" / "swebench_debate"
DEBATE_DIR.mkdir(parents=True, exist_ok=True)

PROVIDERS = ["cerebras", "groq", "github"]


PROBLEM = (
    "SWE-bench score actuel Nokido = 10/50 (echantillon mixte). "
    "Stages livres : 0 (distillation issue), 3a/3b/3c (gen AST + multi-fichiers + "
    "temperature staged), 4 (linter-gate + PASS_TO_PASS gate + troncature). "
    "Stages PENDING : 1 (repomap + dep-graph cross-fichier via warpgrep v2), "
    "2 (skeleton pruning Coder). Modules disponibles : forge_warpgrep v1 "
    "actif, forge_graph_universal (PPR/centrality), forge_scorecard (juge "
    "symbolique 6 axes), Ollama qwen2.5-coder:7b local gratuit. NPU XDNA1 "
    "Radeon 780M pour ONNX embeddings. Cible : 20+/50 a la prochaine run."
)

CONSTRAINTS = (
    "Budget : 1 cycle de dev (~4-8h). Pas de GPU cloud paye. Free tier cloud "
    "OK pour drafts (cerebras gpt-oss-120b, groq llama-3.3-70b, github gpt-4o). "
    "Verification = harness Docker officiel SWE-bench."
)


# === Extraction de keywords symboliques ======================================

_STOPWORDS = {
    "le",
    "la",
    "les",
    "de",
    "des",
    "du",
    "un",
    "une",
    "et",
    "ou",
    "que",
    "qui",
    "pour",
    "dans",
    "sur",
    "par",
    "avec",
    "au",
    "aux",
    "ce",
    "cette",
    "ces",
    "il",
    "elle",
    "ils",
    "elles",
    "est",
    "sont",
    "etre",
    "avoir",
    "the",
    "a",
    "an",
    "of",
    "to",
    "in",
    "on",
    "and",
    "or",
    "for",
    "with",
    "is",
    "are",
    "be",
    "have",
    "has",
    "this",
    "that",
    "it",
    "as",
    "by",
    "from",
    "at",
    "but",
    "not",
    "all",
    "any",
    "more",
    "than",
    "then",
}


def _keywords(text: str, min_len: int = 4) -> set[str]:
    """Extraction simple : alphabetique + lowercase + filter stopwords."""
    words = re.findall(r"[a-zA-Z_]{%d,}" % min_len, text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0


# === Run debate ===============================================================


def run_debate(token: str, problem: str = "", constraints: str = "", providers=None) -> dict:
    """Pour chaque provider, signature_call StrategyHypothesis. Retourne
    list[{provider, fields, ok, keywords}] + consensus matrix + winner.
    problem/constraints vides -> constantes historiques (mai 2026)."""
    problem = problem or PROBLEM
    constraints = constraints or CONSTRAINTS
    proposals: list[dict] = []
    for prov in providers or PROVIDERS:
        print(f"\n[debate] provider={prov} ...")
        t0 = time.monotonic()
        r = signature_call(
            "StrategyHypothesis",
            {"problem": problem, "constraints": constraints},
            prov,
            token,
            max_tokens=8192,
            timeout_s=120,
        )
        dt = time.monotonic() - t0
        if not r.get("ok"):
            print(f"  [{prov}] FAIL : {r.get('error', '?')[:200]}")
            proposals.append(
                {"provider": prov, "ok": False, "error": r.get("error"), "ms": int(dt * 1000)}
            )
            continue
        f = r["fields"]
        text_corpus = " ".join([f.get("hypothesis", ""), f.get("evidence", "")])
        kw = _keywords(text_corpus)
        print(
            f"  [{prov}] OK conf={f.get('confidence_self', '?')} kw={len(kw)} ms={int(dt * 1000)}"
        )
        proposals.append(
            {
                "provider": prov,
                "ok": True,
                "ms": int(dt * 1000),
                "fields": f,
                "keywords": sorted(kw),
            }
        )

    # Symbolic convergence matrix
    print("\n[debate] symbolic Jaccard matrix :")
    matrix = {}
    for i, a in enumerate(proposals):
        if not a.get("ok"):
            continue
        matrix[a["provider"]] = {}
        for b in proposals:
            if a == b or not b.get("ok"):
                continue
            j = _jaccard(set(a["keywords"]), set(b["keywords"]))
            matrix[a["provider"]][b["provider"]] = round(j, 3)
        print(f"  {a['provider']:10s} -> {matrix[a['provider']]}")

    # Decision : max(consensus_avg * confidence_self) ; tie -> highest conf
    print("\n[debate] decision criteria : consensus_avg * confidence_self")
    scored = []
    for p in proposals:
        if not p.get("ok"):
            continue
        peer_sims = list(matrix.get(p["provider"], {}).values())
        consensus = sum(peer_sims) / max(len(peer_sims), 1) if peer_sims else 0.0
        try:
            conf = float(p["fields"].get("confidence_self", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        score = consensus * conf
        scored.append(
            {
                "provider": p["provider"],
                "consensus": round(consensus, 3),
                "confidence_self": round(conf, 3),
                "final_score": round(score, 3),
                "hypothesis": p["fields"].get("hypothesis", "")[:300],
            }
        )
        print(
            f"  {p['provider']:10s} consensus={consensus:.3f}  conf={conf:.3f}  score={score:.3f}"
        )

    scored.sort(key=lambda x: -x["final_score"])
    winner = scored[0] if scored else None
    return {
        "ts": time.time(),
        "proposals": proposals,
        "convergence_matrix": matrix,
        "scored": scored,
        "winner": winner,
    }


def main() -> int:
    # 2b-6 (2026-09-28) : jeton propre de DSPY_ROUTER, sinon le maitre en transition dite
    # -- par la brique `jeton_hub`, plus le maitre lu en direct au coffre machine.
    from nokido_agent.app.forge_agent_credential import jeton_hub

    token = jeton_hub("DSPY_ROUTER") or ""
    if not token:
        print("ERR : aucun jeton pour DSPY_ROUTER (ni propre, ni maitre en transition)")
        return 1
    # Question du jour : problem_*.json le plus récent (déposé avant le run,
    # run_job ne transmet pas d'argv). Absent -> constantes historiques.
    problem, constraints, providers = "", "", None
    pfiles = sorted(DEBATE_DIR.glob("problem_*.json"))
    if pfiles:
        try:
            pj = json.loads(pfiles[-1].read_text(encoding="utf-8"))
            problem = pj.get("problem", "")
            constraints = pj.get("constraints", "")
            providers = pj.get("providers") or None
            print(f"[debate] problem file -> {pfiles[-1].name}")
        except Exception as ex:
            print(f"[debate] problem file illisible ({ex}) -> constantes historiques")
    out = run_debate(token, problem, constraints, providers)
    ts = int(time.time())
    json_path = DEBATE_DIR / f"debate_{ts}.json"
    json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[debate] saved -> {json_path}")
    if out["winner"]:
        md_path = DEBATE_DIR / f"decision_{ts}.md"
        w = out["winner"]
        md = (
            f"# SWE-bench Strategy Debate Decision\n\n"
            f"**Winner provider :** {w['provider']}\n"
            f"**Consensus :** {w['consensus']}  "
            f"**Self-confidence :** {w['confidence_self']}  "
            f"**Final score :** {w['final_score']}\n\n"
            f"## Hypothese retenue\n\n{w['hypothesis']}\n\n"
            f"## Justification\n\n"
            f"Score = consensus * confidence_self. Convergence Jaccard "
            f"keyword sur evidence + hypothesis avec les autres providers.\n"
        )
        md_path.write_text(md, encoding="utf-8")
        print(f"[debate] decision_md -> {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
