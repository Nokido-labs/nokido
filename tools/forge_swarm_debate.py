#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_swarm_debate.py - débat SWARM 3 tours, pool de spécialistes diversifiés.

Orchestre un débat à 3 rounds (map parallèle -> synthèse -> raffine) sur un panel
de personas-spécialistes distincts (backends cloud diversifiés). Appelle
forge_agent_proxy.ask EN DIRECT (in-process) = bypass du ring-gate hub + reach cloud.
Déporté via run_job (online=true). Écrit docs/swarm_debate_organ_tiers.md + reco finale.

Sujet (args/défaut) : faut-il transformer les ORGANES Nokido en agents bas-niveau ?
Proposition à challenger : modèle 3-tiers RÉFLEXE(module) / ACTEUR(event-driven 0-LLM) / AGENT(autonome).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "swarm_debate_organ_tiers.md"
DEFAULT_SUJET = "Organes Nokido -> agents bas-niveau ?"


def deriver_titre_et_fichier(sujet: str, root: Path = ROOT) -> tuple[str, Path]:
    s = (sujet or "").strip()
    if not s or s == DEFAULT_SUJET:
        return DEFAULT_SUJET, root / "docs" / "swarm_debate_organ_tiers.md"
    import re
    import unicodedata
    slug = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", slug).strip().lower()
    slug = re.sub(r"[-\s]+", "_", slug)[:60].strip("_")
    nom_fichier = f"swarm_debate_{slug}.md" if slug else "swarm_debate_sujet.md"
    return s, root / "docs" / nom_fichier

# Spécialistes DISTINCTS (rôle, provider ask). Noms ask courts (cf. list_providers).
SPECIALISTS = [
    ("ARCHITECTE LOGICIEL (couplage, blast-radius, maintenabilité, distributed-monolith)", "groq"),
    ("SRE/PERFORMANCE (latence hot-path, observabilité d'une toile async, débogabilité)", "cerebras"),
    ("SÉCURITÉ (surface d'attaque, isolation, fail-closed, confused deputy)", "mistral"),
    ("INGÉNIEUR SYSTÈMES DISTRIBUÉS (actor model, message-passing, consistency, supervision/résilience)", "nvidia_nim"),  # gpt4o_github RETIRE 15/10
    ("FRUGALITÉ/SOUVERAINETÉ (coût tokens, RAM/iGPU, local-first, tax de l'agentification)", "cohere"),
]
# Providers LIVE+gratuits (cf. list_providers). gemini_cli (OAuth) ne marche PAS déporté
# (WinError 5, exige la session user) -> Gemini le PAIR participe via POSTAL, pas ici.
# deepseek(402)/grok(clé morte) écartés. Run en TRUSTED (écrit le repo + internet).

SEED = (
    "Nokido = OS d'agents local-first (700+ modules forge_*, hub HTTP, organes biomimétiques). "
    "QUESTION : faut-il transformer les ORGANES (modules) en agents bas-niveau ?\n"
    "PROPOSITION 3-TIERS à challenger : RÉFLEXE = module SYNCHRONE hot-path (RBAC/ring/firewall/"
    "RAG-search/gate) -> NE PAS agentifier (latence/complexité) ; ACTEUR RÉACTIF = event-driven "
    "déterministe ZÉRO-LLM (évolution des daemons/keepers) ; AGENT = état+proactif+autonome, déjà "
    "daemons (keepers/facteur/secrétaire/veille) -> formaliser sous contrat OrganAgent."
)


async def _ask_one(role: str, prov: str, task: str) -> tuple:
    # timeout par spécialiste : gemini_cli (OAuth) est lent (>120s) -> ne doit pas
    # bloquer le tour indéfiniment ; les rapides (groq/grok) répondent en <2s.
    _to = 200 if prov.endswith("_cli") else 60
    try:
        from nokido_agent.app.forge_agent_proxy import ask
        r = await asyncio.wait_for(
            ask(prov, f"TON RÔLE = {role}.\n\n{task}", max_tokens=420, rag_context=False), timeout=_to)
        txt = (r.get("text") or "").strip()
        ok = bool(r.get("ok")) and bool(txt)
        # 3/11 : un echec garde son MOTIF (402, 403, « Provider inconnu ») -- l'avaler a rendu 2 debats invalides
        # 8/11 : reponse vide = echec du participant (cause « vide »), jamais compte au quorum
        motif = r.get("error") or ("vide" if not txt else "erreur")
        return (role, prov, txt if ok else "[KO: %s]" % motif, ok)
    except asyncio.TimeoutError:
        return (role, prov, f"[timeout {_to}s]", False)
    except Exception as e:  # noqa: BLE001
        return (role, prov, f"[KO: {type(e).__name__}: {e}]", False)


REMPLACANTS: list[str] = []


async def _round(task: str, label: str, remplacants: list | None = None) -> list:
    print(f"[{label}] {len(SPECIALISTS)} spécialistes en parallèle...")
    res = await asyncio.gather(*[_ask_one(r, p, task) for r, p in SPECIALISTS])
    subs = list(remplacants if remplacants is not None else REMPLACANTS)
    pris = {p for _, p in SPECIALISTS}
    ok = []
    for role, prov, txt, bon in res:
        if bon and txt and not txt.startswith("[KO:"):
            ok.append((role, prov, txt, bon))
        else:
            print(f"[{label}] MUET {prov} ({role[:40]}) : {txt[:160]}")
            # Remplacement comme le fait sonder_panel (l.76)
            remplace = False
            while subs:
                sub = subs.pop(0)
                if sub in pris:
                    continue
                pris.add(sub)
                sub_res = await _ask_one(role, sub, task)
                s_role, s_prov, s_txt, s_bon = sub_res
                if s_bon and s_txt and not s_txt.startswith("[KO:"):
                    ok.append(sub_res)
                    remplace = True
                    print(f"[{label}] REMPLACE {prov} par {sub} ({role[:40]})")
                    break
                else:
                    print(f"[{label}] REMPLACANT {sub} ECHEC : {s_txt[:160]}")
    print(f"[{label}] {len(ok)}/{len(SPECIALISTS)} ont répondu")
    return ok


async def sonder_panel(roles: list, remplacants: list | None = None, minimum: int = 4,
                       question: str = "Reponds seulement par OK.") -> tuple:
    """Pre-vol par la CAPACITE (3/11) : chaque fournisseur recoit une question minuscule ; n'est garde que celui qui
    REPOND. Un muet est remplace par un remplacant lui aussi sonde (un remplacant ne sert qu'une fois). Moins de
    `minimum` roles vivants -> ValueError (fail-closed). Rend (panel, ecartes[(fournisseur, motif)]).
    NR : tests/nr/test_swarm_debate_panel_sonde_nr.py"""
    candidats = list(dict.fromkeys([p for _, p in roles] + list(remplacants or [])))
    sondes = await asyncio.gather(*[_ask_one("SONDE", p, question) for p in candidats])
    vivant = {p: ok for _, p, _, ok in sondes}
    motif = {p: txt for _, p, txt, ok in sondes if not ok}
    panel, pris = [], set()
    for role, prov in roles:
        if vivant.get(prov) and prov not in pris:
            panel.append((role, prov)); pris.add(prov)
            continue
        sub = next((r for r in (remplacants or []) if vivant.get(r) and r not in pris), None)
        if sub:
            panel.append((role, sub)); pris.add(sub)
    ecartes = [(p, motif[p]) for p in candidats if p in motif]
    for p, m in ecartes:
        print(f"[sonde] ecarte {p} : {m[:160]}")
    if len(panel) < minimum:
        raise ValueError("panel insuffisant : %d role(s) vivant(s) < %d -- debat refuse" % (len(panel), minimum))
    return panel, ecartes


async def _synth(answers: list, instr: str) -> str:
    if not answers:
        return "[aucune réponse]"
    from nokido_agent.app.forge_agent_proxy import ask
    joined = "\n\n".join(f"### {r} ({p})\n{t}" for r, p, t, _ in answers)
    s = await ask("groq", f"{instr} Cite les divergences notables.\n\n{joined}",
                  max_tokens=700, rag_context=False)
    return (s.get("text") or "").strip() or "[synthèse vide]"


async def main(argv: list[str] | None = None) -> int:
    # PRÉ-VOL via le RÉSOLVEUR : écarte les providers morts/inadaptés au contexte +
    # redirige le write si non-inscriptible. Plus d'erreur qui passe dans le flux.
    global SPECIALISTS, OUT
    import os
    import argparse
    from nokido_agent.app.forge_resolver import resolve_provider_panel, writable_path

    parser = argparse.ArgumentParser(description="Débat SWARM multi-spécialistes.")
    parser.add_argument("sujet_pos", nargs="?", default=None, help="Sujet du débat (positionnel)")
    parser.add_argument("--sujet", "--subject", dest="sujet_opt", default=None, help="Sujet du débat")
    args = parser.parse_args(argv)

    sujet_effectif = args.sujet_opt or args.sujet_pos or DEFAULT_SUJET
    titre_effectif, out_effectif = deriver_titre_et_fichier(sujet_effectif, ROOT)
    OUT = out_effectif

    _ctx = os.environ.get("LAFORGE_CTX", "trusted")
    SPECIALISTS = resolve_provider_panel(SPECIALISTS, context=_ctx) or SPECIALISTS
    OUT, _red = writable_path(OUT, context=_ctx)
    print(f"[resolver] panel={[p for _, p in SPECIALISTS]} ctx={_ctx} out={OUT.name}")

    seed_effectif = (
        SEED if sujet_effectif == DEFAULT_SUJET
        else f"SUJET : {sujet_effectif}\n\nQUESTION : {sujet_effectif}\nDepuis ton rôle d'expert : analyse, risques, arbitrages et recommandations concrètes."
    )

    r1 = await _round(seed_effectif + "\n\nDepuis ton rôle : VALIDE / RAFFINE / CONTESTE. 4-6 points denses, "
                      "risques concrets, zéro blabla.", "R1")
    s1 = await _synth(r1, "Synthétise ce débat : points d'ACCORD + TENSIONS structurelles.")

    r2 = await _round(f"Synthèse du tour 1 :\n{s1}\n\nDepuis ton rôle, CHALLENGE/RAFFINE les "
                      "tensions (surtout le tier ACTEUR et la frontière réflexe/agent). 4-6 points.", "R2")
    s2 = await _synth(r2, "Synthétise le tour 2 : ce qui CONVERGE, ce qui reste OUVERT.")

    r3 = await _round(f"Synthèse du tour 2 :\n{s2}\n\nCONVERGE : ta RECO FINALE sur le modèle 3-tiers "
                      "(garder tel quel / modifier / rejeter) + LA règle de décision réflexe-vs-agent. 3-5 points.", "R3")
    s3 = await _synth(r3, "RECO FINALE consolidée : le modèle de tiers retenu + le discriminateur + les nuances clés.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        f"# Débat Swarm — {titre_effectif}\n\n"
        f"_Panel : {', '.join(p for _, p in SPECIALISTS)} ({len(SPECIALISTS)} rôles distincts) · 3 tours._\n\n"
        f"## Tour 1 — prises de position\n{s1}\n\n"
        f"## Tour 2 — challenge des tensions\n{s2}\n\n"
        f"## RECO FINALE (convergence)\n{s3}\n",
        encoding="utf-8")
    print(f"[ok] écrit {OUT}")
    print("\n=== RECO FINALE ===\n" + s3[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
