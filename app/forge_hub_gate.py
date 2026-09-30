#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_hub_gate.py — Gate de gouvernance PARALLÈLE du hub (fail-CLOSED).

Comble 3 faiblesses du pipeline `_tool_call` (nokido_hub.py) :
  (#1) RBAC fail-OPEN -> fail-CLOSED : une EXCEPTION sur un check GOUVERNÉ = DENY
       (avant, un throw de forge_rbac sautait silencieusement la capability).
  (#4) firewall absent du dispatch non-LLM -> pre-check firewall sur les ARGS,
       DANS le gate : un tool non-LLM passe enfin une garde DLP/injection.
  (parallélisation) -> résolution CONCURRENTE des resolvers indépendants via
       asyncio.gather + asyncio.to_thread (vrai parallélisme I/O). Ajouter le
       firewall ne coûte plus de latence (il tourne concurrent aux checks cheap).
  (#2) master token break-glass -> conservé (rescue) mais AUDITÉ (override visible).
(#3 monolithe registry = HORS SCOPE : refactor séparé, ce module n'y touche pas.)

ANTI-DUP CAPITAL : ce module N'IMPLÉMENTE AUCUN resolver. Il ORCHESTRE en parallèle
les existants — forge_rbac (capability), forge_mcp_registry._get_ring_needed (ring),
forge_access_switches (ReBAC), forge_semantic_firewall (DLP/injection). ByteRouter
reste séquentiel-AVANT (il réécrit name/args ; les checks en dépendent).

Politique fail-closed : un check GOUVERNÉ ({rbac, ring, switches}) qui DENY ou qui
RAISE -> requête refusée. Le firewall = best-effort (WARN) par défaut, DENY si strict.
Break-glass (token master) -> override des denials GOUVERNÉS, mais tracé OVERRIDE.

Phase 1 = ce module + selftest (checks injectables, 0 dépendance au runtime hub).
Phase 2 = wiring dans nokido_hub._tool_call (hot-path, reload requis) — séparé.
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# Checks GOUVERNÉS = fail-closed (deny ou exception -> refus). firewall = best-effort.
_GOVERNED = ("rbac", "ring", "switches", "author")
# Tools dont CHAQUE appel est trace nominativement : ecriture et execution.
# Mesure du 2026-08-17 : le journal du videur n'enregistre que `_resolve_ring`,
# c'est-a-dire l'identite qui se PRESENTE — jamais le tool DEMANDE. Impossible
# d'y lire qui exerce l'ecriture ou l'execution, donc impossible de durcir un
# ring sur donnees. On ne trace que ces quatre-la : les lectures (majoritaires)
# ne gonflent pas le journal.
_AUDITED_TOOLS = ("write", "run", "governed_edit", "set_mode")
_ORDER = ("rbac", "ring", "switches", "firewall", "author")
_MAX_ARG_CHARS = 4000  # borne la sérialisation des args pour le firewall


@dataclass
class Verdict:
    allow: bool
    name: str
    args: dict
    breakglass: bool = False
    reasons: list = field(default_factory=list)  # [(check, decision, detail)]

    def deny_reason(self) -> str:
        bad = [f"{c}:{d}" for (c, dec, d) in self.reasons if dec == "DENY"]
        return " ; ".join(bad) or "refusé"

    def to_dict(self) -> dict:
        return {"allow": self.allow, "name": self.name, "breakglass": self.breakglass,
                "reasons": self.reasons}


# ── Resolvers RÉELS (wrappent les modules existants, off-loop via to_thread) ──
async def _check_rbac(name, args, agent, ring, token):
    def _f():
        from nokido_agent.app.forge_rbac import get_rbac, TOOL_CAPABILITY_MAP
        entity = f"agt_{agent.lower()}" if agent != "HUB" else "wrk_laforge"
        cap = next((v for k, v in TOOL_CAPABILITY_MAP.items() if k in name.lower()), None)
        if not cap:
            return (True, "aucune capability requise")
        ok = bool(get_rbac().check(entity, cap, token=token))
        return (ok, f"cap={cap}")
    return await asyncio.to_thread(_f)


async def _check_ring(name, args, agent, ring, token):
    def _f():
        from nokido_agent.app.forge_mcp_registry import get_registry
        needed = get_registry()._get_ring_needed(name, args)
        return (int(ring) <= int(needed), f"ring {ring} <= requis {needed}")
    return await asyncio.to_thread(_f)


async def _check_switches(name, args, agent, ring, token):
    def _f():
        from nokido_agent.app.forge_access_switches import check_access
        resource = args.get("path", args.get("filepath", name)) if isinstance(args, dict) else name
        res, reason = check_access(agent, str(resource), name, ring)
        if res is False:
            return (False, f"switch DENY: {reason}")
        return (True, reason or "aucune règle")
    return await asyncio.to_thread(_f)


async def _check_firewall(name, args, agent, ring, token):
    def _f():
        from nokido_agent.app.forge_semantic_firewall import get_firewall
        payload = json.dumps(args, ensure_ascii=False, default=str)[:_MAX_ARG_CHARS]
        pf = get_firewall().pre_flight(payload, context=name, ring=int(ring), provider="tool")
        if getattr(pf, "injection", False):
            return (False, "injection détectée dans les args")
        return (True, "clean" + (" (dlp)" if getattr(pf, "dlp_triggered", False) else ""))
    return await asyncio.to_thread(_f)


async def _check_author(name, args, agent, ring, token):
    """AUTHOR-GUARD (gouverné, fail-CLOSED côté registre) : empêche un agent d'usurper
    l'identité d'un AUTRE agent dans un commit git. `agent` est résolu par le hub
    (resolve_identity) — non forgeable par la commande. Non-bypassable : tourne AVANT
    l'exécution, côté hub. Fail-OPEN sur bug interne (ne jamais bloquer un run légitime),
    DENY UNIQUEMENT sur usurpation positivement détectée."""
    def _f():
        try:
            if name not in ("run",):
                return (True, "n/a")
            import re as _re
            blob = " ".join([
                str(args.get("code") or ""),
                " ".join(args.get("commands") or []),
                str(args.get("script_args") or ""),
            ])
            low = blob.lower()
            if "git" not in low or "commit" not in low:
                return (True, "n/a")
            AGENTS = {"CLAUDE", "ANTIGRAVITY", "AGY", "GEMINI", "CODEX", "COPILOT",
                      "CLINE", "ROO", "SIXTH", "BRIDGE", "COPILOT_CLI", "CLAUDE_CLI"}
            me = str(agent or "").upper()
            claims = []
            for _m in _re.finditer(r'--author[=\s]+["\']?\s*([^"\'<\n]+)', blob):
                claims.append(_m.group(1))
            for _m in _re.finditer(r'--committer[=\s]+["\']?\s*([^"\'<\n]+)', blob):
                claims.append(_m.group(1))
            for _m in _re.finditer(r'GIT_(?:AUTHOR|COMMITTER)_NAME\s*=\s*["\']?\s*([^"\'\n&;|]+)', blob, _re.I):
                claims.append(_m.group(1))
            for _c in claims:
                who = _c.strip().split()[0].upper() if _c.strip() else ""
                if who in AGENTS and who != me:
                    return (False, "author-guard: '%s' ne peut pas signer un commit comme '%s' (usurpation d'identite)" % (me, who))
            return (True, "author ok")
        except Exception:
            return (True, "author-guard error (allow)")
    return await asyncio.to_thread(_f)


_DEFAULT_CHECKS = {"rbac": _check_rbac, "ring": _check_ring,
                   "switches": _check_switches, "firewall": _check_firewall,
                   "author": _check_author}


def _is_breakglass(token: str) -> bool:
    try:
        from nokido_agent.app.forge_rbac import is_breakglass
        return bool(is_breakglass(token))
    except Exception:  # noqa: BLE001
        return False


async def resolve(name: str, args: dict, agent: str, ring: int, token: str = "", *,
                  byte_process=None, checks: dict | None = None,
                  strict_firewall: bool = False, breakglass=None) -> Verdict:
    """Résout la gouvernance d'un appel tool EN PARALLÈLE, fail-closed.

    byte_process(name, args, agent) -> (name, args) : réécriture séquentielle AVANT
    (fail-open). checks : injection de resolvers (tests). strict_firewall : firewall
    devient gouverné (deny). breakglass : override pour tests, sinon is_breakglass(token).
    """
    # PRÉSENCE inter-CLI (la "triche") : chaque consultation du hub = un battement.
    # Qui appelle le gate est "dans la piece". Throttle 30s, best-effort, jamais bloquant.
    try:
        from nokido_agent.tools import forge_presence as _pres

        _pres.mark_seen(agent)
    except Exception:  # noqa: BLE001
        pass
    # 0. ByteRouter SÉQUENTIEL d'abord — il MUTE name/args, les checks en dépendent.
    if byte_process is not None:
        try:
            name, args = await byte_process(name, args, agent)
        except Exception:  # noqa: BLE001 - rewrite optionnel, fail-open
            pass

    bg = breakglass if breakglass is not None else _is_breakglass(token)
    checks = checks or _DEFAULT_CHECKS

    # 1. Resolvers INDÉPENDANTS en PARALLÈLE. return_exceptions -> on capture les throws.
    coros = [checks[k](name, args, agent, ring, token) for k in _ORDER]
    results = await asyncio.gather(*coros, return_exceptions=True)

    allow = True
    reasons: list = []
    for label, res in zip(_ORDER, results):
        governed = label in _GOVERNED or (label == "firewall" and strict_firewall)
        if isinstance(res, Exception):
            # FAIL-CLOSED : un check gouverné qui RAISE => DENY (faiblesse #1).
            if governed and not bg:
                allow = False
                reasons.append((label, "DENY", f"erreur check fail-closed: {type(res).__name__}: {res}"))
            else:
                reasons.append((label, "WARN", f"erreur check best-effort: {type(res).__name__}: {res}"))
            continue
        try:
            ok, detail = res
        except Exception:  # noqa: BLE001 - resolver mal formé -> fail-closed si gouverné
            if governed and not bg:
                allow = False
                reasons.append((label, "DENY", f"resolver malformé: {res!r}"))
            else:
                reasons.append((label, "WARN", f"resolver malformé: {res!r}"))
            continue
        if ok:
            reasons.append((label, "ALLOW", detail))
        elif governed and not bg:
            allow = False
            reasons.append((label, "DENY", detail))
        else:
            reasons.append((label, "WARN", detail))

    # 2. Break-glass : si master token a sauvé un deny gouverné -> AUDIT visible (#2).
    if bg and any(dec == "WARN" and lbl in _GOVERNED for (lbl, dec, _) in reasons):
        reasons.append(("breakglass", "OVERRIDE", "token master — denials gouvernés by-passés (AUDITÉ)"))

    if name in _AUDITED_TOOLS:
        try:
            from nokido_agent.app.forge_videur import capture as _vcap

            _ident = {"agent": agent, "ring": int(ring), "via": "hub_gate"}
            _extra = {
                "decision": "ALLOW" if allow else "DENY",
                "action": str(args.get("action", "")) if isinstance(args, dict) else "",
            }
            # `capture` = DPAPI + HMAC + ecriture disque, SYNCHRONE. Ce chemin est
            # l'event loop du hub : jamais d'I/O bloquante ici (cf. incidents du
            # 2026-08-15 et du 2026-08-17, watchdog os._exit).
            await asyncio.to_thread(_vcap, _ident, name, _extra)
        except Exception:  # muet-ok : une trace perdue ne bloque jamais un appel
            pass

    return Verdict(allow=allow, name=name, args=args, breakglass=bg, reasons=reasons)


# ─────────────────────────── SELFTEST (checks stubs) ───────────────────────────
def _selftest() -> int:
    def mk(ok=True, raise_exc=None):
        async def _c(name, args, agent, ring, token):
            if raise_exc:
                raise raise_exc
            return (ok, "stub")
        return _c

    allow_all = {k: mk(True) for k in _ORDER}
    cases = []

    # 1. tout passe -> allow
    cases.append(("tout-allow", dict(checks=allow_all), True))
    # 2. rbac DENY -> deny (gouverné)
    cases.append(("rbac-deny", dict(checks={**allow_all, "rbac": mk(False)}), False))
    # 3. rbac RAISE -> deny (FAIL-CLOSED, faiblesse #1)
    cases.append(("rbac-raise-failclosed", dict(checks={**allow_all, "rbac": mk(raise_exc=RuntimeError("boom"))}), False))
    # 4. firewall RAISE -> allow (best-effort warn)
    cases.append(("firewall-raise-besteffort", dict(checks={**allow_all, "firewall": mk(raise_exc=ValueError("x"))}), True))
    # 5. firewall DENY non-strict -> allow (warn)
    cases.append(("firewall-deny-nonstrict", dict(checks={**allow_all, "firewall": mk(False)}), True))
    # 6. firewall DENY strict -> deny (gouverné)
    cases.append(("firewall-deny-strict", dict(checks={**allow_all, "firewall": mk(False)}, strict_firewall=True), False))
    # 7. break-glass override un rbac deny -> allow (audité, faiblesse #2)
    cases.append(("breakglass-override", dict(checks={**allow_all, "rbac": mk(False)}, breakglass=True), True))
    # 8. ring DENY -> deny
    cases.append(("ring-deny", dict(checks={**allow_all, "ring": mk(False)}), False))

    ok = 0
    for label, kw, expected in cases:
        v = asyncio.run(resolve("some_tool", {"x": 1}, "CLAUDE", 3, "tok", **kw))
        good = v.allow == expected
        ok += good
        extra = " [OVERRIDE]" if v.breakglass and any(d == "OVERRIDE" for _, d, _ in v.reasons) else ""
        print(f"  [{'OK' if good else 'FAIL'}] {label}: allow={v.allow} (attendu {expected}){extra}")
    print(f"selftest: {ok}/{len(cases)} OK")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
