#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_blind_spot_index.py — indexer le code VIVANT mais hors suivi git.

POURQUOI. `ctf/` (440 .py) et `forge_desktop/` (38 .py) existent sur le disque
mais sont gitignores ou untrackes. Invisibles du depot, donc invisibles du RAG
(mesure du 2026-08-16 : `forge_desktop` = 0 chunk sur 30099 du domaine
nokido_code), de la CI, des gates, de la proprioception AST (SCAN_DIRS = app +
tools) et de toute archeologie basee sur git. Ce n'est pas une perte de code,
c'est un angle mort de mesure : le code est la, personne ne le voit.

Trois evenements l'ont produit (census Phase 7) :
  2026-04-29  refactor(ctf): isolate CTF organ -> ctf/...    (dossier gitignore)
  2026-05-21  chore: consolidate root -- untrack standalone modules
  2026-03-26  chore: clean hackathon branch -- remove 651 non-essential files

LECTURE SEULE sur le code. N'ecrit que dans rag_chunks, avec un id deterministe
et INSERT OR IGNORE : re-executable sans doublon. Revocable d'une ligne :
    DELETE FROM rag_chunks WHERE source GLOB 'untracked:*'

Usage :
    forge_blind_spot_index.py                 # rapport seul, n'ecrit rien
    forge_blind_spot_index.py --apply         # indexe ctf/ et forge_desktop/
    forge_blind_spot_index.py --racines ctf --apply
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "memoire/rag : indexer le code vivant hors suivi git"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import collections
import hashlib
import os
import sqlite3
import subprocess
import time

from nokido_agent.tools.forge_archeo_socle import bruit_motifs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "RAG", "embeddings.db")
DOMAIN = "nokido_code"
CHUNK_SIZE = 1200
OVERLAP = 150
MAX_FICHIER = 400_000  # au-dela, ce n'est plus du code a comprendre

CODE_EXT = {".py", ".ps1", ".ts", ".tsx", ".js", ".sh", ".rs", ".go", ".swift"}
BRUIT = ("node_modules/", "site-packages/", ".venv/", "venv/", "__pycache__/",
         "dist/", "build/", ".git/", ".mypy_cache/", ".pytest_cache/")
RACINES_DEFAUT = ["ctf", "forge_desktop"]


def _est_bruit(rel: str) -> bool:
    return bruit_motifs(rel, BRUIT)


def suivis(depot: str) -> set:
    """Fichiers connus de git (donc deja visibles partout ailleurs)."""
    cmd = ["git", "-c", "safe.directory=*", "-C", depot, "ls-files"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        return set(l.strip() for l in p.stdout.splitlines() if l.strip())
    except Exception:
        return set()


def hors_suivi(depot: str) -> list:
    connus = suivis(depot)
    if not connus:
        raise SystemExit("[blindspot] git ls-files vide : mauvais compte ou depot illisible")
    trouves = []
    for racine, dirs, fichiers in os.walk(depot):
        dirs[:] = [d for d in dirs if not _est_bruit(d + "/") and d != ".git"]
        for f in fichiers:
            if os.path.splitext(f)[1].lower() not in CODE_EXT:
                continue
            rel = os.path.relpath(os.path.join(racine, f), depot).replace("\\", "/")
            if _est_bruit(rel) or rel in connus:
                continue
            trouves.append(rel)
    return sorted(trouves)


def decouper(texte: str):
    """Meme decoupe que les ingesteurs existants : par lignes, avec overlap."""
    morceaux, tampon, taille = [], [], 0
    for ligne in texte.splitlines(keepends=True):
        tampon.append(ligne)
        taille += len(ligne)
        if taille >= CHUNK_SIZE:
            morceaux.append("".join(tampon))
            reste, long_reste = [], 0
            for l in reversed(tampon):
                long_reste += len(l)
                reste.insert(0, l)
                if long_reste >= OVERLAP:
                    break
            tampon, taille = reste, long_reste
    if tampon:
        morceaux.append("".join(tampon))
    return morceaux


def indexer(depot: str, fichiers: list, applique: bool) -> dict:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    inseres = lus = ignores = 0
    t0 = time.time()
    for i, rel in enumerate(fichiers):
        chemin = os.path.join(depot, rel)
        try:
            if os.path.getsize(chemin) > MAX_FICHIER:
                ignores += 1
                continue
            texte = open(chemin, encoding="utf-8", errors="replace").read()
        except OSError as exc:
            print("[blindspot] illisible %s : %s" % (rel, exc))
            ignores += 1
            continue
        lus += 1
        source = "untracked:%s" % rel
        for morceau in decouper(texte):
            if len(morceau.strip()) < 50:
                continue
            cid = hashlib.sha256((source + morceau).encode()).hexdigest()[:16]
            if applique:
                cur.execute(
                    "INSERT OR IGNORE INTO rag_chunks (id,text,source,domain,role_hint)"
                    " SELECT ?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
                    (cid, morceau, source, DOMAIN, "code", cid))
                inseres += cur.rowcount
            else:
                inseres += 1
        if applique and i % 100 == 0 and i:
            con.commit()
    if applique:
        con.commit()
        try:
            cur.execute("INSERT INTO rag_fts(rag_fts) VALUES('rebuild')")
            con.commit()
        except sqlite3.Error as exc:
            print("[blindspot] rebuild FTS refuse : %s" % exc)
    con.close()
    return {"fichiers_lus": lus, "chunks": inseres, "ignores": ignores,
            "secondes": round(time.time() - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Indexe le code hors suivi git")
    ap.add_argument("--depot", default=ROOT)
    ap.add_argument("--racines", nargs="*", default=RACINES_DEFAUT,
                    help="prefixes de chemin a indexer (ex : ctf, app/_attic)")
    ap.add_argument("--apply", action="store_true", help="ecrit dans le RAG")
    ap.add_argument("--noms", type=int, default=0,
                    help="lister N chemins des racines ciblees, classes par nature")
    a = ap.parse_args()

    tous = hors_suivi(a.depot)
    par_racine = collections.Counter(f.split("/")[0] for f in tous)
    print("[blindspot] %s fichiers de code hors suivi dans %s"
          % (len(tous), os.path.basename(a.depot)))
    for r, n in par_racine.most_common(20):
        marque = "  <== indexe" if any(x.split("/")[0] == r for x in a.racines) else ""
        print("   %-28s %5s%s" % (r, n, marque))

    def vise(f):
        # prefixe de chemin, pas seulement racine de tete : `app/_attic` doit
        # pouvoir etre cible sans embarquer tout `app/`.
        return any(f == r or f.startswith(r.rstrip("/") + "/") for r in a.racines)

    cibles = [f for f in tous if vise(f)]
    if a.noms:
        def nature(f):
            b = os.path.basename(f)
            if b.startswith("tmp_") or "_tmp" in b:
                return "brouillon"
            if ".bak" in b or b.endswith("~") or "backup" in b:
                return "sauvegarde"
            if b.startswith("test_"):
                return "test"
            if b.startswith("_"):
                return "prive"
            if "patch" in b or b.startswith("fix_"):
                return "patch"
            return "CODE ORDINAIRE"
        groupes = collections.defaultdict(list)
        for f in cibles:
            groupes[nature(f)].append(f)
        for g in sorted(groupes, key=lambda k: -len(groupes[k])):
            print("  %-16s %s" % (g, len(groupes[g])))
        ordinaires = groupes.get("CODE ORDINAIRE", [])
        tailles = []
        for f in ordinaires:
            try:
                tailles.append((os.path.getsize(os.path.join(a.depot, f)), f))
            except OSError as exc:
                print("  illisible %s : %s" % (f, exc))
        tailles.sort(reverse=True)
        print("  --- code ordinaire non versionne, les plus gros ---")
        for taille, f in tailles[:a.noms]:
            print("   %8s  %s" % (taille, f))
    if not cibles:
        print("[blindspot] aucune cible ; rien a faire")
        return 0
    if not a.apply:
        print("[blindspot] %s fichiers seraient indexes (--apply pour ecrire)"
              % len(cibles))
        return 0

    res = indexer(a.depot, cibles, True)
    print("[blindspot] indexe : %s" % res)
    print("[blindspot] revocable par : DELETE FROM rag_chunks"
          " WHERE source GLOB 'untracked:*'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
