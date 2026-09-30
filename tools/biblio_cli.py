"""
tools/biblio_cli.py — CLI Bibliography Worker (Sprint α — α6b)

Usage:
    python tools/biblio_cli.py search <entry_id>
    python tools/biblio_cli.py list [--status=<status>] [--limit=<n>]
    python tools/biblio_cli.py promote <entry_id>
    python tools/biblio_cli.py reject <entry_id> --reason=<reason>
    python tools/biblio_cli.py pin <entry_id> [--unpin]
    python tools/biblio_cli.py extract --text=<text> --idea=<idea_id>
    python tools/biblio_cli.py worker [--once] [--db=<path>]

CONTRAT : appels directs forge_biblio_core + forge_biblio_worker.
Output : tabulate si disponible, sinon fallback texte brut.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Ajouter app/ au path pour les imports
_app = Path(__file__).resolve().parent.parent / "app"
if str(_app) not in sys.path:
    sys.path.insert(0, str(_app))


def _tabulate(rows: list[dict], keys: list[str] | None = None) -> str:
    if not rows:
        return "(aucun résultat)"
    keys = keys or list(rows[0].keys())
    try:
        from tabulate import tabulate

        return tabulate(
            [[str(r.get(k, ""))[:60] for k in keys] for r in rows],
            headers=keys,
            tablefmt="rounded_outline",
        )
    except ImportError:
        # Fallback texte
        lines = ["  ".join(f"{k:<20}" for k in keys)]
        lines.append("-" * (22 * len(keys)))
        for r in rows:
            lines.append("  ".join(f"{str(r.get(k, '')):<20}"[:20] for k in keys))
        return "\n".join(lines)


def cmd_list(args) -> None:
    from nokido_agent.app.forge_biblio_core import list_entries

    status = args.status
    limit = args.limit
    entries = list_entries(status_filter=status, limit=limit)
    print(
        f"\n=== biblio_raw ({len(entries)} entrées"
        + (f" status={status}" if status else "")
        + ") ==="
    )
    print(_tabulate(entries, ["id", "type", "title", "status", "year", "created_at"]))
    print()


def cmd_search(args) -> None:
    import sqlite3

    from nokido_agent.app.forge_biblio_core import DEFAULT_DB_PATH, get_entry
    from nokido_agent.app.forge_biblio_worker import process_one_entry

    entry_id = args.entry_id
    entry = get_entry(entry_id)
    if not entry:
        print(f"ERR: entry {entry_id!r} introuvable")
        sys.exit(1)
    print(f"[search] id={entry_id} title={entry.get('title', '?')[:60]}")
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute("UPDATE biblio_raw SET status='queued' WHERE id=?", (entry_id,))
        conn.commit()
        entry["status"] = "queued"
        res = process_one_entry(conn, entry)
    finally:
        conn.close()
    print(json.dumps(res, indent=2, ensure_ascii=False))


def cmd_promote(args) -> None:
    from nokido_agent.app.forge_biblio_core import promote_entry

    res = promote_entry(args.entry_id, promoted_by="CLI")
    print(json.dumps(res, indent=2, ensure_ascii=False))


def cmd_reject(args) -> None:
    from nokido_agent.app.forge_biblio_core import reject_entry

    res = reject_entry(args.entry_id, args.reason)
    print(json.dumps(res, indent=2, ensure_ascii=False))


def cmd_pin(args) -> None:
    print("NOTE: pin/unpin reporte en beta (colonne pinned absente du schema alpha)")


def cmd_extract(args) -> None:
    from nokido_agent.app.forge_biblio_core import extract_from_text, insert_biblio_raw

    text = args.text
    idea_id = args.idea
    if not text or not idea_id:
        print("ERR: --text et --idea requis")
        sys.exit(1)
    sources = extract_from_text(text, idea_id, agent="CLI")
    print(f"[extract] {len(sources)} sources trouvées")
    for s in sources:
        r = insert_biblio_raw(s)
        status = r.get("status", "?")
        reason = r.get("rejection_reason", "")
        icon = "✓" if status == "unverified" else "✗"
        print(
            f"  {icon} [{status}] {s.get('title', '?')[:60]}" + (f" — {reason}" if reason else "")
        )


def cmd_worker(args) -> None:
    from nokido_agent.app.forge_biblio_worker import DEFAULT_DB_PATH, run_loop

    db = args.db or DEFAULT_DB_PATH
    run_loop(db_path=db, once=args.once, interval=30)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="biblio_cli",
        description="Nokido Bibliography CLI — Sprint α6b",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    # list
    p_list = sub.add_parser("list", help="Lister les entries biblio_raw")
    p_list.add_argument(
        "--status",
        default=None,
        help="Filtrer par status (unverified|queued|reviewed|promoted|rejected)",
    )
    p_list.add_argument("--limit", type=int, default=20)

    # search
    p_search = sub.add_parser("search", help="Lancer SearXNG sur une entry")
    p_search.add_argument("entry_id")

    # promote
    p_prom = sub.add_parser("promote", help="Promouvoir une entry (reviewed→promoted)")
    p_prom.add_argument("entry_id")

    # reject
    p_rej = sub.add_parser("reject", help="Rejeter une entry")
    p_rej.add_argument("entry_id")
    p_rej.add_argument("--reason", default="manual_reject")

    # pin
    p_pin = sub.add_parser("pin", help="Épingler une entry (beta)")
    p_pin.add_argument("entry_id")
    p_pin.add_argument("--unpin", action="store_true")

    # extract
    p_ext = sub.add_parser("extract", help="Extraire sources depuis un texte (Mistral)")
    p_ext.add_argument("--text", required=True)
    p_ext.add_argument("--idea", required=True, dest="idea")

    # worker
    p_wrk = sub.add_parser("worker", help="Lancer le worker loop (poll→SearXNG)")
    p_wrk.add_argument("--once", action="store_true", help="1 cycle puis exit")
    p_wrk.add_argument("--db", default=None)

    return ap


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()
    dispatch = {
        "list": cmd_list,
        "search": cmd_search,
        "promote": cmd_promote,
        "reject": cmd_reject,
        "pin": cmd_pin,
        "extract": cmd_extract,
        "worker": cmd_worker,
    }
    try:
        dispatch[args.cmd](args)
    except KeyboardInterrupt:
        print("\n[biblio_cli] interrompu")
    except Exception as e:
        print(f"ERR: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
