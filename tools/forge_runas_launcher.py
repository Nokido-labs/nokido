"""forge_runas_launcher.py — de-privilege + Job-Object launcher for the
Nokido supervisor `runAs` field.

The Deno supervisor (proxy_deno/core/supervisor.ts) spawns THIS wrapper for
any service whose ServiceDef carries one of :
  sandbox-online  — LaForgeSbxOnline low-priv user (loopback + outbound)
  sandbox-offline — LaForgeSbxOffline low-priv user (loopback only)
  interactive     — active console user session via WTSQueryUserToken
                    (GUI-needing services : Playwright Firefox, OAuth flow…)

In all three cases the wrapper :
  1. spawns the real command via the matching pywin32 helper,
  2. inside a Job Object with KILL_ON_JOB_CLOSE,
  3. waits on the child and exits with the child's exit code.

When the supervisor kills this wrapper (restart / shutdown), the wrapper
process exits, its job handle closes, and Windows kills the child too —
no orphans. The child inherits this wrapper's stdout/stderr, so the
supervisor's per-service log pipe keeps working unchanged.

The supervisor sets cwd + env on THIS process; both spawn helpers propagate
them to the child.

Usage (argv as the supervisor builds it):
  forge_runas_launcher.py <sandbox-online|sandbox-offline|interactive> \\
                          <cmd> [args...]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nokido_agent.app.forge_sandbox_exec import (
    SandboxError,
    spawn_as_interactive_jobbed,
    spawn_as_sandbox_jobbed,
)

_MODES = ("sandbox-online", "sandbox-offline", "interactive")

# --- SECRETS DU SUPERVISEUR : plus transmis (2026-09-28) ------------------------------------
#
# Decision owner : jeton court injecte par le superviseur. Mesure du jour : le superviseur
# (LocalSystem) porte le jeton maitre et le secret JWT dans son environnement NSSM, et ce
# lanceur les recopiait dans l'environnement du service lance sous un AUTRE compte. On
# retire, AVANT de lancer : les noms reserves du guichet, tout `FORGE_TOKEN_*`, les jetons du
# pont et du hub, la cle d'integrite, et tout jeton court HERITE. Un service lit ses secrets
# au guichet (`get_secret`) ; celui qui declare `NOKIDO_IDENTITE` (services.toml) recoit le
# jeton court de cette identite (`tools/forge_jeton_lanceur.py`, TPM d'abord) et le renouvelle
# par echange RFC 8693. Plan : C:/tmp/plan_jeton_court_lanceur_2026-09-28.md, etape D.
_JETONS_JAMAIS_TRANSMIS = frozenset({"FORGE_BRIDGE_TOKEN", "LAFORGE_HUB_TOKEN", "HUB_TOKEN",
                                     "NOKIDO_HMAC_KEY", "NOKIDO_JETON_COURT"})


def _a_retirer(nom: str, reserves: frozenset) -> bool:
    return nom in reserves or nom in _JETONS_JAMAIS_TRANSMIS or nom.startswith("FORGE_TOKEN_")


def _emettre_jeton(identite: str) -> tuple:
    """(code, jeton, chemin) par l'auxiliaire du lanceur -- charge par son chemin : ce
    lanceur tourne comme script, sans paquet `tools`."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "forge_jeton_lanceur", Path(__file__).resolve().parent / "forge_jeton_lanceur.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.emettre(identite)


# --- JETON PROJETE (2026-09-28) -------------------------------------------------------------
#
# Motif des jetons projetes de comptes de service Kubernetes. Mesure du jour : un service peu
# bavard laissait expirer son jeton injecte (il ne le renouvelait qu'en appelant le hub dans
# les 5 dernieres minutes du bail) et retombait sur le secret statique. Le LANCEUR, vivant
# tant que le service vit, renouvelle le jeton PAR TPM avant expiration et l'ecrit dans un
# fichier lisible par le SEUL compte du service ; le service le relit (`forge_agent_credential`).
RACINE_JETONS = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "NokidoJetons"
ENV_JETON_FICHIER = "NOKIDO_JETON_FICHIER"
_MARGE_PROJECTION_S = 600.0      # renouvelle quand il reste moins de 10 min
_PERIODE_VERIF_S = 60.0
_PROPRIETAIRES_SURS = ("S-1-5-18", "S-1-5-32-544")    # SYSTEM, Administrateurs
_PROJECTION: dict = {}           # identite, chemin, jeton -- pose par _preparer_environnement


def _proprietaire(chemin) -> str:
    try:
        import win32security

        sd = win32security.GetFileSecurity(str(chemin), win32security.OWNER_SECURITY_INFORMATION)
        return win32security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner())
    except Exception:  # noqa: BLE001 -- illisible : jamais « sur » par defaut
        return ""


def _racine_sure(racine) -> str:
    """'' si la racine des jetons projetes est sure, sinon le motif.

    Creee par l'OWNER, comme NokidoCles : ProgramData laisse tout compte creer un
    sous-dossier -- un compte bac a sable aurait pu la pre-creer a son profit."""
    racine = Path(racine)
    if not racine.is_dir():
        return f"{racine} absente (a creer par l'owner)"
    proprio = _proprietaire(racine)
    if proprio not in _PROPRIETAIRES_SURS:
        return f"proprietaire inattendu de {racine} ({proprio or 'ILLISIBLE'})"
    return ""


def _sid_du_processus(proc) -> str:
    """SID du COMPTE du processus lance, lu dans son jeton (le lanceur est SYSTEM). ''."""
    try:
        import win32security

        jeton = win32security.OpenProcessToken(proc, win32security.TOKEN_QUERY)
        sid, _attr = win32security.GetTokenInformation(jeton, win32security.TokenUser)
        return win32security.ConvertSidToStringSid(sid)
    except Exception:  # noqa: BLE001
        return ""


def _compte_du_service(proc, spawned: dict):
    """Compte a qui accorder la lecture du jeton projete : le SID reel lu dans le jeton du
    processus ; sinon un NOM de compte ; jamais une etiquette (`interactive-sid...`, rendue
    en mode interactive) -- pas de projection plutot qu'une ACL fausse."""
    sid = _sid_du_processus(proc)
    if sid:
        return "*" + sid
    nom = str((spawned or {}).get("sandbox_user") or "")
    return nom if nom and not nom.startswith(("interactive-", "current-user")) else None


def _preparer_dossier(dossier, compte) -> bool:
    """Dossier du service, DACL protegee : SYSTEM controle total, le compte du service en
    lecture, personne d'autre (heritage coupe)."""
    if not compte:
        return False
    Path(dossier).mkdir(parents=False, exist_ok=True)
    r = subprocess.run(["icacls", str(dossier), "/inheritance:r", "/grant:r",
                        "*S-1-5-18:(OI)(CI)F", f"{compte}:(OI)(CI)R"],
                       capture_output=True, text=True)
    return r.returncode == 0


def _ecrire_jeton(chemin, jeton: str) -> None:
    """Ecriture ATOMIQUE : le service ne lit jamais un fichier a moitie ecrit."""
    chemin = Path(chemin)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    provisoire.write_text(jeton, encoding="ascii")
    os.replace(provisoire, chemin)


def _boucle_projection(identite: str, chemin, jeton: str, vivant, attendre=None) -> None:
    """Tant que le service vit : renouvelle (TPM d'abord) quand il reste moins de 10 min.
    Un refus est DIT ; le jeton en place n'est jamais remplace par un vide."""
    import time

    from nokido_agent.app.forge_agent_credential import _reste_du_jeton

    attendre = attendre or time.sleep
    while vivant():
        if _reste_du_jeton(jeton) < _MARGE_PROJECTION_S:
            try:
                code, neuf, preuve = _emettre_jeton(identite)
            except Exception as exc:  # noqa: BLE001
                code, neuf, preuve = 4, "", f"auxiliaire en echec ({type(exc).__name__})"
            if code == 0 and neuf:
                _ecrire_jeton(chemin, neuf)
                jeton = neuf
                sys.stderr.write(f"[runas_launcher] jeton projete renouvele pour {identite} ({preuve})\n")
            else:
                sys.stderr.write(f"[runas_launcher] REFUS ({code}) du renouvellement projete pour "
                                 f"{identite} : {preuve}\n")
        attendre(_PERIODE_VERIF_S)


def _demarrer_projection(compte, vivant) -> str:
    """Apres le lancement : dossier restreint, jeton initial, fil de renouvellement."""
    if not _PROJECTION:
        return ""
    ident, chemin, jeton = _PROJECTION["identite"], _PROJECTION["chemin"], _PROJECTION["jeton"]
    if not _preparer_dossier(chemin.parent, compte):
        return f"jeton projete NON demarre pour {ident} : dossier non restreint (compte {compte or '?'})"
    _ecrire_jeton(chemin, jeton)
    import threading

    threading.Thread(target=_boucle_projection, args=(ident, chemin, jeton, vivant),
                     daemon=True, name="jeton-projete").start()
    return f"jeton projete demarre pour {ident}"


def _preparer_environnement(environ) -> str:
    """Retire les secrets herites ; injecte le jeton court de l'identite declaree.

    Rend un message pour stderr -- des NOMS et un chemin de preuve, jamais une valeur."""
    try:
        from nokido_agent.app.forge_secrets import NOMS_RESERVES
    except Exception:  # noqa: BLE001 -- guichet illisible : on retire quand meme ce qu'on sait
        NOMS_RESERVES = frozenset()
    retires = sorted(k for k in list(environ) if _a_retirer(k, NOMS_RESERVES))
    for k in retires:
        environ.pop(k, None)
    message = f"{len(retires)} secret(s) herite(s) retire(s)"
    identite = (environ.get("NOKIDO_IDENTITE") or "").strip().upper()
    if not identite:
        return message + " ; aucune identite declaree (NOKIDO_IDENTITE)"
    try:
        code, jeton, chemin = _emettre_jeton(identite)
    except Exception as exc:  # noqa: BLE001
        code, jeton, chemin = 4, "", f"auxiliaire en echec ({type(exc).__name__})"
    if code == 0 and jeton:
        environ["NOKIDO_IDENTITE"] = identite
        environ["NOKIDO_JETON_COURT"] = jeton
        _PROJECTION.clear()
        motif = _racine_sure(RACINE_JETONS)
        if motif:
            environ.pop(ENV_JETON_FICHIER, None)
            return message + f" ; jeton court injecte pour {identite} ({chemin}) ; PAS de projection : {motif}"
        fichier = RACINE_JETONS / f"{identite}-{os.getpid()}" / "jeton"
        environ[ENV_JETON_FICHIER] = str(fichier)
        _PROJECTION.update(identite=identite, chemin=fichier, jeton=jeton)
        return message + f" ; jeton court injecte pour {identite} ({chemin}) ; projection prevue"
    return message + f" ; REFUS ({code}) du jeton court pour {identite} : {chemin}"


def main() -> int:
    if len(sys.argv) < 3:
        sys.stderr.write(f"usage: forge_runas_launcher.py <{'|'.join(_MODES)}> <cmd> [args...]\n")
        return 2

    mode = sys.argv[1].strip().lower()
    if mode not in _MODES:
        sys.stderr.write(f"[runas_launcher] unknown runAs mode: {mode}\n")
        return 2
    command = subprocess.list2cmdline(sys.argv[2:])
    sys.stderr.write(f"[runas_launcher] {_preparer_environnement(os.environ)}\n")

    import win32event
    import win32process

    try:
        if mode == "interactive":
            spawned = spawn_as_interactive_jobbed(command, cwd=os.getcwd())
        else:
            online = mode == "sandbox-online"
            spawned = spawn_as_sandbox_jobbed(command, online=online)
    except SandboxError as exc:
        sys.stderr.write(f"[runas_launcher] {mode} spawn failed: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[runas_launcher] unexpected: {exc}\n")
        return 1

    job = spawned["_job"]  # keep referenced — closing it kills the child
    proc = spawned["_proc"]
    if _PROJECTION:
        _vivant = lambda: win32event.WaitForSingleObject(proc, 0) == win32event.WAIT_TIMEOUT  # noqa: E731
        sys.stderr.write(f"[runas_launcher] {_demarrer_projection(_compte_du_service(proc, spawned), _vivant)}\n")
    sys.stdout.write(
        f"[runas_launcher] {mode} pid={spawned['pid']} "
        f"user={spawned.get('sandbox_user', '?')} cmd={command[:160]}\n"
    )
    sys.stdout.flush()

    # Block until the child exits, then exit with its code. If the supervisor
    # kills THIS process instead, `job` is released -> the child is killed.
    win32event.WaitForSingleObject(proc, win32event.INFINITE)
    code = win32process.GetExitCodeProcess(proc)
    if _PROJECTION:
        # Le service est mort : son jeton projete ne doit pas lui survivre sur le disque.
        import shutil

        shutil.rmtree(_PROJECTION["chemin"].parent, ignore_errors=True)
    return int(code) if job else int(code)  # `job` ref kept alive until here


if __name__ == "__main__":
    sys.exit(main())
