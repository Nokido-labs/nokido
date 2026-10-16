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
import time
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

    def lire_lot(self, chemins: list) -> dict:
        """Contenu de N fichiers a HEAD en UN processus (`git cat-file --batch`).

        15/10 : un `git show` par fichier = 6 089 processus pour le dist v0.20.11, ~30 min de decoupe muette avant
        la premiere vectorisation (promotion de release comprise). Rend {} si git echoue : l'appelant retombe alors
        sur la lecture fichier par fichier, et le dit. Un chemin absent (« missing ») n'est simplement pas rendu."""
        entree = "".join("HEAD:%s\n" % c for c in chemins).encode("utf-8")
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(self.chemin), "cat-file", "--batch"],
                           input=entree, capture_output=True)
        if r.returncode:
            return {}
        out, i, res = r.stdout, 0, {}
        for c in chemins:
            fin = out.find(b"\n", i)
            if fin < 0:
                break
            entete = out[i:fin].decode("utf-8", "replace").split()
            i = fin + 1
            if len(entete) != 3 or entete[-1] == "missing":
                continue
            taille = int(entete[2])
            res[c] = out[i:i + taille].decode("utf-8", "replace")
            i += taille + 1  # le LF qui suit chaque contenu
        return res

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


# ── PACK NATIF (owner 15/10 : « mesure bien que rien d'essentiel n'est absent du knowledge pack ») ─────────────────
# Mesure sur le pack v0.20.11 : 509 des 604 .md publies sans AUCUN fragment (couverture ponderee 13,9 %), dont
# README, CHANGELOG, docs/ARCHITECTURE, SECURITY, MANIFESTO, le wiki (10,3 %), 14 skills sur 33. Cause STRUCTURELLE :
# le pack etait une SELECTION du RAG prive prouvee contre le dist ; tout ce qui a ete ecrit pour le public sans etre
# reingere en sortait. Ici le pack EST l'arbre publie : couverture complete par construction, et un fichier
# essentiel absent refuse le pack au lieu de le laisser partir troue.
FORMAT_NATIF = "nokido-knowledge-pack/3-natif"
CLASSES_NATIF = {".md": "doc", ".py": "code", ".toml": "config", ".yaml": "config", ".yml": "config",
                 ".json": "config", ".txt": "doc"}
EXCLUS_NATIF = ("tests/", ".agents/", ".github/")  # tests = bruit pour le RAG ; .agents = copie de docs/skills
TAILLE_MAX_NATIF = 512_000                          # au-dela : compte « trop_gros » et LISTE, jamais tronque
ESSENTIELS = ("README.md", "CHANGELOG.md", "docs/ARCHITECTURE.md", "RULES_SHARED.md", "SECURITY.md",
              "CONTRIBUTING.md", "MANIFESTO.md")


def classe_natif(chemin: str) -> str | None:
    if chemin.startswith(EXCLUS_NATIF):
        return None
    ext = Path(chemin).suffix.lower()
    c = CLASSES_NATIF.get(ext)
    if c == "doc" and "/skills/" in "/" + chemin:
        return "skill"
    if c == "doc" and chemin.startswith("docs/wiki/"):
        return "wiki"
    return c


def _embed_bge_m3_local(textes: list, er=None) -> list:
    """bge-m3 LOCAL (:8099) SEUL. La cascade d'embed_batch_fast peut finir chez Voyage ou Jina : d'autres espaces
    de vecteurs, melanges en silence dans le pack. Un lot non vectorise rend des None, comptes par l'appelant.

    15/10 (mesure, journal du keeper) : `pilier NokidoLlamaEmbed -> stopped :: sans intention + idle + ram 86 %` a
    19:36:39, en PLEIN pack -- le pack ne declarait pas son besoin (il n'ouvre une connexion que par lot, et
    `embed.wanted` n'etait pose qu'une fois l'embedder deja injoignable). Le client DECLARE donc son besoin avant
    chaque lot (`declare_wanted`, cooldown interne : pas de repetition) ; un refus de l'arbitre est dit par lui."""
    if er is None:
        try:
            from nokido_agent.app import forge_embed_router as er
        except Exception:
            import forge_embed_router as er  # type: ignore[no-redef]
    try:
        er.declare_wanted("embed.wanted", cooldown=120.0, motif="pack natif : vectorisation en cours")
    except Exception as exc:  # noqa: BLE001 -- l'intention ne doit jamais casser le lot ; on le dit
        print("[pack natif] intention embed.wanted NON posee (%s)" % type(exc).__name__, file=sys.stderr, flush=True)
    v = er._llama8099_call(textes, timeout=120.0)
    return v if v and len(v) == len(textes) else [None] * len(textes)


def _vecteur_valide(vec):
    a = np.asarray(vec, dtype=np.float32) if vec is not None else None
    if a is None or a.shape != (DIM,) or not np.isfinite(a).all() or abs(float(np.linalg.norm(a)) - 1) > 0.02:
        return None
    return a


SEUIL_NON_VECTORISE = 0.005  # au-dela, le pack est REFUSE : un pack troue ne sort pas en silence (15/10)


def selectionner_natif(dist, juge, embed_fn, lot: int = 32, reprises: int = 12, pause_s: float = 90.0,
                       pouls=None, dormir=None) -> tuple[list, dict]:
    """Decoupe l'arbre publie, filtre, vectorise.

    15/10 (pack natif v0.20.11 REFUSE) : les six essentiels de la racine passaient tous les filtres (README 80
    fragments, CHANGELOG 172...) mais AUCUN n'a ete vectorise. `sorted()` met les noms en majuscules de la racine en
    TETE : tout le premier bloc (~500 fragments) a echoue cote :8099, et un lot en echec n'etait jamais retente.
    Desormais : reprise des lots en echec en fin de passe (`reprises` fois, apres `pause_s`), compte dans
    `cr["reprises"]` ; un pouls tous les 20 lots (le relais capture la sortie : sans pouls, 2 h de silence).
    La fenetre (12 x 90 s) couvre une VRAIE coupure de l'embedder : le 15/10 il a ete mis en sommeil par le
    superviseur (« reclaim RAM ») puis releve ~17 min plus tard ; 3 x 30 s n'en couvraient que 90 s."""
    pouls = pouls or (lambda m: print(m, file=sys.stderr, flush=True))
    dormir = dormir or time.sleep
    try:
        from nokido_agent.app.forge_rag_store import MarkdownChunker
    except Exception:
        from forge_rag_store import MarkdownChunker  # type: ignore[no-redef]
    cr: dict = {"par_classe": {}, "trop_gros": [], "fichiers_incomplets": {}}
    candidats = []
    retenus_chemins = [ch for ch in sorted(dist.publies) if classe_natif(ch)]
    lus = dist.lire_lot(retenus_chemins) if hasattr(dist, "lire_lot") else None
    if lus is not None and not lus and retenus_chemins:
        pouls("[pack natif] lecture par lot ECHOUEE : repli sur un `git show` par fichier (lent)")
        lus = None
    for n, chemin in enumerate(retenus_chemins, 1):
        c = classe_natif(chemin)
        k = cr["par_classe"].setdefault(c, Counter())
        k["fichiers"] += 1
        if n % 500 == 0 or n == len(retenus_chemins):
            pouls("[pack natif] decoupe : %d/%d fichiers, %d fragments candidats" % (n, len(retenus_chemins),
                                                                                    len(candidats)))
        if lus is not None and chemin in lus:
            rc, brut = 0, lus[chemin]
        else:
            rc, brut = dist._git("show", "HEAD:" + chemin)
        if rc or not brut.strip():
            k["illisible_ou_vide"] += 1
            continue
        if len(brut) > TAILLE_MAX_NATIF:
            cr["trop_gros"].append((chemin, len(brut)))
            continue
        for frag in MarkdownChunker.chunk(brut, 2000, 200):
            t = (frag.get("text") or frag.get("content") or "").strip()
            k["fragments"] += 1
            motif = ("trop_court" if len(t) < LONGUEUR_MIN else "secret" if any(p.search(t) for p in SECRET_PATTERNS)
                     else "identite" if any(p.search(t) for p in PII_PATTERNS) else "juge_rouge" if juge(chemin, t)
                     else None)
            if motif:
                k[motif] += 1
                cr["fichiers_incomplets"].setdefault(chemin, Counter())[motif] += 1
                continue
            cid = hashlib.sha256(("dist:%s|%s" % (chemin, t)).encode("utf-8")).hexdigest()[:16]
            candidats.append((cid, t, chemin, c))
    vecteurs: dict = {}

    def _passe(indices: list) -> list:
        echec, nb = [], (len(indices) + lot - 1) // lot
        for n, i in enumerate(range(0, len(indices), lot), 1):
            bloc = indices[i:i + lot]
            vecs = embed_fn([candidats[j][1] for j in bloc]) or []
            if len(vecs) != len(bloc):  # moins de vecteurs que de textes : tout le lot en echec, jamais un zip qui tronque
                vecs = [None] * len(bloc)
            for j, vec in zip(bloc, vecs):
                a = _vecteur_valide(vec)
                if a is None:
                    echec.append(j)
                else:
                    vecteurs[j] = a
            if n % 20 == 0 or n == nb:
                pouls("[pack natif] lot %d/%d : %d vectorises, %d en echec" % (n, nb, len(vecteurs), len(echec)))
        return echec

    en_echec = _passe(list(range(len(candidats))))
    cr["reprises"] = {"premiere_passe_en_echec": len(en_echec), "tentatives": 0, "recuperes": 0}
    for essai in range(1, reprises + 1):
        if not en_echec:
            break
        pouls("[pack natif] reprise %d/%d : %d fragments non vectorises, dans %.0f s" % (essai, reprises, len(en_echec),
                                                                                     pause_s))
        dormir(pause_s)
        avant = len(en_echec)
        en_echec = _passe(en_echec)
        cr["reprises"]["tentatives"] = essai
        cr["reprises"]["recuperes"] += avant - len(en_echec)
    retenus = []
    for j, (cid, t, chemin, c) in enumerate(candidats):  # ordre des candidats conserve : pack deterministe
        if j in vecteurs:
            cr["par_classe"][c]["retenus"] += 1
            retenus.append((cid, t, chemin, c, vecteurs[j]))
        else:
            cr["par_classe"][c]["non_vectorise"] += 1
            cr["fichiers_incomplets"].setdefault(chemin, Counter())["non_vectorise"] += 1
    garde = {r[2] for r in retenus}
    # Revue AGY 15/10 : `e in dist.publies` laissait passer un essentiel SUPPRIME du dist (README efface par erreur) :
    # le pack partait sans lui, sans refus. Absent du dist ou sans fragment retenu : les deux refusent, motif distinct.
    cr["essentiels_absents"] = [e if e in dist.publies else "%s (ABSENT DU DIST)" % e for e in ESSENTIELS
                                if e not in garde]
    cr["non_vectorise_total"] = len(candidats) - len(retenus)
    cr["candidats"] = len(candidats)
    cr["par_classe"] = {c: dict(v) for c, v in cr["par_classe"].items()}
    cr["fichiers_incomplets"] = {f: dict(v) for f, v in cr["fichiers_incomplets"].items()}
    return retenus, cr


def export_pack_natif(dist: Path, output: Path | None = None, version: str = "0.0.0", dry_run: bool = False,
                      embed_fn=None) -> dict:
    d = Dist(dist)
    retenus, cr = selectionner_natif(d, _juge_public(), embed_fn or _embed_bge_m3_local)
    stats = {"format": FORMAT_NATIF, "version": version, "dist_commit": d.commit, "retenus": len(retenus), **cr}
    trou = cr.get("non_vectorise_total", 0) / max(cr.get("candidats", 0), 1)
    if cr["essentiels_absents"] or trou > SEUIL_NON_VECTORISE:
        # Le rapport part AVANT le refus : le 15/10 il etait perdu, et la cause a du etre reconstituee a la main.
        print(json.dumps(stats, ensure_ascii=False, indent=1, default=str), file=sys.stderr, flush=True)
        if cr["essentiels_absents"]:
            raise SystemExit("[pack natif] REFUSE : fichiers essentiels sans aucun fragment retenu : %s"
                             % cr["essentiels_absents"])
        raise SystemExit("[pack natif] REFUSE : %d fragments sur %d NON vectorises (%.2f %% > %.1f %%) -- embedder "
                         "indisponible trop longtemps ; relancer quand :8099 tient" % (
                             cr["non_vectorise_total"], cr["candidats"], 100 * trou, 100 * SEUIL_NON_VECTORISE))
    if dry_run or not retenus:
        return stats
    manifest = {"format": FORMAT_NATIF, "version": version, "exported_at": datetime.now(UTC).isoformat(),
                "dist_commit": d.commit, "count": len(retenus), "dim": DIM, "model": "BAAI/bge-m3 (local :8099 seul)",
                "dtype": "float16", "license": "AGPL-3.0-or-later", "exclus": list(EXCLUS_NATIF),
                "critere": "pack natif : arbre publie du dist a ce commit, decoupe MarkdownChunker 2000/200"}
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
    p.add_argument("--natif", action="store_true",
                   help="pack NATIF : l'arbre publie lui-meme, decoupe et vectorise en bge-m3 local (15/10)")
    a = p.parse_args(argv)
    if a.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    if a.natif:
        stats = export_pack_natif(a.dist, a.output, a.version, a.dry_run)
    else:
        stats = export_pack(a.dist, a.output, a.version, a.dry_run, base=a.base)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
