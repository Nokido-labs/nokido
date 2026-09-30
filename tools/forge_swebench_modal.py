#!/usr/bin/env python3
"""tools/forge_swebench_modal.py — SWE-bench sur Modal (conteneurs cloud //).

POURQUOI : les runs détachés locaux sont non fiables ici (sandbox ACL, clones
pollués, hangs, monitoring aveugle). Modal = un conteneur ÉPHÉMÈRE ISOLÉ par
instance, en parallèle → contourne tous ces problèmes.

COÛT : free tier limité (~5 $/mois). cpu=2, timeout 1800s. TESTER d'abord
sur --max-n 1 (~0,05 $) avant un run complet (~0,5-1 $ pour 15).

────────────────────────────────────────────────────────────────────────────
SETUP (une fois, modal CLI authentifié — cf %USERPROFILE%/.modal.toml) :

  modal secret create laforge-llm-keys ^
      MISTRAL_API_KEY=<val> NVIDIA_NIM_API_KEY=<val> CEREBRAS_API_KEY=<val>

  (valeurs = celles de Nokido.env. Le swarm utilise mistral/nvidia/cerebras.)

LANCER :
  modal run tools/forge_swebench_modal.py --max-n 1     # test 1 instance
  modal run tools/forge_swebench_modal.py --max-n 15    # run complet

SORTIE : <SWE_DIR de forge_swebench_runner>/predictions_modal_<n>.jsonl (hors de RAG/ depuis le 2026-09-27)
────────────────────────────────────────────────────────────────────────────
NB : si une API Modal erreure (l'API drifte selon la version) — coller
l'erreur, correctif rapide.
"""

import json
from pathlib import Path

import modal

_RUNNER = Path(__file__).resolve().parent / "forge_swebench_runner.py"

app = modal.App("laforge-swebench")

# Image conteneur : debian + git + le runner Nokido embarqué.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install("requests")
    .add_local_file(str(_RUNNER), "/root/forge_swebench_runner.py")
    .add_local_file(str(_RUNNER.parent / "forge_warpgrep.py"), "/root/forge_warpgrep.py")
)

# Clés LLM injectées en variables d'env (cf `modal secret create` ci-dessus).
llm_secret = modal.Secret.from_name("laforge-llm-keys")


@app.function(image=image, secrets=[llm_secret], timeout=2400, cpu=2.0, retries=1)
def solve_instance(instance: dict) -> dict:
    """Résout UNE instance SWE-bench dans un conteneur frais (Linux)."""
    import sys
    import tempfile
    import time as _t

    sys.path.insert(0, "/root")
    from nokido_agent.tools import forge_swebench_runner as r

    # Le runner hardcode un python Windows — en conteneur Linux, le réécrire.
    r.LAFORGE_PYTHON = sys.executable
    iid = instance.get("instance_id", "?")
    print(f"[modal] {iid} : debut", flush=True)
    t0 = _t.time()
    work = Path(tempfile.mkdtemp())
    try:
        # test_fix=False : la boucle test locale fait un `pip install -e .`
        # lourd (astropy compile du C -> >30 min, explose budget + timeout).
        # On génère le patch ; le scoring DooD officiel jugera la correction.
        pred = r.generate_patch_swarm(instance, work, test_fix=False, best_of=1)
        print(
            f"[modal] {iid} : fini {_t.time() - t0:.0f}s "
            f"patch={len(pred.get('model_patch') or '')}o",
            flush=True,
        )
        return pred
    except Exception as e:  # noqa: BLE001
        print(f"[modal] {iid} : CRASH {type(e).__name__}: {e}", flush=True)
        return {
            "instance_id": iid,
            "model_patch": "",
            "error": f"modal_crash: {type(e).__name__}: {str(e)[:200]}",
        }


@app.local_entrypoint()
def main(max_n: int = 1):
    """Charge max_n instances SWE-bench Verified et les résout en // sur Modal."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from nokido_agent.tools import forge_swebench_runner as r

    instances = r.ensure_dataset("test", "verified")[:max_n]
    print(f"[modal] {len(instances)} instances -> Modal (parallele)")
    preds = list(solve_instance.map(instances))
    out = r.SWE_DIR / f"predictions_modal_{max_n}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(p) for p in preds), encoding="utf-8")
    ok = sum(1 for p in preds if (p.get("model_patch") or "").strip())
    print(f"[modal] {ok}/{len(preds)} patches non-vides -> {out}")
