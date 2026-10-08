"""tools/forge_knowledge_pack_export.py — Knowledge Pack ESSENTIEL : les fragments PROUVES publics.

__FORGE_COLOR__ = "infra/deploy : Knowledge Pack essentiel de la release (fragments prouves publics)"

POURQUOI (2026-10-07)
---------------------
La base RAG (8,6 M fragments, 423 domaines) melange le savoir de Nokido, des veilles et documentations
TIERCES (droit d'auteur) et la memoire de l'owner (sessions, postal). L'ancien filtre par domaine ne
suffisait pas : `nokido_code` contient surtout des resumes de depots tiers (`gitingest:uvicorn:...`), et sa
liste etait perimee (`nokido_docs` = 19 fragments ; la doc vit dans `nokido_doc`).

CRITERE (un seul, mesurable) : un fragment entre dans le pack si son texte, espaces normalises, se retrouve
MOT POUR MOT dans un fichier PUBLIE du dist, lu a son commit. Le contenu est alors deja public : rien de prive
ne peut fuir, meme si l'etiquette de source ment, et rien de perime n'entre. Le critere herite de la politique
publique du promoteur (fichiers exclus, generisation) sans liste parallele. En plus, fail-closed : motif de
secret, identite privee, ou signal ROUGE du juge du gate egress (profil public) -> fragment ecarte.

FORMAT `nokido-knowledge-pack/2` (npz, AUCUN objet pickle : l'importeur charge avec allow_pickle=False) :
  embeddings  float16 (N, 1024)   vecteurs BGE-M3 (l'importeur les relit en float32)
  meta        uint8               JSON UTF-8 : manifest, chunk_ids, sources (chemin publie), domains
  texts       uint8               JSON UTF-8 : liste des textes

Usage :
    LAFORGE_PYTHON tools/forge_knowledge_pack_export.py --dist C:/tmp/nokido-dist --version 0.20.10 --dry-run
    LAFORGE_PYTHON tools/forge_knowledge_pack_export.py --dist C:/tmp/nokido-dist --version 0.20.10 --output X.npz
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger("forge.knowledge_pack")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data"
FORMAT = "nokido-knowledge-pack/2"
DIM = 1024
LONGUEUR_MIN = 40
DOMAINES = ("nokido_doc", "doctrine", "forge_core", "nokido_code", "docs",
            "policy_rules", "policy_roles", "policy_security")

SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{30,}"),
    re.compile(r"gsk_[a-zA-Z0-9]{40,}"),
    re.compile(r"[Bb]earer\s+[A-Fa-f0-9]{40,}"),
]
PII_PATTERNS = [
    re.compile(r"C:[\\/]Users[\\/]\w+", re.I),
    re.compile(r"/home/\w+/|/Users/\w+/", re.I),
    re.compile(r"[a-zA-Z0-9._-]+@(?:gmail|outlook|yahoo|hotmail|proton)\.\w+", re.I),
    re.compile(r"\bnaarobb?\b", re.I),
]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    from nokido_agent.app.forge_git_egress import identites_privees as _identites_privees
    PII_PATTERNS.extend(_identites_privees())
except Exception as _e_ident:  # muet-ok : DIT ci-dessous, et le critere « prouve public » reste le filet
    logger.warning("identites privees illisibles (%s) : motifs limites aux pseudonymes", type(_e_ident).__name__)


def base_rag() -> Path:
    """Base d'autorite (forge_db_path), repli sur RAG/embeddings.db."""
    try:
        import forge_db_path
        return Path(forge_db_path.db_path())
    except Exception:  # muet-ok : repli DIT par le chemin rendu, qui figure au manifeste
        return ROOT / "RAG" / "embeddings.db"


def normaliser(texte: str) -> str:
    return re.sub(r"\s+", " ", texte or "").strip()


def rattacher(source: str, publies: set[str]) -> str | None:
    """Etiquette de source -> chemin d'un fichier publie du dist, ou None."""
    s = (source or "").replace("\\", "/")
    s = re.sub(r"^card/", "", s)
    s = re.sub(r"^(untracked|repo|file|git|disco|docs?)://?", "", s)
    s = re.sub(r"^(untracked|repo|file|git):", "", s)
    s = re.sub(r"^.*?/Nokido/", "", s)
    s = s.split("#")[0].split("::")[0].lstrip("./")
    if s in publies:
        return s
    m = re.match(r"^(.*?\.(?:py|md|ts|toml|json|yml|yaml|txt|js|ps1|sh))(?::\d+.*)?$", s)
    return m.group(1) if m and m.group(1) in publies else None


class Dist:
    """Fichiers publies du dist, lus a son commit (jamais l'arbre de travail)."""

    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)
        rc, sortie = self._git("ls-tree", "-r", "--name-only", "HEAD")
        if rc:
            raise SystemExit("[pack] dist ILLISIBLE : %s n'est pas un depot lisible (rc=%s)" % (chemin, rc))
        self.publies = set(sortie.split("\n")) - {""}
        self.commit = self._git("rev-parse", "HEAD")[1].strip()
        self._cache: dict[str, str] = {}

    def _git(self, *args: str) -> tuple[int, str]:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(self.chemin), *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.returncode, r.stdout

    def contenu(self, chemin: str) -> str:
        if chemin not in self._cache:
            self._cache[chemin] = normaliser(self._git("show", "HEAD:" + chemin)[1])
        return self._cache[chemin]


def decoder_vecteur(blob) -> np.ndarray | None:
    """Vecteur stocke -> float32, dans les formats de `forge_rag_engine._decode_embedding_blob` : JSON en octets
    (commence par « [ »), float32 brut, ou JSON en texte. Plus STRICT que le moteur : un blob brut dont la taille
    n'est pas un multiple de 4 est ecarte (le moteur le tronque ; un pack publie ne porte pas de vecteur douteux).
    Mesure du 2026-10-07 : des blobs de la base reelle ne sont pas du float32 brut (premier essai : ValueError)."""
    if blob is None or len(blob) == 0:
        return None
    try:
        if isinstance(blob, (bytes, bytearray, memoryview)):
            brut = bytes(blob)
            if brut[:1] == b"[":
                return np.asarray(json.loads(brut.decode("utf-8")), dtype=np.float32)
            if len(brut) % 4:
                return None
            return np.frombuffer(brut, dtype=np.float32)
        return np.asarray(json.loads(blob), dtype=np.float32)
    except (ValueError, TypeError, UnicodeDecodeError):
        return None


def _juge_public():
    """Le juge du gate egress, profil public. Absent = refus (on ne publie pas sans juge)."""
    try:
        from nokido_agent.app import forge_git_egress as eg
    except Exception:
        import forge_git_egress as eg  # type: ignore[no-redef]
    profil = (eg.load_manifest().get("profiles") or {}).get("public")
    if not profil:
        raise SystemExit("[pack] profil « public » absent du manifeste egress : export refuse")
    return lambda chemin, texte: eg.scan_files({chemin: texte}, profil)[0] == eg.pg.Severity.RED


def selectionner(lignes, dist, juge) -> tuple[list, dict]:
    """lignes = (id, source, domaine, texte, blob). Rend (retenus, compte rendu par domaine)."""
    retenus, vus = [], set()
    cr: dict[str, Counter] = {}
    for cid, source, domaine, texte, blob in lignes:
        c = cr.setdefault(domaine, Counter())
        c["lus"] += 1
        if cid in vus:
            c["doublon"] += 1
            continue
        chemin = rattacher(source, dist.publies)
        if not chemin:
            c["non_rattache"] += 1
            continue
        t = normaliser(texte)
        if len(t) < LONGUEUR_MIN:
            c["trop_court"] += 1
            continue
        if t not in dist.contenu(chemin):
            c["non_prouve"] += 1
            continue
        vec = decoder_vecteur(blob)
        if vec is None or vec.shape != (DIM,) or not np.isfinite(vec).all():
            c["vecteur_invalide"] += 1
            continue
        # bge-m3 rend des vecteurs NORMES. Mesure du 2026-10-07 : 29 603 retenus de norme 0,9996-1, et 26 de norme
        # infinie (forge_core, stockes en JSON) qui debordaient en float16. Un vecteur corrompu s'ecarte, il ne se
        # renormalise pas : sa direction n'est pas plus sure que sa longueur.
        norme = float(np.linalg.norm(vec.astype(np.float64)))
        if not np.isfinite(norme) or abs(norme - 1.0) > 0.02:
            c["vecteur_non_norme"] += 1
            continue
        if any(p.search(texte) for p in SECRET_PATTERNS):
            c["secret"] += 1
            continue
        if any(p.search(texte) for p in PII_PATTERNS):
            c["identite"] += 1
            continue
        if juge(chemin, texte):
            c["juge_rouge"] += 1
            continue
        vus.add(cid)
        c["retenus"] += 1
        retenus.append((cid, texte, chemin, domaine, vec))
    return retenus, {d: dict(v) for d, v in cr.items()}


def _lignes(base: Path, domaines):
    with sqlite3.connect("file:%s?mode=ro" % base.as_posix(), uri=True, timeout=30) as con:
        for d in domaines:
            yield from con.execute(
                "SELECT id, source, domain, text, embedding FROM rag_chunks "
                "WHERE domain=? AND +active=1 AND embedding IS NOT NULL", (d,))


def ecrire_pack(sortie: Path, retenus: list, manifest: dict) -> str:
    def _octets(obj) -> np.ndarray:
        return np.frombuffer(json.dumps(obj, ensure_ascii=False).encode("utf-8"), dtype=np.uint8)

    meta = {"manifest": manifest, "chunk_ids": [r[0] for r in retenus], "sources": [r[2] for r in retenus],
            "domains": [r[3] for r in retenus]}
    sortie.parent.mkdir(parents=True, exist_ok=True)
    with open(sortie, "wb") as fh:
        np.savez_compressed(fh, embeddings=np.stack([r[4] for r in retenus]).astype(np.float16),
                            meta=_octets(meta), texts=_octets([r[1] for r in retenus]))
    h = hashlib.sha256()
    with open(sortie, "rb") as fh:
        for bloc in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def export_pack(dist: Path, output: Path | None = None, version: str = "0.0.0", dry_run: bool = False,
                domaines=DOMAINES, base: Path | None = None) -> dict:
    """Exporte le pack essentiel depuis la base RAG, prouve contre le dist. Rend le compte rendu."""
    base = Path(base) if base else base_rag()
    if not base.exists():
        raise SystemExit("[pack] base RAG introuvable : %s" % base)
    d = Dist(dist)
    retenus, cr = selectionner(_lignes(base, domaines), d, _juge_public())
    stats = {"format": FORMAT, "version": version, "dist_commit": d.commit, "base": str(base),
             "domaines": cr, "retenus": len(retenus)}
    if not retenus:
        raise SystemExit("[pack] aucun fragment prouve public : rien a publier (%s)" % json.dumps(cr))
    if dry_run:
        return stats
    manifest = {"format": FORMAT, "version": version, "exported_at": datetime.now(UTC).isoformat(),
                "dist_commit": d.commit, "count": len(retenus), "dim": DIM, "model": "BAAI/bge-m3",
                "dtype": "float16", "license": "AGPL-3.0-or-later",
                "critere": "texte present mot pour mot dans un fichier publie du dist a ce commit"}
    sortie = Path(output) if output else OUT_DIR / ("nokido_knowledge_pack_v%s.npz" % version)
    stats["sha256"] = ecrire_pack(sortie, retenus, manifest)
    stats["out_path"], stats["octets"] = str(sortie), sortie.stat().st_size
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dist", required=True, type=Path, help="clone du depot public, lu a son commit HEAD")
    p.add_argument("--output", type=Path, help="defaut : data/nokido_knowledge_pack_v<version>.npz")
    p.add_argument("--version", default="0.0.0")
    p.add_argument("--dry-run", action="store_true", help="compter sans ecrire le pack")
    p.add_argument("--base", type=Path, help="base RAG (defaut : celle de forge_db_path)")
    p.add_argument("--verbose", action="store_true", help="journal detaille")
    a = p.parse_args(argv)
    if a.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    stats = export_pack(a.dist, a.output, a.version, a.dry_run, base=a.base)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
