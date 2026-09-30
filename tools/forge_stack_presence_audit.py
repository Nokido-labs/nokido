"""
tools/forge_stack_presence_audit.py — inventaire PRESENCE + VIVACITE des capacites
implementees (demande owner 2026-07-25 : « assure-toi que wasm ainsi que tout ce qui a
ete implemente est bien present : qdrant, wasmedge, fts, mcts, bm25 etc »).

Pourquoi un module de plus (justification anti-dup exigee) :
- `forge_health_diagnostic` repond « le corps va-t-il bien ? » (score, gaps, hormones,
  heartbeats) ; il ne dit pas, capacite par capacite, « celle-ci est-elle LA et VIVANTE ».
- Les sondes de ports sont DELEGUEES a `forge_health_diagnostic.audit_services_http`,
  pas reecrites. Ce module ajoute uniquement ce que personne ne couvre : collection
  Qdrant, endpoint wasmedge (IP WSL dynamique), integrite FTS5, marqueurs MCTS/BM25.

Trois verdicts DISTINCTS, jamais confondus (une sonde qui n'a pas pu regarder ne doit
jamais se lire comme un « absent ») :
  ABSENT   : le code n'est pas la.
  PRESENT  : le code est la, le service ne repond pas (froid / on-demand / arrete).
  VIVANT   : le code est la et le service repond.
  INCONNU  : on n'a pas pu regarder (accces refuse, dependance manquante) -> on le DIT.

Lecture seule : aucun service demarre, arrete ou modifie. Doit tourner en
trusted_script (le compte sandbox n'atteint pas le loopback, mesure connue).
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

QDRANT_COLLECTION = "nokido_sovereign_rag"
RAG_DB = ROOT / "RAG" / "embeddings.db"


def _http(url: str, timeout: float = 4.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return int(getattr(r, "status", 0) or 0), r.read(4000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {str(e)[:120]}"


def _spec(mod: str) -> bool:
    """Module importable SANS l'executer (un import reel de forge_rag_engine
    chargerait le dense = RAM ; on veut mesurer, pas peser)."""
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:  # noqa: BLE001
        return False


def _markers(rel: str, needles: tuple[str, ...]) -> dict:
    """Presence de marqueurs dans un source (capacite reellement codee, pas devinee)."""
    p = ROOT / rel
    if not p.is_file():
        return {"file": rel, "exists": False}
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"file": rel, "exists": True, "readable": False, "err": type(e).__name__}
    # Insensible a la casse : la 1re version cherchait « mcts » dans un fichier qui
    # ecrit « MCTSNode » et « uct » dans un fichier qui ecrit « ucb1 » -> tous les
    # marqueurs sortaient False sur une capacite POURTANT presente. Un capteur neuf
    # est suspect : ici c'est le capteur qui avait tort, pas le code audite.
    _low = txt.lower()
    return {"file": rel, "exists": True,
            "markers": {n: (n.lower() in _low) for n in needles},
            "loc": txt.count("\n") + 1}


def probe_qdrant() -> dict:
    out: dict = {"capability": "dense_search (Qdrant HNSW)"}
    code, body = _http("http://127.0.0.1:6333/collections")
    out["server_6333"] = "VIVANT" if code == 200 else "PRESENT/froid"
    out["server_detail"] = body[:200]
    if code == 200:
        c2, b2 = _http(f"http://127.0.0.1:6333/collections/{QDRANT_COLLECTION}")
        if c2 == 200:
            try:
                res = json.loads(b2).get("result", {})
                out["collection"] = QDRANT_COLLECTION
                out["points_count"] = res.get("points_count")
                out["vectors_count"] = res.get("vectors_count")
                out["status"] = res.get("status")
            except Exception:  # noqa: BLE001
                out["collection_detail"] = b2[:200]
        else:
            out["collection"] = f"introuvable ({b2[:120]})"
    c3, b3 = _http("http://127.0.0.1:8098/health")
    out["sidecar_8098"] = "VIVANT" if c3 == 200 else f"PRESENT/froid ({b3[:80]})"
    out["modules"] = {m: _spec(m) for m in
                      ("forge_qdrant_sidecar", "forge_qdrant_server", "forge_qdrant_sync_daemon")}
    return out


def probe_wasm() -> dict:
    """wasmedge + llama-api-server tournent dans WSL Debian ; l'IP WSL CHANGE a chaque
    boot, donc on tente le loopback puis on DEMANDE l'IP a WSL (jamais une IP en dur :
    un chemin/IP versionne en dur est un piege deja paye)."""
    out: dict = {"capability": "WASM cervelet (wasmedge + llama-api-server)"}
    tried: list = []
    for host in ("127.0.0.1", "localhost"):
        code, body = _http(f"http://{host}:55555/v1/models", timeout=3.0)
        tried.append({"host": host, "code": code, "detail": body[:120]})
        if code == 200:
            out["runtime"] = "VIVANT"
            out["endpoint"] = f"http://{host}:55555"
            out["models"] = body[:300]
            break
    else:
        wsl_ip = ""
        try:
            # BYTES, pas text=True : wsl.exe ecrit en UTF-16LE. Lu en mode texte, son
            # « Acces refuse » devenait « A\x00c\x00c\x00...\x00 » -> une URL invalide
            # et un verdict trompeur (mesure 2026-07-25 sur ce meme script).
            r = subprocess.run(["wsl", "-d", "Debian", "--", "hostname", "-I"],
                               capture_output=True, timeout=20)
            raw = (r.stdout or b"") + b" " + (r.stderr or b"")
            txt = ""
            for enc in ("utf-16-le", "utf-8", "cp1252"):
                try:
                    cand = raw.decode(enc).replace("\x00", "").strip()
                except Exception:  # noqa: BLE001
                    continue
                if cand:
                    txt = cand
                    break
            import re as _re

            m = _re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", txt)
            if m:
                wsl_ip = m.group(0)
                out["wsl_ip"] = wsl_ip
            else:
                # « pas pu voir » != « absent » : le compte de service n'a pas
                # forcement le droit de lancer wsl.exe (mesure : « Acces refuse »).
                out["wsl_ip"] = "INCONNU"
                out["wsl_detail"] = f"rc={r.returncode} sortie={txt[:140]!r}"
        except Exception as e:  # noqa: BLE001
            out["wsl_ip"] = "INCONNU"
            out["wsl_detail"] = f"{type(e).__name__}: {str(e)[:120]}"
        if wsl_ip:
            code, body = _http(f"http://{wsl_ip}:55555/v1/models", timeout=4.0)
            tried.append({"host": wsl_ip, "code": code, "detail": body[:120]})
            out["runtime"] = "VIVANT" if code == 200 else "PRESENT/froid"
            if code == 200:
                out["endpoint"] = f"http://{wsl_ip}:55555"
                out["models"] = body[:300]
        else:
            out["runtime"] = ("PRESENT/froid en loopback ; IP WSL INCONNUE depuis ce "
                              "compte -> verifier cote owner (wsl -d Debian -- hostname -I)")
    out["probes"] = tried
    out["modules"] = {m: _spec(m) for m in
                      ("forge_wasm_cervelet", "forge_wasm_bridge", "forge_wasm_sandbox",
                       "forge_wasm_selftest")}
    out["start_hint"] = "bash /mnt/c/tmp/wasm_start.sh (dans WSL Debian)"
    return out


def probe_fts() -> dict:
    out: dict = {"capability": "FTS5 / BM25 lexical (rag_fts)"}
    if not RAG_DB.is_file():
        out["verdict"] = "INCONNU"
        out["detail"] = f"base introuvable: {RAG_DB}"
        return out
    try:
        con = sqlite3.connect(f"file:{RAG_DB.as_posix()}?mode=ro", uri=True, timeout=20)
    except Exception as e:  # noqa: BLE001
        out["verdict"] = "INCONNU"
        out["detail"] = f"ouverture refusee: {type(e).__name__}: {str(e)[:120]}"
        return out
    try:
        cur = con.cursor()
        cur.execute("SELECT count(*) FROM rag_chunks")
        out["rag_chunks"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM rag_chunks WHERE embedding IS NOT NULL")
        out["embeddings_non_null"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM rag_fts")
        out["rag_fts_rows"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM rag_fts WHERE rag_fts MATCH 'qdrant OR wasmedge'")
        out["match_smoke"] = cur.fetchone()[0]
        out["verdict"] = "VIVANT"
    except Exception as e:  # noqa: BLE001
        out["verdict"] = "INCONNU"
        out["detail"] = f"{type(e).__name__}: {str(e)[:150]}"
    finally:
        con.close()
    return out


def probe_bm25() -> dict:
    out: dict = {"capability": "BM25 (rank_bm25 + fusion RRF)"}
    out["lib_rank_bm25"] = _spec("rank_bm25")
    out["engine"] = _markers("app/forge_rag_engine.py",
                             ("BM25Okapi", "LAFORGE_BM25_MAX_CHUNKS", "rrf", "rerank"))
    out["verdict"] = "PRESENT" if out["lib_rank_bm25"] else "ABSENT (lib manquante)"
    return out


def probe_mcts() -> dict:
    out: dict = {"capability": "MCTS / LATS (recherche arborescente)"}
    out["modules"] = {m: _spec(m) for m in
                      ("forge_lats", "forge_lats_general", "forge_swebench_lats_runner",
                       "forge_goap", "forge_spike_router")}
    # Marqueurs cales sur le vocabulaire REEL du module (verifie au squelette AST) :
    # classe MCTSNode, ucb1/best_child pour la selection, _llm_rollout pour
    # l'expansion, _reflect_and_backtrack pour la remontee, lats_solve en entree.
    out["lats_general"] = _markers("app/forge_lats_general.py",
                                   ("MCTSNode", "ucb1", "best_child", "_llm_rollout",
                                    "_llm_evaluate", "_reflect_and_backtrack", "lats_solve"))
    out["lats"] = _markers("app/forge_lats.py", ("mcts", "node", "value", "reflect", "budget"))
    _core = out["lats_general"].get("markers") or {}
    ok = any(out["modules"].values()) and sum(_core.values()) >= 4
    out["verdict"] = "PRESENT (MCTS/UCB1 prouve dans le source)" if ok else (
        "PRESENT (modules la) mais coeur MCTS NON confirme -- verifier a la main")
    return out


def probe_llm_serving() -> dict:
    """Embedder / reranker / coder : les piliers que l'eviction doit proteger."""
    out: dict = {"capability": "serving local (embed 8099, rerank 8100, coder 8091)"}
    for label, url in (("embed_8099", "http://127.0.0.1:8099/health"),
                       ("rerank_8100", "http://127.0.0.1:8100/health"),
                       ("coder_8091", "http://127.0.0.1:8091/health"),
                       ("ollama_11434", "http://127.0.0.1:11434/api/version"),
                       ("hub_8766", "http://127.0.0.1:8766/health"),
                       ("searxng_8080", "http://127.0.0.1:8080/")):
        code, body = _http(url, timeout=3.0)
        out[label] = "VIVANT" if code == 200 else f"froid ({body[:60]})"
    return out


def probe_delegated_services() -> dict:
    """DELEGUE a l'audit existant plutot que de re-sonder (anti-dup)."""
    try:
        from nokido_agent.app.forge_health_diagnostic import audit_services_http

        return {"source": "forge_health_diagnostic.audit_services_http", "result": audit_services_http()}
    except Exception as e:  # noqa: BLE001
        return {"source": "forge_health_diagnostic.audit_services_http",
                "verdict": "INCONNU", "detail": f"{type(e).__name__}: {str(e)[:150]}"}


def main() -> int:
    report = {
        "qdrant": probe_qdrant(),
        "wasm": probe_wasm(),
        "fts": probe_fts(),
        "bm25": probe_bm25(),
        "mcts": probe_mcts(),
        "serving": probe_llm_serving(),
        "services_delegated": probe_delegated_services(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
