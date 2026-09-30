# -*- coding: utf-8 -*-
"""Nokido Bibliography Worker — Sprint alpha etape alpha3
poll biblio_raw status=queued -> SearXNG -> update
"""

from __future__ import annotations
import argparse, json, logging, os, sys, time, sqlite3
import urllib.error, urllib.request
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.Biblio.Worker")

DEFAULT_DB_PATH = os.environ.get(
    "LAFORGE_DB_PATH", str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
)
SEARXNG_URL = os.environ.get("LAFORGE_SEARXNG_URL", "http://localhost:8080")
POLL_INTERVAL = int(os.environ.get("LAFORGE_BIBLIO_POLL", "30"))
BATCH_SIZE = int(os.environ.get("LAFORGE_BIBLIO_BATCH", "5"))
SEARXNG_TIMEOUT = int(os.environ.get("LAFORGE_SEARXNG_TIMEOUT", "15"))
MAX_RESULTS = int(os.environ.get("LAFORGE_BIBLIO_MAX_RESULTS", "10"))


def _searxng_search(query: str) -> list[dict]:
    """Appelle SearXNG JSON API, avec fallback académique direct si SearXNG est éteint."""
    from urllib.parse import urlencode

    try:
        params = urlencode({"q": query, "format": "json", "categories": "general", "language": "en"})
        req = urllib.request.Request(f"{SEARXNG_URL}/search?{params}", headers={"User-Agent": "NokidoBiblioWorker/1.0"})
        with urllib.request.urlopen(req, timeout=SEARXNG_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:500],
                "score": r.get("score", 0.0),
            }
            for r in data.get("results", [])[:MAX_RESULTS]
        ]
    except (urllib.error.URLError, OSError) as exc:
        logger.info(f"SearXNG inaccessible ({exc}), bascule sur la recherche académique directe...")
        try:
            # Assurer le chemin d'import correct pour app
            import sys
            app_path = str(Path(__file__).resolve().parent)
            if app_path not in sys.path:
                sys.path.insert(0, app_path)
            from nokido_agent.app.forge_watch_agent import _academic_search
            
            results = _academic_search(query)
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", "")[:500],
                    "score": 1.0,
                }
                for r in results[:MAX_RESULTS]
            ]
        except Exception as fallback_exc:
            logger.error(f"Fallback recherche académique KO: {fallback_exc}")
            raise exc


def _poll_batch(conn: sqlite3.Connection) -> list[dict]:
    """Recupere entries status=queued (WAL)."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id,type,title,authors,year,doi,url FROM biblio_raw "
        # Fix workflow 2026-06-25 : la veille (forge_biblio_core) insere 'unverified',
        # pas 'queued' -> le worker ne voyait jamais ces entrees (583 stranded depuis 05-28).
        # On draine les DEUX vocab pour reparer la boucle autonome.
        "WHERE status IN ('queued','unverified') ORDER BY created_at ASC LIMIT ?",
        (BATCH_SIZE,),
    ).fetchall()
    return [dict(r) for r in rows]


def _mark(conn, entry_id, status, results_json=None, reason=None):
    """UPDATE atomique biblio_raw — WAL safe."""
    conn.execute(
        "UPDATE biblio_raw SET status=?,"
        " search_results_json=COALESCE(?,search_results_json),"
        " rejection_reason=COALESCE(?,rejection_reason),"
        " updated_at=datetime('now') WHERE id=?",
        (status, results_json, reason, entry_id),
    )
    conn.commit()


def _is_product_doc(entry: dict) -> bool:
    """Détecte si l'entrée est une documentation produit/outil (ex: HuggingFace, LeRobot, GitHub)
    plutôt qu'un concept fondamental ou un papier scientifique."""
    title = (entry.get("title") or "").lower()
    url = (entry.get("url") or "").lower()
    
    # Mots-clés caractéristiques des docs produits, tutoriels, repositories
    product_keywords = {
        "huggingface.co", "github.com", "lerobot", "documentation", "install", 
        "installation", "quickstart", "tutorial", "dataset", "how-to", "api reference", 
        "cli reference", "readme", "model hub", "hf-mirror", "pip install"
    }
    
    for kw in product_keywords:
        if kw in title or kw in url:
            return True
    return False


def process_entry(conn: sqlite3.Connection, entry: dict) -> str:
    """Traite 1 entry queued → searched → reviewed|retry.
    Retourne : 'reviewed' | 'retry' | 'error'"""
    from nokido_agent.app.forge_biblio_refine import refine_query  # lazy import

    try:
        query = refine_query(entry)
    except Exception as exc:
        logger.warning(f"refine_query KO id={entry['id']}: {exc}")
        query = (entry.get("title") or "")[:80]

    _mark(conn, entry["id"], "searching")
    print(f"[BIBLIO_WORKER] searching id={entry['id']} q={query!r}", flush=True)

    try:
        results = _searxng_search(query)
        status = "cold_rag" if _is_product_doc(entry) else "reviewed"
        _mark(conn, entry["id"], status, results_json=json.dumps(results, ensure_ascii=False))
        print(f"[BIBLIO_WORKER] {status} id={entry['id']} n_results={len(results)}", flush=True)
        # Hook topics-extractor (opt-out via LAFORGE_BIBLIO_AUTO_TOPICS=0)
        if TOPIC_ENABLE:
            try:
                topics = _extract_topics(entry, results)
                if topics:
                    _persist_topics(conn, entry["id"], topics)
                    print(f"[BIBLIO_WORKER] topics id={entry['id']} {[t[0] for t in topics]}", flush=True)
            except Exception as exc:
                logger.warning(f"topic hook KO id={entry['id']}: {exc}")
        return status
    except (urllib.error.URLError, OSError) as exc:
        reason = f"searxng_err:{type(exc).__name__}:{str(exc)[:120]}"
        _mark(conn, entry["id"], "queued", reason=reason)
        logger.warning(f"SearXNG KO id={entry['id']}: {exc}")
        print(f"[BIBLIO_WORKER] retry id={entry['id']}", flush=True)
        return "retry"
    except Exception as exc:
        logger.error(f"process_entry inattendu id={entry['id']}: {exc}", exc_info=True)
        _mark(conn, entry["id"], "queued", reason=f"unexpected:{str(exc)[:120]}")
        return "error"


SANDBOX = Path(__file__).resolve().parent.parent / "sandbox"
HEARTBEAT = SANDBOX / "biblio_worker.heartbeat"
PIDFILE = SANDBOX / "biblio_worker.pid"

# Topic extractor (Ollama → llama.cpp si UP)
TOPIC_MODEL = os.environ.get("LAFORGE_TOPIC_MODEL", "laforge-qwen:latest")
TOPIC_HOST = os.environ.get("LAFORGE_TOPIC_HOST", "http://127.0.0.1:11434")
TOPIC_K = int(os.environ.get("LAFORGE_TOPIC_K", "5"))
TOPIC_ENABLE = os.environ.get("LAFORGE_BIBLIO_AUTO_TOPICS", "1") != "0"


def _extract_topics(entry: dict, search_results: list[dict]) -> list[tuple[str, float]]:
    """Mini-LLM local — extrait k topics depuis title+description+top snippets.

    Renvoie [(topic_normalisé, weight), ...] ou [] si extraction échoue.
    """
    title = (entry.get("title") or "")[:120]
    desc = (entry.get("description") or "")[:300]
    snips = "\n".join(
        f"- {(r.get('title', '') + ' — ' + r.get('content', ''))[:200]}" for r in (search_results or [])[:3]
    )
    prompt = (
        f"You extract bibliography topics. Reply ONLY with JSON of the form "
        f'{{"topics":[{{"name":"...","weight":0.0-1.0}}]}}. '
        f"Pick {TOPIC_K} concise English topics (1-3 words, lowercase, kebab-case ok).\n\n"
        f"TITLE: {title}\nDESCRIPTION: {desc}\nSNIPPETS:\n{snips}"
    )
    body = json.dumps(
        {
            "model": TOPIC_MODEL,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 256},
        }
    ).encode()
    req = urllib.request.Request(f"{TOPIC_HOST}/api/generate", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        raw = data.get("response", "").strip()
        parsed = json.loads(raw)
    except Exception as exc:
        logger.warning(f"topic extract KO id={entry.get('id')}: {type(exc).__name__}:{exc}")
        return []
    out = []
    # GARDE EXTRACTIVE (2026-07-22) : un topic dont AUCUN mot significatif
    # n'apparait dans le texte source est une hallucination du mini-modele.
    # Mesure sur la carte thematique : 'canari' etiquete 'canadian army'/'bible'
    # (44 entrees polluees), doc LeRobot etiquetee 'cybersecurity'. Contrainte
    # extractive deterministe : au moins un token (>=3 chars) present dans
    # title+desc+snippets, sinon rejet — pas besoin d'un modele plus gros.
    import unicodedata
    def _norm(s: str) -> str:
        s_norm = unicodedata.normalize("NFD", s)
        return "".join(c for c in s_norm if unicodedata.category(c) != "Mn").lower()

    title = (entry.get("title") or "")[:120]
    desc = (entry.get("description") or "")[:300]
    hay_norm = _norm(f"{title} {desc}")

    for t in parsed.get("topics", []):
        name = (t.get("name") or "").strip()
        name_lower = name.lower()
        if not name or len(name) > 60:
            continue
        toks = [w for w in _norm(name).replace("-", " ").split() if len(w) >= 3]
        if toks and not any(w in hay_norm for w in toks):
            logger.info(f"topic halluciné rejeté: {name!r} (absent du texte source: title+description)")
            print(f"[BIBLIO_WORKER] topic_rejected={name!r} reason='absent_from_title_description'", flush=True)
            continue
        weight = float(t.get("weight", 1.0))
        weight = max(0.0, min(1.0, weight))
        out.append((name_lower, weight))
    return out[:TOPIC_K]


def _persist_topics(conn: sqlite3.Connection, entry_id: str, topics: list[tuple[str, float]]) -> int:
    """INSERT OR REPLACE biblio_topics. Renvoie le nombre de rows affectees."""
    if not topics:
        return 0
    n = 0
    for topic, weight in topics:
        conn.execute(
            "INSERT OR REPLACE INTO biblio_topics(entry_id, topic, weight, source) VALUES (?, ?, ?, 'auto_qwen')",
            (entry_id, topic, weight),
        )
        n += 1
    conn.commit()
    return n


def _write_heartbeat(stats: dict, interval: int) -> None:
    """Persiste l'état du worker pour le launcher (sandbox/biblio_worker.heartbeat)."""
    try:
        SANDBOX.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(
            json.dumps(
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "pid": os.getpid(),
                    "interval_s": interval,
                    "searxng_url": SEARXNG_URL,
                    "last_cycle_stats": stats,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # Un POULS non ecrit ne rend pas le service muet : il le rend MORT aux yeux
        # du superviseur et de l'anatomie, qui lisent le fichier et pas le process.
        # C'est le motif « presence != vitalite » : ici l'inverse, un organe vivant
        # declare absent.
        _lg.getLogger(__name__).error(
            "[biblio] heartbeat NON ecrit (%s: %s) | consequence: ce worker sera lu "
            "comme MORT par le superviseur alors qu'il tourne",
            type(e).__name__, str(e)[:100])


def run_loop(db_path: str, once: bool = False, interval: int = POLL_INTERVAL) -> None:
    """Boucle principale du worker."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    print(
        f"[BIBLIO_WORKER] start db={db_path} searxng={SEARXNG_URL} interval={interval}s batch={BATCH_SIZE}", flush=True
    )
    if not once:
        try:
            SANDBOX.mkdir(parents=True, exist_ok=True)
            PIDFILE.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass
    _write_heartbeat({}, interval)
    while True:
        # Adapter l intervalle au mood système (fatigue → relâcher, stress → ralentir)
        try:
            from nokido_agent.app.forge_system_mood import get_mood as _get_mood

            _mood = _get_mood()
            if _mood.is_stressed():
                _eff_interval = interval * 2  # organisme stressé → moins agressif
            elif _mood.is_idle():
                _eff_interval = max(10, interval // 2)  # idle → accélérer
            else:
                _eff_interval = interval
        except Exception:
            _eff_interval = interval
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            batch = _poll_batch(conn)
            if batch:
                print(f"[BIBLIO_WORKER] poll: {len(batch)} queued", flush=True)
                stats = {"reviewed": 0, "retry": 0, "error": 0}
                for entry in batch:
                    r = process_entry(conn, entry)
                    stats[r] = stats.get(r, 0) + 1
                print(f"[BIBLIO_WORKER] cycle done {stats}", flush=True)
            else:
                logger.debug("poll: 0 queued — idle")
        except Exception as exc:
            logger.error(f"run_loop exception: {exc}", exc_info=True)
        finally:
            conn.close()
        _write_heartbeat(locals().get("stats", {}), _eff_interval)
        if once:
            print("[BIBLIO_WORKER] --once: exit", flush=True)
            break
        time.sleep(_eff_interval)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    ap = argparse.ArgumentParser(description="Nokido Biblio Worker alpha3")
    ap.add_argument("--once", action="store_true", help="1 cycle puis exit")
    ap.add_argument("--interval", type=int, default=POLL_INTERVAL)
    ap.add_argument("--db", default=DEFAULT_DB_PATH)
    args = ap.parse_args()
    run_loop(db_path=args.db, once=args.once, interval=args.interval)


if __name__ == "__main__":
    main()


def process_one_entry(conn: sqlite3.Connection, entry: dict) -> dict:
    """
    Alias public exposé pour handle_biblio action=search.
    Traite 1 entry, retourne dict {ok, status, n_results}.
    """
    result = process_entry(conn, entry)
    n = 0
    if result == "reviewed":
        import json as _j

        row = conn.execute("SELECT search_results_json FROM biblio_raw WHERE id=?", (entry["id"],)).fetchone()
        if row and row[0]:
            try:
                n = len(_j.loads(row[0]))
            except:
                pass
    return {"ok": result == "reviewed", "status": result, "entry_id": entry["id"], "n_results": n}
