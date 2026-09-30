"""forge_portail_cle -- cle Ed25519 des sessions du portail (decision owner 2026-09-28).

Le portail signait ses sessions en HS256 avec la cle des JWT du hub : tout lecteur de la cle
fabriquait une session. Desormais il signe en EdDSA avec SA cle, et le hub (comme le portail)
ne verifie qu'avec la cle publique ENREGISTREE au registre des cles d'agents (agent WEBHUB).

Deux gestes owner, dans l'ordre :

  1. SOUS LE COMPTE DU PORTAIL (jamais SYSTEM) :
       forge_portail_cle.py --generer --pub <fichier.json>
     -> cle PRIVEE au coffre PERSONNEL du compte (keyring, service du guichet) ; cle PUBLIQUE
        (JWK nue) dans <fichier.json>. Rien n'est affiche de la cle privee : l'empreinte
        (jkt) seulement. Une cle existante n'est remplacee qu'avec --remplacer (rotation).
  2. SOUS SYSTEM (profil ps_clm) :
       forge_portail_cle.py --enregistrer --pub <fichier.json>
     -> la cle publique entre au registre (dossier owner %ProgramData%\\NokidoCles).

Tant que 2 n'est pas fait, le portail continue en HS256 (transition) : il n'emet jamais une
session que le hub ne saurait pas verifier. Une rotation ajoute une GENERATION ; l'ancienne
reste acceptee jusqu'a sa revocation au registre (`forge_agent_keys.transition`).
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/cle-portail : generer et enregistrer la cle Ed25519 des sessions du portail"

import argparse
import base64
import json

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

from pathlib import Path  # noqa: E402

NOM_PRIVE = "LAFORGE_PORTAIL_ED25519_PRIVE"
AGENT = "WEBHUB"


def _sous_system() -> bool:
    try:
        from nokido_agent.app import forge_machine_vault as mv

        return mv._sid_courant() == mv.RESERVE_COMPTE_SID
    except Exception:  # noqa: BLE001 - compte illisible : on ne suppose jamais SYSTEM
        return False


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def _ecrire_coffre_personnel(nom: str, valeur: str) -> bool:
    """Keyring du COMPTE COURANT, service du guichet (`forge_secrets` le lit en source wcm).
    Jamais le coffre machine : il est lisible par tous les comptes."""
    from nokido_agent.app.forge_env_crypt import _keyring_set

    return bool(_keyring_set(nom, valeur))


def _lire_guichet(nom: str):
    from nokido_agent.app.forge_secrets import get_secret

    return get_secret(nom)


def generer(chemin_pub: Path, ecrire=None, lire=None, remplacer: bool = False) -> str:
    ecrire = ecrire or _ecrire_coffre_personnel
    lire = lire or _lire_guichet
    if _sous_system():
        print("REFUS : a lancer sous le compte du PORTAIL, pas sous SYSTEM -- la cle privee "
              "doit vivre dans le coffre personnel du compte qui signe.")
        raise SystemExit(2)
    if lire(NOM_PRIVE) and not remplacer:
        print("REFUS : une cle privee du portail existe deja. --remplacer pour une rotation "
              "(puis --enregistrer la nouvelle cle publique sous SYSTEM).")
        raise SystemExit(2)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from nokido_agent.app.forge_agent_keys import _thumbprint

    cle = Ed25519PrivateKey.generate()
    brut = cle.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    publique = cle.public_key().public_bytes(serialization.Encoding.Raw,
                                             serialization.PublicFormat.Raw)
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64(publique)}
    if not ecrire(NOM_PRIVE, _b64(brut)):
        print("ECHEC : la cle privee n'a pas ete ecrite au coffre personnel -- rien d'autre "
              "n'est fait.")
        raise SystemExit(1)
    chemin_pub = Path(chemin_pub)
    chemin_pub.parent.mkdir(parents=True, exist_ok=True)
    chemin_pub.write_text(json.dumps(jwk, sort_keys=True), encoding="utf-8")
    jkt = _thumbprint(jwk)
    print(f"cle generee : jkt={jkt}")
    print(f"  publique -> {chemin_pub}")
    print(f"  privee   -> coffre personnel de ce compte ({NOM_PRIVE})")
    print("ETAPE SUIVANTE (owner, sous ps_clm) : forge_portail_cle.py --enregistrer --pub "
          f"{chemin_pub}")
    return jkt


def enregistrer(chemin_pub: Path) -> dict:
    if not _sous_system():
        print("REFUS : l'enregistrement se fait sous SYSTEM (profil ps_clm) -- le registre "
              "n'est inscriptible que par SYSTEM et les administrateurs.")
        raise SystemExit(2)
    jwk = json.loads(Path(chemin_pub).read_text(encoding="utf-8"))
    try:
        x_ok = len(base64.urlsafe_b64decode(jwk.get("x", "") + "==")) == 32
    except Exception:  # noqa: BLE001
        x_ok = False
    if (not isinstance(jwk, dict) or set(jwk) != {"kty", "crv", "x"}
            or jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519" or not x_ok):
        print("REFUS : le fichier n'est pas une cle PUBLIQUE Ed25519 nue (kty, crv, x).")
        raise SystemExit(2)
    from nokido_agent.app.forge_agent_keys import enregistrer as _enregistrer

    entree = _enregistrer(AGENT, {"kty": "OKP", "crv": "Ed25519", "x": jwk["x"]})
    print(f"enregistree : agent {AGENT}, jkt={entree['jkt']}, generation={entree['generation']}")
    return entree


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    geste = ap.add_mutually_exclusive_group(required=True)
    geste.add_argument("--generer", action="store_true",
                       help="sous le compte du portail : generer la paire de cles")
    geste.add_argument("--enregistrer", action="store_true",
                       help="sous SYSTEM : enregistrer la cle publique au registre")
    ap.add_argument("--pub", required=True, help="fichier JSON de la cle publique")
    ap.add_argument("--remplacer", action="store_true",
                    help="--generer : remplacer une cle existante (rotation)")
    a = ap.parse_args(argv)
    if a.generer:
        generer(Path(a.pub), remplacer=a.remplacer)
    else:
        enregistrer(Path(a.pub))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
