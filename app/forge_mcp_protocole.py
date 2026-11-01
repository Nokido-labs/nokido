"""forge_mcp_protocole — negociation de version MCP et consignes serveur du hub (cote SERVEUR).

POURQUOI UN MODULE (anti-doublon verifie le 2026-09-24 : `introspect` ne trouve qu'une
negociation cote CLIENT — connecteurs GitHub/ACP). Le hub (`tools/nokido_hub.py`, fichier
CRITIQUE) n'appelle qu'une fonction pure d'ici : la logique se teste sans importer le hub.

DEFAUTS CORRIGES (veilles lot_B_20 et lot_B_15) :
  - `protocolVersion` etait renvoyee en ECHO AVEUGLE : le hub acquiescait a n'importe quelle
    version, meme inconnue. Spec MCP : le serveur rend la version demandee s'il la supporte,
    SINON une version qu'il supporte (de preference la plus recente) — et le client decide.
  - `initialize` ne portait aucun champ `instructions` : un client MCP ne recevait la doctrine
    que s'il importait lui-meme RULES_SHARED. ATTENTION au cout : ces consignes entrent dans
    le prompt systeme de CHAQUE session cliente, a chaque tour — elles restent donc tres
    courtes et renvoient a la doctrine complete au lieu de la recopier.

MESURE MANQUANTE, DITE : la version reellement envoyee par les clients n'est pas lisible dans
les journaux du hub (aucune ligne `[mcp/initialize]` dans logs/*hub*.log le 24/09). D'ou
l'avertissement journalise ci-dessous quand une version inconnue arrive.
"""
from __future__ import annotations

__FORGE_COLOR__ = "reseau/negociation du protocole MCP et consignes serveur du hub"

# Versions de la spec MCP que le hub sait servir (outils seulement, sans etat).
VERSIONS_SUPPORTEES = ("2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
VERSION_PAR_DEFAUT = "2025-03-26"   # client qui n'en demande aucune (comportement historique)

INSTRUCTIONS_SERVEUR = (
    "Nokido. Ecrire dans le depot : governed_edit. Executer : run (long : run_job). "
    "Chercher : introspect ou rag avant de lire. Confirmer avec l'owner tout geste "
    "irreversible. UNKNOWN n'est pas NO : une source muette ne prouve rien. "
    "Champ explanation de chaque outil : pourquoi cet appel, en une phrase (journalise). "
    "Doctrine : RULES_SHARED.md."
)


def negocier_version(demandee) -> tuple:
    """(version_rendue, avertissement | None).

    - aucune demande -> VERSION_PAR_DEFAUT (inchange par rapport a l'historique) ;
    - version supportee -> la meme (echo LEGITIME) ;
    - version inconnue -> la plus recente supportee, et on le DIT.
    """
    v = (str(demandee).strip() if demandee else "")
    if not v:
        return VERSION_PAR_DEFAUT, None
    if v in VERSIONS_SUPPORTEES:
        return v, None
    return VERSIONS_SUPPORTEES[0], (
        "protocolVersion demandee %r non supportee ; rendue %r (versions : %s)"
        % (v[:40], VERSIONS_SUPPORTEES[0], ", ".join(VERSIONS_SUPPORTEES)))


# ── MCP 2026-07-28, lot 1 ADDITIF ───────────────────────────────────────────────────────
# Sources (docs ingerees) : specification/2026-07-28/basic/transports/streamable-http.md
# (en-tetes MCP-Protocol-Version / Mcp-Method / Mcp-Name, 400), basic/index.md (-32020
# HeaderMismatch, -32022 UnsupportedProtocolVersion), server/discover.md, utilities/caching.md.
# Validation STRICTE seulement si la requete annonce 2026-07-28+ : les clients 2025-11-25 ne
# voient rien changer. UNKNOWN (non code) : format exact du sentinel Base64 de Mcp-Name ;
# Mcp-Param-*; traceparent/tracestate/baggage dans _meta (lus ailleurs via traceparent HTTP).
VERSION_2026 = "2026-07-28"
META_NS = "io.modelcontextprotocol/"
ERR_HEADER_MISMATCH = -32020
ERR_UNSUPPORTED_VERSION = -32022
TTL_TOOLS_LIST_MS = 60_000
_NOM_PAR_METHODE = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}


def _entetes_min(headers) -> dict:
    try:
        return {str(k).lower(): v for k, v in dict(headers or {}).items()}
    except Exception:  # noqa: BLE001 - entetes illisibles : comme absents
        return {}


def _meta(body) -> dict:
    p = body.get("params") if isinstance(body, dict) else None
    m = p.get("_meta") if isinstance(p, dict) else None
    return m if isinstance(m, dict) else {}


def _est_2026_ou_plus(v) -> bool:
    return isinstance(v, str) and v >= "2026-"


def annonce_2026(headers, body) -> bool:
    """Vrai si l'en-tete OU `_meta` annonce une version >= 2026 (supportee ou non)."""
    h = _entetes_min(headers).get("mcp-protocol-version")
    return _est_2026_ou_plus(h) or _est_2026_ou_plus(_meta(body).get(META_NS + "protocolVersion"))


import base64 as _b64  # noqa: E402


def valider_requete(headers, body, schema_outil=None):
    """None si OK / non concerne ; sinon (http_status, code_jsonrpc, message).
    `schema_outil` : inputSchema de l'outil appele (optionnel) pour valider les Mcp-Param-*."""
    if not annonce_2026(headers, body):
        return None
    h = _entetes_min(headers)
    meta_v = _meta(body).get(META_NS + "protocolVersion")
    hv = h.get("mcp-protocol-version")
    for v in (hv, meta_v):
        if v is not None and v not in VERSIONS_SUPPORTEES:
            return 400, ERR_UNSUPPORTED_VERSION, "UnsupportedProtocolVersion: %r (supportees : %s)" % (
                str(v)[:40], ", ".join(VERSIONS_SUPPORTEES)), {
                "supported": list(VERSIONS_SUPPORTEES), "requested": str(v)[:40]}
    if not hv:
        return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: en-tete MCP-Protocol-Version absent"
    if meta_v is not None and meta_v != hv:
        return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: MCP-Protocol-Version != _meta.protocolVersion"
    if not isinstance(body, dict):
        return None
    method = body.get("method")
    if not isinstance(method, str):
        return None  # reponse client / corps sans methode : rien a refleter
    if h.get("mcp-method") is None:
        return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: en-tete Mcp-Method absent"
    if h["mcp-method"] != method:
        return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: Mcp-Method != method"
    champ = _NOM_PAR_METHODE.get(method)
    if champ:
        attendu = (body.get("params") or {}).get(champ)
        recu = h.get("mcp-name")
        if recu is None:
            return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: en-tete Mcp-Name absent"
        ok, recu = _decoder_valeur(recu)
        if not ok:
            return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: Mcp-Name illisible (Base64/caracteres)"
        if recu != attendu:
            return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: Mcp-Name != params.%s" % champ
    if method == "tools/call" and isinstance(schema_outil, dict):
        return _valider_params(h, body, schema_outil)
    return None


def _decoder_valeur(v: str):
    """(ok, valeur). Sentinel `=?base64?...?=` (minuscules, exact) -> UTF-8 decode ; sinon tel quel.
    Base64 ou UTF-8 invalide -> (False, None). Valeur claire : ASCII visible/espace/tab seulement."""
    if v.startswith("=?base64?") and v.endswith("?=") and len(v) >= 11:
        try:
            return True, _b64.b64decode(v[9:-2], validate=True).decode("utf-8")
        except Exception:  # noqa: BLE001 - base64/UTF-8 invalide = en-tete invalide
            return False, None
    if v.startswith("=?base64?"):
        return False, None
    if any(not (c == " " or c == "\t" or "!" <= c <= "~") for c in v):
        return False, None
    return True, v


def _chaine_param(val):
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, str)):
        return str(val)
    return None


def _valider_params(h: dict, body: dict, schema: dict):
    """Mcp-Param-{Name} (streamable-http, Server Behavior for Custom Headers). Seules les proprietes
    `x-mcp-header` atteignables par `properties` seules sont reconnues ; le reste est ignore."""
    args = (body.get("params") or {}).get("arguments")
    args = args if isinstance(args, dict) else {}

    def parcourir(sch, valeurs):
        props = sch.get("properties") if isinstance(sch, dict) else None
        for cle, sub in (props or {}).items():
            if not isinstance(sub, dict):
                continue
            val = valeurs.get(cle) if isinstance(valeurs, dict) else None
            nom = sub.get("x-mcp-header")
            if isinstance(nom, str) and nom:
                yield nom, val
            elif sub.get("type") == "object":
                yield from parcourir(sub, val)

    for nom, val in parcourir(schema, args):
        recu = h.get("mcp-param-" + nom.lower())
        if val is None:
            continue  # valeur absente/null : le serveur n'attend pas l'en-tete
        if recu is None:
            return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: en-tete Mcp-Param-%s absent" % nom
        ok, dec = _decoder_valeur(recu)
        if not ok:
            return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: Mcp-Param-%s invalide" % nom
        if dec != _chaine_param(val):
            return 400, ERR_HEADER_MISMATCH, "HeaderMismatch: Mcp-Param-%s != corps" % nom
    return None


def declared_depuis_meta(body, declared_defaut: str) -> str:
    """Nom DECLARE (jamais `principal`) : `_meta clientInfo.name` si la requete annonce 2026."""
    meta = _meta(body)
    if not _est_2026_ou_plus(meta.get(META_NS + "protocolVersion")):
        return declared_defaut
    ci = meta.get(META_NS + "clientInfo")
    nom = ci.get("name") if isinstance(ci, dict) else None
    if isinstance(nom, str) and nom.strip():
        return nom.upper().strip()
    return declared_defaut


_RE_TRACEPARENT = __import__("re").compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


def _traceparent_valide(v) -> bool:
    if not isinstance(v, str) or not _RE_TRACEPARENT.match(v):
        return False
    return set(v[3:35]) != {"0"} and set(v[36:52]) != {"0"}


from urllib.parse import unquote as _unquote  # noqa: E402


def _baggage(v) -> dict:
    out: dict = {}
    if not isinstance(v, str):
        return out
    for entree in v.split(","):
        kv = entree.split(";", 1)[0]
        if "=" not in kv:
            continue
        k, _, val = kv.partition("=")
        k, val = _unquote(k.strip()), _unquote(val.strip())
        if k:
            out[k] = val
    return out


def trace_depuis_meta(body, headers):
    """W3C trace context : params._meta d'abord, sinon en-tete HTTP. Invalide -> None, sans exception."""
    try:
        meta = _meta(body)
        h = _entetes_min(headers)
        src = meta if _traceparent_valide(meta.get("traceparent")) else (
            h if _traceparent_valide(h.get("traceparent")) else None)
        if src is None:
            return None
        ts = src.get("tracestate")
        return {"traceparent": src["traceparent"],
                "tracestate": ts if isinstance(ts, str) else None,
                "baggage": _baggage(src.get("baggage"))}
    except Exception:  # noqa: BLE001 - jamais d'exception
        return None


def declared_depuis_initialize(body, declared_defaut: str) -> str:
    """Client legacy : nom DECLARE (jamais `principal`) = params.clientInfo.name du handshake initialize."""
    try:
        if not isinstance(body, dict) or body.get("method") != "initialize":
            return declared_defaut
        p = body.get("params")
        ci = p.get("clientInfo") if isinstance(p, dict) else None
        nom = ci.get("name") if isinstance(ci, dict) else None
        if isinstance(nom, str) and nom.strip():
            return nom.upper().strip()
    except Exception:  # noqa: BLE001
        __import__("logging").getLogger(__name__).debug(
            "initialize illisible : declared par defaut conserve", exc_info=True)
    return declared_defaut


def habiller_tools_list(outils, annonce_2026: bool) -> dict:
    """Resultat tools/list. 2025 : inchange. 2026 : ordre deterministe + ttlMs + cacheScope.
    Portee `private` : la liste depend du ring et de l'agent."""
    if not annonce_2026:
        return {"tools": outils}
    tries = sorted(outils, key=lambda t: str(t.get("name", "")))
    return {"resultType": "complete", "tools": tries, "ttlMs": TTL_TOOLS_LIST_MS, "cacheScope": "private"}


def resultat_discover(capabilities: dict, nom: str, version: str, instructions: str = "") -> dict:
    r = {
        "resultType": "complete",
        "supportedVersions": list(VERSIONS_SUPPORTEES),
        "capabilities": capabilities,
        "_meta": {META_NS + "serverInfo": {"name": nom, "version": version}},
        "ttlMs": TTL_TOOLS_LIST_MS,
        "cacheScope": "public",
    }
    if instructions:
        r["instructions"] = instructions
    return r
