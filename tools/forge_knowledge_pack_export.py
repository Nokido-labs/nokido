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
import io
import json
import logging
import lzma
import re
import sqlite3
import subprocess
import sys
import tarfile
import time
import tomllib
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


def famille_source(source: str) -> str:
    """Cle de FAMILLE d'une source = l'unite de licence du pack (rfc, docset:<nom>, watch:<projet>, https:<hote>,
    github:<owner>/<repo> -- la licence d'un depot est celle du depot, 20/10)."""
    s = (source or "").strip()
    if not s:
        return "?"
    if s.startswith(("http://", "https://")):
        schema, reste = s.split("://", 1)
        return "%s:%s" % (schema, reste.split("/", 1)[0])
    tete, _, reste = s.partition(":")
    if len(tete) == 1 and reste[:1] in ("/", "\\"):
        return "chemin_absolu"
    if reste and tete in ("docset", "watch"):
        return "%s:%s" % (tete, re.split(r"[:#/]", reste, maxsplit=1)[0])
    if reste and tete == "github":
        return "github:%s" % "/".join(reste.split("/")[:2])
    if reste:
        return tete
    return re.split(r"[/\\]", s, maxsplit=1)[0]


def inventaire(base: Path, domaines) -> dict:
    """{domaine: {famille: {chunks, octets_texte, avec_vecteur, exemples}}} : la mesure qui precede le decoupage du pack
    par licence (owner 20/10). Index `domain` seul (`+active` ne le detourne pas), aucun COUNT, et la colonne vecteur
    n'est jamais lue : `embedding IS NOT NULL` se juge sur l'en-tete de l'enregistrement."""
    octets = "octet_length(text)" if sqlite3.sqlite_version_info >= (3, 43) else "length(CAST(text AS BLOB))"
    inv: dict = {}
    con = sqlite3.connect("file:%s?mode=ro" % Path(base).as_posix(), uri=True, timeout=30)
    try:
        for d in domaines:
            par = inv.setdefault(d, {})
            for source, taille, vecteur in con.execute(
                    "SELECT source, %s, embedding IS NOT NULL FROM rag_chunks WHERE domain=? AND +active=1" % octets,
                    (d,)):
                f = par.setdefault(famille_source(source),
                                   {"chunks": 0, "octets_texte": 0, "avec_vecteur": 0, "exemples": []})
                f["chunks"] += 1
                f["octets_texte"] += taille or 0
                f["avec_vecteur"] += 1 if vecteur else 0
                if len(f["exemples"]) < 3 and source not in f["exemples"]:
                    f["exemples"].append(source)
    finally:
        con.close()
    return inv


MANIFESTE_KNOWLEDGE = ROOT / "distribution" / "packs" / "knowledge.toml"
FORMAT_SOURCE = "nokido-pack-source/1"
NOM_PACK_SOURCE = "nokido_pack_{famille}_v{version}.tar"  # = forge_release_assets.BUILDERS["rag_pack_source"]
_LICENCES_NON_AFFIRMEES = ("", "NOASSERTION", "INCONNU", "UNKNOWN")
MIROIR_RFC = ROOT / "data" / "rfc_mirror"
_TITRES_COPYRIGHT = ("Copyright Notice", "Full Copyright Statement")
_TITRES_AUTEURS = ("Authors' Addresses", "Author's Address")
_RE_PIED_PAGE_RFC = re.compile(r"\[Page \d+\]\s*$")
_RE_ENTETE_PAGE_RFC = re.compile(r"^RFC\s+\d+\s{2,}")


def slug_famille(famille: str) -> str:
    """docset:Flask -> docset-flask : la famille dans un nom de fichier."""
    return re.sub(r"[^a-z0-9]+", "-", famille.lower()).strip("-")


def _verifier_composant_source(c: dict) -> None:
    """Liste BLANCHE : seule s'exporte une source declaree pack par source, licence AFFIRMEE et PROUVEE en https."""
    if c.get("construit") != "rag_pack_source":
        raise ValueError("%s : pas un pack par source (construit=%r)" % (c.get("id"), c.get("construit")))
    if not str(c.get("famille") or "").strip():
        raise ValueError("%s : famille absente" % c.get("id"))
    if str(c.get("licence") or "").strip().upper() in _LICENCES_NON_AFFIRMEES:
        raise ValueError("%s : licence non affirmee (%r), source non redistribuable" % (c.get("id"), c.get("licence")))
    if not str(c.get("preuve") or "").startswith("https://"):
        raise ValueError("%s : preuve de licence https absente" % c.get("id"))


class _Suite(io.RawIOBase):
    """En-tete .npy puis les octets bruts des vecteurs : le membre du tar s'ecrit sans recopie intermediaire."""

    def __init__(self, tete: bytes, fichier):
        self._tete, self._f = io.BytesIO(tete), fichier

    def readable(self):
        return True

    def readinto(self, b):
        return self._tete.readinto(b) or self._f.readinto(b)


def _ajouter(tar, nom: str, octets: int, flux) -> None:
    info = tarfile.TarInfo(nom)
    info.size, info.mtime, info.mode = octets, int(time.time()), 0o644
    tar.addfile(info, flux)


def _section_rfc(lignes, titres) -> str | None:
    """Corpus LEGAL verbatim d'une RFC : du titre (colonne 0) jusqu'au prochain titre de colonne 0, sans les
    pieds de page `[Page N]` ni les en-tetes `RFC NNNN ...` qui coupent le texte a chaque saut de page."""
    debut = None
    for i, ligne in enumerate(lignes):
        if ligne.strip() in titres:
            debut = i + 1
            break
    if debut is None:
        return None
    corps = []
    for ligne in lignes[debut:]:
        s = ligne.rstrip("\n")
        if _RE_PIED_PAGE_RFC.search(s) or _RE_ENTETE_PAGE_RFC.match(s):
            continue
        if s and not s[0].isspace():
            break
        corps.append(s)
    texte = "\n".join(corps).strip()
    return texte or None


def sections_legales_rfc(texte) -> dict:
    """Les deux sections legales d'une RFC, telles que publiees : copyright et auteurs (IETF TLP 5.0 3.c.iii.y)."""
    lignes = str(texte).replace("\r\n", "\n").split("\n")
    return {"copyright": _section_rfc(lignes, _TITRES_COPYRIGHT),
            "auteurs": _section_rfc(lignes, _TITRES_AUTEURS)}


def notice_rfc(numero, texte) -> str | None:
    """Notice d'une RFC = entete RFC 9110 + sa legende verbatim. Sans copyright lisible : None, jamais inventee."""
    s = sections_legales_rfc(texte)
    if not s["copyright"]:
        return None
    n = int(numero)
    morceaux = ["RFC %d -- https://www.rfc-editor.org/rfc/rfc%d" % (n, n), s["copyright"]]
    if s["auteurs"]:
        morceaux.append(s["auteurs"])
    return "\n\n".join(morceaux)


def _numero_rfc(source):
    m = re.match(r"^rfc:rfc(\d+)", (source or "").strip(), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _notice_rfc_source(numero, miroir, cache) -> str | None:
    """Legende d'une RFC lue dans le miroir local (source unique, mise en cache) : lecture seule, doute = None."""
    if numero in cache:
        return cache[numero]
    texte = ""
    try:
        texte = Path(miroir, "rfc%d.txt" % numero).read_text(encoding="utf-8", errors="replace")
    except OSError:
        texte = ""
    notice = notice_rfc(numero, texte)
    cache[numero] = notice
    return notice


def exporter_sources(base, composants, sortie, version: str, domaine: str = "reference",
                     dry_run: bool = False, miroir_rfc=None) -> dict:
    """Un pack par SOURCE = par licence (owner 20/10), en UN passage sur le domaine : tar NON compresse portant
    vecteurs.npy (float16, lisible en mmap), textes.jsonl.xz, NOTICE.txt et manifest.json. Memes filtres que le pack
    essentiel ; un doublon de TEXTE est ecarte et compte. Toute source est verifiee AVANT la moindre ecriture.
    `dry_run` COMPTE sans ouvrir un seul fichier : une mesure ne coute pas des gigaoctets d'ecriture.
    Chaque fragment d'une source `rfc` est refuse (compte `legende_rfc_absente`) si sa legende d'origine est
    illisible : la NOTICE du pack rfc joint alors la legende verbatim de CHAQUE RFC retenue (IETF TLP 5.0).
    Un composant peut porter son `domaine` (defaut : l'argument `domaine`) : un passage par domaine (20/10)."""
    for c in composants:
        _verifier_composant_source(c)
    miroir = Path(miroir_rfc) if miroir_rfc is not None else MIROIR_RFC
    notices_lues = {}
    par = {c["famille"]: c for c in composants}
    etats = {f: {"n": 0, "doublons": 0, "vus": set(), "ecartes": Counter(), "octets_texte": 0,
                 "notices_rfc": {}} for f in par}
    if not dry_run:
        sortie = Path(sortie)
        sortie.mkdir(parents=True, exist_ok=True)
        for f, e in etats.items():
            e["brut"] = sortie / (".%s.vecteurs.tmp" % slug_famille(f))
            e["xz"] = sortie / (".%s.textes.tmp" % slug_famille(f))
            e["fv"] = open(e["brut"], "wb")
            e["ft"] = lzma.open(e["xz"], "wt", encoding="utf-8")
    con = sqlite3.connect("file:%s?mode=ro" % Path(base).as_posix(), uri=True, timeout=30)
    try:
        # 20/10 : un composant porte son domaine (physiologie...) -- un passage indexe par domaine declare.
        domaines = sorted({c.get("domaine") or domaine for c in composants})
        lignes = (r for d in domaines for r in con.execute(
            "SELECT id, source, text, embedding FROM rag_chunks WHERE domain=? AND +active=1 "
            "AND embedding IS NOT NULL", (d,)))
        for cid, source, texte, blob in lignes:
            fam = famille_source(source)
            e = etats.get(fam)
            if e is None:
                continue
            numero = None
            legende = None
            if fam == "rfc":
                numero = _numero_rfc(source)
                if numero:
                    legende = _notice_rfc_source(numero, miroir, notices_lues)
                if not legende:
                    e["ecartes"]["legende_rfc_absente"] += 1
                    continue
            t = normaliser(texte)
            if len(t) < LONGUEUR_MIN:
                e["ecartes"]["trop_court"] += 1
                continue
            vec = decoder_vecteur(blob)
            if vec is None or vec.shape != (DIM,) or not np.isfinite(vec).all():
                e["ecartes"]["vecteur_invalide"] += 1
                continue
            norme = float(np.linalg.norm(vec.astype(np.float64)))
            if not np.isfinite(norme) or abs(norme - 1.0) > 0.02:
                e["ecartes"]["vecteur_non_norme"] += 1
                continue
            if any(p.search(texte) for p in SECRET_PATTERNS):
                e["ecartes"]["secret"] += 1
                continue
            if any(p.search(texte) for p in PII_PATTERNS):
                e["ecartes"]["identite"] += 1
                continue
            empreinte = hashlib.sha256(t.encode("utf-8")).digest()
            if empreinte in e["vus"]:
                e["doublons"] += 1
                continue
            e["vus"].add(empreinte)
            e["n"] += 1
            e["octets_texte"] += len(texte.encode("utf-8"))
            if numero:
                e["notices_rfc"][numero] = legende
            if not dry_run:
                e["fv"].write(vec.astype(np.float16).tobytes())
                e["ft"].write(json.dumps({"id": cid, "source": source, "texte": texte}, ensure_ascii=False) + "\n")
    finally:
        con.close()
        for e in etats.values():
            for k in ("fv", "ft"):
                if k in e:
                    e[k].close()
    if dry_run:
        return {f: {"famille": f, "retenus": e["n"], "doublons": e["doublons"], "ecartes": dict(e["ecartes"]),
                    "octets_vecteurs": e["n"] * DIM * 2, "octets_texte": e["octets_texte"]} for f, e in etats.items()}
    stats = {}
    try:
        for f, e in etats.items():
            c = par[f]
            nom = NOM_PACK_SOURCE.format(famille=slug_famille(f), version=version)
            tete = io.BytesIO()
            np.lib.format.write_array_header_1_0(tete, {"descr": np.lib.format.dtype_to_descr(np.dtype(np.float16)),
                                                        "fortran_order": False, "shape": (e["n"], DIM)})
            man = {"format": FORMAT_SOURCE, "version": version, "famille": f, "licence": c["licence"],
                   "domaine": c.get("domaine") or domaine,
                   "conditions": c.get("conditions", ""), "preuve": c["preuve"], "count": e["n"], "dim": DIM,
                   "dtype": "float16", "model": "BAAI/bge-m3", "doublons_ecartes": e["doublons"],
                   "ecartes": dict(e["ecartes"]), "exported_at": datetime.now(UTC).isoformat()}
            notice = ("Nokido Knowledge Pack -- source %s (%d fragments, Nokido %s)\n\nLicence du texte : %s\n"
                      "Preuve : %s\nConditions : %s\n\nCes fragments sont des extraits VERBATIM de la documentation "
                      "d'origine : texte non modifie, seulement decoupe en fragments (mention exigee par CC BY et "
                      "Apache 2.0). Ils sont redistribues sous SA licence et ne relevent pas de la licence de Nokido.\n"
                      % (f, e["n"], version, c["licence"], c["preuve"], c.get("conditions", "")))
            if f == "rfc" and e["notices_rfc"]:
                notice += ("Legende d'origine de chaque RFC retenue (IETF TLP 5.0, verbatim) :\n\n"
                           + "\n\n".join(e["notices_rfc"][n] for n in sorted(e["notices_rfc"], key=int)) + "\n")
            chemin = sortie / nom
            with tarfile.open(chemin, "w") as tar, open(e["brut"], "rb") as fv, open(e["xz"], "rb") as ft:
                _ajouter(tar, "vecteurs.npy", len(tete.getvalue()) + e["brut"].stat().st_size,
                         io.BufferedReader(_Suite(tete.getvalue(), fv)))
                _ajouter(tar, "textes.jsonl.xz", e["xz"].stat().st_size, ft)
                for membre, contenu in (("NOTICE.txt", notice), ("manifest.json", json.dumps(man, indent=1))):
                    octets = contenu.encode("utf-8")
                    _ajouter(tar, membre, len(octets), io.BytesIO(octets))
            h = hashlib.sha256()
            with open(chemin, "rb") as fh:
                for bloc in iter(lambda: fh.read(1 << 20), b""):
                    h.update(bloc)
            stats[f] = {"famille": f, "retenus": e["n"], "doublons": e["doublons"], "ecartes": dict(e["ecartes"]),
                        "octets_vecteurs": e["n"] * DIM * 2, "octets_texte": e["octets_texte"],
                        "sha256": h.hexdigest(), "octets": chemin.stat().st_size, "out_path": str(chemin)}
    finally:
        for e in etats.values():
            for k in ("brut", "xz"):
                e[k].unlink(missing_ok=True)
    return stats


def exporter_source(base, composant: dict, sortie: Path, version: str, domaine: str = "reference",
                    miroir_rfc=None) -> dict:
    """Une seule source : voir `exporter_sources` (plusieurs sources = un seul passage sur le domaine)."""
    _verifier_composant_source(composant)
    return exporter_sources(base, [composant], sortie, version, domaine, miroir_rfc=miroir_rfc)[composant["famille"]]


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
# 16/10 (0.20.12) : le FORMAT decrit la STRUCTURE du fichier, que l'importeur verifie ; la facon de CHOISIR les
# fragments est une autre information. L'ancienne etiquette `nokido-knowledge-pack/3-natif` (structure pourtant
# strictement format 2) a fait refuser le pack publie par l'importeur livre dans la meme version -- RAG vide chez
# l'utilisateur. Le pack natif ecrit le FORMAT de l'importeur et dit sa selection a part.
SELECTION_NATIF = "natif"
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
    stats = {"format": FORMAT, "selection": SELECTION_NATIF, "version": version, "dist_commit": d.commit,
             "retenus": len(retenus), **cr}
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
    manifest = {"format": FORMAT, "selection": SELECTION_NATIF, "version": version,
                "exported_at": datetime.now(UTC).isoformat(),
                "dist_commit": d.commit, "count": len(retenus), "dim": DIM, "model": "BAAI/bge-m3 (local :8099 seul)",
                "dtype": "float16", "license": "AGPL-3.0-or-later", "exclus": list(EXCLUS_NATIF),
                "critere": "pack natif : arbre publie du dist a ce commit, decoupe MarkdownChunker 2000/200"}
    sortie = Path(output) if output else OUT_DIR / ("nokido_knowledge_pack_v%s.npz" % version)
    stats["sha256"] = ecrire_pack(sortie, retenus, manifest)
    stats["out_path"], stats["octets"] = str(sortie), sortie.stat().st_size
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dist", type=Path, help="clone du depot public, lu a son commit HEAD (sauf --inventaire)")
    p.add_argument("--output", type=Path, help="defaut : data/nokido_knowledge_pack_v<version>.npz")
    p.add_argument("--version", default="0.0.0")
    p.add_argument("--dry-run", action="store_true", help="compter sans ecrire le pack")
    p.add_argument("--base", type=Path, help="base RAG (defaut : celle de forge_db_path)")
    p.add_argument("--verbose", action="store_true", help="journal detaille")
    p.add_argument("--natif", action="store_true",
                   help="pack NATIF : l'arbre publie lui-meme, decoupe et vectorise en bge-m3 local (15/10)")
    p.add_argument("--inventaire", nargs="*", metavar="DOMAINE",
                   help="mesure par famille de source (defaut : reference), sans pack ni dist ; --output = JSON complet")
    p.add_argument("--sources", action="store_true",
                   help="un pack par source (composants rag_pack_source du manifeste) dans --output ; --dry-run compte")
    p.add_argument("--manifeste", type=Path, default=MANIFESTE_KNOWLEDGE, help="manifeste des packs par source")
    a = p.parse_args(argv)
    if a.verbose:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    if a.sources:
        if not a.output and not a.dry_run:
            p.error("--sources exige --output ou --dry-run")
        with open(a.manifeste, "rb") as fh:
            comps = [c for c in tomllib.load(fh).get("composant", []) if c.get("construit") == "rag_pack_source"]
        stats = exporter_sources(a.base or base_rag(), comps, a.output, a.version, dry_run=a.dry_run)
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        return 0
    if a.inventaire is not None:
        inv = inventaire(a.base or base_rag(), a.inventaire or ["reference"])
        if a.output:
            a.output.parent.mkdir(parents=True, exist_ok=True)
            a.output.write_text(json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")
        for d, familles in inv.items():
            rang = sorted(familles.items(), key=lambda kv: -kv[1]["chunks"])
            print("[inventaire] %s : %d chunks, %d familles (%d montrees)" % (
                d, sum(f["chunks"] for f in familles.values()), len(rang), min(len(rang), 60)))
            for nom, f in rang[:60]:
                print("  %-40s %9d chunks %12d octets %9d vecteurs" % (nom[:40], f["chunks"], f["octets_texte"],
                                                                        f["avec_vecteur"]))
        return 0
    if not a.dist:
        p.error("--dist est requis (sauf --inventaire)")
    if a.natif:
        stats = export_pack_natif(a.dist, a.output, a.version, a.dry_run)
    else:
        stats = export_pack(a.dist, a.output, a.version, a.dry_run, base=a.base)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
