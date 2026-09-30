# -*- coding: utf-8 -*-
from __future__ import annotations
from nokido_agent.app.forge_secrets import get_secret

"""
__FORGE_COLOR__ : metabolisme LLM / gouvernance (primitive interne)

PRIMITIVE : SAMPLING INTERNE — un organe demande une completion SANS detenir de cle.

Item 5 du pack P2 des veilles (spec_pack_veilles_p2) : les organes internes
(digest, triage, resume, classification) n'ont pas de cle LLM et ne doivent PAS en
avoir — distribuer des cles a chaque module, c'est multiplier les surfaces de fuite
et rendre le cout intracable. Ils passent par ici.

Ce module n'est PAS un routeur : `forge_llm_router.router_call` fait deja la cascade
multi-providers, les quotas et les circuit-breakers. Ce qui manquait, c'est la
POLITIQUE d'acces pour les organes :

  1. LOCAL D'ABORD, et par defaut LOCAL SEULEMENT. Un organe de fond qui tourne a
     chaque tick ne doit pas bruler du quota cloud a l'insu de tout le monde.
     `allow_cloud=True` est un choix EXPLICITE de l'appelant.
  2. GARDE BUDGET. Meme autorise, le cloud est refuse quand le gouverneur budgetaire
     signale la pression (CORTISOL_QUOTA_CLOUD) — l'organe econome existe deja, on
     le CONSULTE au lieu de le contourner.
  3. TRACABILITE. Chaque appel porte un `purpose` : sans lui, on constate une facture
     sans savoir quel organe l'a creusee.

Retourne None plutot que de lever : un organe de fond ne doit pas mourir parce que
le LLM est indisponible. `None` se lit « pas de reponse », jamais « reponse vide ».

CLI :
    LAFORGE_PYTHON app/forge_internal_sampling.py --prompt "resume: ..." --purpose test
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
_TRACE = ROOT / "sandbox" / "internal_sampling.jsonl"
_TRACE_KEEP = 500

DEFAULT_MAX_TOKENS = int(get_secret("LAFORGE_INTERNAL_SAMPLE_MAX_TOKENS") or "512")


def _budget_pressure() -> bool:
    """Le gouverneur budgetaire signale-t-il une pression cloud ?

    On DEMANDE a l'organe (forge_endocrine / econome) au lieu de re-deriver un
    budget ici. Indisponible -> False : on ne bloque pas sur un capteur muet, mais
    le local reste le defaut de toute facon.
    """
    try:
        app_dir = str(ROOT / "app")
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        from nokido_agent.app import forge_endocrine as fe

        r = fe.read("CORTISOL_QUOTA_CLOUD")
        lvl = getattr(r, "level", r)
        lvl = lvl.get("level") if isinstance(lvl, dict) else lvl
        return isinstance(lvl, (int, float)) and float(lvl) >= 0.5
    except Exception:  # noqa: BLE001
        return False


def _trace(purpose: str, ok: bool, local: bool, ms: float, chars: int) -> None:
    """Journal borne : qui a demande quoi, et ce que ca a coute."""
    try:
        _TRACE.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if _TRACE.exists():
            lines = _TRACE.read_text(encoding="utf-8", errors="replace").splitlines()[-(_TRACE_KEEP - 1):]
        lines.append(json.dumps({"ts": time.time(), "purpose": purpose[:60], "ok": ok,
                                 "local": local, "ms": round(ms, 1), "chars": chars}))
        _TRACE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def sample(prompt: str, purpose: str = "unspecified", max_tokens: int | None = None,
           allow_cloud: bool = False, system: str | None = None,
           use_case: str = "fast", timeout: float = 60.0) -> str | None:
    """Demande une completion pour un organe interne.

    Args:
        prompt      : la requete.
        purpose     : QUI demande et pourquoi (obligatoire en pratique — c'est ce
                      qui rend la consommation attribuable).
        allow_cloud : False (defaut) = local STRICT. True = cloud autorise, mais
                      encore soumis au garde budgetaire.

    Returns:
        Le texte, ou None si indisponible/refuse. Jamais d'exception.
    """
    if not (prompt or "").strip():
        return None
    t0 = time.perf_counter()

    go_cloud = bool(allow_cloud) and not _budget_pressure()
    force_local = not go_cloud

    try:
        app_dir = str(ROOT / "app")
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        from nokido_agent.app.forge_llm_router import router_call

        # Chemin INSTRUMENTE mais pas encore CLASSE : UNKNOWN, jamais une valeur
        # permissive inventee (cf. app/forge_share_policy).
        from nokido_agent.app.forge_share_policy import contexte_legacy as _ctx_legacy

        res = router_call(
            prompt,
            use_case=use_case,
            context=_ctx_legacy(provenance="forge_internal_sampling.sample"),
            max_tokens=int(max_tokens or DEFAULT_MAX_TOKENS),
            system=system,
            timeout=timeout,
            force_local=force_local,
        )
    except Exception:  # noqa: BLE001
        _trace(purpose, False, force_local, (time.perf_counter() - t0) * 1000, 0)
        return None

    text = res if isinstance(res, str) else (res or {}).get("text") if isinstance(res, dict) else None
    text = (text or "").strip() or None
    _trace(purpose, text is not None, force_local,
           (time.perf_counter() - t0) * 1000, len(text or ""))
    return text


def usage(limit: int = 50) -> list[dict]:
    """Derniers appels tracés — pour savoir quel organe consomme."""
    try:
        if not _TRACE.exists():
            return []
        out = []
        for line in _TRACE.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception:  # noqa: BLE001
        return []


def _main() -> int:
    ap = argparse.ArgumentParser(description="Sampling interne pour organes sans cle")
    ap.add_argument("--prompt")
    ap.add_argument("--purpose", default="cli")
    ap.add_argument("--allow-cloud", action="store_true")
    ap.add_argument("--usage", action="store_true")
    a = ap.parse_args()
    if a.usage or not a.prompt:
        print(json.dumps(usage(), indent=2, ensure_ascii=False))
        return 0
    r = sample(a.prompt, purpose=a.purpose, allow_cloud=a.allow_cloud)
    print(r if r is not None else "(aucune reponse)")
    return 0 if r else 1


if __name__ == "__main__":
    sys.exit(_main())
