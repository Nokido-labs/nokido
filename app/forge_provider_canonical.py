"""
FORGE INTELLIGENCE — forge_provider_canonical [GREEN]
======================================================
SOURCE DE VÉRITÉ unique des providers LLM (Option B, tranchée par multiplan
souverain 2026-06-09, B_module unanime). Réconcilie les 4 registres divergents
(forge_agent_proxy._PROVIDERS, forge_llm_router.PROVIDERS, forge_provider_admin
.PROVIDER_VAULT_KEY, forge_provider_specs.PROVIDER_SPECS).

Dérive {name, model, api_key_env, cost_tier, display_name, tier, context,
capabilities} de :
  - forge_agent_proxy._PROVIDERS  -> CANONIQUE pour name / api_key_env / model
  - forge_provider_specs.PROVIDER_SPECS -> enrichissement tier/context/capabilities

ÉTAPE 1 de la migration (ce module est ADDITIF — ne modifie PAS encore les 3 autres
registres). Étapes suivantes : admin + router consommeront `vault_key_for()` /
`all_providers()` au lieu de leurs dicts manuels. Build LAZY (pas d'import lourd /
circulaire au load).
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(_ROOT))

_CANON: Optional[dict] = None


def _build() -> dict:
    """Construit la table canonique depuis _PROVIDERS (+ specs). Tolérant aux absents."""
    try:
        from nokido_agent.app.forge_agent_proxy import _PROVIDERS, _init_registry
        if not _PROVIDERS:
            _init_registry()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"forge_provider_canonical: _PROVIDERS indisponible: {e}")
    try:
        from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS
    except Exception:
        PROVIDER_SPECS = {}

    canon: dict[str, dict] = {}
    for name, p in _PROVIDERS.items():
        spec = PROVIDER_SPECS.get(name, {}) if isinstance(PROVIDER_SPECS, dict) else {}
        canon[name] = {
            "name": name,
            "model": getattr(p, "model", "?"),
            "api_key_env": getattr(p, "api_key_env", None),
            "cost_tier": getattr(p, "cost_tier", 1),
            "display_name": getattr(p, "display_name", name),
            "tier": spec.get("tier"),
            "context": spec.get("context"),
            "capabilities": spec.get("capabilities", []),
        }
    return canon


def all_providers(refresh: bool = False) -> dict:
    """Table canonique {name -> meta}. Cache (refresh=True pour reconstruire)."""
    global _CANON
    if _CANON is None or refresh:
        _CANON = _build()
    return _CANON


def provider(name: str) -> Optional[dict]:
    return all_providers().get(name)


def vault_key_for(name: str) -> Optional[str]:
    """Nom de clé vault canonique pour un provider (remplace PROVIDER_VAULT_KEY manuel)."""
    p = all_providers().get(name)
    return p["api_key_env"] if p else None


def vault_key_map() -> dict[str, Optional[str]]:
    """{name -> api_key_env} — pour auto-générer forge_provider_admin.PROVIDER_VAULT_KEY."""
    return {n: c["api_key_env"] for n, c in all_providers().items()}


def providers_by_vault_key() -> dict[str, list[str]]:
    """{vault_key -> [providers qui l'utilisent]} — détecte le partage de clé (openrouter)."""
    out: dict[str, list[str]] = {}
    for n, c in all_providers().items():
        k = c["api_key_env"]
        if k:
            out.setdefault(k, []).append(n)
    return out


def audit_consistency() -> dict:
    """Détecte les key-names malformés (dot/url) restants + providers sans clé."""
    bad_keyname, no_key = [], []
    for n, c in all_providers().items():
        k = c["api_key_env"]
        if k is None:
            no_key.append(n)
        elif "." in k or "/" in k or "@" in k or k != k.strip():
            bad_keyname.append((n, k))
    return {"total": len(all_providers()), "malformed_key_names": bad_keyname,
            "no_key (locaux/oauth attendus)": no_key}


def _selftest() -> int:
    canon = all_providers()
    print(f"[canonical] {len(canon)} providers dérivés de _PROVIDERS (+specs)")
    aud = audit_consistency()
    print(f"[canonical] malformed_key_names = {aud['malformed_key_names'] or 'AUCUN'}")
    # vérifie les fixes 2026-06-09
    checks = {"sambanova": "SAMBANOVA_API_KEY", "nvidia_nim": "NVIDIA_API_KEY"}
    ok = True
    for n, expect in checks.items():
        got = vault_key_for(n)
        flag = "OK" if got == expect else "FAIL"
        ok = ok and flag == "OK"
        print(f"  [{flag}] {n} -> {got} (attendu {expect})")
    # partage de clé openrouter
    shared = {k: v for k, v in providers_by_vault_key().items() if len(v) > 1}
    print(f"[canonical] clés partagées : {shared}")
    return 0 if (ok and not aud["malformed_key_names"]) else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
