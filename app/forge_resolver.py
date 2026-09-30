#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_resolver.py — RÉSOLVEUR : pré-vol + résolution d'erreurs des flux.

Critique user : « tu laisses passer trop d'erreurs dans tes flux de réflexion ».
Le résolveur VALIDE avant exécution et RÉSOUT les échecs AVANT qu'ils cascadent :
  - providers : écarte les morts (breaker open, clé absente, balance, known-bad,
    OAuth-déporté-impossible) et garde/substitue les LIVE.
  - write-target : un sandbox ne peut PAS écrire le repo -> redirige vers writable.
  - ring : vérifie la suffisance (sinon conseille le bon contexte/identité).
  - contexte : un provider cloud exige internet ; gemini_cli exige la session user.

ANTI-DUP : réutilise hub list_providers (état runtime), forge_mcp_registry._get_ring_needed,
la carte des contextes d'exécution. N'invente pas de probe maison.

Phase 1 (ce fichier) = logique de validation/résolution DÉTERMINISTE, testable sans hub
(selftest). Phase 2 = brancher sur list_providers/health LIVE + auto-retry dans les flux.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : resolveur pre-vol et resolution d'erreurs des flux"  # organe declare le 2026-09-06 (audit de raccordement)

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# Providers KNOWN-BAD (jusqu'à re-validation) — appris des échecs réels.
KNOWN_BAD = {
    "deepseek": "402 Insufficient Balance",
    "grok": "clé xAI invalide (400)",
    "sambanova": "clé absente",
    "lmstudio": "401 (aucun modèle chargé / auth)",
}
# Providers qui exigent la SESSION user (KO en run_job/sandbox déporté).
SESSION_ONLY = {"gemini_cli", "claude_cli", "copilot_cli", "claude_agent_sdk"}
# Providers cloud (exigent internet ; KO en sandbox offline).
CLOUD = {"groq", "mistral", "cerebras", "gpt4o_github", "cohere", "hf", "gemini",
         "glm5", "kimi", "nvidia_nim", "openrouter_glm5", "perplexity", "claude"}
LOCAL = {"ollama", "llamacpp", "lmstudio"}


def live_providers(want: list, *, context: str = "trusted",
                   status: dict | None = None) -> tuple[list, list]:
    """Garde les providers utilisables DANS ce contexte ; renvoie (live, dropped[(p,why)]).

    context: 'trusted'/'user' (internet+loopback) | 'sandbox_offline' (loopback seul) |
             'run_job' (loopback+internet selon online) | 'session' (user session).
    status: optionnel — sortie hub list_providers {name: {available, breaker_status}}.
    """
    live, dropped = [], []
    cloud_ok = context in ("trusted", "user", "run_job", "session")
    local_ok = context in ("trusted", "user", "run_job", "session", "sandbox_offline")
    for p in want:
        base = p.split(":", 1)[0]
        if base in KNOWN_BAD:
            dropped.append((p, KNOWN_BAD[base])); continue
        if base in SESSION_ONLY and context not in ("session", "user"):
            dropped.append((p, "OAuth session-only — KO déporté (WinError5)")); continue
        if base in CLOUD and not cloud_ok:
            dropped.append((p, f"cloud sans internet (contexte {context})")); continue
        if base in LOCAL and not local_ok:
            dropped.append((p, f"local sans loopback (contexte {context})")); continue
        if status is not None:
            st = status.get(base, {})
            if st and (st.get("available") is False or st.get("breaker_status") == "OPEN"):
                dropped.append((p, f"breaker/indispo: {st.get('breaker_status')}")); continue
        live.append(p)
    return live, dropped


def writable_path(path, *, context: str = "trusted"):
    """Un sandbox NE peut PAS écrire le repo (dubious-ownership/ACL). Redirige vers
    un emplacement writable selon le contexte. Renvoie (path, redirected: bool)."""
    p = Path(path)
    in_repo = str(p).startswith(str(ROOT))
    if context in ("sandbox_offline", "run_job") and in_repo:
        alt = ROOT / "sandbox" / "workspace" / p.name  # writable par le sandbox user
        return alt, True
    return p, False


def ring_ok(needed: int, my_ring: int) -> tuple[bool, str]:
    if int(my_ring) <= int(needed):
        return True, f"ring {my_ring} <= requis {needed}"
    return False, (f"ring {my_ring} > requis {needed} — passer par un contexte ring<= "
                   f"{needed} (ex: hub_call.py=LAFORGE_CLI r1, ou fixer l'identité via videur)")


def resolve_provider_panel(roles_providers: list, *, context: str = "trusted",
                           fallbacks: list | None = None, status: dict | None = None) -> list:
    """Assigne chaque rôle à un provider LIVE. Substitue les morts par un fallback live.
    roles_providers: [(role, provider)]. Renvoie [(role, live_provider)] (rôles non
    résolus = écartés). fallbacks: pool de remplacement (défaut : cloud rapides fiables)."""
    fallbacks = fallbacks or ["groq", "mistral", "cerebras", "gpt4o_github", "cohere"]
    live_fb, _ = live_providers(fallbacks, context=context, status=status)
    out, used = [], set()
    for role, prov in roles_providers:
        keep, _drop = live_providers([prov], context=context, status=status)
        if keep:
            out.append((role, keep[0])); used.add(keep[0].split(":", 1)[0])
        else:
            sub = next((f for f in live_fb if f.split(":", 1)[0] not in used), None)
            if sub:
                out.append((role, sub)); used.add(sub.split(":", 1)[0])
    return out


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    # 1. écarte les morts + session-only en run_job
    live, drop = live_providers(["groq", "deepseek", "grok", "gemini_cli", "mistral"], context="run_job")
    chk(live == ["groq", "mistral"], f"run_job: live={live} (deepseek/grok/gemini_cli écartés)")
    # 2. cloud KO en sandbox offline
    live2, _ = live_providers(["groq", "ollama"], context="sandbox_offline")
    chk(live2 == ["ollama"], f"sandbox_offline: cloud écarté -> {live2}")
    # 3. write redirigé en run_job (repo non-inscriptible)
    p, red = writable_path(ROOT / "docs" / "x.md", context="run_job")
    chk(red and "sandbox" in str(p), f"write repo->sandbox: {p.name} red={red}")
    # 4. ring
    chk(ring_ok(3, 1)[0] and not ring_ok(3, 4)[0], "ring: 1<=3 OK, 4>3 KO+conseil")
    # 5. panel : substitue les morts par fallback live
    panel = resolve_provider_panel(
        [("A", "groq"), ("B", "deepseek"), ("C", "grok")], context="run_job")
    provs = [p for _, p in panel]
    chk("groq" in provs and "deepseek" not in provs and "grok" not in provs and len(panel) == 3,
        f"panel résolu: {provs}")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
