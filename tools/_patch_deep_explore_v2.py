#!/usr/bin/env python3
"""_patch_deep_explore_v2.py — durcit #1+#2 après test live :
  (A) breaker : verdict_mem (in-mem, fail-open silencieux) -> verdict() FS partagé
      (cross-process) + LOG chaque décision dans C:/tmp/recon_breaker.log (observable).
  (B) forge_deep_explore : abandonne synth_local (swarm async = coroutine jamais await,
      fuite) -> DIGEST déterministe des hits (0 token, toujours dispo).
Idempotent : ABORT si ancrage absent ; SKIP si déjà v2. compile() avant write.
"""
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
F = ROOT / "app" / "forge_mcp_registry.py"
src = F.read_text(encoding="utf-8")

if "recon_breaker.log" in src:
    print("SKIP: v2 déjà appliqué")
    sys.exit(0)

EDITS = []

# (A) breaker block -> FS verdict + log
EDITS.append((
'''        # Coupe-circuit COMPORTEMENTAL (anti-fuite-tokens) : throttle la recon FINE
        # (tool `read`) sur du code Nokido, pour TOUT client MCP (agy inclus, sans
        # hook) -> force forge_deep_explore. Compteur en memoire (process hub). Fail-open.
        if name == "read":
            try:
                import sys as _sys
                from pathlib import Path as _P
                _tp = str(_P(__file__).resolve().parent.parent / "tools")
                if _tp not in _sys.path:
                    _sys.path.insert(0, _tp)
                from forge_recon_breaker import verdict_mem, is_nokido_args  # type: ignore
                _v, _why, _n = verdict_mem(agent or "UNKNOWN", "read", is_nokido_args(args))
                if _v == "deny":
                    return {"error": "recon_throttled", "reason": _why,
                            "tool": name, "delegate_to": "forge_deep_explore"}
            except Exception:
                pass''',
'''        # Coupe-circuit COMPORTEMENTAL (anti-fuite-tokens) : throttle la recon FINE
        # (tool `read`) sur du code Nokido, pour TOUT client MCP (agy inclus, sans hook)
        # -> force forge_deep_explore. Compteur FS partage (cross-process). Log observable.
        if name == "read":
            try:
                import sys as _sys, time as _tm
                from pathlib import Path as _P
                _tp = str(_P(__file__).resolve().parent.parent / "tools")
                if _tp not in _sys.path:
                    _sys.path.insert(0, _tp)
                import forge_recon_breaker as _brk
                _islf = _brk.is_nokido_args(args)
                _v, _why, _n = _brk.verdict(str(agent or "HUB"), "read", _islf)
                try:
                    with open(r"C:/tmp/recon_breaker.log", "a", encoding="utf-8") as _lf:
                        _lf.write(f"{int(_tm.time())} read agent={agent} islf={_islf} v={_v} n={_n}\\n")
                except Exception:
                    pass
                if _v == "deny":
                    return {"error": "recon_throttled", "reason": _why,
                            "tool": name, "delegate_to": "forge_deep_explore"}
            except Exception as _e:
                try:
                    with open(r"C:/tmp/recon_breaker.log", "a", encoding="utf-8") as _lf:
                        _lf.write(f"BRK_ERR {type(_e).__name__}: {str(_e)[:140]}\\n")
                except Exception:
                    pass'''))

# (B) deep_explore : digest déterministe (drop synth async cassé)
EDITS.append((
'''        def _run():
            import sys as _s
            from pathlib import Path as _P
            _tp = str(_P(__file__).resolve().parent.parent / "tools")
            if _tp not in _s.path:
                _s.path.insert(0, _tp)
            import forge_local_explore as fle  # type: ignore
            _globs = [g.strip() for g in globs.split(",") if g.strip()]
            _res = fle.search(query, _globs, context=2, max_hits=max_hits)
            _syn = fle.synth_local(intent, _res.get("hits", []), None)
            return _res, _syn

        try:
            res, synth = await _aio.to_thread(_run)
        except Exception as e:  # noqa: BLE001
            return {"error": f"deep_explore: {type(e).__name__}: {str(e)[:120]}"}
        hits = res.get("hits", [])
        files = sorted({h.get("file", "") for h in hits})
        return {
            "ok": True,
            "intent": intent,
            "synthesis": synth,
            "files_touched": files[:40],
            "n_hits": len(hits),
            "note": "recon LOCALE souveraine (0 token cloud). Affine via {target, globs, breadth}.",
        }''',
'''        def _run():
            import sys as _s
            from pathlib import Path as _P
            _tp = str(_P(__file__).resolve().parent.parent / "tools")
            if _tp not in _s.path:
                _s.path.insert(0, _tp)
            import forge_local_explore as fle  # type: ignore
            _globs = [g.strip() for g in globs.split(",") if g.strip()]
            return fle.search(query, _globs, context=2, max_hits=max_hits)

        try:
            res = await _aio.to_thread(_run)
        except Exception as e:  # noqa: BLE001
            return {"error": f"deep_explore: {type(e).__name__}: {str(e)[:120]}"}
        hits = res.get("hits", [])
        files = sorted({h.get("file", "") for h in hits})
        _parts = []
        for h in hits[:60]:
            _parts.append(f"--- {h.get('file')}:{h.get('line')}")
            _parts.append(str(h.get("excerpt", ""))[:400])
        digest = "\\n".join(_parts)[:8000]
        return {
            "ok": True,
            "intent": intent,
            "files_touched": files[:40],
            "n_hits": len(hits),
            "digest": digest,
            "note": "recon LOCALE déterministe (0 token cloud, file:line + extraits). Affine via {target, globs, breadth}.",
        }'''))

for i, (old, new) in enumerate(EDITS, 1):
    c = src.count(old)
    if c != 1:
        print(f"ABORT E{i}: {c} matches (need 1)")
        sys.exit(1)
    src = src.replace(old, new)

try:
    compile(src, str(F), "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError: {e}")
    sys.exit(2)

try:
    F.write_text(src, encoding="utf-8")
except Exception as e:
    print(f"WRITE_FAIL: {type(e).__name__}: {e}")
    sys.exit(3)

print(f"OK v2: forge_mcp_registry.py patched ({len(EDITS)} edits, {len(src)} bytes, compile OK)")
