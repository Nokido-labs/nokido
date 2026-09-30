# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/registre-identites"
MIGRATION du SSoT `config/agent_identities.json` vers le SCHEMA 2 :
acteur canonique, alias, surface, boite aux lettres, audience (RFC 8707).

POURQUOI
========
Recensement du 2026-08-14, trois defauts mesures :

1. **Cinq identites parlent au hub sans etre declarees** : AGENT_PROXY,
   DENOHUBMCP, GEMINI_RELAY, INSPECTOR, POST_COMMIT (+ VERIFY vu en presence).
   Non declarees, elles retombent au defaut UNTRUSTED -- ou passent par le
   master token, ce qui est pire : on ne sait plus qui parle.
2. **Trente-quatre identites declarees n'ont JAMAIS ete vues**, dont AGY,
   AGY_HEADLESS, AGY_DAEMON : le meme acteur parle sous `ANTIGRAVITY` pendant
   que le registre decrit des noms que personne n'emploie.
3. **Deux noms pour la meme boite** : le pair ecrit a `agt_claude`,
   `secretaire("CLAUDE")` rend `[]`. Huit courriers dormaient non lus dans
   `agt_antigravity` alors que le canal tache repondait en 53 s.

Le registre ne distinguait pas trois choses differentes :
  - l'ACTEUR (qui decide : Antigravity, Claude, Cline...) ;
  - la SURFACE par laquelle il parle (cli, headless, daemon, hook, relais) ;
  - la BOITE ou son courrier doit arriver.

Consequence directe (constatee) : un hook ou un relais etait traite comme un
tiers, et la reponse de l'acteur n'etait jamais reconnue comme la sienne.

SCHEMA 2 -- champs ajoutes, aucun champ existant ecrase
=======================================================
  actor    : identite canonique de l'acteur qui DECIDE
  kind     : cli_agent | service | daemon | hook | relay | provider | endpoint
             | local_model | surface
  mailbox  : acteur proprietaire de la boite (un hook/relais n'a PAS de boite
             propre : son courrier va a son acteur)
  aliases  : tous les noms vivants (dont les `agt_*` minuscules)
  audience : URI canonique de la ressource visee -- RFC 8707 (Resource
             Indicators). Le serveur MCP doit verifier que son URL est
             l'audience du jeton presente ; le champ pose la valeur attendue.
  surface  : interactive | autonomous | internal | backend

ETAT DE L ART RESPECTE, ET SES LIMITES
======================================
- RFC 8707 : audience declaree par ressource, pour qu'un jeton emis pour une
  ressource ne serve pas ailleurs. Les jetons d'agent actuels sont des secrets
  OPAQUES du vault (pas de claim `aud`) : le champ prepare la validation, il ne
  la realise pas. La validation d'audience est applicable des maintenant aux
  CapabilityToken (deja porteurs de sub/ring/exp).
- RFC 9700 (BCP securite OAuth 2.0) recommande les jetons SENDER-CONSTRAINED
  (DPoP / mTLS). Adoption reelle faible dans l'ecosysteme. Dette declaree ici,
  pas resolue : un jeton porteur vole reste utilisable.
- SPIFFE/SPIRE : l'identite devrait naitre d'une ATTESTATION du workload, pas
  d'un secret pre-partage. Piste locale la moins chere : verifier que le PID
  qui presente le jeton d'un acteur est bien le binaire attendu. NON FAIT ICI.

GARANTIES
=========
Idempotent (sentinelle `schema_version >= 2`), n'ecrase JAMAIS un `ring`
existant, JSON relu et revalide apres ecriture, sauvegarde horodatee, dry-run
par defaut. Les modules lisent le fichier avec un cache sur mtime : l'effet est
immediat, sans redemarrage.

    LAFORGE_PYTHON tools/forge_identity_registry_upgrade.py            # dry-run
    LAFORGE_PYTHON tools/forge_identity_registry_upgrade.py --apply
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "config" / "agent_identities.json"
AUDIENCE_HUB = "http://127.0.0.1:8766/mcp"

# ── ACTEURS : qui DECIDE. Les surfaces en derivent. ──────────────────────────
ACTEURS = {
    "ANTIGRAVITY": {"ring": 1, "alias": ["AGY", "GEMINI"]},
    "CLAUDE": {"ring": 1, "alias": []},
    "CLINE": {"ring": 1, "alias": []},
    "ROO": {"ring": 2, "alias": []},
    "CODEX": {"ring": 2, "alias": []},
    "COPILOT": {"ring": 3, "alias": []},
    "MAMMOUTH": {"ring": 3, "alias": []},
    "VIBE": {"ring": 2, "alias": []},
    "ZCODE": {"ring": 2, "alias": []},
    "SIXTH": {"ring": 2, "alias": []},
    "VSCODE": {"ring": 2, "alias": []},
    "LAFORGE_CLI": {"ring": 1, "alias": ["NOKIDO_CLI"]},
}

# ── SUFFIXES : une surface, jamais un acteur distinct. ───────────────────────
SUFFIXES = {
    "_CLI": ("surface", "interactive", None),
    "_DESKTOP": ("surface", "interactive", None),
    "_HEADLESS": ("daemon", "autonomous", None),
    "_DAEMON": ("daemon", "autonomous", None),
    "_HOOK": ("hook", "internal", 4),
    "_PLAN": ("surface", "interactive", None),
    "_ACT": ("surface", "interactive", None),
    "_RELAY": ("relay", "internal", None),
    "_PROXY": ("relay", "internal", None),
    "_BRIDGE": ("relay", "internal", None),
}

# ── PORTE-VOIX : parlent AU NOM d'un acteur -> courrier route vers lui. ──────
# Defaut du 2026-08-14 : la reponse d'AGY arrivait sous `agt_task_executor` et
# le relai, qui filtrait sur ANTIGRAV%, ne la reconnaissait pas.
PORTE_VOIX = {
    "TASK_EXECUTOR": None,      # porte-voix de l'acteur de la tache (dynamique)
    "AGENT_PROXY": None,
    "GEMINI_RELAY": "ANTIGRAVITY",
    "BRIDGE": None,
    "COLLAB_BROKER": None,
    "OPENAI_PROXY": None,
}

# ── PROVIDERS cloud : jamais clients du hub -> ring bas, pas de boite. ───────
PROVIDERS = ["GROQ", "MISTRAL", "COHERE", "DEEPSEEK", "GROK", "OPENROUTER",
             "GITHUB_MODELS", "CEREBRAS", "TOGETHER", "ANTHROPIC_API",
             "GEMINI_API", "OPENAI_API"]

# ── ENDPOINTS / modeles locaux : servent, ne decident pas. ───────────────────
ENDPOINTS = {"OLLAMA": "endpoint", "LLAMACPP": "endpoint", "LMSTUDIO": "endpoint",
             "VEC_SIDECAR": "endpoint", "EMBED": "endpoint", "RERANKER": "endpoint",
             "GRAPH_EXPLORER": "endpoint", "BRAIN_WORKER": "endpoint",
             "SEARXNG": "endpoint", "NETCFG": "service", "EXEGOL": "endpoint"}

# ── VUS DANS LE JOURNAL MAIS JAMAIS DECLARES (recensement 2026-08-14). ───────
NON_DECLARES = {"AGENT_PROXY": ("relay", 2), "DENOHUBMCP": ("service", 4),
                "GEMINI_RELAY": ("relay", 2), "INSPECTOR": ("daemon", 4),
                "POST_COMMIT": ("service", 4), "VERIFY": ("service", 4),
                # Schema 3 : destinataires vus UNIQUEMENT sur le transport frames
                # (agent_messages), jamais declares -> leur courrier n'avait
                # aucun proprietaire. Recensement du 2026-08-14 : agt_local 64
                # non lus, agt_worker_code 43, agt_hub 14, agt_worker 13,
                # agt_daemon 9, agt_editor 8, agt_laforge 7, agt_gemini_flash 3.
                "WORKER": ("service", 3), "LOCAL": ("service", 3),
                "HUB": ("service", 2), "DAEMON": ("daemon", 3),
                "EDITOR": ("surface", 2), "LAFORGE": ("service", 3),
                "GEMINI_FLASH": ("provider", 3)}

# WORKER_CODE n'est PAS un acteur : c'est la SURFACE d'execution d'AGY. Le
# service NokidoTaskExecutorAgy tourne avec `--agent WORKER_CODE` et lance le
# binaire agy en mode agent. Son courrier appartient donc a ANTIGRAVITY.
SURFACES_EXPLICITES = {"WORKER_CODE": ("ANTIGRAVITY", "relay", "autonomous", 2)}


def _famille(nom):
    """(actor, kind, surface, ring_defaut) pour un nom donne."""
    if nom in SURFACES_EXPLICITES:
        return SURFACES_EXPLICITES[nom]
    for suf, (kind, surface, ring) in SUFFIXES.items():
        if nom.endswith(suf):
            base = nom[: -len(suf)]
            for acteur, meta in ACTEURS.items():
                if base == acteur or base in meta["alias"]:
                    return acteur, kind, surface, ring
            return base or nom, kind, surface, ring
    for acteur, meta in ACTEURS.items():
        if nom == acteur or nom in meta["alias"]:
            return acteur, "cli_agent", "interactive", None
    if nom in PORTE_VOIX:
        # MOINDRE PRIVILEGE : un porte-voix ROUTE le courrier vers son acteur
        # (mailbox) mais n'HERITE JAMAIS de son ring — sinon compromettre le
        # relais suffirait a obtenir le privilege de l'acteur relaye.
        return PORTE_VOIX[nom] or nom, "relay", "internal", 2
    if nom in PROVIDERS:
        return nom, "provider", "backend", 3
    if nom in ENDPOINTS:
        return nom, ENDPOINTS[nom], "backend", None
    if nom in NON_DECLARES:
        kind, ring = NON_DECLARES[nom]
        return nom, kind, "internal", ring
    return nom, "service", "internal", None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="ecrit (defaut : dry-run)")
    args = ap.parse_args()

    brut = CIBLE.read_bytes()
    reg = json.loads(brut.decode("utf-8"))
    if int(reg.get("schema_version", 0)) >= 3:
        print("[deja applique] schema_version >= 3 -- rien a faire")
        return 0
    agents = reg.setdefault("agents", {})
    avant = len(agents)

    a_connaitre = set(agents)
    for acteur, meta in ACTEURS.items():
        a_connaitre.add(acteur)
        a_connaitre |= {acteur + s for s in ("_CLI", "_HEADLESS", "_DAEMON", "_HOOK")}
        for al in meta["alias"]:
            a_connaitre |= {al} | {al + s for s in ("_CLI", "_HEADLESS", "_DAEMON", "_HOOK")}
    a_connaitre |= set(PROVIDERS) | set(ENDPOINTS) | set(PORTE_VOIX) | set(NON_DECLARES)
    a_connaitre |= set(SURFACES_EXPLICITES)

    nouveaux = []
    for nom in sorted(a_connaitre):
        actor, kind, surface, ring_def = _famille(nom)
        e = agents.get(nom)
        if e is None:
            e = {}
            nouveaux.append(nom)
        # ring : on ne touche JAMAIS un ring deja declare
        if "ring" not in e:
            if ring_def is not None:
                e["ring"] = ring_def
            elif actor in ACTEURS:
                e["ring"] = ACTEURS[actor]["ring"]
            else:
                e["ring"] = 4  # fail-closed : inconnu = UNTRUSTED
        e.setdefault("kind", kind)
        e.setdefault("actor", actor)
        e.setdefault("surface", surface)
        e.setdefault("mailbox", actor)
        e.setdefault("audience", AUDIENCE_HUB)
        al = set(e.get("aliases") or [])
        al.add(nom.lower())
        al.add("agt_" + nom.lower())
        if nom in ACTEURS:
            for x in ACTEURS[nom]["alias"]:
                al |= {x, x.lower(), "agt_" + x.lower()}
        e["aliases"] = sorted(al)
        e.setdefault("channel", "HTTP_DIRECT")
        e.setdefault("transport", "http")
        e.setdefault("machine", "local")
        agents[nom] = e

    reg["schema_version"] = 3
    reg["_schema_doc"] = (
        "actor=qui decide | kind=nature | surface=comment il parle | "
        "mailbox=acteur proprietaire de la boite (un hook/relais n'en a pas) | "
        "aliases=noms vivants (routage boite) | audience=RFC 8707 Resource "
        "Indicator attendu. Un ring declare ici n'est JAMAIS ecrase par la "
        "migration. Dette assumee : jetons porteurs opaques, non "
        "sender-constrained (RFC 9700) ; identite non attestee (SPIFFE)."
    )

    sortie = json.dumps(reg, ensure_ascii=False, indent=2) + "\n"
    json.loads(sortie)  # revalidation
    print("  [ok] %d identites -> %d (%d nouvelles)" % (avant, len(agents), len(nouveaux)))
    print("  nouvelles :", ", ".join(nouveaux[:24]) or "(aucune)")
    if len(nouveaux) > 24:
        print("  ... et %d autres" % (len(nouveaux) - 24))

    if not args.apply:
        print("\n[dry-run] %d caracteres prets. Relancer avec --apply." % len(sortie))
        return 0

    sauvegarde = CIBLE.with_suffix(".json.bak." + time.strftime("%Y%m%d_%H%M%S"))
    sauvegarde.write_bytes(brut)
    CIBLE.write_text(sortie, encoding="utf-8")
    relu = json.loads(CIBLE.read_text(encoding="utf-8"))
    if int(relu.get("schema_version", 0)) != 3 or len(relu["agents"]) != len(agents):
        print("[ECHEC] relecture incoherente")
        return 4
    print("  [ok] sauvegarde %s | relu : %d identites" % (sauvegarde.name, len(relu["agents"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
