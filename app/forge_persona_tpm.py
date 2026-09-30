# -*- coding: utf-8 -*-
"""
forge_persona_tpm.py — AXE 8 PR-6 : racine de confiance MATÉRIELLE de la persona.
================================================================================
Signe l'identité Nokido avec une clé scellée dans le TPM 2.0 (preuve hardware
« émane de cette instance »). Accès via CNG « Microsoft Platform Crypto Provider »
en ctypes/NCrypt — ZÉRO nouvelle dépendance (même approche que forge_env_crypt DPAPI).

TPM = signature/crypto UNIQUEMENT, jamais de compute (cf. CLAUDE.md).
Tout échec TPM → fallback HMAC (clé locale). `sign_identity()` retourne un tag court
`tpm:<hex>` ou `hmac:<hex>` pour la ligne [ANCHOR_SIG] de la persona.

Clé USER par défaut (pas d'élévation requise) ; FORGE_TPM_MACHINE=1 → clé machine
(cohérent hub service, nécessite admin pour la création).

API : tpm_available(), ensure_persona_key(), sign(bytes)->bytes|None,
      verify(bytes,bytes)->bool, sign_identity(str)->str.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `ClePersonaIndisponible` — La cle HMAC persona n'est lisible nulle part pour ce compte (2b-1, 2026-09-28).
- `cle_publique_jwk` — -> (jwk | None, raison). JWK EC P-256 de la cle `nom`, sans aucune partie privee.
- `cle_publique_jwk_agent` — -> (jwk | None, raison) pour la cle TPM D'UN AGENT declare au registre.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
from nokido_agent.app.forge_secrets import get_secret

__FORGE_COLOR__ = "BLUE"

_PROVIDER = "Microsoft Platform Crypto Provider"
_KEY_NAME = "laforge-persona-sign"
_ALG = "ECDSA_P256"

NCRYPT_MACHINE_KEY_FLAG = 0x20
NCRYPT_SILENT_FLAG = 0x40

ROOT = Path(__file__).resolve().parent.parent
_HMAC_KEY_FILE = ROOT / "sandbox" / ".persona_sig_key"


def _key_flags() -> int:
    base = NCRYPT_SILENT_FLAG
    if os.environ.get("FORGE_TPM_MACHINE") == "1":
        base |= NCRYPT_MACHINE_KEY_FLAG
    return base


# ── ctypes NCrypt (lazy, Windows only) ────────────────────────────────────────
def _ncrypt():
    import ctypes
    from ctypes import wintypes

    nc = ctypes.windll.ncrypt
    H = wintypes.HANDLE
    PH = ctypes.POINTER(H)
    LP = wintypes.LPCWSTR
    DW = wintypes.DWORD
    PDW = ctypes.POINTER(DW)
    PB = ctypes.c_char_p
    VP = ctypes.c_void_p
    LONG = ctypes.c_long

    nc.NCryptOpenStorageProvider.argtypes = [PH, LP, DW]
    nc.NCryptOpenStorageProvider.restype = LONG
    nc.NCryptOpenKey.argtypes = [H, PH, LP, DW, DW]
    nc.NCryptOpenKey.restype = LONG
    nc.NCryptCreatePersistedKey.argtypes = [H, PH, LP, LP, DW, DW]
    nc.NCryptCreatePersistedKey.restype = LONG
    nc.NCryptFinalizeKey.argtypes = [H, DW]
    nc.NCryptFinalizeKey.restype = LONG
    nc.NCryptSignHash.argtypes = [H, VP, PB, DW, PB, DW, PDW, DW]
    nc.NCryptSignHash.restype = LONG
    nc.NCryptVerifySignature.argtypes = [H, VP, PB, DW, PB, DW, DW]
    nc.NCryptVerifySignature.restype = LONG
    nc.NCryptFreeObject.argtypes = [H]
    nc.NCryptFreeObject.restype = LONG
    return nc, ctypes, wintypes


def _open_provider(nc, ctypes, wintypes):
    h = wintypes.HANDLE()
    if nc.NCryptOpenStorageProvider(ctypes.byref(h), _PROVIDER, 0) != 0:
        return None
    return h


def tpm_available() -> bool:
    """True si le provider TPM CNG s'ouvre. Best-effort, jamais d'exception."""
    try:
        nc, ctypes, wintypes = _ncrypt()
        h = _open_provider(nc, ctypes, wintypes)
        if not h:
            return False
        nc.NCryptFreeObject(h)
        return True
    except Exception:
        return False


def _open_key(nc, ctypes, wintypes, hprov, create=False, nom=None):
    """Ouvre (ou cree) une cle NCrypt par NOM.

    `nom=None` garde la cle historique `_KEY_NAME` : tous les appelants
    existants sont inchanges. Le nom etait une CONSTANTE, donc il n'existait
    qu'UNE cle pour tout le corps -- la « cle machine » mesuree le 2026-09-02,
    celle qui empeche toute attribution entre agents.
    """
    hkey = wintypes.HANDLE()
    flags = _key_flags()
    cle = nom or _KEY_NAME
    if nc.NCryptOpenKey(hprov, ctypes.byref(hkey), cle, 0, flags) == 0:
        return hkey
    if not create:
        return None
    if nc.NCryptCreatePersistedKey(hprov, ctypes.byref(hkey), _ALG, cle, 0, flags) != 0:
        return None
    if nc.NCryptFinalizeKey(hkey, NCRYPT_SILENT_FLAG) != 0:
        nc.NCryptFreeObject(hkey)
        return None
    return hkey


def ensure_persona_key() -> bool:
    """Crée la clé de signature persona TPM-backed si absente. False si TPM indispo."""
    try:
        nc, ctypes, wintypes = _ncrypt()
        h = _open_provider(nc, ctypes, wintypes)
        if not h:
            return False
        hkey = _open_key(nc, ctypes, wintypes, h, create=True)
        ok = hkey is not None
        if hkey:
            nc.NCryptFreeObject(hkey)
        nc.NCryptFreeObject(h)
        return ok
    except Exception:
        return False


# Codes NCrypt, et la SEULE table qui distingue une absence d'un refus.
# Mesure du 2026-09-21 : `NCryptOpenKey` rend 0x80090016 sur le magasin MACHINE
# et 0x80090011 sur le magasin UTILISATEUR pour les cles d'agents -- deux
# formes d'ABSENCE, la ou 0x80090010 serait un REFUS D'ACCES. `_open_key`
# fusionnait tout en `None`, et l'outil d'etat ne pouvait rendre qu'un
# `INDISPONIBLE` fourre-tout : l'information existait cote Windows et se
# perdait a la frontiere de l'API.
_CODES_NCRYPT = {
    0x00000000: "UTILISABLE",
    0x80090016: "ABSENTE",       # NTE_BAD_KEYSET
    0x80090011: "ABSENTE",       # NTE_NOT_FOUND
    0x80090010: "REFUSEE",       # NTE_PERM
}


def classer_code_ncrypt(code: int) -> str:
    """UTILISABLE | ABSENTE | REFUSEE | INDETERMINE. Fonction PURE.

    LISTE BLANCHE : un code non prevu rend INDETERMINE, jamais UTILISABLE ni
    ABSENTE. Les deux erreurs coutent, et dans des directions opposees :
    conclure ABSENTE sur un refus envoie provisionner une cle qui existe deja ;
    conclure REFUSEE sur une absence envoie reparer des droits hors de cause.
    """
    return _CODES_NCRYPT.get(int(code) & 0xFFFFFFFF, "INDETERMINE")


def etat_cle_tpm(nom: str, machine=None) -> tuple:
    """(etat, code) pour une cle TPM, SANS jamais la creer.

    `machine=None` suit `FORGE_TPM_MACHINE` comme le reste du module ; True ou
    False force le magasin. Le magasin est EXPLICITE parce qu'un « ABSENTE »
    qui ne dit pas ou il a cherche ne veut rien dire : la cle peut exister dans
    l'autre.

    Rend le CODE en plus de l'etat : un verdict sans le code qui le fonde ne se
    conteste pas et ne se rejoue pas. Les codes negatifs disent OU la mesure
    s'est arretee -- -1 pas de provider utilisable, -2 provider non ouvert.
    """
    try:
        nc, ctypes, wintypes = _ncrypt()   # rend le TRIPLET, pas le seul DLL
    except Exception:                      # noqa: BLE001 — pas de ncrypt ici
        return "INDETERMINE", -1
    hprov = _open_provider(nc, ctypes, wintypes)
    if not hprov:
        return "INDETERMINE", -2
    flags = NCRYPT_SILENT_FLAG
    veut_machine = (os.environ.get("FORGE_TPM_MACHINE") == "1"
                    if machine is None else bool(machine))
    if veut_machine:
        flags |= NCRYPT_MACHINE_KEY_FLAG
    hkey = wintypes.HANDLE()
    rc = int(nc.NCryptOpenKey(hprov, ctypes.byref(hkey), nom, 0, flags)) & 0xFFFFFFFF
    if rc == 0:
        nc.NCryptFreeObject(hkey)
    nc.NCryptFreeObject(hprov)
    return classer_code_ncrypt(rc), rc


# Lecture du descripteur de securite d'une cle CNG. LECTURE SEULE, et le mot
# compte : on capture l'etat INITIAL de l'ACL avant d'envisager de la changer.
# Modifier d'abord effacerait la preuve qui explique le NTE_PERM.
_SECURITY_DESCR = "Security Descr"
_OWNER_SI, _GROUP_SI, _DACL_SI = 0x1, 0x2, 0x4


def descripteur_cle_tpm(nom: str, machine=None) -> dict:
    """{etat, code, sddl, proprietaire} d'une cle TPM. NE MODIFIE RIEN.

    QUATRE ETATS, et le troisieme est celui qui compte :

        LISIBLE      le descripteur a ete lu, `sddl` le porte
        REFUSE       la cle EXISTE mais ce compte ne peut pas l'ouvrir ou lire
                     sa propriete -- ce n'est PAS une absence
        ABSENTE      la cle n'existe pas dans ce magasin
        INDETERMINE  ni l'un ni l'autre n'est prouve

    Transformer un refus d'acces en « clé absente » enverrait provisionner une
    cle qui existe deja : c'est la confusion que P4.1 vient de fermer, et elle
    se rejouerait ici si la lecture du descripteur ne distinguait pas les deux.

    Le SDDL n'est pas un secret : c'est une liste de controle d'acces, pas du
    materiel de cle. Aucune partie privee ne transite par cette fonction --
    `NCryptExportKey` n'y est jamais appele.
    """
    etat_ouverture, code = etat_cle_tpm(nom, machine=machine)
    if etat_ouverture != "UTILISABLE":
        # ABSENTE / REFUSEE / INDETERMINE remontent TELS QUELS : on ne
        # reinterprete pas un verdict deja etabli.
        return {"etat": "ABSENTE" if etat_ouverture == "ABSENTE"
                else ("REFUSE" if etat_ouverture == "REFUSEE" else "INDETERMINE"),
                "code": code, "sddl": None, "proprietaire": None}
    try:
        nc, ctypes, wintypes = _ncrypt()
    except Exception:                                    # noqa: BLE001
        return {"etat": "INDETERMINE", "code": -1, "sddl": None,
                "proprietaire": None}
    nc.NCryptGetProperty.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR,
                                     ctypes.c_char_p, wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD),
                                     wintypes.DWORD]
    nc.NCryptGetProperty.restype = ctypes.c_long
    hprov = _open_provider(nc, ctypes, wintypes)
    if not hprov:
        return {"etat": "INDETERMINE", "code": -2, "sddl": None,
                "proprietaire": None}
    flags = NCRYPT_SILENT_FLAG
    veut_machine = (os.environ.get("FORGE_TPM_MACHINE") == "1"
                    if machine is None else bool(machine))
    if veut_machine:
        flags |= NCRYPT_MACHINE_KEY_FLAG
    hkey = wintypes.HANDLE()
    rc = int(nc.NCryptOpenKey(hprov, ctypes.byref(hkey), nom, 0, flags)) & 0xFFFFFFFF
    if rc != 0:
        nc.NCryptFreeObject(hprov)
        return {"etat": classer_code_ncrypt(rc).replace("REFUSEE", "REFUSE"),
                "code": rc, "sddl": None, "proprietaire": None}
    si = _OWNER_SI | _GROUP_SI | _DACL_SI
    taille = wintypes.DWORD(0)
    rc = int(nc.NCryptGetProperty(hkey, _SECURITY_DESCR, None, 0,
                                  ctypes.byref(taille), si)) & 0xFFFFFFFF
    sddl, proprietaire = None, None
    if rc == 0 and taille.value:
        buf = ctypes.create_string_buffer(taille.value)
        rc = int(nc.NCryptGetProperty(hkey, _SECURITY_DESCR, buf, taille.value,
                                      ctypes.byref(taille), si)) & 0xFFFFFFFF
        if rc == 0:
            adv = ctypes.windll.advapi32
            adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
                ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
            adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
            out = wintypes.LPWSTR()
            lg = wintypes.ULONG(0)
            if adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    ctypes.cast(buf, ctypes.c_void_p), 1, si,
                    ctypes.byref(out), ctypes.byref(lg)):
                sddl = out.value
                ctypes.windll.kernel32.LocalFree(out)
    nc.NCryptFreeObject(hkey)
    nc.NCryptFreeObject(hprov)
    if sddl:
        for morceau in sddl.split("O:"):
            if morceau and not morceau.startswith("G:"):
                proprietaire = morceau.split("G:")[0].strip() or None
                break
        return {"etat": "LISIBLE", "code": 0, "sddl": sddl,
                "proprietaire": proprietaire}
    return {"etat": "REFUSE" if rc else "INDETERMINE", "code": rc,
            "sddl": None, "proprietaire": None}


# Droits SDDL qu'on REFUSE d'accorder a un compte de service, quoi qu'il
# demande. Un hub compromis avec FA pourrait effacer la cle ou se reecrire sa
# propre ACL ; il n'a besoin que d'OUVRIR et de SIGNER.
_DROITS_REFUSES = frozenset({"FA", "GA", "KA", "WD"})


def poser_ace_cle_tpm(nom: str, compte: str, droit: str, sddl_attendu: str,
                      appliquer: bool = False, machine=None) -> dict:
    """Ajoute UNE ACE a la DACL d'une cle TPM. DRY-RUN par defaut.

    QUATRE GARDES, et aucun n'est optionnel :

      1. `droit` est OBLIGATOIRE et ne peut etre ni FA, ni GA, ni KA, ni WD.
         Moindre privilege : `GR` ouvre et utilise, `GW` modifierait.
      2. `sddl_attendu` est OBLIGATOIRE et doit correspondre EXACTEMENT a
         l'ACL observee. Une modification concurrente serait sinon ecrasee en
         silence -- l'arbre est partage par plusieurs surfaces.
      3. `appliquer=False` (defaut) ne touche a RIEN : on rend le plan, avec
         l'avant et l'apres calcule, pour qu'il soit relu avant d'etre execute.
      4. On AJOUTE une ACE. Aucune existante n'est retiree ni elargie -- le
         nouveau SDDL doit contenir l'ancien comme prefixe, et c'est verifie.

    Rend {etat, refus, avant, apres, applique, sid}. `etat` vaut PLAN, APPLIQUE,
    REFUS ou INDETERMINE -- jamais un booleen -- ou, quand le descripteur n'a pas
    pu etre lu, l'etat de `descripteur_cle_tpm` tel quel : ABSENTE ou REFUSE.
    """
    d = str(droit or "").upper().strip()
    if not d:
        return {"etat": "REFUS", "refus": "aucun droit demande : le masque doit "
                "etre EXPLICITE, il n'y a pas de defaut sur une ACL",
                "avant": None, "apres": None, "applique": False, "sid": None}
    if d in _DROITS_REFUSES:
        return {"etat": "REFUS", "refus": "droit %r refuse : un compte de "
                "service n'administre pas le key container, il l'utilise" % d,
                "avant": None, "apres": None, "applique": False, "sid": None}
    if not sddl_attendu:
        return {"etat": "REFUS", "refus": "SDDL attendu manquant : sans l'etat "
                "capture on ne peut pas garantir qu'on n'ecrase pas une "
                "modification concurrente", "avant": None, "apres": None,
                "applique": False, "sid": None}

    lu = descripteur_cle_tpm(nom, machine=machine)
    if lu["etat"] != "LISIBLE":
        return {"etat": lu["etat"], "refus": "descripteur illisible (%s) : "
                "relancer depuis le compte qui peut ouvrir la cle" % lu["etat"],
                "avant": None, "apres": None, "applique": False, "sid": None}
    avant = lu["sddl"]
    if avant.strip() != str(sddl_attendu).strip():
        return {"etat": "REFUS", "refus": "l'ACL a CHANGE depuis la capture : "
                "ecrire maintenant ecraserait une modification faite entre "
                "temps", "avant": avant, "apres": None, "applique": False,
                "sid": None}

    import ctypes
    from ctypes import wintypes
    adv = ctypes.windll.advapi32
    # Le compte -> SID, par le systeme. Jamais une chaine construite a la main.
    sid_buf = ctypes.create_string_buffer(256)
    cb_sid = wintypes.DWORD(256)
    dom = ctypes.create_unicode_buffer(256)
    cb_dom = wintypes.DWORD(256)
    use = wintypes.DWORD()
    if not adv.LookupAccountNameW(None, compte, sid_buf, ctypes.byref(cb_sid),
                                  dom, ctypes.byref(cb_dom), ctypes.byref(use)):
        return {"etat": "REFUS", "refus": "compte %r introuvable sur cette "
                "machine" % compte, "avant": avant, "apres": None,
                "applique": False, "sid": None}
    psid = wintypes.LPWSTR()
    adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                           ctypes.POINTER(wintypes.LPWSTR)]
    if not adv.ConvertSidToStringSidW(sid_buf, ctypes.byref(psid)):
        return {"etat": "INDETERMINE", "refus": "SID non convertible",
                "avant": avant, "apres": None, "applique": False, "sid": None}
    sid = psid.value
    ctypes.windll.kernel32.LocalFree(psid)

    ace = "(A;;%s;;;%s)" % (d, sid)
    if ace in avant:
        return {"etat": "REFUS", "refus": "cette ACE est DEJA presente : rien "
                "a faire", "avant": avant, "apres": avant, "applique": False,
                "sid": sid}
    # On AJOUTE en fin de DACL. S'il existe une SACL (`S:`), on insere avant --
    # concatener aveuglement la corromprait.
    coupe = avant.find("S:")
    apres = (avant + ace) if coupe == -1 else (avant[:coupe] + ace + avant[coupe:])
    if not apres.startswith(avant[:coupe if coupe != -1 else len(avant)]):
        return {"etat": "INDETERMINE", "refus": "le SDDL calcule ne contient "
                "pas l'ancien : refus par precaution", "avant": avant,
                "apres": None, "applique": False, "sid": sid}
    if not appliquer:
        return {"etat": "PLAN", "refus": None, "avant": avant, "apres": apres,
                "applique": False, "sid": sid, "aces_perdues": [],
                "normalise": None}   # None : pas encore mesurable, rien n'est ecrit

    # --- ECRITURE, seulement ici et seulement sur demande explicite.
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG)]
    psd = ctypes.c_void_p()
    taille_sd = wintypes.ULONG(0)
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            apres, 1, ctypes.byref(psd), ctypes.byref(taille_sd)):
        return {"etat": "INDETERMINE", "refus": "SDDL calcule non convertible",
                "avant": avant, "apres": apres, "applique": False, "sid": sid}
    try:
        nc, ctypes2, wintypes2 = _ncrypt()
    except Exception:                                    # noqa: BLE001
        ctypes.windll.kernel32.LocalFree(psd)
        return {"etat": "INDETERMINE", "refus": "ncrypt indisponible",
                "avant": avant, "apres": apres, "applique": False, "sid": sid}
    nc.NCryptSetProperty.argtypes = [wintypes2.HANDLE, wintypes2.LPCWSTR,
                                     ctypes2.c_void_p, wintypes2.DWORD,
                                     wintypes2.DWORD]
    nc.NCryptSetProperty.restype = ctypes2.c_long
    hprov = _open_provider(nc, ctypes2, wintypes2)
    flags = NCRYPT_SILENT_FLAG
    veut_machine = (os.environ.get("FORGE_TPM_MACHINE") == "1"
                    if machine is None else bool(machine))
    if veut_machine:
        flags |= NCRYPT_MACHINE_KEY_FLAG
    hkey = wintypes2.HANDLE()
    rc = int(nc.NCryptOpenKey(hprov, ctypes2.byref(hkey), nom, 0, flags)) & 0xFFFFFFFF
    if rc != 0:
        ctypes.windll.kernel32.LocalFree(psd)
        nc.NCryptFreeObject(hprov)
        return {"etat": classer_code_ncrypt(rc), "refus": "ouverture refusee "
                "(rc=0x%08X)" % rc, "avant": avant, "apres": apres,
                "applique": False, "sid": sid}
    rc = int(nc.NCryptSetProperty(hkey, _SECURITY_DESCR, psd, taille_sd.value,
                                  _DACL_SI)) & 0xFFFFFFFF
    nc.NCryptFreeObject(hkey)
    nc.NCryptFreeObject(hprov)
    ctypes.windll.kernel32.LocalFree(psd)
    relu = descripteur_cle_tpm(nom, machine=machine)
    obtenu = relu.get("sddl") or ""
    # REQUESTED != ACHIEVED. Windows NORMALISE la DACL a l'application : mesure
    # du 2026-09-21, l'ACE `(A;;FA;;;CO)` a disparu et `D:P` est devenu `D:PAI`
    # sans que rien ne le demande. Le PLAN conservait les trois ACE ; le
    # RESULTAT non. Comparer le plan ne suffit donc pas -- on relit et on DIT
    # ce qui a bouge, au lieu de supposer que l'ecriture a fait ce qu'on voulait.
    import re as _re
    aces_avant = set(_re.findall(r"\([^)]*\)", avant))
    aces_apres = set(_re.findall(r"\([^)]*\)", obtenu))
    perdues = sorted(aces_avant - aces_apres)
    return {"etat": "APPLIQUE" if rc == 0 else "INDETERMINE",
            "refus": None if rc == 0 else "NCryptSetProperty rc=0x%08X" % rc,
            "avant": avant, "apres": obtenu, "applique": rc == 0, "sid": sid,
            "aces_perdues": perdues,
            "normalise": bool(perdues) or ("D:P" in avant and "D:PAI" in obtenu)}


def nom_cle_agent(agent_id) -> str:
    """Nom de la cle TPM D'UN AGENT. Leve si l'agent n'est pas declare au SSoT.

    DIRECTIVE OWNER 2026-09-20 : « le TPM peut servir ». Il sert, et mieux que
    prevu -- `_ALG = ECDSA_P256` est ASYMETRIQUE : la privee ne quitte jamais le
    TPM, la publique se verifie. La non-repudiation etait donc atteignable, il
    manquait seulement que le NOM de la cle soit parametrable.
    `NCryptCreatePersistedKey` le prend deja en argument ; c'est ce module qui
    lui passait une constante.

    ON RESOUT PAR LE SSoT, jamais par la chaine brute : `agt_claude` et `CLAUDE`
    sont le MEME agent. Deux cles pour un seul agent, ce serait deux identites --
    exactement le defaut des 48 messages non delivrables mesures ce soir.

    Un agent INCONNU ne recoit PAS de cle : donner du materiel cryptographique a
    une etiquette non declaree, c'est authentifier un fantome (`agt_agt_gemini`,
    25 messages accumules).

    ⚠️ LIMITE DITE : `NCRYPT_MACHINE_KEY_FLAG` -- ce sont des cles MACHINE. Une
    cle par agent empeche l'usurpation ACCIDENTELLE, trace l'origine et survit au
    redemarrage, mais un process du meme hote peut l'invoquer. C'est une
    ATTRIBUTION forte, PAS une isolation inter-process. Le dire ainsi est le
    minimum : « invoquer une RFC qu'on n'implemente pas est une fausse garantie ».
    """
    from nokido_agent.app.forge_m2m_protocol import _resoudre_agent

    canon, _surface = _resoudre_agent(agent_id)
    if not canon:
        raise ValueError(
            "agent %r non declare au registre d'identite : aucune cle TPM ne lui "
            "sera attribuee" % (str(agent_id)[:40],))
    # ASCII strict : ce nom part vers une API Windows.
    sur = "".join(c for c in canon if c.isalnum() or c in "._-")
    return "laforge-agent-%s-sign" % sur


def ensure_agent_key(agent_id) -> bool:
    """Cree la cle TPM d'un agent si absente. ACTE EXPLICITE, jamais implicite.

    Une signature qui fabrique silencieusement du materiel cryptographique
    PERSISTANT dans le TPM de la machine est un effet de bord qu'on ne voit
    pas -- `sign_as` refuse donc de creer, et cette fonction existe pour cela.
    """
    try:
        cle = nom_cle_agent(agent_id)
        nc, ctypes, wintypes = _ncrypt()
        h = _open_provider(nc, ctypes, wintypes)
        if not h:
            return False
        hkey = _open_key(nc, ctypes, wintypes, h, create=True, nom=cle)
        ok = hkey is not None
        if hkey:
            nc.NCryptFreeObject(hkey)
        nc.NCryptFreeObject(h)
        return ok
    except Exception:
        return False


def sign_as(agent_id, payload: bytes):
    """Signe AU NOM d'un agent. NE CREE JAMAIS la cle (cf. `ensure_agent_key`).

    ⚠️ CETTE FONCTION N'AUTHENTIFIE PAS SON APPELANT, et la distinction est
    contre-intuitive :

        NON-EXPORTABILITE  la cle ne peut pas SORTIR du TPM
        ISOLATION          seul son proprietaire peut s'en SERVIR

    Le TPM garantit la premiere, PAS la seconde. `agent_id` est une chaine :
    n'importe quelle ligne de code du process peut ecrire `sign_as("HUB", ...)`
    et obtenir une signature au nom du HUB, indiscernable d'une signature
    legitime. Une cle par agent empeche l'usurpation ACCIDENTELLE et donne une
    attribution forte ; elle n'empeche pas l'usurpation DELIBEREE d'un code qui
    tourne deja dans le process.

    DONC : l'autorisation se fait AVANT cet appel, chez l'appelant. Au
    2026-09-21 il n'y en a aucun en production (seule la sonde d'etat de
    `forge_tpm_agent_keys` l'utilise) — la racine de confiance materielle
    existe et n'est cablee nulle part. `test_tpm_isolation_nest_pas_non_
    exportabilite_nr` monte la garde : il rougit des qu'un appelant apparait,
    pour qu'on relise cet invariant avant de s'y fier.
    """
    return sign(payload, nom=nom_cle_agent(agent_id), creer=False)


def verify_etat_agent(agent_id, payload: bytes, sig: bytes) -> tuple:
    """Verifie une signature d'agent en TROIS etats (VALIDE/INVALIDE/INVERIFIABLE).

    On ne regresse PAS vers un booleen : « inverifiable depuis ce compte » n'est
    pas « altere ». C'est la lecon du 2026-09-02, inscrite dans `verify_etat`.
    """
    try:
        return verify_etat(payload, sig, nom=nom_cle_agent(agent_id))
    except ValueError as exc:
        return "INVERIFIABLE", str(exc)


# ─── Cle PUBLIQUE en JWK (2026-09-24, chantier d'authentification -> preuve TPM) ─────
# DPoP (RFC 9449) transporte la cle publique dans l'en-tete de la preuve, et le
# verificateur la compare a l'empreinte (RFC 7638) ATTENDUE. Il manquait l'export : la
# publique est toujours exportable (`ECCPUBLICBLOB`), la privee ne quitte jamais le TPM.
_ECCPUBLICBLOB = "ECCPUBLICBLOB"
_MAGIC_ECDSA_PUBLIC_P256 = 0x31534345   # « ECS1 »


def _b64u(octets: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def cle_publique_jwk(nom: str | None = None) -> tuple:
    """-> (jwk | None, raison). JWK EC P-256 de la cle `nom`, sans aucune partie privee.

    Trois issues distinctes, jamais fondues : cle exportee, cle absente ou non ouvrable
    depuis ce compte, blob inattendu. `None` n'est jamais « pas de cle » sans motif.
    """
    import struct
    try:
        nc, ctypes, wintypes = _ncrypt()
        nc.NCryptExportKey.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.LPCWSTR,
                                       ctypes.c_void_p, ctypes.c_char_p, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
        nc.NCryptExportKey.restype = ctypes.c_long
    except Exception as exc:  # noqa: BLE001
        return None, "interface NCrypt indisponible (%s)" % type(exc).__name__
    h = hkey = None
    try:
        h = _open_provider(nc, ctypes, wintypes)
        if not h:
            return None, "fournisseur TPM non ouvrable depuis ce compte"
        hkey = _open_key(nc, ctypes, wintypes, h, create=False, nom=nom)
        if not hkey:
            return None, "cle TPM absente ou non ouvrable depuis ce compte"
        cb = wintypes.DWORD(0)
        st = nc.NCryptExportKey(hkey, None, _ECCPUBLICBLOB, None, None, 0, ctypes.byref(cb), 0)
        if st != 0 or cb.value == 0:
            return None, "export de la publique refuse (statut 0x%08X)" % (st & 0xFFFFFFFF)
        buf = ctypes.create_string_buffer(cb.value)
        st = nc.NCryptExportKey(hkey, None, _ECCPUBLICBLOB, None, buf, cb.value, ctypes.byref(cb), 0)
        if st != 0:
            return None, "export de la publique refuse (statut 0x%08X)" % (st & 0xFFFFFFFF)
        brut = buf.raw[: cb.value]
        magic, taille = struct.unpack("<II", brut[:8])
        if magic != _MAGIC_ECDSA_PUBLIC_P256 or taille != 32 or len(brut) < 8 + 64:
            return None, "blob inattendu (magic 0x%08X, %d octets)" % (magic, taille)
        return {"kty": "EC", "crv": "P-256",
                "x": _b64u(brut[8:40]), "y": _b64u(brut[40:72])}, ""
    except Exception as exc:  # noqa: BLE001
        return None, "export interrompu (%s)" % type(exc).__name__
    finally:
        for handle in (hkey, h):
            if handle:
                try:
                    nc.NCryptFreeObject(handle)
                except Exception:  # muet-ok : liberation best-effort, deja sorti
                    pass


def cle_publique_jwk_agent(agent_id) -> tuple:
    """-> (jwk | None, raison) pour la cle TPM D'UN AGENT declare au registre."""
    try:
        return cle_publique_jwk(nom=nom_cle_agent(agent_id))
    except ValueError as exc:
        return None, str(exc)[:120]


def sign(payload: bytes, nom: str | None = None, creer: bool = True):
    """Signe SHA-256(payload) avec la clé TPM (ECDSA P-256). None si indispo.

    `nom`/`creer` par defaut = comportement historique inchange (cle unique,
    creation a la volee). `sign_as` les fixe pour signer au nom d'un agent sans
    jamais fabriquer de materiel cryptographique en passant.
    """
    try:
        nc, ctypes, wintypes = _ncrypt()
        h = _open_provider(nc, ctypes, wintypes)
        if not h:
            return None
        hkey = _open_key(nc, ctypes, wintypes, h, create=creer, nom=nom)
        if not hkey:
            nc.NCryptFreeObject(h)
            return None
        digest = hashlib.sha256(payload).digest()
        cb = wintypes.DWORD(0)
        st = nc.NCryptSignHash(hkey, None, digest, len(digest), None, 0, ctypes.byref(cb), 0)
        if st != 0 or cb.value == 0:
            nc.NCryptFreeObject(hkey)
            nc.NCryptFreeObject(h)
            return None
        buf = ctypes.create_string_buffer(cb.value)
        st = nc.NCryptSignHash(hkey, None, digest, len(digest), buf, cb.value, ctypes.byref(cb), 0)
        nc.NCryptFreeObject(hkey)
        nc.NCryptFreeObject(h)
        if st != 0:
            return None
        return buf.raw[: cb.value]
    except Exception:
        return None


# Code Windows d'une signature qui NE CORRESPOND PAS (bcrypt.h). Tout autre
# statut non nul dit un probleme d'ACCES (provider, cle, contexte), pas une
# divergence de signature -- et les confondre fait accuser une altération.
NTE_BAD_SIGNATURE = 0x80090006

VERDICTS = ("VALIDE", "INVALIDE", "INVERIFIABLE")


def verify_etat(payload: bytes, sig: bytes, nom: str | None = None) -> tuple:
    """Verifie une signature TPM en TROIS etats : (verdict, raison).

    POURQUOI trois et pas deux (mesure 2026-09-02) : `verify()` rendait `False`
    aussi bien pour « la signature ne correspond pas » que pour « je n'ai pas
    pu ouvrir la cle », et son appelant traduisait ce `False` en « token
    altéré ». Or la cle du TPM est une cle MACHINE : depuis un compte de
    service, `sign()` rend None et `verify()` rend False alors que le jeton est
    parfaitement intact -- le hub, lui, l'accepte. Un outil de verification
    lance hors du compte du hub accusait donc une altération inexistante.

    `tpm_available()` ne protege pas de ce piege : il constate la presence du
    fournisseur, jamais la capacite a s'en servir.

    La DECISION ne change pas : seul VALIDE vaut acceptation, INVERIFIABLE
    refuse comme avant. C'est le DIAGNOSTIC qui cesse de mentir.
    """
    try:
        nc, ctypes, wintypes = _ncrypt()
    except Exception as exc:
        return "INVERIFIABLE", "interface NCrypt indisponible (%s)" % type(exc).__name__
    h = hkey = None
    try:
        h = _open_provider(nc, ctypes, wintypes)
        if not h:
            return "INVERIFIABLE", "fournisseur TPM non ouvrable depuis ce compte"
        hkey = _open_key(nc, ctypes, wintypes, h, create=False, nom=nom)
        if not hkey:
            return "INVERIFIABLE", "cle TPM non ouvrable depuis ce compte"
        digest = hashlib.sha256(payload).digest()
        st = nc.NCryptVerifySignature(hkey, None, digest, len(digest),
                                      sig, len(sig), 0)
        if st == 0:
            return "VALIDE", ""
        if (st & 0xFFFFFFFF) == NTE_BAD_SIGNATURE:
            return "INVALIDE", "la signature ne correspond pas au contenu"
        return "INVERIFIABLE", "NCryptVerifySignature statut 0x%08X" % (st & 0xFFFFFFFF)
    except Exception as exc:
        return "INVERIFIABLE", "verification interrompue (%s)" % type(exc).__name__
    finally:
        for handle in (hkey, h):
            if handle:
                try:
                    nc.NCryptFreeObject(handle)
                except Exception:  # muet-ok : liberation best-effort, deja sorti
                    pass


def verify(payload: bytes, sig: bytes) -> bool:
    """Vérifie une signature TPM. False si indispo/invalide.

    Conserve pour ses appelants existants. Quand la DISTINCTION compte --
    dire « altéré » alors que la cle est seulement inaccessible est une
    accusation fausse -- utiliser `verify_etat()`.
    """
    return verify_etat(payload, sig)[0] == "VALIDE"


class ClePersonaIndisponible(RuntimeError):
    """La clé HMAC persona n'est lisible nulle part pour ce compte (2b-1, 2026-09-28)."""


# ── Fallback HMAC (clé locale persistée) ──────────────────────────────────────
def _hmac_key() -> bytes:
    """Clé HMAC persona : guichet (nom RÉSERVÉ, coffre réservé lu d'abord), puis fichier.

    FAIL-CLOSED (étape 2b-1 du correctif du coffre, 2026-09-28). Le dernier repli était
    le sha256 du NOM DE MACHINE : une valeur PUBLIQUE. Depuis les ACL owner du 28/09 le
    fichier n'est lisible que par SYSTEM et les administrateurs -- tout autre compte
    tombait donc sur ce repli, et `login_agent` acceptait une signature que n'importe qui
    sait calculer. Illisible n'est pas absent : on LÈVE, on ne devine pas une clé.
    """
    env = get_secret("FORGE_PERSONA_HMAC_KEY")
    if env:
        return env.encode()
    try:
        if _HMAC_KEY_FILE.exists():
            return _HMAC_KEY_FILE.read_bytes()
    except Exception as exc:
        raise ClePersonaIndisponible(
            f"clé persona illisible pour ce compte ({type(exc).__name__}) -- "
            "aucun repli sur une valeur publique") from exc
    # Absent : le module NE CRÉE PLUS le fichier (2026-09-28). Créé ici, il héritait l'ACL
    # de `sandbox/`, lisible par les comptes bac à sable. La clé naît au coffre réservé,
    # sous SYSTEM (`tools/forge_coffre_reserve_provision.py --rotation-persona`).
    raise ClePersonaIndisponible(
        "clé persona absente (ni guichet ni fichier) -- à provisionner au coffre réservé")


def sign_identity(text: str) -> str:
    """Retourne un tag court de preuve d'origine pour la ligne [ANCHOR_SIG] :
    `tpm:<hex16>` si TPM dispo, sinon `hmac:<hex16>` (fallback), sinon
    `aucune:cle-indisponible` -- jamais un tag signé d'une clé devinée (2b-1).
    Jamais d'exception."""
    payload = (text or "").encode("utf-8", "replace")
    s = sign(payload)
    if s:
        return "tpm:" + hashlib.sha256(s).hexdigest()[:16]
    try:
        cle = _hmac_key()
    except ClePersonaIndisponible:
        return "aucune:cle-indisponible"
    mac = hmac.new(cle, payload, hashlib.sha256).hexdigest()[:16]
    return "hmac:" + mac
