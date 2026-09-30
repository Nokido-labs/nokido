import asyncio
import sys
import time

import aiohttp

# Ajout du path pour importer les modules Nokido
# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))


async def bench_wasm(text):
    url = "http://127.0.0.1:55555/v1/embeddings"
    t0 = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json={"model": "nomic-embed-text", "input": text}, timeout=5
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    dt = (time.monotonic() - t0) * 1000
                    return dt, len(data["data"][0]["embedding"])
    except Exception as e:
        return None, str(e)
    return None, "Error"


async def bench_ollama(text):
    url = "http://127.0.0.1:11434/api/embed"
    t0 = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json={"model": "nomic-embed-text", "input": text}, timeout=5
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    dt = (time.monotonic() - t0) * 1000
                    return dt, len(data["embeddings"][0])
    except Exception as e:
        return None, str(e)
    return None, "Error"


def bench_npu(text):
    t0 = time.monotonic()
    try:
        from nokido_agent.app.forge_npu_embedder import get_embed

        # Utilise get_embed qui gere le probe subprocess automatiquement
        emb = get_embed([text])
        if emb:
            dt = (time.monotonic() - t0) * 1000
            return dt, len(emb[0])
    except Exception as e:
        return None, str(e)
    return None, "NPU Not Available"


async def run_bench():
    test_text = "Nokido est un systeme souverain d'orchestration d'agents IA."
    print("--- BENCHMARK EMBEDDINGS (Règle d'Or 2026-05-01) ---")
    print(f"Texte de test : '{test_text}'\n")

    # 1. NPU
    npu_dt, npu_dim = bench_npu(test_text)
    print(f"[NPU ONNX]  Latence: {f'{npu_dt:.2f}ms' if npu_dt else 'FAIL'} | Dim: {npu_dim}")

    # 2. WASM Docker
    wasm_dt, wasm_dim = await bench_wasm(test_text)
    print(f"[WASM 55555] Latence: {f'{wasm_dt:.2f}ms' if wasm_dt else 'FAIL'} | Dim: {wasm_dim}")

    # 3. Ollama Standard
    ollama_dt, ollama_dim = await bench_ollama(test_text)
    print(
        f"[Ollama 11434] Latence: {f'{ollama_dt:.2f}ms' if ollama_dt else 'FAIL'} | Dim: {ollama_dim}"
    )


if __name__ == "__main__":
    asyncio.run(run_bench())
