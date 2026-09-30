#!/usr/bin/env python3
"""
forge_bulk_import.py — Import massif de liens dans Nokido.

Sources compatibles :
  - TabCopy (JSON Array)   : [{"url":"...","title":"..."},...]
  - Link Gopher (texte)    : une URL par ligne
  - Favoris exportés (HTML): extrait les href

Usage :
  # Depuis presse-papier (TabCopy)
  python tools/forge_bulk_import.py --clipboard

  # Depuis fichier JSON
  python tools/forge_bulk_import.py --file liens.json

  # Pipe depuis stdin
  echo '[{"url":"https://...","title":"test"}]' | python tools/forge_bulk_import.py

  # Dossier de favoris (fichier HTML exporté Firefox)
  python tools/forge_bulk_import.py --bookmarks favoris.html

Controles :
  --dry-run    : Affiche ce qui serait inséré sans toucher la DB
  --domain     : Tag de domaine RAG (defaut: manual_import)
  --priority   : Priorité 1-5 (defaut: 3)
  --no-dedup   : Désactive le dédoublonnage (re-insère les doublons)
"""

import argparse
import datetime
import hashlib
import json
import re
import sqlite3
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

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
NOW = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")


def parse_links(raw: str) -> list[dict]:
    """Détecte et parse le format : JSON array, URLs brutes, ou HTML favoris."""
    raw = raw.strip()
    if not raw:
        return []

    # JSON Array (TabCopy)
    if raw.startswith("["):
        try:
            items = json.loads(raw)
            return [
                {"url": i.get("url", ""), "title": i.get("title", i.get("url", ""))}
                for i in items
                if i.get("url")
            ]
        except json.JSONDecodeError:
            pass

    # HTML favoris Firefox/Chrome (href dans les balises <A>)
    if "<A " in raw.upper() or "<a " in raw:
        links = []
        for m in re.finditer(
            r'<[Aa]\s+[^>]*HREF="([^"]+)"[^>]*>([^<]*)</[Aa]>', raw, re.IGNORECASE
        ):
            url, title = m.group(1), m.group(2).strip()
            if url.startswith("http"):
                links.append({"url": url, "title": title or url})
        return links

    # URLs brutes (Link Gopher — une par ligne)
    links = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("http"):
            links.append({"url": line, "title": line})
    return links


def dedup(links: list[dict], conn: sqlite3.Connection) -> tuple[list[dict], int]:
    """Filtre les URLs déjà dans biblio_raw ou rag_chunks."""
    existing = set()
    rows = conn.execute("SELECT url FROM biblio_raw WHERE url IS NOT NULL").fetchall()
    existing.update(r[0] for r in rows)
    try:
        rows2 = conn.execute(
            "SELECT source FROM rag_chunks WHERE domain='manual_import'"
        ).fetchall()
        existing.update(r[0] for r in rows2)
    except Exception:
        pass
    new = [l for l in links if l["url"] not in existing]
    skipped = len(links) - len(new)
    return new, skipped


def insert_bulk(links: list[dict], domain: str, priority: int, dry_run: bool) -> dict:
    """Insère les liens dans biblio_raw avec status=unverified."""
    if dry_run:
        print(f"[DRY-RUN] {len(links)} liens à insérer (aucune écriture)")
        for l in links[:10]:
            print(f"  {l['url'][:80]}")
        if len(links) > 10:
            print(f"  ... et {len(links) - 10} autres")
        return {"inserted": 0, "dry_run": True}

    conn = sqlite3.connect(str(DB), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    inserted = 0
    for l in links:
        url = l["url"]
        title = l.get("title", url)[:200]
        uid = "blr_" + hashlib.md5(url.encode()).hexdigest()[:12]
        phash = hashlib.md5(f"{url}{title}".encode()).hexdigest()[:16]
        try:
            conn.execute(
                "INSERT OR IGNORE INTO biblio_raw"
                "(id,type,title,url,status,source_kind,payload_hash,triggered_by_idea_id,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    uid,
                    "url",
                    title,
                    url,
                    "unverified",
                    "bulk_import",
                    phash,
                    f"bulk_{domain}_p{priority}",
                    NOW,
                    NOW,
                ),
            )
            inserted += 1
        except Exception as e:
            print(f"  SKIP {url[:60]}: {e}", file=sys.stderr)
    conn.commit()

    # Notification unique vers Gemini
    total_unverified = conn.execute(
        "SELECT COUNT(*) FROM biblio_raw WHERE status='unverified'"
    ).fetchone()[0]
    try:
        msg_id = "blk_" + hashlib.md5(f"bulk{NOW}".encode()).hexdigest()[:12]
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_db_path import open_m2m   # scission M2M : la notification part dans la base M2M, pas avec biblio_raw
        _m2m = open_m2m(timeout=5)
        _m2m.execute(
            "INSERT OR IGNORE INTO agent_messages"
            "(id,from_agent,to_agent,correlation_id,method,payload,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                msg_id,
                "agt_claude",
                "agt_gemini",
                msg_id,
                "tool.hub.arg.message",
                json.dumps(
                    {
                        "text": f"[GEMINI][BULK-IMPORT] {inserted} liens ajoutés à biblio_raw "
                        f"(domain={domain}, priority={priority}). "
                        f"Total unverified={total_unverified}. "
                        f"Traite quand mood > 0.5 avec biblio action=list status_filter=unverified."
                    }
                ),
                "unread",
                NOW,
            ),
        )
        conn.commit()
    except Exception:
        pass

    conn.close()
    return {"inserted": inserted, "total_unverified": total_unverified}


def main():
    parser = argparse.ArgumentParser(description="Import massif de liens dans Nokido")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--clipboard", action="store_true", help="Lire depuis le presse-papier")
    src.add_argument("--file", type=str, help="Fichier JSON, HTML ou texte")
    src.add_argument("--bookmarks", type=str, help="Fichier HTML de favoris exportés Firefox")
    parser.add_argument("--domain", default="manual_import")
    parser.add_argument("--priority", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-dedup", action="store_true")
    args = parser.parse_args()

    # Lire la source
    if args.clipboard:
        try:
            import subprocess

            r = subprocess.run(
                ["powershell", "-command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=5,
            errors="replace")
            raw = r.stdout
        except Exception as e:
            print(f"Presse-papier inaccessible: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.file or args.bookmarks:
        path = args.file or args.bookmarks
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    else:
        raw = sys.stdin.read()

    # Parser
    links = parse_links(raw)
    if not links:
        print("Aucun lien détecté dans l'entrée.")
        sys.exit(0)

    print(f"Liens détectés : {len(links)}")

    # Dédoublonnage
    skipped = 0
    if not args.no_dedup and not args.dry_run:
        conn = sqlite3.connect(str(DB), timeout=5)
        links, skipped = dedup(links, conn)
        conn.close()
        if skipped:
            print(f"Doublons ignorés : {skipped}")

    if not links:
        print("Rien à insérer (tous les liens sont déjà connus).")
        sys.exit(0)

    print(f"À insérer : {len(links)}")

    # Insérer
    result = insert_bulk(links, args.domain, args.priority, args.dry_run)

    if not args.dry_run:
        print(f"✓ {result['inserted']} liens insérés → biblio_raw")
        print(f"  Total unverified : {result.get('total_unverified', '?')}")
        print("  Gemini notifié (1 seule notification)")


if __name__ == "__main__":
    main()
