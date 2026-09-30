"""
tools/forge_veille_depollute.py — retire l'en-tete « [VEILLE] Theme: ... » des chunks
DEJA en base et re-embedde le corps seul (owner 2026-07-25 : « le theme ne doit pas
polluer le contenant »).

POURQUOI, mesure a l'appui : l'ancien `_step_ingest` prefixait chaque chunk de
« [VEILLE] Theme / Keyword / Source / URL / Pertinence ». Consequences :
  - le vecteur melange la REQUETE (le theme) et le CONTENU -> toute requete proche du
    theme remonte l'integralite de la veille, et le filtre thematique perd son sens ;
  - `_audit_chunks_quality` comparait le theme a un texte qui LE CONTENAIT : similarite
    0,61-0,78 sur les chunks entetes contre 0,457-0,728 sur les corps seuls. Une fois
    depollue, le meme audit separe NETTEMENT le contenu (0,41-0,65) des pages de
    bibliographie (0,008-0,031) -- c'est ce biais qui laissait passer un papier de
    finance dans une veille Docker.

Le backfill (`forge_veille_backfill.py`) depollue au passage, mais seulement les
sources qu'il re-crawle. Ici on traite TOUT le corpus historique sans reseau : on coupe
l'en-tete, on re-embedde, on re-synchronise rag_fts. La provenance n'est pas perdue :
elle vit dans les colonnes `source` / `role_hint` / `author`.

Idempotent (ne touche que les textes contenant encore le marqueur), dry-run par defaut.
Doit tourner en run_job (l'embedder :8099 est sur le loopback).
"""
from __future__ import annotations

__FORGE_COLOR__ = "digestif/veille : retire l'en-tete [VEILLE] des chunks et re-embedde le corps"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKER = "[VEILLE] Th"


def _strip_header(text: str) -> str:
    """Retire l'en-tete de veille. Elle se termine par la ligne « Pertinence: N/10 »
    suivie d'une ligne vide ; on coupe donc au premier double saut. Si le motif n'est
    pas celui attendu, on NE TOUCHE PAS (mieux vaut un chunk pollue qu'un chunk mutile)."""
    if MARKER not in text[:40]:
        return text
    head, sep, body = text.partition("\n\n")
    if not sep or "Pertinence" not in head:
        return text
    return body.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut: dry-run)")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--domain", default="watch_veille")
    ap.add_argument("--resync-fts", action="store_true",
                    help="resynchronise les entrees FTS dont le texte differe du chunk")
    args = ap.parse_args()

    try:
        from nokido_agent.app.forge_embed_router import embed as _embed, encode_blob as _encode_blob
    except Exception as e:  # noqa: BLE001
        print(f"embed_router indisponible ({e}) : on re-embeddera plus tard", flush=True)
        _embed = _encode_blob = None

    # Writer au pattern prouve (autocommit + WAL + busy_timeout) : permet de tourner
    # EN PARALLELE du backfill au lieu d'attendre son tour. Cf. forge_db_path.open_writer.
    from nokido_agent.app.forge_db_path import open_writer, purger_fts

    conn = open_writer(timeout=60.0)
    conn.row_factory = sqlite3.Row

    # RESYNC FTS : `rag_fts` n'a pas de clef qui declenche un remplacement, donc un
    # `INSERT OR IGNORE` laissait l'ANCIEN texte en place quand un chunk etait reecrit
    # (mesure 2026-07-25 : 106 entrees servaient encore l'en-tete depolluee). Le
    # lexical PRIME, il ne doit jamais etre un cache perime. Sans reseau ni embedding.
    if args.resync_fts:
        rows = conn.execute(
            "SELECT c.id, c.text, c.source, f.text AS ftext FROM rag_fts f JOIN rag_chunks c"
            " ON c.id = f.chunk_id WHERE c.domain=? AND f.text <> c.text",
            (args.domain,)).fetchall()
        print(f"[resync-fts] {len(rows)} entree(s) lexicale(s) obsolete(s)", flush=True)
        if args.apply:
            for r in rows:
                # Purge par MATCH sur le texte FTS OBSOLETE (lu dans la jointure), jamais
                # `WHERE chunk_id=?` : chunk_id est UNINDEXED -> balayage complet sous
                # verrou, une fois PAR ligne (2026-09-27, forge_db_path.purger_fts).
                purger_fts(conn, [(r["id"], r["ftext"])])
                conn.execute(
                    "INSERT INTO rag_fts (chunk_id, text, source, domain)"
                    " VALUES (?,?,?,?)", (r["id"], r["text"], r["source"], args.domain))
            conn.commit()
            reste = conn.execute(
                "SELECT COUNT(*) FROM rag_fts f JOIN rag_chunks c ON c.id = f.chunk_id"
                " WHERE c.domain=? AND f.text <> c.text", (args.domain,)).fetchone()[0]
            print(f"[resync-fts] resynchronise — reste {reste}", flush=True)
        else:
            print("[resync-fts] DRY-RUN : rien ecrit (--apply pour agir)", flush=True)
        conn.close()
        return 0

    rows = conn.execute(
        "SELECT id, text, source FROM rag_chunks WHERE domain=? AND text LIKE ?"
        " ORDER BY rowid LIMIT ?", (args.domain, f"%{MARKER}%", args.limit)).fetchall()
    print(f"[depollute] {len(rows)} chunk(s) portant l'en-tete (limite {args.limit})", flush=True)
    if not args.apply:
        print("[depollute] DRY-RUN : rien ne sera ecrit (--apply pour agir)", flush=True)

    changed = unchanged = reembedded = 0
    for r in rows:
        body = _strip_header(r["text"] or "")
        if not body or body == (r["text"] or "") or len(body) < 40:
            unchanged += 1
            continue
        if not args.apply:
            changed += 1
            continue
        blob = None
        if _embed and _encode_blob:
            try:
                vec = _embed(body)
                if vec and len(vec) >= 256:
                    blob = _encode_blob(vec)
            except Exception:  # noqa: BLE001
                blob = None
        if blob:
            conn.execute("UPDATE rag_chunks SET text=?, embedding=? WHERE id=?",
                         (body, blob, r["id"]))
            reembedded += 1
        else:
            # Pas de vecteur frais : on garde l'ancien plutot que d'ecrire un texte
            # depollue avec un vecteur pollue -> incoherence silencieuse.
            unchanged += 1
            continue
        try:
            # L'ancien texte FTS = le texte du chunk AVANT l'UPDATE (lu par le SELECT).
            purger_fts(conn, [(r["id"], r["text"] or "")])
            conn.execute(
                "INSERT OR IGNORE INTO rag_fts (chunk_id, text, source, domain)"
                " VALUES (?,?,?,?)", (r["id"], body, r["source"], args.domain))
        except Exception:  # noqa: BLE001
            pass
        changed += 1
    if args.apply:
        conn.commit()
    restant = conn.execute(
        "SELECT COUNT(*) FROM rag_chunks WHERE domain=? AND text LIKE ?",
        (args.domain, f"%{MARKER}%")).fetchone()[0]
    conn.close()
    print(f"[depollute] {changed} depollue(s) ({reembedded} re-embedde(s)),"
          f" {unchanged} laisse(s) intact(s) — reste {restant} en base", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
