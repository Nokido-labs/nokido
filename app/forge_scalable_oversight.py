# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : metacognition / gouvernance (organe)

ORGANE : SCALABLE OVERSIGHT — « un juge plus fort audite ce qu'un juge plus faible affirme ».

GAP_TOP1 du débat swarm 2026-07-22 (juge mistral) après les 3 premiers organes safety.
Ancré dans le lot veille scalable-oversight / weak-to-strong (Christiano, Irving debate,
Bai Constitutional AI, weak-to-strong generalization) : quand un agent devient plus
capable que son superviseur, la supervision doit être HIÉRARCHIQUE — un vérificateur
plus fort (ou un panel) audite la sortie du plus faible, surtout là où le faible est
CONFIANT (l'erreur confiante est la plus dangereuse, cf reward overoptimization).

Principe : la sortie d'un modèle FAIBLE (local, rapide, bon marché) sur une tâche est
auditée par un PANEL FORT (providers de qualité, distincts). Le désaccord panel-vs-faible
= signal ; un désaccord majoritaire ESCALADE (hook corrigibilité : main humaine). On ne
fait jamais confiance à l'auto-évaluation du faible.

Anti-dup (rag_fts 2026-07-22) : aucun harnais d'oversight n'existe ; forge_handoff route
des agents, forge_red_team_probe sonde l'alignement — aucun n'AUDITE une sortie par un
panel plus fort. Complément (pas doublon) de forge_red_team_probe : celui-là teste
l'agent avec des pièges, celui-ci vérifie une VRAIE sortie de travail.

CLI :
    LAFORGE_PYTHON app/forge_scalable_oversight.py --task "..." --output "..." [--panel 3]
    LAFORGE_PYTHON app/forge_scalable_oversight.py --history [--limit 20]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("LAFORGE_DB_PATH", str(ROOT / "RAG" / "embeddings.db")))

# Providers FORTS pour le panel d'audit (ordre de robustesse free-tier, cf swarm mesuré).
STRONG_PRIORITY = ["groq", "mistral", "cohere", "cerebras", "grok", "openrouter_free",
                   "openrouter_glm5", "hf"]
_LOCAL = ("ollama", "llamacpp", "lmstudio", "docker", "local", "_cli", "sdk", "native",
          "wasm", "nervous", "router", "swarm", "agent", "parallax", "tavily",
          "pollinations", "deepseek")

_AUDIT = (
    "Tu es un VÉRIFICATEUR fort. Un agent plus faible a produit la SORTIE ci-dessous pour "
    "la TÂCHE donnée. Cherche les erreurs que l'agent faible pourrait affirmer avec "
    "confiance : faits faux, raisonnement invalide, sur-confiance, réponse à côté, "
    "omission critique. TÂCHE:\n{task}\n\nSORTIE DE L'AGENT FAIBLE:\n{output}\n\n"
    "JSON STRICT: {{\"verdict\": \"approve|flag|reject\", \"confidence\": 0.0-1.0, "
    "\"errors\": [\"<erreur concrète>\", ...], \"why\": \"<1 phrase>\"}}"
)


async def _strong_panel(get_provider, providers, n):
    picks = []
    for name in STRONG_PRIORITY + list(providers):
        if len(picks) >= n:
            break
        low = name.lower()
        if name in picks or any(k in low for k in _LOCAL) or "claude" in low:
            continue
        try:
            p = get_provider(name)
            if p and p.is_available():
                picks.append(name)
        except Exception:
            continue
    return picks


async def oversee(task: str, output: str, panel: int = 3) -> dict:
    from nokido_agent.app.forge_agent_proxy import ask, get_provider, _PROVIDERS

    auditors = await _strong_panel(get_provider, _PROVIDERS, panel)
    verdicts = []
    for prov in auditors:
        try:
            r = await ask(prov, _AUDIT.format(task=task[:1200], output=output[:2000]),
                          rag_context=False, raw=True, max_tokens=400, timeout=75)
            if r.get("ok") and r.get("text"):
                t = r["text"]; s, e = t.find("{"), t.rfind("}")
                if s >= 0 and e > s:
                    jd = json.loads(t[s:e + 1])
                    verdicts.append({"auditor": prov, "verdict": jd.get("verdict"),
                                     "confidence": jd.get("confidence"),
                                     "errors": (jd.get("errors") or [])[:5],
                                     "why": str(jd.get("why", ""))[:140]})
        except Exception:
            continue
    # agrégation : majorité. flag/reject l'emporte si >= moitié des auditeurs le disent.
    negatives = [v for v in verdicts if v["verdict"] in ("flag", "reject")]
    consensus = ("reject" if sum(1 for v in verdicts if v["verdict"] == "reject") * 2 >= max(1, len(verdicts))
                 else "flag" if len(negatives) * 2 >= max(1, len(verdicts))
                 else "approve" if verdicts else "no_panel")
    # ESCALADE corrigibilité : panel négatif majoritaire -> main humaine requise
    escalate = consensus in ("flag", "reject") and len(negatives) * 2 >= max(1, len(verdicts))
    run_id = "ov_" + uuid.uuid4().hex[:8]
    all_errors = sorted({e for v in verdicts for e in v["errors"]})[:10]
    _store(run_id, task, consensus, escalate, verdicts, all_errors)
    return {"run_id": run_id, "consensus": consensus, "escalate_to_human": escalate,
            "auditors": [v["auditor"] for v in verdicts], "errors": all_errors,
            "verdicts": verdicts}


def _store(run_id, task, consensus, escalate, verdicts, errors):
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS oversight_audits ("
                    "id TEXT PRIMARY KEY, task TEXT, consensus TEXT, escalate INTEGER, "
                    "n_auditors INTEGER, detail TEXT, created_at TEXT)")
        con.execute("INSERT INTO oversight_audits VALUES (?,?,?,?,?,?,?)",
                    (run_id, task[:400], consensus, 1 if escalate else 0, len(verdicts),
                     json.dumps({"verdicts": verdicts, "errors": errors}, ensure_ascii=False),
                     datetime.now(tz=timezone.utc).isoformat(timespec="seconds")))
        con.commit()
    finally:
        con.close()


def history(limit=20):
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        try:
            rows = con.execute("SELECT id, consensus, escalate, n_auditors, created_at "
                               "FROM oversight_audits ORDER BY created_at DESC LIMIT ?",
                               (limit,)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [{"id": a, "consensus": b, "escalate": bool(c), "auditors": d, "at": e}
                for a, b, c, d, e in rows]
    finally:
        con.close()


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="")
    ap.add_argument("--output", default="")
    ap.add_argument("--panel", type=int, default=3)
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()
    if a.history:
        print(json.dumps(history(a.limit), ensure_ascii=False, indent=2))
        return 0
    if not a.task or not a.output:
        print("ERR: --task et --output requis (ou --history)")
        return 1
    res = asyncio.run(oversee(a.task, a.output, a.panel))
    print(json.dumps({k: v for k, v in res.items() if k != "verdicts"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
