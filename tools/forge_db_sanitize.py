"""
forge_db_sanitize.py — Sanitize embeddings.db avant upload (R2/HF/cloud).

Pipeline Phase A drop + B anonymize + C whitelist (cf [[roadmap-distribution-storage]]).

USAGE :
    LAFORGE_PYTHON tools/forge_db_sanitize.py --mode public --out /tmp/sanitized.db
    LAFORGE_PYTHON tools/forge_db_sanitize.py --mode perso  --out /tmp/perso.db
    LAFORGE_PYTHON tools/forge_db_sanitize.py --mode public --dry-run

Modes :
  public  : Phase A drop PII + B anonymize + C whitelist (HF Datasets safe)
  perso   : Phase A drop seulement (R2 backup chiffré, garde la richesse)

Sanity-checks regex (PII, secrets, paths) AVANT export.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_SRC = ROOT / "RAG" / "embeddings.db"


# ── Tables policy ───────────────────────────────────────────────────────────

# Phase A : NEVER UPLOAD (drop complet)
TABLES_DROP_ALWAYS = {
    "agent_messages",  # PII prompts user
    "conversation_log",  # sessions humain
    "shared_prompt_log",  # prompts détaillés
    "network_log",  # IPs internes
    "user_audit_log",  # UID, sessions
    "user_sessions",  # token hashes
    "entity_sessions",  # ip_hash
    "tui_notifications",
    "tui_commands",
    "inspector_log",
    "agent_chain_nodes",  # exécutions internes
    "agent_chain_context",
    "agent_messages_archive",
}

# Tables avec patterns secret/credential en nom
DROP_PATTERNS = ("vault", "secret", "credential", "token", "session")

# Phase B : SANITIZE-then-UPLOAD
TABLES_SANITIZE = {
    "rag_chunks": {
        "anonymize_cols": {"source", "meta"},
        "drop_rows_where": None,
    },
    "rag_snapshots": {
        "anonymize_cols": {"session_id", "agent_id", "author", "meta"},
        "drop_rows_where": None,
    },
    "forge_entities": {
        "anonymize_cols": {"display_name", "meta"},
        "drop_rows_where": None,
    },
    "agent_profiles": {
        "anonymize_cols": {"trait_humain", "benchmarks"},
        "drop_rows_where": None,
    },
    "biblio_raw": {
        "anonymize_cols": {"meta"},
        "drop_rows_where": "status != 'promoted'",  # garde que promoted
    },
    "trajectories": {
        "anonymize_cols": {"session_id", "prompt"},
        "drop_rows_where": None,
    },
    "commit_intel": {
        "anonymize_cols": {"author", "email"},
        "drop_rows_where": None,
    },
}

# Phase C : WHITELIST safe as-is
TABLES_WHITELIST = {
    "adr_records",
    "system_rules",
    "biblio_topics",
    "biblio_link",
    "rag_graph_edges",
    "rag_graph_nodes",
}


# ── Sanity checks regex ─────────────────────────────────────────────────────

DANGER_PATTERNS = {
    "IPv4_internal": re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"),
    "windows_user": re.compile(r"C:[\\/]Users[\\/]user", re.IGNORECASE),
    "linux_home": re.compile(r"/home/(?!user)[a-z0-9_-]+/"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "github_pat": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    "api_key_long": re.compile(r"\b[A-Fa-f0-9]{40,}\b"),  # potentially sensitive hash/key
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "macaddr": re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    "hostname_perso": re.compile(r"\bnaarob[-_.a-z0-9]*\b", re.IGNORECASE),
}


def _redact_value(v: str) -> str:
    """Applique tous les patterns DANGER → tag <REDACTED>."""
    if not isinstance(v, str) or len(v) > 1_000_000:
        return v
    out = v
    for name, pat in DANGER_PATTERNS.items():
        out = pat.sub(f"<REDACTED:{name}>", out)
    return out


def _sanitize_dict_str_recursive(d) -> object:
    if isinstance(d, str):
        return _redact_value(d)
    if isinstance(d, dict):
        return {k: _sanitize_dict_str_recursive(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_sanitize_dict_str_recursive(x) for x in d]
    return d


def _sanitize_meta_json(meta_raw) -> str:
    """meta = JSON string. Parse, redact, re-serialize."""
    if not meta_raw or not isinstance(meta_raw, str):
        return meta_raw
    try:
        d = json.loads(meta_raw)
        d = _sanitize_dict_str_recursive(d)
        return json.dumps(d, ensure_ascii=False)
    except Exception:
        return _redact_value(meta_raw)


# ── Audit log ───────────────────────────────────────────────────────────────

_AUDIT_LINES: list[str] = []


def _audit(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    _AUDIT_LINES.append(line)
    print(f"  {line}", flush=True)


# ── Operations ──────────────────────────────────────────────────────────────


def _table_exists(c, table: str) -> bool:
    return (
        c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        is not None
    )


def _columns(c, table: str) -> list[str]:
    return [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]


def list_tables(c) -> list[str]:
    return [
        r[0]
        for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]


def phase_A_drop(c, mode: str) -> dict:
    """Drop tables PII + patterns secret. Aussi snapshots si mode public."""
    dropped = []
    for t in list_tables(c):
        if t in TABLES_DROP_ALWAYS or any(p in t.lower() for p in DROP_PATTERNS):
            try:
                n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except Exception:
                n = 0
            c.execute(f'DROP TABLE IF EXISTS "{t}"')
            dropped.append({"table": t, "rows": n})
            _audit(f"[A] DROP {t} ({n:,} rows)")
        # snapshot_janitor_* tables orphelines
        elif t.startswith("snapshot_janitor_"):
            n = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            c.execute(f'DROP TABLE IF EXISTS "{t}"')
            dropped.append({"table": t, "rows": n})
            _audit(f"[A] DROP {t} ({n:,} rows)")
    # Si public, drop aussi rag_snapshots (historique trop verbeux)
    if mode == "public" and _table_exists(c, "rag_snapshots"):
        n = c.execute("SELECT COUNT(*) FROM rag_snapshots").fetchone()[0]
        c.execute("DROP TABLE rag_snapshots")
        dropped.append({"table": "rag_snapshots", "rows": n})
        _audit(f"[A] DROP rag_snapshots ({n:,} rows) — mode=public")
    c.commit()
    return {"dropped": dropped, "count": len(dropped)}


def phase_B_sanitize(c, mode: str) -> dict:
    """Anonymize cols selon policy. Drop rows si drop_rows_where."""
    if mode != "public":
        return {"skipped": "mode=perso → pas d'anonymisation"}
    sanitized = []
    for table, policy in TABLES_SANITIZE.items():
        if not _table_exists(c, table):
            continue
        cols = _columns(c, table)
        anon_cols = [col for col in policy["anonymize_cols"] if col in cols]
        if not anon_cols:
            continue
        drop_where = policy.get("drop_rows_where")
        if drop_where:
            n_dropped = c.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE NOT ({drop_where})'
            ).fetchone()[0]
            c.execute(f'DELETE FROM "{table}" WHERE NOT ({drop_where})')
            _audit(f"[B] DELETE {table} not({drop_where}) → {n_dropped:,} rows dropped")
        # Pour chaque row, sanitize les cols anon_cols
        ids = c.execute(f'SELECT rowid FROM "{table}"').fetchall()
        n_modified = 0
        for (rid,) in ids:
            row = c.execute(
                f'SELECT {",".join(anon_cols)} FROM "{table}" WHERE rowid=?', (rid,)
            ).fetchone()
            new_vals = []
            changed = False
            for col, val in zip(anon_cols, row):
                if val is None:
                    new_vals.append(val)
                    continue
                if col.lower() == "meta":
                    new_val = _sanitize_meta_json(val)
                else:
                    new_val = _redact_value(str(val))
                if new_val != val:
                    changed = True
                new_vals.append(new_val)
            if changed:
                set_clause = ",".join(f"{col}=?" for col in anon_cols)
                c.execute(f'UPDATE "{table}" SET {set_clause} WHERE rowid=?', (*new_vals, rid))
                n_modified += 1
        c.commit()
        sanitized.append({"table": table, "modified": n_modified, "cols": anon_cols})
        _audit(f"[B] SANITIZE {table} ({n_modified:,} rows touched on {anon_cols})")
    return {"sanitized": sanitized}


def _constat(table: str, colonne: str, motif: str, m) -> dict:
    """Un constat de fuite SANS la valeur : table, colonne, motif, longueur de la correspondance.

    L'outil qui cherche les fuites ne doit jamais les recopier. Mesure du 2026-09-29 : chaque constat
    portait `"preview": val[:80]` -- les 80 premiers caracteres de la valeur contenant le secret --
    ecrits dans l'audit, puis dans `.audit.log` a cote de la base exportee, et affiches par `--dry-run`.
    """
    debut, fin = m.span()
    return {"table": table, "colonne": colonne, "pattern": motif, "longueur": fin - debut}


def _scanner(c, table: str, colonnes: list[str], issues: list, limite: int) -> None:
    """Parcourt TOUTES les lignes de `table` (jamais un echantillon) ; s'arrete a `limite` constats."""
    sel = ",".join(f'"{c2}"' for c2 in colonnes)
    for row in c.execute(f'SELECT {sel} FROM "{table}"'):
        for colonne, val in zip(colonnes, row):
            if not isinstance(val, str):
                continue
            for name, pat in DANGER_PATTERNS.items():
                m = pat.search(val)
                if m:
                    issues.append(_constat(table, colonne, name, m))
                    break
        if len(issues) >= limite:
            return


def phase_C_audit_whitelist(c) -> dict:
    """Vérifie whitelist tables : pas de patterns DANGER dedans."""
    issues = []
    for t in TABLES_WHITELIST:
        if not _table_exists(c, t):
            continue
        cols = _columns(c, t)
        text_cols = [
            col
            for col in cols
            if col not in ("id", "rowid", "created_at", "updated_at", "ts", "timestamp")
        ]
        if not text_cols:
            continue
        _scanner(c, t, text_cols, issues, limite=len(issues) + 11)
    if issues:
        _audit(f"[C] WHITELIST AUDIT : {len(issues)} matches in whitelist")
        for i in issues[:5]:
            _audit(f"     {i['table']}.{i['colonne']} - {i['pattern']} ({i['longueur']} car. masques)")
    else:
        _audit("[C] WHITELIST AUDIT : OK (0 patterns)")
    return {"whitelist_issues": issues, "ok": not issues}


def final_sanity_check(db_path: Path) -> dict:
    """Re-scan DB sanitized : 0 occurrence des patterns DANGER attendu."""
    c = sqlite3.connect(str(db_path), timeout=30)
    issues = []
    for t in list_tables(c):
        cols = _columns(c, t)
        text_cols = [col for col in cols if col not in ("id", "rowid")]
        if not text_cols:
            continue
        # TOUTES les lignes. Mesure du 2026-09-29 : `LIMIT 1000` par table -- une fuite a la ligne
        # 1001 d'une table exportee passait « PASS » avant un envoi public.
        _scanner(c, t, text_cols, issues, limite=21)
        if len(issues) > 20:
            break
    c.close()
    return {"final_issues": issues, "passed": not issues}


def verdict_export(mode: str, r_c: dict, final: dict) -> tuple[bool, list[str]]:
    """(publiable, motifs du refus). En mode `public`, l'audit de la phase C COMPTE.

    Mesure du 2026-09-29 : `phase_C_audit_whitelist` etait calcule puis IGNORE -- le code de sortie ne
    lisait que le controle final. Une table de la liste blanche portant un secret sortait « PASS ».
    En mode `perso` (sauvegarde chiffree privee), la phase C reste rapportee sans bloquer.
    """
    motifs = []
    if not final.get("passed"):
        motifs.append("controle final : %d constat(s)" % len(final.get("final_issues", [])))
    if mode == "public" and not r_c.get("ok"):
        motifs.append("phase C (liste blanche) : %d constat(s)" % len(r_c.get("whitelist_issues", [])))
    return (not motifs, motifs)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["public", "perso"], default="perso")
    ap.add_argument(
        "--out", required=False, default=str(ROOT / "_backups" / f"sanitized_{int(time.time())}.db")
    )
    ap.add_argument("--dry-run", action="store_true", help="audit only, ne crée pas de DB sortie")
    args = ap.parse_args()

    if not DB_SRC.exists():
        print(f"ERR: DB source absente: {DB_SRC}")
        return 1

    out_path = Path(args.out)
    print("=" * 64)
    print(f" forge_db_sanitize — mode={args.mode}")
    print(f" DB src: {DB_SRC} ({DB_SRC.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f" DB dst: {out_path}")
    print(f" dry_run: {args.dry_run}")
    print("=" * 64)

    if args.dry_run:
        # Juste lance audit sur src sans copy
        c = sqlite3.connect(str(DB_SRC), timeout=30)
        c.execute("PRAGMA journal_mode=WAL")
        r = phase_C_audit_whitelist(c)
        c.close()
        # Jamais le dict entier : il portait les apercus des valeurs trouvees.
        print(f"\n[DRY-RUN] whitelist audit : {'OK' if r['ok'] else 'ECHEC'} "
              f"({len(r['whitelist_issues'])} constat(s))")
        for i in r["whitelist_issues"][:10]:
            print(f"   {i['table']}.{i['colonne']} - {i['pattern']} ({i['longueur']} car. masques)")
        return 0 if r["ok"] else 2

    # Copy DB src → out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n[copy] {DB_SRC} -> {out_path} (online backup)")
    src_conn = sqlite3.connect(str(DB_SRC), timeout=30)
    dst_conn = sqlite3.connect(str(out_path), timeout=30)
    src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()
    print(f"  copy done, dst size: {out_path.stat().st_size / 1024 / 1024:.1f} MB")

    # Apply sanitize phases
    c = sqlite3.connect(str(out_path), timeout=60, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    print("\n[phases]")
    rA = phase_A_drop(c, args.mode)
    rB = phase_B_sanitize(c, args.mode)
    rC = phase_C_audit_whitelist(c)
    print("\n[VACUUM final]")
    c.execute("VACUUM")
    c.close()

    # Final sanity check
    print("\n[final scan]")
    final = final_sanity_check(out_path)
    publiable, motifs = verdict_export(args.mode, rC, final)
    if publiable:
        _audit("[FINAL] passed — 0 patterns DANGER")
    else:
        _audit("[FINAL] FAILED — " + " ; ".join(motifs))

    # Save audit log
    audit_path = out_path.with_suffix(".audit.log")
    audit_path.write_text("\n".join(_AUDIT_LINES), encoding="utf-8")

    print()
    print("=" * 64)
    print(f" DB out: {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f" Audit : {audit_path}")
    print(f" Final : {'PASS' if publiable else 'FAIL — ' + ' ; '.join(motifs)}")
    print("=" * 64)
    return 0 if publiable else 2


if __name__ == "__main__":
    sys.exit(main())
