#!/usr/bin/env python3
"""forge_docset_ingest.py — ingestion BULK docset Dash/Zeal -> RAG (domain='reference').

Comble le "manque de capacité" de forge_docset_reader (BeautifulSoup pur + texte tronqué [:4000] +
query live, PAS d'ingest). Ici : extraction industrielle direct-to-DB, SANS bibliothèque MD plate
(keeper_pattern : l'artefact vit dans le substrat rag_chunks, pas en fichiers .md).

PIPELINE (compose l'existant, anti-dup) :
  forge_docset_sync (acquisition, existant) -> CE script (extract+chunk) -> rag_chunks(domain=reference,
  embedding=NULL) -> daemon :8099 BGE-M3 remplit l'embedding (Axe A) + FTS5 auto (Axe B). Trinité.

PERF : PARSE parallèle (ProcessPool, CPU-bound, sature le Ryzen) + WRITE sérialisé batch (1 writer,
évite la contention SQLite — leçon bench job_8397087e9236). lxml si dispo (10-50x bs4) sinon fallback
bs4 ; markdownify si dispo sinon texte brut (le vecteur embede le texte de toute façon).

DÉPORTÉ : lancer via run_job (le ProcessPool lourd NE tourne JAMAIS sur l'event-loop du hub).
Gouverné : domain='reference', lane_admission (anti-embolie). Idempotent (id déterministe, OR IGNORE).

USAGE (déporté)
  run_job script=tools/forge_docset_ingest.py  (ENV LAFORGE_DOCSET=Python_3 ou --all)
  ou: forge_docset_ingest.py <docset_name|--all>
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
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
DB = ROOT / "RAG" / "embeddings.db"
DOCSETS_DIR = Path(os.environ.get("LAFORGE_DOCSETS_DIR", str(ROOT / "data" / "docsets")))
_NOISE_TAGS = ("script", "style", "nav", "header", "footer", "aside")
_NOISE_CLASSES = ("sidebar", "toc", "navigation", "breadcrumb", "headerlink")
_MIN_CHUNK = 60          # chars : sous ce seuil = bruit (boilerplate)
_MAX_CHUNK = 6000        # chars : coupe les blocs trop gros (anti-fichier-géant)


def _clean_to_text(html_bytes: bytes) -> str:
    """HTML -> markdown/texte propre. lxml (rapide) si dispo, fallback bs4 (toujours présent)."""
    # voie rapide : lxml + markdownify
    try:
        from lxml.html import fromstring, tostring
        tree = fromstring(html_bytes)
        for tag in _NOISE_TAGS:
            for n in tree.xpath(f"//{tag}"):
                p = n.getparent()
                if p is not None:
                    p.remove(n)
        for cls in _NOISE_CLASSES:
            for n in tree.xpath(f"//*[contains(@class,'{cls}')]"):
                p = n.getparent()
                if p is not None:
                    p.remove(n)
        main = tree.xpath("//main") or tree.xpath("//*[@role='main']") or \
            tree.xpath("//*[contains(@class,'main-content') or contains(@class,'content') or contains(@class,'document')]") or [tree]
        html_clean = tostring(main[0], encoding="unicode")
        try:
            from markdownify import markdownify as _md
            return _md(html_clean, heading_style="ATX").strip()
        except Exception:
            from lxml.html import fromstring as _fs
            return _fs(html_clean).text_content().strip()
    except Exception:
        pass
    # fallback : bs4 (utilisé par forge_docset_reader, donc présent)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_bytes, "html.parser")
        for tag in _NOISE_TAGS:
            for n in soup.find_all(tag):
                n.decompose()
        for cls in _NOISE_CLASSES:
            for n in soup.find_all(class_=lambda c: c and cls in c):
                n.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception:
        return ""


def _semantic_chunks(text: str, symbol: str, dtype: str) -> list[str]:
    """Découpe par sections (## / ###), attache le symbole en métadonnée, borne la taille."""
    if not text:
        return []
    raw = text.replace("\n### ", "\n## ").split("\n## ")
    out: list[str] = []
    head = f"[{dtype}] {symbol}"
    for i, blk in enumerate(raw):
        blk = (("## " + blk) if i > 0 else blk).strip()
        if len(blk) < _MIN_CHUNK:
            continue
        body = f"{head}\n{blk}"
        # borne dure (anti-bloc-géant) : coupe en tranches de _MAX_CHUNK
        for j in range(0, len(body), _MAX_CHUNK):
            piece = body[j:j + _MAX_CHUNK]
            if len(piece) >= _MIN_CHUNK:
                out.append(piece)
    return out


def _process_file(args: tuple) -> list[tuple]:
    """Worker ProcessPool (module-level = picklable). Retourne [(id, source, text)] pour 1 symbole."""
    docs_dir, rel_path, name, dtype, docset = args
    # Certains docsets prefixent le chemin par des metadonnees Dash
    # « <dash_entry_name=...><dash_entry_originalName=...> » (mesure 2026-07-31 :
    # Redis, tous ses chemins introuvables donc 0 chunk, en silence). Les retirer
    # avant de resoudre le fichier.
    chemin = re.sub(r"<dash_entry_[^>]*>", "", rel_path).split("#")[0]
    fpath = os.path.join(docs_dir, chemin)
    if not os.path.exists(fpath):
        return [("__ERR__", "introuvable", chemin)]
    try:
        with open(fpath, "rb") as f:
            text = _clean_to_text(f.read())
    except Exception as exc:
        return [("__ERR__", type(exc).__name__, chemin)]
    rows = []
    for chunk in _semantic_chunks(text, name, dtype):
        source = f"docset:{docset}#{name}"
        cid = hashlib.sha256(f"{source}\x00{chunk[:120]}".encode("utf-8")).hexdigest()[:16]
        rows.append((cid, source, chunk))
    return rows


def ingest(docset_name: str, max_workers: int = 0) -> dict:
    docset_path = DOCSETS_DIR / f"{docset_name}.docset"
    dsidx = docset_path / "Contents" / "Resources" / "docSet.dsidx"
    docs_dir = docset_path / "Contents" / "Resources" / "Documents"
    if not dsidx.exists():
        return {"docset": docset_name, "error": f"dsidx absent: {dsidx}"}
    rel = None
    try:
        from nokido_agent.app.forge_lane_admission import admit, release  # type: ignore
        if not admit("docset_ingest", "claude", heavy=True).get("admit", True):
            return {"docset": docset_name, "skip": "admission refused (anti-embolie)"}
        rel = release
    except Exception:
        pass

    con = sqlite3.connect(str(dsidx))
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "searchIndex" in tables:
            tasks = con.execute("SELECT name, type, path FROM searchIndex").fetchall()
        elif "ZTOKEN" in tables:
            # Format Core Data des docsets Dash OFFICIELS (Python, Flask...). L'ancien
            # schema 'searchIndex' ne couvre que les docsets generes/anciens : mesure
            # 2026-07-31, Python.docset -> 'no such table: searchIndex' alors qu'il
            # contient 14695 tokens. Sans ce chemin, tout docset moderne est ignore.
            tasks = con.execute(
                "SELECT ZTOKENNAME, ZTYPENAME, ZPATH FROM ZTOKEN "
                "INNER JOIN ZTOKENMETAINFORMATION ON ZTOKEN.ZMETAINFORMATION = ZTOKENMETAINFORMATION.Z_PK "
                "INNER JOIN ZFILEPATH ON ZTOKENMETAINFORMATION.ZFILE = ZFILEPATH.Z_PK "
                "INNER JOIN ZTOKENTYPE ON ZTOKEN.ZTOKENTYPE = ZTOKENTYPE.Z_PK"
            ).fetchall()
        else:
            # Ni l'un ni l'autre : le DIRE, plutot que de rendre 0 chunk en silence.
            return {"docset": docset_name,
                    "error": f"schema d'index inconnu ({sorted(tables)[:6]})"}
    finally:
        con.close()
    if not tasks:
        return {"docset": docset_name, "error": "index lisible mais AUCUN symbole"}
    workers = max_workers or max(2, (os.cpu_count() or 4) - 2)
    inserted = seen = 0
    echecs: dict = {}
    now = datetime.now(timezone.utc).isoformat()
    try:
        wcon = sqlite3.connect(str(DB), timeout=30)
        wcon.execute("PRAGMA busy_timeout=30000")
        batch: list[tuple] = []

        def _ecrire_nouveaux(lot: list[tuple]) -> int:
            """Insere les seuls chunks ABSENTS (2026-10-01).

            Le trigger `rag_chunks_fts_bi` (BEFORE INSERT) retire l'entree lexicale
            de l'id existant AVANT que l'INSERT OR IGNORE soit ignore : re-ingerer un
            docset sortait du lexical tous ses chunks INCHANGES. On ecarte donc les
            ids deja presents, en UNE requete par lot. existence-verifiee
            """
            ids = [r[0] for r in lot]
            deja = {r[0] for r in wcon.execute(
                "SELECT id FROM rag_chunks WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)}
            neufs = [r for r in lot if r[0] not in deja]
            if not neufs:
                return 0
            cur = wcon.executemany(
                "INSERT OR IGNORE INTO rag_chunks(id,source,text,domain,ingested_at) VALUES(?,?,?,?,?)",
                neufs)
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_process_file, (str(docs_dir), p, n, t, docset_name)) for n, t, p in tasks]
            for fut in as_completed(futs):
                for cid, source, chunk in (fut.result() or []):
                    if cid == "__ERR__":
                        # « je n'ai pas pu lire » n'est pas « rien a lire » : compte
                        # les fichiers rates au lieu de les avaler (gate MUET).
                        echecs[source] = echecs.get(source, 0) + 1
                        continue
                    seen += 1
                    batch.append((cid, source, chunk, "reference", now))
                    if len(batch) >= 200:  # WRITE sérialisé batch (1 writer, anti-contention)
                        inserted += _ecrire_nouveaux(batch)
                        wcon.commit()
                        batch = []
        if batch:
            inserted += _ecrire_nouveaux(batch)
            wcon.commit()
        wcon.close()
    finally:
        if rel:
            try:
                rel("docset_ingest", "claude")
            except Exception:
                pass
    res = {"docset": docset_name, "symbols": len(tasks), "chunks_seen": seen,
           "inserted": inserted, "workers": workers,
           "note": "embedding=NULL -> daemon :8099 remplit (Axe A) + FTS5 (Axe B). domain=reference."}
    if echecs:
        res["fichiers_illisibles"] = echecs
    if seen == 0:
        # Un docset qui rend 0 chunk avec des symboles est un ECHEC, pas un succes
        # a zero : le dire, sinon il passe pour ingere (mesure : React, 1339
        # symboles -> 0 chunk, sans un mot).
        res["error"] = (f"{len(tasks)} symboles mais AUCUN chunk produit "
                        f"(causes: {echecs or 'contenu vide apres nettoyage'})")
    return res


def main(argv: list[str]) -> int:
    import json
    target = (argv[0] if argv else os.environ.get("LAFORGE_DOCSET", "")).strip()
    if not target:
        avail = sorted(p.stem for p in DOCSETS_DIR.glob("*.docset")) if DOCSETS_DIR.exists() else []
        print(json.dumps({"usage": "forge_docset_ingest.py <docset|--all>", "docsets_dir": str(DOCSETS_DIR),
                          "available": avail}, ensure_ascii=False, indent=1))
        return 0
    if target == "--all":
        names = [p.stem for p in DOCSETS_DIR.glob("*.docset")]
    else:
        names = [target]
    results = [ingest(n) for n in names]
    print(json.dumps({"results": results}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
