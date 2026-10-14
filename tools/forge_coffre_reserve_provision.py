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
import os
import secrets
from pathlib import Path
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

# --- Machine NEUVE (decision owner du 2026-10-09, « Go, coffre reserve ») ------------------
# Mesure 4 de l'organisme sur VM : aucun coffre n'existe, les COPIES n'ont pas de source
# (TaskExecutor : « FORGE_MCP_TOKEN manquant »). `--machine-neuve` GENERE chaque nom reserve
# absent des DEUX coffres et le scelle au coffre RESERVE -- jamais au coffre machine, lisible
# par les comptes bac a sable (faille du 2026-09-28). Une valeur presente, ou qu'elle soit,
# n'est jamais regeneree. Le fichier-cle VeraCrypt n'a pas de sens sans volume chiffre : dit.
HORS_MACHINE_NEUVE = frozenset({"LAFORGE_VC_KEYFILE_B64"})
A_GENERER_NEUF = "A_GENERER_MACHINE_NEUVE"
# Codes d'appariement OAuth des pairs (PairMCP, GithubBridgeMCP) : coffre MACHINE, lus par
# forge_bridge_launch. Decision owner du 2026-10-09 : generes, scelles, AFFICHES UNE FOIS -- par
# l'installeur, qui lit puis efface `A_NOTER` (ACL SYSTEM + Administrateurs, jamais le depot).
APPARIEMENTS = ("NOKIDO_PAIR_OAUTH_APPARIEMENT", "NOKIDO_BRIDGE_OAUTH_APPARIEMENT")
# Hors Windows : dans le dossier du coffre reserve (root, 0700), le seul dossier ferme d'une installation POSIX.
A_NOTER = ((Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Nokido") if os.name == "nt"
           else mv.RESERVE_DIR) / "appariement_a_noter.txt"
_ALPHABET_CODE = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sans 0/O, 1/I/L : un code se tape


def _jeton_neuf() -> str:
    return secrets.token_urlsafe(48)


def _fernet_neuf() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("ascii")


def generateur_neuf(nom: str) -> Callable:
    """Le generateur d'une valeur NEUVE pour un nom reserve : cle Fernet valide pour la cle de
    chiffrement, cle Ed25519 pour les JWT, jeton CSPRNG pour le reste."""
    if nom in _GENERATEURS:
        return _GENERATEURS[nom]
    return _fernet_neuf if nom == "FORGE_ENCRYPT_KEY" else _jeton_neuf


def code_appariement() -> str:
    return "-".join("".join(secrets.choice(_ALPHABET_CODE) for _ in range(4)) for _ in range(3))


def planifier_machine_neuve(plan: dict, lire_machine: Callable = None) -> dict:
    """Machine neuve : un nom SANS source au coffre machine et absent du coffre reserve devient
    A_GENERER_MACHINE_NEUVE ; une cle neuve qui exigeait une rotation n'en est pas une quand rien
    n'a jamais ete signe avec. Rien d'autre ne bouge."""
    lire_machine = lire_machine or _lire_coffre_machine
    neuf = dict(plan)
    for nom, etat in plan.items():
        if nom in HORS_MACHINE_NEUVE:
            continue
        if etat == SOURCE_ABSENTE or (etat == A_GENERER and not lire_machine(nom)[0]):
            neuf[nom] = A_GENERER_NEUF
    return neuf


def dossier_ferme(d: Path, appliquer: bool) -> str:
    """Un dossier de secrets cree avec une ACL EXPLICITE (SYSTEM + Administrateurs, heritage
    coupe) -- jamais l'ACL heritee de ProgramData, qui laisse lire les Utilisateurs (regle de
    forge_machine_vault). L'ACL est RELUE : seul PRESENT_ACL_FERMEE autorise une ecriture."""
    import subprocess

    if os.name != "nt":
        # Hors Windows (owner 2026-10-09) : a root, mode 0700 -- verifie par la meme regle que le coffre.
        if not d.is_dir():
            if not appliquer:
                return "A_CREER"
            d.mkdir(parents=True, mode=0o700)
            os.chown(d, 0, 0)
            os.chmod(d, 0o700)
        return "PRESENT_ACL_FERMEE" if mv._dossier_posix_ferme(d) else "ACL_OUVERTE (attendu : a root, mode 0700)"
    if not d.is_dir():
        if not appliquer:
            return "A_CREER"
        d.mkdir(parents=True)
        subprocess.run(["icacls", str(d), "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F",
                        "*S-1-5-32-544:(OI)(CI)F"], capture_output=True, text=True, errors="replace")
    acl = subprocess.run(["icacls", str(d)], capture_output=True, text=True, errors="replace").stdout
    ouverts = [m for m in ("\\Users:", "\\Utilisateurs:", "Everyone:", "Tout le monde:", "Authenticated Users:",
                           "Utilisateurs authentifi") if m in acl]
    return "ACL_OUVERTE %s" % ouverts if ouverts else "PRESENT_ACL_FERMEE"


def creer_dossier_reserve(appliquer: bool) -> str:
    return dossier_ferme(mv.RESERVE_PATH.parent, appliquer)


def amorcer_identites_et_appariements(appliquer: bool) -> dict:
    """Cle persona TPM (signe les assertions du lanceur runAs) et codes d'appariement absents. Sans
    TPM, le lanceur se replie sur FORGE_TOKEN_<AGENT> : forge_vault_seed_agent_tokens les seme."""
    from nokido_agent.app import forge_persona_tpm as tpm

    bilan = {"persona_tpm": "A_CREER" if not appliquer else
             ("PRESENTE" if tpm.ensure_persona_key() else "TPM_INDISPONIBLE (repli FORGE_TOKEN_<AGENT>)")}
    nouveaux = []
    for nom in APPARIEMENTS:
        if fs.get_secret(nom):
            bilan[nom] = DEJA_EN_PLACE
            continue
        if not appliquer:
            bilan[nom] = A_ECRIRE
            continue
        code = code_appariement()
        ecrit = mv.vault_set(nom, code) is not False
        getattr(fs, "invalidate_cache", lambda: None)()  # l'absence lue plus haut ne doit pas masquer l'ecriture
        ok = ecrit and fs.get_secret(nom) == code
        bilan[nom] = ECRITE if ok else ECHEC
        if ok:
            nouveaux.append((nom, code))
    if nouveaux:
        etat = dossier_ferme(A_NOTER.parent, True)
        if etat != "PRESENT_ACL_FERMEE":
            # Les codes sont scelles au coffre ; on ne les ecrit pas dans un dossier lisible par tous.
            bilan["a_noter"] = "NON ECRIT : %s" % etat
            return bilan
        A_NOTER.write_text("Codes d'appariement Nokido -- a noter, ils ne seront plus affiches :\n"
                           + "".join("  %s = %s\n" % (n, c) for n, c in nouveaux), encoding="utf-8")
        bilan["a_noter"] = str(A_NOTER)
    return bilan


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
    ap.add_argument("--machine-neuve", action="store_true",
                    help="machine NEUVE (owner 2026-10-09) : generer au coffre reserve chaque nom reserve "
                         "absent des deux coffres, creer son dossier a ACL fermee, la cle persona TPM et les "
                         "codes d'appariement absents")
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
    if a.machine_neuve:
        etat_dossier = creer_dossier_reserve(a.appliquer)
        print(f"dossier du coffre reserve : {etat_dossier}")
        if a.appliquer and etat_dossier != "PRESENT_ACL_FERMEE":
            print("REFUS : dossier du coffre reserve non ferme -- aucun secret ne sera ecrit")
            return 2
    elif not mv.RESERVE_PATH.parent.is_dir():
        print(f"REFUS : {mv.RESERVE_PATH.parent} absent -- il se cree par l'owner, avec son ACL")
        return 2
    _noms, etat = mv.reserve_list()
    if a.machine_neuve and not a.appliquer and not mv.RESERVE_PATH.parent.is_dir():
        etat = mv.RESERVE_COFFRE_ABSENT  # plan sur machine vierge : le dossier sera cree par --appliquer
    if etat not in (mv.RESERVE_TROUVE, mv.RESERVE_COFFRE_ABSENT):
        print(f"REFUS : coffre reserve {etat} -- rien ne sera ecrit par-dessus")
        return 2

    cibles = calculer_cibles()
    plan = planifier(cibles)
    plan.update(planifier_nouvelles(rotation=a.rotation_persona))
    if a.machine_neuve:
        plan = planifier_machine_neuve(plan)
        for nom in HORS_MACHINE_NEUVE:
            if plan.get(nom) == SOURCE_ABSENTE:
                plan[nom] = "SANS_OBJET_MACHINE_NEUVE"
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
        for nom in sorted(n for n, e in plan.items() if e == A_GENERER_NEUF):
            plan[nom] = ECRITE if mv.reserve_set(nom, generateur_neuf(nom)()) else ECHEC
            print(f"  {nom:<26} {plan[nom]} (valeur neuve, machine neuve)")
    else:
        print("PLAN seulement -- rien n'est ecrit. Relancer avec --appliquer.")
    if a.machine_neuve:
        for nom, e in amorcer_identites_et_appariements(a.appliquer).items():
            print(f"  {nom:<34} {e}")

    en_place = ({IDENTIQUE, ECRITE, DEJA_EN_PLACE, EN_PLACE_SOURCE_RETIREE, "SANS_OBJET_MACHINE_NEUVE"}
                | ({A_ECRIRE, A_GENERER_NEUF} if not a.appliquer else set()))
    restent = sorted(n for n, e in plan.items() if e not in en_place)
    print(f"bilan : {len(plan) - len(restent)}/{len(plan)} en place"
          + (f" ; NON provisionnees : {restent}" if restent else ""))
    print("coffre machine : INCHANGE (retrait = etape 2b, go owner a part)")
    return 1 if restent else 0


if __name__ == "__main__":
    raise SystemExit(main())
