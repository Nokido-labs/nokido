"""
forge_novelty_search.py — Novelty Search (Stanley/Lehman 2011)

Récompense la NOUVEAUTÉ, pas l'objectif. Mécanique de Frustration → Innovation.

Principe (Why Greatness Cannot Be Planned) :
- Viser un objectif = stuck local optima
- Récompenser la novelty (distance comportementale) = découverte sérendipité

Application Nokido :
- Chaque tentative (intent JSON-RPC) = behavior signature
- Archive des comportements passés (k-NN sur signature)
- Score de nouveauté = distance moyenne aux k voisins
- Frustration → boost le poids de novelty vs reward elegance

Combiné avec forge_motivation :
- Si dopamine baisse + cortisol monte → mode novelty (innovation)
- Si dopamine stable → mode reward (exploitation)

Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:novelty_search|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "embeddings.db"

# Calibration
ARCHIVE_MAX_SIZE = 5000  # capacity max archive comportements
KNN_K = 15  # k voisins pour distance novelty
NOVELTY_THRESHOLD_NEW = 0.3  # si novelty > 0.3 → "découverte"
EXPLORATION_BOOST_DURATION = 1800  # 30min boost après frustration

_SCHEMA = """
CREATE TABLE IF NOT EXISTS novelty_archive (
    sig_hash TEXT PRIMARY KEY,
    method TEXT NOT NULL,
    target TEXT,
    behavior_signature TEXT,
    novelty_score REAL,
    success INTEGER,
    elegance REAL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_novelty_method ON novelty_archive(method);
CREATE INDEX IF NOT EXISTS idx_novelty_ts ON novelty_archive(ts);

CREATE TABLE IF NOT EXISTS novelty_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in _SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()


def _signature(method: str, params: Dict[str, Any]) -> str:
    """Signature comportementale = method + params canoniques."""
    canon = json.dumps({"m": method, "p": params}, sort_keys=True, default=str)
    return canon[:500]


def _sig_hash(sig: str) -> str:
    return hashlib.sha256(sig.encode()).hexdigest()[:16]


def _hamming_jaccard(s1: str, s2: str) -> float:
    """Distance comportementale entre 2 signatures.

    Combo : Jaccard sur tokens + différence longueur.
    Retourne 0 (identique) → 1 (très distant).
    """
    t1 = set(s1.split())
    t2 = set(s2.split())
    if not t1 and not t2:
        return 0.0
    inter = len(t1 & t2)
    union = len(t1 | t2)
    jaccard = 1.0 - (inter / union if union else 0)
    # Aussi : différence longueur normalisée
    len_diff = abs(len(s1) - len(s2)) / max(len(s1), len(s2), 1)
    return min(1.0, 0.7 * jaccard + 0.3 * len_diff)


def compute_novelty(method: str, params: Dict[str, Any], k: int = KNN_K) -> float:
    """Score nouveauté 0-1 = distance moyenne aux k voisins de l'archive."""
    sig = _signature(method, params)
    conn = sqlite3.connect(str(DEFAULT_DB))
    _ensure_schema(conn)
    rows = conn.execute(
        "SELECT behavior_signature FROM novelty_archive WHERE method=? OR method LIKE ? ORDER BY ts DESC LIMIT ?",
        (method, f"{method.split('_')[0]}%", k * 3),  # voisinage méthode même famille
    ).fetchall()
    conn.close()
    if not rows:
        return 1.0  # archive vide pour cette méthode → max nouveauté
    distances = [_hamming_jaccard(sig, r[0] or "") for r in rows]
    distances.sort()
    nearest_k = distances[:k]
    if not nearest_k:
        return 1.0
    return round(sum(nearest_k) / len(nearest_k), 4)


def archive_behavior(
    method: str, params: Dict[str, Any], success: bool, elegance: float = 1.0, target: str = ""
) -> Dict[str, Any]:
    """Archive un comportement avec son score novelty."""
    sig = _signature(method, params)
    h = _sig_hash(sig)
    novelty = compute_novelty(method, params)
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO novelty_archive (sig_hash, method, target, behavior_signature, novelty_score, success, elegance, ts) VALUES (?,?,?,?,?,?,?,?)",
            (h, method, target[:200], sig, novelty, 1 if success else 0, elegance, time.time()),
        )
        # Trim archive si > MAX
        cur = conn.execute("SELECT COUNT(*) FROM novelty_archive").fetchone()[0]
        if cur > ARCHIVE_MAX_SIZE:
            conn.execute(
                "DELETE FROM novelty_archive WHERE sig_hash IN (SELECT sig_hash FROM novelty_archive ORDER BY ts ASC LIMIT ?)",
                (cur - ARCHIVE_MAX_SIZE,),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"sig_hash": h, "novelty": novelty, "is_discovery": novelty >= NOVELTY_THRESHOLD_NEW}


def is_exploration_mode() -> bool:
    """Mode exploration actif si frustration récente (boost 30min)."""
    try:
        from nokido_agent.app.forge_endocrine import read

        cortisol = read("CORTISOL_FRUSTRATION")
        return cortisol > 0.4
    except Exception:
        return False


def combined_score(elegance: float, novelty: float, exploration_weight: Optional[float] = None) -> float:
    """Score combiné : exploit (élégance) vs explore (nouveauté).

    En mode normal : score = 0.7×elegance + 0.3×novelty
    En mode exploration : score = 0.3×elegance + 0.7×novelty
    """
    if exploration_weight is None:
        exploration_weight = 0.7 if is_exploration_mode() else 0.3
    exploit_weight = 1.0 - exploration_weight
    return round(exploit_weight * elegance + exploration_weight * novelty, 4)


def find_novel_alternatives(method: str, n: int = 5) -> List[Dict[str, Any]]:
    """Suggère N comportements PASSÉS les + nouveaux pour méthodes similaires.

    Utile dans curiosity_prompt : "voici 5 alternatives jamais essayées sur même target".
    """
    family = method.split("_")[0] if "_" in method else method
    conn = sqlite3.connect(str(DEFAULT_DB))
    _ensure_schema(conn)
    rows = conn.execute(
        "SELECT method, target, behavior_signature, novelty_score, success FROM novelty_archive "
        "WHERE method LIKE ? AND method != ? ORDER BY novelty_score DESC LIMIT ?",
        (f"{family}%", method, n),
    ).fetchall()
    conn.close()
    return [
        {
            "method": r[0],
            "target": r[1],
            "novelty": r[3],
            "success": bool(r[4]),
            "signature_preview": (r[2] or "")[:200],
        }
        for r in rows
    ]


def archive_stats() -> Dict[str, Any]:
    conn = sqlite3.connect(str(DEFAULT_DB))
    _ensure_schema(conn)
    total = conn.execute("SELECT COUNT(*) FROM novelty_archive").fetchone()[0]
    success = conn.execute("SELECT COUNT(*) FROM novelty_archive WHERE success=1").fetchone()[0]
    avg_nov = conn.execute("SELECT AVG(novelty_score) FROM novelty_archive").fetchone()[0]
    discoveries = conn.execute(
        "SELECT COUNT(*) FROM novelty_archive WHERE novelty_score>=?", (NOVELTY_THRESHOLD_NEW,)
    ).fetchone()[0]
    by_method = conn.execute(
        "SELECT method, COUNT(*), AVG(novelty_score), AVG(elegance) FROM novelty_archive GROUP BY method ORDER BY COUNT(*) DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return {
        "archive_size": total,
        "success_count": success,
        "avg_novelty": round(avg_nov or 0, 4),
        "discoveries": discoveries,
        "exploration_mode": is_exploration_mode(),
        "top_methods": [
            {"method": r[0], "count": r[1], "avg_nov": round(r[2] or 0, 3), "avg_eleg": round(r[3] or 0, 3)}
            for r in by_method
        ],
    }


# ============================================================
# Hook : à appeler depuis dispatch_intent ou hooks externes
# ============================================================
def observe_intent(
    method: str, params: Dict[str, Any], success: bool, elegance: float = 1.0, target: str = ""
) -> Dict[str, Any]:
    """Observe un intent + retourne décision routing.

    Returns:
        {novelty, elegance, combined, is_discovery, recommend, alternatives}
    """
    res = archive_behavior(method, params, success, elegance, target)
    novelty = res["novelty"]
    combined = combined_score(elegance, novelty)
    recommend = "exploit"
    if is_exploration_mode():
        recommend = "explore"
    elif novelty < 0.1 and elegance < 0.5:
        recommend = "abandon"
    elif res["is_discovery"] and success:
        recommend = "amplify"
    alt = find_novel_alternatives(method, n=3) if novelty < 0.1 else []
    return {
        "sig_hash": res["sig_hash"],
        "novelty": novelty,
        "elegance": elegance,
        "combined_score": combined,
        "is_discovery": res["is_discovery"],
        "recommend": recommend,
        "alternatives": alt,
        "exploration_mode": is_exploration_mode(),
    }


# ============================================================
# AutoencoderNovelty — détection d'anomalie par reconstruction
# ============================================================
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim

    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False


class AutoencoderNovelty:
    """Autoencoder de curiosité : erreur de reconstruction = score de surprise.

    Fallback numpy si torch absent : MSE vs centroïde running-mean.
    """

    def __init__(self, input_dim: int = 64, latent_dim: int = 8):
        self.input_dim = input_dim
        self.latent_dim = latent_dim
        self._threshold: float = 0.05  # tau dynamique (FlowRegulator l'injecte)

        if _TORCH_OK:

            class _AE(nn.Module):
                def __init__(self, d: int, z: int):
                    super().__init__()
                    self.enc = nn.Sequential(nn.Linear(d, 32), nn.ReLU(), nn.Linear(32, z))
                    self.dec = nn.Sequential(nn.Linear(z, 32), nn.ReLU(), nn.Linear(32, d), nn.Sigmoid())

                def forward(self, x):
                    return self.dec(self.enc(x))

            self._model = _AE(input_dim, latent_dim)
            self._opt = optim.Adam(self._model.parameters(), lr=1e-3)
            self._loss_fn = nn.MSELoss()
        else:
            import numpy as np

            self._centroid = np.zeros(input_dim, dtype=float)
            self._n_seen = 0

    def set_threshold(self, tau: float) -> None:
        self._threshold = tau

    def evaluate_novelty(self, vector: list) -> float:
        if _TORCH_OK:
            x = torch.tensor(vector, dtype=torch.float32).unsqueeze(0)
            self._model.eval()
            with torch.no_grad():
                rec = self._model(x)
                return float(self._loss_fn(rec, x).item())
        else:
            import numpy as np

            v = np.array(vector, dtype=float)
            return float(np.mean((v - self._centroid) ** 2))

    def learn_pattern(self, vector: list) -> float:
        if _TORCH_OK:
            x = torch.tensor(vector, dtype=torch.float32).unsqueeze(0)
            self._model.train()
            self._opt.zero_grad()
            rec = self._model(x)
            loss = self._loss_fn(rec, x)
            loss.backward()
            self._opt.step()
            return float(loss.item())
        else:
            import numpy as np

            v = np.array(vector, dtype=float)
            self._n_seen += 1
            self._centroid += (v - self._centroid) / self._n_seen
            return float(np.mean((v - self._centroid) ** 2))

    def check_and_alert(self, vector: list) -> dict:
        score = self.evaluate_novelty(vector)
        is_anomaly = score > self._threshold
        return {
            "alert": is_anomaly,
            "score": round(score, 6),
            "threshold": self._threshold,
            "status": "ANOMALY_DETECTED" if is_anomaly else "NOISE_FILTERED",
        }


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        print("Usage:")
        print("  forge_novelty_search.py --stats")
        print("  forge_novelty_search.py --observe METHOD '<json_params>' SUCCESS ELEGANCE")
        print("  forge_novelty_search.py --alternatives METHOD")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "--stats":
        print(json.dumps(archive_stats(), indent=2))
    elif cmd == "--observe" and len(sys.argv) >= 6:
        m = sys.argv[2]
        p = json.loads(sys.argv[3])
        s = sys.argv[4] in ("1", "true")
        e = float(sys.argv[5])
        print(json.dumps(observe_intent(m, p, s, e), indent=2))
    elif cmd == "--alternatives" and len(sys.argv) >= 3:
        print(json.dumps(find_novel_alternatives(sys.argv[2]), indent=2))
    else:
        print("invalid args")
