"""
FORGE INTELLIGENCE — forge_reconcile_test [GREEN]
===================================================
Step 5 de la réconciliation registres providers (Option B). Valide que les
steps 1-4 NE CASSENT PAS ask()/call_cascade/api-providers + cohérence des 3
registres (forge_llm_router / forge_provider_admin / forge_agent_proxy) via la
source de vérité forge_provider_canonical. Fresh-process = teste le code édité
sur disque (= ce que le reboot chargera). Sans réseau (déterministe).
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _s in ("app", "tools"):
    _p = str(ROOT / _s)
    if _p not in sys.path:
        sys.path.insert(0, _p)

_RESULTS: list[tuple[str, bool, str]] = []


def _check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"EXC {type(e).__name__}: {str(e)[:140]}"
    _RESULTS.append((name, bool(ok), detail))


def t_imports():
    from nokido_agent.app import forge_llm_router  # noqa: F401
    from nokido_agent.app import forge_provider_admin  # noqa: F401
    from nokido_agent.app import forge_provider_canonical  # noqa: F401
    from nokido_agent.app import forge_remediation  # noqa: F401
    from nokido_agent.app import forge_agent_proxy  # noqa: F401
    from nokido_agent.app import forge_autonomous_loops  # noqa: F401
    return True, "6 modules importés sans erreur"


def t_router_no_phantom():
    from nokido_agent.app.forge_llm_router import PROVIDERS, USE_CASE_CHAINS
    ph = sorted({p for ch in USE_CASE_CHAINS.values() for p in ch if p not in PROVIDERS})
    return (not ph), f"phantoms={ph or 'AUCUN'} | providers={len(PROVIDERS)} chains={len(USE_CASE_CHAINS)}"


def t_router_status():
    from nokido_agent.app.forge_llm_router import router_status
    st = router_status()
    return isinstance(st, dict) and bool(st), f"router_status keys={list(st)[:4] if isinstance(st, dict) else type(st)}"


def t_admin_canonical_merge():
    from nokido_agent.app import forge_provider_admin as a
    need = ["deepseek", "glm5", "kimi", "sambanova", "nvidia_nim"]
    miss = [k for k in need if not a.PROVIDER_VAULT_KEY.get(k)]
    return (not miss), f"vault_keys={len(a.PROVIDER_VAULT_KEY)} missing={miss or 'AUCUN'}"


def t_admin_resolve():
    from nokido_agent.app.forge_provider_admin import _resolve_vault_key
    return _resolve_vault_key("sambanova") == "SAMBANOVA_API_KEY", \
        f"_resolve_vault_key(sambanova)={_resolve_vault_key('sambanova')}"


def t_canonical_clean():
    from nokido_agent.app import forge_provider_canonical as c
    aud = c.audit_consistency()
    return (not aud["malformed_key_names"]), \
        f"providers={aud['total']} malformed={aud['malformed_key_names'] or 'AUCUN'}"


def t_agent_proxy_keyfix():
    from nokido_agent.app.forge_agent_proxy import _PROVIDERS, _init_registry
    if not _PROVIDERS:
        _init_registry()
    sn = _PROVIDERS.get("sambanova")
    nv = _PROVIDERS.get("nvidia_nim")
    ok = (sn and sn.api_key_env == "SAMBANOVA_API_KEY" and nv and nv.api_key_env == "NVIDIA_API_KEY")
    return ok, f"sambanova={getattr(sn, 'api_key_env', None)} nvidia_nim={getattr(nv, 'api_key_env', None)}"


def t_remediation_phantom_cleared():
    from nokido_agent.app.forge_remediation import run_remediation_cycle
    r = run_remediation_cycle(armed=False)
    ph = r["debts"]["phantom_slots"].get("phantoms", ["?"])
    return (ph == []), f"phantom_slots={ph} signals={r['signals_emitted']} elapsed={r['elapsed_s']}s"


def t_pat_remediation_defined():
    from nokido_agent.app import forge_autonomous_loops as al
    return hasattr(al, "pat_remediation"), f"pat_remediation defined={hasattr(al, 'pat_remediation')}"


def main() -> int:
    for name, fn in [
        ("imports", t_imports),
        ("router_no_phantom", t_router_no_phantom),
        ("router_status", t_router_status),
        ("admin_canonical_merge", t_admin_canonical_merge),
        ("admin_resolve", t_admin_resolve),
        ("canonical_clean", t_canonical_clean),
        ("agent_proxy_keyfix", t_agent_proxy_keyfix),
        ("remediation_phantom_cleared", t_remediation_phantom_cleared),
        ("pat_remediation_defined", t_pat_remediation_defined),
    ]:
        _check(name, fn)
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    print(f"=== STEP 5 — TESTS RÉCONCILIATION : {passed}/{len(_RESULTS)} PASS ===")
    for name, ok, detail in _RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return 0 if passed == len(_RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
