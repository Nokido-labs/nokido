"""Ingere un DEPOT GitHub entier dans le RAG Nokido, cible PARAMETRABLE.

Pourquoi pas `gitingest` : le SDK n'est installe QUE dans la base `miniforge3`.
Le hub, les jobs detaches et `trusted_script` tournent sous
`miniforge3/envs/laforge_py314`, ou `import gitingest` leve ModuleNotFoundError
(mesure 2026-08-04, rc=1 sur job_30862de01d6e et sur le trusted_script). Plutot
que d'installer une lib dans l'environnement de Nokido pour un besoin d'outil,
on prend le tarball public via la stdlib : ca marche dans TOUS les comptes.

Cable, ne duplique pas : le chunking vient de `forge_gitingest_sdk_ingest._chunks`
(borne le 02-08 apres la boucle infinie qui a fait geler le poste). On ne le
reecrit pas. Le parseur de format gitingest (`_blocs_fichiers`) devient inutile :
le tarball donne deja les fichiers un par un, sans passer par un dump texte —
donc zero fichier intermediaire a nettoyer.

Ce que ce module apporte, et qui n'existait nulle part :
  1. une cible passee en argument (`--url`), la ou `tmp_gitingest_deepmind.py`
     a ses depots EN DUR ;
  2. une SOURCE qui porte la provenance : `github:<owner>/<repo>/<chemin>`.
     `forge_gitingest_sdk_ingest.ingest_file` ecrit le seul chemin INTERNE du
     fichier (`backend/config.py`) sous `domain='sdk_gitingest'` : deux depots
     ayant un `config.py` y sont indistinguables. Ici `WHERE source LIKE
     'github:owner/repo/%'` rend un depot exact, et le retrait est propre.

Les chunks sont inseres SANS embedding : le lexical (rag_fts) est immediat, le
vectoriel est calcule par le backfill existant. Comportement de l'ingesteur
historique, inchange.

Usage :
    run action=run_job script=tools/forge_ingest_github_repo.py online=true
    run action=trusted_script path=tools/forge_ingest_github_repo.py \
        script_args="--url https://github.com/owner/repo --dry-run"
"""

from __future__ import annotations

__FORGE_COLOR__ = "digestif/ingestion-depot-externe"

import argparse
import hashlib
import io
import json
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# ROOT EN TETE. Le paquet-pont `nokido_agent` vit a la RACINE du depot, pas sous
# `app/` ni `tools/`. Sans elle, ce module ne s'importait QUE si le cwd se trouvait
# etre la racine, et mourait partout ailleurs : mesure du 2026-09-16, job detache
# job_13ad3534707f, `ModuleNotFoundError: No module named 'nokido_agent'` a la
# ligne d'import -- alors que le meme fichier s'importe sans broncher depuis un
# shell lance a la racine. Le point d'entree REEL n'empruntait pas le chemin que
# la lecture du code laissait croire, et l'usage inscrit dans la docstring
# (`run action=run_job`) etait precisement celui qui echouait.
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.app.forge_db_path import write_retry  # noqa: E402
from nokido_agent.tools.forge_gitingest_sdk_ingest import _chunks  # noqa: E402

# Cible par defaut : run_job IGNORE les args (gotcha mesure le 25-07), donc un
# lancement detache retombe ici.
DEFAULT_URL = "https://github.com/karpathy/llm-council"
DEFAULT_DOMAIN = "ext_repo"

KEEP_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".txt",
    ".toml", ".json", ".yaml", ".yml", ".sh", ".cfg", ".ini",
}
SKIP_PARTS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv"}
SKIP_NAMES = {"package-lock.json", "uv.lock", "poetry.lock", "yarn.lock"}
MAX_FILE_SIZE = 200_000
MAX_TOTAL = 20_000_000  # au-dela on refuse plutot que d'avaler le depot


def parse_slug(url: str) -> tuple[str, str]:
    """`https://github.com/karpathy/llm-council` -> ('karpathy', 'llm-council')."""
    m = re.search(r"github\.com[:/]+([^/]+)/([^/#?\s]+)", url)
    if not m:
        raise SystemExit(f"[ingest_repo] URL GitHub non reconnue : {url!r}")
    repo = m.group(2)
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return m.group(1), repo


def _garder(nom: str, prefixe: str | None = None) -> bool:
    p = Path(nom)
    # FILTRE DE SOUS-DOSSIER (2026-08-20) : sans lui, ingerer la doc d'un gros
    # depot (ex: ggml-org/llama.cpp -> `docs/`) obligeait a avaler TOUT le code
    # et butait sur le cap MAX_TOTAL. On veut la doc, pas le depot.
    if prefixe and not nom.replace("\\", "/").startswith(prefixe.strip("/") + "/"):
        return False
    if SKIP_PARTS & set(p.parts):
        return False
    if p.name in SKIP_NAMES:
        return False
    return p.suffix.lower() in KEEP_SUFFIXES


def fetch(owner: str, repo: str, ref: str | None,
          prefixe: str | None = None) -> tuple[list[tuple[str, str]], dict]:
    """Rend [(chemin_dans_le_depot, contenu), ...] + un rapport de collecte.

    Le rapport DIT ce qui a ete ecarte et pourquoi : un collecteur qui rend
    seulement ce qu'il a retenu fait passer un acces refuse pour un depot vide.
    """
    refs = [ref] if ref else ["main", "master"]
    blob = last_err = None
    for r in refs:
        url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/refs/heads/{r}"
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                blob = resp.read()
            ref = r
            break
        except urllib.error.HTTPError as e:
            last_err = f"{r}: HTTP {e.code}"
        except Exception as e:  # reseau coupe, DNS, TLS
            last_err = f"{r}: {type(e).__name__}: {e}"
    if blob is None:
        raise SystemExit(f"[ingest_repo] telechargement impossible ({last_err})")

    fichiers: list[tuple[str, str]] = []
    ecartes: dict[str, int] = {"extension_ou_dossier": 0, "trop_gros": 0, "illisible": 0}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for membre in tar.getmembers():
            if not membre.isfile():
                continue
            # le tarball GitHub prefixe tout par "<repo>-<ref>/"
            interne = membre.name.split("/", 1)[1] if "/" in membre.name else membre.name
            if not _garder(interne, prefixe):
                ecartes["extension_ou_dossier"] += 1
                continue
            if membre.size > MAX_FILE_SIZE:
                ecartes["trop_gros"] += 1
                continue
            flux = tar.extractfile(membre)
            if flux is None:
                ecartes["illisible"] += 1
                continue
            texte = flux.read().decode("utf-8", errors="replace")
            total += len(texte)
            if total > MAX_TOTAL:
                raise SystemExit(
                    f"[ingest_repo] {total} chars > cap {MAX_TOTAL} — depot trop gros"
                )
            fichiers.append((interne, texte))

    if not fichiers:
        raise SystemExit(
            f"[ingest_repo] 0 fichier RETENU pour {owner}/{repo}@{ref} "
            f"(ecartes: {ecartes}) — rien a ingerer"
        )
    return fichiers, {"ref": ref, "retenus": len(fichiers), "prefixe": prefixe,
                      "ecartes": ecartes, "chars": total}


def index(fichiers: list[tuple[str, str]], slug: str, domain: str) -> dict:
    now = int(time.time())
    lignes: list[tuple[str, str, str]] = []
    for interne, texte in fichiers:
        for chunk in _chunks(texte):
            chunk = chunk.strip()
            if not chunk:
                continue
            source = f"github:{slug}/{interne}"
            cid = hashlib.sha256((source + chunk).encode()).hexdigest()[:16]
            lignes.append((cid, source, chunk))

    def _op(conn):
        inserted = skipped = 0
        for cid, source, chunk in lignes:
            conn.execute(
                "INSERT OR IGNORE INTO rag_chunks "
                "(id, source, text, domain, created_at) VALUES (?, ?, ?, ?, ?)",
                (cid, source, chunk, domain, now),
            )
            if not conn.execute("SELECT changes()").fetchone()[0]:
                skipped += 1
                continue
            # Pas de DELETE prealable dans rag_fts ici : l'id EST le hash de
            # (source + chunk), donc un texte modifie produit un id NEUF et ne
            # reecrit jamais une ligne existante — le cas que le DELETE protege
            # (gotcha « INSERT OR IGNORE ne MET PAS A JOUR le FTS ») ne peut pas
            # se produire. Il coutait un full-scan de rag_fts PAR chunk
            # (chunk_id n'y est pas indexe) : mesure 2026-08-04, 65 chunks non
            # termines en 120 s, ingestion coupee a 12 fichiers sur 23.
            conn.execute(
                "INSERT INTO rag_fts (chunk_id, text, source, domain) "
                "VALUES (?, ?, ?, ?)",
                (cid, chunk, source, domain),
            )
            inserted += 1
        return {"chunks": len(lignes), "inserted": inserted, "skipped_dedup": skipped}

    # `write_retry` OUVRE la connexion et la PASSE a l'operation (`op(conn)`) avant
    # de la fermer : en ouvrir une soi-meme fait recevoir la sienne en 1er argument
    # positionnel (mesure 2026-08-04 : « Error binding parameter 1: type
    # sqlite3.Connection is not supported »). Une seule reprise couvre TOUTE la
    # boucle, rejouable sans degat (id deterministe + INSERT OR IGNORE).
    return write_retry(_op)


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingere un depot GitHub dans le RAG")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--ref", default=None, help="branche (defaut: main puis master)")
    ap.add_argument("--domain", default=DEFAULT_DOMAIN)
    ap.add_argument("--prefixe", default=None,
                    help="ne garder que ce sous-dossier du depot (ex: docs) — "
                         "indispensable sur un gros depot dont on ne veut que la doc")
    ap.add_argument("--dry-run", action="store_true",
                    help="telecharge et compte, n'ecrit RIEN en base")
    args = ap.parse_args()

    owner, repo = parse_slug(args.url)
    slug = f"{owner}/{repo}"
    fichiers, collecte = fetch(owner, repo, args.ref, args.prefixe)

    rapport: dict = {"repo": slug, "url": args.url, "domain": args.domain,
                     "collecte": collecte,
                     "fichiers": [n for n, _ in fichiers][:60]}
    rapport["index"] = ("DRY-RUN — aucune ecriture" if args.dry_run
                        else index(fichiers, slug, args.domain))
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
