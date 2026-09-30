"""forge_sandbox_exec.py -- execute a command as a low-privilege sandbox user.

The hub runs as SYSTEM, so `run`/`orchestrate` would otherwise execute
agent-generated code with SYSTEM rights. This module spawns that code under
a standard, non-admin sandbox account instead:

  LaForgeSbxOffline  -- loopback-only (outbound blocked by firewall)
  LaForgeSbxOnline   -- internet allowed

Provision the accounts with tools/forge_sandbox_setup.py first.
See docs/sandbox_user_plan.md.

The hub (SYSTEM) holds SeTcbPrivilege, so LogonUser + CreateProcessAsUser
let it spawn a child under the sandbox token without lowering its own
privilege. stdout/stderr are captured via inheritable file handles (no
pipe-handle juggling, no cmd.exe quote hell).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "sandbox" / "workspace"


def chemin_tmp_sandbox() -> str:
    """Chemin TEMP/TMP donne aux processus enfants — POINT UNIQUE de decision.

    POURQUOI UNE FONCTION pour une expression d'une ligne. Ce chemin etait
    calcule EN DUR sur DEUX sites (les deux poseurs d'environnement, plus bas).
    La regle du corps l'interdit : un etat partage par N chemins bascule par un
    INTERRUPTEUR lu a chaque appel, jamais site par site — sinon un site bascule
    seul et le systeme ecrit d'un cote pendant qu'il lit de l'autre. Meme patron
    que `forge_db_path.m2m_path()` + `sandbox/m2m.switch` (2026-09-06).

    LE DEFAUT NE CHANGE PAS : `<depot>/sandbox/workspace/tmp`, exactement comme
    avant. C'est un correctif de FORME, livrable sans fenetre de risque.

    ⚠️ AVANT DE POINTER AILLEURS (owner 2026-09-08, « les tmp devraient etre sur
    D:\\Temp ») — deux mesures a connaitre, sinon on casse :
      1. `forge_workspace_guard` compare des chemins RELATIFS A ROOT : un tmp
         HORS du depot est refuse (« ecriture hors zone agent ») pour tout
         `action=python`. Le code porte deja la cicatrice de ce piege ailleurs :
         « C:/tmp bloque par WORKSPACE_GUARD process-wide ». Deplacer suppose donc
         d'elargir la zone du garde — ce qui l'affaiblit, et se decide.
      2. D: avait 64,0 Go libres contre 140,6 Go pour C: le 2026-09-08 : deplacer
         chargerait le disque le MOINS libre, pour 0,55 Go de tmp mesures.

    Verrouille par tests/nr/test_tmp_point_unique_nr.py.
    """
    force = (os.environ.get("LAFORGE_SANDBOX_TMP") or "").strip()
    return force or str(WORKSPACE / "tmp")
CREDS_FILE = ROOT / "sandbox" / ".sandbox_creds"

USER_ONLINE = "LaForgeSbxOnline"
USER_OFFLINE = "LaForgeSbxOffline"
USER_TRUSTED = "LaForgeTrusted"  # dedicated account for git-tracked scripts

_CREATE_NO_WINDOW = 0x08000000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400

# Phase 23A (2026-05-24) hardening : critique Plan-securite a montre que
# le cache global indefini est un ticking bomb (memory dump hub = leak total
# creds DPAPI dechiffrees). Nouveau : TTL court + purge_creds_cache() apres
# chaque LogonUser. La penalite perf est ~10ms par spawn (DPAPI decrypt) vs
# leak permanent en RAM hub privilege.
import time as _time_purge

_creds_cache: dict | None = None
_creds_cache_ts: float = 0.0
_CREDS_CACHE_TTL_S: float = 30.0  # auto-expire si cache pas purge explicitement


class SandboxError(RuntimeError):
    """Raised when the sandbox cannot be used (missing creds, logon fail)."""


def _load_creds() -> dict:
    """Decrypt sandbox/.sandbox_creds (DPAPI, LocalMachine scope).
    Cache TTL 30s — purge auto + manuelle via purge_creds_cache()."""
    global _creds_cache, _creds_cache_ts
    if _creds_cache is not None and (_time_purge.time() - _creds_cache_ts) < _CREDS_CACHE_TTL_S:
        return _creds_cache
    if not CREDS_FILE.exists():
        raise SandboxError(f"{CREDS_FILE} missing -- run tools/forge_sandbox_setup.py")
    import win32crypt

    blob = CREDS_FILE.read_bytes()
    _desc, plain = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
    creds: dict = {}
    for line in plain.decode("utf-8").splitlines():
        if "=" in line:
            user, pwd = line.split("=", 1)
            creds[user.strip()] = pwd.strip()
    _creds_cache = creds
    _creds_cache_ts = _time_purge.time()
    return creds


def purge_creds_cache() -> None:
    """Best-effort zeroize + clear. A appeler APRES chaque LogonUser.
    Pas mlock vrai (Windows n'a pas mlock natif Python), mais limite la
    fenetre d'exfiltration via memory dump."""
    global _creds_cache, _creds_cache_ts
    if _creds_cache is not None:
        for k in list(_creds_cache.keys()):
            try:
                _creds_cache[k] = "\x00" * len(_creds_cache[k])
            except Exception:  # muet-ok : purge best-effort, la valeur est deja hors d'usage
                pass
            try:
                del _creds_cache[k]
            except Exception:  # muet-ok : la cle a pu disparaitre entre-temps
                pass
        _creds_cache = None
    _creds_cache_ts = 0.0


def sandbox_ready() -> tuple[bool, str]:
    """Cheap preflight: creds present and decryptable."""
    try:
        creds = _load_creds()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    missing = [u for u in (USER_ONLINE, USER_OFFLINE) if u not in creds]
    if missing:
        return False, f"no creds for {missing}"
    return True, "ok"


# ---- Sondes de diagnostic : exemption BORNEE du gate P1 (owner 2026-07-25) ----
# Binaires read-only dont le cout RAM/disque est negligeable. La decision se prend
# ICI, cote hub : un client ne se declare JAMAIS exempt lui-meme (l'alignement
# emane de LaForge). Fail-safe : au moindre doute -> pas d'exemption, le garde
# s'applique.
_PROBE_BINARIES = frozenset({
    "tasklist", "netstat", "ipconfig", "whoami", "hostname", "ver", "dir",
    "type", "findstr", "where", "tree", "sc", "nssm", "wsl", "docker", "git",
})
# Binaires dont SEULES certaines sous-commandes sont des sondes (`docker run` et
# `git clone` sont tout sauf legers). `git remote` est exclu : il imprime les URL
# avec le PAT (meme raison que le guard cote client).
_PROBE_SUBCMD = {
    "sc": {"query", "qc"},
    "nssm": {"status", "get"},
    "wsl": {"-l", "--list", "--status", "-v"},
    "docker": {"ps", "logs", "inspect", "version", "info", "images", "port", "top", "stats"},
    "git": {"status", "log", "diff", "rev-parse", "ls-files", "branch", "count-objects"},
}
# GESTES DE MENAGE (P1 owner 2026-07-27) : le garde jugeait toujours par la PRESSION
# et jamais par le POIDS. Mesure : cinq refus consecutifs sur 30 min pour un simple
# `del` de fichier — cout RAM nul, ~10 ms. Pire, ces gestes LIBERENT (disque, verrous,
# fichiers temporaires) : les refuser sous pression freine precisement ce qui soulage.
# Ce sont des mutations, donc PAS des sondes : classe distincte, budget distinct.
# Ce gate arbitre les RESSOURCES, pas les droits — videur, WorkspaceGuard et firewall
# restent seuls juges de ce qui a le droit d'etre supprime, et ils sont ailleurs. Hors
# pression ces commandes passaient deja : l'exemption n'ouvre aucun chemin nouveau.
_HOUSEKEEP_BINARIES = frozenset({"del", "erase", "rmdir", "rd", "move", "ren", "rename"})
_HOUSEKEEP_MAX_PER_MIN = 10  # un menage repete reste borne : jamais un canal de charge
_HOUSEKEEP_CALLS: list = []

_PROBE_TIMEOUT_CAP_S = 20
_PROBE_MAX_PER_MIN = 20      # anti-boucle : une sonde ne devient pas un canal de charge
_PROBE_RAM_HARD_PCT = 95.0   # au bord de l'OOM, meme une sonde attend son tour
_PROBE_CALLS: list = []


def _is_light_probe(command: str) -> bool:
    """True si TOUS les segments de `command` sont des sondes read-only legeres.

    Le test porte sur CHAQUE segment (`&`, `&&`, `|`, `||`) : sinon
    `tasklist & <job lourd>` passerait par la porte ouverte pour la sonde.
    Redirections et interpreteurs sont refuses d'emblee -- un shell ou un python
    peut tout faire, y compris devenir le glouton que le garde surveille.
    """
    if not command or len(command) > 400:
        return False
    low = command.strip().lower()
    for pref in ("cmd.exe /c ", "cmd /c "):
        if low.startswith(pref):
            low = low[len(pref):].strip()
            break
    if ">" in low or "<" in low:
        return False
    import re as _re

    seen = False
    for seg in _re.split(r"&&|\|\||[&|]", low):
        parts = seg.strip().split()
        if not parts:
            continue
        exe = parts[0].strip('"').replace("/", "\\").rsplit("\\", 1)[-1]
        if exe.endswith(".exe"):
            exe = exe[:-4]
        if exe not in _PROBE_BINARIES:
            return False
        allowed = _PROBE_SUBCMD.get(exe)
        if allowed is not None and (len(parts) < 2 or parts[1] not in allowed):
            return False
        seen = True
    return seen


def _is_housekeeping(command: str) -> bool:
    """True si TOUS les segments sont des gestes de menage a cout RAM nul.

    Meme discipline que `_is_light_probe` : chaque segment est verifie (sinon
    `del x & <job lourd>` passerait par la porte), et un interpreteur ou une
    redirection disqualifie d'emblee. `del` est atteignable via cmd.exe, qui est
    justement l'interpreteur que la sonde refuse : on tolere donc UNIQUEMENT le
    prefixe `cmd /c` ou `cmd.exe /c` en tete, et on juge ce qui suit.
    """
    if not command or len(command) > 400:
        return False
    low = command.strip().lower()
    for pref in ("cmd.exe /c ", "cmd /c "):
        if low.startswith(pref):
            low = low[len(pref):].strip()
            break
    if ">" in low or "<" in low:
        return False
    import re as _re

    seen = False
    for seg in _re.split(r"&&|\|\||[&|]", low):
        parts = seg.strip().split()
        if not parts:
            continue
        exe = parts[0].strip('"').replace("/", "\\").rsplit("\\", 1)[-1]
        if exe.endswith(".exe"):
            exe = exe[:-4]
        if exe not in _HOUSEKEEP_BINARIES:
            return False
        seen = True
    return seen


def _probe_exempt(command: str) -> bool:
    """Sonde legere ET budget disponible ET pas au bord de l'OOM -> exemption.

    Journalise CHAQUE exemption : une classe exemptee doit rester SURVEILLEE
    (une zone non-balayee est une dette, pas un privilege). Kill-switch :
    LAFORGE_P1_PROBE_EXEMPT=0.
    """
    import time as _t

    if os.environ.get("LAFORGE_P1_PROBE_EXEMPT", "1") == "0":
        return False
    _menage = False
    if not _is_light_probe(command):
        if not _is_housekeeping(command):
            return False
        _menage = True
    now = _t.time()
    if _menage:
        _HOUSEKEEP_CALLS[:] = [t for t in _HOUSEKEEP_CALLS if now - t < 60.0]
        if len(_HOUSEKEEP_CALLS) >= _HOUSEKEEP_MAX_PER_MIN:
            return False
    else:
        _PROBE_CALLS[:] = [t for t in _PROBE_CALLS if now - t < 60.0]
        if len(_PROBE_CALLS) >= _PROBE_MAX_PER_MIN:
            return False
    snap: dict = {}
    try:
        from nokido_agent.app.forge_resource_manager import get_snapshot

        snap = get_snapshot() or {}
        if float(snap.get("ram_pct") or 0.0) >= _PROBE_RAM_HARD_PCT:
            return False   # bord de l'OOM : plus personne ne passe, sonde comprise
    except Exception as _e:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger("Nokido.Sandbox").warning(
            "garde RAM AVEUGLE (%s) — le throttle ne s'applique pas", type(_e).__name__)
    _classe = "menage" if _menage else "sonde"
    _budget = _HOUSEKEEP_CALLS if _menage else _PROBE_CALLS
    _cap = _HOUSEKEEP_MAX_PER_MIN if _menage else _PROBE_MAX_PER_MIN
    _budget.append(now)
    print(f"[p1] {_classe} exempte (RAM {snap.get('ram_pct')}%, "
          f"{len(_budget)}/{_cap} par min): {command[:90]}", flush=True)
    try:
        from nokido_agent.app.forge_resource_manager import _audit_lifecycle

        _audit_lifecycle("probe_exempt", "gate",
                         "geste de menage a cout nul sous pression" if _menage
                         else "sonde read-only sous pression",
                         classe=_classe, cmd=command[:120], ram_pct=snap.get("ram_pct"))
    except Exception as _e:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger("Nokido.Sandbox").debug(
            "evenement de throttle non emis: %s", type(_e).__name__)
    return True


def spawn_as_sandbox(command: str, online: bool = False, timeout: int = 120, user: str | None = None,
                     env_extra: dict[str, str] | None = None) -> dict:
    """Run `command` as the sandbox user. Returns
    {ok, stdout, stderr, exit_code, timed_out, sandbox_user}.
    `user` overrides the online/offline pick (used by spawn_as_trusted).

    `env_extra` injecte des variables dans l'environnement de l'ENFANT. La
    frontiere de process ne transporte RIEN d'autre : un `git commit` lance ici
    doit pouvoir nommer l'agent que le hub a authentifie, sinon le hook
    post-commit ne voit que l'identite git du compte sandbox et la provenance
    est perdue (mesure 2026-09-03 : 219 notes `GIT:<user>|UNKNOWN`)."""
    # P1 homeostat-ressources (organ_audit 2026-07-05, go user 2026-07-07) :
    # gate RAM/CPU AVANT tout spawn sandbox — sous pression, refus propre
    # (l'appelant differe/retry) au lieu de spawner jusqu'a l'OOM. Fail-open :
    # la regulation ne casse jamais l'execution. Exemptions : user trusted
    # (reparations critiques) + kill-switch LAFORGE_P1_THROTTLE=0. Lit le
    # snapshot cache du sampler (daemon prime au boot hub), pas de sonde froide.
    #
    # EXEMPTION SONDE (owner 2026-07-25) : le garde jugeait par la PRESSION seule,
    # jamais par le POIDS -- sous RAM>85% il refusait `tasklist` (~30 Mo, <1 s)
    # exactement comme un job de 5 Go. Mesure du jour : 4 sondes refusees d'affilee
    # pendant qu'un llama-server orphelin de 5,59 Go tenait la RAM ; le corps perdait
    # sa PROPRIOCEPTION au moment precis ou il en avait le plus besoin, et le
    # diagnostic n'a ete possible que par les chemins in-process. Le garde reste BON,
    # c'est son DIAGNOSTIC qui etait faux : on le corrige, on ne le contourne pas.
    _probe = _probe_exempt(command) if user != USER_TRUSTED else False
    if _probe:
        timeout = min(max(1, int(timeout or _PROBE_TIMEOUT_CAP_S)), _PROBE_TIMEOUT_CAP_S)
    if user != USER_TRUSTED and not _probe and os.environ.get("LAFORGE_P1_THROTTLE", "1") != "0":
        try:
            from nokido_agent.app.forge_resource_manager import should_throttle

            # Ressources PURES (cortisol_threshold>1 + tdr off) : constate live
            # 2026-07-07, CORTISOL_FRUSTRATION est LATCHE chronique (organ_pulse
            # re-release 0.9 a chaque pulse sur embolies structurelles type
            # embed_backlog SKIP_TIER / daemons morts assumes) -> le consommer
            # ici = spawns geles en permanence. Le cortisol reste consomme par
            # l'orchestration_gate (escalade), sa place. TDR GPU sans rapport
            # avec un spawn cmd.exe.
            if should_throttle(cortisol_threshold=1.01, tdr_quarantine=False):
                # Nommer le glouton dans le refus. L'echelle d'eviction de
                # request_resources n'a que 3 leviers (ollama / llama-server /
                # docker) : face a un process python tiers elle tire a vide,
                # echoue, et l'appelant ne recoit qu'un "retry plus tard"
                # aveugle. Mesure 2026-07-16 : 6 tours perdus a diagnostiquer
                # searxng alors qu'un job python tenait 4.5 GB. Le snapshot est
                # deja en cache (sampler), donc ce diagnostic est gratuit.
                from nokido_agent.app.forge_resource_manager import get_snapshot

                snap = get_snapshot()
                top = ", ".join(
                    f"{p.get('name')}({p.get('ram_gb')}GB,pid={p.get('pid')})"
                    for p in (snap.get("top_procs") or [])[:3]
                )

                # P1 INTENT-AWARE (owner 2026-07-24) : avant de refuser, tenter de
                # FAIRE DE LA PLACE. Un refus sec sur un pic transitoire coute un
                # tour entier a l'appelant — mesure du jour : gate a 87.8% pendant
                # que le SSoT resource_state lisait 68.3%, le pic etant un churn de
                # chargement llama-server (4.82 -> 1.31 GB).
                #
                # Regulation COGNITIVE et non capacitive : on ne libere QUE si le
                # corps ne se sert pas de ces residents. get_active_intents() dit ce
                # qui est VIVANT (chains de veille, docker voulu) ; tant qu'une
                # cognition tourne, ses residents sont intouchables et on refuse
                # proprement plutot que de casser le flux.
                _evict = None
                _why_no_evict = ""
                if os.environ.get("LAFORGE_P1_EVICT", "1") != "0":
                    try:
                        from nokido_agent.app.forge_resource_manager import (
                            get_active_intents,
                            request_resources,
                        )

                        # Cible commune aux deux branches : repasser franchement sous
                        # le seuil, pas le raser (sinon le tour suivant re-throttle
                        # sur le meme pic).
                        _total = float(snap.get("ram_total_gb") or 0.0)
                        _target = round(_total * 0.18, 2) if _total else 4.0
                        _intents = get_active_intents()
                        if _intents.get("chains_active") or _intents.get("docker_wanted"):
                            # Le garde cognitif protege les ORGANES, pas les caches :
                            # endormir un service casse ses lecteurs, rendre un cache
                            # reconstructible ne casse rien. Mesure 2026-07-30 : ce
                            # garde faisait refuser des spawns a 86-90 % de RAM alors
                            # que 2.3 Go de cache dense attendaient d'etre rendus.
                            try:
                                from nokido_agent.app.forge_resource_manager import run_reclaimers

                                _rec = run_reclaimers(_target)
                            except Exception as e:  # noqa: BLE001
                                _rec = {"ok": False, "action": [
                                    f"reclaim indisponible ({type(e).__name__})"]}
                            _why_no_evict = (
                                f" | eviction refusee: cognition active "
                                f"(chains={_intents.get('chains_active')}, "
                                f"docker_wanted={_intents.get('docker_wanted')})"
                                f" | caches: {_rec.get('action')}"
                            )
                            if _rec.get("ok"):
                                _evict = {"ok": True, "action": _rec["action"],
                                          "before_free": snap.get("ram_free_gb"),
                                          "after_free": None}
                        else:
                            _evict = request_resources(_target, allow_evict=True)
                    except Exception:  # noqa: BLE001
                        _evict = None

                if _evict and _evict.get("ok") and _evict.get("action") != "noop":
                    # Place faite sur des residents IDLE : le spawn continue.
                    print(
                        f"[p1] eviction idle -> spawn autorise: {_evict.get('action')} "
                        f"(libre {_evict.get('before_free')} -> {_evict.get('after_free')} GB)",
                        flush=True,
                    )
                else:
                    if _evict and not _evict.get("ok"):
                        _why_no_evict = (
                            f" | eviction tentee sans succes ({_evict.get('action')}, "
                            f"manque {_evict.get('missing_gb')} GB)"
                        )
                        # QUI porte la pression (27/09) : `['noop']` seul ne disait pas
                        # que la memoire etait hors du corps, hors de portee de l'eviction.
                        if _evict.get("attribution"):
                            try:
                                from nokido_agent.app.forge_resource_manager import resume_attribution

                                _why_no_evict += " | " + resume_attribution(_evict["attribution"])
                            except Exception:  # noqa: BLE001 - muet-ok : le message reste celui d'avant
                                pass
                    return {
                        "ok": False,
                        "stdout": "",
                        "stderr": (
                            "THROTTLED: pression RAM/CPU (P1 homeostat) — spawn differe, "
                            f"retry plus tard. RAM {snap.get('ram_pct')}% "
                            f"(libre {snap.get('ram_free_gb')} GB) | top: {top}"
                            f"{_why_no_evict}"
                        ),
                        "exit_code": -9,
                        "timed_out": False,
                        "sandbox_user": user or (USER_ONLINE if online else USER_OFFLINE),
                        "throttled": True,
                        "top_procs": (snap.get("top_procs") or [])[:3],
                    }
        except Exception as _e:
            import logging as _lg
            _lg.getLogger("Nokido.Sandbox").warning(
                "throttle P1 INOPERANT (%s) — spawn autorise sans gate", type(_e).__name__)
    import win32api
    import win32con
    import win32event
    import win32file
    import win32process
    import win32profile
    import win32security

    user = user or (USER_ONLINE if online else USER_OFFLINE)
    pwd = _load_creds().get(user)
    if not pwd:
        raise SandboxError(f"no credentials for {user}")

    INTERNAL_LOGS = ROOT / "sandbox" / ".internal_logs"
    INTERNAL_LOGS.mkdir(parents=True, exist_ok=True)
    
    # Sécurisation du dossier parent (Audit 2026-06-15) : on s'assure que l'utilisateur
    # sandboxé n'a PAS de droit de création/suppression dans .internal_logs pour
    # prévenir tout TOCTOU via lien symbolique.
    rid = uuid.uuid4().hex[:16]
    out_f = INTERNAL_LOGS / f"_sbx_{rid}.out"
    err_f = INTERNAL_LOGS / f"_sbx_{rid}.err"

    # batch logon -- needs SeBatchLogonRight (granted by forge_sandbox_setup)
    try:
        token = win32security.LogonUser(
            user,
            ".",
            pwd,
            win32con.LOGON32_LOGON_BATCH,
            win32con.LOGON32_PROVIDER_DEFAULT,
        )
    except Exception as exc:  # noqa: BLE001
        raise SandboxError(f"LogonUser({user}) failed: {exc}") from None
    finally:
        # Phase 23A : zeroize pwd local + purge cache global apres LogonUser.
        # Token Win32 reste valide sans le pwd, donc clean now.
        try:
            pwd = "\x00" * len(pwd)  # type: ignore[assignment]
        except Exception as _e:
            import logging as _lg
            _lg.getLogger("Nokido.Sandbox").debug(
                "effacement du secret en memoire non confirme: %s", type(_e).__name__)
        purge_creds_cache()

    handles: list = [token]
    try:
        # The sandbox user has no profile -> its env lacks miniforge on PATH,
        # so python.exe fails with STATUS_DLL_NOT_FOUND. Build a usable env.
        try:
            env = dict(win32profile.CreateEnvironmentBlock(token, False) or {})
        except Exception:  # noqa: BLE001
            env = {}
        _mf = os.path.expanduser(r"~\miniforge3")
        _extra = ";".join(
            [
                _mf,
                _mf + r"\Library\bin",
                _mf + r"\Library\mingw-w64\bin",
                _mf + r"\Library\usr\bin",
                _mf + r"\Scripts",
                r"C:\Windows\System32",
                r"C:\Windows",
            ]
        )
        env["PATH"] = _extra + ";" + (env.get("PATH") or env.get("Path") or "")
        env.setdefault("SystemRoot", r"C:\Windows")
        env.setdefault("SYSTEMDRIVE", "C:")
        env.setdefault("SystemDrive", "C:")
        # Frontière de process : contextvars ne traverse pas -> on sérialise le
        # trace_id courant en env, get_trace_id() le relit côté enfant (fallback).
        try:
            from nokido_agent.app.forge_trace_context import get_trace_id

            env["LAFORGE_TRACE_ID"] = get_trace_id()
        except Exception as _e:
            import logging as _lg
            _lg.getLogger("Nokido.Sandbox").debug(
                "trace_id non propage a l'enfant: %s", type(_e).__name__)
        _tmp = chemin_tmp_sandbox()
        env["TEMP"] = _tmp
        env["TMP"] = _tmp
        # UTF-8 souverain : ce chemin ne recopie pas os.environ -> l'enfant herite
        # du profil du compte sandbox (Default), sans les vars UTF-8 du hub -> stdout
        # et open() par defaut en cp1252 crashent sur les non-ASCII (fleche, emoji).
        # On les force ici = fix definitif, plus besoin de sys.stdout.reconfigure.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # Provenance de l'appelant : elle n'existe que de CE cote de la frontiere.
        # Applique en DERNIER pour primer sur le profil du compte sandbox. Une
        # valeur vide est ignoree : mieux vaut l'absence de variable qu'une
        # identite vide, que le hook post-commit lirait comme une declaration.
        for _k, _v in (env_extra or {}).items():
            if _v:
                env[str(_k)] = str(_v)

        sa = win32security.SECURITY_ATTRIBUTES()
        sa.bInheritHandle = True
        # CREATE_NEW : atomique, échoue si un lien symbolique ou fichier existe déjà.
        # Prévient le détournement de handle par un attaquant sandboxé (TOCTOU).
        h_out = win32file.CreateFile(
            str(out_f), win32file.GENERIC_WRITE, win32file.FILE_SHARE_READ, sa, win32file.CREATE_NEW, 0, None
        )
        h_err = win32file.CreateFile(
            str(err_f), win32file.GENERIC_WRITE, win32file.FILE_SHARE_READ, sa, win32file.CREATE_NEW, 0, None
        )
        h_in = win32file.CreateFile(
            "NUL", win32file.GENERIC_READ, win32file.FILE_SHARE_READ, sa, win32file.OPEN_EXISTING, 0, None
        )
        handles += [h_out, h_err, h_in]

        si = win32process.STARTUPINFO()
        si.dwFlags = win32process.STARTF_USESTDHANDLES
        si.hStdInput = h_in
        si.hStdOutput = h_out
        si.hStdError = h_err

        h_proc, h_thread, _pid, _tid = win32process.CreateProcessAsUser(
            token,
            None,
            command,
            None,
            None,
            True,
            _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT,
            env,
            str(WORKSPACE),
            si,
        )
        handles += [h_proc, h_thread]

        rc = win32event.WaitForSingleObject(h_proc, max(1, timeout) * 1000)
        timed_out = rc == win32event.WAIT_TIMEOUT
        if timed_out:
            # Tuer l'ARBRE, pas juste le process direct. Un script qui a spawné
            # des enfants (ex: semgrep, py-spy) les laissait ORPHELINS au timeout
            # -> ils survivaient, tenaient ports/CPU, congestionnaient le hub
            # (incident 2026-06-03). psutil reape la descendance d'abord.
            try:
                import psutil
                _parent = psutil.Process(_pid)
                _tree = _parent.children(recursive=True) + [_parent]
                for _p in _tree:
                    try:
                        _p.kill()
                    except Exception:  # noqa: BLE001 — muet-ok : process deja mort
                        pass
                psutil.wait_procs(_tree, timeout=3)
            except Exception:  # noqa: BLE001 — muet-ok : l'attente est un confort, le kill a eu lieu
                pass
            win32process.TerminateProcess(h_proc, 1)
            win32event.WaitForSingleObject(h_proc, 3000)
        exit_code = win32process.GetExitCodeProcess(h_proc)
    finally:
        for h in handles:
            try:
                win32api.CloseHandle(h)
            except Exception:  # noqa: BLE001 — muet-ok : handle deja ferme
                pass

    out = out_f.read_text("utf-8", "replace") if out_f.exists() else ""
    err = err_f.read_text("utf-8", "replace") if err_f.exists() else ""
    for f in (out_f, err_f):
        try:
            f.unlink()
        except Exception:  # noqa: BLE001 — muet-ok : menage best-effort, le fichier temporaire survit au pire
            pass

    return {
        "ok": (exit_code == 0) and not timed_out,
        "stdout": out,
        "stderr": err,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "sandbox_user": user,
    }


def spawn_as_trusted(command: str, timeout: int = 120) -> dict:
    """Run `command` as the dedicated LaForgeTrusted account: write access to
    the repo + RAG db, may spawn subprocesses, NO Python audit hook. ONLY for
    git-tracked, reviewed scripts -- the trust gate (committed + clean vs HEAD)
    lives in forge_mcp_registry.handle_run (action=trusted_script). Never
    expose this to ad-hoc / agent-generated code."""
    return spawn_as_sandbox(command, timeout=timeout, user=USER_TRUSTED)


def trusted_ready() -> tuple[bool, str]:
    """Cheap preflight: LaForgeTrusted credentials present and decryptable."""
    try:
        creds = _load_creds()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if USER_TRUSTED not in creds:
        return False, f"no creds for {USER_TRUSTED} -- run forge_sandbox_setup.py"
    return True, "ok"


def spawn_as_sandbox_detached(command: str, out_file: str, err_file: str, online: bool = False) -> dict:
    """Launch `command` as the sandbox user DETACHED. Returns immediately with
    {ok, pid, sandbox_user}. The child outlives this process (no job-object
    kill on Windows) — for long jobs. stdout/stderr -> out_file/err_file."""
    import win32api
    import win32con
    import win32file
    import win32process
    import win32profile
    import win32security

    user = USER_ONLINE if online else USER_OFFLINE
    pwd = _load_creds().get(user)
    if not pwd:
        raise SandboxError(f"no credentials for {user}")
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    try:
        token = win32security.LogonUser(
            user,
            ".",
            pwd,
            win32con.LOGON32_LOGON_BATCH,
            win32con.LOGON32_PROVIDER_DEFAULT,
        )
    except Exception as exc:  # noqa: BLE001
        raise SandboxError(f"LogonUser({user}) failed: {exc}") from None

    handles: list = [token]
    try:
        try:
            env = dict(win32profile.CreateEnvironmentBlock(token, False) or {})
        except Exception:  # noqa: BLE001
            env = {}
        _mf = os.path.expanduser(r"~\miniforge3")
        _extra = ";".join(
            [
                _mf,
                _mf + r"\Library\bin",
                _mf + r"\Library\mingw-w64\bin",
                _mf + r"\Library\usr\bin",
                _mf + r"\Scripts",
                r"C:\Windows\System32",
                r"C:\Windows",
            ]
        )
        env["PATH"] = _extra + ";" + (env.get("PATH") or env.get("Path") or "")
        env.setdefault("SystemRoot", r"C:\Windows")
        env.setdefault("SYSTEMDRIVE", "C:")
        env.setdefault("SystemDrive", "C:")
        # Frontière de process : contextvars ne traverse pas -> on sérialise le
        # trace_id courant en env, get_trace_id() le relit côté enfant (fallback).
        try:
            from nokido_agent.app.forge_trace_context import get_trace_id

            env["LAFORGE_TRACE_ID"] = get_trace_id()
        except Exception as _e:
            import logging as _lg
            _lg.getLogger("Nokido.Sandbox").debug(
                "trace_id non propage a l'enfant: %s", type(_e).__name__)
        _tmp = chemin_tmp_sandbox()
        env["TEMP"] = _tmp
        env["TMP"] = _tmp
        # UTF-8 souverain : ce chemin ne recopie pas os.environ -> l'enfant herite
        # du profil du compte sandbox (Default), sans les vars UTF-8 du hub -> stdout
        # et open() par defaut en cp1252 crashent sur les non-ASCII (fleche, emoji).
        # On les force ici = fix definitif, plus besoin de sys.stdout.reconfigure.
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        sa = win32security.SECURITY_ATTRIBUTES()
        sa.bInheritHandle = True
        # CREATE_NEW : atomique, échoue si un lien symbolique ou fichier existe déjà.
        # Prévient le détournement de handle par un attaquant sandboxé (TOCTOU).
        h_out = win32file.CreateFile(
            str(out_file), win32file.GENERIC_WRITE, win32file.FILE_SHARE_READ, sa, win32file.CREATE_NEW, 0, None
        )
        h_err = win32file.CreateFile(
            str(err_file), win32file.GENERIC_WRITE, win32file.FILE_SHARE_READ, sa, win32file.CREATE_NEW, 0, None
        )
        h_in = win32file.CreateFile(
            "NUL", win32file.GENERIC_READ, win32file.FILE_SHARE_READ, sa, win32file.OPEN_EXISTING, 0, None
        )
        handles += [h_out, h_err, h_in]

        si = win32process.STARTUPINFO()
        si.dwFlags = win32process.STARTF_USESTDHANDLES
        si.hStdInput = h_in
        si.hStdOutput = h_out
        si.hStdError = h_err

        h_proc, h_thread, pid, _tid = win32process.CreateProcessAsUser(
            token,
            None,
            command,
            None,
            None,
            True,
            _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT,
            env,
            str(WORKSPACE),
            si,
        )
        handles += [h_proc, h_thread]
        # Return without waiting — the child runs on independently.
        return {"ok": True, "pid": int(pid), "sandbox_user": user}
    finally:
        for h in handles:
            try:
                win32api.CloseHandle(h)
            except Exception:  # noqa: BLE001 — muet-ok : handle deja ferme
                pass


def spawn_as_sandbox_jobbed(command: str, online: bool = False, cwd: str | None = None) -> dict:
    """Launch `command` as the sandbox user inside a Job Object with
    KILL_ON_JOB_CLOSE; return immediately.

    Returns {ok, pid, sandbox_user, _job, _proc}. The CALLER MUST keep the
    `_job` handle alive: when the last handle to the job object closes (the
    caller process exits or is killed), Windows terminates the child too.
    This is the de-privilege launcher for the supervisor `runAs` field — a
    supervisor restart/shutdown can never leave a sandboxed orphan, which
    spawn_as_sandbox_detached() above cannot guarantee.

    The child inherits this process's stdout/stderr (forced inheritable), so
    a supervisor that pipes the launcher's stdio gets the child output live.
    `cwd` defaults to this process's cwd. The child env = sandbox token env
    block + this process's os.environ (the supervisor passes service env
    straight through the launcher process).
    """
    import win32api
    import win32con
    import win32file
    import win32job
    import win32process
    import win32profile
    import win32security

    user = USER_ONLINE if online else USER_OFFLINE
    pwd = _load_creds().get(user)
    if not pwd:
        raise SandboxError(f"no credentials for {user}")
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    child_cwd = cwd or os.getcwd()

    # Job object: kill the child when the last handle to the job closes.
    job = win32job.CreateJobObject(None, "")
    _info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    _info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, _info)

    try:
        token = win32security.LogonUser(
            user,
            ".",
            pwd,
            win32con.LOGON32_LOGON_BATCH,
            win32con.LOGON32_PROVIDER_DEFAULT,
        )
    except Exception as exc:  # noqa: BLE001
        win32api.CloseHandle(job)
        raise SandboxError(f"LogonUser({user}) failed: {exc}") from None

    transient: list = [token]
    try:
        try:
            env = dict(win32profile.CreateEnvironmentBlock(token, False) or {})
        except Exception:  # noqa: BLE001
            env = {}
        # Sandbox user has no profile -> miniforge missing from PATH. Fold in
        # this process's env so the supervisor can pass service env through.
        _mf = os.path.expanduser(r"~\miniforge3")
        _extra = ";".join(
            [
                _mf,
                _mf + r"\Library\bin",
                _mf + r"\Library\mingw-w64\bin",
                _mf + r"\Library\usr\bin",
                _mf + r"\Scripts",
                r"C:\Windows\System32",
                r"C:\Windows",
            ]
        )
        for _k, _v in os.environ.items():
            if _v is not None:
                env[_k] = _v
        env["PATH"] = _extra + ";" + (env.get("PATH") or env.get("Path") or "")
        env.setdefault("SystemRoot", r"C:\Windows")
        env.setdefault("SYSTEMDRIVE", "C:")
        env.setdefault("SystemDrive", "C:")
        # Frontière de process : contextvars ne traverse pas -> on sérialise le
        # trace_id courant en env, get_trace_id() le relit côté enfant (fallback).
        try:
            from nokido_agent.app.forge_trace_context import get_trace_id

            env["LAFORGE_TRACE_ID"] = get_trace_id()
        except Exception as _e:
            import logging as _lg
            _lg.getLogger("Nokido.Sandbox").debug(
                "trace_id non propage a l'enfant: %s", type(_e).__name__)

        sa = win32security.SECURITY_ATTRIBUTES()
        sa.bInheritHandle = True
        h_in = win32file.CreateFile(
            "NUL", win32file.GENERIC_READ, win32file.FILE_SHARE_READ, sa, win32file.OPEN_EXISTING, 0, None
        )
        transient.append(h_in)

        # Child inherits the launcher's stdout/stderr (forced inheritable) so
        # the supervisor's per-service log pipe captures child output direct.
        def _std(std_id):
            try:
                h = win32api.GetStdHandle(std_id)
                if h:
                    win32api.SetHandleInformation(h, win32con.HANDLE_FLAG_INHERIT, win32con.HANDLE_FLAG_INHERIT)
                    return h
            except Exception:  # noqa: BLE001 — muet-ok : repli explicite sur h_in juste en dessous
                pass
            return h_in  # fallback: NUL — never None, child stdio always valid

        si = win32process.STARTUPINFO()
        si.dwFlags = win32process.STARTF_USESTDHANDLES
        si.hStdInput = h_in
        si.hStdOutput = _std(win32api.STD_OUTPUT_HANDLE)
        si.hStdError = _std(win32api.STD_ERROR_HANDLE)

        # CREATE_SUSPENDED: assign to the job before the child runs a single
        # instruction, so it can never escape the job.
        h_proc, h_thread, pid, _tid = win32process.CreateProcessAsUser(
            token,
            None,
            command,
            None,
            None,
            True,
            _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT | win32con.CREATE_SUSPENDED,
            env,
            child_cwd,
            si,
        )
        transient.append(h_thread)
        try:
            win32job.AssignProcessToJobObject(job, h_proc)
        except Exception as exc:  # noqa: BLE001
            win32process.TerminateProcess(h_proc, 1)
            win32api.CloseHandle(h_proc)
            win32api.CloseHandle(job)
            raise SandboxError(f"AssignProcessToJobObject failed: {exc}") from None
        win32process.ResumeThread(h_thread)
        return {
            "ok": True,
            "pid": int(pid),
            "sandbox_user": user,
            "_job": job,
            "_proc": h_proc,
        }
    finally:
        for h in transient:
            try:
                win32api.CloseHandle(h)
            except Exception:  # noqa: BLE001 — muet-ok : handle deja ferme
                pass


def fallback_same_session_allowed(sid_cible, sid_courant) -> bool:
    """Le repli `CreateProcess` du spawn interactif est-il legitime ?

    Il ne l'est que si CE processus vit deja dans la session visee : la, un
    CreateProcess ordinaire fait naitre l'enfant au bon endroit — c'est le cas
    du superviseur lance comme user, qui n'a pas SeTcbPrivilege. Depuis
    SYSTEM en session 0, le meme appel livrerait l'enfant en session 0.

    Mesure du 2026-09-10 : un `Runner.Listener.exe` s'est ainsi retrouve en
    session 0 sous SYSTEM a cote de celui de l'owner ; il a ecrit
    `C:\\laforge-runner\\_work\\nokido` sous SYSTEM, et le checkout suivant est
    mort en `fatal: detected dubious ownership`, avant le moindre test.

    Session inconnue = REFUS. Un identifiant illisible n'est pas une
    autorisation : UNKNOWN n'est pas OUI.
    """
    if sid_cible is None or sid_courant is None:
        return False
    try:
        return int(sid_cible) == int(sid_courant)
    except (TypeError, ValueError):
        return False


def spawn_as_interactive_jobbed(command: str, cwd: str | None = None) -> dict:
    """Launch `command` in the active console user session via
    WTSQueryUserToken. Returns {ok, pid, sandbox_user, _job, _proc}.

    For services that need a real desktop session (Playwright Firefox, OAuth
    browser flows). Without lpDesktop=winsta0\\default + a real user token,
    Firefox crashes with exitCode=0xC0000005 (ACCESS_VIOLATION) when spawned
    from Session 0 (Windows services / NSSM LocalSystem default).

    Caller process needs SeTcbPrivilege — granted to LocalSystem by default,
    so the LaForge-Master NSSM service satisfies this with no extra config.

    Same Job Object KILL_ON_JOB_CLOSE contract as spawn_as_sandbox_jobbed :
    the CALLER MUST keep `_job` alive; when its last handle closes, Windows
    kills the child too. Supervisor restart/shutdown → zero orphans.

    No credentials needed (WTSQueryUserToken returns a token for the currently
    logged-in console user without a password). If no user is logged in
    (WTSGetActiveConsoleSessionId == 0xFFFFFFFF) → SandboxError.
    """
    import win32api
    import win32con
    import win32file
    import win32job
    import win32process
    import win32profile
    import win32security
    import win32ts

    # 1. Active session id (try to find an active RDP/console session first, else default).
    sid = None
    try:
        for s in win32ts.WTSEnumerateSessions():
            if s.get("State") == 0:  # WTSActive
                sid = s.get("SessionId")
                break
    except Exception as _e:
        import logging as _lg
        _lg.getLogger("Nokido.Sandbox").debug(
            "enumeration des sessions ILLISIBLE (%s) — sid inconnu, pas absent",
            type(_e).__name__)
    if sid is None:
        sid = win32ts.WTSGetActiveConsoleSessionId()
    if sid == 0xFFFFFFFF or sid is None:
        raise SandboxError("no active console session — no user logged in to a desktop. Log in as user then retry.")

    # 2. Pull the user's PRIMARY access token via WTSQueryUserToken
    #    (per MSDN : "Retrieves the **primary** access token of the logged-on
    #    user"). No password. No duplication needed — already a primary token,
    #    directly usable for CreateProcessAsUser.
    #    Caller must have SeTcbPrivilege ; LocalSystem has it by default.
    try:
        primary = win32ts.WTSQueryUserToken(sid)
    except Exception as exc:  # noqa: BLE001
        # Fallback if caller lacks SeTcbPrivilege (e.g. running supervisor directly as user)
        # Spawn using standard CreateProcess (since we already run in user's user session)
        #
        # GARDE (2026-09-10) : ce repli ne vaut QUE depuis la session visee.
        # Sans lui, un appelant SYSTEM en session 0 degradait sans echouer et
        # livrait un enfant en session 0 — cf. fallback_same_session_allowed.
        try:
            sid_courant = win32ts.ProcessIdToSessionId(os.getpid())
        except Exception as _e:  # noqa: BLE001
            sid_courant = None  # illisible : on refuse, on ne devine pas
        if not fallback_same_session_allowed(sid, sid_courant):
            raise SandboxError(
                "WTSQueryUserToken(sid=%s) a echoue (%s) et le repli CreateProcess "
                "est REFUSE : ce processus vit en session %s. Un spawn d'ici "
                "livrerait l'enfant hors de la session visee. L'appelant doit "
                "detenir SeTcbPrivilege (LocalSystem), ou tourner deja dans la "
                "session %s."
                % (sid, exc,
                   sid_courant if sid_courant is not None else "INCONNUE", sid)
            ) from None
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.bInheritHandle = True
        h_in = win32file.CreateFile(
            "NUL", win32file.GENERIC_READ, win32file.FILE_SHARE_READ, sa, win32file.OPEN_EXISTING, 0, None
        )
        job = win32job.CreateJobObject(None, "")
        _info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        _info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, _info)
        
        def _std(std_id):
            try:
                h = win32api.GetStdHandle(std_id)
                if h:
                    win32api.SetHandleInformation(h, win32con.HANDLE_FLAG_INHERIT, win32con.HANDLE_FLAG_INHERIT)
                    return h
            except Exception:  # muet-ok : repli explicite sur h_in juste en dessous
                pass
            return h_in

        si = win32process.STARTUPINFO()
        si.dwFlags = win32process.STARTF_USESTDHANDLES
        si.hStdInput = h_in
        si.hStdOutput = _std(win32api.STD_OUTPUT_HANDLE)
        si.hStdError = _std(win32api.STD_ERROR_HANDLE)
        child_cwd = cwd or r"C:\tmp"
        if not os.path.exists(child_cwd):
            try:
                os.makedirs(child_cwd, exist_ok=True)
            except Exception as _e:
                import logging as _lg
                _lg.getLogger("Nokido.Sandbox").debug(
                    "cwd enfant non cree (%s) — le spawn echouera plus loin", type(_e).__name__)
        
        h_proc, h_thread, pid, _tid = win32process.CreateProcess(
            None,
            command,
            None,
            None,
            True,
            _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT | win32con.CREATE_SUSPENDED,
            None, # inherits env
            child_cwd,
            si,
        )
        try:
            win32job.AssignProcessToJobObject(job, h_proc)
        except Exception as exc2:
            win32process.TerminateProcess(h_proc, 1)
            win32api.CloseHandle(h_proc)
            win32api.CloseHandle(job)
            raise SandboxError(f"AssignProcessToJobObject failed: {exc2}") from None
        win32process.ResumeThread(h_thread)
        win32api.CloseHandle(h_thread)
        win32api.CloseHandle(h_in)
        return {
            "ok": True,
            "pid": int(pid),
            "sandbox_user": "current-user-fallback-sid%s" % sid_courant,
            "_job": job,
            "_proc": h_proc,
        }

    # 4. Job Object KILL_ON_JOB_CLOSE (same pattern as spawn_as_sandbox_jobbed).
    job = win32job.CreateJobObject(None, "")
    _info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    _info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, _info)

    child_cwd = cwd or r"C:\tmp"
    if not os.path.exists(child_cwd):
        try:
            os.makedirs(child_cwd, exist_ok=True)
        except Exception as _e:
            import logging as _lg
            _lg.getLogger("Nokido.Sandbox").debug(
                "cwd enfant non cree (%s) — le spawn echouera plus loin", type(_e).__name__)
    transient: list = [primary]
    try:
        # 5. User env block (the user has a real profile — PATH already sane).
        try:
            env = dict(win32profile.CreateEnvironmentBlock(primary, False) or {})
        except Exception:  # noqa: BLE001
            env = {}
        # Overlay select service-supplied env vars from supervisor's env,
        # WITHOUT clobbering user-session vars (USERPROFILE / TEMP / APPDATA
        # etc.) — those came from the SYSTEM context and would break the
        # child's filesystem & Python expectations (e.g. __pycache__ writes
        # to C:\Windows\TEMP fail under user token).
        # Allowlist : explicit prefixes used by Nokido services + Playwright
        # + Python runtime tuning.
        _ALLOW_PREFIXES = (
            "LAFORGE_",
            "FORGE_",
            "PLAYWRIGHT_",
            "PYTHON",
            "OLLAMA_",
            "MCP_",
            "NETCFG_",
        )
        for _k, _v in os.environ.items():
            if _v is None:
                continue
            if any(_k.startswith(p) for p in _ALLOW_PREFIXES):
                env[_k] = _v
        env.setdefault("SystemRoot", r"C:\Windows")
        env.setdefault("SYSTEMDRIVE", "C:")
        env.setdefault("SystemDrive", "C:")

        sa = win32security.SECURITY_ATTRIBUTES()
        sa.bInheritHandle = True
        h_in = win32file.CreateFile(
            "NUL", win32file.GENERIC_READ, win32file.FILE_SHARE_READ, sa, win32file.OPEN_EXISTING, 0, None
        )
        transient.append(h_in)

        # Child inherits launcher's stdout/stderr → supervisor log pipe intact.
        def _std(std_id):
            try:
                h = win32api.GetStdHandle(std_id)
                if h:
                    win32api.SetHandleInformation(h, win32con.HANDLE_FLAG_INHERIT, win32con.HANDLE_FLAG_INHERIT)
                    return h
            except Exception:  # noqa: BLE001 — muet-ok : repli explicite sur h_in juste en dessous
                pass
            return h_in

        si = win32process.STARTUPINFO()
        si.dwFlags = win32process.STARTF_USESTDHANDLES
        # CRITIQUE : sans lpDesktop interactif, le child voit Session 0
        # window station et Firefox refait crash 0xC0000005.
        si.lpDesktop = "winsta0\\default"
        si.hStdInput = h_in
        si.hStdOutput = _std(win32api.STD_OUTPUT_HANDLE)
        si.hStdError = _std(win32api.STD_ERROR_HANDLE)

        # CREATE_SUSPENDED + AssignProcessToJobObject avant Resume = pas d'évasion
        h_proc, h_thread, pid, _tid = win32process.CreateProcessAsUser(
            primary,
            None,
            command,
            None,
            None,
            True,
            _CREATE_NO_WINDOW | _CREATE_UNICODE_ENVIRONMENT | win32con.CREATE_SUSPENDED,
            env,
            child_cwd,
            si,
        )
        transient.append(h_thread)
        try:
            win32job.AssignProcessToJobObject(job, h_proc)
        except Exception as exc:  # noqa: BLE001
            win32process.TerminateProcess(h_proc, 1)
            win32api.CloseHandle(h_proc)
            win32api.CloseHandle(job)
            raise SandboxError(f"AssignProcessToJobObject failed: {exc}") from None
        win32process.ResumeThread(h_thread)
        return {
            "ok": True,
            "pid": int(pid),
            "sandbox_user": f"interactive-sid{sid}",
            "_job": job,
            "_proc": h_proc,
        }
    finally:
        for h in transient:
            try:
                win32api.CloseHandle(h)
            except Exception:  # noqa: BLE001 — muet-ok : handle deja ferme
                pass


# ── Phase 1b : exec dans la session console user (sandbox=console) ──────────
# RÉUTILISE spawn_as_interactive_jobbed (token user/Job KILL) + capture par
# redirection `> tmp 2>&1` CONTRÔLÉE PAR NOUS (la seule, car argv est garanti
# métachar-free par ConsolePolicy). Cf. roadmap_console_exec : 5e contexte
# d'exéc exposé via le hub. Durcissement TPM/secure-desktop/ledger-signé = Ph2.
import re as _re_console

_CONSOLE_TOKEN_RE = _re_console.compile(r"^[A-Za-z0-9_.:/\\=@+-]+$")  # zéro espace / métachar
_CONSOLE_DENY_EXE = {
    "cmd", "powershell", "pwsh", "wscript", "cscript", "bash", "sh",
    "reg", "net", "schtasks", "rundll32", "regsvr32", "mshta", "msiexec",
}  # NB: 'sc' retiré du hard-DENY -> _csafe_sc autorise lecture-seule (qc/query),
   # tout verbe write (config/create/delete/start/stop) reste PARK (refusé).
_CONSOLE_BLOCK_ARGS = {"-c", "-e", "-ec", "--exec", "/c", "/k",
                       "-command", "-encodedcommand", "-enc"}


def _csafe_gemini(a):
    return True  # egress = firewall (hors périmètre) ; interpréteur-escape déjà bloqué


def _csafe_docker(a):
    return bool(a) and a[0] in {
        "ps", "images", "info", "version", "inspect", "logs",
        "stats", "top", "port", "context", "system"}


def _csafe_git(a):
    if not a or a[0] not in {
            "status", "log", "diff", "branch", "remote", "show",
            "rev-parse", "describe", "tag"}:
        return False
    return "core.sshcommand" not in " ".join(a).lower() and "-c" not in a


def _csafe_wsl(a):
    return bool(a) and all(
        x in {"-l", "--list", "--status", "--version", "-v", "--running"} for x in a)


def _csafe_any(a):
    return True


def _csafe_sc(a):
    # sc : LECTURE SEULE uniquement (query/qc/...). Tout verbe write
    # (config/create/delete/start/stop/control/failure/sdset) -> PARK (refusé).
    # Forme distante (\\host en a[0]) -> pas un verbe RO -> PARK.
    _ro = {"query", "queryex", "qc", "qdescription", "qfailure",
           "qtriggerinfo", "qsidtype", "qprotection", "enumdepend",
           "sdshow", "showsid", "getdisplayname", "getkeyname"}
    return bool(a) and a[0].lower() in _ro


_CONSOLE_SAFE = {
    "gemini": _csafe_gemini,
    "docker": _csafe_docker,
    "git": _csafe_git,
    "wsl": _csafe_wsl,
    "where": _csafe_any,
    "tasklist": _csafe_any,
    "sc": _csafe_sc,
}


class ConsolePolicy:
    """Phase 1b — default-DENY. Décide ALLOW / PARK / DENY pour un argv splitté.
    DENY = dur (shell, charset). PARK = hors set-sûr → approbation humaine (non
    câblée en 1b → traité comme refus explicite par l'appelant). Cf. design v4."""

    @staticmethod
    def decide(argv: list) -> tuple:
        if not argv:
            return ("DENY", "argv vide")
        for t in argv:  # 1. charset strict tous tokens (anti-injection/métachar)
            if not _CONSOLE_TOKEN_RE.match(t):
                return ("DENY", f"token hors charset autorise: {t!r}")
        base = argv[0].lower().rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        for ext in (".exe", ".cmd", ".bat", ".com"):
            if base.endswith(ext):
                base = base[: -len(ext)]
        args = argv[1:]
        if base in _CONSOLE_DENY_EXE:  # 2. shells interdits (dur)
            return ("DENY", f"interpreteur/shell interdit: {base}")
        if any(x.lower() in _CONSOLE_BLOCK_ARGS for x in args):  # 3. interpréteur-escape
            return ("PARK", f"arg interpreteur ({base}) -> approbation humaine requise")
        pred = _CONSOLE_SAFE.get(base)  # 4. default-deny : set-sûr + prédicat args
        if pred is None:
            return ("PARK", f"exe hors set-sur: {base} -> approbation humaine requise")
        if not pred(args):
            return ("PARK", f"args non read-only pour {base} -> approbation requise")
        return ("ALLOW", "")


def console_exec(argv: list, timeout: float = 60.0, cwd: str | None = None) -> dict:
    """Exécute argv (DÉJÀ validé ConsolePolicy.decide()==ALLOW : charset strict,
    zéro métachar) dans la session console user, capture stdout+stderr.
    Réutilise spawn_as_interactive_jobbed + redirection `> tmp 2>&1` CONTRÔLÉE
    (la seule, argv étant métachar-free). Returns {ok, rc, stdout, timed_out,
    sandbox_user}. SeTcbPrivilege requis (hub LocalSystem) ; user loggé requis."""
    import win32api
    import win32event
    import win32process

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex[:12]
    out_f = WORKSPACE / f"_console_{rid}.out"
    cmd_str = "cmd /c " + " ".join(argv) + f' > "{out_f}" 2>&1'
    spawned = spawn_as_interactive_jobbed(cmd_str, cwd=cwd)
    job = spawned.get("_job")
    proc = spawned.get("_proc")
    timed_out = False
    rc = -1
    try:
        w = win32event.WaitForSingleObject(proc, max(1, int(timeout)) * 1000)
        timed_out = w == win32event.WAIT_TIMEOUT
        if not timed_out:
            rc = win32process.GetExitCodeProcess(proc)
    finally:
        try:
            win32api.CloseHandle(proc)
        except Exception:  # noqa: BLE001 — muet-ok : handle deja ferme ou process disparu
            pass
        try:
            win32api.CloseHandle(job)  # KILL_ON_JOB_CLOSE -> tue cmd+enfants au timeout
        except Exception:  # noqa: BLE001 — muet-ok : le job est deja ferme, ses enfants sont tues
            pass
    out = out_f.read_text("utf-8", "replace") if out_f.exists() else ""
    try:
        out_f.unlink()
    except Exception:  # noqa: BLE001 — muet-ok : menage best-effort, la sortie est deja lue
        pass
    return {
        "ok": (not timed_out and rc == 0),
        "rc": rc,
        "stdout": out,
        "timed_out": timed_out,
        "sandbox_user": spawned.get("sandbox_user"),
    }


if __name__ == "__main__":
    import json
    import sys

    ok, msg = sandbox_ready()
    print(f"sandbox_ready: {ok} ({msg})")
    if ok:
        for net in (False, True):
            r = spawn_as_sandbox("cmd.exe /c whoami && echo CWD=%CD%", online=net, timeout=20)
            print(f"\n--- spawn online={net} ---")
            print(json.dumps(r, indent=2, ensure_ascii=False))
        sys.exit(0)
    sys.exit(1)
