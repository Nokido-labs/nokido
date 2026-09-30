# -*- coding: utf-8 -*-
"""One-shot patcher: fix cold-wedge RAG (RCA 2026-07-07) on app/forge_mcp_registry.py.

CRITICAL_FILE -> applied via owner trusted_script (mirror forge_patch_mcpsec_fix3):
exact-match (assert count==1), idempotence guard, AST compile() BEFORE write,
newline-style preserved. Aborts without writing on any mismatch. Re-runnable.

Fix (3 blocks):
  A. _rag_dense_search: never load the ~691k-embeddings matrix inline on a
     search. No cache -> kick background refresh + raise (handle_rag falls back
     to BM25, already wired). Stale cache -> serve stale + background refresh
     (stale-while-revalidate). TTL 300s -> env LAFORGE_DENSE_CACHE_TTL (1800s).
  B. New method _dense_refresh_bg: daemon thread, non-blocking Lock = single
     loader; never overwrites a healthy cache with an empty load.
  C. get_registry(): kick prewarm at hub singleton creation (first dispatch /
     tools-list, seconds after boot). Opt-out LAFORGE_RAG_PREWARM=0. Tests that
     instantiate ToolRegistry() directly do NOT trigger it.

Does NOT touch _save_embeddings nor the chunks pipeline (wipe trap, cf RCA).
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

A_OLD = (
    '        cache = getattr(self, "_dense_cache", None)\n'
    '        if not cache or _t.time() - cache["ts"] > 300:\n'
    '            cache = self._load_dense_cache()\n'
    '            self._dense_cache = cache\n'
)
A_NEW = (
    '        # Cold-wedge RCA 2026-07-07 : le load ~691k embeddings (GIL-bound,\n'
    '        # minutes) ne tourne plus JAMAIS inline sur un search. Pas de cache\n'
    '        # -> refresh background + raise (handle_rag bascule BM25). Cache\n'
    '        # stale -> stale-while-revalidate (sert le stale, refresh en fond).\n'
    '        cache = getattr(self, "_dense_cache", None)\n'
    '        _ttl = float(os.environ.get("LAFORGE_DENSE_CACHE_TTL", "1800"))\n'
    '        if not cache:\n'
    '            self._dense_refresh_bg()\n'
    '            raise RuntimeError("dense cache warming -> fallback BM25")\n'
    '        if _t.time() - cache["ts"] > _ttl:\n'
    '            self._dense_refresh_bg()\n'
)

B_OLD = '    def _rag_dense_search(self, topic: str, limit: int, multi: bool = False) -> str:'
B_NEW = (
    '    def _dense_refresh_bg(self) -> None:\n'
    '        """Pre-warm/refresh du cache dense en thread daemon, race-garde.\n'
    '\n'
    '        Cold-wedge RCA 2026-07-07 : _load_dense_cache decode ~691k\n'
    '        embeddings (GIL-bound) -> jamais inline. Lock non-bloquant = un\n'
    '        seul loader ; les searches pendant le warm servent le stale ou\n'
    '        tombent en BM25. Ne touche PAS _save_embeddings (piege wipe).\n'
    '        """\n'
    '        import threading as _th\n'
    '\n'
    '        lk = getattr(self, "_dense_lock", None)\n'
    '        if lk is None:\n'
    '            lk = self._dense_lock = _th.Lock()\n'
    '        if not lk.acquire(blocking=False):\n'
    '            return  # warm deja en cours\n'
    '\n'
    '        def _work():\n'
    '            try:\n'
    '                c = self._load_dense_cache()\n'
    '                # Jamais ecraser un cache sain par un load vide (DB en vrac).\n'
    '                if c.get("ids") or getattr(self, "_dense_cache", None) is None:\n'
    '                    self._dense_cache = c\n'
    '                logging.getLogger(__name__).info(\n'
    '                    "[rag] dense cache warm OK: %d vecteurs", len(c.get("ids") or [])\n'
    '                )\n'
    '            except Exception as e:\n'
    '                logging.getLogger(__name__).warning("[rag] dense warm failed: %s", e)\n'
    '            finally:\n'
    '                lk.release()\n'
    '\n'
    '        _th.Thread(target=_work, name="rag-dense-prewarm", daemon=True).start()\n'
    '\n'
    '    def _rag_dense_search(self, topic: str, limit: int, multi: bool = False) -> str:'
)

C_OLD = (
    'def get_registry() -> ToolRegistry:\n'
    '    global _registry\n'
    '    if _registry is None:\n'
    '        _registry = ToolRegistry()\n'
    '    return _registry\n'
)
C_NEW = (
    'def get_registry() -> ToolRegistry:\n'
    '    global _registry\n'
    '    if _registry is None:\n'
    '        _registry = ToolRegistry()\n'
    '        # Cold-wedge RCA 2026-07-07 : pre-warm dense au boot du singleton\n'
    '        # hub (thread daemon race-garde) -> le 1er rag search ne gele plus\n'
    '        # le hub. Opt-out : LAFORGE_RAG_PREWARM=0.\n'
    '        if os.environ.get("LAFORGE_RAG_PREWARM", "1") != "0":\n'
    '            try:\n'
    '                _registry._dense_refresh_bg()\n'
    '            except Exception:\n'
    '                pass\n'
    '    return _registry\n'
)

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "_dense_refresh_bg" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

for label, old in (("A", A_OLD), ("B", B_OLD), ("C", C_OLD)):
    n = text.count(old)
    if n != 1:
        print(f"ABORT: block {label} found {n} times (expected exactly 1) -> no write")
        sys.exit(2)

text = text.replace(A_OLD, A_NEW, 1)
text = text.replace(B_OLD, B_NEW, 1)
text = text.replace(C_OLD, C_NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

out = text.replace("\n", nl)
open(TARGET, "wb").write(out.encode("utf-8"))
print(f"OK: cold-wedge prewarm A+B+C applied + AST valid. newline={nl!r}")
