# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/authz-routes"
PATCH : `admin_ingest_repo` passe par le garde d'auth CENTRAL.

LE DEFAUT
=========
La route refaisait sa propre verification au lieu d'appeler `_admin_tok_ok` :

    expected = os.getenv("FORGE_MCP_TOKEN", "")
    if expected and tok != expected:
        return 401

`if expected and ...` : quand la variable est ABSENTE de l'environnement du process,
`expected` vaut "" et la condition entiere est fausse — le controle est SAUTE et la
requete passe. L'authentification se desarme quand sa source se tait.

`_admin_tok_ok`, le garde central du meme fichier, avait deja appris la lecon et
fait l'inverse : sans jeton attendu il REFUSE, sauf `LAFORGE_NO_AUTH=1` explicite et
alors seulement depuis le loopback. La copie avait diverge de l'original — c'est
l'anti-dup applique a un controle d'acces, ou une duplication ne coute pas de la
lisibilite mais de la securite.

PORTEE MESUREE, a ne pas surestimer : UNE route, pas la surface admin. Les autres
routes appellent bien `_admin_tok_ok`. `admin_ingest_repo` ecrit dans le RAG
(ingestion d'un repertoire local), elle n'execute pas de code.

Ce patch ne reecrit pas la logique : il SUPPRIME la copie et appelle le garde. Le
comportement devient identique aux autres routes admin, derogation loopback comprise.

Harnais REUTILISE : `forge_patch_muted_paths.campagne()`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_patch_muted_paths import campagne  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "tools" / "nokido_hub.py"
SENTINELLE = "admin_ingest_repo : garde central"

BLOCS = [
    (r'''        tok = request.headers.get("authorization", "")
        tok = tok[7:].strip() if tok.lower().startswith("bearer ") else tok.strip()
        expected = _os.getenv("FORGE_MCP_TOKEN", "")
        if expected and tok != expected:
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()''',

     r'''        # admin_ingest_repo : garde central, plus de copie locale. L'ancienne
        # verification faisait `if expected and tok != expected` : quand
        # FORGE_MCP_TOKEN etait absent de l'environnement, `expected` valait "" et
        # le controle entier etait SAUTE — la route passait sans jeton. Le garde
        # central `_admin_tok_ok` refuse dans ce cas (sauf LAFORGE_NO_AUTH=1, et
        # seulement depuis le loopback) : une copie d'un controle d'acces finit par
        # diverger de l'original, et ici la divergence se payait en securite.
        if not _admin_tok_ok(request):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        try:
            body = await request.json()'''),
]


def main(argv=None) -> int:
    return campagne(CIBLE, SENTINELLE, BLOCS, suffixe="ingest-authz",
                    note_finale="Le hub doit etre REDEMARRE pour charger ce code.",
                    argv=argv)


if __name__ == "__main__":
    sys.exit(main())
