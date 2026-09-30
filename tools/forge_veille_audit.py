"""forge_veille_audit.py — audit DETERMINISTE des veilles passees (0 LLM, 0 token cloud).

Question posee par l'owner le 2026-07-22 : "ce qui a ete demande dans les veilles
a-t-il ete implemente ?". Ce script ne juge pas : il RAPPROCHE trois sources et
laisse voir les trous.

  1. watch_jobs        — les veilles lancees : statut, sortie reelle, echecs muets.
  2. biblio_raw        — ce qu'elles ont produit : promu / rejete / en attente.
  3. git log           — ce qui a effectivement ete code depuis.

Defaut connu a mettre en evidence (mesure 2026-07-16) : un job peut rendre
status=completed avec n_stored=0 et un refine VIDE — un echec qui se declare
reussi. La colonne VERDICT ci-dessous l'isole.

Sortie : sandbox/veille_audit.md + resume compact sur stdout.
Usage : run action=run_job script=tools/forge_veille_audit.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
OUT = ROOT / "sandbox" / "veille_audit.md"


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _pick(cols, *candidates):
    for c in candidates:
        if c in cols:
            return c
    return None


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def _git(*args):
    try:
        r = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", str(ROOT), *args],
            capture_output=True, text=True, errors="replace", timeout=60,
        )
        return r.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"(git indisponible: {type(exc).__name__})"


def audit_watch_jobs(conn):
    cols = _cols(conn, "watch_jobs")
    c_id = _pick(cols, "id", "job_id")
    c_topic = _pick(cols, "theme", "topic", "subject", "query", "keywords")
    c_status = _pick(cols, "status", "state")
    c_created = _pick(cols, "created_at", "created", "ts")
    c_err = _pick(cols, "error", "last_error")
    sel = [c for c in (c_id, c_topic, c_status, c_created, c_err) if c]
    extra = [c for c in cols if c.startswith("n_") or c.endswith("_json")]
    sel += [c for c in extra if c not in sel]
    order = f" ORDER BY {c_created} DESC" if c_created else ""
    rows = _rows(conn, f"SELECT {', '.join(sel)} FROM watch_jobs{order}")

    # n_ingested = pages rapatriees ; n_stored = ce qui a REELLEMENT ete garde.
    # Prendre le max des deux masquait le cas decisif (rapatrie puis tout jete).
    # refined_json vide n'est PAS un echec : le pipeline efface ses intermediaires
    # a l'etape done (auditabilite perdue, sujet distinct).
    def _int(v):
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    for r in rows:
        status = str(r.get(c_status) or "").lower()
        ing, sto = _int(r.get("n_ingested")), _int(r.get("n_stored"))
        r["_ing"], r["_sto"] = ing, sto
        if status in ("completed", "done", "ok"):
            if ing == 0 and sto == 0:
                r["_verdict"] = "VIDE (rien rapatrie)"
            elif sto == 0:
                r["_verdict"] = "RIEN GARDE (%d rapatries)" % ing
            else:
                r["_verdict"] = "OK (%d/%d gardes)" % (sto, ing)
        elif status in ("error", "failed"):
            r["_verdict"] = "ECHEC DECLARE"
        else:
            r["_verdict"] = status.upper() or "?"
    return cols, rows, (c_id, c_topic, c_status, c_created, c_err)


def audit_biblio(conn):
    cols = _cols(conn, "biblio_raw")
    c_status = _pick(cols, "status", "state")
    c_kind = _pick(cols, "source_kind", "kind", "source")
    c_rej = _pick(cols, "rejection_reason")
    out = {"columns": cols, "by_status": [], "by_kind": [], "incoherent": 0}
    if c_status:
        out["by_status"] = _rows(
            conn, f"SELECT {c_status} AS k, COUNT(*) AS n FROM biblio_raw GROUP BY 1 ORDER BY n DESC")
    if c_kind:
        out["by_kind"] = _rows(
            conn, f"SELECT {c_kind} AS k, COUNT(*) AS n FROM biblio_raw GROUP BY 1 ORDER BY n DESC LIMIT 12")
    if c_status and c_rej:
        r = _rows(conn, f"SELECT COUNT(*) AS n FROM biblio_raw "
                        f"WHERE {c_rej} IS NOT NULL AND {c_status}='promoted'")
        out["incoherent"] = r[0]["n"] if r else 0
    return out


def main() -> int:
    if not DB.exists():
        print("ERR base introuvable:", DB)
        return 2
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = None

    wcols, jobs, keys = audit_watch_jobs(conn)
    c_id, c_topic, c_status, c_created, _c_err = keys
    bib = audit_biblio(conn)

    # Volume RAG issu des veilles
    try:
        veille_chunks = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE domain LIKE '%watch%' OR domain LIKE '%veille%'"
        ).fetchone()[0]
    except Exception:  # noqa: BLE001
        veille_chunks = -1

    lines = []
    lines.append("# Audit des veilles — demande contre implemente")
    lines.append("")
    lines.append("Genere le %s par tools/forge_veille_audit.py (deterministe, 0 LLM)."
                 % datetime.now(timezone.utc).isoformat(timespec="seconds"))
    lines.append("")

    verdicts = {}
    for j in jobs:
        verdicts[j["_verdict"].split(" (")[0]] = verdicts.get(j["_verdict"].split(" (")[0], 0) + 1
    tot_ing = sum(j.get("_ing", 0) for j in jobs)
    tot_sto = sum(j.get("_sto", 0) for j in jobs)
    lines.append("Retention globale : **%d gardes / %d rapatries**." % (tot_sto, tot_ing))
    lines.append("")
    lines.append("## 1. Veilles lancees (%d)" % len(jobs))
    lines.append("")
    for k, n in sorted(verdicts.items(), key=lambda x: -x[1]):
        lines.append("- **%s** : %d" % (k, n))
    lines.append("")
    lines.append("| job | sujet | statut | verdict | date |")
    lines.append("|---|---|---|---|---|")
    for j in jobs:
        lines.append("| %s | %s | %s | %s | %s |" % (
            str(j.get(c_id))[:14] if c_id else "?",
            str(j.get(c_topic) or "")[:70].replace("|", "/"),
            str(j.get(c_status) or "")[:12],
            j["_verdict"],
            str(j.get(c_created) or "")[:19],
        ))
    lines.append("")

    lines.append("## 2. Production bibliographique")
    lines.append("")
    lines.append("- chunks RAG issus des veilles : **%s**" % veille_chunks)
    lines.append("- entrees promues portant un rejection_reason (incoherent) : **%s**" % bib["incoherent"])
    lines.append("")
    lines.append("Par statut : " + ", ".join("`%s`=%s" % (r["k"], r["n"]) for r in bib["by_status"]))
    lines.append("")
    lines.append("Par origine : " + ", ".join("`%s`=%s" % (r["k"], r["n"]) for r in bib["by_kind"]))
    lines.append("")

    lines.append("## 3. Rapprochement avec le code livre")
    lines.append("")
    lines.append("Commits portant une trace de veille / integration :")
    lines.append("")
    lines.append("```")
    lines.append(_git("log", "--date=short", "--pretty=%ad %h %s", "-40",
                      "--grep=veille", "--grep=watch", "--grep=biblio", "--grep=integr", "-i"))
    lines.append("```")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")

    print("=== AUDIT VEILLES ===")
    print("jobs:", len(jobs), "|", json.dumps(verdicts, ensure_ascii=False))
    print("chunks veille:", veille_chunks, "| biblio incoherentes:", bib["incoherent"])
    print("statuts biblio:", json.dumps({r["k"]: r["n"] for r in bib["by_status"]}, ensure_ascii=False))
    print("rapport:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
