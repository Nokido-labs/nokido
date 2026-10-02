"""forge_semantic_pressure.py — Pression sémantique autopoiétique.

Source veille 2026-05-29 : Autopoietic AI + Semantic Pressure Architecture
(papers veille recents) + Lenia artificial life + Royal Society 2024
"Origins of life: the possible and the actual" + Maturana/Varela autopoiese.

Concept : Nokido mesure tension entre :
- nouveaute ingestee (chunks recents avec embeddings divergents du cluster moyen)
- equilibre actuel RAG (homeostasie semantique)

Si pression > seuil pendant N cycles -> declenchement auto :
- refactor proposal (code change suggestion)
- nouvelle ingestion focusee (curiosity drive)
- consolidation memoire (compactage)

Pattern :
1. Compute embedding centroid par cluster (forge_rag_engine clusters)
2. Pour chaque nouveau chunk : distance vs centroid = "tension instantanee"
3. Moyenne mobile tension sur fenetre temporelle = pression sustained
4. Trigger action si pression > threshold (analogie pression osmotique cellule)

API :
- `compute_semantic_pressure(window_days=7)` : score actuel + historique
- `should_trigger_action(threshold=0.4)` : bool + suggested action
- `autopoiesis_cycle()` : 1 cycle complet scan -> mesure -> action conditionnelle
"""

from __future__ import annotations
import json, logging, math, sqlite3
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("semantic_pressure")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


def _decode_blob(blob: bytes) -> list[float] | None:
    # REGLE UNIQUE (2026-10-01) : delegue au decodeur du routeur, tolerant au JSON (~20 % des
    # vecteurs en base). Ce doublon depaquetait un blob JSON en floats absurdes.
    try:
        from nokido_agent.app.forge_embed_router import decode_blob

        return decode_blob(blob)
    except Exception:  # noqa: BLE001 - muet-ok : None = vecteur illisible, l'appelant l'ecarte
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na * nb else 0.0


def compute_cluster_centroids(domain_filter: str = None, max_chunks: int = 2000) -> dict:
    """Compute embedding centroid par domain (cluster simple).

    Returns: {domain: centroid_vector}
    """
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    where = f"AND domain='{domain_filter}'" if domain_filter else ""
    rows = cur.execute(
        f"""
    SELECT domain, embedding FROM rag_chunks
    WHERE embedding IS NOT NULL {where}
    ORDER BY RANDOM() LIMIT ?
    """,
        (max_chunks,),
    ).fetchall()
    con.close()

    sums = defaultdict(lambda: None)
    counts = defaultdict(int)
    for dom, blob in rows:
        vec = _decode_blob(blob)
        if not vec or not dom:
            continue
        if sums[dom] is None:
            sums[dom] = list(vec)
        else:
            sums[dom] = [a + b for a, b in zip(sums[dom], vec)]
        counts[dom] += 1

    centroids = {}
    for dom, s in sums.items():
        n = counts[dom]
        if n > 0 and s:
            centroid = [x / n for x in s]
            # L2-normalize
            norm = math.sqrt(sum(x * x for x in centroid))
            if norm:
                centroid = [x / norm for x in centroid]
            centroids[dom] = centroid
    return centroids


def compute_semantic_pressure(window_days: int = 7, max_recent: int = 200) -> dict:
    """Compute semantic pressure sur fenetre recent.

    Pression = 1 - mean(cosine_sim(new_chunk_emb, domain_centroid))
    Si chunks recents tres divergents du centroid (cosine bas) = pression haute.

    Returns:
        {pressure_global, pressure_by_domain, n_recent_chunks, window_days}
    """
    centroids = compute_cluster_centroids(max_chunks=3000)
    if not centroids:
        return {"skip": "no centroids"}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    rows = cur.execute(
        """
    SELECT domain, embedding FROM rag_chunks
    WHERE embedding IS NOT NULL AND ingested_at >= ?
    ORDER BY ingested_at DESC LIMIT ?
    """,
        (cutoff, max_recent),
    ).fetchall()
    con.close()

    if not rows:
        return {"skip": "no recent chunks", "window_days": window_days}

    by_dom_tensions = defaultdict(list)
    global_tensions = []

    for dom, blob in rows:
        vec = _decode_blob(blob)
        if not vec or not dom or dom not in centroids:
            continue
        sim = _cosine(vec, centroids[dom])
        tension = 1.0 - sim  # divergence vs centroid
        by_dom_tensions[dom].append(tension)
        global_tensions.append(tension)

    pressure_by_domain = {d: round(sum(ts) / len(ts), 4) if ts else 0.0 for d, ts in by_dom_tensions.items()}
    pressure_global = round(sum(global_tensions) / len(global_tensions), 4) if global_tensions else 0.0

    return {
        "pressure_global": pressure_global,
        "pressure_by_domain": pressure_by_domain,
        "n_recent_chunks": len(global_tensions),
        "window_days": window_days,
        "centroids_count": len(centroids),
    }


def should_trigger_action(pressure_result: dict, threshold: float = 0.4) -> dict:
    """Determine si pression haute suggere action autopoietique.

    Actions possibles :
    - high_pressure : nouveaute ecrasante -> consolidate (compact RAG)
    - low_pressure  : redondance -> trigger curiosity (new themes)
    - balanced      : etat stable, rien a faire
    """
    p = pressure_result.get("pressure_global", 0.0)
    if p > threshold + 0.2:
        return {
            "action": "consolidate",
            "rationale": f"pression {p:.2f} > {threshold + 0.2:.2f} : trop nouveaute, consolidate via compaction",
            "trigger": True,
            "pressure": p,
        }
    elif p > threshold:
        return {
            "action": "monitor",
            "rationale": f"pression {p:.2f} elevee mais sous critique, monitor",
            "trigger": False,
            "pressure": p,
        }
    elif p < threshold - 0.2:
        return {
            "action": "curiosity_drive",
            "rationale": f"pression {p:.2f} faible : redondance, trigger curiosity_driver",
            "trigger": True,
            "pressure": p,
        }
    return {
        "action": "stable",
        "rationale": f"pression {p:.2f} equilibree",
        "trigger": False,
        "pressure": p,
    }


def autopoiesis_cycle(window_days: int = 7, dry_run: bool = True) -> dict:
    """1 cycle autopoiese : mesure pression + decide action + log.

    Si dry_run=False ET trigger=True, execute action :
    - consolidate : call forge_auto_compact si dispo
    - curiosity_drive : call forge_curiosity_driver.curiosity_cycle
    """
    pressure = compute_semantic_pressure(window_days=window_days)
    if "skip" in pressure:
        return {"status": "skipped", "reason": pressure["skip"]}

    decision = should_trigger_action(pressure)

    result = {
        "pressure": pressure,
        "decision": decision,
        "dry_run": dry_run,
        "executed": None,
    }

    if not dry_run and decision["trigger"]:
        try:
            if decision["action"] == "curiosity_drive":
                import sys

                sys.path.insert(0, str(ROOT))
                from nokido_agent.app.forge_curiosity_driver import curiosity_cycle

                cc_result = curiosity_cycle(dry_run=False, n_themes=3)
                result["executed"] = {"curiosity_cycle": cc_result.get("n_pushed", 0)}
            elif decision["action"] == "consolidate":
                # Trigger forge_auto_compact si module dispo
                try:
                    import subprocess

                    subprocess.run(
                        ["python", str(ROOT / "tools" / "forge_auto_compact.py")],
                        timeout=300,
                    )
                    result["executed"] = {"consolidate": "triggered"}
                except Exception as e:
                    result["executed"] = {"consolidate": f"fail: {e}"}
        except Exception as e:
            result["executed"] = {"error": str(e)}

    return result


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=7)
    ap.add_argument("--execute", action="store_true", help="Execute action si trigger (default dry-run)")
    args = ap.parse_args()
    result = autopoiesis_cycle(window_days=args.window, dry_run=not args.execute)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
