# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : observabilite / metacognition (organe, ECRITURE BORNEE)

ORGANE : PROFILING PAR TOOL MCP — « ce tool coute-t-il ce qu'on croit ? ».

Item 2 du pack P2 des veilles (spec_pack_veilles_p2, lot ProMCP) : le routage
choisit aujourd'hui sur des couts ESTIMES a l'ecriture. Personne ne mesure ce que
coute REELLEMENT un appel de tool au chokepoint `ToolRegistry.dispatch`. Or c'est
le meme angle mort que la journee entiere du 2026-07-24 a documente : on decide sur
du declare, jamais sur du mesure.

Anti-dup (rag_fts + lecture des modules) : `forge_token_monitor` compte les tokens
par appel PROVIDER (LLM), `forge_tool_efficiency` classe les MODELES par use-case a
partir de `token_usage` / `network_log`. AUCUN des deux ne descend au niveau du TOOL
MCP — aucune table de metriques par tool n'existait (verifie sur sqlite_master).
Domaine neuf, volontairement etroit.

ECRITURE BORNEE : une ligne par appel, purge cablee dans forge_log_retention
(`promcp_tool_metrics`). L'enregistrement est best-effort et n'echoue JAMAIS vers
l'appelant : un profileur qui casse le dispatch serait pire que pas de profileur.

CLI :
    LAFORGE_PYTHON app/forge_promcp_profiler.py --stats [--hours 24]
    LAFORGE_PYTHON app/forge_promcp_profiler.py --costliest [--limit 10]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS promcp_tool_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT NOT NULL,
    ts REAL NOT NULL,
    duration_ms REAL NOT NULL,
    ok INTEGER NOT NULL DEFAULT 1,
    payload_bytes INTEGER DEFAULT 0,
    result_bytes INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_promcp_tool_ts ON promcp_tool_metrics(tool, ts);
"""

# Le profilage ne doit jamais devenir un cout a son tour : au-dela, on echantillonne.
_MAX_ROWS_HINT = int(os.environ.get("LAFORGE_PROMCP_MAX_ROWS", "200000"))


# Schema pose UNE fois par base et par processus : le rejouer a chaque INSERT prenait le verrou
# de embeddings.db a chaque appel de tool (mesure 27/09).
_SCHEMA_OK: set[str] = set()

try:
    from nokido_agent.app.forge_bounded_queue import EcrivainDiffere
except ImportError:  # lance par chemin (CLI) : app/ est sys.path[0]
    from forge_bounded_queue import EcrivainDiffere
# Fil d'ecriture unique du profileur ; il ne demarre qu'a la premiere ecriture differee.
_ECRIVAIN = EcrivainDiffere("promcp_profiler")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=5)
    if str(DB) not in _SCHEMA_OK:
        for stmt in _SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                c.execute(s)
        _SCHEMA_OK.add(str(DB))
    return c


def _inserer(ligne: tuple) -> None:
    c = _conn()
    try:
        c.execute(
            "INSERT INTO promcp_tool_metrics (tool, ts, duration_ms, ok, "
            "payload_bytes, result_bytes) VALUES (?,?,?,?,?,?)", ligne)
        c.commit()
    finally:
        c.close()


def record(tool: str, duration_ms: float, ok: bool = True,
           payload_bytes: int = 0, result_bytes: int = 0) -> None:
    """Trace UN appel. Best-effort absolu : aucune exception ne remonte.

    Appele depuis le chokepoint de dispatch, donc sur le chemin chaud : pas de
    lecture prealable, pas de calcul, un seul INSERT. Sur la boucle du hub, l'INSERT
    part dans un fil dedie : il attendait le verrou de embeddings.db (jusqu'a 5 s)
    EN BLOQUANT tout le hub -- 211 gels de boucle le 27/09. `ts` reste l'instant de
    l'appel, pas celui de l'ecriture.
    """
    if os.environ.get("LAFORGE_PROMCP_PROFILE", "1") == "0":
        return
    try:
        ligne = (str(tool)[:120], time.time(), round(float(duration_ms), 2),
                 1 if ok else 0, int(payload_bytes or 0), int(result_bytes or 0))
        if _ECRIVAIN.sur_une_boucle():
            _ECRIVAIN.soumettre(lambda: _inserer(ligne))
        else:
            _inserer(ligne)
    except Exception:  # noqa: BLE001  muet-ok : best-effort absolu, contrat du module
        pass


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((len(s) - 1) * p))))
    return round(s[k], 1)


def stats(since_hours: float = 24.0) -> dict[str, Any]:
    """Cout OBSERVE par tool sur une fenetre.

    p95 et pas seulement la moyenne : c'est la queue qui fait attendre l'appelant,
    et une moyenne lisse exactement ce qu'on cherche a voir.
    """
    cutoff = time.time() - max(60.0, float(since_hours) * 3600.0)
    try:
        c = _conn()
        try:
            rows = c.execute(
                "SELECT tool, duration_ms, ok FROM promcp_tool_metrics WHERE ts>=?",
                (cutoff,),
            ).fetchall()
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120], "tools": {}}

    per: dict[str, dict] = {}
    for tool, dur, ok in rows:
        d = per.setdefault(tool, {"durations": [], "n": 0, "errors": 0})
        d["durations"].append(float(dur))
        d["n"] += 1
        if not ok:
            d["errors"] += 1

    out: dict[str, Any] = {}
    for tool, d in per.items():
        ds = d["durations"]
        out[tool] = {
            "n": d["n"],
            "error_rate": round(d["errors"] / d["n"], 3) if d["n"] else 0.0,
            "p50_ms": _percentile(ds, 0.50),
            "p95_ms": _percentile(ds, 0.95),
            "mean_ms": round(sum(ds) / len(ds), 1) if ds else 0.0,
            "total_ms": round(sum(ds), 1),
        }
    return {"ok": True, "since_hours": since_hours, "n_calls": len(rows), "tools": out}


def costliest(limit: int = 10, since_hours: float = 24.0) -> list[dict]:
    """Tools les plus couteux en temps CUMULE — la cible d'optimisation reelle.

    Un tool lent appele deux fois coute moins qu'un tool tiede appele mille fois ;
    trier sur la latence unitaire designerait la mauvaise cible.
    """
    s = stats(since_hours)
    if not s.get("ok"):
        return []
    rows = [{"tool": t, **m} for t, m in s["tools"].items()]
    rows.sort(key=lambda r: r["total_ms"], reverse=True)
    return rows[:max(1, int(limit))]


def observed_cost_ms(tool: str, since_hours: float = 168.0) -> float | None:
    """Cout unitaire OBSERVE d'un tool (p50), ou None si jamais mesure.

    Destine au routage : `None` doit se lire « je ne sais pas », jamais « gratuit ».
    """
    s = stats(since_hours)
    m = (s.get("tools") or {}).get(tool)
    return m["p50_ms"] if m else None


def _main() -> int:
    ap = argparse.ArgumentParser(description="Profiling par tool MCP (cout observe)")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--costliest", action="store_true")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    if a.costliest:
        print(json.dumps(costliest(a.limit, a.hours), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(stats(a.hours), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
