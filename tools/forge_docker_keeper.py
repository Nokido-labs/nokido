"""
forge_docker_keeper.py — Docker daemon keeper for Nokido supervisor.

Pattern keeper (cf services.toml ligne 501-504) : un wrapper Python qui
probe Docker daemon, garantit qu'il tourne, publie un heartbeat conforme
au schema Phase 3 (docs/heartbeat_schema.md). Sans ce keeper, le daemon
Docker = SPOF non-supervise pour ~13 modules consommateurs (Exegol,
SearXNG futur, clawhub, etc.) — RCA audit 2026-05-24.

Strategie :
  - Loop infini, tick = TICK_S (defaut 30s)
  - Chaque tick : `docker info` (timeout 5s)
    - OK   -> heartbeat health=ok + iter++
    - DOWN -> launch "Docker Desktop.exe", poll info jusqu'a BOOT_TIMEOUT_S,
              puis re-emit heartbeat. health=degraded pendant boot, crit
              si impossible a relancer.
  - Aucune dependance sur DockerSupervisor (decouple — keeper minimal).
  - Ne tue jamais Docker Desktop. Le supervisor envoie SIGTERM au keeper
    seulement, pas a Docker.

Lance depuis services.toml :
  [[service]] name = "NokidoDockerKeeper" wave = 1 cmd = "${PYTHON}"
  args = ["tools/forge_docker_keeper.py"]
  heartbeat = "sandbox/docker_keeper.heartbeat"
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logging.basicConfig(
    format="%(asctime)s [docker_keeper] %(levelname)s %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger("docker_keeper")


def _journal_fichier() -> None:
    """Double la sortie stdout vers un FICHIER — sinon ce keeper est MUET.

    Mesure 2026-09-05 : le superviseur ne capture PAS la sortie des services qu'il
    lance en SYSTEM (il journalise `started PID` / `exited code=1`, jamais la cause),
    et aucune des 7 afferences sous contrat de `forge_trace_spine` ne porte une
    sortie de service. Resultat : ce keeper est mort en boucle pendant 4 h sur un
    `ModuleNotFoundError` que PERSONNE ne pouvait lire, et il a fallu le relancer a
    la main en `run_job` pour lui voler son traceback.

    `RotatingFileHandler` et non `FileHandler` : la politique du depot l'impose
    (`forge_filehandler_migrator` — un log sans rotation a deja atteint le Go).
    Tout echec ici est AVALE volontairement : un keeper ne doit pas mourir de ne
    pas savoir ecrire son journal, mais il le DIT sur stdout.
    """
    try:
        from logging.handlers import RotatingFileHandler

        rep = Path(__file__).resolve().parent.parent / "logs" / "services"
        rep.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(rep / "docker_keeper.log", maxBytes=2_000_000,
                                 backupCount=3, encoding="utf-8", errors="replace")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [docker_keeper] %(levelname)s %(message)s"))
        logging.getLogger().addHandler(fh)
    except Exception as exc:  # noqa: BLE001
        print("[docker_keeper] journal fichier INDISPONIBLE (%s) : la sortie reste "
              "sur stdout, que le superviseur ne capture pas" % type(exc).__name__,
              flush=True)


_journal_fichier()

ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT_PATH = ROOT / "sandbox" / "docker_keeper.heartbeat"

DOCKER_DESKTOP_PATH = os.environ.get(
    "DOCKER_DESKTOP_PATH", r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
)
TICK_S = float(os.environ.get("DOCKER_KEEPER_TICK_S", "30"))
INFO_TIMEOUT_S = 5.0
BOOT_TIMEOUT_S = float(os.environ.get("DOCKER_KEEPER_BOOT_TIMEOUT_S", "90"))
BOOT_POLL_S = 3.0

# ── Délai de démarrage ADAPTATIF (owner 2026-07-24) ─────────────────────────
# Incident source (sawtooth du 23-07) : le keeper a tué un engine SAIN parce que
# son boot, lent sous RAM 88 %, dépassait un délai de 90 s calibré à 70 %. Un seuil
# fixe uniforme mesure des secondes, pas la CHARGE qui les explique.
#
# On ne régresse pas sur des données qu'on n'a pas : le keeper ENREGISTRE d'abord
# chaque boot réussi (durée + RAM au moment), et ne bascule sur la régression
# qu'au-delà de MIN_SAMPLES. En attendant, loi de repli monotone et bornée.
BOOT_TIMEOUT_MAX_S = float(os.environ.get("DOCKER_KEEPER_BOOT_TIMEOUT_MAX_S", "600"))
BOOT_SAMPLES_PATH = ROOT / "sandbox" / "docker_boot_samples.jsonl"
BOOT_SAMPLES_KEEP = 200
BOOT_MIN_SAMPLES = 5
BOOT_SAFETY_FACTOR = 1.8  # marge sur la durée PRÉDITE avant de déclarer mort


def _ram_pct_now() -> float:
    """RAM courante. On DEMANDE au propriétaire du capteur (SSoT du sampler) avant
    de sonder soi-même ; psutil en repli. 0.0 = inconnu -> pas d'adaptation."""
    try:
        import sys as _s

        _app = str(ROOT / "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_resource_manager import get_snapshot

        return float(get_snapshot().get("ram_pct") or 0.0)
    except Exception:  # noqa: BLE001
        try:
            import psutil

            return float(psutil.virtual_memory().percent)
        except Exception:  # noqa: BLE001
            return 0.0


def _load_boot_samples() -> list[tuple[float, float]]:
    """[(ram_pct, duration_s)] des boots réussis observés."""
    out: list[tuple[float, float]] = []
    try:
        if not BOOT_SAMPLES_PATH.exists():
            return out
        for line in BOOT_SAMPLES_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                r, s = float(d["ram_pct"]), float(d["duration_s"])
            except Exception:  # noqa: BLE001
                continue
            if r > 0 and s > 0:
                out.append((r, s))
    except Exception:  # noqa: BLE001
        pass
    return out[-BOOT_SAMPLES_KEEP:]


def _record_boot_sample(duration_s: float, ram_pct: float) -> None:
    """Trace un boot RÉUSSI. Sans cette collecte, la régression n'aurait jamais
    la moindre donnée et le délai resterait fixe en se croyant adaptatif."""
    if duration_s <= 0 or ram_pct <= 0:
        return
    try:
        BOOT_SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
        rows = _load_boot_samples()
        rows.append((float(ram_pct), float(duration_s)))
        rows = rows[-BOOT_SAMPLES_KEEP:]  # borné : pas de fichier qui enfle
        BOOT_SAMPLES_PATH.write_text(
            "\n".join(json.dumps({"ram_pct": r, "duration_s": s}) for r, s in rows) + "\n",
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[docker_keeper] echantillons de boot NON sauvegardes (%s: %s) | "
            "consequence: la duree de demarrage attendue restera calibree sur des "
            "mesures anciennes, et un boot qui s'allonge ne se verra pas",
            type(e).__name__, str(e)[:90])


def _boot_timeout_for_load() -> tuple[float, str]:
    """Délai de démarrage toléré, dérivé de la charge du moment.

    Retourne (secondes, explication) — l'explication part au heartbeat : un délai
    qui change sans dire pourquoi est indiagnosticable.
    """
    ram = _ram_pct_now()
    if ram <= 0:
        return BOOT_TIMEOUT_S, "ram inconnue -> base"

    samples = _load_boot_samples()
    if len(samples) >= BOOT_MIN_SAMPLES:
        # Moindres carrés : duration ~ a*ram + b (la pression mémoire allonge le boot).
        n = len(samples)
        sx = sum(r for r, _ in samples)
        sy = sum(s for _, s in samples)
        sxx = sum(r * r for r, _ in samples)
        sxy = sum(r * s for r, s in samples)
        denom = n * sxx - sx * sx
        if abs(denom) > 1e-9:
            a = (n * sxy - sx * sy) / denom
            b = (sy - a * sx) / n
            pred = a * ram + b
            if pred > 0:
                t = max(BOOT_TIMEOUT_S, min(BOOT_TIMEOUT_MAX_S, pred * BOOT_SAFETY_FACTOR))
                return t, f"regression n={n} ram={ram:.0f}% pred={pred:.0f}s -> {t:.0f}s"

    # Repli monotone tant que la population de mesures est trop maigre pour conclure.
    t = BOOT_TIMEOUT_S * (1.0 + 2.0 * max(0.0, ram - 70.0) / 30.0)
    t = max(BOOT_TIMEOUT_S, min(BOOT_TIMEOUT_MAX_S, t))
    return t, f"repli n={len(samples)}<{BOOT_MIN_SAMPLES} ram={ram:.0f}% -> {t:.0f}s"

_iter = 0
_consecutive_failures = 0
_last_launch_ts = 0.0
_LAUNCH_COOLDOWN_S = 120.0  # don't relaunch Docker Desktop more than 1x/2min

# Periode REFRACTAIRE du remede violent — MESURE 2026-07-26, correctif `fe9f323d`
# RESTAURE le 2026-08-14 : il avait ete emporte collateralement par `3aec1500`
# (« revert(docker): abandon pivot dockerd-WSL »), qui a annule plus que le pivot.
# Trois force-recycles se sont enchaines a 13:56:09, 13:58:24 et 14:00:35, et les
# trois boots ont REUSSI (echantillons: 11.7 s, 11.7 s, 6.5 s). Arithmetique du
# cycle : 3 ticks de 30 s sans reponse = 90 s -> STUCK_FAILS atteint -> taskkill /F
# + `wsl --shutdown` + relance -> ~12 s de boot -> et 90 s plus tard le meme
# raisonnement retire. Un daemon qu'on vient de tuer et relancer ne repond
# evidemment pas tout de suite : sans periode refractaire, le reflexe se declenche
# sur son PROPRE contrecoup (tetanie, pas panne). On garde le garde ARME, et on lui
# interdit de re-tirer tant qu'un boot REUSSI est recent.
_FORCE_RECYCLE_REFRACTORY_S = float(
    os.environ.get("DOCKER_KEEPER_FORCE_RECYCLE_REFRACTORY_S", "300")
)
# Conteneur mutable : mutation sans declaration `global` dans main().
_STATE = {"last_boot_ok_ts": 0.0, "last_release_ts": 0.0}

# GARDE ANTI-BOUCLE (2026-09-05, directive owner : « lancer Docker OUI, le faire
# BOUCLER NON »). Mesure du jour : la prothese a demarre PROPREMENT trois fois de
# suite — 12 s a chaque fois, `docker daemon recovered (29.7.2)` — puis est morte
# seule au bout de 10 min, 16 s, puis 31 s. Le keeper relancait a chaque mort, sans
# jamais remarquer que le motif se REPETAIT.
#
# Un cooldown ne suffit pas : il espace les relances, il ne les COMPTE pas. Or une
# prothese qui demarre bien et meurt vite n'est pas une prothese absente — c'est une
# prothese INSTABLE, et la relancer indefiniment ne fait que consommer la machine en
# masquant le probleme. Apres N vies courtes consecutives, on ARRETE et on le DIT :
# `health=instable`, avec les durees mesurees, pour que la cause soit instruite au
# lieu d'etre noyee. Une vie longue remet le compteur a zero.
_VIE_COURTE_S = float(os.environ.get("DOCKER_KEEPER_VIE_COURTE_S", "600"))
_VIES_COURTES_MAX = int(os.environ.get("DOCKER_KEEPER_VIES_COURTES_MAX", "3"))
_vies_courtes: list = []


def _noter_fin_de_vie() -> float | None:
    """Mesure la duree de la vie qui vient de s'achever et la classe.

    Rend la duree en secondes, ou None si aucun demarrage reussi n'est connu —
    trois etats, jamais deux : on ne compte pas comme « vie courte » ce qu'on n'a
    pas pu mesurer.
    """
    debut = _STATE.get("last_boot_ok_ts") or 0.0
    if debut <= 0.0:
        return None
    duree = time.monotonic() - debut
    _STATE["last_boot_ok_ts"] = 0.0          # une fin de vie ne se compte qu'une fois
    if duree < _VIE_COURTE_S:
        _vies_courtes.append(round(duree, 1))
    else:
        _vies_courtes.clear()                # une vie longue absout les precedentes
    return duree


def _boucle_detectee() -> bool:
    return len(_vies_courtes) >= _VIES_COURTES_MAX

# ── RELACHE (vasoconstriction) — mandat owner 2026-07-26, RESTAURE le 2026-08-14
# Supprimee par `3aec1500 revert(docker): abandon pivot dockerd-WSL` qui a
# deborde de son intention : la relache n'avait rien a voir avec le pivot WSL.
# Constat d'origine : `docker.wanted` expire depuis 5527 s, conteneurs vivants,
# 1,43 Go de process — Docker tournait 92 min SANS AUCUN DEMANDEUR. La
# conception on-demand etait a moitie faite : un drapeau a TTL, un keeper qui
# DEMARRE, et rien qui RELACHE.
#
# Ce n'est PAS un minuteur : le tick ne fait qu'EVALUER. Trois garde-fous
# decident, et le troisieme est le vrai :
#   1. GRACE >= TTL : jamais dans le dos d'un consommateur qui vient de finir.
#   2. REFRACTAIRE : 1800 s entre deux relaches (budget `medium` de
#      forge_regulation_loops), sinon on fabrique l'oscillation.
#   3. INTENTION avant capacite : `chains_active` interdit la relache, et sans
#      lecture d'intention on ne coupe PAS (fail-closed).
RELEASE_ENABLED = os.environ.get("DOCKER_KEEPER_RELEASE", "1") not in ("0", "false", "")
RELEASE_GRACE_S = float(os.environ.get("DOCKER_KEEPER_RELEASE_GRACE_S", "900"))
_RELEASE_REFRACTORY_S = float(os.environ.get("DOCKER_KEEPER_RELEASE_REFRACTORY_S", "1800"))
# On ne touche QUE nos conteneurs : un conteneur de l'owner ne nous appartient pas.
#
# ⚠️ CETTE LISTE SE DERIVE, ELLE NE S'ENUMERE PAS (mesure 2026-08-19).
# L'ancienne forme etait `(searxng|crawl4ai)` : deux noms figes dans une regex.
# Un recensement du depot montre que `exegol-laforge` est le conteneur LE PLUS
# cite (11 occurrences) et qu'il n'etait JAMAIS relache -- pas plus que
# `nokido-qdrant` ou `laforge-runner`. Docker pouvait donc tourner avec des
# conteneurs lourds vivants, sans aucun demandeur, precisement le defaut que la
# relache existe pour corriger. Un artefact statique qui pretend suivre un
# systeme vivant finit toujours par mentir : chaque conteneur ajoute depuis
# echappait en silence.
#
# On identifie desormais par CONVENTION DE NOM -- la marque `laforge`/`nokido`
# portee par le conteneur -- ce qui couvre aussi ceux qui n'existent pas encore.
# Les deux historiques sans suffixe restent admis, mais en nom EXACT : `^searxng`
# mordait sur n'importe quel `searxng-*` de l'owner, y compris le sien.
# Verifie sur 13 cas : nos 7 couverts, 6 tiers epargnes (postgres, redis,
# portainer, grafana, `searxng-de-lowner-a-lui`, `mon-searxng-perso`).
_OWN_CONTAINERS = re.compile(
    r"(?i)(?:(?:^|[-_])(?:laforge|nokido)(?:[-_]|$))"
    r"|(?:^(?:searxng|crawl4ai)$)")

# On-demand (RCA 2026-06-01) : par défaut MONITOR-ONLY — le keeper ne FORCE plus
# Docker au boot. Docker n'est lancé que si DOCKER_KEEPER_AUTOLAUNCH=1 (ancien
# comportement always-on) OU si un consommateur (Exegol/CTF) a signalé un besoin
# récent via ensure_docker() (flag frais). "Docker seulement si nécessaire."
AUTO_LAUNCH = os.environ.get("DOCKER_KEEPER_AUTOLAUNCH", "0") == "1"
WANT_FLAG = ROOT / "sandbox" / "docker.wanted"
WANT_TTL_S = float(os.environ.get("DOCKER_KEEPER_WANT_TTL_S", "900"))


def _docker_wanted() -> bool:
    """True si Docker est explicitement requis : autolaunch forcé OU un
    consommateur a posé un flag de demande récent (< WANT_TTL_S)."""
    if AUTO_LAUNCH:
        return True
    try:
        if WANT_FLAG.exists():
            return (time.time() - WANT_FLAG.stat().st_mtime) < WANT_TTL_S
    except OSError:
        pass
    # ON-DEMAND STRICT : Docker n'est "voulu" QUE si un consommateur (exegol/searxng/sandbox) a
    # posé docker.wanted, OU AUTO_LAUNCH. Process présent != voulu -> sinon respawn sans fin +
    # RAM gaspillée quand Docker n'est utile à personne (feedback user 2026-06-11). Un Docker
    # lancé à la main et figé : laissé tel quel (l'utilisateur le ferme), le keeper ne le force pas.
    return False


def _audit(action: str, reason: str = "", **extra) -> None:
    """Trace vers le journal d'audit Docker partage. Best-effort, jamais fatal.

    Sans ce journal, une extinction de Docker n'a pas d'auteur identifiable :
    l'enquete du 2026-07-22 a du eliminer quatre organes un par un. Son SILENCE
    vaut preuve : Docker qui meurt sans entree ici = acteur EXTERNE a Nokido.
    """
    try:
        import sys as _s
        from pathlib import Path as _P

        _app = str(_P(__file__).resolve().parent.parent / "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_docker_audit import record as _record

        _record(action, reason=reason, **extra)
    except Exception:  # noqa: BLE001 - le journal ne doit jamais casser le keeper
        pass


def ensure_docker() -> None:
    """API consommateurs (Exegol/CTF) : signale que Docker est requis maintenant.
    Pose/rafraîchit le flag ; le keeper lance Docker au prochain tick (<=30s).
    Non-bloquant, idempotent. Découplé (pas d'import du launcher côté appelant)."""
    _audit("want", "consommateur reclame Docker (pose docker.wanted)")
    try:
        WANT_FLAG.parent.mkdir(parents=True, exist_ok=True)
        WANT_FLAG.write_text(str(time.time()), encoding="utf-8")
    except OSError as exc:
        log.warning("ensure_docker: flag write failed: %s", exc)


def _docker_info_ok() -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=INFO_TIMEOUT_S,
        errors="replace")
        if r.returncode == 0:
            return True, (r.stdout or "").strip() or "unknown"
        return False, (r.stderr or r.stdout or "rc!=0").strip()[:200]
    except subprocess.TimeoutExpired:
        return False, "docker info timeout"
    except FileNotFoundError:
        return False, "docker CLI not in PATH"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# Ticks daemon-KO + process-up avant force-recycle (taskkill /F + wsl --shutdown).
# RESTAURE a 10 le 2026-08-14 : `3aec1500 revert(docker)` l'avait abaisse de 10 a
# 3 sans rapport avec son intention annoncee (abandon du pivot dockerd-WSL).
# A 3 ticks de 30 s, le garde tirait apres 90 s de non-reponse — alors que ce
# meme fichier accorde `BOOT_TIMEOUT_S=300` a un demarrage de Docker Desktop
# (60-90 s nominal). Le remede se declenchait donc PENDANT le boot normal et
# tuait un daemon sain, symptome vu cote owner : beaucoup de PID differents sur
# le process Docker. 10 ticks = 300 s, aligne sur le budget de boot.
STUCK_FAILS = int(os.environ.get("DOCKER_KEEPER_STUCK_FAILS", "10"))
_DOCKER_PROC_NAMES = ("Docker Desktop.exe", "com.docker.backend.exe", "com.docker.service", "dockerd.exe", "vpnkit.exe")


def _docker_ready() -> tuple[bool, str]:
    """Readiness RÉELLE = le socket/exec, pas juste le CLI. `docker ps` exige le named-pipe
    docker_engine vivant ; `docker info` peut répondre alors que le socket est STALE (Docker
    figé en 'starting' post-MAJ). C'est `ps` le vrai test de readiness."""
    try:
        r = subprocess.run(
            ["docker", "ps", "-q"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", timeout=INFO_TIMEOUT_S,
        )
        if r.returncode == 0:
            return True, "socket ok"
        return False, (r.stderr or "docker ps rc!=0").strip()[:200]
    except subprocess.TimeoutExpired:
        return False, "docker ps timeout (socket stale ?)"
    except FileNotFoundError:
        return False, "docker CLI not in PATH"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _docker_procs_present() -> bool:
    """Un process Docker tourne-t-il (Desktop/dockerd/backend) ? Si OUI mais daemon KO =
    'stuck starting' (figé) -> un re-Popen ne fait RIEN (l'instance hung est déjà là),
    il faut FORCE-RECYCLE (kill + wsl --shutdown + relaunch)."""
    if sys.platform != "win32":
        return False
    try:
        r = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], stdout=subprocess.PIPE, text=True, errors="replace", timeout=10)
        out = (r.stdout or "").lower()
        return any(n.lower() in out for n in _DOCKER_PROC_NAMES)
    except Exception:  # noqa: BLE001
        return False


def _force_recycle_docker() -> bool:
    """Débloque un Docker figé en 'starting' : kill TOUS les process Docker + wsl --shutdown
    (reset backend WSL2) + relance propre. Un simple re-Popen ne suffit pas si l'instance
    hung est encore présente (cf symptôme 'reste en starting / ne se coupe pas')."""
    log.warning("docker STUCK starting (process up, daemon KO) -> FORCE-RECYCLE (kill + wsl shutdown + relaunch)")
    _audit("kill", "force-recycle: process up mais daemon KO", procs=",".join(_DOCKER_PROC_NAMES))
    if sys.platform == "win32":
        for name in _DOCKER_PROC_NAMES:
            try:
                subprocess.run(["taskkill", "/F", "/IM", name, "/T"], timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(3)
    return _launch_docker_desktop()  # fait _wsl_shutdown() puis relance proprement


def _own_session_id() -> "int | None":
    """Session Windows du process keeper (0 = session services/NSSM)."""
    if sys.platform != "win32":
        return None
    import ctypes

    sid = ctypes.c_ulong()
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    if ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(sid)):
        return sid.value
    return None


def _active_console_session_id() -> "int | None":
    """Session console/RDP interactive active, ou None si aucun user loggé."""
    if sys.platform != "win32":
        return None
    try:
        import win32ts
        for s in win32ts.WTSEnumerateSessions():
            if s.get("State") == 0:  # WTSActive
                return s.get("SessionId")
        sid = win32ts.WTSGetActiveConsoleSessionId()
        if sid != 0xFFFFFFFF:
            return sid
    except Exception:
        import ctypes
        sid = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
        if sid != 0xFFFFFFFF:
            return sid
    return None


def _launch_in_user_session(session_id: int, exe_path: str, args: str = "") -> None:
    """CreateProcessAsUser dans la session console interactive.

    Requiert que le keeper tourne en SYSTEM (SeTcbPrivilege) — vrai sous NSSM.
    Une app GUI (Docker Desktop) DOIT tourner dans la session user, jamais en
    session 0 : lancée depuis session 0 le backend WSL2 démarre cassé et
    squatte le named pipe dockerBackendApiServer → Docker inutilisable en user.
    Cf. incident 2026-05-30. Lève OSError si une étape Win32 échoue.
    """
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)

    class STARTUPINFO(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    wts.WTSQueryUserToken.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    wts.WTSQueryUserToken.restype = wintypes.BOOL
    adv.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_int, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE),
    ]
    adv.DuplicateTokenEx.restype = wintypes.BOOL
    userenv.CreateEnvironmentBlock.argtypes = [
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.BOOL,
    ]
    userenv.CreateEnvironmentBlock.restype = wintypes.BOOL
    userenv.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]
    userenv.DestroyEnvironmentBlock.restype = wintypes.BOOL
    adv.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
        ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFO), ctypes.POINTER(PROCESS_INFORMATION),
    ]
    adv.CreateProcessAsUserW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL

    SecurityImpersonation = 2
    TokenPrimary = 1
    MAXIMUM_ALLOWED = 0x02000000
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    CREATE_NO_WINDOW = 0x08000000

    hToken = wintypes.HANDLE()
    if not wts.WTSQueryUserToken(wintypes.DWORD(session_id), ctypes.byref(hToken)):
        raise OSError(ctypes.get_last_error(), "WTSQueryUserToken")

    hDup = wintypes.HANDLE()
    env_ptr = ctypes.c_void_p()
    try:
        if not adv.DuplicateTokenEx(
            hToken, MAXIMUM_ALLOWED, None,
            SecurityImpersonation, TokenPrimary, ctypes.byref(hDup),
        ):
            raise OSError(ctypes.get_last_error(), "DuplicateTokenEx")

        if not userenv.CreateEnvironmentBlock(ctypes.byref(env_ptr), hDup, False):
            env_ptr = ctypes.c_void_p()  # env optionnel, on continue sans

        si = STARTUPINFO()
        si.cb = ctypes.sizeof(si)
        si.lpDesktop = "winsta0\\default"
        pi = PROCESS_INFORMATION()
        cmdline = ctypes.create_unicode_buffer((f'"{exe_path}" {args}').strip())
        flags = CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW

        ok = adv.CreateProcessAsUserW(
            hDup, exe_path, cmdline, None, None, False,
            flags, env_ptr, None, ctypes.byref(si), ctypes.byref(pi),
        )
        err = ctypes.get_last_error()
        if not ok:
            raise OSError(err, "CreateProcessAsUserW")
        k32.CloseHandle(pi.hProcess)
        k32.CloseHandle(pi.hThread)
    finally:
        if env_ptr:
            userenv.DestroyEnvironmentBlock(env_ptr)
        if hDup:
            k32.CloseHandle(hDup)
        k32.CloseHandle(hToken)


def _wsl_shutdown() -> None:
    """Coupe WSL AVANT de (re)lancer Docker Desktop. Post-MAJ Docker, l'intégration
    WSL (distro Debian) casse — proxy `execvpe ... Permission denied`, la distro
    interne docker-desktop n'a pas re-monté. Lancer Docker avec WSL coupé d'abord
    le ré-monte PROPREMENT (validé 2026-06-03, [[incident_docker_wsl_postupdate]]).
    Gate DOCKER_KEEPER_WSL_SHUTDOWN (def 1). Best-effort, ne bloque jamais le launch."""
    if os.environ.get("DOCKER_KEEPER_WSL_SHUTDOWN", "1") in ("0", "false", ""):
        return
    # FIX DURABLE 2026-06-16 : `wsl --shutdown` est SCOPÉ OWNER. Le keeper tourne en SYSTEM/restreint
    # -> un subprocess direct se prend E_ACCESSDENIED (mesuré) et le recycle reste impuissant (Docker
    # re-coince en 'starting'). On le lance dans la session console OWNER (même mécanisme WTS que le
    # launch Docker Desktop), avec fallback subprocess si pas de session owner / keeper déjà en user.
    if sys.platform == "win32":
        try:
            sid = _active_console_session_id()
            if sid is not None:
                wsl_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wsl.exe")
                _launch_in_user_session(sid, wsl_exe, "--shutdown")
                time.sleep(3)  # CreateProcessAsUser = async -> laisser wsl --shutdown finir
                log.info("wsl --shutdown via session OWNER (sid=%s) — fix ré-mount post-MAJ", sid)
                return
        except Exception as exc:  # noqa: BLE001
            log.warning("wsl --shutdown owner-session KO (%s) -> fallback subprocess", exc)
    try:
        subprocess.run(
            ["wsl", "--shutdown"], timeout=30,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        log.info("wsl --shutdown (subprocess fallback)")
    except Exception as exc:  # noqa: BLE001
        log.warning("wsl --shutdown échoué (on lance Docker quand même): %s", exc)


def _wsl_unmount() -> None:
    """Detache les disques montes par `wsl --mount` AVANT de relancer Docker.

    CAUSE RACINE du sawtooth, mesuree 22-07 puis RE-mesuree le 24-07 a 12:09:29Z :
    apres une mort brutale, `docker_data.vhdx` reste ATTACHE a WSL2
    (`WSL_E_USER_VHD_ALREADY_ATTACHED`, 0x80040312) ; chaque boot du backend
    echoue son mount et la boucle s'auto-entretient — meme Nokido arrete.

    Pourquoi une fonction distincte de `_wsl_shutdown` : le shutdown PURGEAIT bien
    ce verrou, mais il tue TOUT WSL, donc il decapitait un Docker sain en plein
    boot (doom-loop du 23-07) — d'ou son desarmement, qui a laisse le verrou sans
    remede. `--unmount` ne detache QUE les disques `--mount` : les distros restent
    intactes et un engine deja ready n'est pas touche. On garde donc le shutdown
    desarme ET on retrouve la purge.

    Gate DOCKER_KEEPER_WSL_UNMOUNT (def 1). Best-effort, ne bloque jamais le launch.
    """
    if os.environ.get("DOCKER_KEEPER_WSL_UNMOUNT", "1") in ("0", "false", ""):
        return
    # `wsl` est SCOPE OWNER : depuis SYSTEM un subprocess direct est sans effet sur
    # la session de l'utilisateur (mesure 2026-06-16). Meme mecanisme WTS que le launch.
    if sys.platform == "win32":
        try:
            sid = _active_console_session_id()
            if sid is not None:
                wsl_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                       "System32", "wsl.exe")
                _launch_in_user_session(sid, wsl_exe, "--unmount")
                time.sleep(2)  # CreateProcessAsUser est async
                log.info("wsl --unmount via session OWNER (sid=%s) — purge le verrou VHD", sid)
                return
        except Exception as exc:  # noqa: BLE001
            log.warning("wsl --unmount owner-session KO (%s) -> fallback subprocess", exc)
    try:
        subprocess.run(["wsl", "--unmount"], timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info("wsl --unmount (subprocess fallback)")
    except Exception as exc:  # noqa: BLE001
        log.warning("wsl --unmount echoue (on lance Docker quand meme): %s", exc)


def _launch_docker_desktop() -> bool:
    """Lance Docker Desktop dans la session user. Returns False si impossible.

    Docker Desktop = app GUI : interdit en session 0. Si le keeper tourne en
    session services (NSSM/supervisor), on spawne via WTS dans la session
    console interactive. Déjà en session user → Popen direct. Personne loggé
    → refus (Docker Windows ne démarre pas headless).
    """
    if not os.path.exists(DOCKER_DESKTOP_PATH):
        log.error("Docker Desktop introuvable: %s", DOCKER_DESKTOP_PATH)
        return False

    _audit("start", "keeper relance Docker Desktop")
    if sys.platform == "win32":
        _audit("wsl_shutdown", "pre-launch: re-monte l integration WSL")
        _wsl_unmount()   # purge le verrou VHD (ALREADY_ATTACHED) sans tuer WSL
        _wsl_shutdown()  # WSL propre avant launch -> ré-monte l'intégration (fix post-MAJ)
        own = _own_session_id()
        active = _active_console_session_id()
        if active is None:
            log.warning(
                "no active console session (no user logged in) — Docker "
                "Desktop ne peut pas démarrer headless, skip launch"
            )
            return False
        if own is not None and own != active:
            # keeper en session 0 (service) → spawn dans la session user
            try:
                _launch_in_user_session(active, DOCKER_DESKTOP_PATH)
                log.info("Docker Desktop launched into session %s (WTS)", active)
                return True
            except Exception as exc:
                log.error("WTS launch into session %s failed: %s", active, exc)
                return False
        # même session que l'user interactif → Popen direct (fast path)

    try:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [DOCKER_DESKTOP_PATH],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        log.info("Docker Desktop launch initiated (Popen, same session)")
        return True
    except Exception as exc:
        log.error("launch Docker Desktop failed: %s", exc)
        return False


def _wait_daemon(deadline_ts: float) -> tuple[bool, str]:
    while time.monotonic() < deadline_ts:
        ok, _ = _docker_ready()  # readiness RÉELLE = socket (docker ps), pas juste `docker info`
        if ok:
            iok, ver = _docker_info_ok()
            return True, ver if iok else "ready"
        time.sleep(BOOT_POLL_S)
    return False, "boot timeout"


def _code_identity() -> dict:
    """Identité du code RÉELLEMENT CHARGÉ (cf tools/forge_code_identity.py).

    Mesuré le 02/08 sur CE keeper : le pivot dockerd-WSL avait été reverté sur disque,
    mais le process vivant exécutait toujours l'ancien code et publiait `daemon_up: true`
    en sondant un daemon abandonné. Il ignorait donc `docker.wanted` et ne lançait pas
    Docker Desktop, sans qu'aucun champ ne trahisse le décalage.
    """
    try:
        from nokido_agent.tools.forge_code_identity import fields
        return fields(__file__)
    except Exception:  # muet-ok : diagnostic, jamais un SPOF pour le keeper
        return {}


def _write_heartbeat(health: str, stats: dict) -> None:
    # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il ajoute le `pid`.
    # Charge construite par `update` et non par deux `**` dans l'appel : un litteral
    # de dict tolere une clef en double, un appel leve `TypeError`.
    #
    # `app/` n'est PAS sur le sys.path de ce module. La SEULE insertion presente
    # (`_maybe_release`) est enfouie dans une branche RARE, jamais atteinte avant le
    # premier pouls : sans cette amorce le keeper mourait en `ModuleNotFoundError`
    # des le tick 1 (mesure 2026-09-05 : `exited code=1`, pouls fige 4 h pendant que
    # le superviseur le declarait `already_running`). Une dependance satisfaite
    # seulement sur un chemin d'exception n'est pas une dependance satisfaite.
    _app = str(Path(__file__).resolve().parent.parent / "app")
    if _app not in sys.path:
        sys.path.insert(0, _app)
    from nokido_agent.app.forge_heartbeat import beat_daemon

    charge = {"service": "NokidoDockerKeeper", "ts": time.time(), "iter": _iter,
              "health": health}
    charge.update(_code_identity())
    charge["stats"] = stats
    if not beat_daemon("docker_keeper", **charge):
        log.error("write heartbeat failed (beat_daemon)")


def _release_docker() -> dict:
    """Relache Docker : arret de NOS conteneurs, puis extinction du moteur.

    Aucune violence : `docker stop` puis `docker desktop stop`. Pas de taskkill —
    c'est le remede fort, reserve a un daemon FIGE. Si l'extinction du moteur
    echoue, on s'arrete apres les conteneurs et on le DIT (leur RAM est rendue).

    L'original coupait le moteur par `wsl -d Debian systemctl stop docker` :
    residu du pivot dockerd-WSL, abandonne par `3aec1500`. On garde la decision,
    pas le pivot — d'ou la voie Docker Desktop native, conforme a la docstring
    d'origine qui annoncait deja `docker desktop stop`.
    """
    out: dict = {"stopped": [], "engine": "intact"}
    try:
        r = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=15)
        names = [n.strip() for n in (r.stdout or "").splitlines() if n.strip()]
    except Exception as exc:  # noqa: BLE001
        return {"error": "docker ps: %s" % type(exc).__name__}
    mine = [n for n in names if _OWN_CONTAINERS.search(n)]
    foreign = [n for n in names if n not in mine]
    out["foreign_laisses"] = foreign
    for n in mine:
        try:
            subprocess.run(["docker", "stop", n], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=45)
            out["stopped"].append(n)
        except Exception as exc:  # noqa: BLE001
            out.setdefault("stop_failed", []).append("%s: %s" % (n, type(exc).__name__))
    if foreign:
        # Un conteneur qui n'est pas a nous interdit d'eteindre le moteur.
        out["engine"] = "intact (conteneurs tiers presents)"
        return out
    try:
        r = subprocess.run(["docker", "desktop", "stop"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
        out["engine"] = "stop demande (rc=%s)" % r.returncode
        if r.returncode != 0:
            out["engine_stderr"] = (r.stderr or "")[:120]
    except Exception as exc:  # noqa: BLE001
        out["engine"] = "indisponible: %s" % type(exc).__name__
    return out


def _maybe_release(now: float) -> dict | None:
    """Faut-il relacher ? Rend le detail si une relache a eu lieu, sinon None."""
    if not RELEASE_ENABLED:
        return None
    if _docker_wanted():
        return None
    if now - float(_STATE["last_release_ts"]) < _RELEASE_REFRACTORY_S:
        return None
    # Grace : un TTL entier APRES l'expiration de la demande.
    try:
        age = time.time() - WANT_FLAG.stat().st_mtime if WANT_FLAG.exists() else None
    except Exception:  # noqa: BLE001
        age = None
    if age is not None and age < (WANT_TTL_S + RELEASE_GRACE_S):
        return None
    # Intention avant capacite : une veille en cours interdit la relache.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_resource_manager import get_active_intents

        intents = get_active_intents()
        if intents.get("chains_active"):
            return None
    except Exception:  # noqa: BLE001
        return None            # fail-closed : sans lecture d'intention, on ne coupe pas
    detail = _release_docker()
    _STATE["last_release_ts"] = now
    _audit("release", "aucun demandeur depuis %s s (TTL %.0f + grace %.0f)"
           % (int(age) if age else "?", WANT_TTL_S, RELEASE_GRACE_S), **detail)
    log.info("relache Docker : %s", json.dumps(detail, default=str)[:200])
    return detail


def main() -> int:
    global _iter, _consecutive_failures, _last_launch_ts
    log.info("docker_keeper start tick=%.0fs heartbeat=%s", TICK_S, HEARTBEAT_PATH)
    # Initial probe
    _iter = 0
    while True:
        _iter += 1
        ok, info = _docker_ready()  # readiness = socket (docker ps), pas juste `docker info` (anti stale)
        if ok:
            _consecutive_failures = 0
            iok, ver = _docker_info_ok()
            # Docker tourne — quelqu'un le reclame-t-il encore ? La decision se
            # prend ICI, pas dans un minuteur : le tick ne fait qu'evaluer.
            relache = _maybe_release(time.monotonic())
            _write_heartbeat(
                "ok",
                {
                    "daemon_up": True,
                    "server_version": ver if iok else "ready",
                    "consecutive_failures": 0,
                    **({"released": relache} if relache else {}),
                },
            )
        else:
            _consecutive_failures += 1
            log.warning("docker info DOWN (#%d): %s", _consecutive_failures, info)
            health = "degraded"
            stats: dict = {
                "daemon_up": False,
                "error": info,
                "consecutive_failures": _consecutive_failures,
            }
            now = time.monotonic()
            if not _docker_wanted():
                # MONITOR-ONLY : personne ne demande Docker → ne pas le forcer.
                # Docker reste down par design (on-demand). health=idle.
                #
                # Un daemon eteint PAR DESIGN n'est pas un daemon en panne : on remet
                # le compteur a zero (correctif `43dbf555`, RESTAURE le 2026-08-14 —
                # meme revert que ci-dessus). Sans ce reset, _consecutive_failures
                # grimpait de 1 par tick pendant toute la pause on-demand — journal
                # keeper « docker info DOWN (#80) … (#100) » de 13:23 a 13:39 — et
                # depassait STUCK_FAILS=3 bien AVANT la premiere demande. Resultat :
                # au reveil, le keeper ne LANCAIT pas Docker, il le FORCE-RECYCLAIT
                # (taskkill /F + `wsl --shutdown`) sur un boot SAIN. Les deux
                # conteneurs (--restart unless-stopped) repartaient ensemble -> dent
                # de scie a ~135 s. Le garde reste arme : il ne compte plus que les
                # echecs survenus alors que Docker etait REELLEMENT reclame.
                _consecutive_failures = 0
                stats["consecutive_failures"] = 0
                stats["monitor_only"] = True
                _write_heartbeat("idle", stats)
                time.sleep(TICK_S)
                continue
            # Le daemon est DOWN alors qu'il etait reclame : une vie vient de
            # s'achever. On la MESURE avant toute relance — c'est elle qui distingue
            # une prothese absente d'une prothese instable.
            _duree_vie = _noter_fin_de_vie()
            if _duree_vie is not None:
                stats["derniere_vie_s"] = round(_duree_vie, 1)
            if _vies_courtes:
                stats["vies_courtes"] = list(_vies_courtes)
            if _boucle_detectee():
                # ARRET DELIBERE. Relancer une Nieme fois ne rendrait pas Docker plus
                # stable : cela consommerait la machine en masquant la cause. On cesse,
                # et on le DIT assez fort pour que ce soit instruit.
                stats["boucle_detectee"] = True
                stats["monitor_only"] = True
                log.error(
                    "BOUCLE DETECTEE : %d demarrages REUSSIS suivis d'une mort en "
                    "moins de %.0f s (durees: %s). Relance SUSPENDUE — la prothese "
                    "n'est pas absente, elle est INSTABLE, et la cause doit etre "
                    "instruite (journaux Docker : AppData/Local/Docker/log/host). "
                    "Reprise apres une vie longue ou un redemarrage du keeper.",
                    len(_vies_courtes), _VIE_COURTE_S, _vies_courtes)
                _audit("boucle", "relance suspendue apres %d vies courtes"
                       % len(_vies_courtes), durees=list(_vies_courtes))
                _write_heartbeat("instable", stats)
                time.sleep(TICK_S)
                continue
            if now - _last_launch_ts > _LAUNCH_COOLDOWN_S:
                _last_launch_ts = now
                # STUCK STARTING : process Docker présent MAIS daemon KO depuis >=STUCK_FAILS ticks
                # -> re-Popen inutile (l'instance figée reste) -> FORCE-RECYCLE (kill+wsl+relaunch).
                _since_ok = now - _STATE["last_boot_ok_ts"]
                _refractory = (
                    _STATE["last_boot_ok_ts"] > 0.0
                    and _since_ok < _FORCE_RECYCLE_REFRACTORY_S
                )
                if _refractory:
                    stats["force_recycle_refractory_s_left"] = round(
                        _FORCE_RECYCLE_REFRACTORY_S - _since_ok, 1
                    )
                if (
                    _docker_procs_present()
                    and _consecutive_failures >= STUCK_FAILS
                    and not _refractory
                ):
                    launched = _force_recycle_docker()
                    stats["force_recycle"] = launched
                else:
                    launched = _launch_docker_desktop()
                    stats["relaunch_attempted"] = launched
                if launched:
                    boot_budget, why = _boot_timeout_for_load()
                    ram_at_launch = _ram_pct_now()
                    stats["boot_timeout_s"] = round(boot_budget, 1)
                    stats["boot_timeout_why"] = why
                    log.info("budget de demarrage: %s", why)
                    t_launch = time.monotonic()
                    deadline = t_launch + boot_budget
                    woke, what = _wait_daemon(deadline)
                    stats["wake_ok"] = woke
                    stats["wake_info"] = what
                    if woke:
                        boot_dur = time.monotonic() - t_launch
                        stats["boot_duration_s"] = round(boot_dur, 1)
                        _record_boot_sample(boot_dur, ram_at_launch)
                        _STATE["last_boot_ok_ts"] = time.monotonic()
                        _consecutive_failures = 0
                        health = "ok"
                        stats["daemon_up"] = True
                        stats["server_version"] = what
                        log.info("docker daemon recovered (%s) en %.0fs", what, boot_dur)
                    else:
                        health = "crit"
                        log.error("docker daemon stayed down after launch: %s", what)
                else:
                    health = "crit"
                    stats["relaunch_attempted"] = False
            else:
                stats["relaunch_cooldown_s_left"] = round(
                    _LAUNCH_COOLDOWN_S - (now - _last_launch_ts), 1
                )
            _write_heartbeat(health, stats)
        time.sleep(TICK_S)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("docker_keeper SIGINT — exit")
        sys.exit(0)
