# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : metacognition / immunitaire (organe, READ-ONLY)

ORGANE : INTEGRITE DES METRIQUES — « mes scores internes mentent-ils sous la pression ? ».

Gap VERIFIE (audit veilles 2026-07-22) : le lot RLHF/reward-overoptimization enseigne une
LOI (Goodhart : toute metrique optimisee finit par mentir) et TROIS detecteurs — desaccord
entre juges, divergence score-vs-usage-reel (EvalStop : le monde tranche), saturation aux
extremes = gaming. Nokido VIT de scores internes (trust provider, novelty) mais n'avait
AUCUN organe pour les traiter comme structurellement suspects.

STRICTEMENT READ-ONLY : il LIT les scores et EMET des findings. Il ne mute JAMAIS un score
(corriger la metrique appartient a son organe proprietaire — ici on ne fait que SONNER).
C'est la microglie du scoring : elle signale l'inflammation, elle ne recable pas le neurone.

Anti-dup (rag_fts) : forge_trust_score CALCULE le score provider ; forge_novelty_search
CALCULE la nouveaute ; forge_rag_qualify pondere. AUCUN ne CROISE ces scores pour detecter
la derive Goodhart. Cet organe est transverse et passif.

CLI :
    LAFORGE_PYTHON app/forge_metric_integrity.py --scan
    LAFORGE_PYTHON app/forge_metric_integrity.py --history [--limit 20]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("LAFORGE_DB_PATH", str(ROOT / "RAG" / "embeddings.db")))

# Seuils (env-overridable). Un score PINNED aux bornes sur N observations = suspect.
SAT_HI = float(os.environ.get("LAFORGE_METRIC_SAT_HI", "0.98"))
SAT_LO = float(os.environ.get("LAFORGE_METRIC_SAT_LO", "0.02"))
DIVERGENCE = float(os.environ.get("LAFORGE_METRIC_DIVERGENCE", "0.4"))


def _rows(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _scan_provider_trust(con):
    """Divergence score-vs-usage : un provider bien noté mais JAMAIS choisi (ou l'inverse)
    = la metrique de trust ne predit plus la selection reelle (Goodhart / metrique morte)."""
    out = []
    rows = _rows(con, "SELECT provider, score, calls, successes, failures FROM provider_scores")
    if not rows:
        return out
    total_calls = sum((r[2] or 0) for r in rows) or 1
    for prov, score, calls, succ, fail in rows:
        score = float(score or 0.0)
        usage = (calls or 0) / total_calls
        # score haut, usage nul (jamais choisi malgre bonne note) OU inverse
        if score >= 0.7 and usage < 0.02 and (calls or 0) >= 0:
            out.append({"kind": "trust_usage_divergence", "target": prov,
                        "detail": "score=%.2f mais usage=%.1f%% — noté bon, jamais choisi"
                                  % (score, usage * 100), "severity": "med"})
        if (fail or 0) > 0 and (succ or 0) == 0 and score >= 0.5:
            out.append({"kind": "trust_stale", "target": prov,
                        "detail": "score=%.2f mais 0 succès / %d échecs — score non recalé"
                                  % (score, fail or 0), "severity": "high"})
    return out


def _scan_novelty(con):
    """Saturation : si la nouveauté est massivement pinned (tout '100% nouveau' ou tout
    '0'), le detecteur ne discrimine plus — c'est le faux-positif novelty mesure au 06-25."""
    out = []
    rows = _rows(con, "SELECT novelty FROM novelty_archive WHERE novelty IS NOT NULL "
                      "ORDER BY ROWID DESC LIMIT 200")
    vals = [float(r[0]) for r in rows if r and r[0] is not None]
    if len(vals) >= 20:
        hi = sum(1 for v in vals if v >= SAT_HI) / len(vals)
        lo = sum(1 for v in vals if v <= SAT_LO) / len(vals)
        if hi >= 0.8:
            out.append({"kind": "novelty_saturation_high", "target": "novelty_archive",
                        "detail": "%.0f%% des 200 derniers >= %.2f — ne discrimine plus"
                                  % (hi * 100, SAT_HI), "severity": "high"})
        if lo >= 0.8:
            out.append({"kind": "novelty_saturation_low", "target": "novelty_archive",
                        "detail": "%.0f%% des 200 derniers <= %.2f — détecteur muet"
                                  % (lo * 100, SAT_LO), "severity": "med"})
    return out


def _scan_biblio_relevance(con):
    """Desaccord juges : relevance elevee (le refine dit 'pertinent') mais rejet a l'insert
    (le schema/dedup dit non) = les deux juges de la veille divergent (cf RETENTION_ZERO)."""
    out = []
    rows = _rows(con, "SELECT COUNT(*) FROM biblio_raw WHERE status='rejected' "
                      "AND rejection_reason IS NOT NULL")
    n = rows[0][0] if rows else 0
    if n and n >= 20:
        out.append({"kind": "biblio_judge_disagreement", "target": "biblio_raw",
                    "detail": "%d entrées jugées pertinentes puis rejetées à l'insert" % n,
                    "severity": "low"})
    return out


def scan() -> dict:
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        findings = (_scan_provider_trust(con) + _scan_novelty(con)
                    + _scan_biblio_relevance(con))
        con.execute("CREATE TABLE IF NOT EXISTS metric_integrity_findings ("
                    "id TEXT PRIMARY KEY, kind TEXT, target TEXT, severity TEXT, "
                    "detail TEXT, created_at TEXT)")
        stamp = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        ins = 0
        import hashlib
        for f in findings:
            h = hashlib.md5((f["kind"] + f["target"]).encode()).hexdigest()[:16]
            try:
                con.execute("INSERT INTO metric_integrity_findings VALUES (?,?,?,?,?,?)",
                            (h, f["kind"], f["target"], f["severity"], f["detail"], stamp))
                ins += 1
            except sqlite3.IntegrityError:
                con.execute("UPDATE metric_integrity_findings SET detail=?, created_at=? "
                            "WHERE id=?", (f["detail"], stamp, h))
        con.commit()
        return {"findings": findings, "count": len(findings), "new_or_updated": ins}
    finally:
        con.close()


def history(limit=20):
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        rows = _rows(con, "SELECT kind, target, severity, detail, created_at "
                          "FROM metric_integrity_findings ORDER BY created_at DESC LIMIT ?",
                     (limit,))
        return [{"kind": a, "target": b, "severity": c, "detail": d, "at": e}
                for a, b, c, d, e in rows]
    finally:
        con.close()


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()
    if a.history:
        print(json.dumps(history(a.limit), ensure_ascii=False, indent=2))
        return 0
    if a.scan:
        res = scan()
        print(json.dumps({"count": res["count"], "new_or_updated": res["new_or_updated"]},
                         ensure_ascii=False))
        for f in res["findings"]:
            print("  [%s] %-26s %s — %s" % (f["severity"], f["kind"], f["target"], f["detail"]))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(_main())
