#!/usr/bin/env python3
"""
forge_at_rest_veracrypt.py — At-rest #1 via conteneur chiffré, CROSS-OS.

Décision 2026-06-01 (panel multi-LLM) : chiffrement bloc transparent (conteneur
monté) préserve la vitesse RAG (0 overhead/requête, FTS5 + vecteurs intacts),
contrairement à SQLCipher (+10-30%/requête) et EFS (cassé multi-compte).

Backends par OS :
  - Windows : VeraCrypt.exe / "VeraCrypt Format.exe" + mklink, monté sur lettre.
  - Linux   : `veracrypt --text` (conteneur, comme Windows) OU LUKS (--backend luks,
              cryptsetup + image loop) ; symlink = os.symlink ; monté sur dir.
  - macOS   : `veracrypt --text` ; symlink = os.symlink ; monté sur dir.

⚠️ Chemins Linux/macOS groundés sur la CLI standard, NON testés sur Windows.
   Valider sur l'OS cible. `migrate` REFUSE si DB ouverte ; backup auto ; jamais
   de suppression non vérifiée.

CLÉ : keyfile 64o au machine_vault (DPAPI win / keyring mac-linux), matérialisé
en temp éphémère au mount, supprimé après. Jamais en clair sur disque.

RUNBOOK : voir --help. Étapes : (stop services) → --init-key → --create → --mount
→ --migrate → --verify → (start services) → boot auto via forge_install_boot_mount.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `cmd_rekey` — Change le fichier-cle SANS interface graphique (remplace la voie retiree le 2026-09-28).
- `cmd_rekey_abandonner` — Efface une preparation SEULEMENT si l'ANCIENNE cle ouvre l'en-tete ACTUEL, prouve hors VeraCrypt en lecture seule.
- `cmd_rekey_clore` — Efface REKEY_DIR apres un --rekey REUSSI (anciens en-tetes, ancienne cle, copie de la nouvelle), seulement si la phase est « verifie ».
- `cmd_rekey_finaliser` — Phase 3 (SYSTEM) : nouvelle cle au coffre reserve, copie du coffre machine RETIREE.
- `cmd_rekey_preparer` — RETIRE le 2026-09-28 -- voie graphique (incident V:). Refuse, ne cree rien, le dit.
- `cmd_rekey_restaurer` — Remet les en-tetes sauvegardes par --rekey et l'ancienne cle au coffre reserve.
- `cmd_rekey_verifier` — RETIRE le 2026-09-28 -- voie graphique (incident V:). Refuse, ne monte rien, le dit.
- `cmd_verifier_cle` — La cle rangee ouvre-t-elle l'en-tete ACTUEL ? Lecture seule, sans montage, a faire AVANT tout demontage ou changement de cle.
- `verdict_cle_entete` — LECTURE SEULE : {'principal', 'secours'} valent OUVRE, NON ou ILLISIBLE, + 'motif'.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # forge_machine_vault
RAG_DIR = ROOT / "RAG"
DB_FILES = ["embeddings.db", "execution_traces.db"]

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# Conteneur 50GiB hors-repo (l'ancien 16GiB ROOT/rag_secure.hc était trop petit ;
# stocké hors du dépôt git). Défaut OS-aware pour que le boot `--mount` (sans env)
# trouve le bon conteneur. Approche montage = lettre + JONCTION /J (cf. cmd_migrate),
# PAS file-symlink (le file-symlink RAG/embeddings.db→V: a cassé l'atomicité WAL =
# corruption 2026-06-02 ; voir memory/incident_db_corruption_recovery_2026-06-02).
# NE PAS renommer en Nokido_data : chemin d'ETAT EXTERNE, le dossier sur disque
# s'appelle LaForge_data (comme les services NSSM restes 'LaForge*'). Le rename
# 2026-07-08 l'avait reecrit -> --mount echouait sur "conteneur absent".
_DEFAULT_CONTAINER = (r"C:\LaForge_data\rag_secure_50g.hc" if IS_WIN
                      else str(ROOT / "rag_secure_50g.hc"))
CONTAINER = Path(os.environ.get("LAFORGE_VC_CONTAINER", _DEFAULT_CONTAINER))
KEYFILE_DISK = Path(os.environ.get("LAFORGE_VC_KEYFILE", str(ROOT / "sandbox" / "vc_keyfile.bin")))
VAULT_KEY = "LAFORGE_VC_KEYFILE_B64"
BACKEND = os.environ.get("LAFORGE_VC_BACKEND", "veracrypt")  # veracrypt | luks (linux)

# Cible de montage : lettre (Windows) ou dossier (POSIX)
if IS_WIN:
    MOUNT_TARGET = os.environ.get("LAFORGE_VC_LETTER", "V")
else:
    MOUNT_TARGET = os.environ.get("LAFORGE_VC_MOUNT", str(ROOT / "sandbox" / "rag_mnt"))


def _log(m: str) -> None:
    print(f"[at-rest-vc] {m}", flush=True)


def _vc_format_bin() -> str | None:
    if IS_WIN:
        p = Path(r"C:\Program Files\VeraCrypt") / "VeraCrypt Format.exe"
        return str(p) if p.exists() else None
    return shutil.which("veracrypt")


def _vc_main_bin() -> str | None:
    if IS_WIN:
        p = Path(r"C:\Program Files\VeraCrypt") / "VeraCrypt.exe"
        return str(p) if p.exists() else None
    return shutil.which("veracrypt")


def _mount_path() -> Path:
    return Path(f"{MOUNT_TARGET}:\\") if IS_WIN else Path(MOUNT_TARGET)


def _is_mounted() -> bool:
    if IS_WIN:
        return _mount_path().exists()
    return os.path.ismount(str(_mount_path()))


def _fs() -> str:
    if IS_WIN:
        return "NTFS"
    if IS_MAC:
        return "exFAT"  # >4GB ok (embeddings.db 7.2GB), cross-tool
    return "ext4"


def _vault_get(key: str):
    """Au GUICHET (2026-09-28) : le fichier-cle est un nom reserve -- coffre reserve d'abord
    sous SYSTEM (tache de demarrage), transition dite ailleurs. Plus jamais le coffre machine
    en direct, hors guichet et hors recensement."""
    try:
        from nokido_agent.app.forge_secrets import get_secret
        return get_secret(key)
    except Exception:
        return None


def _vault_set(key: str, value: str) -> bool:
    try:
        from nokido_agent.app.forge_machine_vault import vault_set
        return vault_set(key, value)
    except Exception as e:
        _log(f"WARN: vault indisponible ({e})")
        return False


@contextlib.contextmanager
def _keyfile():
    """Matérialise le keyfile (vault > disque) en temp éphémère, supprimé après."""
    b64 = _vault_get(VAULT_KEY)
    if b64:
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".kf")
        try:
            tf.write(base64.b64decode(b64))
            tf.close()
            yield tf.name
        finally:
            with contextlib.suppress(OSError):
                os.remove(tf.name)
        return
    if KEYFILE_DISK.exists():
        _log("WARN: keyfile sur disque (préférer le vault via --init-key).")
        yield str(KEYFILE_DISK)
        return
    _log("ERREUR: aucune clé (lancer --init-key).")
    sys.exit(1)


# ── Constructeurs de commandes par OS ──────────────────────────────────────

def _create_cmd(keyfile: str, size_bytes: int) -> list[str]:
    if IS_WIN:
        return [_vc_format_bin(), "/create", str(CONTAINER), "/size", str(size_bytes),
                "/encryption", "AES", "/hash", "sha512", "/filesystem", "NTFS",
                "/silent", "/force", "/keyfile", keyfile, "/password", ""]
    # POSIX veracrypt --text non-interactif
    return ["veracrypt", "--text", "--create", str(CONTAINER), "--size", str(size_bytes),
            "--volume-type", "normal", "--encryption", "AES", "--hash", "sha-512",
            "--filesystem", _fs(), "--pim", "0", "-k", "", "--keyfiles", keyfile,
            "--random-source", "/dev/urandom", "--non-interactive"]


def _mount_cmd(keyfile: str) -> list[str]:
    if IS_WIN:
        return [_vc_main_bin(), "/volume", str(CONTAINER), "/letter", MOUNT_TARGET,
                "/quit", "/silent", "/keyfile", keyfile, "/password", ""]
    return ["veracrypt", "--text", "--non-interactive", "--pim", "0", "-k", "",
            "--protect-hidden", "no", "--keyfiles", keyfile,
            str(CONTAINER), str(_mount_path())]


# ── En-tete VeraCrypt verifie HORS VeraCrypt (incident du 2026-09-28) ─────────
# V: est reste inaccessible ~2 h : une etape de l'interface graphique (« Ajouter/Supprimer des
# fichiers cles ») avait reecrit les deux en-tetes avec un verrou inconnu, et `--mount` ne
# disait que « rc=1 » (VeraCrypt en /silent). Ce dechiffrement -- valide ce jour-la sur les
# en-tetes des cliches VSS du 27/09 -- tranche en LECTURE SEULE « la cle n'ouvre pas l'en-tete »
# contre « l'echec vient d'ailleurs ». Il ne rend qu'un VERDICT : jamais la cle, jamais l'en-tete
# dechiffre (il contient la cle maitresse). NR : tests/nr/test_vc_entete_hors_veracrypt_nr.py.
ENTETE_GROUPE = 131072          # groupe d'en-tetes : normal 64 Kio + cache 64 Kio
_PRFS_ENTETE = ("sha512", "sha256", "blake2s256")
_ITERATIONS_ENTETE = 500000     # volume standard, PIM par defaut


def _pool_fichiers_cles(fichiers: list[bytes], taille: int) -> bytes:
    """Pool VeraCrypt (KeyFileProcess) : CRC32 octet par octet, ses 4 octets ajoutes au pool ;
    chaque fichier repart a la position 0 ; les pools s'additionnent (ordre indifferent)."""
    pool = [0] * taille
    for kf in fichiers:
        pos, c = 0, 0
        for b in kf[:1048576]:
            c = zlib.crc32(bytes([b]), c)
            reg = c ^ 0xFFFFFFFF                  # registre VeraCrypt, sans XOR final
            for decalage in (24, 16, 8, 0):
                pool[pos] = (pool[pos] + ((reg >> decalage) & 0xFF)) & 0xFF
                pos += 1
            if pos >= taille:
                pos = 0
    return bytes(pool)


def _entete_clair(entete512: bytes, fichiers: list[bytes]):
    """(prf, taille_pool, clair448) si la magie VERA apparait avec ce(s) fichier(s)-cle(s) et
    un mot de passe vide, sinon None. AES-XTS seul : le conteneur est cree en AES (`_create_cmd`).
    Le clair contient la cle MAITRESSE : il ne sort jamais de ce module."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    sel = entete512[:64]
    for taille in (64, 128):
        mdp = _pool_fichiers_cles(fichiers, taille)
        for prf in _PRFS_ENTETE:
            try:
                dk = hashlib.pbkdf2_hmac(prf, mdp, sel, _ITERATIONS_ENTETE, dklen=64)
            except (ValueError, TypeError):
                continue  # muet-ok : PRF absente de cet OpenSSL, les autres sont essayees
            dec = Cipher(algorithms.AES(dk), modes.XTS(b"\x00" * 16)).decryptor()
            clair = dec.update(entete512[64:512]) + dec.finalize()
            if clair[:4] == b"VERA":
                return prf, taille, clair
    return None


def _entete_ouvre(entete512: bytes, fichiers: list[bytes]):
    """(prf, taille_pool) si ce(s) fichier(s)-cle(s) ouvrent l'en-tete, sinon None."""
    r = _entete_clair(entete512, fichiers)
    return (r[0], r[1]) if r else None


def _entete_chiffre(clair: bytes, fichiers: list[bytes], prf: str) -> bytes:
    """En-tete de 512 octets : NOUVEAU sel + le MEME clair chiffre sous le nouveau fichier-cle.
    Pool de 64 : c'est celui que VeraCrypt applique a un mot de passe vide (<= 64 caracteres)."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    sel = os.urandom(64)
    dk = hashlib.pbkdf2_hmac(prf, _pool_fichiers_cles(fichiers, 64), sel, _ITERATIONS_ENTETE, dklen=64)
    enc = Cipher(algorithms.AES(dk), modes.XTS(b"\x00" * 16)).encryptor()
    return sel + enc.update(clair) + enc.finalize()


def verdict_cle_entete(fichier_cle: bytes, conteneur: Path | None = None) -> dict:
    """LECTURE SEULE : {'principal', 'secours'} valent OUVRE, NON ou ILLISIBLE, + 'motif'.
    ILLISIBLE n'est JAMAIS « la cle ne marche pas » : sans lecture, pas de verdict."""
    chemin = Path(conteneur or CONTAINER)
    try:
        taille = chemin.stat().st_size
        with open(chemin, "rb") as f:
            principal = f.read(512)
            f.seek(taille - ENTETE_GROUPE)
            secours = f.read(512)
    except OSError as e:
        motif = type(e).__name__ + (" (volume monte : conteneur tenu par VeraCrypt ?)"
                                    if _is_mounted() else "")
        return {"principal": "ILLISIBLE", "secours": "ILLISIBLE", "motif": motif}
    return {"principal": "OUVRE" if _entete_ouvre(principal, [fichier_cle]) else "NON",
            "secours": "OUVRE" if _entete_ouvre(secours, [fichier_cle]) else "NON", "motif": ""}


def _diagnostic_echec_montage() -> None:
    """VeraCrypt en /silent ne dit pas POURQUOI : on tranche hors VeraCrypt, en lecture seule."""
    b64 = _vault_get(VAULT_KEY)
    if not b64:
        _log("  diagnostic : cle illisible pour ce compte -- aucun verdict possible.")
        return
    try:
        v = verdict_cle_entete(base64.b64decode(b64))
    except Exception as e:  # noqa: BLE001 -- un diagnostic ne doit jamais masquer l'echec
        _log(f"  diagnostic impossible ({type(e).__name__}).")
        return
    if v["principal"] == "OUVRE":
        _log("  diagnostic : la cle OUVRE l'en-tete (verifie hors VeraCrypt) -- l'echec vient "
             "d'ailleurs : droits sur le conteneur, lettre deja prise, VeraCrypt.")
    elif v["principal"] == "NON":
        _log(f"  diagnostic : la cle N'OUVRE PAS l'en-tete principal (verifie hors VeraCrypt ; "
             f"secours : {v['secours']}). NE RIEN ECRIRE : chercher un en-tete anterieur dans "
             "les cliches VSS (vssadmin list shadows) avant toute restauration.")
    else:
        _log(f"  diagnostic : en-tete ILLISIBLE ({v['motif']}) -- aucun verdict.")


def cmd_verifier_cle() -> int:
    """La cle rangee ouvre-t-elle l'en-tete ACTUEL ? Lecture seule, sans montage. A faire AVANT
    tout demontage ou changement de cle (lecon du 2026-09-28). 0 = les deux en-tetes s'ouvrent,
    1 = refus, 2 = pas de verdict (cle ou conteneur illisible)."""
    b64 = _vault_get(VAULT_KEY)
    if not b64:
        _log("cle ILLISIBLE pour ce compte (guichet) : aucun verdict -- ce n'est pas « la cle "
             "ne marche pas ».")
        return 2
    v = verdict_cle_entete(base64.b64decode(b64))
    _log(f"en-tete principal : {v['principal']} ; en-tete de secours : {v['secours']}"
         + (f" ; motif : {v['motif']}" if v["motif"] else ""))
    if v["principal"] == "OUVRE" and v["secours"] == "OUVRE":
        return 0
    return 2 if "ILLISIBLE" in (v["principal"], v["secours"]) else 1


def _lire_entetes(chemin: Path) -> tuple[int, bytes, bytes]:
    """(taille, groupe principal, groupe de secours) -- 128 Kio chacun, lecture seule."""
    taille = chemin.stat().st_size
    with open(chemin, "rb") as f:
        principal = f.read(ENTETE_GROUPE)
        f.seek(taille - ENTETE_GROUPE)
        secours = f.read(ENTETE_GROUPE)
    return taille, principal, secours


def _ecrire_entetes(chemin: Path, taille: int, principal: bytes, secours: bytes) -> None:
    with open(chemin, "r+b") as f:
        f.seek(0)
        f.write(principal)
        f.seek(taille - ENTETE_GROUPE)
        f.write(secours)
        f.flush()
        os.fsync(f.fileno())


def cmd_rekey(appliquer: bool) -> int:
    """Change le fichier-cle SANS interface graphique (remplace la voie retiree le 2026-09-28).

    Rechiffre les DEUX en-tetes : meme clair -- donc meme cle maitresse, memes donnees --,
    nouveau sel, nouveau fichier-cle. Ordre qui ne peut pas perdre l'acces : preuve, sauvegarde
    RELUE, nouvelle cle sur disque AVANT l'ecriture, relecture (nouvelle OUVRE / ancienne NON,
    sinon en-tetes REMIS), rangement au coffre reserve RELU. Sans `appliquer` : preuves seules.
    SYSTEM seulement (coffre reserve). NR : tests/nr/test_vc_rekey_scripte_nr.py."""
    from nokido_agent.app import forge_machine_vault as mv

    b64 = _vault_get(VAULT_KEY)
    if not b64:
        _log("cle rangee ILLISIBLE pour ce compte : rien n'est fait.")
        return 2
    ancienne = base64.b64decode(b64)
    try:
        taille, gp, gs = _lire_entetes(CONTAINER)
    except OSError as e:
        _log(f"conteneur ILLISIBLE ({type(e).__name__}) : rien n'est fait.")
        return 2
    cp, cs = _entete_clair(gp[:512], [ancienne]), _entete_clair(gs[:512], [ancienne])
    if not (cp and cs):
        _log(f"REFUS : la cle rangee n'ouvre pas les DEUX en-tetes (principal "
             f"{'OUVRE' if cp else 'NON'}, secours {'OUVRE' if cs else 'NON'}) -- rien n'est fait.")
        return 1
    _log(f"preuve : la cle rangee ouvre les deux en-tetes ({cp[0]}).")
    if not appliquer:
        _log("PREUVES OK, RIEN N'A ETE ECRIT. Pour changer la cle : --rekey --appliquer (SYSTEM).")
        return 0
    if mv._sid_courant() != mv.RESERVE_COMPTE_SID:
        _log("REFUS : SYSTEM requis (la nouvelle cle se range au coffre reserve) -- rien n'est fait.")
        return 1
    if REKEY_DIR.exists():
        _log(f"REFUS : un changement est deja EN COURS ({REKEY_DIR}), jamais ecrase -- rien n'est fait.")
        return 1

    REKEY_DIR.mkdir(parents=True)
    subprocess.run(["icacls", str(REKEY_DIR), "/inheritance:r", "/grant:r",
                    "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"], capture_output=True, text=True,
                   errors="replace")
    (REKEY_DIR / "entete_avant_principal.bin").write_bytes(gp)
    (REKEY_DIR / "entete_avant_secours.bin").write_bytes(gs)
    (REKEY_DIR / "ancien.kf").write_bytes(ancienne)
    nouvelle = os.urandom(64)
    (REKEY_DIR / "nouveau.kf").write_bytes(nouvelle)
    if ((REKEY_DIR / "entete_avant_principal.bin").read_bytes() != gp
            or (REKEY_DIR / "entete_avant_secours.bin").read_bytes() != gs
            or (REKEY_DIR / "nouveau.kf").read_bytes() != nouvelle):
        _log("ERREUR : sauvegarde ou nouvelle cle NON relue identique -- les en-tetes ne sont PAS touches.")
        return 1
    _rekey_ecrire_etat("ecriture")

    np_ = _entete_chiffre(cp[2], [nouvelle], cp[0]) + gp[512:]
    ns_ = _entete_chiffre(cs[2], [nouvelle], cs[0]) + gs[512:]
    try:
        _ecrire_entetes(CONTAINER, taille, np_, ns_)
    except OSError as e:
        _rekey_ecrire_etat("ecriture_refusee")
        _log(f"ECRITURE REFUSEE ({type(e).__name__}{' ; volume monte ?' if _is_mounted() else ''}) "
             "-- l'ancienne cle reste en service ; --rekey-abandonner nettoie.")
        return 1
    _, rp, rs = _lire_entetes(CONTAINER)
    if not (_entete_ouvre(rp[:512], [nouvelle]) and _entete_ouvre(rs[:512], [nouvelle])
            and not _entete_ouvre(rp[:512], [ancienne]) and not _entete_ouvre(rs[:512], [ancienne])):
        _ecrire_entetes(CONTAINER, taille, gp, gs)
        _rekey_ecrire_etat("remis")
        _log("ECHEC de la relecture : en-tetes d'avant REMIS ; l'ancienne cle reste en service.")
        return 1

    b64n = base64.b64encode(nouvelle).decode("ascii")
    ecrit = mv.reserve_set(VAULT_KEY, b64n)
    # `reserve_lire` rend (valeur, etat) : comparer le tuple a la chaine a produit, le
    # 2026-09-28, une fausse alerte « cle NON rangee » alors que la cle ETAIT rangee (et la
    # copie du coffre machine n'a pas ete retiree). On compare la VALEUR.
    relue, _etat = mv.reserve_lire(VAULT_KEY) if ecrit else (None, "NON_ECRIT")
    if not ecrit or relue != b64n:
        _rekey_ecrire_etat("ecrit_non_range")
        _log(f"ATTENTION : en-tetes changes mais cle NON rangee au coffre reserve. Elle est dans "
             f"{REKEY_DIR / 'nouveau.kf'} -- NE RIEN EFFACER ; --rekey-restaurer remet l'ancienne.")
        return 1
    mv.vault_delete(VAULT_KEY)
    _rekey_ecrire_etat("verifie")
    _log("OK : cle changee (les deux en-tetes rechiffres, relus : nouvelle OUVRE, ancienne NON) ; "
         "nouvelle cle au coffre reserve, relue. Sauvegardes et cles conservees dans "
         f"{REKEY_DIR} jusqu'a la cloture.")
    return 0


def cmd_rekey_restaurer() -> int:
    """Remet les en-tetes sauvegardes par --rekey et l'ancienne cle au coffre reserve."""
    from nokido_agent.app import forge_machine_vault as mv

    fp, fs = REKEY_DIR / "entete_avant_principal.bin", REKEY_DIR / "entete_avant_secours.bin"
    ancien = REKEY_DIR / "ancien.kf"
    if not (fp.exists() and fs.exists() and ancien.exists()):
        _log("rien a restaurer (aucune sauvegarde d'en-tetes).")
        return 1
    if mv._sid_courant() != mv.RESERVE_COMPTE_SID:
        _log("REFUS : SYSTEM requis (l'ancienne cle retourne au coffre reserve).")
        return 1
    gp, gs, ancienne = fp.read_bytes(), fs.read_bytes(), ancien.read_bytes()
    if not (_entete_ouvre(gp[:512], [ancienne]) and _entete_ouvre(gs[:512], [ancienne])):
        _log("REFUS : la sauvegarde ne s'ouvre pas avec l'ancienne cle -- rien n'est ecrit.")
        return 1
    taille = CONTAINER.stat().st_size
    _ecrire_entetes(CONTAINER, taille, gp, gs)
    _, rp, rs = _lire_entetes(CONTAINER)
    if rp != gp or rs != gs:
        _log("ERREUR : relecture DIFFERENTE apres restauration.")
        return 1
    mv.reserve_set(VAULT_KEY, base64.b64encode(ancienne).decode("ascii"))
    _rekey_ecrire_etat("restaure")
    _log("RESTAURE : en-tetes d'avant remis et relus ; ancienne cle au coffre reserve.")
    return 0


def cmd_rekey_clore() -> int:
    """Efface REKEY_DIR apres un --rekey REUSSI : anciens en-tetes + ancienne cle (= acces a la
    cle maitresse) et copie de la nouvelle cle. SEULEMENT si la phase est « verifie » (en-tetes
    rechiffres et relus) ET si le coffre reserve contient exactement nouveau.kf. Sinon rien."""
    from nokido_agent.app import forge_machine_vault as mv

    nouveau = REKEY_DIR / "nouveau.kf"
    if not nouveau.exists():
        _log("rien a clore.")
        return 1
    if _rekey_etat().get("phase") != "verifie":
        _log(f"REFUS : phase « {_rekey_etat().get('phase')} », pas « verifie » -- rien n'est efface.")
        return 1
    relue, etat = mv.reserve_lire(VAULT_KEY)
    if relue != base64.b64encode(nouveau.read_bytes()).decode("ascii"):
        _log(f"REFUS : le coffre reserve ne contient pas la nouvelle cle ({etat}) -- rien n'est efface.")
        return 1
    _rekey_effacer()
    _log("clos : anciens en-tetes, ancienne cle et copie de la nouvelle cle effaces ; la cle en "
         "service vit au coffre reserve seulement.")
    return 0


def _make_symlink(src: Path, dst: Path) -> bool:
    if IS_WIN:
        return subprocess.run(["cmd", "/c", "mklink", str(src), str(dst)], timeout=30).returncode == 0
    try:
        os.symlink(str(dst), str(src))
        return src.is_symlink()
    except OSError as e:
        _log(f"  symlink échec: {e}")
        return False


# ── Jonction de répertoire (approche at-rest courante, remplace file-symlink) ─
# Une JONCTION de dossier (Windows mklink /J) résout le chemin ENTIER, donc
# RAG/embeddings.db-wal → %NOKIDO_DATA%\embeddings.db-wal (même volume) : un seul -wal, zéro
# split. Le file-symlink par-fichier (ancien code) mettait le -wal côté lien (C:)
# pendant que la DB était sur V: → désync WAL → corruption 2026-06-02. NE PLUS
# jamais file-symlinker une .db. Voir memory/incident_db_corruption_recovery.

def _is_junction(p: Path) -> bool:
    """True si p est une jonction/reparse-point (dir) ou un symlink (POSIX)."""
    if not IS_WIN:
        return p.is_symlink()
    try:
        import stat as _stat
        return bool(os.lstat(str(p)).st_file_attributes & _stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


def _make_junction(link: Path, target: Path) -> bool:
    """Jonction de dossier link → target (résout -wal au bon endroit)."""
    if IS_WIN:
        return subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                              timeout=30).returncode == 0
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return link.is_dir()
    except OSError as e:
        _log(f"  jonction échec: {e}")
        return False


# ── LUKS (Linux natif, alternatif) ─────────────────────────────────────────

def _luks_create(keyfile: str, size_bytes: int) -> int:
    img = str(CONTAINER)
    name = "nokido_rag"
    mp = str(_mount_path())
    steps = [
        ["truncate", "-s", str(size_bytes), img],
        ["cryptsetup", "luksFormat", "--batch-mode", "--key-file", keyfile, img],
        ["cryptsetup", "open", "--key-file", keyfile, img, name],
        ["mkfs.ext4", f"/dev/mapper/{name}"],
        ["cryptsetup", "close", name],
    ]
    for c in steps:
        rc = subprocess.run(c, timeout=600).returncode
        if rc != 0:
            _log(f"ERREUR LUKS: {' '.join(c)} rc={rc}")
            return 1
    _log("OK conteneur LUKS créé.")
    return 0


def _luks_mount(keyfile: str) -> int:
    img = str(CONTAINER); name = "nokido_rag"; mp = str(_mount_path())
    Path(mp).mkdir(parents=True, exist_ok=True)
    if subprocess.run(["cryptsetup", "open", "--key-file", keyfile, img, name]).returncode != 0:
        return 1
    return subprocess.run(["mount", f"/dev/mapper/{name}", mp]).returncode


# ── Commandes ──────────────────────────────────────────────────────────────

def cmd_init_key() -> int:
    if _vault_get(VAULT_KEY):
        _log("keyfile déjà présent au vault.")
        return 0
    if _vault_set(VAULT_KEY, base64.b64encode(os.urandom(64)).decode("ascii")):
        _log("keyfile généré + stocké au machine_vault. Aucun secret en clair sur disque.")
        return 0
    _log("ERREUR: stockage vault échoué.")
    return 1


def cmd_create(size_gb: int) -> int:
    if CONTAINER.exists():
        _log(f"ERREUR: conteneur existe déjà: {CONTAINER}")
        return 1
    size = max(size_gb, 12) * 1024 * 1024 * 1024
    if IS_LINUX and BACKEND == "luks":
        with _keyfile() as kf:
            return _luks_create(kf, size)
    if not _vc_format_bin():
        _log("ERREUR: VeraCrypt absent (win: IDRIX.VeraCrypt ; posix: paquet veracrypt).")
        return 1
    _log(f"création conteneur {CONTAINER} ({size_gb} GiB, AES) [{'win' if IS_WIN else 'posix'}]...")
    with _keyfile() as kf:
        rc = subprocess.run(_create_cmd(kf, size), timeout=3600).returncode
    if rc != 0:
        _log(f"ERREUR: create rc={rc}")
        return 1
    _log("OK conteneur créé. Suivant: --mount")
    return 0


def cmd_mount() -> int:
    if not CONTAINER.exists():
        _log(f"ERREUR: conteneur absent: {CONTAINER} (--create d'abord)")
        return 1
    if _is_mounted():
        _log(f"déjà monté sur {_mount_path()}")
        return 0
    if not IS_WIN:
        Path(_mount_path()).mkdir(parents=True, exist_ok=True)
    _log(f"montage {CONTAINER} -> {_mount_path()}")
    if IS_LINUX and BACKEND == "luks":
        with _keyfile() as kf:
            rc = _luks_mount(kf)
    else:
        if not _vc_main_bin():
            _log("ERREUR: VeraCrypt absent.")
            return 1
        with _keyfile() as kf:
            rc = subprocess.run(_mount_cmd(kf), timeout=120).returncode
    if rc != 0 or not _is_mounted():
        _log(f"ERREUR: montage échoué rc={rc}")
        if not (IS_LINUX and BACKEND == "luks"):
            _diagnostic_echec_montage()
        return 1
    _log(f"OK monté sur {_mount_path()}")
    return 0


def _db_open_elsewhere(db: Path) -> bool:
    if not db.exists():
        return False
    try:
        con = sqlite3.connect(f"file:{db}?mode=rw", uri=True, timeout=1)
        con.execute("BEGIN EXCLUSIVE")
        con.execute("COMMIT")
        con.close()
        return False
    except sqlite3.OperationalError:
        return True


def cmd_migrate() -> int:
    """Bascule RAG/ ENTIER sur le volume chiffré monté, via JONCTION de dossier.
    Idempotent (skip si RAG/ déjà jonction). Services Nokido doivent être arrêtés.
    RAG/ original conservé en RAG_plain_bak/ (à supprimer après --verify)."""
    if not _is_mounted():
        _log(f"ERREUR: volume non monté ({_mount_path()}) (--mount d'abord)")
        return 1
    if RAG_DIR.exists() and _is_junction(RAG_DIR):
        _log(f"RAG/ déjà jonction -> {_mount_path()} (déjà migré).")
        return 0
    for name in DB_FILES:
        if _db_open_elsewhere(RAG_DIR / name):
            _log(f"ERREUR: {name} OUVERTE (services actifs). Arrêter Nokido d'abord.")
            return 1
    bak = RAG_DIR.parent / "RAG_plain_bak"
    if bak.exists():
        _log(f"ERREUR: {bak} existe déjà — renommer/supprimer avant migration.")
        return 1
    mp = _mount_path()
    _log(f"copie {RAG_DIR} -> {mp} (peut prendre plusieurs minutes)...")
    if IS_WIN:
        rc = subprocess.run(["robocopy", str(RAG_DIR), str(mp), "/E", "/COPY:DAT",
                             "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/MT:8"], timeout=7200).returncode
        if rc >= 8:  # robocopy: 0-7 = succès
            _log(f"ERREUR: robocopy rc={rc}")
            return 1
    else:
        if subprocess.run(["cp", "-a", f"{RAG_DIR}/.", str(mp)], timeout=7200).returncode != 0:
            _log("ERREUR: cp échoué")
            return 1
    for name in DB_FILES:
        src = RAG_DIR / name
        dst = mp / name
        if src.exists() and not src.is_symlink() and dst.exists() and src.stat().st_size != dst.stat().st_size:
            _log(f"ERREUR: taille {name} copiée != source — abandon (RAG/ intact).")
            return 1
    RAG_DIR.rename(bak)
    _log(f"  RAG/ -> {bak.name}")
    if not _make_junction(RAG_DIR, mp):
        _log(f"  ERREUR: jonction échouée — RESTAURATION ({bak.name} -> RAG/).")
        bak.rename(RAG_DIR)
        return 1
    _log(f"OK migration jonction RAG/ -> {mp}. --verify. Garder {bak.name} jusqu'à validation.")
    return 0


def cmd_verify() -> int:
    ok = True
    if not _is_mounted():
        _log(f"  volume {_mount_path()}: NON monté")
        ok = False
    if not (RAG_DIR.exists() and _is_junction(RAG_DIR)):
        _log(f"  RAG/: PAS une jonction (attendu jonction -> {_mount_path()})")
        ok = False
    else:
        _log(f"  RAG/: jonction -> {_mount_path()} [ok]")
    for name in DB_FILES:
        f = RAG_DIR / name
        if not f.exists():
            _log(f"  {name}: absent")
            continue
        if f.is_symlink():
            _log(f"  {name}: ENCORE un file-symlink (regression WAL-split !) [FAIL]")
            ok = False
        try:
            con = sqlite3.connect(f"file:{f}?mode=ro", uri=True, timeout=5)
            n = con.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
            con.close()
            _log(f"  {name}: fichier_reel objets={n} [ok]")
        except sqlite3.Error as e:
            _log(f"  {name}: ERREUR lecture ({e})")
            ok = False
    if ok:
        _log("VERIFY OK — RAG/ jonction sur volume chiffré, DB réelles (zéro file-symlink).")
    return 0 if ok else 1


def _is_admin() -> bool:
    """True si le process est élevé. Rend None-like (False) hors Windows."""
    if not IS_WIN:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def cmd_unmount() -> int:
    """Démonte le volume. REFUSE si une base est ouverte : un /force sur une
    SQLite active corromprait le WAL (cf. incident_db_corruption_recovery_2026-06-02)."""
    if not _is_mounted():
        _log(f"déjà démonté ({_mount_path()})")
        return 0
    # Mesure 2026-07-31 : sans élévation, VeraCrypt échoue en rendant rc=1 SANS
    # rien dire. Le message générique « un processus tient le volume » a envoyé
    # la chasse au mauvais gibier (kill d'un daemon owner innocent, puis reboot
    # envisagé) alors qu'il manquait seulement les privilèges. Le dire ICI.
    if not _is_admin():
        _log("ERREUR: démontage NON ÉLEVÉ — VeraCrypt exige une console administrateur.")
        _log("  Rouvrir PowerShell en « Exécuter en tant qu'administrateur », puis relancer.")
        _log("  (un rc=1 ici ne signifie PAS qu'un processus tient le volume)")
        return 1
    ouvertes = [n for n in DB_FILES if _db_open_elsewhere(RAG_DIR / n)]
    if ouvertes:
        _log(f"ERREUR: base(s) OUVERTE(S) {ouvertes} — arrêter les services Nokido d'abord.")
        _log("  (hub :8766, superviseur, daemons ; jamais de démontage forcé sur SQLite active)")
        return 1
    if not _vc_main_bin():
        _log("ERREUR: VeraCrypt absent.")
        return 1
    rc = subprocess.run(
        [_vc_main_bin(), "/dismount", MOUNT_TARGET, "/quit", "/silent"], timeout=120
    ).returncode
    if rc != 0 or _is_mounted():
        _log(f"ERREUR: démontage échoué rc={rc} (un processus tient peut-être le volume)")
        return 1
    _log(f"OK démonté ({_mount_path()})")
    return 0


def cmd_expand(size_gb: int) -> int:
    """Agrandit le conteneur via VeraCryptExpander (volume DÉMONTÉ obligatoire).

    L'Expander n'a pas de CLI : ce wrapper pose les gardes, matérialise le keyfile
    le temps de la session, puis ouvre l'interface. L'agrandissement d'un conteneur
    ne re-chiffre pas l'existant et étend le NTFS interne.

    Exige une console ÉLEVÉE : LaForgeTrusted n'a aucun privilège Windows.
    """
    if not IS_WIN:
        _log("ERREUR: --expand n'est câblé que pour VeraCrypt Windows.")
        return 1
    if not CONTAINER.exists():
        _log(f"ERREUR: conteneur absent: {CONTAINER}")
        return 1
    if not _is_admin():
        _log("ERREUR: NON ÉLEVÉ — VeraCryptExpander exige une console administrateur.")
        return 1

    actuel = CONTAINER.stat().st_size
    cible = size_gb * 1024 * 1024 * 1024
    _log(f"conteneur {CONTAINER} : {actuel / 1024**3:.1f} GiB -> cible {size_gb} GiB")
    if cible <= actuel:
        _log("ERREUR: la cible n'est pas supérieure à la taille actuelle "
             "(VeraCrypt ne sait PAS rétrécir un conteneur).")
        return 1

    delta = cible - actuel
    libre = shutil.disk_usage(CONTAINER.parent).free
    _log(f"disque hôte {CONTAINER.parent} : {libre / 1024**3:.1f} GiB libres, "
         f"besoin {delta / 1024**3:.1f} GiB")
    if libre < delta:
        _log("ERREUR: espace insuffisant sur le disque hôte.")
        return 1

    if _is_mounted():
        _log(f"ERREUR: {_mount_path()} est MONTÉ. L'Expander exige un volume démonté.")
        _log("  1) arrêter les services Nokido   2) --unmount   3) relancer --expand")
        return 1

    expander = Path(r"C:\Program Files\VeraCrypt") / "VeraCryptExpander.exe"
    if not expander.exists():
        _log(f"ERREUR: VeraCryptExpander introuvable ({expander}).")
        return 1

    _log("NOTE: le nom du fichier restera 'rag_secure_50g.hc' après extension — "
         "il est codé dans _DEFAULT_CONTAINER et dans le montage au boot. Ne pas renommer.")
    with _keyfile() as kf:
        _log("VeraCryptExpander va s'ouvrir. Dans l'interface :")
        _log(f"  - volume        : {CONTAINER}")
        _log(f"  - nouvelle taille : {size_gb} GiB")
        _log("  - mot de passe  : VIDE, cocher « Use keyfiles » et choisir le fichier ci-dessous")
        _log(f"  - keyfile (temporaire, supprimé à la fermeture) : {kf}")
        rc = subprocess.run([str(expander), str(CONTAINER)]).returncode

    # L'Expander est une GUI : son code de retour ne dit QUE « la fenêtre s'est
    # fermée ». Mesure 2026-07-31 : rc=0 alors que le conteneur faisait toujours
    # 50 GiB. Un code de retour n'est pas une mesure -- on relit la taille.
    apres = CONTAINER.stat().st_size
    _log(f"Expander fermé (rc={rc}). Taille relue : {apres / 1024**3:.1f} GiB")
    if apres <= actuel:
        _log("AUCUNE EXTENSION DÉTECTÉE : le conteneur n'a pas grandi.")
        _log("  L'opération n'a pas été menée dans l'interface (fenêtre fermée, "
             "mot de passe/keyfile refusé, ou taille non validée).")
        _log("  Vérifier aussi l'espace libre DANS le volume après --mount : "
             "seul lui prouve que le NTFS interne a suivi.")
        return 1
    _log(f"OK conteneur étendu ({actuel / 1024**3:.1f} -> {apres / 1024**3:.1f} GiB). "
         "Suivant : --mount puis --verify, et redémarrer les services Nokido.")
    return 0


def cmd_grow(size_gb: int) -> int:
    """Passe le volume a `size_gb` par RECREATION + RECOPIE (seule voie 100 % CLI).

    Un conteneur VeraCrypt existant ne peut PAS etre agrandi sans interface :
    VeraCryptExpander n'expose aucun switch (son wWinMain ne parse que
    /protectMemory et /protectScreen) et ExpandVolume.c refuse un mot de passe
    vide (`if (pVolumePassword->Length == 0) return -1;`) -- or ce volume est
    keyfile seul. Etendre le fichier hote a la main corrompt le volume : la
    taille est scellee chiffree dans le header principal ET le backup header.
    Analyse confirmee par ANTIGRAVITY (job_5f72f952_1785524959_claude_need_clarify).

    L'ancien conteneur n'est JAMAIS supprime : il est renomme en `.old`, a
    effacer manuellement apres validation.
    """
    if not IS_WIN:
        _log("ERREUR: --grow n'est cable que pour VeraCrypt Windows.")
        return 1
    if not _is_admin():
        _log("ERREUR: NON ELEVE — montage/demontage VeraCrypt exigent l'administrateur.")
        return 1
    if not CONTAINER.exists():
        _log(f"ERREUR: conteneur absent: {CONTAINER}")
        return 1

    actuel = CONTAINER.stat().st_size
    cible = size_gb * 1024 * 1024 * 1024
    if cible <= actuel:
        _log(f"ERREUR: cible {size_gb} GiB <= taille actuelle {actuel / 1024**3:.1f} GiB.")
        return 1
    libre = shutil.disk_usage(CONTAINER.parent).free
    if libre < cible + (1 << 30):
        _log(f"ERREUR: {libre / 1024**3:.1f} GiB libres sur l'hote, il en faut "
             f"{cible / 1024**3:.0f} (l'ancien et le neuf coexistent).")
        return 1

    lettre_tmp = os.environ.get("LAFORGE_VC_LETTER_TMP", "W")
    neuf = CONTAINER.with_name(f"rag_secure_{size_gb}g_new.hc")
    fmt, vc = _vc_format_bin(), _vc_main_bin()
    if not fmt or not vc:
        _log("ERREUR: VeraCrypt introuvable.")
        return 1
    reprise = False
    if neuf.exists():
        # Reprise : un --grow interrompu APRES la creation laisse un conteneur
        # valide. Le recreer couterait une seconde ecriture chiffree de la taille
        # cible pour rien ; robocopy repart en incrementiel.
        if neuf.stat().st_size == cible:
            _log(f"reprise : {neuf.name} existe deja a la bonne taille, on le reutilise.")
            reprise = True
        else:
            _log(f"ERREUR: {neuf} existe avec une taille inattendue "
                 f"({neuf.stat().st_size / 1024**3:.1f} GiB) — le retirer d'abord.")
            return 1

    # Les services doivent etre a l'arret : on copie un etat SQLite vivant sinon.
    if _is_mounted():
        ouvertes = [n for n in DB_FILES if _db_open_elsewhere(RAG_DIR / n)]
        if ouvertes:
            _log(f"ERREUR: base(s) OUVERTE(S) {ouvertes} — arreter Nokido d'abord.")
            return 1

    with _keyfile() as kf:
        if _is_mounted():
            _log("demontage du volume source...")
            if subprocess.run([vc, "/dismount", MOUNT_TARGET, "/quit", "/silent"],
                              timeout=120).returncode != 0 or _is_mounted():
                _log("ERREUR: demontage source echoue.")
                return 1

        if not reprise:
            _log(f"creation du conteneur {size_gb} GiB : {neuf} (peut prendre plusieurs minutes)...")
            rc = subprocess.run(
                [fmt, "/create", str(neuf), "/size", str(cible), "/encryption", "AES",
                 "/hash", "sha512", "/filesystem", "NTFS", "/silent", "/force",
                 "/keyfile", kf, "/password", ""], timeout=14400).returncode
            if rc != 0 or not neuf.exists():
                _log(f"ERREUR: creation echouee rc={rc}")
                return 1
            _log(f"  cree : {neuf.stat().st_size / 1024**3:.1f} GiB")

        _log("montage source et cible...")
        for chemin, lettre in ((CONTAINER, MOUNT_TARGET), (neuf, lettre_tmp)):
            if subprocess.run([vc, "/volume", str(chemin), "/letter", lettre, "/quit",
                               "/silent", "/keyfile", kf, "/password", ""],
                              timeout=180).returncode != 0:
                _log(f"ERREUR: montage {chemin} -> {lettre}: echoue.")
                return 1
        src, dst = Path(f"{MOUNT_TARGET}:\\"), Path(f"{lettre_tmp}:\\")
        if not src.exists() or not dst.exists():
            _log(f"ERREUR: {src} ou {dst} absent apres montage.")
            return 1

        # /XD : les metadonnees systeme du volume NTFS sont illisibles meme en
        # administrateur (mesure 2026-07-31 : 3 fichiers de System Volume
        # Information en ERREUR 5 -> robocopy rc=9, alors que 50887 fichiers sur
        # 50890 et 36,3 Go etaient passes). Elles sont recreees par le systeme
        # sur le volume cible : les exclure, plutot qu'echouer sur du bruit.
        exclusions = ["/XD", str(src / "System Volume Information"), str(src / "$RECYCLE.BIN")]

        def _copier(passe: int) -> int:
            _log(f"recopie {src} -> {dst} (robocopy, passe {passe})...")
            return subprocess.run(
                ["robocopy", str(src), str(dst), "/E", "/COPY:DAT", *exclusions,
                 "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/MT:8"], timeout=14400).returncode

        def _ecarts() -> list:
            out = []
            for nom in DB_FILES:
                a, b = src / nom, dst / nom
                if a.exists() and (not b.exists() or a.stat().st_size != b.stat().st_size):
                    out.append(f"{nom}: {a.stat().st_size} -> "
                               f"{b.stat().st_size if b.exists() else 'ABSENT'}")
            return out

        rc = _copier(1)
        if rc >= 8:  # robocopy : 0-7 = succes
            _log(f"ERREUR: robocopy rc={rc} — rien n'a ete remplace.")
            return 1

        # Verification AVANT tout swap : tailles des bases, a l'octet. Une seconde
        # passe rattrape une ecriture residuelle (mesure 2026-07-31 : un daemon
        # owner relance en cours de route a fait diverger execution_traces.db de
        # 516 Ko, ce qui aurait fait swapper une base incoherente).
        if _ecarts():
            _log("ecart detecte apres la 1re passe — seconde passe incrementale...")
            if _copier(2) >= 8:
                _log("ERREUR: seconde passe echouee — l'ancien conteneur est INTACT.")
                return 1
        restants = _ecarts()
        if restants:
            _log(f"ERREUR: copie incoherente {restants} — l'ancien conteneur est INTACT.")
            _log("  Un processus ecrit encore sur le volume : arreter Nokido ET les "
                 "daemons du profil owner, puis relancer --grow (il reprendra).")
            return 1
        _log(f"  copie verifiee ({', '.join(DB_FILES)} identiques a l'octet)")

        _log("demontage des deux volumes...")
        for lettre in (MOUNT_TARGET, lettre_tmp):
            subprocess.run([vc, "/dismount", lettre, "/quit", "/silent"], timeout=120)
        # Un demontage qui echoue rend le renommage impossible ("fichier utilise")
        # et laisserait croire a un swap fait. Le verifier, ne pas le supposer.
        if _mount_path().exists() or Path(f"{lettre_tmp}:\\").exists():
            _log(f"ERREUR: demontage incomplet ({MOUNT_TARGET}: ou {lettre_tmp}: "
                 "encore monte) — aucun renommage effectue, tout est INTACT.")
            return 1

    # Swap par RENOMMAGE : le nom de fichier historique est conserve, car il est
    # code dans _DEFAULT_CONTAINER et dans le montage au boot. L'ancien devient
    # .old et n'est PAS supprime.
    ancien = CONTAINER.with_name(CONTAINER.name + ".old")
    if ancien.exists():
        _log(f"ERREUR: {ancien} existe deja — le deplacer avant de recommencer.")
        return 1
    CONTAINER.rename(ancien)
    neuf.rename(CONTAINER)
    _log(f"OK swap : ancien -> {ancien.name} (conserve), neuf -> {CONTAINER.name} "
         f"({CONTAINER.stat().st_size / 1024**3:.1f} GiB)")
    _log("Suivant : --mount puis --verify, redemarrer Nokido, et supprimer le .old "
         "SEULEMENT apres validation.")
    return 0


# --- CHANGEMENT DU FICHIER-CLE (2026-09-28) -------------------------------------------------
#
# Le fichier-cle a ete lisible par les comptes bac a sable (coffre machine) : on le change,
# c.-a-d. on re-chiffre l'entete du volume. VeraCrypt ne le permet sous Windows que par son
# interface graphique, et une erreur d'ordre rend le volume inaccessible. Trois phases,
# chacune gardee ; aucune cle n'est jamais affichee.
REKEY_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "NokidoCles" / "vc_rekey"


def _rekey_etat() -> dict:
    try:
        import json as _json
        return _json.loads((REKEY_DIR / "etat.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _rekey_ecrire_etat(phase: str) -> None:
    import json as _json
    import time as _time
    (REKEY_DIR / "etat.json").write_text(_json.dumps({"phase": phase, "ts": int(_time.time())}),
                                         encoding="utf-8")


def _rekey_effacer() -> None:
    """Ecrase puis supprime les fichiers-cles temporaires, puis le dossier."""
    for nom in ("ancien.kf", "nouveau.kf"):
        f = REKEY_DIR / nom
        with contextlib.suppress(OSError):
            f.write_bytes(b"\0" * max(64, f.stat().st_size))
    shutil.rmtree(REKEY_DIR, ignore_errors=True)


def _monter_avec(keyfile: Path) -> bool:
    """Tente un montage avec CE fichier-cle ; True si le volume est monte ensuite."""
    rc = subprocess.run(_mount_cmd(str(keyfile)), timeout=120).returncode
    return rc == 0 and _is_mounted()


_VOIE_GRAPHIQUE_RETIREE = (
    "RETIRE (2026-09-28) : cette voie reposait sur une etape dans l'interface graphique de "
    "VeraCrypt ; cette etape a reecrit les deux en-tetes de V: avec un verrou inconnu (V: "
    "inaccessible ~2 h, restaure depuis les cliches VSS). Consigne owner : plus aucune "
    "manipulation VeraCrypt a la main. Le changement de cle se fera par rechiffrement SCRIPTE de "
    "l'en-tete, jamais par l'interface. Version graphique gelee dans l'historique git (35edce8c8).")


def cmd_rekey_preparer() -> int:
    """RETIRE le 2026-09-28 -- voie graphique (incident V:). Refuse, ne cree rien, le dit."""
    _log(_VOIE_GRAPHIQUE_RETIREE)
    return 1


def cmd_rekey_verifier() -> int:
    """RETIRE le 2026-09-28 -- voie graphique (incident V:). Refuse, ne monte rien, le dit."""
    _log(_VOIE_GRAPHIQUE_RETIREE)
    return 1


def cmd_rekey_finaliser() -> int:
    """Phase 3 (SYSTEM) : nouvelle cle au coffre reserve, copie du coffre machine RETIREE."""
    from nokido_agent.app import forge_machine_vault as mv

    if mv._sid_courant() != mv.RESERVE_COMPTE_SID:
        _log("ERREUR: SYSTEM requis (profil ps_clm) -- le coffre reserve se scelle sous SYSTEM.")
        return 1
    if _rekey_etat().get("phase") != "verifie":
        _log("ERREUR: nouvelle cle NON verifiee (--rekey-verifier d'abord) -- rien n'est range.")
        return 1
    b64 = base64.b64encode((REKEY_DIR / "nouveau.kf").read_bytes()).decode("ascii")
    if not mv.reserve_set(VAULT_KEY, b64):
        _log("ERREUR: ecriture au coffre reserve refusee -- dossier conserve.")
        return 1
    retire = mv.vault_delete(VAULT_KEY)
    _rekey_effacer()
    _log("OK: nouvelle cle au coffre reserve (tache de demarrage) ; copie du coffre machine "
         + ("RETIREE" if retire else "NON retiree (a verifier)") + " ; fichiers temporaires effaces.")
    return 0


def cmd_rekey_abandonner() -> int:
    """Efface une preparation SEULEMENT si l'ANCIENNE cle ouvre l'en-tete ACTUEL -- prouve HORS
    VeraCrypt, en lecture seule (2026-09-28) : plus de montage, plus besoin de demonter V:.
    NON ou ILLISIBLE = refus : ces fichiers sont peut-etre la seule cle du volume."""
    if not _is_admin():
        _log("ERREUR: console administrateur requise.")
        return 1
    ancien = REKEY_DIR / "ancien.kf"
    if not ancien.exists():
        _log("rien a abandonner.")
        return 0
    v = verdict_cle_entete(ancien.read_bytes())
    if v["principal"] != "OUVRE":
        _log(f"REFUS: l'ancienne cle ne s'est PAS prouvee sur l'en-tete actuel ({v['principal']}"
             + (f", {v['motif']}" if v["motif"] else "") + ") -- rien n'est efface.")
        return 1
    _rekey_effacer()
    _log("abandonne : l'ancienne cle ouvre l'en-tete actuel (verifie hors VeraCrypt) ; "
         "fichiers temporaires effaces.")
    return 0


def cmd_status() -> int:
    _log(f"OS                 : {sys.platform} | backend={BACKEND if (IS_LINUX and BACKEND=='luks') else 'veracrypt'}")
    _log(f"VeraCrypt/cryptsetup: {bool(_vc_main_bin()) or bool(shutil.which('cryptsetup'))}")
    _log(f"conteneur          : {CONTAINER} (existe={CONTAINER.exists()})")
    _log(f"montage {_mount_path()} : monté={_is_mounted()}")
    _log(f"keyfile vault      : {'présent' if _vault_get(VAULT_KEY) else 'ABSENT (--init-key)'}")
    for name in DB_FILES:
        p = RAG_DIR / name
        _log(f"  {name}: existe={p.exists()} symlink={p.is_symlink() if p.exists() else False}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="At-rest via conteneur chiffré (cross-OS, vitesse-préservée).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--init-key", action="store_true", help="Génère le keyfile au machine_vault")
    g.add_argument("--create", action="store_true")
    g.add_argument("--mount", action="store_true")
    g.add_argument("--unmount", action="store_true", help="Démonte (refuse si une base est ouverte)")
    g.add_argument("--expand", action="store_true",
                   help="Agrandit le conteneur via VeraCryptExpander (--size-gb, volume démonté, admin)")
    g.add_argument("--grow", action="store_true",
                   help="Agrandit par recréation + recopie (--size-gb) : seule voie 100%% CLI")
    g.add_argument("--migrate", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--install-boot", action="store_true", help="DÉPRÉCIÉ -> forge_install_boot_mount.py")
    g.add_argument("--verifier-cle", action="store_true",
                   help="La cle rangee ouvre-t-elle l'en-tete ACTUEL ? (lecture seule, sans montage)")
    g.add_argument("--rekey", action="store_true",
                   help="Change le fichier-cle SANS interface (SYSTEM) ; preuves seules sans --appliquer")
    g.add_argument("--rekey-restaurer", action="store_true",
                   help="Remet les en-tetes sauvegardes par --rekey et l'ancienne cle (SYSTEM)")
    g.add_argument("--rekey-clore", action="store_true",
                   help="Efface les sauvegardes d'un --rekey reussi (phase verifie + coffre reserve = nouvelle cle)")
    g.add_argument("--rekey-preparer", action="store_true",
                   help="RETIRE (voie graphique, incident du 2026-09-28)")
    g.add_argument("--rekey-verifier", action="store_true",
                   help="RETIRE (voie graphique, incident du 2026-09-28)")
    g.add_argument("--rekey-finaliser", action="store_true",
                   help="Phase 3 (SYSTEM) : coffre reserve, copie du coffre machine retiree")
    g.add_argument("--rekey-abandonner", action="store_true",
                   help="Seulement si l'ANCIENNE cle ouvre l'en-tete actuel (preuve hors VeraCrypt)")
    p.add_argument("--size-gb", type=int, default=16)
    p.add_argument("--appliquer", action="store_true", help="avec --rekey : ecrit vraiment")
    args = p.parse_args(argv)

    if args.verifier_cle:
        return cmd_verifier_cle()
    if args.rekey:
        return cmd_rekey(args.appliquer)
    if args.rekey_restaurer:
        return cmd_rekey_restaurer()
    if args.rekey_clore:
        return cmd_rekey_clore()
    if args.rekey_preparer:
        return cmd_rekey_preparer()
    if args.rekey_verifier:
        return cmd_rekey_verifier()
    if args.rekey_finaliser:
        return cmd_rekey_finaliser()
    if args.rekey_abandonner:
        return cmd_rekey_abandonner()

    if args.status:
        return cmd_status()
    if args.init_key:
        return cmd_init_key()
    if args.create:
        return cmd_create(args.size_gb)
    if args.mount:
        return cmd_mount()
    if args.unmount:
        return cmd_unmount()
    if args.expand:
        return cmd_expand(args.size_gb)
    if args.grow:
        return cmd_grow(args.size_gb)
    if args.migrate:
        return cmd_migrate()
    if args.verify:
        return cmd_verify()
    if args.install_boot:
        _log("DÉPRÉCIÉ. Utiliser : python tools/forge_install_boot_mount.py --install")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
