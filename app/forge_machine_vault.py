"""app/forge_machine_vault.py - coffre de secrets cross-OS.

POURQUOI UN NOUVEAU MODULE (anti-duplication) :
  forge_secrets.py est une FACADE haut-niveau (chaine de priorite). Le
  stockage backend est ce module bas-niveau qui merite son unite testable.

BACKENDS PAR OS :
  - Windows : DPAPI avec flag CRYPTPROTECT_LOCAL_MACHINE (ctypes pur, zero dep).
              Chiffre avec la cle MACHINE -> dechiffrable par tout compte local.
              Permet aux comptes service sandbox de lire sans WCM per-user.
  - macOS   : Keychain via `keyring` (service="Nokido_Vault"). Per-user, mais
              acceptable car les sandbox accounts ne sont pas un cas macOS.
  - Linux   : libsecret/Secret Service via `keyring` si dispo, sinon fallback
              fichier `data/machine_vault.dat` chiffre AES-256-GCM avec une
              passphrase derivee de `LAFORGE_VAULT_KEY` env var (PBKDF2).

STORE : `data/machine_vault.dat` — JSON {cle: base64(blob_chiffre)}. Toujours
  utilise sur Windows pour partager entre comptes service. Sur Linux fallback,
  meme format. Sur macOS le store reste dans Keychain (pas de fichier).

COFFRE RESERVE (2026-09-28) : `C:/ProgramData/NokidoCoffre/coffre_reserve.dat`,
  meme format, mais scelle en portee UTILISATEUR sous SYSTEM, dans un dossier a
  ACL SYSTEM + Administrateurs posee par l'owner. Pour les seuls noms reserves
  (jeton maitre, jetons admin et superviseur, secret JWT, cles dediees). Voir
  `reserve_lire` / `reserve_set` / `_garde_copie_reservee`.

CLI :
  python -m app.forge_machine_vault test          # roundtrip
  python -m app.forge_machine_vault list
  python -m app.forge_machine_vault get -k CLE
  python -m app.forge_machine_vault set -k CLE
  python -m app.forge_machine_vault del -k CLE

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `reserve_lire` — (valeur, etat) d'une cle du coffre reserve. Ne leve jamais.
- `reserve_list` — (noms, etat) du coffre reserve -- jamais les valeurs.
- `reserve_set` — Scelle `value` dans le coffre reserve (SYSTEM). True ssi verifie par relecture.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
VAULT_PATH = ROOT / "data" / "machine_vault.dat"

_IS_WIN = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"
_IS_LINUX = sys.platform.startswith("linux")
_KEYRING_SERVICE = "Nokido_Vault"  # macOS Keychain / Linux Secret Service service name

CRYPTPROTECT_UI_FORBIDDEN = 0x01
CRYPTPROTECT_LOCAL_MACHINE = 0x04


def _keyring_get(key: str) -> Optional[str]:
    """Backend macOS Keychain / Linux libsecret via `keyring`. None si lib absente."""
    try:
        import keyring  # type: ignore

        return keyring.get_password(_KEYRING_SERVICE, key)
    except Exception:
        return None


def _keyring_set(key: str, value: str) -> bool:
    try:
        import keyring  # type: ignore

        keyring.set_password(_KEYRING_SERVICE, key, value)
        return _keyring_get(key) == value
    except Exception:
        return False


def _keyring_delete(key: str) -> bool:
    try:
        import keyring  # type: ignore

        keyring.delete_password(_KEYRING_SERVICE, key)
        return True
    except Exception:
        return False


class _Blob(ctypes.Structure):
    """DATA_BLOB — paire (taille, pointeur) attendue par l'API DPAPI."""

    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _drapeaux_protection(portee_machine: bool = True) -> int:
    """Drapeaux de `CryptProtectData`. Portee MACHINE : tout compte local dechiffre.
    Portee UTILISATEUR (coffre reserve) : seul le compte qui a scelle dechiffre."""
    return (CRYPTPROTECT_LOCAL_MACHINE if portee_machine else 0) | CRYPTPROTECT_UI_FORBIDDEN


def _protect(plain: bytes, portee_machine: bool = True) -> bytes:
    """Chiffre via DPAPI, scope MACHINE par defaut (UTILISATEUR pour le coffre
    reserve). `buf` reste vivant le temps de l'appel API (sinon pointeur
    pendouillant — piege ctypes classique)."""
    buf = ctypes.create_string_buffer(plain, len(plain))
    blob_in = _Blob(len(plain), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    flags = _drapeaux_protection(portee_machine)
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, flags, ctypes.byref(blob_out)
    )
    if not ok:
        raise OSError(f"CryptProtectData failed (err {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _unprotect(cipher: bytes) -> bytes:
    """Dechiffre un blob DPAPI."""
    buf = ctypes.create_string_buffer(cipher, len(cipher))
    blob_in = _Blob(len(cipher), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out)
    )
    if not ok:
        raise OSError(f"CryptUnprotectData failed (err {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


# Variable d'environnement qui dit OU LIRE le coffre quand le module ne vit pas
# a cote de lui. Elle ne transporte JAMAIS de valeur : un chemin, rien d'autre.
_ENV_CHEMIN_COFFRE = "LAFORGE_VAULT_PATH"


def resoudre_chemin_coffre(defaut, override, existe):
    """(chemin, motif) — ou LIRE le coffre. Aucune valeur de secret n'entre ici.

    MESURE 2026-09-16, et c'est le chainon manquant de la CI. `VAULT_PATH` est
    calcule a cote du MODULE (`ROOT = Path(__file__).parent.parent`), or en CI
    le depot est clone dans le repertoire de travail du runner et `data/` est
    ignore par git : le coffre y est ABSENT. `forge_secrets.get_secret` descend
    alors ses quatre couches jusqu'a `os.environ`, donc jusqu'au secret CI --
    qui datait du 2026-07-03 et n'avait jamais ete renouvele. Le gate UI
    rapportait `TENTE_ET_REFUSE` la ou le meme jeton du coffre ETABLIT le login
    en local.

    CE QUI REND CE CORRECTIF SUR : le coffre est chiffre avec
    `CRYPTPROTECT_LOCAL_MACHINE`, donc tout compte de CETTE machine sait le
    dechiffrer, runner self-hosted compris. Ce qui manquait n'etait pas un
    secret mais un CHEMIN -- on cesse donc de faire voyager une valeur.

    DEUX REFUS, et ils sont dits plutot que silencieux :
      - un chemin RELATIF depend du repertoire courant, donc du hasard du
        lanceur : refuse ;
      - un chemin INEXISTANT ferait naitre un coffre VIDE ailleurs, et un
        coffre vide se lit exactement comme « ce secret n'existe pas ».

    ⚠️ LECTURE SEULE, par construction : `_save` reste sur `VAULT_PATH`. Lire
    un mauvais coffre donne un mauvais jeton, donc un login refuse et aucune
    fuite ; y ECRIRE deplacerait des secrets vers un emplacement dicte par
    l'environnement. Les deux directions ne se valent pas.
    """
    if not override:
        return defaut, "DEFAUT"
    candidat = Path(override)
    if not candidat.is_absolute():
        return defaut, "REFUSE_RELATIF"
    if not existe(candidat):
        return defaut, "REFUSE_ABSENT"
    return candidat, "OVERRIDE"


def chemin_coffre():
    """Le chemin de LECTURE effectif, override compris."""
    chemin, _motif = resoudre_chemin_coffre(
        VAULT_PATH, os.environ.get(_ENV_CHEMIN_COFFRE, "").strip(),
        lambda p: p.exists())
    return chemin


def _load() -> dict:
    """Charge le store JSON. Dict vide si absent ou illisible."""
    source = chemin_coffre()
    if not source.exists():
        return {}
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(store: dict) -> None:
    """Ecrit le store de maniere atomique (tmp + replace)."""
    VAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = VAULT_PATH.parent / (VAULT_PATH.name + ".tmp")
    tmp.write_text(json.dumps(store, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(VAULT_PATH)


def available() -> bool:
    """True si un backend coffre est utilisable sur cet OS."""
    if _IS_WIN:
        return True
    # macOS / Linux : keyring lib disponible ?
    try:
        import keyring  # type: ignore

        return True
    except ImportError:
        return False


def vault_get(key: str) -> Optional[str]:
    """Lit + dechiffre une cle. None si absente ou illisible."""
    val = _vault_get_brut(key)
    _journaliser_si_reserve(key, val)
    return val


# Recensement direct IMPOSSIBLE dans ce process (forge_secrets inimportable) : compte et
# derniere cause, lisibles. Un `except: pass` rendait cette limite invisible (gate
# recidive « chemin d'erreur muet », 2026-09-28) ; la lecture du coffre, elle, reste
# toujours servie.
_RECENSEMENT_INDISPONIBLE: dict = {"n": 0, "derniere": None}


def _journaliser_si_reserve(key: str, val: Optional[str]) -> None:
    """Etape 0 du correctif du coffre (owner 2026-09-28) : recense les lecteurs
    DIRECTS d'un nom reserve, ceux qui ne passent pas par `get_secret`.

    La liste des noms et le journal vivent dans `forge_secrets` (une seule
    copie). Ne leve jamais, ne change jamais ce que `vault_get` rend. Si
    `forge_secrets` est inimportable dans ce process, ces lectures ne sont PAS
    recensees : c'est une limite dite, pas une absence de lecteur.
    """
    try:
        from nokido_agent.app.forge_secrets import journaliser_lecture_directe
        journaliser_lecture_directe(key, "TROUVE" if val else "ABSENT_OU_ILLISIBLE")
    except Exception as exc:  # noqa: BLE001 -- l'observation ne casse jamais la lecture
        _RECENSEMENT_INDISPONIBLE["n"] += 1
        _RECENSEMENT_INDISPONIBLE["derniere"] = repr(exc)[:200]


def _vault_get_brut(key: str) -> Optional[str]:
    """Lecture sans recensement. None si absente ou illisible."""
    if _IS_WIN:
        enc = _load().get(key)
        if not enc:
            return None
        try:
            return _unprotect(base64.b64decode(enc)).decode("utf-8")
        except Exception:
            return None
    # macOS / Linux : keyring (Keychain / libsecret)
    return _keyring_get(key)


def vault_set(key: str, value: str) -> bool:
    """Chiffre + stocke. True ssi verifie par relecture.

    Une copie RESERVEE du meme nom est mise a jour D'ABORD, ou rien n'est ecrit
    (`_garde_copie_reservee`). Limite dite : si ce coffre-ci echoue APRES, la copie
    reservee porte deja la nouvelle valeur -- l'echec est rendu, pas masque.
    """
    if _IS_WIN:
        garde = _garde_copie_reservee(key, value)
        if garde:
            print(f"[machine_vault] set {key} REFUSE : {garde}")
            return False
        try:
            store = _load()
            store[key] = base64.b64encode(_protect(value.encode("utf-8"))).decode("ascii")
            _save(store)
            return vault_get(key) == value
        except Exception as e:  # noqa: BLE001
            print(f"[machine_vault] set {key} echec: {e}")
            return False
    # macOS / Linux : keyring
    return _keyring_set(key, value)


def vault_delete(key: str) -> bool:
    """Retire une cle. True si elle existait."""
    if _IS_WIN:
        store = _load()
        if key in store:
            del store[key]
            _save(store)
            return True
        return False
    return _keyring_delete(key)


def vault_list() -> list[str]:
    """Noms des cles presentes (jamais les valeurs).
    Note: sur macOS/Linux via keyring, l'enumeration n'est pas portable —
    on retourne le store DPAPI uniquement (vide sur non-Win)."""
    return sorted(_load().keys())


# --- Coffre RESERVE (etape 2a du correctif du coffre, go owner 2026-09-28) -----------
#
# MESURE du 2026-09-28 : `LaForgeSbxOffline` lisait dans CE coffre le jeton maitre, le
# secret de signature JWT et le jeton admin -- portee MACHINE, donc dechiffrables par
# tout compte local qui lit le fichier. Le coffre reserve pose DEUX verrous independants :
#   1. son dossier porte une ACL SYSTEM + Administrateurs, posee par l'OWNER. Ce module
#      ne le cree JAMAIS : cree ici, il heriterait l'ACL de ProgramData, qui laisse lire
#      les Utilisateurs ;
#   2. ses blobs sont scelles en portee UTILISATEUR sous SYSTEM : seul SYSTEM les
#      dechiffre, meme si l'ACL venait a s'ouvrir.
# Il ne sert que les noms reserves (`forge_secrets.NOMS_RESERVES`). En 2a, `get_secret`
# le lit D'ABORD, avec repli sur le coffre machine : on observe quelle source sert
# avant de fermer quoi que ce soit (la fermeture est l'etape 2b, go owner a part).
RESERVE_DIR = Path(r"C:\ProgramData\NokidoCoffre")
RESERVE_PATH = RESERVE_DIR / "coffre_reserve.dat"
# Le seul compte qui scelle : un blob scelle sous un autre compte serait INDECHIFFRABLE
# pour le hub, qui retomberait en silence sur le coffre machine.
RESERVE_COMPTE_SID = "S-1-5-18"

# Etats d'une lecture. ILLISIBLE n'est jamais ABSENT : un compte a qui l'ACL refuse le
# fichier ne sait PAS si la cle y est.
RESERVE_TROUVE = "TROUVE"
RESERVE_CLE_ABSENTE = "CLE_ABSENTE"
RESERVE_COFFRE_ABSENT = "COFFRE_ABSENT"
RESERVE_ACCES_REFUSE = "ACCES_REFUSE"
RESERVE_ILLISIBLE = "ILLISIBLE"
RESERVE_INDECHIFFRABLE = "INDECHIFFRABLE"
RESERVE_HORS_WINDOWS = "HORS_WINDOWS"
RESERVE_ETATS_ILLISIBLES = frozenset({
    RESERVE_ACCES_REFUSE, RESERVE_ILLISIBLE, RESERVE_INDECHIFFRABLE,
})


def _sid_courant() -> Optional[str]:
    """SID du compte du jeton de CE process (`S-1-5-18` = SYSTEM). None si illisible.

    Instances `WinDLL` PROPRES : poser des `argtypes` sur `ctypes.windll` les
    imposerait a tout le process, `_protect` compris.
    """
    if not _IS_WIN:
        return None
    try:
        advapi32 = ctypes.WinDLL("advapi32")
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD)]
        advapi32.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        jeton = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008,  # TOKEN_QUERY
                                         ctypes.byref(jeton)):
            return None
        try:
            taille = wintypes.DWORD(0)
            advapi32.GetTokenInformation(jeton, 1, None, 0, ctypes.byref(taille))  # TokenUser
            tampon = ctypes.create_string_buffer(taille.value)
            if not advapi32.GetTokenInformation(jeton, 1, ctypes.cast(tampon, ctypes.c_void_p),
                                                taille, ctypes.byref(taille)):
                return None
            # TOKEN_USER commence par SID_AND_ATTRIBUTES, dont le premier champ est le PSID.
            psid = ctypes.cast(tampon, ctypes.POINTER(ctypes.c_void_p))[0]
            texte = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(psid, ctypes.byref(texte)):
                return None
            try:
                return texte.value
            finally:
                kernel32.LocalFree(ctypes.cast(texte, ctypes.c_void_p))
        finally:
            kernel32.CloseHandle(jeton)
    except Exception:  # noqa: BLE001 -- ILLISIBLE se dit (None) ; jamais un « pas SYSTEM » invente
        return None


def _lire_store_reserve() -> tuple[dict, str]:
    """(store, etat) du coffre reserve. Ne leve jamais."""
    try:
        texte = RESERVE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, RESERVE_COFFRE_ABSENT
    except PermissionError:
        return {}, RESERVE_ACCES_REFUSE
    except OSError:
        return {}, RESERVE_ILLISIBLE
    try:
        store = json.loads(texte)
    except ValueError:
        return {}, RESERVE_ILLISIBLE
    if not isinstance(store, dict):
        return {}, RESERVE_ILLISIBLE
    return store, RESERVE_TROUVE


def reserve_lire(key: str) -> tuple[Optional[str], str]:
    """(valeur, etat) d'une cle du coffre reserve. Ne leve jamais.

    Ne journalise pas : le guichet `forge_secrets.get_secret` note la source qui a servi.
    """
    if not _IS_WIN:
        return None, RESERVE_HORS_WINDOWS
    store, etat = _lire_store_reserve()
    if etat != RESERVE_TROUVE:
        return None, etat
    enc = store.get(key)
    if not enc:
        return None, RESERVE_CLE_ABSENTE
    try:
        return _unprotect(base64.b64decode(enc)).decode("utf-8"), RESERVE_TROUVE
    except Exception:  # noqa: BLE001 -- scelle pour un AUTRE compte, ou altere : illisible, pas absent
        return None, RESERVE_INDECHIFFRABLE


def reserve_list() -> tuple[list[str], str]:
    """(noms, etat) du coffre reserve -- jamais les valeurs."""
    if not _IS_WIN:
        return [], RESERVE_HORS_WINDOWS
    store, etat = _lire_store_reserve()
    return sorted(store.keys()), etat


def reserve_set(key: str, value: str) -> bool:
    """Scelle `value` en portee UTILISATEUR dans le coffre reserve. True ssi verifie
    par relecture.

    Refuse -- False, et le dit -- hors SYSTEM, si le dossier manque (il se cree par
    l'owner, avec son ACL), ou si le coffre existant est illisible (l'ecraser perdrait
    ce qu'il contient).
    """
    if not _IS_WIN:
        print("[coffre_reserve] refuse : Windows seulement")
        return False
    sid = _sid_courant()
    if sid != RESERVE_COMPTE_SID:
        print(f"[coffre_reserve] refuse : compte {sid or 'ILLISIBLE'} -- seul SYSTEM scelle ce coffre")
        return False
    if not RESERVE_PATH.parent.is_dir():
        print(f"[coffre_reserve] refuse : {RESERVE_PATH.parent} absent -- il se cree par l'owner, avec son ACL")
        return False
    store, etat = _lire_store_reserve()
    if etat not in (RESERVE_TROUVE, RESERVE_COFFRE_ABSENT):
        print(f"[coffre_reserve] refuse : coffre existant {etat}")
        return False
    try:
        store[key] = base64.b64encode(
            _protect(value.encode("utf-8"), portee_machine=False)).decode("ascii")
        tmp = RESERVE_PATH.parent / (RESERVE_PATH.name + ".tmp")
        tmp.write_text(json.dumps(store, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(RESERVE_PATH)
    except Exception as e:  # noqa: BLE001
        print(f"[coffre_reserve] set {key} echec : {type(e).__name__}")
        return False
    return reserve_lire(key) == (value, RESERVE_TROUVE)


def _est_nom_reserve(key: str) -> bool:
    """La liste vit dans `forge_secrets` (une seule copie). Inimportable = INCONNU,
    traite comme reserve : une ecriture de secret ne se decide pas sur une ignorance."""
    try:
        from nokido_agent.app.forge_secrets import NOMS_RESERVES
    except Exception:  # noqa: BLE001
        return True
    return key in NOMS_RESERVES


def _garde_copie_reservee(key: str, value: str) -> Optional[str]:
    """Motif de REFUS d'une ecriture au coffre machine, ou None.

    `get_secret` lit la copie RESERVEE avant ce coffre : l'ecrire ici seul la
    laisserait perimee, et le corps aurait deux verites -- SYSTEM l'ancienne valeur,
    les autres comptes la nouvelle (une rotation du jeton maitre casserait
    l'authentification en silence). Tant qu'une copie reservee existe, l'ecriture la
    met a jour d'abord, ou n'a pas lieu.
    """
    noms, etat = reserve_list()
    if etat in (RESERVE_COFFRE_ABSENT, RESERVE_HORS_WINDOWS):
        return None
    if etat == RESERVE_TROUVE:
        if key not in noms:
            return None
        if reserve_set(key, value):
            return None
        return "copie RESERVEE non mise a jour (seul SYSTEM la scelle) -- rien n'est ecrit"
    if _est_nom_reserve(key):
        return (f"coffre reserve {etat} pour ce compte : une copie reservee resterait "
                "peut-etre perimee -- ecrire sous SYSTEM")
    return None


def main() -> int:
    """CLI du coffre machine DPAPI.

    Entrypoint console `nokido-vault` (pyproject [project.scripts]). Le corps
    vivait dans le garde `__main__` : la cible declaree n'existait donc pas, et
    la commande installee par pip mourait en AttributeError (mesure 2026-08-27).
    """
    import argparse
    import getpass

    ap = argparse.ArgumentParser(description="Nokido coffre machine DPAPI")
    ap.add_argument("cmd", choices=["test", "list", "get", "set", "del"])
    ap.add_argument("--key", "-k", help="Nom de la cle")
    a = ap.parse_args()

    if not available():
        sys.exit("Aucun backend coffre disponible. Sur Linux/macOS, installe `keyring`: pip install keyring")

    if a.cmd == "test":
        ok = vault_set("__selftest__", "hello-machine-vault")
        rt = ok and vault_get("__selftest__") == "hello-machine-vault"
        vault_delete("__selftest__")
        print(f"roundtrip DPAPI machine-scope : {'OK' if rt else 'FAIL'}")
        sys.exit(0 if rt else 1)
    elif a.cmd == "list":
        keys = vault_list()
        print(f"{len(keys)} cle(s) : {keys}")
    elif a.cmd == "get" and a.key:
        v = vault_get(a.key)
        print(f"{a.key} = {'***' + v[-4:] if v else 'ABSENT'}")
    elif a.cmd == "set" and a.key:
        ok = vault_set(a.key, getpass.getpass(f"Valeur pour {a.key}: "))
        print("OK" if ok else "ECHEC")
    elif a.cmd == "del" and a.key:
        print("supprimee" if vault_delete(a.key) else "absente")
    else:
        sys.exit("usage: cmd [--key CLE]  (get/set/del exigent --key)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
