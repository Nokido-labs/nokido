"""Coffre cloisonne : les comptes du bac ne lisent pas les identites ring <= 3.

__FORGE_COLOR__ = "immunitaire/reconnaissance-du-soi"

Logique pure. Mode "observation" : signale `aurait_refuse:<code>` sans bloquer.
Migration : plan en dry-run uniquement ; la migration reelle est une commande
owner (tray) et ce module la refuse (PermissionError). Aucune valeur de secret
n'apparait dans les plans ni dans les journaux. Client d'echange minimal inclus
(RFC 8693 demande, RFC 9449 preuve avec cle ephemere).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from app import forge_dpop
from app import forge_token_exchange as te

RING_MAX_CLOISONNE = 3


def decision_lecture(compte: str, genre: str, ring: int, comptes_bac: Iterable[str],
                     mode: str = "observation", principal_exempte: str | None = None) -> Tuple[bool, str]:
    """(autorise, raison). Refus : compte du bac, genre identite, ring <= 3.

    `principal_exempte` (COF-1 tranche 1, plan owner 30/10) : le service PROUVE par le superviseur dont le lecteur
    descend (le hub : il compare les Bearer et verifie les codes HMAC des boites aux lettres, il lui faut les jetons
    en clair). Seule une preuve deja etablie par l'appelant l'exempte ; None = decision d'avant."""
    if principal_exempte:
        return True, "exempte:%s" % principal_exempte
    if compte in set(comptes_bac) and genre == "identite" and ring <= RING_MAX_CLOISONNE:
        if mode == "observation":
            return True, "aurait_refuse:bac_ring_le_3"
        return False, "bac_ring_le_3"
    return True, "ok"


def planifier_migration(entrees: Iterable[Dict[str, Any]], dry_run: bool = True) -> Dict[str, Any]:
    """Liste les identites ring <= 3 a deplacer vers le coffre owner. Noms seulement."""
    if not dry_run:
        raise PermissionError("migration reelle = commande owner au tray, jamais ici")
    dep: List[Dict[str, Any]] = [
        {"nom": e["nom"], "ring": e["ring"], "vers": "coffre_owner"}
        for e in entrees if e.get("genre") == "identite" and e.get("ring", 99) <= RING_MAX_CLOISONNE]
    return {"execute": False, "deplacements": dep}


def cle_ephemere():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(ec.SECP256R1())


def demande_echange(jeton_job: str, job_id: str, audience: str, scope: str, cle) -> Dict[str, Any]:
    return {"grant_type": te.GRANT_TYPE, "subject_token": jeton_job,
            "subject_token_type": te.TYPE_JOB, "job_id": job_id, "audience": audience,
            "scope": scope, "dpop_jwk": forge_dpop.jwk_public(cle)}


def preuve_appel(cle, methode: str, uri: str, jeton_acces: str) -> str:
    return forge_dpop.creer_preuve(methode, uri, jeton_acces=jeton_acces, cle=cle)
