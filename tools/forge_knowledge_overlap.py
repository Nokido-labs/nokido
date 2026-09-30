"""tools/forge_knowledge_overlap.py - le savoir candidat est-il DEJA digere ?

DETECTEUR DE NOUVEAUTE, place AVANT l'ingestion. Repond a la question owner du
2026-08-30 : « openhands par exemple est a mon avis deja digere ? ».

POURQUOI CE MODULE EXISTE (mesure du 2026-08-30, base %NOKIDO_DATA%\\embeddings.db) :
  rag_chunks ................ 1 331 428 lignes
  doublons EXACTS (texte) ...   166 799  = 12,5 %
  archive de dedup .........      4 806  = la campagne CURATIVE du 2026-07-31
Autrement dit : le curatif a tourne UNE fois, et les doublons se sont
reaccumules x35 depuis. Un nettoyage a posteriori ne tient pas une base qui
ingere en continu -- il faut refuser le doublon A L'ENTREE.

CE MODULE NE SUPPRIME RIEN. Il MESURE et rend un verdict. La suppression reste
au seul chemin gouverne `tools/forge_rag_dedup_hash.py` (ARCHIVE-NOT-PURGE,
nettoie les DEUX tables FTS, sait restaurer).

ARCHITECTURE -- le lexical sert de BLOCKING au vectoriel
  Comparer un chunk candidat aux 1,15 M vecteurs de la base est O(N) par
  candidat, donc impraticable. On procede comme la recherche elle-meme :
    1. LEXICAL: `rag_fts` (BM25) ramene k candidats PLAUSIBLES -- jamais un scan,
                jamais un LIKE (regle d'or n1).
    2. EXACT  : egalite du texte NORMALISE parmi ces k voisins. Un doublon exact
                obtient le score BM25 maximal : s'il existe, il est dans le top-k.
    3. VECTORIEL : cosinus sur ces memes k candidats. O(k), pas O(N).
  Le lexical ne juge pas, il selectionne qui merite d'etre compare.

POURQUOI L'EXACT NE PASSE PAS PAR LA COLONNE `hash` (mesure 2026-08-30)
  La colonne existe, et c'est un piege : elle est peuplee sur 25 485 lignes,
  soit 1,9 % de la table, et son format (12 hex) ne se reproduit ni par sha256
  ni par md5 du texte. Un lookup dessus rend donc « pas de doublon » pour 98 %
  des lignes -- faux negatif SYSTEMATIQUE et muet -- au prix d'un
  `SCAN rag_chunks` mesure a 1,99 s (aucun des 18 index de la table ne couvre
  `hash`). Le hash reste calcule et rendu, pour tracer ; aucune decision ne
  s'y appuie.

GARDE SUR L'ESPACE VECTORIEL -- mesure du 2026-08-30 : 1 055 411 chunks portent
un embedding avec `embedding_model` a NULL (91 %). On ne peut donc PAS supposer
un espace commun. Deux vecteurs ne sont compares que si leurs DIMENSIONS
coincident ; un modele declare different disqualifie la comparaison. Un cosinus
entre deux espaces differents est un nombre qui a l'air d'une mesure.

TROIS ETATS, JAMAIS DEUX. Un candidat sans vecteur, ou dont les voisins n'ont pas
de vecteur comparable, ne sort pas « NEUF » : il sort ILLISIBLE_VECTORIEL. Ne pas
avoir vu n'est pas ne rien avoir trouve.
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/detection-nouveaute"

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Iterable, Optional, Sequence

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# --- verdicts ---------------------------------------------------------------
NEUF = "NEUF"
DOUBLON_EXACT = "DOUBLON_EXACT"
QUASI_DOUBLON = "QUASI_DOUBLON"
ILLISIBLE_VECTORIEL = "ILLISIBLE_VECTORIEL"

# Seuil PAR DEFAUT, a calibrer sur donnees reelles (`--calibrer`). Il n'est pas
# affirme : 0.93 est le point de depart usuel pour bge-m3, la mesure tranche.
SEUIL_QUASI = 0.93
CANDIDATS_PAR_DEFAUT = 25

_MOT = re.compile(r"[A-Za-z0-9_]{3,}")
_ESPACES = re.compile(r"\s+")


# --- couche 1 : hash exact --------------------------------------------------
def normaliser(texte: str) -> str:
    """Forme canonique pour l'egalite EXACTE.

    Casse, espaces et accents decomposes ne font pas un savoir different. La
    normalisation NFC est la meme que celle appliquee a l'ingestion des PDF
    LaTeX (accents flottants), sinon deux textes identiques a l'oeil sortent
    avec deux hashes.
    """
    t = unicodedata.normalize("NFC", texte or "")
    return _ESPACES.sub(" ", t).strip().lower()


def hash_texte(texte: str) -> str:
    """sha256 de la forme normalisee, tronque a 32 hex (collision negligeable)."""
    return hashlib.sha256(normaliser(texte).encode("utf-8")).hexdigest()[:32]


# --- couche 2 : blocking lexical -------------------------------------------
def requete_fts(texte: str, max_termes: int = 12) -> str:
    """Construit une requete FTS5 SURE a partir d'un texte libre.

    FTS5 traite `"` et les operateurs comme de la syntaxe : un texte brut passe
    tel quel fait planter la requete ou, pire, la detourne. On extrait donc des
    mots simples, on garde les plus longs (les plus discriminants pour BM25) et
    on les cite un par un.

    Rend "" si aucun terme exploitable -- l'appelant DOIT traiter ce cas comme
    « pas de blocking possible », pas comme « aucun voisin ».
    """
    mots = _MOT.findall(texte or "")
    if not mots:
        return ""
    vus: dict[str, None] = {}
    for m in sorted(mots, key=len, reverse=True):
        bas = m.lower()
        if bas not in vus:
            vus[bas] = None
        if len(vus) >= max_termes:
            break
    return " OR ".join(f'"{m}"' for m in vus)


# --- couche 3 : vectoriel ---------------------------------------------------
def blob_vers_vecteur(blob: object, dim_attendue: Optional[int] = None):
    """Decode un embedding en vecteur float32, ou None si ILLISIBLE.

    DEUX FORMATS COEXISTENT EN BASE (mesure 2026-08-30, sur 25 voisins tires) :
      - float32 binaire : 4096 octets = 1024 dims (bge-m3)          -- 17 / 25
      - JSON texte      : ~20 400 octets, taille VARIABLE selon les
                          valeurs ecrites                            --  7 / 25
    Ne lire que le binaire fait rendre None sur les seconds, donc « aucun voisin
    comparable » -- une couche vectorielle morte sans que rien ne le signale.
    C'est ce qui s'est produit ici : le candidat lui-meme etait en JSON.

    Le format est reconnu par son PREMIER caractere (`[` = JSON), jamais par la
    taille : un JSON peut faire un multiple de 4 octets et serait alors decode
    en float32 avec succes apparent -- et un vecteur mal decode produit un
    cosinus parfaitement plausible et faux.

    Un vecteur dont la dimension ne correspond pas a `dim_attendue` n'est PAS
    approxime : il rend None. Les deux espaces (384 historique, 1024 bge-m3) ne
    se comparent pas.
    """
    import numpy as np

    if isinstance(blob, (bytes, bytearray, memoryview)):
        b = bytes(blob)
        if not b:
            return None
        tete = b.lstrip()[:1]
        if tete == b"[":
            try:
                brut = json.loads(b.decode("utf-8", errors="strict"))
            except (UnicodeDecodeError, ValueError):
                return None
            v = np.asarray(brut, dtype=np.float32).ravel()
        elif len(b) % 4 == 0:
            v = np.frombuffer(b, dtype=np.float32)
        else:
            return None
    elif isinstance(blob, str):
        s = blob.strip()
        if not s.startswith("["):
            return None
        try:
            v = np.asarray(json.loads(s), dtype=np.float32).ravel()
        except (ValueError, TypeError):
            return None
    else:
        return None

    if v.size == 0 or not np.all(np.isfinite(v)):
        return None
    if dim_attendue is not None and v.size != dim_attendue:
        return None
    return v


def cosinus(a, b) -> Optional[float]:
    """Cosinus de deux vecteurs de MEME dimension, ou None si incomparables.

    Rendre None plutot que 0.0 : un 0.0 se lit comme « tres different », alors
    qu'il signifie ici « je n'ai pas pu comparer ».
    """
    import numpy as np

    if a is None or b is None or a.size != b.size:
        return None
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 0.0 or nb <= 0.0:
        return None
    return float(np.dot(a, b) / (na * nb))


def modeles_comparables(m_candidat: Optional[str], m_voisin: Optional[str]) -> bool:
    """Deux embeddings sont comparables si aucun ne CONTREDIT l'autre.

    91 % des lignes ont `embedding_model` a NULL : exiger l'egalite stricte
    disqualifierait presque tout. On refuse donc seulement quand les deux
    modeles sont declares ET differents. L'inconnu reste comparable, la
    contradiction non.
    """
    if m_candidat and m_voisin:
        return m_candidat == m_voisin
    return True


# --- verdict ----------------------------------------------------------------
def verdict(
    exact: bool,
    meilleur_cos: Optional[float],
    voisins_compares: int,
    seuil: float = SEUIL_QUASI,
) -> str:
    """Assemble les trois couches en UN verdict a trois etats (+ exact).

    `voisins_compares` est le denominateur : sans lui, un `meilleur_cos` a None
    ne se distingue pas de « aucun voisin proche ».
    """
    if exact:
        return DOUBLON_EXACT
    if voisins_compares == 0 or meilleur_cos is None:
        return ILLISIBLE_VECTORIEL
    return QUASI_DOUBLON if meilleur_cos >= seuil else NEUF


# --- acces base (lecture seule) --------------------------------------------
def ouvrir_lecture(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Connexion LECTURE SEULE.

    Un detecteur de nouveaute n'ecrit jamais : `mode=ro` rend la faute
    impossible plutot que la deconseiller, et evite de tenir un verrou sur une
    base ou d'autres ingerent (cf. `database is locked`).
    """
    from app.forge_db_path import DB_PATH

    p = Path(db_path) if db_path else Path(DB_PATH)
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10.0)


def candidats_lexicaux(
    conn: sqlite3.Connection, texte: str, k: int = CANDIDATS_PAR_DEFAUT
) -> list[tuple]:
    """k voisins plausibles via BM25. Jamais de LIKE, jamais de scan.

    Le top-k est reduit AVANT la jointure, en sous-requete. Ecrit en JOIN direct,
    SQLite joignait rag_chunks sur TOUS les matches avant de trier par bm25 :
    mesure 2026-08-30, 9,65 s pour 8 voisins. Ici la jointure ne porte que sur k
    identifiants, resolus par la clef primaire.
    """
    q = requete_fts(texte)
    if not q:
        return []
    try:
        return conn.execute(
            "SELECT c.id, c.source, c.embedding, c.embedding_model, c.text "
            "FROM rag_chunks c WHERE c.id IN ("
            "  SELECT chunk_id FROM rag_fts WHERE rag_fts MATCH ?"
            "  ORDER BY bm25(rag_fts) LIMIT ?)",
            (q, k),
        ).fetchall()
    except sqlite3.Error:
        return []


def est_neuf(
    conn: sqlite3.Connection,
    texte: str,
    vecteur=None,
    modele: Optional[str] = None,
    seuil: float = SEUIL_QUASI,
    k: int = CANDIDATS_PAR_DEFAUT,
    ignorer_id: Optional[str] = None,
) -> dict:
    """Verdict complet pour UN texte candidat.

    Rend toujours le denominateur (`voisins_vus`, `voisins_compares`) : un
    verdict NEUF sans denominateur ne se distingue pas d'une sonde aveugle.

    `ignorer_id` exclut une ligne du voisinage. Indispensable des qu'on evalue
    un chunk DEJA en base : il se retrouve lui-meme, cosinus 1.0 et texte
    identique, et la mesure sort « 100 % de doublons » -- un chiffre qui ARRANGE
    et qui ne mesure rien. Mesure du 2026-08-30 sans ce garde : 25/25
    DOUBLON_EXACT sur l'echantillon openhands.
    """
    h = hash_texte(texte)
    cible = normaliser(texte)
    voisins = candidats_lexicaux(conn, texte, k)

    exact_id = None
    meilleur, meilleur_id, compares = None, None, 0
    vus = 0

    for cid, _src, blob, mdl, txt in voisins:
        if ignorer_id is not None and cid == ignorer_id:
            continue
        vus += 1
        if exact_id is None and normaliser(txt or "") == cible:
            exact_id = cid
        if vecteur is None:
            continue
        if not modeles_comparables(modele, mdl):
            continue
        v = blob_vers_vecteur(blob, dim_attendue=vecteur.size)
        if v is None:
            continue
        c = cosinus(vecteur, v)
        if c is None:
            continue
        compares += 1
        if meilleur is None or c > meilleur:
            meilleur, meilleur_id = c, cid

    return {
        "verdict": verdict(exact_id is not None, meilleur, compares, seuil),
        "hash": h,
        "doublon_exact_id": exact_id,
        "meilleur_cosinus": meilleur,
        "plus_proche_id": meilleur_id,
        "voisins_vus": vus,
        "voisins_compares": compares,
        "seuil": seuil,
    }


def recouvrement_source(
    conn: sqlite3.Connection, motif_source: str, limite: int = 200
) -> dict:
    """« <sujet> est-il deja digere ? » -- mesure le RECOUVREMENT d'une source.

    Prend les chunks deja en base dont la source correspond, et regarde combien
    d'entre eux ont un quasi-doublon AILLEURS (autre source). Un fort taux =
    savoir acquis de seconde main, deja present avant l'ingestion directe.
    """
    q = requete_fts(motif_source, max_termes=4)
    if not q:
        return {"erreur": "motif inexploitable", "echantillon": 0}
    try:
        lignes = conn.execute(
            "SELECT c.id, c.source, c.embedding, c.embedding_model, c.text "
            "FROM rag_fts f JOIN rag_chunks c ON c.id = f.chunk_id "
            "WHERE rag_fts MATCH ? LIMIT ?",
            (q, limite),
        ).fetchall()
    except sqlite3.Error as exc:
        return {"erreur": f"illisible: {exc}", "echantillon": 0}

    sources: dict[str, int] = {}
    compte = {NEUF: 0, QUASI_DOUBLON: 0, DOUBLON_EXACT: 0, ILLISIBLE_VECTORIEL: 0}
    for cid, src, blob, mdl, txt in lignes:
        sources[str(src)] = sources.get(str(src), 0) + 1
        v = blob_vers_vecteur(blob)
        # `ignorer_id` : un chunk deja en base est toujours son propre voisin.
        r = est_neuf(conn, txt or "", vecteur=v, modele=mdl, ignorer_id=cid)
        compte[r["verdict"]] = compte.get(r["verdict"], 0) + 1

    return {
        "echantillon": len(lignes),
        "sources_distinctes": len(sources),
        "top_sources": sorted(sources.items(), key=lambda kv: -kv[1])[:8],
        "verdicts": compte,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sujet", help="mesure le recouvrement d'un sujet deja en base")
    ap.add_argument("--fichier", help="teste la nouveaute du contenu d'un fichier")
    ap.add_argument("--seuil", type=float, default=SEUIL_QUASI)
    ap.add_argument("--limite", type=int, default=200)
    a = ap.parse_args(argv)

    if not a.sujet and not a.fichier:
        ap.error("donner --sujet ou --fichier")

    conn = ouvrir_lecture()
    try:
        if a.sujet:
            res = recouvrement_source(conn, a.sujet, a.limite)
        else:
            txt = Path(a.fichier).read_text(encoding="utf-8", errors="replace")
            res = est_neuf(conn, txt, seuil=a.seuil)
    finally:
        conn.close()
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
