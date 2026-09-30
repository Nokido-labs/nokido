#!/usr/bin/env python3
"""forge_embed_router_8099_test.py — valide le câblage :8099 dans embed_router.

Vérifie : llama8099 en 1er provider + creds OK + fn directe 1024d + cascade embed()
1024d (passe par le local :8099) + blob compat rag_chunks (4096 bytes). Run trusted.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app import forge_embed_router as er  # noqa: E402


def main() -> int:
    # 1. llama8099 = 1er provider, creds OK (toujours tenté, local)
    assert er.PROVIDERS[0][0] == "llama8099", er.PROVIDERS[0][0]
    assert er._provider_has_creds("llama8099") is True
    assert er._CB_TIMEOUT_PROVIDER.get("llama8099") == 30.0

    # 2. fn directe :8099 -> 1024d BGE-M3 réel
    v = er._embed_llama8099("a sample sentence to embed for the local test")
    assert v and len(v) == 1024, f"llama8099 direct dim: {None if not v else len(v)}"

    # 3. cascade embed() -> 1024d (doit choisir llama8099, pas le cloud)
    v2 = er.embed("another distinct sentence for the cascade path")
    assert v2 and len(v2) == 1024, f"embed() dim: {None if not v2 else len(v2)}"

    # 4. blob compat rag_chunks (1024 float32 = 4096 bytes)
    blob = er.encode_blob(v2)
    assert len(blob) == 4096, f"blob bytes: {len(blob)}"

    # 5. batch :8099 (ordre préservé, N textes) — le path BULK RAG
    vb = er._llama8099_call(["first text alpha", "second text beta", "third gamma here"])
    assert vb and len(vb) == 3 and all(len(x) == 1024 for x in vb), \
        f"batch dims: {None if not vb else [len(x) for x in vb]}"

    # 6. embed_batch_fast = local-first via :8099 (Essai 0), pas cloud
    vf = er.embed_batch_fast(["bulk sentence one", "bulk sentence two"])
    assert vf and len(vf) == 2 and all(x and len(x) == 1024 for x in vf), \
        f"batch_fast dims: {[None if not x else len(x) for x in vf]}"

    print(f"EMBED-8099 OK | PROVIDERS[0]={er.PROVIDERS[0][0]} | direct={len(v)}d cascade={len(v2)}d "
          f"blob={len(blob)}B batch={len(vb)}x{len(vb[0])}d batch_fast={len(vf)}x{len(vf[0])}d | RAG embed LOCAL (single+bulk)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
