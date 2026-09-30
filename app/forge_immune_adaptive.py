"""forge_immune_adaptive.py — Immunité adaptative biomimétique (anticorps appris).

Mapping bio↔code :
- Antigène         = pattern d'attaque vu (DLP detected, prompt injection, SSRF beacon...)
- Lymphocyte B     = cette table immune_antibodies (mémoire spécifique)
- Anticorps        = signature pattern + counter (appris depuis exposition)
- Mémoire immune   = decay lent (90j) — anticorps non rappelés s'éteignent
- Plasma cell      = production rapide à la 2e exposition
- Auto-immunité    = anti-pattern : ne pas créer d'anticorps contre des patterns "self"

PROBLÈME RÉEL ADRESSÉ
=====================
forge_semantic_firewall = immunité INNÉE (regex hardcoded). Aucun apprentissage
des nouveaux patterns d'attaque vus en mcp_audit.log status=ERR. Si un nouveau
pattern d'injection apparaît, il est détecté la 1ère fois (peut-être) puis
oublié.

PIPELINE
========
1. Scan mcp_audit.log entries status=ERR / WARN avec match firewall
2. Extract pattern (n-gram char + token) → signature
3. INSERT OR UPDATE immune_antibodies (count++)
4. Decay 90j si pas re-rencontré
5. API check_request(text) : match existing antibodies → block fast (mémoire)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SANDBOX = ROOT / "sandbox"
AUDIT_LOG = ROOT / "logs" / "mcp_audit.log"

DEFAULT_INTERVAL_S = int(os.environ.get("LAFORGE_IMMUNE_INTERVAL_S", "3600"))
ANTIBODY_DECAY_DAYS = 90
MIN_PATTERN_LEN = 8  # ne pas faire d'anticorps sur < 8 chars (faux positifs)
MAX_PATTERN_LEN = 80  # cap pour éviter signatures trop spécifiques


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS immune_antibodies (
        signature_hash TEXT PRIMARY KEY,
        pattern        TEXT NOT NULL,
        kind           TEXT NOT NULL,   -- injection / ssrf / pii_leak / canary / unknown
        count          INTEGER NOT NULL DEFAULT 1,
        first_seen     TEXT NOT NULL,
        last_seen      TEXT NOT NULL,
        severity       REAL NOT NULL,   -- 0.0-1.0
        confidence     REAL NOT NULL,   -- monte avec count
        meta           TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_immune_kind ON immune_antibodies(kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_immune_seen ON immune_antibodies(last_seen DESC)")
    conn.commit()


# Patterns connus de la firewall (pour classifier les nouveaux antigènes)
KIND_PATTERNS = {
    "injection": [r"ignore.*(previous|instructions)", r"forget.*system", r"\\\\n#\\s*ROOT"],
    "ssrf": [r"169\\.254\\.169\\.254", r"localhost.*\\d{2,5}", r"file://", r"gopher://"],
    "pii_leak": [r"\\b\\d{3}-\\d{2}-\\d{4}\\b", r"\\b\\d{16}\\b"],  # SSN-like, CC-like
    "canary": [r"nokido_canary", r"forge_canary"],
}


def _classify(pattern: str) -> str:
    """Classifie un pattern dans une famille connue (ou 'unknown')."""
    p = pattern.lower()
    for kind, regexes in KIND_PATTERNS.items():
        for rx in regexes:
            if re.search(rx, p, re.IGNORECASE):
                return kind
    return "unknown"


def _signature(pattern: str) -> str:
    """Signature normalisée pour dédup (case-fold + strip whitespace)."""
    norm = re.sub(r"\s+", " ", pattern.strip().lower())[:MAX_PATTERN_LEN]
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def learn_from_audit(conn, since_hours: int = 24) -> dict:
    """Scan mcp_audit.log → extrait patterns ERR/WARN comme antigènes."""
    if not AUDIT_LOG.exists():
        return {"learned": 0, "audit_missing": True}

    cutoff = (datetime.now() - timedelta(hours=since_hours)).strftime("%Y-%m-%dT%H:%M:%S")
    learned = 0
    seen_signatures = set()

    try:
        lines = AUDIT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {"learned": 0, "error": "audit_read_fail"}

    # Garde seulement les N dernières lignes (économie)
    lines = lines[-5000:]

    for line in lines:
        if "ERR" not in line and "WARN" not in line:
            continue
        if cutoff not in line[:25] and line[:25] < cutoff:
            continue
        # Format approximatif : ts | channel | meta_json | status
        # Extraire le payload "in" ou "out" si présent
        m = re.search(r'"in":\s*"([^"]{8,300})"', line)
        if not m:
            m = re.search(r'"out":\s*"([^"]{8,300})"', line)
        if not m:
            continue
        candidate = m.group(1)
        if len(candidate) < MIN_PATTERN_LEN:
            continue
        # Tronquer + extraire pattern signifiant (mots-clés bruts ne servent pas)
        pattern = candidate[:MAX_PATTERN_LEN]
        sig = _signature(pattern)
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)

        kind = _classify(pattern)
        if kind == "unknown":
            continue  # éviter d'apprendre du bruit (auto-immunité prevention)

        severity = {"injection": 0.8, "ssrf": 0.9, "pii_leak": 0.7, "canary": 0.6}.get(kind, 0.5)

        # INSERT OR UPDATE
        existing = conn.execute("SELECT count FROM immune_antibodies WHERE signature_hash=?", (sig,)).fetchone()
        now = datetime.now().isoformat()
        if existing:
            conn.execute(
                "UPDATE immune_antibodies SET count=count+1, last_seen=?, "
                "confidence=MIN(1.0, confidence + 0.1) WHERE signature_hash=?",
                (now, sig),
            )
        else:
            conn.execute(
                "INSERT INTO immune_antibodies(signature_hash, pattern, kind, "
                "count, first_seen, last_seen, severity, confidence) "
                "VALUES (?, ?, ?, 1, ?, ?, ?, 0.3)",
                (sig, pattern, kind, now, now, severity),
            )
            learned += 1
    conn.commit()

    # Decay : anticorps non rencontrés depuis ANTIBODY_DECAY_DAYS → archive
    cutoff_decay = (datetime.now() - timedelta(days=ANTIBODY_DECAY_DAYS)).isoformat()
    n_archived = conn.execute(
        "DELETE FROM immune_antibodies WHERE last_seen < ? AND count < 3", (cutoff_decay,)
    ).rowcount
    conn.commit()

    return {"learned": learned, "archived": n_archived, "scanned_lines": len(lines)}


def check_request(text: str) -> dict:
    """API publique : vérifie un text contre les anticorps en mémoire.

    Renvoie {match: bool, antibody: dict | None, action: 'block'|'log'|'allow'}.
    Utilisable depuis forge_semantic_firewall.pre_flight() en complément des
    regex hardcoded.
    """
    if not text or len(text) < MIN_PATTERN_LEN:
        return {"match": False, "antibody": None, "action": "allow"}
    conn = _conn()
    _ensure_schema(conn)
    rows = conn.execute(
        "SELECT signature_hash, pattern, kind, count, severity, confidence "
        "FROM immune_antibodies WHERE confidence > 0.4 ORDER BY confidence DESC LIMIT 200"
    ).fetchall()
    conn.close()

    text_lower = text.lower()
    for sig, pat, kind, count, sev, conf in rows:
        # Match approximatif : substring lower-case
        if pat.lower() in text_lower:
            action = "block" if (sev * conf) > 0.5 else "log"
            return {
                "match": True,
                "antibody": {
                    "signature_hash": sig,
                    "pattern": pat[:60],
                    "kind": kind,
                    "count": count,
                    "severity": sev,
                    "confidence": conf,
                },
                "action": action,
            }
    return {"match": False, "antibody": None, "action": "allow"}


def stats(conn) -> dict:
    by_kind = dict(conn.execute("SELECT kind, COUNT(*) FROM immune_antibodies GROUP BY kind").fetchall())
    total = conn.execute("SELECT COUNT(*) FROM immune_antibodies").fetchone()[0]
    avg_conf = conn.execute("SELECT AVG(confidence) FROM immune_antibodies").fetchone()[0] or 0.0
    top = conn.execute(
        "SELECT pattern, kind, count, ROUND(confidence,2) FROM immune_antibodies ORDER BY count DESC LIMIT 5"
    ).fetchall()
    return {
        "total_antibodies": total,
        "by_kind": by_kind,
        "avg_confidence": round(avg_conf, 3),
        "top5": [{"pattern": p[:60], "kind": k, "count": c, "conf": cf} for p, k, c, cf in top],
    }


def run_cycle() -> dict:
    conn = _conn()
    _ensure_schema(conn)
    t0 = time.time()
    learn = learn_from_audit(conn, since_hours=24)
    s = stats(conn)
    conn.close()
    return {
        "ts": datetime.now().isoformat(),
        "duration_s": round(time.time() - t0, 2),
        "learning": learn,
        "stats": s,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido immune adaptive")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--check", help="Test check_request() sur un texte")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    args = ap.parse_args()

    if args.check:
        print(json.dumps(check_request(args.check), indent=2, ensure_ascii=False))
        return 0
    if not args.once and not args.daemon:
        ap.error("--once / --daemon / --check requis")

    while True:
        out = run_cycle()
        print(
            f"[immune] cycle {out['duration_s']}s : "
            f"learned={out['learning']['learned']} "
            f"archived={out['learning'].get('archived', 0)} "
            f"total_antibodies={out['stats']['total_antibodies']} "
            f"by_kind={out['stats']['by_kind']}",
            flush=True,
        )
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
