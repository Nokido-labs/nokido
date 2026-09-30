#!/usr/bin/env python
"""forge_patch_hub_ordres_bureau.py — cable `hub action=redemarrer_stack|ordre_bureau` (fichier CRITIQUE).

POURQUOI UN SCRIPT : `app/forge_mcp_registry.py` est CRITICAL_FILE, `governed_edit` le refuse.
Ce script est commite, relu, puis lance par `trusted_script`. La logique vit dans
`app/forge_ordres_bureau.py` (NR `tests/nr/test_ordres_bureau_nr.py`) ; ici, seulement les
points d'appel. Meme forme que `tools/forge_patch_hub_elicitation.py`.

CE QUE LE PATCH CABLE (decision owner 2026-09-26 : panneau et tray ring 2, redemarrage
full-stack confirme par elicitation) :
  R1  schema de l'outil `hub` : actions `redemarrer_stack` et `ordre_bureau`.
  R2  aiguillage : `redemarrer_stack` questionne l'owner (elicitation) et depose un ordre
      s'il ACCEPTE ; `ordre_bureau` le rend au tray (usage unique, consommateurs admis).
  Le flux SSE qui porte la question est ouvert par `forge_mcp_elicitation.sse_requis`
  (ACTIONS_QUI_QUESTIONNENT), deja cable dans le hub : rien a toucher dans `nokido_hub.py`.

USAGE
  --verifier   ancres uniques + AST apres patch ; n'ecrit RIEN.
  (defaut)     applique : tout ou rien. Deja applique -> rien a faire (idempotent).
  Retour arriere : `git checkout -- app/forge_mcp_registry.py`.
  Effet reel : au prochain redemarrage du hub seulement (geste coordonne, accord owner).
"""
from __future__ import annotations

import sys
from pathlib import Path

from forge_patch_hub_elicitation import appliquer  # source unique (cliquet clones)

__FORGE_COLOR__ = "moteur/ordres confirmes par l'owner : patch des points d'appel du registre"

RACINE = Path(__file__).resolve().parent.parent
REGISTRE = RACINE / "app" / "forge_mcp_registry.py"
TEMOIN = "forge_ordres_bureau"

# (etiquette, ancre exacte et UNIQUE, remplacement) — ecrits en LF, adaptes au CRLF du fichier.
PATCH_REGISTRE = [
    # AVANT "quota_model" et non apres "confirmer_owner" : la R1 du patch d'elicitation
    # (forge_patch_hub_elicitation) couvre le bloc contigu quota_model..confirmer_owner..],
    # et son NR le relit a l'identique. S'inserer dedans casserait son chemin reel.
    ("R1 schema de l'outil hub",
     '                                "emit_telemetry",\n'
     '                                "quota_model",\n',
     '                                "emit_telemetry",\n'
     '                                "redemarrer_stack",\n'
     '                                "ordre_bureau",\n'
     # demander_ordre (2026-09-29, derogation owner unique) : AVANT quota_model, pour la
     # meme raison que ci-dessus -- le bloc quota_model..confirmer_owner reste contigu.
     '                                "demander_ordre",\n'
     '                                "quota_model",\n'),
    ("R2 aiguillage",
     '            r = await confirmer_owner(str(args.get("message") or ""), str(args.get("detail") or ""))\n'
     '            return _json.dumps(r, ensure_ascii=False)\n',
     '            r = await confirmer_owner(str(args.get("message") or ""), str(args.get("detail") or ""))\n'
     '            return _json.dumps(r, ensure_ascii=False)\n'
     '        if action in ("redemarrer_stack", "ordre_bureau", "demander_ordre"):\n'
     '            # Ordres confies a la session de l\'owner (app/forge_ordres_bureau.py, 2026-09-26) :\n'
     '            # redemarrer_stack questionne l\'owner par elicitation et ne depose l\'ordre que\n'
     '            # sur ACCEPTE ; ordre_bureau le rend au tray, une seule fois. demander_ordre\n'
     '            # (2026-09-29, derogation owner UNIQUE sur ce fichier) est la porte generique :\n'
     '            # les ordres suivants s\'ajoutent dans forge_ordres_bureau, plus ici.\n'
     '            import json as _json\n'
     '            from nokido_agent.app import forge_ordres_bureau as _ob\n'
     '\n'
     '            if action == "redemarrer_stack":\n'
     '                r = await _ob.redemarrer_stack(agent, str(args.get("message") or ""))\n'
     '            elif action == "demander_ordre":\n'
     '                r = await _ob.demander_ordre(agent, str(args.get("ordre") or ""), str(args.get("message") or ""),\n'
     '                                             cible=str(args.get("cible") or ""), texte=str(args.get("texte") or ""),\n'
     '                                             pointeur=str(args.get("pointeur") or ""))\n'
     '            else:\n'
     '                r = _ob.prendre(agent)\n'
     '            return _json.dumps(r, ensure_ascii=False)\n'),
]


def main(argv: list) -> int:
    # Source unique du patch par ancre (cliquet clones, CI de reference du 2026-09-26) :
    # tout ou rien, CRLF, AST, --verifier -- dans forge_patch_hub_elicitation.
    return appliquer([(REGISTRE, PATCH_REGISTRE)], argv, TEMOIN)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
