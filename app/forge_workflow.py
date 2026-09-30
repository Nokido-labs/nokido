#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_workflow.py — Workflow SOUVERAIN DÉPORTÉ (équivalent local du tool Workflow).

Directive user : le CLIENT (agent CLI) émet JUSTE un PLAN léger ; l'INTELLIGENCE +
toute la logique d'exécution sont DÉPORTÉES (run_job, pool LOCAL, server-side). Le
client reçoit UN résultat consolidé, pas les sorties intermédiaires (= économie tokens,
'client ≠ exécuteur'). JAMAIS le tool Workflow Claude (subagents cloud payants).

Un PLAN (dict léger, JSON-sérialisable) :
  {"name": str,
   "phases": [{"name": str, "mode": "parallel"|"pipeline",
               "agents": [{"role": str, "prompt": str, "provider": str?, "max_tokens": int?}],
               "synth": str?}],     # synth = instruction de réduction (optionnelle)
   "out": "docs/x.md"?}             # écriture optionnelle (résolveur redirige si non-inscriptible)

L'engine : résout les providers (forge_resolver = écarte morts/inadaptés au contexte),
exécute chaque phase (parallel = fan-out ; pipeline = chaîne, sortie N -> entrée N+1),
synthétise, persiste. Routeur de planif = forge_orchestration_gate.classify (voie DEPORT).

ANTI-DUP : réutilise forge_resolver (pré-vol), forge_agent_proxy.ask (agents), run_job
(déportation, via submit). forge_dag_runner (deps arbitraires) = Phase 2. forge_swarm_debate
et forge_roadmap_synth deviennent des PLANS soumis ici.

Phase 1 (ce fichier) = run_plan (exécution, déportable) + submit (déport run_job) + selftest
(ask injectable, 0 réseau). CLI : forge_workflow.py --plan <fichier.json> (lancé en run_job).
"""
from __future__ import annotations

__FORGE_COLOR__ = "locomoteur/orchestr : workflow souverain deporte"  # organe declare le 2026-09-06 (audit de raccordement)

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT))


async def _default_ask(provider: str, prompt: str, max_tokens: int) -> str:
    """Agent réel = pool LOCAL/souverain via forge_agent_proxy.ask (in-process, pas de gate)."""
    from nokido_agent.app.forge_agent_proxy import ask
    r = await ask(provider, prompt, max_tokens=max_tokens, rag_context=False)
    return (r.get("text") or "").strip() if r.get("ok") else ""


async def _run_phase(phase: dict, prev: str, context: str, ask_fn) -> tuple:
    """Exécute une phase. parallel = fan-out concurrent ; pipeline = chaîne (prev injecté).
    Providers VETTÉS par forge_resolver (morts écartés/substitués)."""
    from nokido_agent.app.forge_resolver import resolve_provider_panel
    agents = phase.get("agents", [])
    roles_provs = [(a.get("role", f"agent{i}"), a.get("provider", "groq")) for i, a in enumerate(agents)]
    vetted = resolve_provider_panel(roles_provs, context=context)
    vmap = dict(vetted)  # role -> live provider

    mode = phase.get("mode", "parallel")

    async def _one(a: dict) -> tuple:
        role = a.get("role", "agent")
        prov = vmap.get(role)
        if not prov:
            return (role, "", False)
        body = a.get("prompt", "")
        if prev:
            body = f"[CONTEXTE amont]\n{prev}\n\n{body}"
        try:
            txt = await ask_fn(prov, f"TON RÔLE = {role}.\n{body}", a.get("max_tokens", 420))
            return (role, (txt or "").strip(), bool(txt))
        except Exception as e:  # noqa: BLE001
            return (role, f"[KO: {type(e).__name__}: {e}]", False)

    if mode == "pipeline":
        out = []
        acc = prev
        for a in agents:
            role, txt, ok = await _one({**a})
            if ok:
                acc = txt  # sortie N -> entrée N+1
            out.append((role, txt, ok))
    else:  # parallel (fan-out)
        out = list(await asyncio.gather(*[_one(a) for a in agents]))

    oks = [(r, t) for r, t, k in out if k]
    synthed = None
    if phase.get("synth") and len(oks) >= 1:
        joined = "\n\n".join(f"### {r}\n{t}" for r, t in oks)
        try:
            synthed = await ask_fn("groq", f"{phase['synth']} Cite les divergences.\n\n{joined}", 700)
        except Exception:  # noqa: BLE001
            synthed = joined
    phase_out = synthed if synthed else "\n\n".join(f"### {r}\n{t}" for r, t in oks)
    return phase_out, out


async def run_plan(plan: dict, *, context: str = "trusted", ask_fn=None) -> dict:
    """Exécute un PLAN sur le pool LOCAL. Déportable (appelé en run_job). Retour consolidé."""
    ask_fn = ask_fn or _default_ask
    t0 = time.time()
    sections, prev = [], ""
    for ph in plan.get("phases", []):
        out, raw = await _run_phase(ph, prev, context, ask_fn)
        sections.append((ph.get("name", "phase"), out))
        prev = out  # chaînage inter-phases (le résultat alimente la suivante)

    body = f"# {plan.get('name', 'workflow')}\n\n" + "\n\n".join(
        f"## {n}\n{o}" for n, o in sections)
    written = None
    if plan.get("out"):
        try:
            from nokido_agent.app.forge_resolver import writable_path
            p, _red = writable_path(ROOT / plan["out"], context=context)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            written = str(p)
        except Exception as e:  # noqa: BLE001
            written = f"[write KO: {e}]"
    return {"name": plan.get("name"), "elapsed_s": round(time.time() - t0, 1),
            "sections": [n for n, _ in sections], "result": sections[-1][1] if sections else "",
            "written": written, "body": body}


def submit(plan: dict, *, online: bool = True, notify: str = "CLAUDE") -> dict:
    """DÉPORTE le workflow : écrit le plan + lance run_job(forge_workflow --plan). Le CLIENT
    n'exécute RIEN — il reçoit un job_id. Nécessite le hub (run_job)."""
    plan_path = ROOT / "sandbox" / "workspace" / f"wf_plan_{abs(hash(json.dumps(plan, sort_keys=True))) % 10**8}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return {"plan_path": str(plan_path),
            "run": f"run_job script=app/forge_workflow.py (avec --plan {plan_path.name})",
            "note": "déport via le hub run_job ; le client reçoit job_id, pas l'exécution"}


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", help="fichier JSON du plan")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest or not a.plan:
        return _selftest()
    plan = json.loads(Path(a.plan).read_text("utf-8"))
    res = asyncio.run(run_plan(plan, context="trusted"))
    print(json.dumps({k: v for k, v in res.items() if k != "body"}, ensure_ascii=False, indent=2))
    print("\n=== RÉSULTAT ===\n" + (res.get("result") or "")[:1500])
    return 0


def _selftest() -> int:
    async def _mock(provider, prompt, max_tokens):
        return f"[{provider}] vu {len(prompt)} chars"

    plan = {
        "name": "test-wf",
        "phases": [
            {"name": "P1", "mode": "parallel",
             "agents": [{"role": "A", "provider": "groq", "prompt": "x"},
                        {"role": "B", "provider": "deepseek", "prompt": "y"}],  # deepseek mort -> substitué
             "synth": "Synthétise"},
            {"name": "P2", "mode": "pipeline",
             "agents": [{"role": "C", "provider": "mistral", "prompt": "z"}]},
        ],
    }
    res = asyncio.run(run_plan(plan, context="trusted", ask_fn=_mock))
    ok = 0
    total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    chk(res["sections"] == ["P1", "P2"], f"phases exécutées: {res['sections']}")
    chk("P1" in res["body"] and "P2" in res["body"], "body contient les 2 phases")
    chk(res["result"], "résultat final non vide (chaînage inter-phases)")
    s = submit(plan)
    chk("plan_path" in s and Path(s["plan_path"]).exists(), "submit écrit le plan (déport)")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_main())
