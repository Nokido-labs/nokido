#!/usr/bin/env python3
"""forge_ingest_llms_txt.py — ingere un SITE de documentation via son `llms.txt`.

POURQUOI CE SCRIPT EXISTE (verifie avant d'ecrire, 2026-08-20) : Nokido savait
ingerer un depot GitHub (`forge_ingest_github_repo`), un docset Dash local
(`forge_docset_ingest`), un fichier .md (`forge_doc_ingest`) et UNE url
(`crawl` / veille rapide) — mais AUCUN outil ne prenait un site de doc
multi-pages. Le format `llms.txt` (publie a la racine par les docs modernes,
dont platform.claude.com) donne exactement l'index qui manquait : la liste des
pages, sans crawl exploratoire ni devinette de sitemap.

CABLE, NE DUPLIQUE PAS :
  - fetch + markdown  : `forge_crawl_tool.crawl_url` (trafilatura > markdownify)
  - decoupage         : `forge_gitingest_sdk_ingest._chunks` (borne le 02-08
                        apres la boucle infinie qui avait gele le poste)
  - ecriture          : `forge_db_path.open_writer` (autocommit + WAL)
  - id EXPLICITE      : sha256(source+chunk)[:16] — regle d'or #3, et surtout
                        mesure du 2026-08-20 : 307 lignes a `id IS NULL`
                        faisaient reboucler le drain embed a l'infini, car
                        `WHERE id = NULL` ne matche rien et ne leve rien.

DEPORTE : lancer via `run_job` (online=true). Un crawl multi-pages sur
l'event-loop du hub = hub mort (incident 2026-08-15).

Usage :
    run_job script=tools/forge_ingest_llms_txt.py online=true \
      script_args="--url https://platform.claude.com/llms.txt --domain claude_docs"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_crawl_tool import crawl_url  # noqa: E402
from nokido_agent.app.forge_db_path import open_writer  # noqa: E402
from nokido_agent.tools.forge_gitingest_sdk_ingest import _chunks  # noqa: E402

# `llms.txt` est du markdown : les pages sont des liens [titre](url).
_LIEN = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def recuperer_index(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Nokido-docs-ingest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def extraire_pages(index_txt: str, prefixe: str | None) -> list[tuple[str, str]]:
    """[(titre, url)] dedupliquees, dans l'ordre, filtrees sur `prefixe`."""
    vues: set[str] = set()
    out: list[tuple[str, str]] = []
    for titre, url in _LIEN.findall(index_txt):
        u = url.rstrip(").,")
        if prefixe and not u.startswith(prefixe):
            continue
        if u in vues:
            continue
        vues.add(u)
        out.append((titre.strip() or u, u))
    return out


def ingerer(pages: list[tuple[str, str]], domain: str, pause: float,
            timeout: int) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conn = open_writer(timeout=60.0)
    total_chunks = inserted = pages_ok = pages_ko = 0
    erreurs: list[str] = []
    try:
        for n, (titre, url) in enumerate(pages, 1):
            try:
                # MESURE 2026-08-20 : `llms.txt` de platform.claude.com liste des
                # URLs en `.md` — le markdown SOURCE est servi tel quel. Passer
                # par Crawl4AI/trafilatura reviendrait a rendre du HTML pour le
                # re-convertir en markdown : plus lent, et plus lossy que
                # l'original. GET direct quand la cible est deja du markdown ;
                # crawl (Crawl4AI d'abord, trafilatura en repli) sinon.
                if url.lower().endswith((".md", ".txt", ".markdown")):
                    try:
                        _rq = urllib.request.Request(
                            url, headers={"User-Agent": "Nokido-docs-ingest/1.0"})
                        with urllib.request.urlopen(_rq, timeout=timeout) as _r:
                            texte = _r.read().decode("utf-8", "replace")
                    except Exception:  # noqa: BLE001
                        # MESURE 2026-08-20 : docs.mistral.ai publie un `llms.txt`
                        # dont TOUTES les entrees `.md` rendent 404 (75/75) — l'index
                        # existe, les fichiers markdown non. L'index annonce donc une
                        # forme que le serveur ne sert pas. Repli sur la page HTML
                        # (URL sans l'extension), rendue par Crawl4AI puis trafilatura.
                        _base = re.sub(r"\.(md|txt|markdown)$", "", url, flags=re.I)
                        texte = crawl_url(_base, timeout=timeout) or ""
                else:
                    texte = crawl_url(url, timeout=timeout) or ""
            except Exception as e:  # noqa: BLE001
                pages_ko += 1
                erreurs.append("%s :: %s" % (url[:80], str(e)[:70]))
                print("[%d/%d] KO %s (%s)" % (n, len(pages), url[:70], type(e).__name__),
                      flush=True)
                continue
            if len(texte.strip()) < 200:
                pages_ko += 1
                erreurs.append("%s :: contenu trop court (%d car.)" % (url[:80], len(texte)))
                print("[%d/%d] VIDE %s" % (n, len(pages), url[:70]), flush=True)
                continue
            source = "%s:%s" % (domain, url.split("://", 1)[-1])
            n_ins = 0
            for chunk in _chunks(texte):
                if not chunk.strip():
                    continue
                cid = hashlib.sha256((source + chunk).encode("utf-8")).hexdigest()[:16]
                total_chunks += 1
                cur = conn.execute(
                    "INSERT OR IGNORE INTO rag_chunks (id, source, text, domain, created_at) "
                    "VALUES (?, ?, ?, ?, ?)", (cid, source, chunk, domain, now))
                # ROWCOUNT, pas le compteur d'intention : un INSERT OR IGNORE qui
                # ignore un doublon rend 0. Sans ca on rapporte des insertions
                # qui n'ont pas eu lieu (faux-vert mesure le 2026-08-20).
                if cur.rowcount == 1:
                    inserted += 1
                    n_ins += 1
                    try:
                        conn.execute(
                            "INSERT INTO rag_fts (chunk_id, text, source, domain) "
                            "VALUES (?, ?, ?, ?)", (cid, chunk, source, domain))
                    except Exception:  # noqa: BLE001
                        pass  # FTS best-effort : forge_fts_backfill rattrape
            pages_ok += 1
            # Validation PAR PAGE (2026-09-24). Avant : une seule transaction pour tout
            # le site, validee a la fin -- le verrou d'ecriture de embeddings.db restait
            # pris des la premiere insertion jusqu'a la derniere page (208 a 638 pages,
            # plusieurs minutes), et tout autre ecrivain attendait ou expirait. C'est le
            # P0 « on retire des ecrivains du verrou RAG » ; ici, on raccourcit la prise.
            conn.commit()
            print("[%d/%d] OK %-64s +%d chunks" % (n, len(pages), url[-64:], n_ins),
                  flush=True)
            if pause:
                time.sleep(pause)
        conn.commit()
    finally:
        conn.close()
    return {"pages_total": len(pages), "pages_ok": pages_ok, "pages_ko": pages_ko,
            "chunks_vus": total_chunks, "chunks_inseres": inserted,
            "erreurs": erreurs[:20]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingere un site de doc via son llms.txt")
    ap.add_argument("--url", default="https://platform.claude.com/llms.txt")
    ap.add_argument("--domain", default="claude_docs")
    ap.add_argument("--prefixe", default=None,
                    help="ne garder que les URLs commencant par ceci (ex: https://platform.claude.com/docs/fr)")
    ap.add_argument("--limit", type=int, default=0, help="0 = toutes les pages")
    ap.add_argument("--pause", type=float, default=0.4, help="secondes entre deux pages (politesse)")
    ap.add_argument("--timeout", type=int, default=25)
    ap.add_argument("--urls", default=None,
                    help="URLs isolees separees par des virgules (arXiv, PDF, page unique) "
                         "— pour les sources SANS index llms.txt")
    ap.add_argument("--dry-run", action="store_true", help="liste les pages, n'ecrit rien")
    ap.add_argument("--sonder", default=None,
                    help="liste d'URLs llms.txt separees par des virgules : dit "
                         "lesquelles existent et combien de pages, sans rien ecrire. "
                         "Sert a inventorier la doc des CONSTITUANTS (owner 2026-08-20 : "
                         "« pour chaque constituant tu dois avoir la doc a jour »).")
    a = ap.parse_args()

    if a.urls:
        # URLS ISOLEES (2026-08-20) : tout n'a pas d'index `llms.txt` — un article
        # arXiv, un PDF, une page unique. Mesure du jour : le tool `crawl` du hub
        # AFFICHE le contenu sans TOUJOURS l'indexer (l'article TESSERA est revenu
        # en entier, `MATCH TESSERA` ne le trouvait pas). Lire n'est pas ingerer.
        pages = [(u.strip(), u.strip()) for u in a.urls.split(",") if u.strip()]
        print(json.dumps({"mode": "urls", "pages": len(pages),
                          "domain": a.domain}, ensure_ascii=False), flush=True)
        if a.dry_run:
            for _t, u in pages:
                print("   ", u, flush=True)
            return 0
        print(json.dumps(ingerer(pages, a.domain, a.pause, a.timeout),
                         ensure_ascii=False, indent=2), flush=True)
        return 0

    if a.sonder:
        trouves = []
        for u in [x.strip() for x in a.sonder.split(",") if x.strip()]:
            try:
                txt = recuperer_index(u, timeout=15)
                pages = extraire_pages(txt, None)
                trouves.append({"url": u, "ok": True, "octets": len(txt),
                                "pages": len(pages)})
                print("  OK   %-52s %5d pages" % (u[:52], len(pages)), flush=True)
            except Exception as e:  # noqa: BLE001
                trouves.append({"url": u, "ok": False,
                                "motif": "%s: %s" % (type(e).__name__, str(e)[:60])})
                print("  ---  %-52s %s" % (u[:52], str(e)[:50]), flush=True)
        print(json.dumps({"sondes": len(trouves),
                          "avec_llms_txt": sum(1 for t in trouves if t["ok"]),
                          "detail": trouves}, ensure_ascii=False, indent=2), flush=True)
        return 0

    idx = recuperer_index(a.url)
    pages = extraire_pages(idx, a.prefixe)
    if a.limit:
        pages = pages[: a.limit]
    print(json.dumps({"index": a.url, "index_chars": len(idx),
                      "pages_retenues": len(pages), "prefixe": a.prefixe,
                      "domain": a.domain}, ensure_ascii=False), flush=True)
    if a.dry_run:
        for t, u in pages[:40]:
            print("   %-52s %s" % (t[:52], u), flush=True)
        return 0
    rapport = ingerer(pages, a.domain, a.pause, a.timeout)
    print(json.dumps(rapport, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
