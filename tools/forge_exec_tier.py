#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_exec_tier.py — politique TRUST→TIER d'exécution de code.

Route l'exécution selon le NIVEAU DE CONFIANCE (axe ISOLATION), distinct de
forge_orchestration_gate (axe COÛT/lane). Tiers mesurés 2026-06-17 :

  Tier0 NATIF   — code TRUSTED (tes jobs : numpy/torch/forge/réseau). Pleine vitesse.
  Tier1 WASM    — module .wasm UNTRUSTED pur-calcul (wasmtime ~25ms / wasmedge wasi_nn).
  Tier2 gVisor  — code UNTRUSTED python/sh avec FS/I/O. Noyau user-space 4.19-gvisor,
                  syscall-filtering, network=none (exfil BLOQUÉ, mesuré OSError).
                  Via forge_privileged_bridge (pont gouverné → daemon owner → runsc).

Fail-closed : untrusted ne tombe JAMAIS en Tier0 natif. Compose l'existant
(forge_wasm_cervelet.run_wasm, forge_privileged_bridge.request_privileged).
"""
from __future__ import annotations

_TRUSTED = {"trusted", "owner", "system"}


def pick_tier(trust: str, kind: str = "python") -> str:
    """(trust, kind) → tier. trust trusted/owner/system → tier0 ; sinon untrusted :
    kind 'wasm' → tier1, kind python/sh → tier2 (gVisor)."""
    if (trust or "").strip().lower() in _TRUSTED:
        return "tier0"
    if kind == "wasm":
        return "tier1"
    return "tier2"


def run_sandboxed(payload: str, *, kind: str = "python", trust: str = "untrusted",
                  network: str = "none", timeout: int = 40, native_runner=None) -> dict:
    """Exécute `payload` dans le tier dicté par (trust, kind). Retourne {tier, ...}.

    - tier0 : trusted → native_runner(payload) requis, sinon FAIL-CLOSED.
    - tier1 : payload = chemin .wasm → forge_wasm_cervelet.run_wasm.
    - tier2 : payload = source python/sh untrusted → bridge gvisor_run (network=none).
    """
    tier = pick_tier(trust, kind)
    if tier == "tier0":
        if native_runner is None:
            return {"ok": False, "tier": tier,
                    "error": "tier0 natif = trusted + native_runner requis (fail-closed)"}
        r = native_runner(payload)
        return {"tier": tier, **(r if isinstance(r, dict) else {"ok": True, "result": r})}
    if tier == "tier1":
        from nokido_agent.app.forge_wasm_cervelet import run_wasm

        return {"tier": tier, **run_wasm(payload)}
    from nokido_agent.tools.forge_privileged_bridge import request_privileged

    lang = "python3" if kind == "python" else "sh"
    return {"tier": tier, **request_privileged(
        "gvisor_run", {"lang": lang, "code": payload, "network": network, "timeout": timeout})}
