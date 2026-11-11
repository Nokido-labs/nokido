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

# Homologue biologique (owner 3/11, debat 1 tour 2, proposition Q3).
__FORGE_HOMOLOGUE__ = {
    "mecanisme": "autophagie (recyclage de ce qui ne sert plus)",
    "nature": "biologie",
    "termes": "autophagy lysosome clearance recycling organelle degradation",
    "sources": ["openstax:m46039"],
    "invariant": "une carcasse sans intention est coupee apres son delai de grace",
    "nr": "tests/nr/test_keeper_carcasse_sans_intention_nr.py",
}

ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT_PATH = ROOT / "sandbox" / "docker_keeper.heartbeat"
# 3/11 (debat 2 tour 2) : refractaire de l'effecteur de substrat PARTAGE entre le hub et le keeper (horloge MURALE).
_FICHIER_SUBSTRAT = ROOT / "sandbox" / "docker.substrat_release.json"

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
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_docker_keeper.py', 148, exc_info=True)
                continue
            if r > 0 and s > 0:
                out.append((r, s))
    except Exception:  # noqa: BLE001
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_docker_keeper.py', 152, exc_info=True)
    return out[-BOOT_SAMPLES_KEEP:]


def _record_boot_sample(duration_s: float, ram_pct: float) -> None:
    """Trace un boot RÉUSSI. Sans cette collecte, la régression n'aurait jamais
    la moindre donnée et le délai resterait fixe en se croyant adaptatif."""
    if duration_s <= 0 or ram_pct <= 0:
        return
    try:
        BOOT_SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 3/11 (bilan a 100) : chaque echantillon porte son `ts` (forge_timecode.stamp_row) ; les lignes
        # existantes sont recopiees TELLES QUELLES (un ancien echantillon n'est pas re-date apres coup).
        anciennes = []
        if BOOT_SAMPLES_PATH.exists():
            anciennes = [x.strip() for x in BOOT_SAMPLES_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
                         if x.strip()]
        try:
            from nokido_agent.app.forge_timecode import stamp_row as _stamp_row
        except ImportError:  # muet-ok : repli date locale ISO, la ligne reste datee
            def _stamp_row(d):
                return dict(d, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
        neuve = json.dumps(_stamp_row({"ram_pct": float(ram_pct), "duration_s": float(duration_s)}))
        rows = (anciennes + [neuve])[-BOOT_SAMPLES_KEEP:]  # borné : pas de fichier qui enfle
        BOOT_SAMPLES_PATH.write_text("\n".join(rows) + "\n", encoding="utf-8")
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


def _arret_volontaire_path() -> Path:
    return WANT_FLAG.with_name("docker.arret_volontaire")


def _marquer_arret_volontaire(motif: str) -> None:
    """Trace d'un arret VOULU (relache, fin de TTL), posee par TOUT processus qui coupe Docker : le keeper ne
    compte plus cet arret comme une mort precoce (10/11 soir : 3 relaches -> « relance suspendue »)."""
    try:
        _arret_volontaire_path().parent.mkdir(parents=True, exist_ok=True)
        _arret_volontaire_path().write_text("%s %s" % (time.time(), motif), encoding="utf-8")
    except OSError as exc:
        log.warning("trace d'arret volontaire non ecrite (%s) : l'arret pourra etre lu comme une mort", exc)


def _arret_volontaire_depuis(debut_wall: float) -> bool:
    try:
        return _arret_volontaire_path().stat().st_mtime >= debut_wall
    except OSError:  # muet-ok : pas de trace = arret non declare volontaire, contrat anterieur
        return False


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
    if duree < _VIE_COURTE_S and _arret_volontaire_depuis(time.time() - duree):
        return duree                         # arret VOULU apres un boot recent : pas une mort precoce
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
    if AUTO_LAUNCH or _crawl4ai_voulu():
        return True
    try:
        if WANT_FLAG.exists():
            return (time.time() - WANT_FLAG.stat().st_mtime) < WANT_TTL_S
    except OSError:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_docker_keeper.py', 331, exc_info=True)
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
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_docker_keeper.py', 357, exc_info=True)


# CRAWL4AI A LA DEMANDE (19/10, roadmap P2 crawl4ai) : son seul demarreur etait `restart: always`, qui le
# levait a CHAQUE reveil de Docker. L'outil de crawl pose crawl4ai.wanted ; le keeper `docker start` le
# conteneur EXISTANT (jamais de creation : un second conteneur volerait le port 11235).
CRAWL4AI_FLAG = ROOT / "sandbox" / "crawl4ai.wanted"
# Decision owner 19/10 : l'image de crawl4ai est EPINGLEE par empreinte -- digest note au premier demarrage,
# toute derive ensuite DITE (jamais adoptee en silence). Changer d'image = recreer le conteneur = installeur.
CRAWL4AI_EPINGLE = ROOT / "sandbox" / "crawl4ai_image_epinglee.json"
_CRAWL4AI_REFRACTAIRE_S = 300.0


def _crawl4ai_voulu() -> bool:
    try:
        return CRAWL4AI_FLAG.exists() and (time.time() - CRAWL4AI_FLAG.stat().st_mtime) < WANT_TTL_S
    except OSError:
        return False


def _docker_cli(args: list) -> tuple[int, str]:
    r = subprocess.run(["docker", *args], capture_output=True, text=True, errors="replace", timeout=30)
    return r.returncode, (r.stdout or "").strip()


def _politique_crawl4ai(nom: str) -> dict:
    """Decision owner 19/10 (« les trois ») : restart:no + memoire bornee + image epinglee, sur le conteneur EXISTANT.

    Constat qui l'autorise : 30 demarrages A LA DEMANDE au journal du 19/10 -- `restart: always` ne sert plus de
    reveil, il relancait crawl4ai a chaque reveil de Docker, meme sans besoin. `docker update` agit a chaud et ne
    recree rien ; un echec se DIT dans le detail sans masquer le demarrage."""
    mem = os.environ.get("NOKIDO_CRAWL4AI_MEM", "3g")
    rc, out = _docker_cli(["update", "--restart=no", "--memory=%s" % mem, "--memory-swap=%s" % mem, nom])
    detail = {"politique": "POSEE" if rc == 0 else "ECHEC"}
    if rc != 0:
        detail["politique_sortie"] = (out or "")[:120]
    rc, vu = _docker_cli(["inspect", "--format", "{{.Image}}", nom])
    vu = (vu or "").strip() if rc == 0 else ""
    if not vu:
        detail["image"] = "INCONNU"  # digest illisible : ni conforme ni derive
        return detail
    try:
        epingle = json.loads(CRAWL4AI_EPINGLE.read_text(encoding="utf-8")).get("digest")
    except (OSError, ValueError):
        epingle = None
    if epingle is None:
        try:
            CRAWL4AI_EPINGLE.write_text(json.dumps({"digest": vu, "conteneur": nom, "ts": time.time()}),
                                        encoding="utf-8")
            detail["image"] = "EPINGLEE"
        except OSError as e:
            detail["image"] = "EPINGLE_NON_ECRITE:%s" % type(e).__name__
    elif epingle != vu:
        detail.update(image="image_derive", image_epinglee=epingle, image_vue=vu)
    else:
        detail["image"] = "CONFORME"
    return detail


# Conteneur crawl4ai DE NOKIDO = labels compose (projet + service), jamais l'image : mesure 2026-11-10, apres la MAJ
# 0.9.4 le filtre `ancestor=unclecode/crawl4ai` (= :latest) a rendu sweb_dood13 (0.8.6, sans port) et le keeper l'a
# demarre. Meme projet que tools/forge_crawl4ai_jeton.py (-p).
CRAWL4AI_PROJET = os.environ.get("NOKIDO_CRAWL4AI_PROJET", "laforge")


def _demarrer_crawl4ai(now: float) -> dict | None:
    """Rend le detail d'un demarrage tente, None si rien a faire (pas de demande, ou refractaire)."""
    if not _crawl4ai_voulu():
        return None
    if now - float(_STATE.get("last_crawl4ai_start_ts", 0.0)) < _CRAWL4AI_REFRACTAIRE_S:
        return None
    _STATE["last_crawl4ai_start_ts"] = now
    try:
        rc, noms = _docker_cli(["ps", "-a", "--filter", "label=com.docker.compose.project=%s" % CRAWL4AI_PROJET,
                                "--filter", "label=com.docker.compose.service=crawl4ai", "--format", "{{.Names}}"])
        noms = [n for n in noms.splitlines() if n.strip()] if rc == 0 else []
        if not noms:
            detail = {"verdict": "ABSENT" if rc == 0 else "INCONNU", "motif": "aucun conteneur crawl4ai (installeur)"}
        else:
            rc, out = _docker_cli(["start", noms[0]])
            detail = {"verdict": "DEMARRE" if rc == 0 else "ECHEC", "conteneur": noms[0], "sortie": out[:120]}
            if rc == 0:
                detail.update(_politique_crawl4ai(noms[0]))
    except Exception as e:  # noqa: BLE001 - une sonde ratee est INCONNU, jamais un refus
        detail = {"verdict": "INCONNU", "motif": "%s: %s" % (type(e).__name__, str(e)[:120])}
    _audit("crawl4ai", "crawl4ai.wanted frais : demarrage a la demande", **detail)
    return detail


def _anonyme_path() -> Path:
    """Trace d'une demande ANONYME (ensure_docker direct, sans reclamation nommee) : sa fraicheur protege
    docker.wanted de la relache de la derniere reclamation nommee (10/11, NR test_docker_relache_respecte...)."""
    return WANT_FLAG.with_name("docker.wanted.anonyme")


def ensure_docker(anonyme: bool = True) -> None:
    """API consommateurs (Exegol/CTF) : signale que Docker est requis maintenant.
    Pose/rafraîchit le flag ; le keeper lance Docker au prochain tick (<=30s).
    Non-bloquant, idempotent. Découplé (pas d'import du launcher côté appelant).
    `anonyme=False` : appel interne de claim_docker (la reclamation nommee porte deja la demande)."""
    _audit("want", "consommateur reclame Docker (pose docker.wanted)")
    try:
        WANT_FLAG.parent.mkdir(parents=True, exist_ok=True)
        WANT_FLAG.write_text(str(time.time()), encoding="utf-8")
        if anonyme:
            _anonyme_path().write_text(str(time.time()), encoding="utf-8")
    except OSError as exc:
        log.warning("ensure_docker: flag write failed: %s", exc)


def _demande_anonyme_age() -> float | None:
    """Age (s) de la derniere demande anonyme ; None si aucune (ou illisible : la relache garde alors son contrat)."""
    try:
        return time.time() - _anonyme_path().stat().st_mtime
    except OSError:  # muet-ok : pas de trace = pas de demande anonyme a proteger
        return None


def _claims_path() -> Path:
    return WANT_FLAG.with_name("docker.claims.json")


def _lire_claims() -> list:
    try:
        d = json.loads(_claims_path().read_text(encoding="utf-8"))
        return [str(x) for x in d] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _ecrire_claims(claims: list) -> None:
    try:
        _claims_path().parent.mkdir(parents=True, exist_ok=True)
        _claims_path().write_text(json.dumps(sorted(set(claims))), encoding="utf-8")
    except OSError as exc:
        log.warning("claims write failed: %s", exc)


def claim_docker(owner: str) -> None:
    """Une chaine reclame Docker EN SON NOM : compteur de reclamations + docker.wanted."""
    _ecrire_claims(_lire_claims() + [str(owner)])
    _annuler_release_at("reclamation de %s" % owner)
    ensure_docker(anonyme=False)


# ── DELAI DE GRACE avant l'arret (GO owner 28/10) ───────────────────────────
# On DIFFERE l'extinction, on ne la desarme jamais (CLAUDE.md 6.ter §5 : Docker est dynamique).
_GRACE_DEFAUT_S = 180.0
_GRACE_PAR_INTENTION_S = 120.0
_GENE_MAX_S = 30.0


def _release_at_path() -> Path:
    return WANT_FLAG.with_name("docker.release_at")


def delai_de_grace(intentions, palier) -> float:
    """Pure. Secondes a attendre avant d'arreter Docker.

    base LAFORGE_DOCKER_GRACE_S (180) + 120 s par intention en attente, plafond = TTL de docker.wanted ;
    RALENTISSEMENT x0.5, GENE 30 s max, DETRESSE/CRITIQUE 0. Palier illisible (ILLISIBLE/INCONNU/None) :
    base SANS extension -- UNKNOWN != NO, donc ni 0 ni calme etendu. Intentions None : idem, pas d'extension."""
    try:
        base = float(os.environ.get("LAFORGE_DOCKER_GRACE_S", _GRACE_DEFAUT_S))
        if base < 0:
            base = _GRACE_DEFAUT_S
    except ValueError:
        base = _GRACE_DEFAUT_S
    if palier in ("DETRESSE", "CRITIQUE"):
        return 0.0
    if palier not in ("CALME", "RALENTISSEMENT", "GENE"):
        return base
    n = intentions if isinstance(intentions, int) and not isinstance(intentions, bool) and intentions > 0 else 0
    d = min(base + _GRACE_PAR_INTENTION_S * n, max(WANT_TTL_S, base))
    if palier == "RALENTISSEMENT":
        return d * 0.5
    if palier == "GENE":
        return min(d, _GENE_MAX_S)
    return d


def palier_courant() -> str:
    """Palier de pression RAM du moment, par la fonction du proprietaire (`palier_pression_ram`, meme entree que
    le tick Hamilton : plancher 60 s sinon instant, memoire libre). Illisible -> "ILLISIBLE", jamais CALME."""
    try:
        _app = str(ROOT / "app")
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app.forge_resource_manager import get_snapshot, palier_pression_ram

        snap = get_snapshot()
        ram = snap.get("ram_pct_plancher_60s", snap.get("ram_pct"))
        return palier_pression_ram(ram, float(snap.get("ram_free_gb") or 0.0))
    except Exception as exc:  # noqa: BLE001 - dit ci-dessous : ILLISIBLE != CALME
        log.warning("palier_courant ILLISIBLE (%s)", type(exc).__name__)
        return "ILLISIBLE"


# Une chaine de veille reclamera Docker tant qu'elle n'a pas depasse son etape `crawl` (search = SearXNG,
# crawl = crawl4ai). `agent_chain_nodes` n'a AUCUN index (status/chain_id) : l'interroger serait un SCAN de
# table ; on lit donc `watch_jobs` (index idx_watch_status(status, step)), dont `step` = etape courante.
_ETAPES_DOCKER = ("keywords", "search", "refine", "crawl")
_STATUTS_ACTIFS = ("pending", "running", "en_cours")
_REQUETES_INTENTIONS = [(
    "SELECT COUNT(*) FROM watch_jobs WHERE status IN (?,?,?) AND step IN (?,?,?,?)",
    _STATUTS_ACTIFS + _ETAPES_DOCKER,
)]


def intentions_docker_en_attente(db=None) -> "int | None":
    """Nombre de chaines/jobs de veille qui reclameront encore Docker. Lecture seule, par index.
    Base illisible -> None (UNKNOWN != 0)."""
    import sqlite3

    try:
        if db is None:
            _app = str(ROOT / "app")
            if _app not in sys.path:
                sys.path.insert(0, _app)
            from nokido_agent.app.forge_db_path import db_path

            db = db_path()
        conn = sqlite3.connect("file:%s?mode=ro" % Path(db).as_posix(), uri=True, timeout=2.0)
        try:
            return int(sum(conn.execute(sql, args).fetchone()[0] for sql, args in _REQUETES_INTENTIONS))
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - dit : None remonte, jamais 0
        log.warning("intentions_docker_en_attente ILLISIBLE (%s)", type(exc).__name__)
        return None


def _annuler_release_at(raison: str) -> None:
    p = _release_at_path()
    try:
        existait = p.exists()
        if existait:
            p.unlink()
    except OSError as exc:
        log.warning("release_at non retire: %s", exc)
        return
    if existait:
        _audit("release_annule", "arret differe annule : %s" % raison)


def _arreter_apres_grace(motif: str) -> dict:
    _audit("release", motif)
    return _release_docker()


def _tick_release_at(now: float) -> "dict | None":
    """Tick du keeper : arrete Docker si l'echeance de grace est atteinte et qu'aucune reclamation n'est revenue.
    Le delai est REEVALUE avec le palier et les intentions du moment (une degradation avance l'arret, jamais
    ne le recule au-dela de l'echeance posee)."""
    p = _release_at_path()
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        debut, echeance = float(d["debut"]), float(d["echeance"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _audit("release_at_illisible", "docker.release_at illisible (%s) : aucun arret decide ce tick "
               "(la relache de secours TTL+grace reste armee)" % type(exc).__name__)
        return None
    if _lire_claims():
        _annuler_release_at("une reclamation est revenue")
        return None
    # 2/11 : intention AVANT capacite, comme _maybe_release. Une veille ne reclame Docker qu'a sa RECHERCHE : sans ce
    # garde, la premiere veille finie rendait sa reclamation et Docker etait coupe sous les autres (19:34, 19:41 --
    # SearXNG absent, crawl4ai 10061, Rau non ingere). Lecture illisible = on ne coupe pas (fail-closed).
    # NR : tests/nr/test_keeper_release_at_respecte_chaines_nr.py
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_resource_manager import get_active_intents

        if _retient_docker(get_active_intents()):   # 4/11 : par etape (search/crawl), plus toute chaine
            return None
    except Exception:  # noqa: BLE001
        return None
    palier = palier_courant()
    n = intentions_docker_en_attente()
    due = min(echeance, debut + delai_de_grace(n, palier))
    if now < due:
        return None
    try:
        p.unlink()
    except OSError as exc:
        log.warning("release_at non retire: %s", exc)
    return _arreter_apres_grace("echeance de grace atteinte (delai pose %.0f s, palier %s, intentions %s)"
                                % (float(d.get("delai", 0)), palier, n))


def release_claim(owner: str, immediat: bool = False) -> dict:
    """Une chaine terminee relache SA reclamation. Idempotent. La derniere retire
    docker.wanted puis DIFFERE l'arret de `delai_de_grace(intentions, palier)` secondes
    (docker.release_at) ; delai 0 = arret immediat. Une autre reclamation encore
    active interdit toute coupure."""
    restantes = [c for c in _lire_claims() if c != str(owner)]
    _ecrire_claims(restantes)
    if restantes:
        return {"released": False, "claims_restantes": restantes}
    # 10/11 soir : une demande ANONYME plus jeune que le TTL (ensure_service docker, recherche, hub) n'appartient
    # pas a cette reclamation : on la laisse vivre, le TTL de docker.wanted fera l'arret (mesure : Docker coupe a
    # 16:26 sous un ensure de 16:22, canari Gordon ILLISIBLE).
    age = _demande_anonyme_age()
    if age is not None and age < WANT_TTL_S:
        _audit("release", "derniere reclamation relachee (%s) : demande anonyme fraiche (%.0f s) -> Docker garde "
                          "jusqu'au TTL" % (owner, age))
        return {"released": True, "differe": False, "garde_anonyme": round(age)}
    try:
        WANT_FLAG.unlink()
    except FileNotFoundError:  # muet-ok : relachement IDEMPOTENT, un drapeau deja absent est l'etat vise
        pass
    except OSError as exc:
        log.warning("release_claim: unlink docker.wanted failed: %s", exc)
    palier = palier_courant()
    n = intentions_docker_en_attente()
    delai = delai_de_grace(n, palier)
    # Owner 3/11 (« deja dit ») : une CHAINE qui finit ou est annulee (immediat=True) et qu'aucune intention n'attend
    # -> coupure SANS grace. La grace reste pour les recherches PONCTUELLES qui s'enchainent, et quand le nombre
    # d'intentions est ILLISIBLE (None : UNKNOWN != NO). NR test_docker_coupure_sans_intention_nr.
    if immediat and isinstance(n, int) and not isinstance(n, bool) and n == 0:
        delai = 0.0
    motif = ("derniere reclamation relachee (%s) : delai %.0f s (palier %s, intentions %s)"
             % (owner, delai, palier, "INCONNU" if n is None else n))
    if delai <= 0:
        _audit("release", motif + " -> arret immediat")
        detail = _release_docker()
        if not str((detail or {}).get("engine_verdict", "")).startswith("ARRETE"):
            # 4/11 : arret non atteint ici (ex. compte des jobs face a un Docker Desktop de session owner) -> on
            # SIGNALE a l'effecteur au lieu de le laisser allume sans intention. NR test_docker_relache_retentee...
            _signaler_relache("release_claim:%s" % owner)
        return {"released": True, "differe": False, "detail": detail}
    now = time.time()
    rec = {"debut": now, "echeance": now + delai, "delai": delai, "intentions": n, "palier": palier,
           "motif": motif}
    try:
        p = _release_at_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec), encoding="utf-8")
    except OSError as exc:
        # echeance non posable : on ne laisse pas Docker sans fin de vie, on arrete comme avant.
        _audit("release", motif + " ; release_at NON ecrit (%s) -> arret immediat" % type(exc).__name__)
        return {"released": True, "differe": False, "detail": _release_docker()}
    _audit("release", motif + " -> arret differe", echeance=rec["echeance"])
    return {"released": True, "differe": True, "release_at": rec}


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


def _force_recycle_docker(motif: str = "process up mais daemon KO") -> bool:
    """Débloque un Docker figé en 'starting' : kill TOUS les process Docker + wsl --shutdown
    (reset backend WSL2) + relance propre. Un simple re-Popen ne suffit pas si l'instance
    hung est encore présente (cf symptôme 'reste en starting / ne se coupe pas').
    `motif` : la raison REELLE du cycle, journalisee telle quelle (2026-10-13 : l'integration WSL cassee
    declenche aussi ce cycle, et le journal ne doit pas dire « STUCK starting » a sa place)."""
    log.warning("docker FORCE-RECYCLE (kill + wsl shutdown + relaunch) : %s", motif)
    _audit("kill", "force-recycle: %s" % motif, procs=",".join(_DOCKER_PROC_NAMES))
    if sys.platform == "win32":
        for name in _DOCKER_PROC_NAMES:
            try:
                subprocess.run(["taskkill", "/F", "/IM", name, "/T"], timeout=15,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:  # noqa: BLE001
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_docker_keeper.py', 492, exc_info=True)
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


# --- Levier 1 (owner 2/11) : vider le cache Linux de la VM Docker quand son SURCOUT le justifie ---------------------
# Mesure du 2/11 : conteneurs ~1,0 Gio pour vmmemWSL 4,56 Go ; drop_caches manuel -> 3,99 Go (gain progressif via
# autoMemoryReclaim). Ne touche pas aux conteneurs : pas d'attente de fin de veille (c'est pendant elles que la RAM
# bloque leur admission). Chaque vidage est journalise avec la mesure d'AVANT (capteur : le tick suivant dit l'apres).
_VIDAGE_SEUIL_MO = int(os.environ.get("LAFORGE_WSL_VIDAGE_SEUIL_MO", "1500"))
_VIDAGE_REFRACTAIRE_S = float(os.environ.get("LAFORGE_WSL_VIDAGE_REFRACTAIRE_S", "300"))
_dernier_vidage = None
_RE_MEM = re.compile(r"([\d.]+)\s*(KiB|MiB|GiB|kB|MB|GB|B)\b")
_FACTEUR_MO = {"B": 1 / 1048576, "KiB": 1 / 1024, "kB": 1 / 1024, "MiB": 1.0, "MB": 1.0, "GiB": 1024.0, "GB": 1024.0}


def decider_vidage_cache(vmmem_mo, conteneurs_mo, dernier, maintenant) -> tuple:
    """(vider ?, motif). Mesure illisible -> non (UNKNOWN != 0) ; sous le seuil -> non ; periode refractaire -> non."""
    if vmmem_mo is None or conteneurs_mo is None:
        return False, "mesure illisible (vmmem=%s, conteneurs=%s)" % (vmmem_mo, conteneurs_mo)
    surcout = vmmem_mo - conteneurs_mo
    if surcout <= _VIDAGE_SEUIL_MO:
        return False, "surcout %d Mo <= seuil %d Mo" % (surcout, _VIDAGE_SEUIL_MO)
    if dernier is not None and maintenant - dernier < _VIDAGE_REFRACTAIRE_S:
        return False, "refractaire (%.0f s < %.0f s)" % (maintenant - dernier, _VIDAGE_REFRACTAIRE_S)
    return True, "surcout %d Mo > seuil %d Mo" % (surcout, _VIDAGE_SEUIL_MO)


def memoire_conteneurs_mo(sortie) -> "float | None":
    """Somme des memoires de `docker stats --format {{.MemUsage}}` (« 226.6MiB / 9.714GiB » par ligne)."""
    if sortie is None:
        return None
    tot = 0.0
    for ligne in sortie.splitlines():
        m = _RE_MEM.search(ligne.split("/")[0])
        if m:
            tot += float(m.group(1)) * _FACTEUR_MO[m.group(2)]
    return tot


def mesurer_surcout_vm() -> tuple:
    """(vmmem_mo, conteneurs_mo) ; None pour une mesure illisible."""
    vm = None
    try:
        import psutil
        vm = sum(p.info["memory_info"].rss for p in psutil.process_iter(["name", "memory_info"])
                 if (p.info["name"] or "").lower().startswith("vmmem")) / 1048576.0
    except Exception as exc:  # noqa: BLE001 - dit : None, jamais 0
        log.warning("vmmem ILLISIBLE (%s)", type(exc).__name__)
    try:
        rc, out = _docker_cli(["stats", "--no-stream", "--format", "{{.MemUsage}}"])
        ct = memoire_conteneurs_mo(out) if rc == 0 else None
    except Exception as exc:  # noqa: BLE001
        log.warning("docker stats ILLISIBLE (%s)", type(exc).__name__)
        ct = None
    return vm, ct


def _commande_vidage_cache() -> list:
    return ["wsl", "-d", "docker-desktop", "-u", "root", "sh", "-c", "sync; echo 1 > /proc/sys/vm/drop_caches"]


def _vider_cache_wsl() -> tuple:
    """Vidage dans la session OWNER (wsl est scope owner ; meme mecanisme que _wsl_shutdown), repli subprocess."""
    cmd = _commande_vidage_cache()
    if sys.platform == "win32":
        try:
            sid = _active_console_session_id()
            if sid is not None:
                wsl_exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "wsl.exe")
                _launch_in_user_session(sid, wsl_exe, " ".join(cmd[1:-1]) + ' "%s"' % cmd[-1])
                return 0, "session owner sid=%s" % sid
        except Exception as exc:  # noqa: BLE001
            log.warning("vidage cache WSL owner-session KO (%s) -> repli subprocess", exc)
    try:
        r = subprocess.run(cmd, timeout=25, capture_output=True, text=True, errors="replace")
        return r.returncode, (r.stderr or r.stdout or "").strip()[-200:]
    except Exception as exc:  # noqa: BLE001
        return -1, "%s: %s" % (type(exc).__name__, exc)


# LEVIER QDRANT (owner 2/11, « levier durable + vidage maintenant ») : qdrant.exe tenait 6,34 Go RESIDENTS dont 0,19 Go
# PRIVES -- pages des vecteurs on_disk mappees (1,6 M points ColBERT) que la jauge compte comme occupees, bloquant
# l'admission des jobs. Geste owner EmptyWorkingSet : 6,34 -> 0,00 Go, service intact. Le keeper (lance par le meme
# superviseur que Qdrant, donc avec les droits sur son processus -- les comptes du bac a sable sont refuses) refait ce
# geste quand : RAM >= seuil, residente >= plancher, privee < fraction du residente ; refractaire ; audit.
# NR : tests/nr/test_keeper_vidage_ws_qdrant_nr.py
_QDRANT_RAM_SEUIL = float(os.environ.get("LAFORGE_QDRANT_WS_RAM_SEUIL", "80"))
_QDRANT_RSS_PLANCHER_GO = float(os.environ.get("LAFORGE_QDRANT_WS_RSS_GO", "2.0"))
_QDRANT_PRIVE_FRACTION = float(os.environ.get("LAFORGE_QDRANT_WS_PRIVE_FRACTION", "0.2"))
_QDRANT_REFRACTAIRE_S = float(os.environ.get("LAFORGE_QDRANT_WS_REFRACTAIRE_S", "600"))
# 7/11 (owner) : au-dela de ce seuil, vidage sans attendre le refractaire, pour ne pas franchir les 88 % du superviseur
# entre deux recherches. Une voie sterile garde son refractaire : vider sans gain ne libere rien.
_QDRANT_RAM_URGENCE = float(os.environ.get("LAFORGE_QDRANT_WS_RAM_URGENCE", "85"))
_dernier_vidage_qdrant = None


def _ram_dispo_go():
    """RAM reellement disponible (Go) ; None si illisible (jamais 0)."""
    try:
        import psutil

        return psutil.virtual_memory().available / 1e9
    except Exception:  # noqa: BLE001  # muet-ok : illisible -> None, l'appelant le traite comme INCONNU
        return None


# 3/11 (debat 2) : un effecteur MESURE ce qu'il rend. Le vidage du working set de qdrant « reussissait » sans rien
# rendre (cache mappe re-touche aussitot) et recommencait a chaque fin de refractaire. Voie sterile -> refractaire
# double (x2, x4, x8) ; voie feconde -> remis a la base.
_QDRANT_GAIN_MIN_GO = 0.3
_qdrant_sterile = 0


def decider_vidage_qdrant(ram_pct, rss_go, prive_go, dernier, maintenant, sterile: int = 0) -> tuple:
    """(vider ?, motif). Mesure illisible -> non (UNKNOWN != 0) ; memoire PRIVEE majoritaire -> non (rien a rendre)."""
    if None in (ram_pct, rss_go, prive_go):
        return False, "mesure illisible (ram=%s, rss=%s, prive=%s)" % (ram_pct, rss_go, prive_go)
    if ram_pct < _QDRANT_RAM_SEUIL:
        return False, "RAM %.1f %% < seuil %.0f %%" % (ram_pct, _QDRANT_RAM_SEUIL)
    if rss_go < _QDRANT_RSS_PLANCHER_GO:
        return False, "residente %.2f Go < plancher %.1f Go" % (rss_go, _QDRANT_RSS_PLANCHER_GO)
    if prive_go >= _QDRANT_PRIVE_FRACTION * rss_go:
        return False, "privee %.2f Go >= %.0f %% de la residente : pas du cache de fichiers" % (
            prive_go, 100 * _QDRANT_PRIVE_FRACTION)
    if ram_pct > _QDRANT_RAM_URGENCE and not sterile:
        return True, "URGENCE RAM %.1f %%, qdrant residente %.2f Go dont privee %.2f Go (cache mappe)" % (
            ram_pct, rss_go, prive_go)
    refractaire = _QDRANT_REFRACTAIRE_S * (2 ** min(max(int(sterile), 0), 3))
    if dernier is not None and maintenant - dernier < refractaire:
        return False, "refractaire (%.0f s < %.0f s%s)" % (maintenant - dernier, refractaire,
                                                           ", voie sterile x%d" % sterile if sterile else "")
    return True, "RAM %.1f %%, qdrant residente %.2f Go dont privee %.2f Go (cache mappe)" % (ram_pct, rss_go, prive_go)


def mesurer_qdrant() -> tuple:
    """(ram_pct, rss_go, prive_go, pid) ; None sur ce qui n'est pas lisible (jamais 0 par defaut)."""
    try:
        import psutil

        ram = psutil.virtual_memory().percent
        p = next((x for x in psutil.process_iter(["name"]) if (x.info["name"] or "").lower() == "qdrant.exe"), None)
        if p is None:
            return ram, None, None, None
        mi = p.memory_info()
        prive = getattr(mi, "private", None)
        return ram, mi.rss / 2 ** 30, (None if prive is None else prive / 2 ** 30), p.pid
    except Exception:  # noqa: BLE001 - illisible, dit par la decision
        return None, None, None, None


def _vider_ws_processus(pid: int) -> tuple:
    """EmptyWorkingSet sur `pid` (psapi). (ok, detail). Ne tue ni ne modifie le processus : ses pages repassent en
    cache liberable et sont relues a la demande."""
    try:
        import ctypes

        k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        h = k32.OpenProcess(0x0100 | 0x0400, False, int(pid))   # PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION
        if not h:
            return False, "OpenProcess refuse (erreur %d)" % k32.GetLastError()
        try:
            ok = bool(psapi.EmptyWorkingSet(h))
            return ok, "EmptyWorkingSet=%s" % ok
        finally:
            k32.CloseHandle(h)
    except Exception as exc:  # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)


def _tick_vidage_qdrant(maintenant, _attendre=time.sleep) -> dict:
    global _dernier_vidage_qdrant, _qdrant_sterile
    ram, rss, prive, pid = mesurer_qdrant()
    vider, motif = decider_vidage_qdrant(ram, rss, prive, _dernier_vidage_qdrant, maintenant, sterile=_qdrant_sterile)
    r = {"vidage": vider, "motif": motif}
    if vider and pid:
        _dernier_vidage_qdrant = maintenant
        avant = _ram_dispo_go()
        ok, detail = _vider_ws_processus(pid)
        _attendre(5)
        apres = _ram_dispo_go()
        gain = round(apres - avant, 2) if None not in (avant, apres) else None
        if gain is not None:
            _qdrant_sterile = _qdrant_sterile + 1 if gain < _QDRANT_GAIN_MIN_GO else 0
        r.update(ok=ok, detail=detail, gain_go=gain, sterile=_qdrant_sterile)
        _audit("vidage_ws_qdrant", motif, rss_avant_go=round(rss, 2), prive_go=round(prive, 2), ram_pct=ram, ok=ok,
               detail=detail, gain_go=gain, sterile=_qdrant_sterile)
        log.info("vidage working set qdrant : %s (%s) gain mesure %s Go, sterile %d", detail, motif, gain,
                 _qdrant_sterile)
    return r


_dernier_journal_non_vidage = None
_JOURNAL_NON_VIDAGE_S = 600.0


def _tick_vidage_cache(maintenant) -> dict:
    global _dernier_vidage, _dernier_journal_non_vidage
    vm, ct = mesurer_surcout_vm()
    vider, motif = decider_vidage_cache(vm, ct, _dernier_vidage, maintenant)
    r = {"vidage": vider, "motif": motif, "vmmem_mo": None if vm is None else round(vm),
         "surcout_mo": None if vm is None or ct is None else round(vm - ct)}
    # Un REFUS se dit aussi (owner 10/11 « garder dropcache, mesurer ») : vmmemWSL a 5 Go sans aucune trace de
    # decision rendait le levier invisible. Borne a 1 ligne / 10 min pour ne pas noyer le journal.
    if not vider and (_dernier_journal_non_vidage is None
                      or maintenant - _dernier_journal_non_vidage >= _JOURNAL_NON_VIDAGE_S):
        _dernier_journal_non_vidage = maintenant
        logging.getLogger("docker_keeper").info(
            "vidage cache WSL : non (%s) -- vmmem %s Mo, surcout %s Mo", motif,
            r["vmmem_mo"] if r["vmmem_mo"] is not None else "?", r["surcout_mo"] if r["surcout_mo"] is not None else "?")
    if vider:
        _dernier_vidage = maintenant
        rc, detail = _vider_cache_wsl()
        r.update(rc=rc, detail=detail)
        _audit("vidage_cache_wsl", motif, vmmem_avant_mo=round(vm), conteneurs_mo=round(ct), rc=rc)
    return r


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
    _marquer_arret_volontaire("release_docker")
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
    # Un conteneur a la demande ne revient pas sans reclamation : on retire la reclamation et on pose
    # restart=no AVANT l'arret (un conteneur cree en restart=always remonte avec le moteur).
    try:
        CRAWL4AI_FLAG.unlink(missing_ok=True)
    except OSError as exc:
        out["crawl4ai_flag"] = "non retire: %s" % type(exc).__name__
    for n in mine:
        try:
            subprocess.run(["docker", "update", "--restart=no", n], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        except Exception as exc:  # noqa: BLE001
            out.setdefault("restart_non_pose", []).append("%s: %s" % (n, type(exc).__name__))
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
    out["engine_verdict"] = _verifier_arret_moteur(out)
    out["etat_reel"] = verifier_etat_arret()
    return out


def _distros_wsl_docker_arretees() -> bool | None:
    """Verifie si les distributions WSL docker-desktop* sont arretees.
    Rend True si arretees, False si au moins une tourne, None si illisible."""
    if sys.platform != "win32":
        return True
    try:
        r = subprocess.run(["wsl", "--list", "--running", "-q"],
                           capture_output=True, timeout=15)
        if r.returncode != 0:
            r = subprocess.run(["wsl", "--list", "--running"],
                               capture_output=True, timeout=15)
            if r.returncode != 0:
                return None
        raw = r.stdout or b""
        txt = raw.decode("utf-16", errors="replace") if b"\x00" in raw else raw.decode("utf-8", errors="replace")
        en_cours = [
            l.strip() for l in txt.splitlines()
            if l.strip() and any(d in l.lower() for d in ("docker-desktop", "docker-desktop-data"))
        ]
        return len(en_cours) == 0
    except Exception:  # noqa: BLE001
        return None


def verifier_etat_arret(sonde_docker=None, sonde_wsl=None) -> str:
    """REQUESTED != ACHIEVED : lit l'etat reel apres un arret demande.

    Sondes :
      - Docker repond-il ?
      - Distributions WSL docker-desktop* arretees ?

    Verdicts (journalise) :
      - ARRETE : Docker ne repond pas ET toutes les distros WSL docker-desktop* arretees.
      - ENCORE_VIVANT : Docker repond encore OU au moins une distro WSL docker-desktop* encore active.
      - ILLISIBLE : sonde indisponible / en erreur. ILLISIBLE n'est JAMAIS interprete comme ARRETE.
    """
    docker_up = None
    wsl_arrete = None

    # 1. Sonde Docker
    try:
        fn_docker = sonde_docker if sonde_docker is not None else _moteur_repond
        res_d = fn_docker()
        if res_d is None or res_d == "ILLISIBLE":
            docker_up = None
        elif isinstance(res_d, str):
            if res_d.upper() in ("UP", "VIVANT", "ENCORE_VIVANT", "TRUE"):
                docker_up = True
            elif res_d.upper() in ("DOWN", "ARRETE", "FALSE"):
                docker_up = False
            else:
                docker_up = None
        else:
            docker_up = bool(res_d)
    except Exception:  # noqa: BLE001
        docker_up = None

    # 2. Sonde WSL
    try:
        fn_wsl = sonde_wsl if sonde_wsl is not None else _distros_wsl_docker_arretees
        res_w = fn_wsl()
        if res_w is None or res_w == "ILLISIBLE":
            wsl_arrete = None
        elif isinstance(res_w, (list, tuple, set)):
            wsl_arrete = (len(res_w) == 0)
        elif isinstance(res_w, str):
            if res_w.upper() in ("ARRETE", "STOPPED", "TRUE"):
                wsl_arrete = True
            elif res_w.upper() in ("VIVANT", "RUNNING", "ENCORE_VIVANT", "FALSE"):
                wsl_arrete = False
            else:
                wsl_arrete = None
        elif isinstance(res_w, bool):
            wsl_arrete = res_w
        else:
            wsl_arrete = None
    except Exception:  # noqa: BLE001
        wsl_arrete = None

    # 3. Arbitrage strict
    if docker_up is True:
        verdict = "ENCORE_VIVANT"
        detail = "daemon Docker repond encore"
    elif docker_up is False and wsl_arrete is False:
        verdict = "ENCORE_VIVANT"
        detail = "daemon Docker muet mais distribution WSL docker-desktop encore active"
    elif docker_up is False and wsl_arrete is True:
        verdict = "ARRETE"
        detail = "daemon Docker muet et distributions WSL docker-desktop arretees"
    else:
        verdict = "ILLISIBLE"
        raisons = []
        if docker_up is None:
            raisons.append("sonde Docker illisible")
        if wsl_arrete is None:
            raisons.append("sonde WSL illisible")
        detail = " ; ".join(raisons) or "etat indisponible"

    log.info("verification etat arret : %s (%s)", verdict, detail)
    _audit("verify_stop", detail, verdict=verdict, docker_up=docker_up, wsl_arrete=wsl_arrete)
    return verdict


# Alias pour interoperabilite et callers
verifier_etat_reel = verifier_etat_arret
verifier_etat_reel_arret = verifier_etat_arret
verifier_arret_effectif = verifier_etat_arret
verifier_fin_de_vie = verifier_etat_arret


def _moteur_repond() -> bool:
    try:
        r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True,
                           text=True, errors="replace", timeout=10)
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:  # noqa: BLE001 - pas de reponse = pas de moteur
        return False


def _attendre_moteur_eteint(delai_s: float, pas_s: float = 2.0) -> bool:
    for _ in range(max(1, int(delai_s // pas_s)) + 1):
        if not _moteur_repond():
            return True
        time.sleep(pas_s)
    return False


def _verifier_arret_moteur(out: dict) -> str:
    """REQUESTED != ACHIEVED : attend l'effet, escalade (seule distribution docker-desktop, jamais
    `wsl --shutdown` qui toucherait les autres distributions), puis rend un verdict honnete."""
    if "intact" in str(out.get("engine", "")):
        return "NON ARRETE : moteur volontairement conserve (%s)" % out["engine"]
    if _attendre_moteur_eteint(20.0):
        return "ARRETE (docker desktop stop)"
    for distro in ("docker-desktop", "docker-desktop-data"):
        try:
            subprocess.run(["wsl", "--terminate", distro], capture_output=True, text=True,
                           errors="replace", timeout=30)
        except Exception as exc:  # noqa: BLE001
            out.setdefault("terminate_ko", []).append("%s: %s" % (distro, type(exc).__name__))
    if _attendre_moteur_eteint(20.0):
        return "ARRETE (wsl --terminate docker-desktop)"
    return "NON ARRETE : le daemon repond encore apres desktop stop (20 s) et wsl --terminate docker-desktop (20 s)"


# 3/11 (owner « s'il ne porte pas d'intention tu le coupes ») : carcasse = processus Docker (Desktop/backend/VM WSL)
# vivants alors que le moteur ne repond pas et que personne ne le reclame. Mesure : ~5,5 Go tenus 18h41-18h55, RAM 87 %,
# tous les jobs refuses -- la relache n'etait evaluee que moteur REPONDANT.
CARCASSE_GRACE_S = float(os.environ.get("DOCKER_KEEPER_CARCASSE_GRACE_S", "300"))


def _tick_carcasse(now: float) -> dict | None:
    """Moteur DOWN, non voulu : si des processus Docker restent vivants au-dela de CARCASSE_GRACE_S (un demarrage manuel
    a le temps d'aboutir ; il serait alors relache par _maybe_release comme tout Docker non voulu), on relache. Une chaine
    de veille active, ou des intentions illisibles, interdisent (fail-closed, comme _maybe_release)."""
    if not RELEASE_ENABLED:
        return None
    if _docker_wanted() or not _docker_procs_present():
        _STATE.pop("carcasse_depuis", None)
        return None
    debut = _STATE.setdefault("carcasse_depuis", now)
    if now - debut < CARCASSE_GRACE_S:
        return None
    # Meme refractaire que _maybe_release : un Desktop qui survit a `docker desktop stop` ne doit pas etre re-stoppe
    # toutes les CARCASSE_GRACE_S.
    if now - float(_STATE.get("last_release_ts", 0.0)) < _RELEASE_REFRACTORY_S:
        return None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_resource_manager import get_active_intents

        if _retient_docker(get_active_intents()):   # 4/11 : par etape (search/crawl)
            return None
    except Exception:  # noqa: BLE001  # muet-ok : intentions illisibles -> on ne coupe pas (fail-closed)
        return None
    detail = _release_docker()
    _STATE.pop("carcasse_depuis", None)
    _STATE["last_release_ts"] = now
    _audit("release_carcasse", "processus Docker vivants, moteur eteint, sans intention depuis %.0f s" % (now - debut),
           **detail)
    log.info("relache carcasse Docker : %s", json.dumps(detail, default=str)[:200])
    return detail


def relacher_substrat_sans_intention(now: float) -> dict:
    """Effecteur de SUBSTRAT (3/11, debat 2) appele par la garde d'admission quand l'eviction des modeles n'a pas rendu
    assez : relache IMMEDIATE (stress aigu, pas de grace) d'un Docker vivant SANS intention. Jamais sous docker.wanted,
    jamais avec une chaine active, jamais sur intentions illisibles (fail-closed) ; meme refractaire que _maybe_release."""
    if not RELEASE_ENABLED:
        return {"relache": False, "motif": "relache desactivee"}
    if _docker_wanted():
        return {"relache": False, "motif": "intention docker.wanted presente"}
    if not _docker_procs_present():
        return {"relache": False, "motif": "aucun processus Docker (absent) : rien a rendre"}
    # `now` est l'horloge MONOTONE de l'appelant (propre a son processus) : elle ne sert qu'au refractaire en memoire.
    # Le refractaire PARTAGE (hub <-> keeper) se juge a l'horloge MURALE, seule comparable entre processus.
    _dernier_local = _STATE.get("last_release_ts")
    if _dernier_local is not None and now - float(_dernier_local) < _RELEASE_REFRACTORY_S:
        return {"relache": False, "motif": "refractaire"}
    try:
        _dernier_partage = (float((json.loads(_FICHIER_SUBSTRAT.read_text(encoding="utf-8")) or {}).get("ts") or 0.0)
                            if _FICHIER_SUBSTRAT.exists() else 0.0)
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        return {"relache": False, "motif": "registre refractaire illisible (%s) : on ne coupe pas" % type(exc).__name__}
    if time.time() - _dernier_partage < _RELEASE_REFRACTORY_S:
        return {"relache": False, "motif": "refractaire (partage)"}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from nokido_agent.app.forge_resource_manager import get_active_intents

        if _retient_docker(get_active_intents()):   # 4/11 : par etape (search/crawl)
            return {"relache": False, "motif": "chaine active : le substrat travaille"}
    except Exception as exc:  # noqa: BLE001 - dit dans le motif, on ne coupe pas
        return {"relache": False, "motif": "intentions illisibles (%s) : on ne coupe pas" % type(exc).__name__}
    detail = _release_docker()
    _STATE["last_release_ts"] = now
    motif = "Docker vivant sans intention relache"
    try:
        _FICHIER_SUBSTRAT.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FICHIER_SUBSTRAT.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
        os.replace(tmp, _FICHIER_SUBSTRAT)
    except OSError as exc:
        # Docker EST relache : le dire. Seul le partage du refractaire a echoue (memoire locale seule).
        motif += " (refractaire non persiste : %s)" % type(exc).__name__
        log.warning("refractaire du substrat NON persiste (%s) : refractaire en memoire seulement", exc)
    _audit("release_substrat", "refus d'admission : Docker vivant sans intention", **detail)
    log.info("relache substrat (refus d'admission) : %s", json.dumps(detail, default=str)[:200])
    return {"relache": True, "motif": motif, "detail": detail}


def _retient_docker(intents) -> bool:
    """4/11 : une chaine retient-elle Docker ? `forge_resource_manager.intention_docker` (intention PAR ETAPE :
    search/crawl, anticipation) ; module sans elle (doublure, version anterieure) = lecture d'avant, chains_active."""
    try:
        from nokido_agent.app import forge_resource_manager as _rm
        juge = getattr(_rm, "intention_docker", None)
    except Exception:  # noqa: BLE001 - module illisible : lecture d'avant
        juge = None
    if juge is not None:
        return bool(juge(intents))
    return bool((intents or {}).get("chains_active"))


# 4/11 (owner « capacite basique du corps » ; « signal nerveux = action / reaction ») : 17:58 relache tentee mais
# « engine intact (conteneurs tiers presents) » -> refractaire de 1800 s arme par une tentative SANS EFFET, Docker
# allume sans intention ; et release_claim depuis le compte des jobs ne peut pas arreter un Docker Desktop de session
# owner (6 x NON ARRETE). L'organe qui constate DEPOSE un signal ; le keeper (effecteur qui en a les droits) REAGIT a
# son battement suivant, refractaire ignore ; signal maintenu tant qu'un tiers bloque, eteint des que l'arret est fait.
# NR tests/nr/test_docker_relache_retentee_apres_tiers_nr.py.
def _signal_relache_path() -> Path:
    return WANT_FLAG.parent / "docker.relache_demandee"


def _signaler_relache(origine: str) -> None:
    try:
        _signal_relache_path().write_text(json.dumps({"ts": time.time(), "origine": str(origine)}), encoding="utf-8")
    except OSError as exc:
        log.warning("signal de relache non depose (%s) : %s", origine, exc)


def _eteindre_signal_relache() -> None:
    try:
        _signal_relache_path().unlink()
    except FileNotFoundError:  # muet-ok : extinction IDEMPOTENTE, un signal deja absent est l'etat vise
        pass
    except OSError as exc:
        log.warning("signal de relache non eteint : %s", exc)


def _maybe_release(now: float) -> dict | None:
    """Faut-il relacher ? Rend le detail si une relache a eu lieu, sinon None."""
    if not RELEASE_ENABLED:
        return None
    reflexe = _signal_relache_path().exists()
    if _docker_wanted():
        if reflexe:
            _eteindre_signal_relache()   # un consommateur a re-reclame : le signal est perime
        return None
    if _release_at_path().exists():
        # Grace en cours : c'est _tick_release_at qui decide. Sans ce garde, docker.wanted retire (age None)
        # laissait cette relache de secours couper Docker au tick suivant -- grace annulee (NR tick reel 28/10).
        return None
    if not reflexe and now - float(_STATE["last_release_ts"]) < _RELEASE_REFRACTORY_S:
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
        if _retient_docker(intents):   # 4/11 : par etape (search/crawl), plus toute chaine
            if reflexe:
                _eteindre_signal_relache()   # une intention vivante l'emporte sur le signal
            return None
    except Exception:  # noqa: BLE001
        return None            # fail-closed : sans lecture d'intention, on ne coupe pas
    detail = _release_docker()
    if str((detail or {}).get("engine", "")).startswith("intact"):
        _signaler_relache("keeper:tiers %s" % (detail or {}).get("foreign_laisses"))   # reflexe ARME
    else:
        _eteindre_signal_relache()
    _STATE["last_release_ts"] = now
    _audit("release", "aucun demandeur depuis %s s (TTL %.0f + grace %.0f)"
           % (int(age) if age else "?", WANT_TTL_S, RELEASE_GRACE_S), **detail)
    log.info("relache Docker : %s", json.dumps(detail, default=str)[:200])
    return detail


# INTEGRATION WSL CASSEE (2026-10-13). Apres une mise a jour de Docker Desktop -- ou toute relance qui ne passe pas
# par ce keeper -- le namespace partage /mnt/wsl se rompt : la distro Debian ne voit plus backend.sock, et Docker
# Desktop affiche une fenetre d'erreur toutes les ~75 s alors que le moteur, lui, REPOND. Le remede est prouve
# (`wsl --shutdown`, 2026-06-03 et 2026-07-27) et deja ecrit ici (_force_recycle_docker -> _launch_docker_desktop
# -> _wsl_shutdown) ; il n'etait jamais declenche par ce symptome, puisque le daemon repond. Signal = le journal de
# l'ORGANE (Docker Desktop), jamais une sonde. Un cycle par episode, refractaire d'une heure : lancer OUI, boucler NON.
_SIGNATURE_INTEGRATION = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})[^\]]*\].*waiting \S+ for the backend socket.*DockerDesktop/Wsl/ExecError",
    re.M)
# PREUVE POSITIVE de sante : Docker Desktop journalise « adding a wsl agent for new distro <X> » ; un ajout sans
# erreur derriere depuis plus de _INTEGRATION_PREUVE_S vaut « ok ». Sans cette ligne, l'absence d'erreur ne prouve
# rien (Docker Desktop peut avoir cesse de reessayer) : INCONNU, jamais « ok » (2026-10-13).
_AJOUT_AGENT = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})[^\]]*\]\[com\.docker\.backend\.exe\.wslintegration\] "
    r"adding a wsl agent for new distro", re.M)
_INTEGRATION_PREUVE_S = 90
_INTEGRATION_FENETRE_S = 600
_INTEGRATION_REFRACTAIRE_S = 3600
_INTEGRATION: dict = {"fichier": None, "pos": None, "dernier_cycle": 0.0, "sans_effet_dit": False}


def _journal_docker_desktop() -> Path | None:
    """Journal backend de Docker Desktop. Le keeper tourne en SYSTEM, sans le LOCALAPPDATA de l'owner : on prend le
    journal le plus recemment ecrit sous les profils (override DOCKER_KEEPER_DESKTOP_LOG). None = introuvable."""
    force = os.environ.get("DOCKER_KEEPER_DESKTOP_LOG")
    if force:
        return Path(force)
    racine = Path(os.environ.get("SystemDrive", "C:") + "\\") / "Users"
    try:
        cands = list(racine.glob("*/AppData/Local/Docker/log/host/com.docker.backend.exe.log"))
        return max(cands, key=lambda p: p.stat().st_mtime) if cands else None
    except OSError:  # muet-ok : None remonte en « integration_wsl: ILLISIBLE » dans le heartbeat
        return None


def _integration_wsl_cassee(maintenant: float | None = None) -> int | None:
    """Occurrences RECENTES (< 10 min) de la signature, lues depuis la derniere position.
    None = journal ILLISIBLE, jamais lu comme « pas de panne »."""
    p = _journal_docker_desktop()
    if p is None:
        return None
    try:
        taille = p.stat().st_size
        if _INTEGRATION["fichier"] != str(p) or _INTEGRATION["pos"] is None or taille < _INTEGRATION["pos"]:
            debut = max(0, taille - 262144)  # premiere lecture ou rotation : la fin recente seulement
        else:
            debut = _INTEGRATION["pos"]
        with open(p, "rb") as f:
            f.seek(debut)
            bloc = f.read(max(0, taille - debut)).decode("utf-8", "replace")
        _INTEGRATION.update(fichier=str(p), pos=taille)
    except OSError:  # muet-ok : None remonte en « integration_wsl: ILLISIBLE » dans le heartbeat
        return None
    from datetime import datetime, timezone

    def _ts(h):
        try:
            return datetime.strptime(h, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:  # muet-ok : une ligne a l'horodatage illisible ne compte pas
            return None

    limite = (maintenant if maintenant is not None else time.time()) - _INTEGRATION_FENETRE_S
    n = 0
    for ts in filter(None, map(_ts, _SIGNATURE_INTEGRATION.findall(bloc))):
        _INTEGRATION["derniere_signature_ts"] = max(ts, _INTEGRATION.get("derniere_signature_ts") or 0.0)
        if ts >= limite:
            n += 1
    for ts in filter(None, map(_ts, _AJOUT_AGENT.findall(bloc))):
        _INTEGRATION["dernier_ajout_ts"] = max(ts, _INTEGRATION.get("dernier_ajout_ts") or 0.0)
    return n


def _signaler_moelle(stats: dict) -> None:
    """Afference DIRECTE vers la moelle (forge_organ_afferent -> forge_trace_spine), sur TRANSITION d'etat
    seulement : le heartbeat dit l'etat a qui le lit, la moelle le PORTE aux organes qui ecoutent (owner 13/10 :
    « branche au systeme nerveux »). Pas d'hormone : une integration Docker cassee est une information
    sensorielle, pas un stress systemique -- une hormone module les admissions de tout le corps."""
    etat = stats.get("integration_wsl")
    if etat == _INTEGRATION.get("dernier_etat_signale"):
        return
    _INTEGRATION["dernier_etat_signale"] = etat
    try:
        from nokido_agent.app.forge_organ_afferent import emettre

        ok, raison = emettre("docker_keeper", "docker", dict(stats), kind="integration_wsl")
        if not ok:
            log.warning("moelle : signal integration_wsl=%s REFUSE (%s)", etat, raison)
    except Exception as exc:  # noqa: BLE001 -- dit ici : le heartbeat porte toujours l'etat
        log.warning("moelle INJOIGNABLE (%s) : transition integration_wsl=%s non propagee", type(exc).__name__, etat)


def _en_refractaire(stats: dict) -> bool:
    depuis = time.monotonic() - _INTEGRATION["dernier_cycle"]
    if not (_INTEGRATION["dernier_cycle"] and depuis < _INTEGRATION_REFRACTAIRE_S):
        return False
    stats["integration_wsl_refractaire_s"] = round(_INTEGRATION_REFRACTAIRE_S - depuis, 1)
    if stats.get("integration_wsl") == "CASSEE" and not _INTEGRATION["sans_effet_dit"]:
        _INTEGRATION["sans_effet_dit"] = True
        log.error("integration WSL toujours CASSEE %.0f s apres le cycle : remede SANS EFFET cette fois, aucun "
                  "nouveau cycle avant la fin du refractaire (instruire : %s)", depuis, _INTEGRATION["fichier"])
    return True


def _cycle_integration(stats: dict, motif: str) -> dict:
    log.warning("integration WSL : %s -> cycle prouve", motif)
    _INTEGRATION["dernier_cycle"] = time.monotonic()
    lance = _force_recycle_docker(motif)
    stats["integration_wsl_cycle"] = bool(lance)
    if lance:
        budget, _why = _boot_timeout_for_load()
        woke, what = _wait_daemon(time.monotonic() + budget)
        stats["integration_wsl_wake_ok"] = woke
        stats["integration_wsl_wake_info"] = what
        if woke:
            _STATE["last_boot_ok_ts"] = time.monotonic()
    try:  # les lignes ecrites avant ou pendant le cycle ne sont pas recomptees
        _INTEGRATION["pos"] = Path(_INTEGRATION["fichier"]).stat().st_size
    except (OSError, TypeError):  # muet-ok : au pire, la lecture suivante recompte et le refractaire tient
        pass
    return stats


def _surveiller_integration_wsl(version: str | None = None) -> dict:
    """Champs de heartbeat sur l'integration WSL, propages a la moelle sur transition."""
    stats = _evaluer_integration_wsl(version)
    _signaler_moelle(stats)
    return stats


def _evaluer_integration_wsl(version: str | None = None) -> dict:
    """PREVENTIF puis CURATIF (voir plus haut). Preventif (owner 13/10, « plus reactif ») : la mise a jour se VOIT
    avant la panne -- la version du serveur change. Si ce n'est pas le keeper qui a relance Docker (son lancement
    fait deja wsl --shutdown), le cycle part AVANT que la distro ne casse : zero fenetre au lieu d'une."""
    maj = None
    if version:
        prec, prec_ts = _INTEGRATION.get("version"), _INTEGRATION.get("version_ts") or 0.0
        _INTEGRATION.update(version=version, version_ts=time.monotonic())
        if prec and prec != version and _STATE["last_boot_ok_ts"] <= prec_ts:
            maj = "%s -> %s" % (prec, version)
    if maj:
        stats0: dict = {"integration_wsl": "MISE_A_JOUR", "docker_mise_a_jour": maj}
        if not _docker_wanted():
            stats0["integration_wsl_action"] = "aucune : Docker n'est pas reclame"
            return stats0
        if _en_refractaire(stats0):
            return stats0
        return _cycle_integration(stats0, "mise a jour Docker %s : cycle PREVENTIF de l'integration WSL" % maj)
    n = _integration_wsl_cassee()
    if n is None:
        return {"integration_wsl": "ILLISIBLE"}
    if n == 0:
        _INTEGRATION["sans_effet_dit"] = False
        ajout = _INTEGRATION.get("dernier_ajout_ts") or 0.0
        if ajout > (_INTEGRATION.get("derniere_signature_ts") or 0.0) and time.time() - ajout > _INTEGRATION_PREUVE_S:
            return {"integration_wsl": "ok"}
        return {"integration_wsl": "INCONNU"}  # aucune panne lue, mais aucune preuve de sante non plus
    stats: dict = {"integration_wsl": "CASSEE", "integration_wsl_signatures": n}
    if not _docker_wanted():
        stats["integration_wsl_action"] = "aucune : Docker n'est pas reclame"
        return stats
    if _en_refractaire(stats):
        return stats
    return _cycle_integration(stats, "integration WSL cassee (%d signature(s) dans %s) : backend.sock invisible "
                              "depuis la distro" % (n, _INTEGRATION["fichier"]))


def main() -> int:
    global _iter, _consecutive_failures, _last_launch_ts
    # Ici et pas a l'import (4/11) : chaque importeur tenait ce fichier ouvert, la rotation echouait en WinError 32
    # et le journal s'est fige a 2 Mo. NR : test_keeper_journal_pas_a_l_import_nr.
    _journal_fichier()
    log.info("docker_keeper start tick=%.0fs heartbeat=%s", TICK_S, HEARTBEAT_PATH)
    # Initial probe
    _iter = 0
    while True:
        _iter += 1
        try:   # levier Qdrant (2/11) : independant de l'etat de Docker, jamais fatal pour la boucle
            _tick_vidage_qdrant(time.monotonic())
        except Exception as exc:  # noqa: BLE001
            log.warning("levier qdrant en echec : %s", exc)
        ok, info = _docker_ready()  # readiness = socket (docker ps), pas juste `docker info` (anti stale)
        if ok:
            _consecutive_failures = 0
            iok, ver = _docker_info_ok()
            # Docker tourne — quelqu'un le reclame-t-il encore ? La decision se
            # prend ICI, pas dans un minuteur : le tick ne fait qu'evaluer.
            relache = _tick_release_at(time.time()) or _maybe_release(time.monotonic())
            crawl4ai = None if relache else _demarrer_crawl4ai(time.monotonic())
            cache_wsl = None if relache else _tick_vidage_cache(time.monotonic())
            integ = _surveiller_integration_wsl(ver if iok else None)
            _write_heartbeat(
                # Sain = PROUVE sain sur tous ses champs : un moteur qui repond avec une integration WSL cassee
                # ne se declare plus « ok » en transportant sa panne (2026-10-13).
                "degraded" if integ.get("integration_wsl") == "CASSEE" else "ok",
                {
                    "daemon_up": True,
                    "server_version": ver if iok else "ready",
                    "consecutive_failures": 0,
                    **({"released": relache} if relache else {}),
                    **({"crawl4ai": crawl4ai} if crawl4ai else {}),
                    **({"cache_wsl": cache_wsl} if cache_wsl else {}),
                    **integ,
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
                _annuler_release_at("daemon deja arrete : rien a differer")
                # 3/11 : « down par design » supposait TOUT eteint ; Desktop + VM WSL peuvent survivre au moteur.
                try:
                    if _tick_carcasse(now):
                        stats["carcasse_relachee"] = True
                except Exception as exc:  # noqa: BLE001
                    log.warning("relache carcasse en echec : %s", exc)
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
