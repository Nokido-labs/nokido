#!/usr/bin/env python
"""forge_patch_hub_elicitation.py — cable l'elicitation MCP dans le hub (fichiers CRITIQUES).

POURQUOI UN SCRIPT : `tools/nokido_hub.py` et `app/forge_mcp_registry.py` sont CRITICAL_FILE,
`governed_edit` les refuse. Ce script est commite, relu, puis lance par `trusted_script`.
La logique vit dans `app/forge_mcp_elicitation.py` (NR `tests/nr/test_mcp_elicitation_nr.py`) ;
ici, seulement les points d'appel.

CE QUE LE PATCH CABLE (accord owner 2026-09-26, chantier « leviers Claude Code ») :
  hub  H1  `initialize` : l'id de session rendu au client est enregistre avec ses capacites.
  hub  H2  POST qui porte une REPONSE du client (pas de `method`) : routee vers la demande
           de SA session et de SON agent -> 202 ; sinon 400.
  hub  H3  `tools/call` : `sse_requis(nom, args)` ajoute les outils qui questionnent l'owner
           au flux SSE historique.
  hub  H4  le heartbeat SSE devient un flux qui porte aussi les `elicitation/create`.
  reg  R1  `hub action=confirmer_owner` (schema) ; R2 son aiguillage.
  Chaque point retombe sur le comportement historique si le module est illisible.

USAGE
  --verifier   ancres uniques + AST apres patch, pour les deux fichiers ; n'ecrit RIEN.
  (defaut)     applique : tout ou rien. Deja applique -> rien a faire (idempotent).
  Retour arriere : `git checkout -- tools/nokido_hub.py app/forge_mcp_registry.py`.
  Effet reel : au prochain redemarrage du hub seulement (geste coordonne, accord owner).
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

__FORGE_COLOR__ = "reseau/elicitation MCP : patch des points d'appel du hub"

RACINE = Path(__file__).resolve().parent.parent
HUB = RACINE / "tools" / "nokido_hub.py"
REGISTRE = RACINE / "app" / "forge_mcp_registry.py"
TEMOIN = "forge_mcp_elicitation"

# (etiquette, ancre exacte et UNIQUE, remplacement) — ecrits en LF, adaptes au CRLF du fichier.
PATCH_HUB = [
    ("H1 enregistrement de session",
     '            except Exception:  # noqa: BLE001 - muet-ok : un log ne casse jamais un handshake\n'
     '                pass\n',
     '            except Exception:  # noqa: BLE001 - muet-ok : un log ne casse jamais un handshake\n'
     '                pass\n'
     '            # Elicitation (2026-09-26) : l\'id rendu ici est celui que le client renverra ;\n'
     '            # ses capacites y sont attachees pour savoir, au tools/call, s\'il sait repondre.\n'
     '            _mcp_sid = __import__("uuid").uuid4().hex\n'
     '            try:\n'
     '                from nokido_agent.app.forge_mcp_elicitation import enregistrer_session as _es\n'
     '\n'
     '                _es(_mcp_sid, _ci.get("name", "?"), _pv, _cc)\n'
     '            except Exception as _e_es:  # noqa: BLE001 - un registre ne casse jamais un handshake\n'
     '                logger.warning("[mcp/initialize] registre d\'elicitation non ecrit : %s", _e_es)\n'),
    ("H1 id de session rendu",
     '                headers={"Mcp-Session-Id": __import__("uuid").uuid4().hex},\n',
     '                headers={"Mcp-Session-Id": _mcp_sid},\n'),
    ("H2 reponse du client",
     '        if method.startswith("notifications/") or bid is None:\n'
     '            from starlette.responses import Response as _Resp\n'
     '\n'
     '            return _Resp(status_code=202)\n',
     '        if method.startswith("notifications/") or bid is None:\n'
     '            from starlette.responses import Response as _Resp\n'
     '\n'
     '            return _Resp(status_code=202)\n'
     '\n'
     '        # Reponse du CLIENT a une requete du hub (elicitation, 2026-09-26) : aucune `method`,\n'
     '        # un `id`. Elle ne resout que la demande de SA session et de SON agent.\n'
     '        try:\n'
     '            from nokido_agent.app.forge_mcp_elicitation import est_reponse_client as _est_rep\n'
     '        except Exception:  # noqa: BLE001 - module illisible : le hub sert quand meme\n'
     '            _est_rep = None\n'
     '        if _est_rep is not None and _est_rep(body):\n'
     '            from starlette.responses import Response as _Resp\n'
     '            from nokido_agent.app.forge_mcp_elicitation import recevoir_reponse as _rr\n'
     '\n'
     '            _ok_rep, _pourquoi = _rr(body, request.headers.get("Mcp-Session-Id", ""), agent_hdr)\n'
     '            logger.info("[mcp/elicitation] reponse client id=%s acceptee=%s (%s)",\n'
     '                        str(bid)[:60], _ok_rep, _pourquoi)\n'
     '            return _Resp(status_code=202 if _ok_rep else 400)\n'),
    ("H3 outils qui questionnent l'owner",
     '            if use_sse:\n'
     '\n'
     '                async def sse_gen():\n',
     '            if not use_sse and "text/event-stream" in accept:\n'
     '                try:\n'
     '                    from nokido_agent.app.forge_mcp_elicitation import sse_requis as _sse_requis\n'
     '\n'
     '                    use_sse = _sse_requis(name, args)\n'
     '                except Exception:  # noqa: BLE001 - sans le module : liste historique\n'
     '                    pass\n'
     '            if use_sse:\n'
     '\n'
     '                async def sse_gen():\n'),
    ("H4 flux SSE porteur des requetes",
     '                    _tk = asyncio.ensure_future(_tool_call(name, args, ring, agent=agent_hdr))\n'
     '                    while True:\n'
     '                        try:\n'
     '                            r2 = await asyncio.wait_for(asyncio.shield(_tk), timeout=15.0)\n'
     '                            break\n'
     '                        except asyncio.TimeoutError:\n'
     '                            yield ": ping\\n\\n"\n',
     '                    # Elicitation (2026-09-26) : le tool tourne avec un CANAL ; ses requetes\n'
     '                    # vers le client (`elicitation/create`) partent dans ce flux, entre les\n'
     '                    # pings du heartbeat (15 s). Module illisible : boucle historique.\n'
     '                    try:\n'
     '                        from nokido_agent.app.forge_mcp_elicitation import (\n'
     '                            Canal as _Canal, flux as _flux, lancer_avec_canal as _lancer)\n'
     '                    except Exception:  # noqa: BLE001\n'
     '                        _Canal = None\n'
     '                    if _Canal is not None:\n'
     '                        _canal = _Canal(request.headers.get("Mcp-Session-Id", ""), agent_hdr)\n'
     '                        _tk = _lancer(_tool_call(name, args, ring, agent=agent_hdr), _canal)\n'
     '                        async for _evt in _flux(_tk, _canal):\n'
     '                            yield _evt\n'
     '                        r2 = _tk.result()\n'
     '                    else:\n'
     '                        _tk = asyncio.ensure_future(_tool_call(name, args, ring, agent=agent_hdr))\n'
     '                        while True:\n'
     '                            try:\n'
     '                                r2 = await asyncio.wait_for(asyncio.shield(_tk), timeout=15.0)\n'
     '                                break\n'
     '                            except asyncio.TimeoutError:\n'
     '                                yield ": ping\\n\\n"\n'),
]

PATCH_REGISTRE = [
    ("R1 schema de hub",
     '                                "quota_model",\n'
     '                                "quota_report",\n'
     '                            ],\n',
     '                                "quota_model",\n'
     '                                "quota_report",\n'
     '                                "confirmer_owner",\n'
     '                            ],\n'),
    ("R2 aiguillage de hub",
     '        if action == "whoami":\n'
     '            return await self.handle_whoami(args, agent, ring)\n',
     '        if action == "whoami":\n'
     '            return await self.handle_whoami(args, agent, ring)\n'
     '        if action == "confirmer_owner":\n'
     '            # Elicitation MCP : le dialogue s\'affiche chez l\'owner, le modele ne le remplit\n'
     '            # pas. Seul etat qui autorise : ACCEPTE (app/forge_mcp_elicitation.py).\n'
     '            import json as _json\n'
     '            from nokido_agent.app.forge_mcp_elicitation import confirmer_owner\n'
     '\n'
     '            r = await confirmer_owner(str(args.get("message") or ""), str(args.get("detail") or ""))\n'
     '            return _json.dumps(r, ensure_ascii=False)\n'),
]


def _preparer(cible: Path, patch: list, temoin: str = TEMOIN) -> tuple:
    """(texte_patche | None, rapport, ok). None = rien a ecrire (deja applique) ou ABANDON.

    SOURCE UNIQUE des patchs du hub par ancre (cliquet clones, 2026-09-26) : les scripts
    ordres_bureau et sse_conforme l'importent. `temoin` = la chaine dont la presence
    dans la cible dit « deja applique »."""
    if not cible.exists():
        return None, ["%s : ABSENT" % cible.name], False
    src = cible.read_bytes().decode("utf-8")
    if temoin in src:
        return None, ["%s : deja applique (temoin %r present)" % (cible.name, temoin)], True
    nl = "\r\n" if "\r\n" in src else "\n"
    out, rapport, ok = src, [], True
    for etiquette, ancre, remplacement in patch:
        a, r = ancre.replace("\n", nl), remplacement.replace("\n", nl)
        n = out.count(a)
        rapport.append("%s : %s — ancre trouvee %d fois" % (cible.name, etiquette, n))
        if n != 1:
            ok = False
            continue
        out = out.replace(a, r, 1)
    if not ok:
        return None, rapport + ["%s : ABANDON, une ancre n'est pas unique" % cible.name], False
    try:
        ast.parse(out, filename=str(cible))
    except SyntaxError as e:
        return None, rapport + ["%s : AST CASSE apres patch (%s) — ABANDON" % (cible.name, e)], False
    rapport.append("%s : AST OK, +%d octets" % (cible.name, len(out) - len(src)))
    return out, rapport, True


def appliquer(plan: list, argv: list, temoin: str = TEMOIN) -> int:
    """Tout ou rien sur `plan` = [(cible, patch), ...] ; `--verifier` n'ecrit jamais."""
    verifier = "--verifier" in argv
    prets, tout_ok = [], True
    for cible, patch in plan:
        out, rapport, ok = _preparer(cible, patch, temoin)
        print("\n".join("[patch] " + ligne for ligne in rapport))
        tout_ok = tout_ok and ok
        if out is not None:
            prets.append((cible, out))
    if not tout_ok:
        print("[patch] ABANDON : RIEN n'est ecrit (tout ou rien)")
        return 2
    if verifier:
        print("[patch] --verifier : %d fichier(s) a patcher, RIEN n'est ecrit" % len(prets))
        return 0
    for cible, out in prets:
        cible.write_bytes(out.encode("utf-8"))
        print("[patch] ecrit : %s" % cible)
    print("[patch] effet au prochain redemarrage du hub seulement (accord owner)")
    return 0


def main(argv: list) -> int:
    return appliquer([(HUB, PATCH_HUB), (REGISTRE, PATCH_REGISTRE)], argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
