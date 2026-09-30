"""forge_coffre_reserve_provision -- provisionner le coffre RESERVE (etape 2a du
correctif du coffre, go owner 2026-09-28).

A LANCER SOUS SYSTEM (profil `ps_clm`, ouvert par l'owner). Le coffre reserve scelle en
portee UTILISATEUR, et seul le compte qui scelle dechiffre : sous un autre compte
l'outil REFUSE et le dit -- une copie scellee pour le mauvais compte serait
indechiffrable par le hub, qui retomberait en silence sur le coffre machine.

Ce qu'il fait, SANS JAMAIS AFFICHER une valeur (ni empreinte, ni longueur) :
  - COPIE du coffre machine les quatre porteurs reserves : jeton maitre, jeton
    superviseur, secret de signature JWT, jeton admin ;
  - CREE les trois cles dediees a leur valeur EN SERVICE, calculee par les modules
    eux-memes, pour que rien ne change a la lecture :
      NOKIDO_HMAC_KEY   = ce que lisent les signataires HMAC (cle dediee, sinon maitre),
      FORGE_ENCRYPT_KEY = la cle de `forge_encrypt.get_fernet`, prouvee par un
                          aller-retour chiffre/dechiffre avec l'instance du module,
      LAFORGE_DB_KEY    = ce que rend `forge_db_conn.resolve_key`.
  - GENERE la cle HMAC persona (FORGE_PERSONA_HMAC_KEY, etape 2b-1) -- jamais une
    copie : elle vivait dans un fichier lisible par les comptes bac a sable, sa valeur
    est reputee eventee. Generer = ROTATION : les signatures HMAC persona deja posees
    (verrous de release `hmac-sha256`) ne se verifient plus. D'ou `--rotation-persona`,
    jamais implicite ; une cle deja au coffre reserve n'est jamais regeneree ;
  - verifie chaque ecriture par relecture (`reserve_set`).

Par defaut : PLAN seulement, rien n'est ecrit. `--appliquer` ecrit. Une cle deja au
coffre reserve avec une AUTRE valeur n'est jamais ecrasee : elle est DITE. Rien n'est
retire du coffre machine -- c'est l'etape 2b, qui a son propre go owner.

Codes de sortie : 0 tout est en place (ou le serait, en plan) ; 1 au moins une cle non
provisionnee (source absente, divergence, valeur differente deja scellee) ; 2 refus
prealable (compte, dossier, coffre illisible).
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/coffre-reserve : provisionner le coffre reserve sous SYSTEM"

import argparse
import secrets
from typing import Callable, Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

from nokido_agent.app import forge_machine_vault as mv  # noqa: E402
from nokido_agent.app import forge_secrets as fs  # noqa: E402

# Les quatre porteurs mesures lisibles par `LaForgeSbxOffline` le 2026-09-28, puis les
# quatre noms reserves a l'etape 2b-2 (cles de signature des CapabilityToken et des jetons
# de trame, cle du pont privilegie, cle du journal du pare-feu) : copies de la valeur EN
# SERVICE au coffre machine. Absente du coffre machine -> SOURCE_ABSENTE, dite, rien ecrit.
COPIES = ("FORGE_MCP_TOKEN", "LAFORGE_SUPERVISOR_TOKEN", "LAFORGE_JWT_SECRET",
          "LAFORGE_ADMIN_TOKEN",
          "MCP_DEV_SECRET", "HUB_JWT_SECRET", "LAFORGE_PRIV_BRIDGE_HMAC", "firewall_log_hmac",
          # 2026-09-28 : fichier-cle VeraCrypt de V: (lisible par les comptes bac a sable).
          "LAFORGE_VC_KEYFILE_B64")
# Les cles dediees de l'etape 1 (e736322fc). NOKIDO_HMAC_KEY en est SORTIE le 2026-09-28
# (decision owner) : cle d'integrite partagee, lisible par les comptes qui signent, qui ne
# vit pas au coffre reserve -- voir `forge_secrets.cle_integrite_hmac`.
DEDIEES = ("FORGE_ENCRYPT_KEY", "LAFORGE_DB_KEY")
# Nouvelle valeur, jamais une copie (etape 2b-1, 2026-09-28) -- voir la docstring. Etape
# 2b-3 : la cle privee Ed25519 des JWT du hub, NEUVE -- la generer n'invalide aucune
# signature existante (HS256 reste accepte en transition), donc sans drapeau de rotation.
NOUVELLES = ("FORGE_PERSONA_HMAC_KEY", "LAFORGE_JWT_ED25519_PRIVE")
_EXIGE_ROTATION = frozenset({"FORGE_PERSONA_HMAC_KEY"})


def _nouvelle_cle_ed25519() -> str:
    """Cle privee Ed25519 brute (32 octets), base64url sans remplissage."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    brut = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    return base64.urlsafe_b64encode(brut).rstrip(b"=").decode("ascii")


_GENERATEURS = {
    "FORGE_PERSONA_HMAC_KEY": lambda: secrets.token_urlsafe(48),
    "LAFORGE_JWT_ED25519_PRIVE": _nouvelle_cle_ed25519,
}

A_ECRIRE = "A_ECRIRE"
A_GENERER = "A_GENERER_SUR_GO"
DEJA_EN_PLACE = "DEJA_EN_PLACE"
IDENTIQUE = "IDENTIQUE"
DIFFERENTE = "DIFFERENTE_NON_ECRASEE"
SOURCE_ABSENTE = "SOURCE_ABSENTE"
# Un nom FERME voit sa copie du coffre machine RETIREE (c'est le but) : source absente,
# cle bien au coffre reserve. Ce n'est PAS une absence (faux « NON provisionnees » du 2026-09-28).
EN_PLACE_SOURCE_RETIREE = "EN_PLACE_SOURCE_RETIREE"
ECRITE = "ECRITE"
ECHEC = "ECHEC_ECRITURE"


def _lire_coffre_machine(nom: str) -> tuple[Optional[str], str]:
    v = mv.vault_get(nom)
    return v, ("copie du coffre machine" if v else "ABSENTE du coffre machine")


def _hmac_en_service() -> tuple[Optional[str], str]:
    """Meme chaine que les signataires (`forge_vec_ledger`, `forge_snapshot`, ...)."""
    v = fs.get_secret("NOKIDO_HMAC_KEY")
    if v:
        return v, "cle dediee deja en service"
    v = fs.get_secret("FORGE_MCP_TOKEN")
    return v, ("valeur du maitre (repli en service)" if v else "maitre ABSENT")


def _fernet_en_service() -> tuple[Optional[str], str]:
    """La cle de `get_fernet`, PROUVEE par le module : ce que son instance chiffre, la
    cible le dechiffre, et reciproquement. Sinon rien n'est provisionne."""
    from nokido_agent.app import forge_encrypt as fe
    # Le guichet seul, jamais `os.environ` en direct. Si l'environnement portait une AUTRE
    # cle que celle du guichet, `get_fernet` (qui le lit d'abord) la prefererait : la
    # preuve ci-dessous le voit, et rien n'est provisionne.
    brute = fe.get_secret("FORGE_ENCRYPT_KEY")
    if not brute:
        # 2026-09-28 : plus aucune cle derivee du maitre, ni dans le module ni ici -- la
        # migration de l'etape 1 est faite (cle dediee IDENTIQUE au coffre reserve).
        return None, "aucune cle Fernet dediee en service (jamais derivee du maitre)"
    cand, prov = brute, "cle dediee deja en service"
    try:
        Fernet, _, _ = fe._get_fernet()
        en_service, cible, sonde = fe.get_fernet(), Fernet(cand.encode()), b"sonde-coffre-reserve"
        ok = (cible.decrypt(en_service.encrypt(sonde)) == sonde
              and en_service.decrypt(cible.encrypt(sonde)) == sonde)
    except Exception as exc:  # noqa: BLE001 -- une autre cle fait LEVER decrypt (InvalidToken)
        return None, f"DIVERGENCE avec get_fernet, ou preuve en echec ({type(exc).__name__})"
    if not ok:
        return None, "DIVERGENCE avec get_fernet"
    return cand, prov


def _db_en_service() -> tuple[Optional[str], str]:
    from nokido_agent.app import forge_db_conn as dbc
    v = dbc.resolve_key()
    if not v:
        return None, "aucune passphrase dediee en service (jamais derivee du maitre)"
    return v, "cle dediee deja en service"


def calculer_cibles(lire_machine: Callable = None, hmac: Callable = None,
                    fernet: Callable = None, db: Callable = None) -> dict:
    """{nom: (valeur ou None, provenance)}. La provenance dit D'OU, jamais QUOI."""
    lire_machine = lire_machine or _lire_coffre_machine
    cibles = {nom: lire_machine(nom) for nom in COPIES}
    cibles["FORGE_ENCRYPT_KEY"] = (fernet or _fernet_en_service)()
    cibles["LAFORGE_DB_KEY"] = (db or _db_en_service)()
    return cibles


def planifier(cibles: dict, lire_reserve: Callable = None) -> dict:
    """{nom: etat} face au contenu actuel du coffre reserve. N'ecrit rien."""
    lire_reserve = lire_reserve or mv.reserve_lire
    plan = {}
    for nom, (valeur, _prov) in cibles.items():
        actuelle, etat = lire_reserve(nom)
        if not valeur:
            plan[nom] = EN_PLACE_SOURCE_RETIREE if etat == mv.RESERVE_TROUVE else SOURCE_ABSENTE
            continue
        if etat == mv.RESERVE_TROUVE:
            plan[nom] = IDENTIQUE if actuelle == valeur else DIFFERENTE
        elif etat in (mv.RESERVE_CLE_ABSENTE, mv.RESERVE_COFFRE_ABSENT):
            plan[nom] = A_ECRIRE
        else:
            plan[nom] = f"RESERVE_{etat}"
    return plan


def planifier_nouvelles(lire_reserve: Callable = None, rotation: bool = False) -> dict:
    """{nom: etat} des cles a valeur NOUVELLE. N'ecrit rien, ne rend aucune valeur.

    Deja au coffre reserve -> DEJA_EN_PLACE, jamais regeneree (une regeneration
    silencieuse serait une rotation que personne n'a decidee). Absente -> A_ECRIRE
    seulement sur `rotation`, sinon A_GENERER_SUR_GO."""
    lire_reserve = lire_reserve or mv.reserve_lire
    plan = {}
    for nom in NOUVELLES:
        _valeur, etat = lire_reserve(nom)
        if etat == mv.RESERVE_TROUVE:
            plan[nom] = DEJA_EN_PLACE
        elif etat in (mv.RESERVE_CLE_ABSENTE, mv.RESERVE_COFFRE_ABSENT):
            plan[nom] = A_ECRIRE if (rotation or nom not in _EXIGE_ROTATION) else A_GENERER
        else:
            plan[nom] = f"RESERVE_{etat}"
    return plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--appliquer", action="store_true",
                    help="ecrire au coffre reserve (defaut : plan seulement)")
    ap.add_argument("--rotation-persona", action="store_true",
                    help="generer la NOUVELLE cle HMAC persona (rotation, go owner)")
    a = ap.parse_args(argv)

    manquants = fs.NOMS_RESERVES - set(COPIES) - set(DEDIEES) - set(NOUVELLES)
    if manquants:
        print(f"REFUS : noms reserves non traites par cet outil : {sorted(manquants)}")
        return 2
    sid = mv._sid_courant()
    if sid != mv.RESERVE_COMPTE_SID:
        print(f"REFUS : compte courant {sid or 'ILLISIBLE'} -- le coffre reserve se scelle "
              f"sous SYSTEM ({mv.RESERVE_COMPTE_SID}), profil ps_clm")
        return 2
    if not mv.RESERVE_PATH.parent.is_dir():
        print(f"REFUS : {mv.RESERVE_PATH.parent} absent -- il se cree par l'owner, avec son ACL")
        return 2
    _noms, etat = mv.reserve_list()
    if etat not in (mv.RESERVE_TROUVE, mv.RESERVE_COFFRE_ABSENT):
        print(f"REFUS : coffre reserve {etat} -- rien ne sera ecrit par-dessus")
        return 2

    cibles = calculer_cibles()
    plan = planifier(cibles)
    plan.update(planifier_nouvelles(rotation=a.rotation_persona))
    print(f"coffre reserve : {mv.RESERVE_PATH} ({etat}) -- compte {sid}")
    for nom in (*COPIES, *DEDIEES):
        print(f"  {nom:<26} {plan[nom]:<24} {cibles[nom][1]}")
    for nom in NOUVELLES:
        genre = "rotation" if nom in _EXIGE_ROTATION else "cle neuve"
        print(f"  {nom:<26} {plan[nom]:<24} nouvelle valeur ({genre}), jamais une copie")

    if a.appliquer:
        print("ecriture :")
        for nom in (*COPIES, *DEDIEES):
            if plan[nom] != A_ECRIRE:
                continue
            plan[nom] = ECRITE if mv.reserve_set(nom, cibles[nom][0]) else ECHEC
            print(f"  {nom:<26} {plan[nom]}")
        for nom in NOUVELLES:
            if plan[nom] != A_ECRIRE:
                continue
            plan[nom] = ECRITE if mv.reserve_set(nom, _GENERATEURS[nom]()) else ECHEC
            print(f"  {nom:<26} {plan[nom]}")
    else:
        print("PLAN seulement -- rien n'est ecrit. Relancer avec --appliquer.")

    en_place = ({IDENTIQUE, ECRITE, DEJA_EN_PLACE, EN_PLACE_SOURCE_RETIREE}
                | ({A_ECRIRE} if not a.appliquer else set()))
    restent = sorted(n for n, e in plan.items() if e not in en_place)
    print(f"bilan : {len(plan) - len(restent)}/{len(plan)} en place"
          + (f" ; NON provisionnees : {restent}" if restent else ""))
    print("coffre machine : INCHANGE (retrait = etape 2b, go owner a part)")
    return 1 if restent else 0


if __name__ == "__main__":
    raise SystemExit(main())
