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
