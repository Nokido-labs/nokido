"""forge_cli_swarm.py — Swarm multi-CLI SOUVERAIN, appelé depuis Nokido.

__FORGE_COLOR__ = "locomoteur-orchestration"

Dispatch UN task à N providers (CLI OAuth + cloud rapide) en PARALLÈLE, collecte, synthèse.
Réutilise `forge_agent_proxy.ask` (primitive atomique — NE la duplique pas) ; ce module = le
COMPOSEUR panel par-dessus, déportable (claude_cli/gemini_cli lents -> lancer via run_job).
PAS le tool Workflow de Claude (règle d'or Nokido : swarm souveraine via le hub).

Anti-dup : LeadOrchestrator (forge_swarm_team) = panel parallèle MAIS orienté providers API +
async-non-déportable. Ici = panel sur les CLI OAuth (claude_cli/gemini_cli) + cloud free, en
script CLI déportable. Membres par défaut = OAuth Max/Ultra (quota frais) + groq/cerebras rapides.

Usage:
  LAFORGE_PYTHON tools/forge_cli_swarm.py "<task>" [provider1,provider2,...]
  (déporté: run action=run_job script=tools/forge_cli_swarm.py online=true)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_agent_proxy import ask  # primitive atomique réutilisée

DEFAULT_MEMBERS = ["claude_cli", "gemini_cli", "groq", "cerebras"]
# Reduce en LOCAL (ollama) : les réponses du swarm peuvent contenir des internals Nokido ;
# synthétiser sur un cloud (groq) = egress -> DLP firewall bloque (constat 2026-06-10). Local = 0 egress.
SYNTH_PROVIDER = os.environ.get("LAFORGE_SWARM_SYNTH", "ollama")


# Un provider peut rendre ok=True avec un TEXTE d'erreur (« [ERR pollinations] HTTP
# Error 401 ») ou un texte VIDE : mesure du swarm du 2026-09-22, « 6/16 ok »
# annonce pour 5 reponses reelles. Et « backend non pret » depuis un compte qui ne
# voit pas le binaire du profil owner (AGY, codex, copilot) est une lecture
# IMPOSSIBLE, pas un pair mort : UNKNOWN != NO.
_MARQUES_ERREUR = ("[err", "[agy]", "error:", "http error")
_MARQUES_ILLISIBLE = ("backend non pret", "backend non prêt")


def _classer(ok: bool, texte: str, erreur) -> str:
    """OK · VIDE · KO · INDETERMINE -- liste BLANCHE : n'est OK que la vraie reponse."""
    err = str(erreur or "").lower()
    if any(m in err for m in _MARQUES_ILLISIBLE):
        return "INDETERMINE"
    if not ok:
        return "KO"
    if not texte.strip():
        return "VIDE"
    if texte.lstrip().lower().startswith(_MARQUES_ERREUR):
        return "KO"
    return "OK"


async def _one(member: str, task: str, max_tokens: int) -> dict:
    # Membre = "provider" OU "provider:model" -> pioche un modèle PRÉCIS d'un même backend
    # (LMStudio :1234 / Ollama hébergent N modèles joignables). Ex: "lmstudio_native:qwen2.5-7b",
    # "lmstudio_native:phi-4", "ollama:laforge-qwen:latest". partition sur le 1er ':' (les ids
    # ollama gardent leur ':tag'). Sans ':' = comportement historique (modèle défaut du provider).
    provider, _sep, model = member.partition(":")
    t0 = time.time()
    try:
        r = await ask(provider, task, max_tokens=max_tokens, rag_context=False, model=(model or None))
        texte = (r.get("text") or "").strip()
        etat = _classer(bool(r.get("ok")), texte, r.get("error"))
        return {
            "provider": member,  # label COMPLET (provider:model) pour distinguer les membres d'un même backend
            "ok": etat == "OK",
            "etat": etat,
            "text": texte,
            "model": r.get("model") or (model or None),
            "ms": int((time.time() - t0) * 1000),
            "error": r.get("error"),
        }
    except Exception as e:  # noqa: BLE001
        return {"provider": member, "ok": False, "etat": _classer(False, "", e), "text": "",
                "error": str(e), "ms": int((time.time() - t0) * 1000)}


async def swarm(task: str, members: list[str], max_tokens: int = 900) -> dict:
    """Map (parallèle) -> Reduce (synthèse). Règle d'or : pure orchestration, 0 garde sémantique ici."""
    answers = await asyncio.gather(*[_one(p, task, max_tokens) for p in members])
    ok_ans = [a for a in answers if a["ok"] and a["text"]]
    synthesis = None
    if len(ok_ans) >= 2:
        joined = "\n\n".join(f"### {a['provider']} ({a.get('model')})\n{a['text']}" for a in ok_ans)
        s = await ask(
            SYNTH_PROVIDER,
            f"Synthétise ces {len(ok_ans)} réponses d'un swarm multi-CLI en UNE réponse consolidée "
            f"(garde les divergences notables, cite le provider):\n\n{joined}",
            max_tokens=max_tokens,
            rag_context=False,
        )
        synthesis = (s.get("text") or "").strip()
        if not synthesis:
            synthesis = f"[synthèse indisponible — {SYNTH_PROVIDER}: {s.get('error') or 'réponse vide'} (modèle local KO ? override LAFORGE_SWARM_SYNTH)]"
    return {"task": task, "members": members, "answers": answers, "synthesis": synthesis}


def main() -> int:
    task = sys.argv[1] if len(sys.argv) > 1 else "Swarm test : en 1 phrase, qui es-tu (modèle réel) et ton ring ?"
    members = sys.argv[2].split(",") if len(sys.argv) > 2 else DEFAULT_MEMBERS
    res = asyncio.run(swarm(task, members))
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = ROOT / "sandbox" / f"cli_swarm_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    okc = sum(1 for a in res["answers"] if a["ok"])
    print(f"SWARM {okc}/{len(members)} ok -> {out}")
    for a in res["answers"]:
        tag = a.get("etat") or ("OK" if a["ok"] else "KO")
        print(f"  [{a['provider']:12}] {tag} {a['ms']}ms  {(a.get('error') or a['text'][:90])}")
    if res["synthesis"]:
        print(f"SYNTHÈSE: {res['synthesis'][:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
