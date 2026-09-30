"""
forge_vector_index.py — Nokido v18.5 ANN Index (FAISS)
=========================================================
Index HNSW en RAM chargé depuis embeddings.db au démarrage.
Remplace la brute-force O(N) numpy par une recherche O(logN).

FAISS 1.13.2 installé (vérifié).
Fallback numpy si FAISS indisponible.

USAGE :
  from app.forge_vector_index import VectorIndex
  idx = VectorIndex()
  await idx.load()                    # charge depuis DB (~2s pour 100K)
  results = idx.search(query_vec, k=10)
  # → [{"chunk_id": ..., "score": ..., "rank": ...}]

  idx.add(chunk_id, vector)           # ajout en ligne
  idx.remove(chunk_id)                # suppression (rebuild partiel)
  idx.save_checkpoint()               # persist index sur disque (optionnel)
"""

from __future__ import annotations
import sqlite3
import numpy as np
import logging
import time
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import faiss

    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False
    logger.warning("FAISS non disponible — fallback numpy brute-force")


class VectorIndex:
    """
    Index HNSW en RAM sur les embeddings rag_chunks.

    Architecture HNSW (Gemini recommandation) :
      - M=32          : connexions par nœud (qualité graph)
      - ef_construction=200 : profondeur build (précision index)
      - ef_search=64   : profondeur recherche (vitesse vs rappel)
      O(logN) vs O(N) numpy → ~50ms → <2ms à 100K chunks
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        dim: int = 1024,
        index_type: str = "hnsw",  # "hnsw" | "flat" | "ivf"
        checkpoint_path: str | Path | None = None,
    ):
        self._db = Path(db_path) if db_path else (Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
        self.dim = dim
        self.index_type = index_type
        self._checkpoint = (
            Path(checkpoint_path)
            if checkpoint_path
            else (Path(__file__).resolve().parent.parent / "data" / "faiss_index.bin")
        )

        self._index: Optional[object] = None  # faiss index
        self._id_to_pos: dict[str, int] = {}  # chunk_id → position
        self._pos_to_id: list[str] = []  # position → chunk_id
        self._loaded = False
        self._n_vectors = 0

    # ── Construction de l'index ─────────────────────────────────────────────

    def _make_faiss_index(self) -> object:
        """Crée l'index FAISS selon le type configuré."""
        if not HAS_FAISS:
            return None

        # METRIC_INNER_PRODUCT explicite partout : load() normalise les vecteurs
        # "pour cosine similarity via produit scalaire (FAISS IP)", mais ces deux
        # constructeurs prennent L2 PAR DEFAUT. L'ordre restait bon (d² = 2-2·cos
        # est monotone), le SCORE non : search() rendait une distance dans [0, 4]
        # la ou le fallback numpy rend un cosinus dans [-1, 1]. Deux echelles pour
        # la meme API selon que faiss est installe ou non.
        if self.index_type == "hnsw":
            # HNSW : O(logN), excellent pour < 10M vecteurs
            index = faiss.IndexHNSWFlat(self.dim, 32, faiss.METRIC_INNER_PRODUCT)  # M=32
            index.hnsw.efConstruction = 200
            index.hnsw.efSearch = 64
        elif self.index_type == "ivf":
            # IVF : meilleur sur > 1M vecteurs (nécessite entraînement)
            quantizer = faiss.IndexFlatIP(self.dim)
            index = faiss.IndexIVFFlat(quantizer, self.dim, 256, faiss.METRIC_INNER_PRODUCT)
        else:
            # Flat : brute-force FAISS (baseline, exact)
            index = faiss.IndexFlatIP(self.dim)

        return index

    def load(self, domains: list[str] | None = None, limit: int | None = None) -> int:
        """
        Charge les embeddings depuis embeddings.db.
        domains : filtre sur rag_chunks.domain (None = tout)
        limit   : cap optionnel (debug)
        Retourne le nombre de vecteurs indexés.
        """
        t0 = time.perf_counter()
        conn = sqlite3.connect(str(self._db), timeout=60)
        conn.execute("PRAGMA cache_size=-32000")

        # CHARGEMENT EN FLUX, UNE SEULE ALLOCATION (2026-08-25).
        # L'ancienne forme faisait TROIS materialisations pleine taille de la meme
        # donnee : `fetchall()` (tous les blobs en objets Python), puis
        # `np.array(vecs)` (copie complete), puis `matrix / norms` (encore une).
        # Mesure du jour : 1 152 198 vecteurs de 4096 octets = 4,72 Go utiles, et un
        # pic d'engagement du hub a 11,88 Go sur une machine qui en expose 23,67. Le
        # cout n'etait pas l'index, c'etaient les copies -- et ce pic n'est pas un
        # detail de demarrage : c'est lui qui declenche pagination et compression
        # memoire pour tout le corps.
        where = "embedding IS NOT NULL"
        params: list = []
        if domains:
            ph = ",".join("?" * len(domains))
            where += f" AND domain IN ({ph})"
            params.extend(domains)
        q = f"SELECT id, embedding FROM rag_chunks WHERE {where}"
        if limit:
            q += f" LIMIT {limit}"

        # COMBIEN, avant de reserver. Ce COUNT coute 1,9 s mesure sur la base reelle :
        # payer 1,9 s pour ne pas materialiser 4,7 Go d'objets Python est un bon change.
        n_attendu = int(
            conn.execute(f"SELECT COUNT(*) FROM rag_chunks WHERE {where}",
                         params).fetchone()[0] or 0)
        if limit:
            n_attendu = min(n_attendu, int(limit))
        if not n_attendu:
            conn.close()
            logger.warning("VectorIndex.load: aucun vecteur trouvé")
            return 0

        matrix = np.empty((n_attendu, self.dim), dtype=np.float32)
        ids: list[str] = []
        i = 0
        ecartes_type = 0
        ecartes_dim = 0
        ecartes_illisible = 0
        # Le curseur est parcouru PARESSEUSEMENT : a aucun moment la base entiere
        # n'est en memoire. Les vecteurs ecartes sont COMPTES, d'ou un decompte reel
        # `i` qui peut finir sous `n_attendu`.
        for chunk_id, blob in conn.execute(q, params):
            if i >= n_attendu:
                break
            if not isinstance(blob, (bytes, bytearray, memoryview)):
                # DEFAUT PREEXISTANT, mesure 2026-08-25 : des lignes portent leur
                # embedding en TEXT et non en BLOB. L'ancienne forme levait
                # TypeError en plein chargement -- l'index restait a moitie
                # construit et personne ne savait combien de vecteurs manquaient.
                # On ecarte, et surtout on DENOMBRE : une donnee ignoree qu'on ne
                # compte pas surestime la couverture en silence.
                ecartes_type += 1
                continue
            try:
                v = np.frombuffer(blob, dtype=np.float32)
            except Exception:  # noqa: BLE001
                # Blob dont la taille n'est pas un multiple de 4 octets : ce n'est
                # pas un vecteur float32, quoi qu'en dise la colonne. Meme raison
                # qu'au-dessus -- une exception ici interrompait la construction de
                # l'index ENTIER pour une ligne abimee.
                ecartes_illisible += 1
                continue
            if v.shape[0] != self.dim:
                ecartes_dim += 1
                continue
            matrix[i] = v
            ids.append(chunk_id)
            i += 1
        conn.close()

        if ecartes_type or ecartes_dim or ecartes_illisible:
            logger.warning(
                "VectorIndex.load: %d vecteur(s) ecarte(s) sur %d — %d de type non "
                "binaire, %d de taille non decodable, %d de dimension inattendue "
                "(attendu %dd)",
                ecartes_type + ecartes_dim + ecartes_illisible, n_attendu,
                ecartes_type, ecartes_illisible, ecartes_dim, self.dim)

        if i == 0:
            logger.warning("VectorIndex.load: aucun vecteur trouvé")
            return 0
        if i < n_attendu:
            matrix = matrix[:i]  # vue, pas copie

        # Normaliser pour cosine similarity via produit scalaire (FAISS IP).
        # EN PLACE : `matrix = matrix / norms` fabriquait un second exemplaire complet.
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix /= norms

        # Construire l'index
        if HAS_FAISS:
            self._index = self._make_faiss_index()
            if self.index_type == "ivf":
                self._index.train(matrix)
            self._index.add(matrix)
        else:
            # Fallback : stockage numpy
            self._matrix_np = matrix

        # Map id ↔ position
        self._pos_to_id = ids
        self._id_to_pos = {cid: i for i, cid in enumerate(ids)}
        self._n_vectors = len(ids)
        self._loaded = True

        elapsed = (time.perf_counter() - t0) * 1000
        backend = f"FAISS/{self.index_type}" if HAS_FAISS else "numpy"
        logger.info(f"VectorIndex: {self._n_vectors} vecteurs {self.dim}d ({backend}) chargés en {elapsed:.0f}ms")
        return self._n_vectors

    # ── Recherche ───────────────────────────────────────────────────────────

    def search(
        self,
        query_vec: np.ndarray | list,
        k: int = 10,
    ) -> list[dict]:
        """
        Recherche les k plus proches voisins.
        query_vec : vecteur 1024d (non normalisé ok)
        Retourne : [{"chunk_id":..., "score":float, "rank":int}]
        """
        if not self._loaded:
            raise RuntimeError("VectorIndex: appeler .load() d'abord")

        qv = np.array(query_vec, dtype=np.float32)
        norm = np.linalg.norm(qv)
        if norm > 0:
            qv = qv / norm

        k_eff = min(k, self._n_vectors)

        if HAS_FAISS and self._index is not None:
            qv_2d = qv.reshape(1, -1)
            scores, indices = self._index.search(qv_2d, k_eff)
            results = []
            for rank, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if idx < 0:
                    continue
                results.append(
                    {
                        "chunk_id": self._pos_to_id[idx],
                        "score": float(score),
                        "rank": rank,
                    }
                )
        else:
            # Fallback numpy
            sims = self._matrix_np @ qv
            top_idx = np.argpartition(sims, -k_eff)[-k_eff:]
            top_idx = top_idx[np.argsort(sims[top_idx])[::-1]]
            results = [
                {"chunk_id": self._pos_to_id[i], "score": float(sims[i]), "rank": r} for r, i in enumerate(top_idx)
            ]

        return results

    # ── Mise à jour en ligne ────────────────────────────────────────────────

    def add(self, chunk_id: str, vector: np.ndarray | list) -> None:
        """Ajoute un vecteur à l'index en live (sans rebuild complet)."""
        if not self._loaded:
            return
        v = np.array(vector, dtype=np.float32)
        norm = np.linalg.norm(v)
        if norm > 0:
            v = v / norm
        pos = len(self._pos_to_id)
        self._pos_to_id.append(chunk_id)
        self._id_to_pos[chunk_id] = pos
        self._n_vectors += 1

        if HAS_FAISS and self._index is not None:
            self._index.add(v.reshape(1, -1))
        else:
            self._matrix_np = np.vstack([self._matrix_np, v])

    def remove(self, chunk_id: str) -> bool:
        """Marque un chunk comme supprimé (soft delete — rebuild pour purge complète)."""
        if chunk_id not in self._id_to_pos:
            return False
        pos = self._id_to_pos.pop(chunk_id)
        self._pos_to_id[pos] = "__deleted__"
        return True

    # ── Checkpoint ─────────────────────────────────────────────────────────

    def save_checkpoint(self) -> None:
        """Sauvegarde l'index FAISS sur disque (restore rapide au démarrage)."""
        if not HAS_FAISS or self._index is None:
            return
        self._checkpoint.parent.mkdir(exist_ok=True)
        faiss.write_index(self._index, str(self._checkpoint))
        logger.info(f"VectorIndex checkpoint: {self._checkpoint}")

    def load_checkpoint(self) -> bool:
        """Charge depuis checkpoint si disponible (évite rebuild depuis DB)."""
        if not HAS_FAISS or not self._checkpoint.exists():
            return False
        self._index = faiss.read_index(str(self._checkpoint))
        logger.info(f"VectorIndex: checkpoint chargé ({self._checkpoint})")
        return True


# ── Singleton ────────────────────────────────────────────────────────────────

_index_instance: Optional[VectorIndex] = None


def get_vector_index(db_path=None, auto_load=False) -> VectorIndex:
    """Singleton VectorIndex."""
    global _index_instance
    if _index_instance is None:
        _index_instance = VectorIndex(db_path)
        if auto_load:
            _index_instance.load()
    return _index_instance


# ── Self-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    DB = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db")
    print("=== forge_vector_index self-test ===")

    idx = VectorIndex(DB, index_type="hnsw")

    # Charger 5000 chunks pour le test
    n = idx.load(limit=5000)
    print(f"Chargé: {n} vecteurs")

    # Benchmark
    import time

    query = np.random.randn(1024).astype(np.float32)
    runs = []
    for _ in range(20):
        t = time.perf_counter()
        results = idx.search(query, k=10)
        runs.append((time.perf_counter() - t) * 1000)

    avg = sum(runs) / len(runs)
    print(f"HNSW search (k=10, n={n}): {avg:.2f}ms avg / {min(runs):.2f}ms min")
    print(f"Top result: {results[0]}")

    # Test add/remove
    fake_vec = np.random.randn(1024).astype(np.float32)
    idx.add("test_chunk_xyz", fake_vec)
    assert idx.search(fake_vec / np.linalg.norm(fake_vec), k=1)[0]["chunk_id"] == "test_chunk_xyz"
    idx.remove("test_chunk_xyz")
    print("Add/remove: OK")

    print("Self-test PASS")
