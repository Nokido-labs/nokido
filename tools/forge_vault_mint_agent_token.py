"""tools/forge_vault_mint_agent_token.py — FRAPPE un jeton d'agent au coffre.

POURQUOI CET OUTIL EXISTE, alors que `forge_vault_seed_agent_tokens.py` est deja
la : celui-la MIGRE des valeurs existantes (env, fichier, stdin) ; il ne sait pas
en CREER. Or provisionner l'identite d'un daemon demande une valeur neuve, et les
trois sources du migrateur passent toutes par un endroit ou la valeur est
visible.

CE QUI EST INTERDIT ICI, et c'est la raison d'etre du fichier :
  - la valeur n'est JAMAIS un argument. `forge_mcp_registry._handle_trusted_script`
    journalise `script_args` en clair (`logger.info("[trusted_script] keys=%s
    script_args=%r")`) : un secret passe en parametre finirait dans les logs du
    hub. On ne prend donc QUE le nom de l'agent.
  - la valeur n'est jamais imprimee, ni en entier ni tronquee. La sortie ne porte
    que des METADONNEES : presence, longueur, empreinte courte.
  - aucun secret n'est ecrit dans le depot, `sandbox/` ou un journal.

POURQUOI IL DOIT TOURNER EN `trusted_script` : le coffre machine vit dans
`data/machine_vault.dat`, sous le dossier du depot, et le compte bac a sable n'y
a pas l'ecriture (mesure 2026-08-31 : `[Errno 13] Permission denied` sur le
fichier temporaire). Le compte `LaForgeTrusted` l'a.

MOINDRE PRIVILEGE : on refuse de frapper un jeton pour une identite qui n'est pas
DECLAREE dans `config/agent_identities.json`. Frapper un secret pour un nom
inconnu creerait une identite fantome que le registre ne connaitrait pas, et le
ring resolu serait de toute facon 4 — un secret sans effet, mais bien reel.

Usage :
    run action=trusted_script path=tools/forge_vault_mint_agent_token.py
        script_args="--agent AUTONOMOUS_LOOPS"
    ... --agent X --rotate     # remplace un jeton existant (assume, jamais par defaut)
    ... --agent X --verify     # etat seul, aucune ecriture
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_LONGUEUR_OCTETS = 32          # 64 caracteres hex, aligne sur les jetons existants


def _ring_declare(agent: str):
    """Le ring que le REGISTRE accorde a cette identite, ou None si inconnue.

    On lit la meme source que le hub (`_agents_a_charger` en fait l'union avec
    son tuple fige) : frapper un jeton en se fiant a une autre liste ferait
    diverger le coffre et le registre.
    """
    p = ROOT / "config" / "agent_identities.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        print("[mint] registre ILLISIBLE (%s: %s) — on refuse de frapper a l'aveugle"
              % (type(exc).__name__, str(exc)[:80]))
        return None
    ent = (d.get("agents") or {}).get(agent)
    if not isinstance(ent, dict):
        return None
    r = ent.get("ring")
    return int(r) if isinstance(r, (int, float, str)) and str(r).isdigit() else None


def _etat(cle: str) -> dict:
    """Presence et empreinte, JAMAIS la valeur."""
    from nokido_agent.app.forge_secrets import get_secret, invalidate_cache
    invalidate_cache(cle)
    v = get_secret(cle)
    if not v:
        return {"present": False}
    return {"present": True, "longueur": len(v),
            "empreinte_sha256_8": hashlib.sha256(v.encode()).hexdigest()[:8]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True,
                    help="nom de l'identite (jamais une valeur de secret)")
    ap.add_argument("--rotate", action="store_true",
                    help="remplace un jeton existant au lieu de s'abstenir")
    ap.add_argument("--verify", action="store_true", help="etat seul, aucune ecriture")
    a = ap.parse_args(argv)

    agent = a.agent.strip().upper()
    if not agent.replace("_", "").isalnum():
        print("[mint] nom d'agent invalide")
        return 2
    cle = "FORGE_TOKEN_%s" % agent

    ring = _ring_declare(agent)
    if ring is None:
        print("[mint] REFUS : %s n'est pas declaree dans config/agent_identities.json. "
              "Un secret frappe pour une identite inconnue serait resolu ring 4 — "
              "sans effet, et pourtant bien reel." % agent)
        return 1
    print("[mint] agent=%s ring_declare=%s cle=%s" % (agent, ring, cle))

    avant = _etat(cle)
    print("[mint] avant : %s" % json.dumps(avant, ensure_ascii=False))
    if a.verify:
        return 0
    if avant.get("present") and not a.rotate:
        print("[mint] deja provisionne — aucune ecriture (idempotent). "
              "Utiliser --rotate pour remplacer.")
        return 0

    from nokido_agent.app.forge_secrets import set_secret
    if not set_secret(cle, secrets.token_hex(_LONGUEUR_OCTETS)):
        print("[mint] ECHEC d'ecriture au coffre. Cause la plus frequente : le "
              "compte n'a pas l'ecriture sur data/machine_vault.dat — relancer "
              "en trusted_script.")
        return 1

    apres = _etat(cle)
    print("[mint] apres : %s" % json.dumps(apres, ensure_ascii=False))
    if not apres.get("present"):
        print("[mint] ecriture rapportee OK mais relecture VIDE — ne pas conclure "
              "au succes.")
        return 1
    if avant.get("present") and avant.get("empreinte_sha256_8") == apres.get(
            "empreinte_sha256_8"):
        print("[mint] l'empreinte n'a PAS change : la rotation n'a rien remplace.")
        return 1
    print("[mint] OK. Le hub charge ses jetons au BOOT (_load_agent_tokens) : "
          "un redemarrage est necessaire pour que cette identite soit reconnue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
