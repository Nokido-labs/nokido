#!/usr/bin/env python
# -*- coding: utf-8 -*-
# __FORGE_COLOR__ = "ssot-knowledge-uniform"
"""forge_ssot.py — Couche SSoT GÉNÉRIQUE pour TOUT savoir centralisé.

Problème (directive user 2026-06-17) : "point sur <X>" rend des réponses
DIFFÉRENTES selon le CLI (Claude/Gemini/local) — chacun re-dérive depuis sa
mémoire de session volatile au lieu de lire UNE source. Fix = forcer la lecture
d'un artefact central (SSoT) + contraindre la sortie à un SCHÉMA → la
"personnalité" du moteur d'inférence est écrasée → réponse uniforme cross-CLI.

Pourquoi un nouveau module (anti-dup, cf CLAUDE.md §3) — les briques existent
mais AUCUNE ne fait "consult(domain) + contrainte schéma arbitraire" :
  - forge_keeper_base = STOCKAGE seul (internalize/consult d'un KEEPERART_<name>,
    pas de schéma ni de contrainte de sortie).
  - forge_trajectory  = boucle valide/corrige mais FIGÉE au schéma `intent`
    (whitelist de 17 méthodes), pas un schéma de domaine arbitraire.
  - forge_agent_proxy = l'appel LLM, sans response_format natif.
Ce module les COMPOSE : registre domaine→{SSoT, schéma} + consult + enforce.
Domain-paramétré : roadmap = 1ère instance, extensible à memory/rules/canon/...

Logique (valable pour tout savoir centralisé) :
  consult_ssot(domain) →
    1. SSoT STRUCTURÉ présent (fichier docs/<domain>_state.json) → on le lit
       tel quel = déterministe, uniforme, ZÉRO LLM (le cas idéal).
    2. sinon → markdown du keeper (KEEPERART_<domain>) + le schéma du domaine,
       à contraindre côté appelant (forge_agent_proxy response_schema).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent

# ── Schémas par domaine ──────────────────────────────────────────────────
# "shape" compact {champ: type} — sert (a) au validateur minimal, (b) à prompter
# le LLM. Types : str|int|float|bool|list|object|any.
ROADMAP_SCHEMA: Dict[str, str] = {
    "schema_version": "int",
    "generated_ts": "int",
    "generated_by": "str",
    "system_state": "object",
    "current_milestone": "str",
    "next_milestone": "str",
    "blockers": "list",
    "roadmap": "object",
    "source": "str",
}

RULES_SCHEMA: Dict[str, str] = {
    "schema_version": "int", "generated_ts": "int", "generated_by": "str",
    "count": "int", "rules": "list", "source": "str",
}

MEMORY_SCHEMA: Dict[str, str] = {
    "schema_version": "int", "generated_ts": "int", "generated_by": "str",
    "count": "int", "recent": "list", "source": "str",
}

PROVIDERS_SCHEMA: Dict[str, str] = {
    "schema_version": "int", "generated_ts": "int", "generated_by": "str",
    "count": "int", "providers": "list", "source": "str",
}

SYSTEM_STATE_SCHEMA: Dict[str, str] = {
    "schema_version": "int", "generated_ts": "int", "generated_by": "str",
    "hub_version": "str", "master_up": "bool", "ports": "object",
    "services_degraded": "list", "source": "str",
}

# Registre extensible domaine → {file structuré, keeper markdown, schéma}.
# Ajouter un domaine = 1 entrée (+ son build_doc dans forge_ssot_maintainer).
DOMAINS: Dict[str, Dict[str, Any]] = {
    "roadmap": {
        "file": ROOT / "docs" / "roadmap_state.json",
        "keeper": "roadmap",
        "schema": ROADMAP_SCHEMA,
    },
    "rules": {
        "file": ROOT / "docs" / "rules_state.json",
        "keeper": "rules",
        "schema": RULES_SCHEMA,
    },
    "memory": {
        "file": ROOT / "docs" / "memory_state.json",
        "keeper": "memory",
        "schema": MEMORY_SCHEMA,
    },
    "providers": {
        "file": ROOT / "docs" / "providers_state.json",
        "keeper": "providers",
        "schema": PROVIDERS_SCHEMA,
    },
    "system_state": {
        "file": ROOT / "docs" / "system_state.json",
        "keeper": "system_state",
        "schema": SYSTEM_STATE_SCHEMA,
    },
}


def register_domain(domain: str, *, file: Optional[Path] = None,
                    keeper: Optional[str] = None,
                    schema: Optional[Dict[str, str]] = None) -> None:
    """Enregistre/MAJ un domaine de savoir centralisé (idempotent)."""
    d = DOMAINS.setdefault(domain, {})
    if file is not None:
        d["file"] = Path(file)
    if keeper is not None:
        d["keeper"] = keeper
    if schema is not None:
        d["schema"] = schema


_TYPE_OK: Dict[str, tuple] = {
    "str": (str,), "int": (int,), "float": (int, float), "bool": (bool,),
    "list": (list,), "object": (dict,), "any": (object,),
}


def enforce_schema(obj: Any, schema: Dict[str, str]) -> Dict[str, Any]:
    """Validation MINIMALE (sans dép jsonschema) : présence + type grossier.
    Ne lève jamais — retourne {ok, missing, wrong_type, coerced}. `coerced`
    remplit les champs manquants par un défaut neutre du type."""
    if not isinstance(obj, dict):
        return {"ok": False, "missing": list(schema), "wrong_type": [],
                "coerced": {k: _default(t) for k, t in schema.items()}}
    missing, wrong = [], []
    coerced = dict(obj)
    for field, typ in schema.items():
        if field not in obj:
            missing.append(field)
            coerced[field] = _default(typ)
            continue
        if not isinstance(obj[field], _TYPE_OK.get(typ, (object,))):
            wrong.append(field)
    return {"ok": not missing and not wrong, "missing": missing,
            "wrong_type": wrong, "coerced": coerced}


def _default(typ: str) -> Any:
    return {"str": "", "int": 0, "float": 0.0, "bool": False,
            "list": [], "object": {}, "any": None}.get(typ, None)


def consult_ssot(domain: str, query: str = "") -> Dict[str, Any]:
    """Lit le SSoT d'un domaine. Retour :
      {domain, kind: 'structured'|'markdown'|'absent', artifact, schema,
       generated_ts, stale_s, source}.
    'structured' = déjà uniforme (0 LLM). 'markdown' = à contraindre au schéma."""
    cfg = DOMAINS.get(domain)
    if not cfg:
        return {"domain": domain, "kind": "absent", "artifact": None,
                "schema": None, "error": f"domaine inconnu: {domain}"}
    schema = cfg.get("schema")

    # 1) SSoT STRUCTURÉ (fichier JSON) = déterministe, uniforme, prioritaire.
    f = cfg.get("file")
    if f and Path(f).exists():
        try:
            data = json.loads(Path(f).read_text(encoding="utf-8"))
            ts = int(data.get("generated_ts", 0) or 0)
            return {"domain": domain, "kind": "structured", "artifact": data,
                    "schema": schema, "generated_ts": ts,
                    "stale_s": (int(time.time()) - ts) if ts else None,
                    "source": str(f)}
        except Exception as exc:  # noqa: BLE001 - fichier corrompu -> fallback keeper
            _last = f"file KO: {type(exc).__name__}: {exc}"
    else:
        _last = "no structured file"

    # 2) Fallback markdown du keeper (KEEPERART_<domain>).
    keeper = cfg.get("keeper")
    md = None
    if keeper:
        try:
            from nokido_agent.app.forge_keeper_base import consult as _keeper_consult
            md = _keeper_consult(keeper, query=query, limit=1)
        except Exception as exc:  # noqa: BLE001
            _last = f"keeper KO: {type(exc).__name__}: {exc}"
    return {"domain": domain, "kind": "markdown" if md else "absent",
            "artifact": md, "schema": schema, "generated_ts": None,
            "stale_s": None, "source": f"KEEPERART_{keeper}" if keeper else None,
            "note": _last}


def answer_uniform(domain: str, llm_call_fn: Optional[Callable[[str], str]] = None,
                   query: str = "") -> Dict[str, Any]:
    """Réponse UNIFORME cross-CLI à "point sur <domain>".
      - SSoT structuré présent  → on le retourne tel quel (0 LLM, déterministe).
      - sinon + llm_call_fn      → on contraint le markdown au schéma via le LLM.
      - sinon                    → squelette du schéma (jamais d'invention)."""
    c = consult_ssot(domain, query=query)
    schema = c.get("schema") or {}
    if c["kind"] == "structured":
        return c["artifact"]
    if c["kind"] == "markdown" and llm_call_fn and schema:
        prompt = _schema_prompt(schema, c["artifact"])
        try:
            raw = llm_call_fn(prompt)
            i, j = raw.find("{"), raw.rfind("}")
            obj = json.loads(raw[i:j + 1]) if i >= 0 and j > i else {}
        except Exception:  # noqa: BLE001
            obj = {}
        return enforce_schema(obj, schema)["coerced"]
    return enforce_schema({}, schema)["coerced"]


def _schema_prompt(schema: Dict[str, str], context: Any) -> str:
    shape = ", ".join(f'"{k}": <{t}>' for k, t in schema.items())
    return ("Réponds en JSON STRICT (et RIEN d'autre), schéma EXACT : {"
            + shape + "}\n\nSource (SSoT) :\n" + str(context)[:6000])


# Synonymes par domaine pour détecter "point sur <domain>" en langage naturel.
# Le nom du domaine est toujours reconnu ; ces alias couvrent les formulations FR.
_DOMAIN_SYNONYMS: Dict[str, tuple] = {
    "roadmap": ("roadmap", "feuille de route", "statut du projet", "où en est",
                "ou en est", "vue d'ensemble", "point projet", "état du projet"),
    "rules": ("règle", "regle", "règles", "regles", "architecture_rules", "loi ",
              "conscience", "canon", "directive"),
    "memory": ("mémoire", "memoire", "leçon", "lecon", "leçons", "lessons",
               "souvenir", "ce qu'on a appris", "retour d'expérience"),
    "providers": ("provider", "providers", "endpoint", "endpoints", "modèles dispo",
                  "modeles dispo", "llm dispo", "backends", "fournisseurs"),
    "system_state": ("état système", "etat systeme", "system state", "santé du hub",
                     "sante du hub", "état du hub", "etat du hub", "ports", "services up"),
}


def detect_domain(query: str) -> Optional[str]:
    """Détecte le domaine SSoT visé par une requête "point sur <X>" (None sinon)."""
    q = (query or "").lower()
    for d in DOMAINS:               # nom de domaine explicite d'abord
        if d in q:
            return d
    for d, syns in _DOMAIN_SYNONYMS.items():
        if d in DOMAINS and any(s in q for s in syns):
            return d
    return None


def point(query: str, llm_call_fn: Optional[Callable[[str], str]] = None) -> Optional[Dict[str, Any]]:
    """Entrée 1-APPEL pour "point sur <domain>" : détecte le domaine → réponse SSoT
    UNIFORME (structuré déterministe, ou markdown contraint au schéma). None si la
    requête ne cible aucun domaine SSoT connu (l'appelant retombe sur son flux normal)."""
    d = detect_domain(query)
    if not d:
        return None
    c = consult_ssot(d)
    return {"domain": d, "kind": c.get("kind"), "source": c.get("source"),
            "stale_s": c.get("stale_s"),
            "answer": answer_uniform(d, llm_call_fn=llm_call_fn, query=query)}


def list_domains() -> Dict[str, Dict[str, Any]]:
    """Inventaire des domaines de savoir centralisé enregistrés."""
    out = {}
    for name, cfg in DOMAINS.items():
        f = cfg.get("file")
        out[name] = {"has_structured_file": bool(f and Path(f).exists()),
                     "file": str(f) if f else None,
                     "keeper": cfg.get("keeper"),
                     "schema_fields": list((cfg.get("schema") or {}).keys())}
    return out


def _selftest() -> int:
    assert enforce_schema({"a": 1}, {"a": "int", "b": "str"})["missing"] == ["b"]
    assert enforce_schema({"a": "x"}, {"a": "int"})["wrong_type"] == ["a"]
    inv = list_domains()
    assert "roadmap" in inv
    c = consult_ssot("roadmap")
    print("[selftest] consult_ssot(roadmap) kind=", c["kind"], "stale_s=", c.get("stale_s"))
    print("[selftest] domains=", json.dumps(inv, ensure_ascii=False))
    print("[selftest] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
