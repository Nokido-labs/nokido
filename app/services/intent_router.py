"""
forge_intent_router.py - Nokido v18.5 Intent-Based Routing
Circuit-court semantique : intention connue + approuvee -> bypass LLM.
SEUILS: bypass>=0.95 ET marge>=0.02 ET plan lisible | suggest>=0.85 | enrich>=0.70 | fallback<0.70
"""

from __future__ import annotations
import asyncio, hashlib, json, logging, sqlite3, time
from collections import OrderedDict
from pathlib import Path
from typing import Optional
import numpy as np

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger(__name__)

THRESHOLD_BYPASS = 0.95
THRESHOLD_SUGGEST = 0.85
THRESHOLD_ENRICH = 0.70
# Marge top1-top2 minimale pour BYPASSER. Un score eleve dont le second est a
# egalite designe une FAMILLE de plans, pas un plan : en rejouer un a l'aveugle
# est un tirage au sort. Sous cette marge -> degradation explicite en suggest.
THRESHOLD_MARGIN = 0.02


def _get_db_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "RAG" / "embeddings.db"


def _load_env_val(key: str, default: str) -> str:
    env_path = Path(__file__).resolve().parent.parent.parent / "Nokido.env"
    if env_path.exists():
        for line in env_path.read_text(errors="replace").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return default


class IntentRouter:
    """Routeur semantique Nokido. Bypass LLM si intention connue+approuvee."""

    def __init__(self, db_path=None, model=None, ollama_url=None, dim=1024):
        self._db = Path(db_path) if db_path else _get_db_path()
        self._model = model or _load_env_val("OLLAMA_EMBEDDINGS_MODEL", "bge-m3")
        self._ollama_url = ollama_url or _load_env_val("OLLAMA_EMBEDDINGS_URL", "http://127.0.0.1:11434/api/embeddings")
        self._dim = dim
        self._embed_cache: OrderedDict = OrderedDict()
        self._cache_max = 500
        self._faiss_index = None
        self._faiss_ids: list = []
        self._faiss_plans: list = []
        self._loaded = False
        self._session = None
        self._session_loop = None
        self._dim_skipped = 0
        logger.info(f"IntentRouter: db={self._db} model={self._model}")

    async def _get_session(self):
        """Session aiohttp partagee : evite une connexion TCP par embedding."""
        import aiohttp

        loop = asyncio.get_running_loop()
        sess = self._session
        if sess is not None and not sess.closed and self._session_loop is loop:
            return sess
        if sess is not None and not sess.closed:
            try:
                await sess.close()
            except Exception:  # muet-ok : la session est remplacee juste apres
                pass
        self._session = aiohttp.ClientSession()
        self._session_loop = loop
        return self._session

    async def aclose(self) -> None:
        """Ferme la session partagee (shutdown)."""
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception:  # muet-ok : on abandonne la session dans tous les cas
                pass
        self._session = None
        self._session_loop = None

    async def _embed(self, text: str) -> Optional[np.ndarray]:
        """Vectorise via bge-m3. Cache LRU 500 entrees."""
        key = hashlib.md5(text.encode()).hexdigest()
        if key in self._embed_cache:
            self._embed_cache.move_to_end(key)
            return self._embed_cache[key]
        # NPU local prioritaire
        try:
            from nokido_agent.app.forge_npu_embedder import get_npu_embedder

            npu = get_npu_embedder()
            if npu and npu.available:
                vecs = npu.embed_batch([text])
                if vecs:
                    v = np.array(vecs[0], dtype=np.float32)
                    self._embed_cache[key] = v
                    if len(self._embed_cache) > self._cache_max:
                        self._embed_cache.popitem(last=False)
                    return v
        except Exception as e:
            # Bascule silencieuse = tout le trafic part sur un AUTRE modele,
            # donc un autre espace vectoriel, sans que rien ne le signale.
            logger.debug(f"IntentRouter: NPU indisponible -> Ollama ({e})")
        # Ollama HTTP — self._ollama_url, PAS une URL codee en dur (l'argument
        # du constructeur etait stocke puis jete).
        try:
            import aiohttp

            session = await self._get_session()
            async with session.post(
                self._ollama_url,
                json={"model": self._model, "prompt": text[:1200]},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    vec = data.get("embedding") or (data.get("embeddings") or [[]])[0]
                    if vec:
                        v = np.array(vec, dtype=np.float32)
                        self._embed_cache[key] = v
                        if len(self._embed_cache) > self._cache_max:
                            self._embed_cache.popitem(last=False)
                        return v
        except Exception as e:
            logger.warning(f"IntentRouter embed err: {e}")
        return None

    def _load_index(self, force=False) -> bool:
        # Sans cette garde, route() reconstruisait le SELECT + l'index HNSW a
        # CHAQUE requete : `force` etait un parametre mort.
        if self._loaded and not force:
            return bool(self._faiss_ids)
        conn = sqlite3.connect(str(self._db), timeout=10)
        try:
            q_approved = "SELECT id, plan, intent_embedding FROM agent_tasks WHERE forge_verdict='approved' AND status='done' AND intent_embedding IS NOT NULL"
            rows = conn.execute(q_approved).fetchall()
        finally:
            conn.close()
        if not rows:
            self._loaded = True
            return False
        ids, plans, vecs = [], [], []
        skipped: dict = {}
        for tid, plan, blob in rows:
            v = np.frombuffer(blob, dtype=np.float32)
            if v.shape[0] == self._dim:
                ids.append(tid)
                plans.append(plan)
                vecs.append(v)
            else:
                skipped[int(v.shape[0])] = skipped.get(int(v.shape[0]), 0) + 1
        self._dim_skipped = sum(skipped.values())
        if skipped:
            # Une autre dimension = un autre modele = un espace vectoriel non
            # comparable. Ecarter en silence vidait l'index sans aucun bruit.
            logger.warning(f"IntentRouter: {self._dim_skipped} taches ecartees dim!={self._dim} -> {skipped}")
        if not vecs:
            self._loaded = True
            return False
        M = np.array(vecs, dtype=np.float32)
        norms = np.linalg.norm(M, axis=1, keepdims=True)
        norms[norms == 0] = 1
        M = M / norms
        try:
            import faiss

            # METRIC_INNER_PRODUCT obligatoire. Par defaut l'index est en L2 et
            # search() rend une DISTANCE (0=identique, 4=oppose) que le code
            # comparait a des seuils de SIMILARITE : decisions exactement
            # inversees (cos 0.9985 -> 0.0029 -> fallback ; cos -1.0 -> 4.0 -> bypass).
            idx = faiss.IndexHNSWFlat(self._dim, 32, faiss.METRIC_INNER_PRODUCT)
            idx.hnsw.efSearch = 64
            idx.add(M)
            self._faiss_index = idx
        except ImportError:
            self._faiss_index = M
        self._faiss_ids = ids
        self._faiss_plans = plans
        self._loaded = True
        logger.info(f"IntentRouter: {len(ids)} taches indexees")
        return True

    def _search(self, qv: np.ndarray, k: int = 3) -> dict:
        if not self._faiss_ids:
            return {}
        q = (qv / (np.linalg.norm(qv) + 1e-9)).astype(np.float32)
        k = max(1, min(k, len(self._faiss_ids)))
        pairs: list = []  # [(score, position)] decroissant
        if hasattr(self._faiss_index, "search"):
            try:
                scores, indices = self._faiss_index.search(q.reshape(1, -1), k)
                pairs = [(float(s), int(i)) for s, i in zip(scores[0], indices[0]) if int(i) >= 0]
            except Exception as e:
                # Avaler l'echec rendait {} -> score 0 -> fallback silencieux.
                logger.warning(f"IntentRouter faiss search err: {e}")
                return {}
        elif isinstance(self._faiss_index, np.ndarray):
            sims = self._faiss_index @ q
            top = np.argsort(sims)[::-1][:k]
            pairs = [(float(sims[i]), int(i)) for i in top]
        if not pairs:
            return {}
        best_score, best_i = pairs[0]
        runner = pairs[1] if len(pairs) > 1 else None
        return {
            "task_id": self._faiss_ids[best_i],
            "plan": self._faiss_plans[best_i],
            "score": best_score,
            # Marge top1-top2 : une marge nulle = plusieurs plans distincts a
            # egalite, signal d'incertitude que le score seul ne porte pas.
            "margin": (best_score - runner[0]) if runner else 1.0,
            "runner_up": self._faiss_ids[runner[1]] if runner else None,
            "neighbours": [(self._faiss_ids[i], round(s, 4)) for s, i in pairs],
        }

    async def backfill_embeddings(self, limit=50) -> dict:
        conn = sqlite3.connect(str(self._db), timeout=60)
        q_miss = "SELECT id, title, description FROM agent_tasks WHERE forge_verdict='approved' AND status='done' AND (intent_embedding IS NULL OR intent_hash='') LIMIT ?"
        rows = conn.execute(q_miss, (limit,)).fetchall()
        done, errors = 0, 0
        for tid, title, desc in rows:
            text = f"{title}. {desc}"
            h = hashlib.md5(text.encode()).hexdigest()
            vec = await self._embed(text)
            if vec is not None:
                blob = vec.astype(np.float32).tobytes()
                conn.execute("UPDATE agent_tasks SET intent_embedding=?, intent_hash=? WHERE id=?", (blob, h, tid))
                done += 1
            else:
                errors += 1
        conn.commit()
        conn.close()
        if done > 0:
            self._load_index(force=True)
        logger.info(f"IntentRouter backfill: {done} ok {errors} err")
        return {"backfilled": done, "errors": errors}

    async def route(self, query: str, task_type="", entity_id="laforge", token="") -> dict:
        t0 = time.perf_counter()
        # RBAC pre-check non bloquant
        rbac_ok = True
        try:
            import sys as _s, os as _o

            _app = str(_o.path.dirname(__file__))
            if _app not in _s.path:
                _s.path.insert(0, _app)
            from nokido_agent.app.forge_rbac import get_rbac, is_breakglass

            if not is_breakglass(token):
                rbac_ok = get_rbac().check(entity_id, "task_create", token=token)
        except Exception as e:
            logger.debug(f"IntentRouter RBAC skip: {e}")

        vec = await self._embed(query)
        if vec is None:
            return {
                "action": "llm_fallback",
                "confidence": 0.0,
                "plan": None,
                "source_task": None,
                "context_hint": None,
                "rbac_check": rbac_ok,
                "entity_id": entity_id,
            }

        self._load_index()
        best = self._search(vec)
        score = best.get("score", 0.0)
        margin = float(best.get("margin", 1.0)) if best else 1.0

        plan_obj = None
        if best and best.get("plan"):
            try:
                plan_obj = json.loads(best["plan"])
            except (TypeError, ValueError) as e:
                # Un plan illisible n'est pas rejouable : ne jamais bypasser dessus.
                logger.warning(f"IntentRouter: plan illisible task={best.get('task_id')}: {e}")

        # Le score seul ne suffit pas : il faut que le meilleur plan se DETACHE
        # (marge) et qu'il soit REJOUABLE (plan lisible).
        do_bypass = score >= THRESHOLD_BYPASS and bool(best) and margin >= THRESHOLD_MARGIN and plan_obj is not None
        acted = (
            "bypass"
            if do_bypass
            else "suggest"
            if score >= THRESHOLD_SUGGEST
            else "enrich"
            if score >= THRESHOLD_ENRICH
            else "llm_fallback"
        )
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(f"IntentRouter: score={score:.3f} marge={margin:.3f} t={elapsed:.1f}ms action={acted}")

        if do_bypass:
            self._update_replay(best["task_id"])
            return {
                "action": "bypass",
                "confidence": score,
                "margin": margin,
                "runner_up": best.get("runner_up"),
                "plan": plan_obj,
                "source_task": best["task_id"],
                "context_hint": None,
                "rbac_check": rbac_ok,
                "entity_id": entity_id,
            }

        if score >= THRESHOLD_SUGGEST and best:
            if score >= THRESHOLD_BYPASS:
                why = (
                    f"marge {margin:.3f} < {THRESHOLD_MARGIN} — plans a egalite"
                    if margin < THRESHOLD_MARGIN
                    else "plan source illisible"
                )
                hint = f"Score {score:.2f} suffisant mais DEGRADE : {why} — validation requise"
                logger.info(f"IntentRouter: bypass degrade en suggest ({why})")
            else:
                hint = f"Plan similaire score={score:.2f}, validation requise"
            return {
                "action": "suggest",
                "confidence": score,
                "margin": margin,
                "runner_up": best.get("runner_up"),
                "plan": plan_obj,
                "source_task": best["task_id"],
                "context_hint": hint,
                "rbac_check": rbac_ok,
                "entity_id": entity_id,
            }

        if score >= THRESHOLD_ENRICH and best:
            return {
                "action": "enrich",
                "confidence": score,
                "plan": None,
                "source_task": best["task_id"],
                "context_hint": f"Tache similaire score={score:.2f} — injecter comme contexte",
                "rbac_check": rbac_ok,
                "entity_id": entity_id,
            }

        return {
            "action": "llm_fallback",
            "confidence": score,
            "plan": None,
            "source_task": None,
            "context_hint": None,
            "rbac_check": rbac_ok,
            "entity_id": entity_id,
        }

    def _update_replay(self, task_id: str) -> None:
        try:
            conn = sqlite3.connect(str(self._db), timeout=5)
            conn.execute("UPDATE agent_tasks SET replay_count=replay_count+1, bypass_llm=1 WHERE id=?", (task_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"replay_count update err: {e}")

    def reload_index(self):
        self._load_index(force=True)

    def stats(self) -> dict:
        conn = sqlite3.connect(str(self._db), timeout=5)
        total = conn.execute(
            "SELECT COUNT(*) FROM agent_tasks WHERE forge_verdict='approved' AND status='done'"
        ).fetchone()[0]
        indexed = conn.execute(
            "SELECT COUNT(*) FROM agent_tasks WHERE forge_verdict='approved' AND status='done' AND intent_embedding IS NOT NULL"
        ).fetchone()[0]
        bypassed = conn.execute("SELECT COALESCE(SUM(replay_count),0) FROM agent_tasks").fetchone()[0]
        conn.close()
        return {
            "approved_tasks": total,
            "indexed_tasks": indexed,
            "total_bypasses": int(bypassed),
            "cache_size": len(self._embed_cache),
            "faiss_loaded": self._loaded,
            "index_size": len(self._faiss_ids),
            "dim_skipped": self._dim_skipped,
            "thresholds": {"bypass": THRESHOLD_BYPASS, "suggest": THRESHOLD_SUGGEST, "enrich": THRESHOLD_ENRICH},
        }


_router: Optional[IntentRouter] = None


def get_intent_router(db_path=None, model=None) -> IntentRouter:
    global _router
    if _router is None:
        _router = IntentRouter(db_path=db_path, model=model)
    return _router


def register_in_container(container) -> None:
    def _factory():
        return IntentRouter()

    container.register("intent_router", _factory)
    logger.info("IntentRouter enregistre dans DIContainer")


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async def _test():
        print("=== forge_intent_router self-test ===")
        r = IntentRouter()
        s = r.stats()
        print(f"Stats: {s}")
        d = await r.route("analyser les logs nginx", entity_id="agt_claude")
        print(f"Route (vide): {d['action']} conf={d['confidence']:.3f}")
        assert d["action"] == "llm_fallback"
        bf = await r.backfill_embeddings(limit=5)
        print(f"Backfill: {bf}")
        s2 = r.stats()
        print(f"Stats apres backfill: {s2}")
        print("Self-test PASS")

    asyncio.run(_test())
