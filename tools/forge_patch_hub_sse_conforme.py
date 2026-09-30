#!/usr/bin/env python
"""forge_patch_hub_sse_conforme.py — l'ouverture du flux SSE de `tools/call` devient un
COMMENTAIRE SSE (fichier CRITIQUE `tools/nokido_hub.py`).

POURQUOI : le hub ouvrait chaque flux SSE par `data: {"type":"progress","status":"running"}`.
Ce n'est pas un message JSON-RPC. Le client MCP de Claude Code (2.1.283) valide chaque
`data:` comme tel : il le rejette (`invalid_union ... unrecognized_keys: type, status`) et
journalise `HTTP connection dropped` a CHAQUE appel servi en SSE (run, ask, orchestrate,
elicitation...). Mesure : journal MCP de Claude Code du 2026-09-26, une paire de lignes par
appel. Les appels aboutissaient quand meme, mais le transport se disait coupe sans raison.

POURQUOI UN COMMENTAIRE, pas `notifications/progress` : une notification de progression
n'est permise que si le client a fourni un `progressToken` ; la plupart n'en donnent pas.
Un commentaire SSE (`: ...`) est ignore de tout client conforme, et garde ce que l'evenement
apportait : un premier octet tout de suite, avant le premier `: ping` a 15 s.

CLIENTS VERIFIES (2026-09-26, decision owner : garder les acces stdio de Claude Desktop) :
  - `tools/mcp_stdio_bridge.py::_post` garde le DERNIER `data: {` du flux et ignore le reste :
    le commentaire est ignore, le resultat final inchange.
  - `tools/nokido_stdio_bridge.py` n'envoie pas `Accept: text/event-stream` : jamais servi en SSE.
  - aucun lecteur de `"type":"progress"` dans tests/, app/web_hub, proxy_deno, tools/.

USAGE
  --verifier   ancre unique + AST apres patch ; n'ecrit RIEN.
  (defaut)     applique : tout ou rien. Deja applique -> rien a faire (idempotent).
  Retour arriere : `git checkout -- tools/nokido_hub.py`.
  Effet reel : au prochain redemarrage du hub seulement (geste coordonne, accord owner).
"""
from __future__ import annotations

import sys
from pathlib import Path

from forge_patch_hub_elicitation import appliquer  # source unique (cliquet clones)

__FORGE_COLOR__ = "reseau/transport MCP : flux SSE du hub conforme JSON-RPC"

RACINE = Path(__file__).resolve().parent.parent
HUB = RACINE / "tools" / "nokido_hub.py"
TEMOIN = 'yield ": progress running'

# (etiquette, ancre exacte et UNIQUE, remplacement) — ecrits en LF, adaptes au CRLF du fichier.
PATCH_HUB = [
    ("S1 ouverture du flux SSE",
     '                    yield "data: " + \'{"type":"progress","status":"running"}\' + "\\n\\n"\n',
     '                    # Ouverture = COMMENTAIRE SSE, jamais un `data:` hors JSON-RPC : le client\n'
     '                    # MCP valide chaque `data:` comme un message JSON-RPC et rejetait l\'ancien\n'
     '                    # evenement de progression a chaque appel (2026-09-26,\n'
     '                    # tools/forge_patch_hub_sse_conforme.py). Premier octet immediat conserve.\n'
     '                    yield ": progress running\\n\\n"\n'),
]


def main(argv: list) -> int:
    # Source unique du patch par ancre (cliquet clones, CI de reference du 2026-09-26) :
    # tout ou rien, CRLF, AST, --verifier -- dans forge_patch_hub_elicitation.
    return appliquer([(HUB, PATCH_HUB)], argv, TEMOIN)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
