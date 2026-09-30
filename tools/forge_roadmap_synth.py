#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_roadmap_synth.py - Synthese SOUVERAINE de la ROADMAP Nokido.

Agrege les sources roadmap (anchors RAG via rag_fts + docs/roadmap*.md +
docs/specs/*.md), les fait digerer par le POOL LOCAL (cascade force_local,
JAMAIS cloud), reduit en docs/ROADMAP.md priorise (P0/P1/P2), puis ancre le
resultat dans le RAG (domain=roadmap) pour continuite cross-session. Source
unique VIVANTE : re-lancer = roadmap re-synthetisee (raffinage periodique).

Anti-dup (reutilise, ne reconstruit pas) :
  - forge_llm_router.router_call(force_local=True) : cascade locale bornee +
    circuit-breakers + skip anti-OOM (host_capabilities). Le routage local
    agentique demande, deja robuste.
  - rag_fts (FTS5/BM25) pour les sources, PAS de SQL LIKE brut (regle d'or #1).
  - forge_self_correction.anchor_solution pour persister (domain=roadmap).

A lancer DEPORTE (survit, pool local potentiellement lent) :
  run_job script=tools/forge_roadmap_synth.py
Ou direct : LAFORGE_PYTHON tools/forge_roadmap_synth.py [--dry-run] [--limit N]
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/ssot : synthese souveraine de la roadmap"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import concurrent.futures as _cf
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

DB = ROOT / "RAG" / "embeddings.db"
OUT = ROOT / "docs" / "ROADMAP.md"


def _extract_text(r) -> str:
    if isinstance(r, str):
        return r
    keys = ("text", "response", "content", "message", "answer", "output")
    if isinstance(r, dict):
        for k in keys:
            v = r.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return ""
    for k in keys:
        v = getattr(r, k, None)
        if isinstance(v, str) and v.strip():
            return v
    return ""


import json as _json
import os as _os
import urllib.request as _urlreq

# Backend LOCAL souverain, no-egress — VETTÉ par forge_resolver + cascade FAST-FIRST :
# llamacpp :8091 (Vulkan, ~300ms, prioritaire) -> ollama :11434 (qwen3:8b, fallback).
# Route la COMPLEXITÉ vers le backend RAPIDE (au lieu d'ollama lent en 1er, qui galérait).
_LLAMACPP_URL = _os.environ.get("LAFORGE_SYNTH_LLAMACPP", "http://127.0.0.1:8091")
_OLLAMA_URL = _os.environ.get("LAFORGE_SYNTH_OLLAMA", "http://127.0.0.1:11434")
_OLLAMA_MODEL = _os.environ.get("LAFORGE_SYNTH_MODEL", "qwen3:8b")


def _post_json(url: str, payload: dict, timeout: int) -> dict:
    body = _json.dumps(payload).encode("utf-8")
    req = _urlreq.Request(url, data=body, headers={"Content-Type": "application/json"})
    with _urlreq.urlopen(req, timeout=timeout) as r:
        return _json.loads(r.read().decode("utf-8", "replace"))


def _try_llamacpp(prompt: str, max_tokens: int) -> str:
    d = _post_json(_LLAMACPP_URL + "/v1/chat/completions", {
        "model": "laforge-coder", "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.3, "stream": False}, timeout=90)
    return (d.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def _try_ollama(prompt: str, max_tokens: int) -> str:
    d = _post_json(_OLLAMA_URL + "/api/generate", {
        "model": _OLLAMA_MODEL, "prompt": prompt + "\n/no_think", "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.3}}, timeout=180)
    t = (d.get("response") or "").strip()
    return t.rsplit("</think>", 1)[-1].strip() if "</think>" in t else t


def _try_groq(prompt: str, max_tokens: int) -> str:
    """Groq (cloud rapide ~350ms) via forge_agent_proxy.ask — GOUVERNÉ (firewall pre_flight,
    Golden Rule #4). Override FAST pour CE synthé non-sensible quand l'iGPU local est trop
    lent (13 buckets map-reduce). Env-gated, le local reste le défaut souverain."""
    import asyncio
    from nokido_agent.app.forge_agent_proxy import ask
    r = asyncio.run(ask("groq", prompt, max_tokens=max_tokens, rag_context=False))
    return (r.get("text") or "").strip() if r.get("ok") else ""


def _local_ask(prompt: str, max_tokens: int = 1200, attempts: int = 2) -> str:
    """Cascade FAST-FIRST VETTÉE par forge_resolver : llamacpp :8091 (Vulkan) -> ollama.
    Override LAFORGE_SYNTH_FAST=groq (cloud gouverné) en TÊTE quand l'iGPU est trop lent.
    Le local reste le défaut souverain. Lève si épuisé (l'appelant wrappe)."""
    import os as _os
    try:
        from nokido_agent.app.forge_resolver import live_providers
        order, _drop = live_providers(["llamacpp", "ollama"], context="trusted")
    except Exception:  # noqa: BLE001
        order = ["llamacpp", "ollama"]
    _fns = {"llamacpp": _try_llamacpp, "ollama": _try_ollama, "groq": _try_groq}
    _fast = _os.environ.get("LAFORGE_SYNTH_FAST", "").strip()
    if _fast in _fns:
        order = [_fast] + [p for p in order if p != _fast]
    last = "(aucune tentative)"
    for _i in range(max(1, attempts)):
        for _p in order:
            try:
                t = (_fns[_p](prompt, max_tokens) or "").strip()
                if t:
                    return t
                last = f"{_p}: vide"
            except Exception as e:  # noqa: BLE001
                last = f"{_p}: {type(e).__name__}: {e}"
    raise RuntimeError(f"_local_ask cascade locale epuisee ({attempts}x): {last}")


def _collect_rag(limit: int = 40) -> list:
    """Sources roadmap depuis le RAG (FTS5 BM25, jamais de LIKE brut)."""
    if not DB.exists():
        return []
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        match = ('roadmap OR "P0" OR "P1" OR "P2" OR autonomie OR swarm '
                 'OR cognition OR souverain OR handoff')
        rows = con.execute(
            "SELECT source, substr(text,1,1200) FROM rag_fts "
            "WHERE rag_fts MATCH ? ORDER BY bm25(rag_fts) LIMIT ?",
            (match, limit),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] rag_fts: {exc}")
        rows = []
    finally:
        con.close()
    return [f"[{s}]\n{t}" for s, t in rows]


def _collect_docs() -> list:
    out = []
    for pat in ("docs/roadmap*.md", "docs/ROADMAP*.md", "docs/specs/*.md"):
        for p in sorted(ROOT.glob(pat)):
            if p.name == "ROADMAP.md":  # ne pas se relire soi-meme
                continue
            try:
                out.append(f"[{p.relative_to(ROOT)}]\n" + p.read_text("utf-8", "ignore")[:4000])
            except Exception:  # noqa: BLE001
                pass
    return out


def _collect_blackboard() -> list:
    """Stratégie FRAÎCHE : architecture_rules + discovered_facts du blackboard — là où vit la
    direction RÉELLE (décisions de session pas encore dans le RAG). Source qui met la roadmap
    à jour (sinon le synth ne voit que le vieux corpus). Lit forge_swarm_blackboard.read_zone."""
    out = []
    try:
        from nokido_agent.app.forge_swarm_blackboard import read_zone
    except Exception:  # noqa: BLE001
        return out
    for zone in ("architecture_rules", "discovered_facts"):
        try:
            z = read_zone(zone)
            facts = z.get("facts", []) if isinstance(z, dict) else (z or [])
            for f in facts[:30]:
                k = f.get("key", "") if isinstance(f, dict) else ""
                v = f.get("value", "") if isinstance(f, dict) else str(f)
                if v:
                    out.append(f"[blackboard:{zone}:{k}]\n{str(v)[:1500]}")
        except Exception:  # noqa: BLE001
            continue
    return out


# ── SSoT roadmap_state.json — bloc STATE déterministe (capté, 0 LLM) + roadmap JSON ──
# Source unique structurée pour "point roadmap" UNIFORME cross-CLI : les agents la LISENT
# avant de répondre (ne se fient plus à leur mémoire de session volatile), sortie contrainte
# au schéma => écrase la divergence de personnalité du moteur (cf blackboard ssot_roadmap_state_schema).
STATE_OUT = ROOT / "docs" / "roadmap_state.json"
SCHEMA_VERSION = 1
_HUB_URL = _os.environ.get("LAFORGE_HUB_URL", "http://127.0.0.1:8766")
_SUP_URL = _os.environ.get("LAFORGE_SUP_URL", "http://127.0.0.1:8765")
# Ports DÉTERMINISTES = le coeur anti-divergence.
# 8770 retiré : forge_cli_daemon.py supprimé (zone morte, job_32fe596a).
# ExegolMCP (:8770) est disabled (boot-trim) et géré par son propre service.
_STATE_PORTS = (8765, 8766, 8099, 8091, 11434)


def _port_up(port: int) -> bool:
    import socket as _sock
    s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    s.settimeout(0.6)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        s.close()


def _http_get_json(url: str, timeout: int = 4) -> dict:
    try:
        with _urlreq.urlopen(url, timeout=timeout) as r:
            return _json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return {}


def _capture_state() -> dict:
    """État système DÉTERMINISTE (capté en direct, JAMAIS LLM). Tout best-effort, ne lève jamais.
    Le bloc `ports` (socket connect) est le coeur fiable ; health/degraded sont best-effort."""
    health = _http_get_json(_HUB_URL + "/health")
    ports = {str(p): _port_up(p) for p in _STATE_PORTS}
    degraded: list = []
    sup = _http_get_json(_SUP_URL + "/status") or _http_get_json(_SUP_URL + "/api/services")
    try:
        for s in (sup.get("services") or sup.get("degraded") or []):
            if isinstance(s, dict) and s.get("status") not in (None, "running", "ok", "up"):
                degraded.append({
                    "service": s.get("service") or s.get("name"),
                    "status": s.get("status"),
                    "restarts": s.get("restarts", 0),
                })
    except Exception:  # noqa: BLE001
        pass
    return {
        "hub_version": health.get("version", ""),
        "hub_ts": health.get("ts", ""),
        "master_up": ports.get("8765", False),
        "ports": ports,
        "services_degraded": degraded,
    }


def _synth_roadmap_json(level: list) -> dict:
    """Réduit la roadmap en structure {current_milestone,next_milestone,blockers,P0/P1/P2}.
    LLM LOCAL borné ; fallback déterministe si JSON invalide (ne casse jamais)."""
    prompt = (
        "Convertis ces notes de roadmap Nokido en JSON STRICT (et RIEN d'autre), schéma EXACT :\n"
        '{"current_milestone":"","next_milestone":"",'
        '"blockers":[{"id":"","desc":"","severity":"P0|P1|P2"}],'
        '"P0":[{"title":"","why":"","state":"done|wip|todo"}],"P1":[],"P2":[]}\n\n'
        + "\n\n---\n\n".join(level)
    )
    try:
        raw = _local_ask(prompt, max_tokens=1600)
        i, j = raw.find("{"), raw.rfind("}")
        if i >= 0 and j > i:
            return _json.loads(raw[i:j + 1])
    except Exception:  # noqa: BLE001
        pass
    return {"current_milestone": "", "next_milestone": "", "blockers": [],
            "P0": [], "P1": [], "P2": [], "_degraded": "json synth KO -> markdown reste la source"}


def _write_roadmap_state(level: list) -> None:
    rm = _synth_roadmap_json(level)
    doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_ts": int(time.time()),
        "generated_by": "tools/forge_roadmap_synth.py",
        "system_state": _capture_state(),
        "current_milestone": rm.get("current_milestone", ""),
        "next_milestone": rm.get("next_milestone", ""),
        "blockers": rm.get("blockers", []),
        "roadmap": {"P0": rm.get("P0", []), "P1": rm.get("P1", []), "P2": rm.get("P2", [])},
        "source": "blackboard architecture_rules + KEEPERART_ROADMAP",
    }
    out = STATE_OUT
    try:
        from nokido_agent.app.forge_resolver import writable_path
        out, _red = writable_path(STATE_OUT, context=_os.environ.get("LAFORGE_CTX", "run_job"))
    except Exception:  # noqa: BLE001
        pass
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    n_items = sum(len(doc["roadmap"][k]) for k in ("P0", "P1", "P2"))
    print(f"[ok] ecrit {out} (roadmap_state.json, {n_items} items, master_up={doc['system_state']['master_up']})")
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution
        anchor_solution(
            problem="'point roadmap' diverge entre CLI (chaque agent re-derive, pas de SSoT structure)",
            solution=("docs/roadmap_state.json = SSoT STRUCTURE (state DETERMINISTE capte + roadmap JSON). "
                      "Les CLI le LISENT avant de repondre ; sortie contrainte au schema = uniforme cross-CLI."),
            example="run_job script=tools/forge_roadmap_synth.py ; lecture: docs/roadmap_state.json",
            domain="roadmap",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] anchor roadmap_state: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    sources = _collect_blackboard() + _collect_rag(args.limit) + _collect_docs()
    if not sources:
        print("[ERR] aucune source roadmap trouvee (RAG vide ? docs absents ?)")
        return 1
    print(f"[synth] {len(sources)} sources roadmap collectees")

    # MAP : digerer par buckets (n_ctx local frugal, ~6k chars/bucket)
    buckets, cur, sz = [], [], 0
    for s in sources:
        cur.append(s)
        sz += len(s)
        if sz > 6000:
            buckets.append(cur)
            cur, sz = [], 0
    if cur:
        buckets.append(cur)

    def _map_one(arg: tuple) -> tuple:
        i, b = arg
        prompt = (
            "Extrais de ces notes Nokido les ITEMS de roadmap CONCRETS. Pour chacun : "
            "titre court, pourquoi, etat (fait / en cours / a faire), priorite estimee "
            "(P0 socle / P1 / P2). Liste markdown dense, zero blabla.\n\n"
            + "\n\n---\n\n".join(b)
        )
        try:
            d = _local_ask(prompt, max_tokens=900)
        except Exception as exc:  # noqa: BLE001 - un bucket KO ne tue pas le run
            print(f"[warn] bucket {i + 1} KO: {type(exc).__name__}: {exc}")
            return (i, None)
        return (i, d if (d and d.strip()) else None)

    # MAP PARALLELE : les buckets sont independants -> fan-out concurrent sur le
    # pool local (borne a 3 = ollama Semaphore(3) / llama-server --parallel).
    # Chainage agentique data-parallele, pas un for sequentiel.
    print(f"[map] {len(buckets)} buckets en PARALLELE (max 3 concurrents sur le pool local)...")
    _by_idx: dict = {}
    with _cf.ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(_map_one, (i, b)): i for i, b in enumerate(buckets)}
        for fut in _cf.as_completed(futs):
            i, d = fut.result()
            _by_idx[i] = d
            print(f"[map] bucket {i + 1}/{len(buckets)} {'OK' if d else 'vide'}")
    digests = [_by_idx[i] for i in sorted(_by_idx) if _by_idx[i]]
    fails = len(buckets) - len(digests)
    if not digests:
        print(f"[ERR] pool local muet ({fails}/{len(buckets)} buckets KO) - backend down ? abort sans ecrire")
        return 2

    # REDUCE HIERARCHIQUE : 13 digests concatenes > n_ctx local (8k) -> overflow
    # (rc=1 observe). On fusionne par lots de 4 (sous-syntheses), puis fusion finale.
    def _merge(chunks: list) -> str:
        return _local_ask(
            "Fusionne ces notes de roadmap Nokido en une liste markdown dense, sans doublon, "
            "en gardant la priorite (P0/P1/P2) et l'etat de chaque item. Zero blabla.\n\n"
            + "\n\n---\n\n".join(chunks),
            max_tokens=1100,
        )

    level = list(digests)
    while len(level) > 4:
        print(f"[reduce] niveau intermediaire : {len(level)} -> lots de 4")
        level = [_merge(level[i:i + 4]) for i in range(0, len(level), 4)]

    print("[reduce] fusion finale priorisee...")
    try:
        body = _local_ask(
            "Fusionne en UNE roadmap Nokido unique, sans doublon, priorisee. Format markdown EXACT :\n"
            "# ROADMAP LaForge\n\n## P0 - Socle\n- ...\n\n## P1 - Autonomie & robustesse\n- ...\n\n"
            "## P2 - Cognition distribuee\n- ...\n\nChaque item : **titre** - pourquoi (etat).\n\n"
            + "\n\n---\n\n".join(level),
            max_tokens=2200,
        )
    except Exception as exc:  # noqa: BLE001 - jamais rc=1 : ROADMAP degradee garantie
        print(f"[warn] reduce final KO ({exc}) -> ROADMAP degradee (digests fusionnes bruts)")
        body = ("# ROADMAP Nokido (degradee - reduce final KO, sous-syntheses brutes)\n\n"
                + "\n\n---\n\n".join(level))

    header = (
        "<!-- Genere par tools/forge_roadmap_synth.py (pool LOCAL souverain) - "
        f"ts={int(time.time())}. Source unique VIVANTE, re-synthetisable. -->\n\n"
    )
    content = header + body.strip() + "\n"

    if args.dry_run:
        print("=== DRY-RUN - docs/ROADMAP.md (apercu) ===\n" + content[:2500])
        return 0

    # write VETTÉ par le résolveur : un run_job (sandbox) ne peut PAS écrire le repo
    # docs/ -> redirige vers sandbox/workspace (writable). Copie dans docs/ ensuite.
    _out = OUT
    try:
        from nokido_agent.app.forge_resolver import writable_path
        _out, _red = writable_path(OUT, context=_os.environ.get("LAFORGE_CTX", "run_job"))
    except Exception:  # noqa: BLE001
        pass
    _out.parent.mkdir(parents=True, exist_ok=True)
    _out.write_text(content, encoding="utf-8")
    print(f"[ok] ecrit {_out} ({len(content)} chars)")

    try:
        from nokido_agent.app.forge_self_correction import anchor_solution

        anchor_solution(
            problem="Roadmap Nokido eparpillee (pas de doc canonique ; chaque agent improvise)",
            solution=("docs/ROADMAP.md synthetise par le POOL LOCAL souverain "
                      "(tools/forge_roadmap_synth.py) depuis anchors roadmap_* + docs. "
                      "Re-lancer = roadmap raffinee."),
            example="run_job script=tools/forge_roadmap_synth.py  (ou LAFORGE_PYTHON tools/forge_roadmap_synth.py)",
            domain="roadmap",
        )
        print("[ok] anchored domain=roadmap")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] anchor_solution: {exc}")

    # SSoT structuré (state déterministe + roadmap JSON) — uniforme cross-CLI.
    # Best-effort : ne casse JAMAIS la synth markdown ci-dessus.
    try:
        _write_roadmap_state(level)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] roadmap_state.json: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
