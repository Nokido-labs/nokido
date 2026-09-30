"""redaction_middleware.py — rédige les réponses d'ERREUR du webhub avant qu'elles sortent.

POURQUOI (mesure du 2026-09-19). Le rédacteur du corps existe et fonctionne :
`forge_semantic_firewall.redact_tool_output` est câblé sur `forge_mcp_registry`,
et c'est lui qui remplace les chemins absolus par `[PATH_WIN_1]` dans toute
sortie d'outil MCP. Mais il tient **une voie sur trois** — mesure AST, 27
fichiers de `app/web_hub/` lus, **0 illisible, 0 appel** ; le seul middleware
enregistré est `AuthMiddleware`, qui authentifie et ne rédige rien.

Sur cette surface non rédigée, 34 sites laissent partir le message COMPLET
d'une exception (13 autres le bornent, 6 ne montrent que le type). Un message
d'exception porte des chemins absolus, parfois du SQL, parfois une clef lue
dans un fichier de configuration.

## Pourquoi un MIDDLEWARE, et pas un `exception_handler`

C'est le choix qui décide de tout, et le réflexe échoue :

    raise HTTPException(..., detail=str(e))   11 sites  <- un handler les voit
    return JSONResponse({"error": str(e)})    23 sites  <- il ne les voit PAS

Un `app.exception_handler(...)` aurait couvert **11 sur 34** tout en se relisant
comme une protection générale — exactement le motif « un garde qui tient une
porte sur quatre ». Une réponse rendue par `return` est une réponse NORMALE :
seule une couche qui inspecte ce qui SORT les attrape toutes les deux.

## Portée volontairement ÉTROITE

Seules les réponses `status >= 400` au type JSON sont bufferisées et rédigées.
Tout le reste passe sans être touché ni copié : les erreurs sont rares, donc le
coût est nul, et on ne met pas un filtre sur le chemin d'un téléchargement ou
d'un flux. Un garde large qui ralentit tout finit désarmé.

## Ce que ce middleware ne fait PAS

Il ne remplace pas la correction des sites : un message d'erreur devrait être
court et non technique par construction. Il garantit seulement qu'aucun secret
ne sort **par cette voie**, y compris depuis un site écrit demain. Et il ne
protège pas les réponses de succès — si un secret part dans un `200`, c'est un
défaut de la route, pas du filtre d'erreurs.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

__FORGE_COLOR__ = "immunitaire/guard : redaction des reponses d'erreur du webhub"

# Deux noms d'import pour un seul module selon le chemin d'exécution (dépôt ou
# paquet installé) : les deux doivent marcher, sinon le garde est absent là où
# on croit l'avoir posé.
try:  # pragma: no cover - dépend du mode d'exécution
    from nokido_agent.app.forge_semantic_firewall import redact_tool_output  # type: ignore
except ImportError:  # pragma: no cover
    try:
        from app.forge_semantic_firewall import redact_tool_output  # type: ignore
    except ImportError:
        redact_tool_output = None  # type: ignore

_TYPES_JSON = ("application/json", "application/problem+json")


def _est_json(headers: list[tuple[bytes, bytes]]) -> bool:
    for cle, val in headers:
        if cle.lower() == b"content-type":
            t = val.decode("latin-1", "replace").lower()
            return any(j in t for j in _TYPES_JSON)
    return False


def _rediger_charge_json(texte: str):
    """Rédige les VALEURS d'un corps JSON, pas son texte brut.

    ⚠️ Défaut trouvé par un NR rouge le 2026-09-19, et qui rendait ce middleware
    inutile sur le cas le plus courant : dans du JSON, un chemin Windows s'écrit
    `C:\\\\Users\\\\...` — les backslashes sont ÉCHAPPÉS. Le motif de rédaction
    d'infrastructure cherche `C:\\Users\\...` et ne matche donc RIEN. Appliqué au
    texte sérialisé, le filtre se relisait comme actif et laissait passer tous
    les chemins.

    On décode donc la structure, on rédige chaque chaîne, et on ré-encode. La
    rédaction porte sur les valeurs, jamais sur la syntaxe.

    Repli : si le corps n'est pas du JSON valide malgré son en-tête, on rédige le
    texte brut — moins précis, mais mieux que ne rien faire, et le cas est dit.
    """
    total = {"n": 0, "json": True}

    def _parcourir(obj):
        if isinstance(obj, str):
            redige, bilan = redact_tool_output(obj, outil="webhub:erreur")
            total["n"] += int(bilan.get("secrets_rediges") or 0)
            return redige
        if isinstance(obj, list):
            return [_parcourir(x) for x in obj]
        if isinstance(obj, dict):
            return {k: _parcourir(v) for k, v in obj.items()}
        return obj

    try:
        charge = json.loads(texte)
    except (ValueError, TypeError):
        redige, bilan = redact_tool_output(texte, outil="webhub:erreur-non-json")
        bilan = dict(bilan or {})
        bilan["json"] = False
        return redige, bilan

    sortie = json.dumps(_parcourir(charge), ensure_ascii=False)
    return sortie, {"secrets_rediges": total["n"], "json": True}


class RedactionMiddleware:
    """Middleware ASGI pur, même forme qu'`AuthMiddleware`.

    À enregistrer APRÈS lui : `add_middleware` empile, le dernier inscrit est le
    plus EXTERNE, donc celui-ci voit aussi les réponses produites par
    l'authentification elle-même.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or redact_tool_output is None:
            if redact_tool_output is None and scope.get("type") == "http":
                # Jamais muet : un filtre absent qui se tait laisse croire à une
                # sortie propre.
                logger.error("[redaction] firewall indisponible — les reponses "
                             "d'erreur du webhub sortent NON REDIGEES")
            await self.app(scope, receive, send)
            return

        etat: dict = {"actif": False, "start": None, "morceaux": []}

        async def _envoyer(message):
            t = message.get("type")
            if t == "http.response.start":
                statut = int(message.get("status", 200))
                entetes = list(message.get("headers") or [])
                etat["actif"] = statut >= 400 and _est_json(entetes)
                if not etat["actif"]:
                    await send(message)
                    return
                # On retient l'en-tête : `content-length` devra être recalculé,
                # la rédaction change la longueur du corps.
                etat["start"] = message
                return

            if t == "http.response.body" and etat["actif"]:
                etat["morceaux"].append(message.get("body", b"") or b"")
                if message.get("more_body"):
                    return
                brut = b"".join(etat["morceaux"])
                corps, bilan = brut, None
                try:
                    texte = brut.decode("utf-8")
                    redige, bilan = _rediger_charge_json(texte)
                    corps = redige.encode("utf-8")
                except UnicodeDecodeError:
                    # Corps non textuel annoncé JSON : on ne touche à rien plutôt
                    # que de le corrompre. C'est un ILLISIBLE, et il se dit.
                    logger.warning("[redaction] corps d'erreur non decodable — laisse INTACT")
                except Exception as e:  # noqa: BLE001
                    logger.error("[redaction] echec du filtre (%s: %s) — corps laisse INTACT",
                                 type(e).__name__, str(e)[:120])

                if bilan and bilan.get("secrets_rediges"):
                    logger.warning("[redaction] %s secret(s) retire(s) d'une reponse %s",
                                   bilan.get("secrets_rediges"),
                                   etat["start"].get("status"))

                depart = dict(etat["start"])
                entetes = [(k, v) for k, v in (depart.get("headers") or [])
                           if k.lower() != b"content-length"]
                entetes.append((b"content-length", str(len(corps)).encode("latin-1")))
                depart["headers"] = entetes
                await send(depart)
                await send({"type": "http.response.body", "body": corps, "more_body": False})
                etat["actif"] = False
                return

            await send(message)

        await self.app(scope, receive, _envoyer)
