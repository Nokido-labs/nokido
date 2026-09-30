<!-- DEPORTE depuis CLAUDE.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de CLAUDE.md, re-facture a chaque tour. -->

# 13. Protocole ZMQ brain_worker :5557

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## 13. Protocole ZMQ brain_worker :5557

> ⚠ **:5557 DISABLED depuis 2026-06-03** (3 services embed disabled dans proxy_deno/core/services.toml ;
> cause = BGE-M3 ONNX 'bad allocation' OOM sur Cast node, RAM 81%). **L'embedder LIVE =
> `:8099` NokidoLlamaEmbed** (BGE-M3 GGUF llama.cpp GPU, HTTP `/v1/embeddings`), câblé en
> 1er provider dans `forge_embed_router` (single `embed()` + batch `embed_batch_fast`).
> Pour embedder : passer par `forge_embed_router` (route vers :8099). Le protocole ZMQ
> ci-dessous reste valable SI :5557 est réparé (re-export onnxruntime OU migration tinygrad).

brain_worker tourne en ONNX NPU (BGE-M3, 1024D). Socket ZMQ DEALER
(ou REQ depuis les scripts). Toujours utiliser msgpack.

### Submit + poll pattern (a utiliser dans TOUT script embed)

```python
import zmq, msgpack, time

ctx = zmq.Context()
sock = ctx.socket(zmq.REQ)
sock.connect("tcp://localhost:5557")

# --- SUBMIT ---
sock.send(msgpack.packb(
    {"cmd": "submit", "type": "embed", "texts": ["texte1", "texte2"]},
    use_bin_type=True
))
if not sock.poll(10_000):
    raise TimeoutError("submit timeout")
rep = msgpack.unpackb(sock.recv(), raw=False)
task_id = rep["task_id"]   # NOT rep["result"] — cle = task_id direct

# --- POLL jusqu a completion ---
for _ in range(120):
    sock.send(msgpack.packb({"cmd": "check", "task_id": task_id}, use_bin_type=True))
    if not sock.poll(5_000):
        raise TimeoutError("check timeout")
    res = msgpack.unpackb(sock.recv(), raw=False)
    status = res.get("status", "pending")
    if status == "completed":            # PAS "done" — c est "completed"
        data = res.get("data")          # PAS "result" — c est "data"
        if isinstance(data, dict):
            vecs = data.get("vecs", []) # liste de listes float (1024D)
        elif isinstance(data, list):
            vecs = data
        break
    elif status == "error":
        raise RuntimeError(res.get("error", "embed error"))
    time.sleep(1)
```

### Drain socket REQ apres timeout (evite "Operation cannot be accomplished")

```python
sock.setsockopt(zmq.RCVTIMEO, 1000)
try:
    sock.recv()
except Exception:
    pass
sock.setsockopt(zmq.RCVTIMEO, -1)
```

### Regles sub-batch (forge_embed_auto_trigger.py)

- BATCH_SIZE = 200 chunks par passe DB
- SUB_BATCH = 20 textes par submit brain_worker (overhead ZMQ trop haut si 1)
- Throughput observe : ~0.05s/chunk → ~48 000 chunks/heure
- Embeddings stockes en BLOB float32 binaire (1024 floats = 4096 bytes)
  OU JSON TEXT selon origine. `_decode_embedding_blob()` dans
  forge_rag_engine.py gere les deux formats sans intervention.

---

