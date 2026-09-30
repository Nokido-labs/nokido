#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_background_review.py — fork post-turn LOCAL : auto-anchor solution + propose skill.

MOTIF (hermes-agent `agent/background_review.py`, veille 2026-06-17) : après un tour,
rejouer un snapshot de conversation dans un agent forké qui se demande « faut-il
persister une compétence / une solution ? » et écrit dans les stores. Le prompt-cache
principal n'est jamais touché.

VERSION Nokido — SÛRE + SOUVERAINE :
  - LLM **LOCAL UNIQUEMENT** (ollama :11434, qwen) → 0 token Claude, 0 API payante.
    Si le LLM local est indisponible → skip propre (aucune dépense, aucun cloud).
  - Lancé DÉTACHÉ par le Stop-hook (claude_session_stop.py) → ne bloque jamais le tour.
  - ANTI-DUP (§3) : RÉUTILISE forge_self_correction.anchor_solution (mémoire = MemGPT,
    interdit de reconstruire) + forge_skill_forge.from_text (création skill → PROPOSAL,
    pas d'auto-install) + les loaders de claude_precompact (chargement des tours).
  - Throttle : 1 review / session / 300s (évite de spammer le LLM local à chaque tour).
  - Skill = PROPOSAL seulement (install reste owner+confirm) → zéro action irréversible.

Usage :
  - hook : stdin JSON {session_id, transcript_path} → review_session(...)
  - cli  : forge_background_review.py <session_id> [transcript_path] [--dry-run]
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/lesson : fork post-turn, auto-anchor de solution et proposition de skill"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

OLLAMA = "http://127.0.0.1:11434/v1/chat/completions"
OLLAMA_MODEL = os.environ.get("LAFORGE_REVIEW_MODEL", "qwen2.5-coder:7b-instruct")
THROTTLE_S = 300
MARKER_DIR = Path("C:/tmp/bg_review")
MAX_TURNS = 12

_PROMPT = (
    "Tu es un relecteur de session de travail technique. À partir de l'historique ci-dessous,\n"
    "décide s'il faut PERSISTER quelque chose de RÉUTILISABLE. Sois CONSERVATEUR : si rien de\n"
    "durable, renvoie des null. Réponds UNIQUEMENT par un objet JSON STRICT :\n"
    '{\n'
    '  "solution": {"problem": "...", "solution": "...", "example": "...", "domain": "systeme|rag|llm|security|..."} ou null,\n'
    '  "skill": {"slug": "kebab-court", "doc_md": "# Titre\\n\\nInstructions réutilisables concises (markdown)"} ou null\n'
    '}\n'
    "Une SOLUTION = un fix/pattern validé, généralisable (noms de fichiers exacts si utile).\n"
    "Un SKILL = une procédure réutilisable claire (commandes + étapes). Sinon null.\n\n"
    "HISTORIQUE:\n"
)


def _load_turns(session_id: str, transcript_path: str) -> list:
    """Réutilise les loaders de claude_precompact (source unique)."""
    try:
        from nokido_agent.tools import claude_precompact as cp  # type: ignore

        turns, last_ts = cp._load_from_agent_messages(session_id)
        if transcript_path:
            turns = (turns + cp._load_transcript_after(transcript_path, last_ts))[-MAX_TURNS:]
        return turns[-MAX_TURNS:]
    except Exception:
        return []


def _local_llm(payload: str, timeout: int = 45) -> "str | None":
    """Appel LLM LOCAL qualifié via le résolveur souverain (modèle choisi parmi les
    INSTALLÉS — plus de tag hardcodé mort). Aucun fallback cloud. None si indispo."""
    try:
        from nokido_agent.tools.forge_local_llm import chat

        return chat(_PROMPT + payload, json_mode=True, timeout=timeout, max_tokens=600)
    except Exception:
        return None


def _parse(text: str) -> dict:
    import re

    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]+\}", text or "")
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def _throttled(session_id: str) -> bool:
    try:
        MARKER_DIR.mkdir(parents=True, exist_ok=True)
        mk = MARKER_DIR / f"{session_id}.ts"
        if mk.exists() and (time.time() - mk.stat().st_mtime) < THROTTLE_S:
            return True
        mk.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass
    return False


def review_session(session_id: str, transcript_path: str = "", dry_run: bool = False) -> dict:
    """Relit le tour via LLM local, persiste solution (anchor) + propose skill. Fail-soft."""
    out = {"session_id": session_id, "dry_run": dry_run, "actions": []}
    if not dry_run and _throttled(session_id):
        out["skipped"] = "throttled"
        return out
    turns = _load_turns(session_id, transcript_path)
    if not turns:
        out["skipped"] = "no_turns"
        return out
    payload = "\n".join(
        ("U: " if t.get("role") == "user" else "A: ") + (t.get("content", "")[:600]) for t in turns
    )[:9000]

    raw = _local_llm(payload)
    if raw is None:
        out["skipped"] = "local_llm_unavailable"
        return out
    decision = _parse(raw)
    out["decision"] = {k: bool(decision.get(k)) for k in ("solution", "skill")}

    sol = decision.get("solution")
    if isinstance(sol, dict) and sol.get("problem") and sol.get("solution"):
        if dry_run:
            out["actions"].append({"anchor_solution": sol.get("problem", "")[:60]})
        else:
            try:
                from nokido_agent.app.forge_self_correction import anchor_solution

                r = anchor_solution(
                    problem=str(sol.get("problem", ""))[:300],
                    solution=str(sol.get("solution", ""))[:400],
                    example=str(sol.get("example", ""))[:300],
                    domain=str(sol.get("domain", "systeme")),
                )
                out["actions"].append({"anchor_solution": r})
            except Exception as e:
                out["actions"].append({"anchor_solution_error": str(e)})

    sk = decision.get("skill")
    if isinstance(sk, dict) and sk.get("slug") and sk.get("doc_md"):
        if dry_run:
            out["actions"].append({"propose_skill": sk.get("slug")})
        else:
            try:
                from nokido_agent.app.forge_skill_forge import from_text

                r = from_text(str(sk["doc_md"]), str(sk["slug"]), source="background_review")
                out["actions"].append({"propose_skill": r})
            except Exception as e:
                out["actions"].append({"propose_skill_error": str(e)})

    # log compact (audit)
    try:
        MARKER_DIR.mkdir(parents=True, exist_ok=True)
        (MARKER_DIR / f"{session_id}.log").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    return out


def main() -> int:
    sid, tpath, dry = "", "", False
    args = [a for a in sys.argv[1:]]
    if "--dry-run" in args:
        dry = True
        args = [a for a in args if a != "--dry-run"]
    if args:
        sid = args[0]
        tpath = args[1] if len(args) > 1 else ""
    else:
        try:
            raw = sys.stdin.read()
            if raw.strip():
                hi = json.loads(raw)
                sid = hi.get("session_id", "")
                tpath = hi.get("transcript_path", "")
        except Exception:
            pass
    if not sid:
        return 0
    res = review_session(sid, tpath, dry_run=dry)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
