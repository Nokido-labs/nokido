"""forge_hebbian_linker.py — Plasticité Hebbian sur `biblio_link`.

Pattern neuro-inspiré (cf. mapping bio↔code) :
- Hebbian rule : "fire together, wire together"
- Quand 2 entries sont co-activées (même conversation, même topic, même session),
  on renforce le lien biblio_link entre elles.
- Decay : les liens jamais réactivés voient leur poids décroitre lentement.

Sources de co-activation détectées :
1. **Topic co-occurrence** : 2 entries qui partagent ≥2 topics dans biblio_topics
2. **Idea co-occurrence** : 2 entries avec le même triggered_by_idea_id
3. **Search results** : 2 entries qui apparaissent dans les top-5 d'un même search
   (parsing search_results_json)
4. **Session burst** : 2 entries reviewed/promoted dans une fenêtre <1h

Stockage :
- INSERT OR REPLACE biblio_link(src_id, dst_id, kind='hebbian', weight=...)
- weight ∈ [0, 1] = fraction normalisée des activations
- decay : weight *= 0.95 chaque cycle si pas réactivé

Output :
- sandbox/hebbian_state.json (last_run, stats par kind)
- anchor RAG si nouveau cluster détecté

Usage :
    LAFORGE_PYTHON app/forge_hebbian_linker.py --once [--decay-rate 0.95]
    LAFORGE_PYTHON app/forge_hebbian_linker.py --daemon
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
# ORDRE (2026-09-24, mesure) : ce bloc etait place APRES l'import qu'il devait
# rendre possible -- NokidoHebbian mourait en ModuleNotFoundError a chaque demarrage.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Le pouls passe par l'organe du battement, JAMAIS par une implementation locale :
# recensement du 2026-07-28, 39 modules avaient reimplemente ce geste.
from nokido_agent.app.forge_heartbeat import Cadence  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SANDBOX = ROOT / "sandbox"
STATE_FILE = SANDBOX / "hebbian_state.json"

DEFAULT_INTERVAL_S = int(os.environ.get("LAFORGE_HEBBIAN_INTERVAL_S", "21600"))  # 6h

DEFAULT_DECAY = float(os.environ.get("LAFORGE_HEBBIAN_DECAY", "0.95"))
MIN_SHARED_TOPICS = 2
MAX_PAIRS_PER_KIND = 200  # cap pour éviter quadratic explosion


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=15)
    c.execute("PRAGMA journal_mode=WAL")
    return c


# ============================================================================
# CO-ACTIVATIONS
# ============================================================================


def coactivation_topics(conn) -> dict[tuple[str, str], int]:
    """Compte le nombre de topics partagés entre paires d'entries.
    Retourne {(src_id, dst_id): n_shared_topics} pour n >= MIN_SHARED_TOPICS.
    """
    rows = conn.execute("SELECT entry_id, topic FROM biblio_topics WHERE entry_id IS NOT NULL").fetchall()
    by_topic: dict[str, list[str]] = defaultdict(list)
    for entry_id, topic in rows:
        by_topic[topic].append(entry_id)

    counter: dict[tuple[str, str], int] = defaultdict(int)
    for topic, entries in by_topic.items():
        if len(entries) < 2:
            continue
        for a, b in combinations(sorted(set(entries)), 2):
            counter[(a, b)] += 1

    return {pair: n for pair, n in counter.items() if n >= MIN_SHARED_TOPICS}


def coactivation_ideas(conn) -> dict[tuple[str, str], int]:
    """Entries partageant le même triggered_by_idea_id."""
    rows = conn.execute(
        "SELECT id, triggered_by_idea_id FROM biblio_raw "
        "WHERE triggered_by_idea_id IS NOT NULL AND status != 'rejected'"
    ).fetchall()
    by_idea: dict[str, list[str]] = defaultdict(list)
    for entry_id, idea in rows:
        by_idea[idea].append(entry_id)

    counter: dict[tuple[str, str], int] = defaultdict(int)
    for idea, entries in by_idea.items():
        if len(entries) < 2:
            continue
        for a, b in combinations(sorted(set(entries)), 2):
            counter[(a, b)] += 1
    return counter


def coactivation_search_results(conn) -> dict[tuple[str, str], int]:
    """Entries dont les search_results se réfèrent aux mêmes URLs (proxy de
    similarité de query SearXNG).

    Heuristique : 2 entries qui ont des urls communes dans leur search_results_json
    sont co-pertinentes pour le même contexte.
    """
    rows = conn.execute(
        "SELECT id, search_results_json FROM biblio_raw WHERE search_results_json IS NOT NULL AND status='reviewed'"
    ).fetchall()
    by_url: dict[str, list[str]] = defaultdict(list)
    for entry_id, srj in rows:
        try:
            results = json.loads(srj or "[]")
        except Exception:
            continue
        for r in (results or [])[:5]:  # top-5 only
            url = r.get("url")
            if url:
                by_url[url].append(entry_id)

    counter: dict[tuple[str, str], int] = defaultdict(int)
    for url, entries in by_url.items():
        if len(entries) < 2:
            continue
        for a, b in combinations(sorted(set(entries)), 2):
            counter[(a, b)] += 1
    return counter


# ============================================================================
# HEBBIAN UPDATE
# ============================================================================


def reinforce_links(conn, coactivations: dict[tuple[str, str], int], kind: str, weight_max: float) -> dict:
    """Pour chaque pair co-activée, INSERT OR REPLACE dans biblio_link
    avec poids = min(1.0, count / weight_max).
    """
    if not coactivations:
        return {"created_or_updated": 0}
    # Top N par count pour éviter l'explosion
    top = sorted(coactivations.items(), key=lambda x: -x[1])[:MAX_PAIRS_PER_KIND]

    n = 0
    for (a, b), count in top:
        weight = min(1.0, count / max(weight_max, 1.0))
        try:
            # INSERT OR REPLACE — si la pair existe avec un autre kind, kind='hebbian' override
            conn.execute(
                "INSERT OR REPLACE INTO biblio_link(src_id, dst_id, kind, weight, source) VALUES (?, ?, ?, ?, ?)",
                (a, b, kind, weight, "hebbian_auto"),
            )
            n += 1
        except sqlite3.IntegrityError:
            # FK violation : a ou b n'existe plus dans biblio_raw
            continue
    conn.commit()
    return {"created_or_updated": n, "kind": kind}


def decay_unused_links(conn, decay_rate: float, since_ts: float) -> int:
    """Décay les biblio_link non touchés depuis last_run (heuristique : tous
    les liens hebbian_auto pas dans le batch courant). Pour rester simple,
    on multiplie tous les liens hebbian par decay_rate (déjà run ⇒ INSERT OR
    REPLACE remet à jour avec le nouveau weight, donc seuls les "non
    rappelés" reçoivent le decay du tour précédent puis sont écrasés).
    """
    cur = conn.execute(
        "UPDATE biblio_link SET weight = weight * ? WHERE source = 'hebbian_auto' AND weight > 0.05", (decay_rate,)
    )
    n = cur.rowcount
    # Purge faibles (< 0.05) — synapse "morte"
    conn.execute("DELETE FROM biblio_link WHERE source='hebbian_auto' AND weight < 0.05")
    conn.commit()
    return n


# ============================================================================
# CYCLE
# ============================================================================


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"last_run_ts": 0, "cycles": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_run_ts": 0, "cycles": 0}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def run_cycle(decay_rate: float = DEFAULT_DECAY) -> dict:
    state = _load_state()
    conn = _conn()
    t0 = time.time()

    # 1. Decay préalable (synapses non rappelées s'affaiblissent)
    decayed = decay_unused_links(conn, decay_rate, state.get("last_run_ts", 0))

    # 2. Compute coactivations
    topics_co = coactivation_topics(conn)
    ideas_co = coactivation_ideas(conn)
    search_co = coactivation_search_results(conn)

    # 3. Reinforcement par kind
    stats_topics = reinforce_links(conn, topics_co, "hebbian_topic", weight_max=5.0)
    stats_ideas = reinforce_links(conn, ideas_co, "hebbian_idea", weight_max=10.0)
    stats_search = reinforce_links(conn, search_co, "hebbian_search", weight_max=3.0)

    # 4. Stats finales
    n_links = conn.execute("SELECT COUNT(*) FROM biblio_link WHERE source='hebbian_auto'").fetchone()[0]
    avg_w = conn.execute("SELECT AVG(weight) FROM biblio_link WHERE source='hebbian_auto'").fetchone()[0] or 0.0
    conn.close()

    out = {
        "ts": datetime.now().isoformat(),
        "duration_s": round(time.time() - t0, 2),
        "decayed": decayed,
        "topics_pairs": len(topics_co),
        "ideas_pairs": len(ideas_co),
        "search_pairs": len(search_co),
        "reinforced": {
            "topic": stats_topics["created_or_updated"],
            "idea": stats_ideas["created_or_updated"],
            "search": stats_search["created_or_updated"],
        },
        "total_hebbian_links": n_links,
        "avg_weight": round(avg_w, 3),
    }

    state["last_run_ts"] = time.time()
    state["cycles"] = state.get("cycles", 0) + 1
    state.setdefault("history", []).append(
        {k: out[k] for k in ("ts", "topics_pairs", "ideas_pairs", "search_pairs", "total_hebbian_links")}
    )
    state["history"] = state["history"][-30:]  # last 30 cycles
    _save_state(state)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Nokido Hebbian linker (plasticité biblio_link)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument(
        "--decay-rate",
        type=float,
        default=DEFAULT_DECAY,
        help=f"décay des liens non rappelés (default {DEFAULT_DECAY})",
    )
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    args = ap.parse_args()

    if not args.once and not args.daemon:
        ap.error("--once ou --daemon requis")

    if args.daemon:
        try:
            (SANDBOX / "hebbian_linker.pid").write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

    # Le TICK est le metabolisme : il porte le pouls a chaque tour. La plasticite
    # hebbienne reste une fonction LENTE declenchee tous les N ticks -- 6 h est un
    # rythme de MAINTENANCE, pas un rythme cardiaque (arbitrage owner 2026-09-03,
    # apres 765 relances mesurees au journal du superviseur).
    cad = Cadence("hebbian_linker", cycle_s=args.interval)
    while True:
        if cad.tour():
            out = run_cycle(decay_rate=args.decay_rate)
            print(
                f"[hebbian] cycle done in {out['duration_s']}s : "
                f"topics={out['topics_pairs']} ideas={out['ideas_pairs']} "
                f"search={out['search_pairs']} | reinforced "
                f"{out['reinforced']} | total_links={out['total_hebbian_links']} "
                f"avg_w={out['avg_weight']} | decayed={out['decayed']}",
                flush=True,
            )
            cad.cycle_termine(ok=True, liens=out["total_hebbian_links"],
                              duree_s=out["duration_s"])
        if args.once:
            return 0
        cad.dormir()


if __name__ == "__main__":
    sys.exit(main())
