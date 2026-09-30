#!/usr/bin/env python3
"""Délègue les tâches CTF paliers + embed aux LLMs appropriés via hub."""

__FORGE_COLOR__ = "locomoteur/dispatcher : delegue les taches CTF et embed aux LLM via le hub"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
import urllib.request
from pathlib import Path

HUB = "http://127.0.0.1:8766/mcp"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_secrets import get_secret  # noqa: E402

TOK = get_secret("FORGE_TOKEN_CLAUDE") or ""


def hub(tool, args):
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }
    ).encode()
    req = urllib.request.Request(
        HUB,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TOK}",
            "X-Agent-Name": "CLAUDE",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read())
    text = resp.get("result", {}).get("content", [{}])[0].get("text", "")
    print(f"  [{tool}] {text[:120]}")
    return text


tasks = [
    # ── Embed + ingest (Gemini, accès hub+run direct)
    (
        "agt_gemini",
        "EMBED_PRIORITY",
        "Batch embed manquant. "
        "1) Vérifier que brain_worker :5557 est UP (socket.connect_ex(127.0.0.1,5557)==0). "
        "Si non UP: run action=python code='import subprocess,sys; subprocess.Popen([sys.executable,\"tools/spawn_brain_worker_npu.py\"])' puis attendre 25s. "
        "2) Lancer: run action=python code='import subprocess,sys; subprocess.run([sys.executable,\"tools/batch_embed_priority.py\"],timeout=600)' "
        "3) Quand terminé: hub action=notify topic=embed_done message=EMBED_LAFORGE_OK",
    ),
    # ── Palier 1 — forge_gdb_live.py (groq 70B, code gen)
    (
        "agt_gemini",
        "CTF_PALIER1_GDB",
        "Créer ctf/tools/forge_gdb_live.py. "
        "Utilise: ask provider=groq message='Écris forge_gdb_live.py Python: GDB/MI protocol (gdb --interpreter=mi), "
        "fonctions: heap_dump() retourne dict{addr,size,status} tcache/fastbin/smallbin, "
        "auto_cyclic_offset(binary) retourne int offset ret_addr via cyclic+coredump, "
        "stack_align_check(regs) retourne bool. Subprocess non-bloquant, timeout 30s.' max_tokens=3000. "
        "Écrire le résultat dans ctf/tools/forge_gdb_live.py via write tool. "
        "Notifier: hub action=notify topic=ctf_done message=PALIER1_GDB_DONE",
    ),
    # ── Palier 2 — heap templates (groq 70B + qwen local)
    (
        "agt_gemini",
        "CTF_PALIER2_HEAP",
        "Créer ctf/tools/heap_templates.py. "
        "ask provider=groq message='Écris heap_templates.py Python/pwntools: "
        "tcache_poison(p, fake_chunk_addr, target_addr) pour glibc 2.31+, "
        "fastbin_dup(p, chunk_addr) pour glibc <2.27, "
        "house_of_force(p, target_addr, malloc_size) template, "
        "fsop_chain(p, libc_base) template FILE* exploit. "
        "Chaque fonction: commentaire glibc version + prérequis.' max_tokens=3000. "
        "write path=ctf/tools/heap_templates.py content=<résultat>. "
        "Notifier: hub action=notify topic=ctf_done message=PALIER2_HEAP_DONE",
    ),
    # ── Palier 4 — anti-IA-traps (mistral, raisonnement adversarial)
    (
        "agt_gemini",
        "CTF_PALIER4_ANTITRAPS",
        "Créer ctf/tools/anti_ia_traps.py. "
        "ask provider=mistral message='Écris anti_ia_traps.py Python: "
        "detect_red_herring(binary_analysis:dict) -> float score 0-1 (1=piège probable), "
        "patterns: vuln évidente mais non-exploitable, service qui détecte vitesse agentique (rate-limit), "
        "fausse stack overflow (canary caché), timeout_adaptive(attempts:list) -> int delay_ms. "
        "Logique heuristique, pas de ML.' max_tokens=2000. "
        "write path=ctf/tools/anti_ia_traps.py content=<résultat>. "
        "Notifier: hub action=notify topic=ctf_done message=PALIER4_TRAPS_DONE",
    ),
]

print("Assigning tasks to agents...")
for agent, job_id, desc in tasks:
    print(f"\n→ {job_id} → {agent}")
    hub("task", {"action": "assign", "agent": agent, "description": desc, "job_id": job_id})

print("\nDone. Gemini will claim and execute.")
