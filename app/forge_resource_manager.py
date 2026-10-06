"""
forge_resource_manager — System resource monitor + dynamic allocator for Nokido.

Was : ports + docker check.
Then : RAM / CPU / GPU / disk + ports + docker, non-blocking via background thread.
Now : + dynamic allocation/eviction for the 2 cervelet engines (Ollama :11434
      + llama-server NSSM `NokidoLlamaNative` :8091) + Docker pause/unpause +
      smart `request_resources()` allocator + `brain_pick()` endpoint router.

Design constraints :
- ZERO blocking on read paths (TUI, Hub handlers, prompts) — sampler runs in
  daemon thread, snapshot dict is lock-free read of the latest values.
- LAZY init — sampler thread starts on first .get_snapshot() call, never on
  module import. CLI users / tests pay nothing.
- BEST-EFFORT GPU — uses Win32 perf counters on Windows (no nvml/rocm hard
  deps). Returns None if unavailable, never crashes.
- ALL new functions : timeout 3s max, never raise, return safe defaults on
  error. Heavy libs (urllib, json) imported lazily inside the function bodies.
- PUBLIC API — `get_snapshot()`, `should_throttle()`, `summary_line()`,
  `start_sampler()`, `stop_sampler()` + legacy `is_port_open()`,
  `is_docker_running()`, `check_resources()`, `start_ollama()` +
  NEW: `docker_status()`, `docker_pause_all()`, `docker_unpause_all()`,
  `ollama_loaded_models()`, `ollama_unload()`, `llamacpp_native_status()`,
  `llamacpp_native_stop()`, `llamacpp_native_start()`, `request_resources()`,
  `brain_pick()`.

Usage in Nokido code :
    from forge_resource_manager import get_snapshot, should_throttle, request_resources
    if should_throttle():
        # defer the spawn / inference
        ...
    plan = request_resources(needed_ram_gb=8.0, allow_evict=True)
    if not plan["ok"]:
        ...  # not enough RAM even after eviction

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `attribuer_pression` — Qui porte la memoire ENGAGEE : SOI (le corps), NON_SOI (le reste de la machine), NOYAU.
- `decider_demande_deleguee` — Decision de `POST /api/resource/request` : (statut HTTP, corps JSON, en-tetes).
- `resume_attribution` — Une ligne lisible pour un journal ou le message THROTTLED du gate P1.
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from nokido_agent.app.forge_secrets import get_secret

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

try:
    import psutil  # type: ignore

    _PSUTIL_OK = True
except ImportError:  # pragma: no cover
    _PSUTIL_OK = False


# ─────────────────────────────────────────────────────────────────────────────
# Background sampler — lock-free read snapshot
# ─────────────────────────────────────────────────────────────────────────────

# Shared snapshot dict. Single writer (sampler thread), many readers (lock-free).
_SNAPSHOT: dict[str, Any] = {
    "ts": 0.0,
    "ram_pct": 0.0,
    "ram_used_gb": 0.0,
    "ram_total_gb": 0.0,
    "ram_free_gb": 0.0,
    "cpu_pct": 0.0,
    "disk_pct": 0.0,
    "gpu_pct": None,
    "top_procs": [],
    # TDR (Timeout Detection and Recovery) — driver GPU AMD/Nvidia ne repond
    # plus, Windows recupere. Compteur events 4101 provider 'Display' dans la
    # derniere fenetre TDR_WINDOW_MIN. RCA 2026-05-24 BSOD 0x119 :
    # 15 TDR en 5min ont precede le BSOD. >= 1 TDR < 5min => quarantine GPU.
    "tdr_recent": 0,
    "tdr_last_check_ts": 0.0,
}

_SAMPLER_THREAD: threading.Thread | None = None
_SAMPLER_STOP = threading.Event()
_SAMPLE_INTERVAL_S = 3.0
# Seuil VITAL sous lequel plus AUCUNE protection (meme cognitive) ne tient :
# en dessous, l'OOM est plus proche que la fin de la pensee en cours.
_EVICT_SEUIL_VITAL_GB = float(os.environ.get("LAFORGE_EVICT_SEUIL_VITAL_GB", "1.0"))
_TDR_CHECK_INTERVAL_S = 60.0
_TDR_WINDOW_MIN = 5
_last_tdr_check_ts: float = 0.0
# top_procs echantillonne 1x/30s et NON a chaque tick (3s) — cf _sample_once.
_TOP_PROCS_INTERVAL_S = 30.0
_last_top_procs_ts: float = 0.0
# GPU : throttle 1x/min, MEME idiome que TDR. Cf la mesure dans _sample_once.
_GPU_CHECK_INTERVAL_S = float(os.environ.get("LAFORGE_GPU_SAMPLE_INTERVAL_S", "60"))
_last_gpu_check_ts: float = 0.0
_gpu_consecutive_fail = 0
_GPU_FAIL_BACKOFF = 5  # echecs d'affilee avant de suspendre la sonde 10 min
_gpu_suspended_until_ts: float = 0.0

# ── Historique des vitaux hote (RCA gel systeme 2026-07-26 11:38:50) ─────────
# resource_state.json est ECRASE a chaque echantillon : au moment ou la machine
# est morte, il n'existait donc AUCUNE courbe RAM/CPU/GPU. L'enquete a pu dater
# la mort a la seconde (dernier write disque 11:38:50) mais pas dire ce que la
# machine encaissait. Un instantane ne refute jamais un fait temporel — seul un
# LOG le peut. On garde donc une serie bornee, en append, qui SURVIT au reboot.
# Bornee par TAILLE et non par nombre de lignes : c'est la seule borne qui tient
# si la cadence change.
_VITALS_HISTORY_PATH = Path(__file__).resolve().parent.parent / "sandbox" / "vitals_history.jsonl"
_VITALS_HISTORY_INTERVAL_S = float(os.environ.get("LAFORGE_VITALS_HISTORY_INTERVAL_S", "15"))
# Plafond RECALCULE le 2026-08-05 avec l'elargissement du vecteur de capteurs.
# Arithmetique, pas au doigt mouille : la ligne passe de 274 a ~680 octets (12
# scalaires + la carte des services). A 8 Mio, la profondeur tombait de 5,75 j a
# ~2,3 j -- or les bancs neuromorphiques travaillent sur 9 jours de vitals. A
# 32 Mio la serie couvre ~11 j pleins entre deux rotations, pour 32 Mio de disque
# sur 169,9 Gio libres. On paie du disque pour ne pas perdre de la MEMOIRE.
_VITALS_HISTORY_MAX_BYTES = int(os.environ.get("LAFORGE_VITALS_HISTORY_MAX_BYTES", str(32 * 1024 * 1024)))
# Derniers canaux vus. Sert UNIQUEMENT a journaliser les TRANSITIONS : la serie
# s'ecrit 4x/minute, un log a chaque tick noierait le signal. On parle quand
# l'ensemble des canaux CHANGE -- apparition, disparition -- et on dit alors ce
# que ca signifie, pas un code a dechiffrer.
_CANAUX_VUS: frozenset = frozenset()
_last_vitals_write_ts: float = 0.0
# Horodatage d'amorce du sampler LOCAL : publie avec l'instantane pour que le
# proprietaire soit identifiable sans deviner (cf _dump_snapshot_json).
_SAMPLER_STARTED_TS: float = 0.0

# File-broker fallback: dump _SNAPSHOT to disk each tick so the Deno supervisor
# (or any external process) can read resource state without HTTP round-trip if
# the hub :8766 is down. Phase 2 couplage supervisor↔resource_manager.
_SNAPSHOT_JSON_PATH = Path(__file__).resolve().parent.parent / "sandbox" / "resource_state.json"


def _dump_snapshot_json() -> None:
    """Publie l'instantane EN SE NOMMANT.

    Manque comble le 2026-07-30 : l'etat publie ne disait pas QUI l'ecrivait, alors
    que l'architecture impose UN SEUL proprietaire d'echantillonneur et que
    `LAFORGE_SAMPLER_AUTOSTART` n'est declare nulle part — la propriete etait donc
    decidee par un repli implicite et restait indeterminable. Consequence concrete :
    impossible de savoir si l'eviction automatique a 75 % tourne dans le process qui
    detient les caches reclamables, donc impossible de garantir qu'elle a un levier.
    Un capteur qui publie sans signer force a deviner ; il signe desormais.
    """
    import json as _json

    try:
        _SNAPSHOT_JSON_PATH.parent.mkdir(exist_ok=True)
        _proc = "?"
        try:
            import psutil as _ps

            _proc = _ps.Process(os.getpid()).name()
        except Exception as e:  # noqa: BLE001
            _proc = f"?({type(e).__name__})"
        _paye = dict(_SNAPSHOT)
        _paye["sampler"] = {
            "pid": os.getpid(),
            "proc": _proc,
            "since": _SAMPLER_STARTED_TS or None,
            "reclaimers": sorted(_RECLAIMERS),
        }
        _SNAPSHOT_JSON_PATH.write_text(_json.dumps(_paye, default=str), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).debug("publication de l'instantane impossible: %s", e)
    # L'instantane est ECRASE ; la serie, elle, survit au reboot. Cf _append_vitals_history.
    _append_vitals_history(_SNAPSHOT)


def _append_vitals_history(snap: dict) -> None:
    """Append une ligne compacte de vitaux a la serie bornee. Ne leve JAMAIS.

    Pourquoi une serie et pas seulement l'instantane : le 2026-07-26 a 11:38:50
    la machine s'est arretee sans bugcheck ni dump, et Nokido tenait sa cadence
    a la seconde pres. Sans historique, impossible de dire si elle etouffait ou
    si elle a ete coupee net. C'est ce trou que ce fichier ferme.

    Rotation par TAILLE : au-dela de _VITALS_HISTORY_MAX_BYTES on garde la
    MOITIE la plus RECENTE. On ne tronque jamais a zero — un post-mortem a
    besoin des dernieres minutes, pas d'un fichier vide.
    """
    # `_json` n'est PAS un global de ce module : il est importe localement par les
    # fonctions qui s'en servent. Mesure du 26-07 : sans cet import, le corps levait
    # un NameError avale par l'except ci-dessous -> serie muette, et un rc « ok »
    # de governed_edit ne l'aurait jamais dit. Un journal qui echoue en silence est
    # le defaut que ce journal existe pour corriger.
    import json as _json

    global _last_vitals_write_ts
    now = snap.get("ts") or time.time()
    if now - _last_vitals_write_ts < _VITALS_HISTORY_INTERVAL_S:
        return
    _last_vitals_write_ts = now
    try:
        row = {
            "ts": round(float(now), 1),
            "ram_pct": snap.get("ram_pct"),
            "ram_used_gb": snap.get("ram_used_gb"),
            "ram_free_gb": snap.get("ram_free_gb"),
            "cpu_pct": snap.get("cpu_pct"),
            "disk_pct": snap.get("disk_pct"),
            "gpu_pct": snap.get("gpu_pct"),
            "tdr_recent": snap.get("tdr_recent"),
        }
        top = snap.get("top_procs") or []
        if top:
            # 3 premiers seulement : nommer le glouton suffit, la serie doit rester legere.
            row["top"] = [{"n": t.get("name"), "g": t.get("ram_gb")} for t in top[:3]]
        # ELARGISSEMENT DU VECTEUR DE CAPTEURS (2026-08-05). Jusqu'ici la serie ne
        # portait que des scalaires GLOBAUX, et quatre bancs neuromorphiques ont
        # perdu contre `if ram > 85` sur ce vecteur : le verdict portait sur le
        # SIGNAL. Les canaux ajoutes ici sont ceux qu'une campagne de mesure a
        # juges LISIBLES, VARIABLES et BON MARCHE (~21 ms cumules, cf.
        # tools/forge_vitals_channel_probe.py). Les groupes chers ou de dimension
        # journaliere restent au palier `sonde`, hors de cette boucle.
        _canaux = {}
        try:
            from nokido_agent.app.forge_vitals_channels import echantillon as _canaux_echantillon

            _canaux = _canaux_echantillon("serie")
            row.update(_canaux)
        except Exception as _ce:  # noqa: BLE001
            # Un capteur qui casse le journal serait pire que le trou qu'il laisse,
            # mais un echec MUET rendrait le capteur indistinguable d'un capteur
            # eteint -- c'est le defaut qu'on vient de corriger ailleurs.
            logging.getLogger(__name__).warning(
                "[vitals] canaux elargis INDISPONIBLES (%s: %s) -- la serie continue "
                "avec les seuls scalaires globaux ; les bancs multi-canaux n'auront "
                "rien a apprendre tant que ce message revient",
                type(_ce).__name__, _ce)
        global _CANAUX_VUS
        _vus = frozenset(_canaux)
        if _vus != _CANAUX_VUS:
            _apparus = sorted(_vus - _CANAUX_VUS)
            _disparus = sorted(_CANAUX_VUS - _vus)
            logging.getLogger(__name__).info(
                "[vitals] vecteur de capteurs = %d canaux%s%s | serie=%s cadence=%.0fs "
                "plafond=%.0fMio | signification des cles : forge_vitals_channels.SCHEMA",
                len(_vus),
                (" | APPARUS: " + ", ".join(_apparus)) if _apparus else "",
                (" | DISPARUS (mesure perdue, PAS une valeur nulle): "
                 + ", ".join(_disparus)) if _disparus else "",
                _VITALS_HISTORY_PATH.name, _VITALS_HISTORY_INTERVAL_S,
                _VITALS_HISTORY_MAX_BYTES / 1048576.0)
            _CANAUX_VUS = _vus
        _ecrire_jsonl(_VITALS_HISTORY_PATH, row, _VITALS_HISTORY_MAX_BYTES)
    except Exception:  # noqa: BLE001 - un journal qui casse son appelant serait pire
        pass


def _ecrire_jsonl(chemin, row: dict, max_bytes: int) -> None:
    """Ajoute une ligne JSON, rotation par TAILLE en gardant la moitie RECENTE.

    Extrait de l'ecriture de la serie vitale pour servir aussi le journal de
    decision (A0-4b). Deux copies de cette boucle auraient ete deux politiques de
    rotation a maintenir -- et le cliquet de duplication de la CI l'aurait refuse.
    On ne tronque JAMAIS a zero : un post-mortem a besoin des dernieres minutes.
    """
    import json as _json

    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(row, ensure_ascii=False) + "\n")
    if chemin.stat().st_size > max_bytes:
        lines = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
        chemin.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")


# --- A0-4b : journal de DECISION, surface distincte de la serie physiologique ---
#
# SEPARE de `vitals_history.jsonl`, et ce n'est pas un detail de rangement : la
# mesure du 2026-09-05 a montre que l'etat physiologique et les entrees de la
# decision ne sont pas la meme surface. Le journal vital porte 50 canaux et
# AUCUNE des onze entrees de `arbitrer_pression` -- d'ou l'impossibilite de
# reconstruire une baseline a posteriori. Les melanger aurait aussi melange leurs
# denominateurs, et « 0 arbitrage » se serait lu « 0 opportunite ».
#
# STRICTEMENT OBSERVATIONNEL : ce journal n'influence aucune decision, il
# l'enregistre. Il consigne AUSSI les ticks ou l'arbitre n'a pas ete appele
# (`saut`) -- sans eux, `ticks_decision_observes` n'aurait pas de denominateur et
# l'absence d'arbitrage serait indistinguable d'une absence d'occasion.
_DECISIONS_PATH = Path(__file__).resolve().parent.parent / "sandbox" / "decision_observations.jsonl"
_DECISIONS_MAX_BYTES = int(os.environ.get("LAFORGE_DECISIONS_MAX_BYTES", str(16 * 1024 * 1024)))
_POLICY_ID_CACHE: str = ""


def _policy_id() -> str:
    """`arbitrer_pression/current@<sha7>` — jamais `rules_v1`.

    MESURE 2026-09-05 : `forge_regulation_proposer.POLITIQUES["rules_v1"]` declare
    `evict=75 / wake=65`. Le code reel n'a ni l'un ni l'autre (seuil 78,0 ; urgence
    2,5 Go / 15 % ; vital 1,0 Go ; detresse 1,5 Go) et `wake` n'existe pas comme
    seuil. Les 24 episodes du ledger etiquetent pourtant `politique: rules_v1` sans
    qu'aucune action n'y soit observee : l'etiquette fabriquait une causalite.
    Un identifiant ancre sur le COMMIT laisse la politique evoluer sans reecrire
    l'histoire ; un sha illisible rend `@inconnu`, jamais un faux sha.
    """
    global _POLICY_ID_CACHE
    if _POLICY_ID_CACHE:
        return _POLICY_ID_CACHE
    sha = "inconnu"
    try:
        g = Path(__file__).resolve().parent.parent / ".git"
        tete = (g / "HEAD").read_text(encoding="utf-8").strip()
        if tete.startswith("ref: "):
            ref = g / tete[5:]
            sha = ref.read_text(encoding="utf-8").strip()[:7] if ref.exists() else "inconnu"
        elif tete:
            sha = tete[:7]
    except Exception as _e:  # noqa: BLE001
        # `logging` importe LOCALEMENT : ce module n'expose pas de `logger` global.
        # Attrape par le NR le 2026-09-05 -- le gestionnaire d'erreur levait un
        # NameError, donc le garde cassait la regulation qu'il devait proteger.
        import logging as _lg

        _lg.getLogger(__name__).debug(
            "[decisions] sha illisible (%r) -- policy_id restera @inconnu", _e)
    _POLICY_ID_CACHE = "arbitrer_pression/current@%s" % sha
    return _POLICY_ID_CACHE


def observer_decision(entrees: dict | None = None, decision: dict | None = None,
                      saut: str = "", coder_verdict: str = "") -> None:
    """Consigne UNE invocation d'arbitrage. Ne leve jamais, ne decide jamais.

    `saut` non vide = l'arbitre n'a PAS ete appele a ce tick (cooldown, arbitrage
    desactive) ; c'est le denominateur de `ticks_decision_observes`.

    `coder_verdict` porte le verdict COMPOSITE d'origine : `arbitrer_pression`
    recoit un booleen, donc l'etat INCERTAIN est deja perdu quand elle decide. Le
    seul endroit qui sait encore que la preuve etait partielle est l'appelant --
    sans ce parametre, un `coder_up: false` du journal melangerait « mort » et
    « pas su », soit precisement la confusion que ce journal existe pour empecher.
    """
    try:
        row: dict = {"ts": round(time.time(), 1), "policy_id": _policy_id()}
        if saut:
            row["saut"] = saut
            _ecrire_jsonl(_DECISIONS_PATH, row, _DECISIONS_MAX_BYTES)
            return
        d = decision or {}
        inconnues = list(d.get("inconnues") or [])
        if coder_verdict and coder_verdict not in ("VIVANT", "MORT"):
            inconnues.append("coder_up")
            row["coder_verdict"] = coder_verdict
        row["inputs"] = dict(entrees or {})
        row["derive"] = d.get("derive")
        row["inconnues"] = inconnues
        row["output"] = {"action": d.get("action"), "strategie": d.get("strategie"),
                         "raison": d.get("raison")}
        _ecrire_jsonl(_DECISIONS_PATH, row, _DECISIONS_MAX_BYTES)
    except Exception as _e:  # noqa: BLE001
        # Un journal qui casse la regulation serait pire que le trou qu'il laisse,
        # mais un echec MUET rendrait le journal indistinguable d'un arbitre qui
        # ne tourne pas -- exactement le doute qu'on vient de payer.
        #
        # `logging` importe ICI, jamais un `logger` global suppose : le NR a
        # mesure le 2026-09-05 qu'un NameError dans CE bloc transformait une
        # panne d'ecriture benigne en arret de la regulation. Meme famille que
        # le heartbeat mort 12 h sur un `import os` manquant (2026-09-03).
        import logging as _lg

        _lg.getLogger(__name__).debug("[decisions] ecriture impossible (%r)", _e)


# Dernier echantillonnage du capteur de derive memoire par service (cf. la boucle
# du sampler). Module-level : le thread du sampler est unique.
_RSS_WATCH_DERNIER = 0.0


def read_vitals_history(since_ts: float = 0.0, limit: int = 400) -> list[dict]:
    """Derniers vitaux enregistres, du plus ancien au plus recent.

    Consommateur premier : le post-mortem au boot (forge_reboot_sentinel), qui
    joint cette courbe a un arret sale. Retourne [] si la serie n'existe pas
    encore — un appelant ne doit jamais distinguer « pas de donnee » d'une
    erreur en plantant.
    """
    import json as _json  # idem : import local, cf _append_vitals_history

    if not _VITALS_HISTORY_PATH.exists():
        return []
    out: list[dict] = []
    try:
        for line in _VITALS_HISTORY_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = _json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if float(row.get("ts") or 0) >= since_ts:
                out.append(row)
    except OSError:
        return out
    return out[-limit:]


def _sample_gpu_win32() -> float | None:
    """Best-effort GPU usage via Windows perf counters. None if unavailable.

    Reads `\\GPU Engine(*engtype_3D)\\Utilization Percentage` via PowerShell
    Get-Counter. Sums all engines. Returns None on any failure.
    """
    if sys.platform != "win32":
        return None
    try:
        ps = (
            'Get-Counter "\\GPU Engine(*engtype_3D)\\Utilization Percentage" '
            "-MaxSamples 1 -ErrorAction SilentlyContinue | "
            "Select-Object -ExpandProperty CounterSamples | "
            "Measure-Object CookedValue -Sum | "
            "Select-Object -ExpandProperty Sum"
        )
        # errors= seul, SANS forcer l'encodage : la sortie PowerShell est localisee
        # (cp1252 ici) et imposer utf-8 changerait le codec d'un capteur qui marche.
        # On ajoute la tolerance, pas un nouveau decodeur.
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True, errors="replace",
            timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = result.stdout.strip()
        if not out:
            return None
        val = float(out.replace(",", "."))
        # Cap at 100 (multi-engine sum can overflow on multi-GPU)
        return min(val, 100.0)
    except Exception:
        return None


def _sample_tdr_recent_win32(window_min: int = 5) -> int:
    """Count GPU TDR events (Display driver recovery) in last window_min.

    Filters System log Event ID 4101 (provider 'Display') = "Display driver
    stopped responding and has recovered". RCA 2026-05-24 : 15 LiveKernelEvent
    0x141 ont precede BSOD VIDEO_SCHEDULER. Detecter pour quarantine GPU.

    Best-effort. Returns 0 on any failure (Linux/macOS, no perm, timeout).
    Coute ~300ms PowerShell spawn => appel max 1x/min via cache _last_tdr_check_ts.
    """
    if sys.platform != "win32":
        return 0
    try:
        ps = (
            f"(Get-WinEvent -FilterHashtable @{{LogName='System';"
            f"ProviderName='Display';StartTime=(Get-Date).AddMinutes(-{window_min})}} "
            f"-ErrorAction SilentlyContinue | Where-Object {{$_.Id -eq 4101}} | "
            f"Measure-Object).Count"
        )
        # idem : tolerance au decodage sans toucher au codec. Un journal Windows en
        # francais rendrait sinon la sonde TDR muette, et « 0 evenement » se lirait
        # « tout va bien » a tort.
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True, errors="replace",
            timeout=4,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = result.stdout.strip()
        if not out:
            return 0
        return int(out)
    except Exception:
        return 0


def _sample_top_procs(n: int = 5) -> list[dict]:
    """Top N processes by RSS. Best-effort, never raises."""
    if not _PSUTIL_OK:
        return []
    try:
        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                rss = p.info["memory_info"].rss
                procs.append((rss, p.info["pid"], p.info["name"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
        procs.sort(reverse=True)
        return [{"pid": pid, "name": name, "ram_gb": round(rss / 1024**3, 2)} for rss, pid, name in procs[:n]]
    except Exception:
        return []


# ── Attribution de la pression : SOI / NON_SOI / NOYAU (owner 2026-09-27) ──────────────
# Mesure du 27/09 : RAM a 83 % des le full stack, `request_resources` rendait `['noop']`
# et le gate P1 citait le top RSS -- sans jamais dire que la pression ne venait PAS du
# corps : deux services Windows hors Nokido fuyaient des handles (mtkbtsvc 16,7 M,
# audiodg 2,1 M) et le pool noyau portait la difference. Un regulateur qui ne distingue
# pas soi de non-soi evince ses propres organes pour une fuite qu'il ne peut atteindre.
# SOI ne se DEDUIT pas d'un nom : il se DEMANDE au registre du superviseur (pids des
# services et leurs descendants). Registre muet -> INCERTAIN, jamais NON_SOI ; lanceur
# d'un organe -> incertain (ni prouve soi, ni etranger) ; illisible -> COMPTE, pas range.
_ATTRIB_TTL_S = 60.0
_ATTRIB_CACHE: dict = {"ts": 0.0, "val": None}
_ATTRIB_DERNIER_AUDIT_TS = 0.0


def _perf_systeme() -> dict | None:
    """Pool noyau + handles SYSTEME (K32GetPerformanceInfo, sans droit admin). None = illisible."""
    try:
        import ctypes
        from ctypes import wintypes

        class _PI(ctypes.Structure):
            _fields_ = ([("cb", wintypes.DWORD)]
                        + [(n, ctypes.c_size_t) for n in (
                            "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal",
                            "PhysicalAvailable", "SystemCache", "KernelTotal", "KernelPaged",
                            "KernelNonpaged", "PageSize")]
                        + [(n, wintypes.DWORD) for n in ("HandleCount", "ProcessCount", "ThreadCount")])

        pi = _PI()
        pi.cb = ctypes.sizeof(pi)
        if not ctypes.windll.kernel32.K32GetPerformanceInfo(ctypes.byref(pi), pi.cb):
            return None
        pg = pi.PageSize / 1024 ** 3
        return {"noyau_pagine_gb": round(pi.KernelPaged * pg, 2),
                "noyau_non_pagine_gb": round(pi.KernelNonpaged * pg, 2),
                "handles_systeme": int(pi.HandleCount)}
    except Exception:  # noqa: BLE001 - muet-ok : hors Windows -> None, l'appelant le DIT
        return None


def attribuer_pression(force: bool = False) -> dict:
    """Qui porte la memoire ENGAGEE : SOI (le corps), NON_SOI (le reste de la machine), NOYAU.

    Diagnostic seulement, AUCUNE action. Memoire PRIVEE et non RSS (meme grandeur que
    `_heavy_evictable_services` : le working set se rogne, un gourmand pagine paraissait
    petit). Verdict = part dominante, INCERTAIN si la part incertaine suffit a le renverser
    ou si le registre est muet. Cache 60 s : appele sur le chemin d'echec de l'eviction."""
    now = time.time()
    if not force and _ATTRIB_CACHE["val"] is not None and now - _ATTRIB_CACHE["ts"] < _ATTRIB_TTL_S:
        return _ATTRIB_CACHE["val"]
    out: dict = {"verdict": "INCERTAIN", "soi_gb": 0.0, "non_soi_gb": 0.0, "incertain_gb": 0.0,
                 "illisibles": 0, "top_non_soi": [], "top_handles": [], "raison": "",
                 "mesure_ts": now}
    out.update(_perf_systeme() or {})
    if not _PSUTIL_OK:
        out["raison"] = "psutil indisponible"
        return out
    try:
        from nokido_agent.app.forge_service_rss_watch import _registre

        corps = {int(p) for p in (_registre() or {}).values()}
    except Exception as e:  # noqa: BLE001
        corps = set()
        out["raison"] = "registre illisible: %s" % type(e).__name__
    procs = {}
    for p in psutil.process_iter(["pid", "ppid", "name"]):
        procs[p.info["pid"]] = p
    parent = {pid: p.info.get("ppid") for pid, p in procs.items()}
    lanceurs = {parent.get(pid) for pid in corps} - {None}

    def _du_corps(pid: int) -> bool:
        vus, cur = set(), pid
        for _ in range(8):
            if cur in corps:
                return True
            if cur in vus or cur is None:
                return False
            vus.add(cur)
            cur = parent.get(cur)
        return False

    parts = {"soi": 0.0, "non_soi": 0.0, "incertain": 0.0}
    non_soi, handles = [], []
    for pid, p in procs.items():
        nom = p.info.get("name") or "?"
        try:
            mi = p.memory_info()
            prive = float(getattr(mi, "private", None) or mi.rss) / 1024 ** 3
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            out["illisibles"] += 1
            continue
        if not corps or pid in lanceurs:
            classe = "incertain"
        elif _du_corps(pid):
            classe = "soi"
        else:
            classe = "non_soi"
            non_soi.append((prive, pid, nom))
        parts[classe] += prive
        try:
            handles.append((p.num_handles(), pid, nom, classe))
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            pass  # muet-ok : les illisibles de handles ne changent pas le verdict memoire
    for k, v in parts.items():
        out[k + "_gb"] = round(v, 2)
    non_soi.sort(reverse=True)
    handles.sort(reverse=True)
    out["top_non_soi"] = [{"name": n, "pid": pid, "gb": round(g, 2)} for g, pid, n in non_soi[:3]]
    out["top_handles"] = [{"name": n, "pid": pid, "handles": h, "classe": c}
                          for h, pid, n, c in handles[:3]]
    if not corps:
        out["raison"] = out["raison"] or "registre superviseur muet : soi non prouvable"
    else:
        noyau = float(out.get("noyau_pagine_gb", 0.0)) + float(out.get("noyau_non_pagine_gb", 0.0))
        rang = sorted({"SOI": parts["soi"], "NON_SOI": parts["non_soi"], "NOYAU": noyau}.items(),
                      key=lambda kv: kv[1], reverse=True)
        if rang[0][1] - rang[1][1] <= parts["incertain"]:
            out["raison"] = "la part incertaine (%.1f Go) suffit a renverser %s" % (
                parts["incertain"], rang[0][0])
        else:
            out["verdict"] = rang[0][0]
            out["raison"] = "part dominante de la memoire engagee lisible"
    _ATTRIB_CACHE.update(ts=now, val=out)
    return out


def resume_attribution(a: dict | None) -> str:
    """Une ligne lisible pour un journal ou le message THROTTLED du gate P1."""
    if not a:
        return "attribution indisponible"
    s = "pression %s (soi %.1f / non-soi %.1f / incertain %.1f Go, %d illisibles" % (
        a.get("verdict"), a.get("soi_gb", 0), a.get("non_soi_gb", 0), a.get("incertain_gb", 0),
        a.get("illisibles", 0))
    if "noyau_non_pagine_gb" in a:
        s += ", noyau %.1f+%.1f Go, %s handles systeme" % (
            a["noyau_pagine_gb"], a["noyau_non_pagine_gb"], a.get("handles_systeme"))
    s += ")"
    if a.get("top_non_soi"):
        s += " | non-soi: " + ", ".join("%s %.1f Go" % (t["name"], t["gb"]) for t in a["top_non_soi"])
    if a.get("top_handles"):
        s += " | handles: " + ", ".join("%s %s" % (t["name"], t["handles"]) for t in a["top_handles"])
    return s


def _sample_once() -> dict[str, Any]:
    """Take one sample of all metrics. Single dict allocation, no shared state."""
    out: dict[str, Any] = {"ts": time.time()}
    if _PSUTIL_OK:
        try:
            vm = psutil.virtual_memory()
            out["ram_pct"] = round(vm.percent, 1)
            out["ram_used_gb"] = round(vm.used / 1024**3, 2)
            out["ram_total_gb"] = round(vm.total / 1024**3, 2)
            out["ram_free_gb"] = round(vm.available / 1024**3, 2)
        except Exception:
            pass
        try:
            # interval=None = non-blocking, returns last sample
            out["cpu_pct"] = round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            pass
        try:
            d = psutil.disk_usage(str(Path(__file__).anchor))
            out["disk_pct"] = round(d.percent, 1)
        except Exception:
            pass
    # GPU : throttle 1x/min + breaker. MESURE 2026-07-26 (Observateur d'evenements,
    # canaux PowerShell + WMI-Activity) : a la cadence de 3 s, ce capteur faisait
    # demarrer PUIS s'arreter un MOTEUR PowerShell complet toutes les ~4,7 s, soit
    # ~17 000 process par jour, avec trois effets de bord journalises par Windows :
    # PowerShell 600/400/403 en boucle, WMI-Activity 5857 (provider CIMWin32a), et
    # Diagnosis-PCW 16 « impossible de modifier le compteur » sur CIMWin32/nettcpip,
    # plus KnownFolders 1002 (0x80070002) a chaque spawn — le compte de service n'a
    # aucun dossier Documents a resoudre. Un capteur ne doit pas couter plus cher
    # que ce qu'il mesure : gpu_pct n'a AUCUN lecteur temps-reel a 3 s.
    global _last_gpu_check_ts, _gpu_consecutive_fail, _gpu_suspended_until_ts
    _now_gpu = time.time()
    if _now_gpu < _gpu_suspended_until_ts:
        out["gpu_pct"] = _SNAPSHOT.get("gpu_pct")
        out["gpu_sample_ms"] = _SNAPSHOT.get("gpu_sample_ms")
    elif _now_gpu - _last_gpu_check_ts >= _GPU_CHECK_INTERVAL_S:
        _last_gpu_check_ts = _now_gpu
        _t0 = time.perf_counter()
        _gpu = _sample_gpu_win32()
        # On PUBLIE le cout reel : une affirmation de cout qui ne se verifie pas
        # dans l'etat se re-oubliera, et c'est precisement ce qui est arrive ici.
        out["gpu_sample_ms"] = round((time.perf_counter() - _t0) * 1000.0, 1)
        if _gpu is None:
            _gpu_consecutive_fail += 1
            if _gpu_consecutive_fail >= _GPU_FAIL_BACKOFF:
                # Une sonde qui echoue en boucle paie le spawn sans rien rendre.
                _gpu_suspended_until_ts = _now_gpu + 600.0
                _gpu_consecutive_fail = 0
            out["gpu_pct"] = _SNAPSHOT.get("gpu_pct")
        else:
            _gpu_consecutive_fail = 0
            out["gpu_pct"] = _gpu
    else:
        out["gpu_pct"] = _SNAPSHOT.get("gpu_pct")
        out["gpu_sample_ms"] = _SNAPSHOT.get("gpu_sample_ms")
    # top_procs throttle a 1x/30s — MESURE 2026-07-16 : `_sample_top_procs` coute
    # 1373 ms et il est GIL-BOUND (psutil.process_iter sur ~300 process + lecture du
    # memory_info de chacun). A 3s de cadence, le sampler tenait donc le GIL ~1.3s
    # sur 3 = ~43% DU TEMPS, dans le process qui l'heberge — le hub. Soit une event
    # loop stallee pres d'une seconde sur deux : la famille de cause exacte des wedges
    # hub (loop_lag / doom-loop, « to_thread ne protege pas du GIL »).
    # IRONIE UTILE : le commentaire de `start_sampler` interdit de primer le sampler en
    # accusant le subprocess GPU de geler la boucle. Le glouton MESURE ici, c'est
    # process_iter — jamais soupconne. Le garde-fou etait bon, son diagnostic etait faux.
    # NUANCE AJOUTEE LE 2026-07-26, et c'est la meme lecon retournee contre nous : la
    # conclusion « _sample_gpu_win32 = 0.42 ms, HORS DE CAUSE » etait fausse aussi. Elle
    # reposait sur une sonde d'UNE seule dimension (un chronometre sur un retour court),
    # quand Windows journalisait, lui, un moteur PowerShell demarre/arrete toutes les
    # ~4,7 s. Deux capteurs, deux verites : celui qui porte la dimension TEMPS gagne.
    # D'ou le throttle GPU plus haut, et gpu_sample_ms publie pour trancher sans debat.
    # 30s est sans risque : top_procs n'a AUCUN consommateur temps-reel. Ses deux seuls
    # lecteurs (forge_sandbox_exec:139/153) s'en servent pour NOMMER le glouton dans un
    # message de REFUS de spawn — un process qui tient 4.5 GB ne s'evapore pas en 30s.
    # Zero lecteur cote Deno/TS. Meme idiome que le throttle TDR juste en dessous.
    global _last_top_procs_ts
    _now_tp = time.time()
    if _now_tp - _last_top_procs_ts >= _TOP_PROCS_INTERVAL_S:
        _last_top_procs_ts = _now_tp
        out["top_procs"] = _sample_top_procs(5)
    else:
        out["top_procs"] = _SNAPSHOT.get("top_procs", [])
    # TDR check throttle a 1x/min — PS spawn ~300ms, jamais a 3s.
    global _last_tdr_check_ts
    now = time.time()
    if now - _last_tdr_check_ts >= _TDR_CHECK_INTERVAL_S:
        _last_tdr_check_ts = now
        out["tdr_recent"] = _sample_tdr_recent_win32(_TDR_WINDOW_MIN)
        out["tdr_last_check_ts"] = now
    else:
        # Garde valeurs precedentes — _SNAPSHOT sera update preservant tdr_*.
        out["tdr_recent"] = _SNAPSHOT.get("tdr_recent", 0)
        out["tdr_last_check_ts"] = _SNAPSHOT.get("tdr_last_check_ts", 0.0)
    return out


# ACCORD DES SEUILS (2026-08-25, mesure). L'alarme et le bras capable d'agir etaient
# regles sur deux echelles differentes : le sampler declenche l'echelle d'eviction a
# 75 % de RAM, tandis que le seul palier qui atteint un gros service ne s'ouvre qu'a
# moins de 15 % de libre, soit environ 85 %. Sur 25 294 echantillons / 188,8 h :
# RAM >= 75 % pendant 26,1 % du temps, >= 85 % pendant 4,1 %. L'alarme sonnait donc
# six fois plus souvent que le bras ne pouvait repondre, et dans tout cet ecart le
# seul effecteur a portee endormait NokidoLlamaEmbed -- 9 fois en 7 jours, le pilier
# embedding, avec 4 reveils annonces en echec. Le corps payait en cognition une
# pression qu'il ne pouvait pas soulager autrement.
# On accorde l'alarme sur le palier DEJA declare juste en dessous du bras
# (_SUPERVISOR_SLEEP_RAM_THRESHOLD, 78) plutot que d'ouvrir le bras plus tot :
# ouvrir plus tot aurait MULTIPLIE les mises en sommeil de l'organe critique, soit
# exactement le degat mesure le 2026-07-24. Reglable sans toucher au code.
_AUTO_EVICT_RAM_THRESHOLD = float(os.environ.get("LAFORGE_AUTO_EVICT_RAM_PCT", "78.0"))
# Seuil d'URGENCE du palier par capacite. Ces deux nombres etaient ecrits en dur a
# DEUX endroits (_evict_conditions_met et la branche restart de pilier) : deux copies
# d'une meme politique divergent tot ou tard, et une politique qu'on ne peut pas
# regler se contourne au lieu de se corriger.
_EVICT_URGENCE_LIBRE_GB = float(os.environ.get("LAFORGE_EVICT_URGENCE_LIBRE_GB", "2.5"))
_EVICT_URGENCE_LIBRE_PCT = float(os.environ.get("LAFORGE_EVICT_URGENCE_LIBRE_PCT", "15.0"))
# Reveil d'un service : le POST /supervisor/wake ne repond qu'APRES avoir relance le
# service (delay 600 ms puis startService). Un llama-server qui recharge 2,9 Go
# depasse largement les 4 s d'attente d'origine, et l'attente ecourtee etait lue
# comme un refus. Cf _wake_service.
_WAKE_TIMEOUT_S = float(os.environ.get("LAFORGE_WAKE_TIMEOUT_S", "30"))
_WAKE_VERIFY_TRIES = int(os.environ.get("LAFORGE_WAKE_VERIFY_TRIES", "5"))
_WAKE_VERIFY_DELAY_S = float(os.environ.get("LAFORGE_WAKE_VERIFY_DELAY_S", "6"))
# PLANCHER DE 5 MINUTES — decision owner du 2026-08-03, en meme temps que l'armement
# du mode conditionne : aucun delai de regulation ne descend sous 300 s. Deux fois
# 120 s laissaient jusqu'a 30 tirs/h la ou le budget par gravite est de 6/h ; le
# plancher borne le debit AVANT que `forge_regulation_efficacy` n'ait a crier au
# pompage. Cf le motif « la moyenne all-time ment sur les rafales » (30/07).
_AUTO_EVICT_COOLDOWN_S = 300.0  # min seconds between auto-evictions (plancher 5 min)
_SUPERVISOR_SLEEP_RAM_THRESHOLD = 78.0  # % RAM above which supervisor non-essential services sleep
_SUPERVISOR_WAKE_RAM_THRESHOLD = 65.0  # % RAM below which sleeping services wake
_SUPERVISOR_URL = "http://127.0.0.1:8765/supervisor"
# Services to sleep when RAM pressure builds (ordered by MB desc, heaviest first)
_SUPERVISOR_NON_ESSENTIAL = [
    "NokidoBrainWorker",  # ~116 MB ZMQ embedder — restart on demand
    "NokidoIngestDaemon",  # batch ingestion, not real-time
    "NokidoAutonomousLoops",  # 60s patterns, tolerates sleep
    "NokidoGraph",  # graph explorer
    "NokidoHebbian",  # plasticity daemon
    "NokidoRSSWatcher",  # RSS feed watcher
    "NokidoCapture",  # cli tail
    "NokidoMultiLLMDaemon",  # multi-provider LLM router, demand-driven
    "NokidoNetcfgUI",  # netcfg web UI :7500
    # NokidoHomeostasis RETIRÉ 2026-07-05 (fix autorégulation) : c'est le RÉGULATEUR
    # (watchdog daemons + coagulation + health score). Le sleeper RAM le parquait dès
    # RAM>=78% (wake <65%) — donc slept sous pression EXACTEMENT quand la régulation est
    # requise : duty-cycle/flapping + tick incomplet (exit code=1) + watchdog HS =>
    # ingestion_pipeline stale jamais relancé. Le régulateur DOIT rester éveillé ; les 9
    # autres services + la hard-eviction (Ollama/llamacpp/Docker @75%, GBs) absorbent la
    # pression RAM. Coût = ~290MB torch résident. Voir memory organ-audit-autoregulation.
]
# Services to wake when RAM recovers (superset — includes core daemons that supervisor
# may have slept at high RAM but doesn't auto-wake on restart)
_SUPERVISOR_WAKE_ON_RECOVERY = _SUPERVISOR_NON_ESSENTIAL + [
    "NokidoDenoHubMCP",  # :8769 Deno MCP bridge
]


def _non_essential_sains() -> list[str]:
    """La liste ci-dessus, PRIVEE de tout service porteur d'une capacite critique.

    La liste est curatee a la main, donc figee : elle ne sait rien des services
    apparus depuis, et surtout rien de ce qu'ils PORTENT. Le 24-07, endormir par
    heuristique a coupe l'embedder, le reranker et la base vectorielle — les trois
    piliers du RAG — parce qu'aucune source ne disait quelle CAPACITE un service
    rend. Cette source existe depuis (`forge_service_capabilities`) : on l'oppose
    ici a la liste, en INTERSECTION et jamais en extension. Ajouter par erreur un
    organe critique a la liste ne suffit plus a l'endormir.

    Fail-safe : source indisponible -> la liste d'origine, comportement inchange.
    """
    try:
        from nokido_agent.app.forge_service_capabilities import is_critical, why_critical
    except Exception:  # noqa: BLE001 - jamais empecher la regulation de tourner
        return list(_SUPERVISOR_NON_ESSENTIAL)

    sains: list[str] = []
    for svc in _SUPERVISOR_NON_ESSENTIAL:
        try:
            critique = is_critical(svc)
        except Exception:  # noqa: BLE001 - verdict indisponible = on s'abstient
            critique = False
        if critique:
            try:
                _audit_lifecycle("sleep_skipped", "service", why_critical(svc), target=svc)
            except Exception:  # noqa: BLE001
                pass
            continue
        sains.append(svc)
    return sains
_last_evict_ts: float = 0.0

# RECUPERATEURS de RAM reclamable, enregistres par les modules qui la DETIENNENT.
# Pourquoi un registre et pas un appel direct : un cache vit dans le process qui
# l'a construit (celui du hub pour la matrice dense), et aucun autre process ne
# peut le liberer. Le module proprietaire s'inscrit ; l'echelle appelle sans
# savoir qui repond. Chaque fonction rend les Go REELLEMENT liberes, mesures, ou 0.
_RECLAIMERS: dict[str, object] = {}
# PERIODE REFRACTAIRE (avis biomimetique AGY, 2026-07-30). Sans elle, un cache rendu
# se reconstruit au prochain appel puis se fait rendre a nouveau : c'est le pompage
# oscillatoire, deja paye sur un autre organe (docker force-recycle sans refractaire,
# dent de scie a 135 s, 2026-07-26). La matiere biologique dit la meme chose : un
# glycogene mobilise ne se remobilise pas dans la seconde.
# On REUTILISE la convention de cooldown deja presente dans ce module
# (`_AUTO_EVICT_COOLDOWN_S` / `_last_evict_ts`) plutot que d'importer le `_can_act`
# de forge_auto_pilot, qui est une methode privee a etat en memoire d'une autre
# classe — meme roue, mauvais perimetre.
_RECLAIM_COOLDOWN_S = 300.0  # plancher 5 min (decision owner 2026-08-03)
# EXCEPTION AU PLANCHER, et la seule. Un refractaire protege du pompage en regime
# NORMAL ; il ne doit jamais empecher de sauver la machine. Mesure 2026-08-03 16:52 :
# RAM 99,0 % et 0,23 Go libre -- le niveau exact du gel du 02/08 ou dwm.exe est tombe --
# pendant que le refractaire de 300 s courait depuis 16:50:46. Resultat : AUCUN acte, pas
# meme un refus journalise, et le creux est passe tout seul. Meme raisonnement que
# « une intention n'est pas un droit absolu » (04a4ed00) : un refractaire non plus.
# 30 s et non 0 : le sampler tourne toutes les 3 s, sans borne il lancerait vingt
# threads d'eviction par minute -- on cederait au pompage en croyant l'eviter.
_DETRESSE_COOLDOWN_S = 30.0
_last_reclaim_ts: dict[str, float] = {}


def register_reclaimer(nom: str, fn) -> None:
    """Declare une RAM reclamable. `fn()` libere et rend les Go liberes (float).

    Idempotent : re-enregistrer le meme nom remplace, ce qui permet d'appeler
    depuis un chemin chaud sans accumuler de doublons.
    """
    _RECLAIMERS[str(nom)] = fn


def reclaimers_declares() -> list[str]:
    """Ce que le corps sait rendre sans arreter un organe. Vide = aucun levier."""
    return sorted(_RECLAIMERS)


def run_reclaimers(needed_gb: float = 0.0) -> dict:
    """Rend la RAM reclamable. AUCUN arret de service, donc sans garde cognitif.

    Appelable meme pendant un travail en cours : le garde « cognition active » qui
    protege l'eviction de services serait ici un contresens — endormir un organe
    casse ce qui l'utilise, rendre un cache reconstructible ne casse rien. Mesure
    2026-07-30 : ce garde faisait refuser des spawns a 86-90 % de RAM alors que
    2.3 Go de cache dense attendaient d'etre rendus.

    `needed_gb` = 0 -> rend tout ce qui est declare. Sinon on s'arrete des que la
    cible est atteinte, pour ne pas jeter un cache utile sans necessite.
    """
    actions: list[str] = []
    libere_total = 0.0
    # REFRACTAIRE ADAPTATIVE (avis AGY 2026-07-30, fragilite b). Le cooldown PLAT
    # traitait un cache rendu une fois et un cache rendu six fois de suite de la
    # meme facon. Le modele du corps existe deja et sait faire la difference :
    # `forge_regulation_loops.Loop.should_fire` = refractaire ABSOLUE infranchissable
    # (elle couvre le contrecoup du remede) + exigence d'urgence DECROISSANTE dans la
    # fenetre relative, cette derniere s'allongeant avec la recidive MESUREE par
    # `forge_regulation_efficacy`. On le CABLE, on ne le reecrit pas.
    # Le journal est lu UNE fois par appel et passe a chaque verdict : run_reclaimers
    # est sur un chemin chaud, une relecture par reclaimer serait une fuite d'I/O.
    _urgence = _urgence_ram()
    _verdict_fn = None
    _ev = None
    try:
        import sys as _sys
        _t = str(Path(__file__).resolve().parent.parent / "tools")
        if _t not in _sys.path:  # chemin CHAUD : un insert par appel gonflerait sys.path
            _sys.path.insert(0, _t)
        from nokido_agent.tools.forge_regulation_efficacy import journal as _lire_journal
        from nokido_agent.tools.forge_regulation_efficacy import refractaire_verdict as _verdict_fn
        _ev = _lire_journal()
    except Exception as _e:  # noqa: BLE001
        # Repli sur le cooldown plat : l'absence du capteur meta ne doit JAMAIS
        # empecher de rendre de la RAM. Mais elle se DIT, sinon on croit adaptatif
        # un palier qui ne l'est plus.
        actions.append(f"refractaire:plat(capteur meta absent: {type(_e).__name__})")
        _verdict_fn = None
    for nom, fn in list(_RECLAIMERS.items()):
        if needed_gb and _free_now() >= needed_gb:
            break
        # Refractaire : jamais en silence, sinon un cache saute son tour sans qu'on
        # sache pourquoi et le palier parait defaillant alors qu'il se protege.
        _depuis = time.time() - _last_reclaim_ts.get(nom, 0.0)
        if _verdict_fn is None:
            if _depuis < _RECLAIM_COOLDOWN_S:
                actions.append(
                    f"reclaim:{nom}:refractaire({int(_RECLAIM_COOLDOWN_S - _depuis)}s)")
                continue
        else:
            _v = _verdict_fn("reclaim", nom, _depuis, _RECLAIM_COOLDOWN_S,
                             urgence=_urgence, evenements=_ev)
            if not _v.get("fire"):
                actions.append(
                    "reclaim:%s:refractaire(%ds ecoules, relative %ds, recidive %s, %s)"
                    % (nom, int(_depuis), int(_v.get("relative_s") or 0),
                       _v.get("recidive", "?"), _v.get("reason", "")))
                continue
        try:
            libere = float(fn() or 0.0)
        except Exception as e:  # noqa: BLE001
            actions.append(f"reclaim:{nom}:echec({type(e).__name__})")
            continue
        if libere > 0:
            _last_reclaim_ts[nom] = time.time()
            libere_total += libere
            actions.append(f"reclaim:{nom}(~{round(libere, 2)}GB)")
            _audit_lifecycle("reclaim", "cache", "rendre un cache reconstructible",
                             target=nom, ram_gb=round(libere, 2))
    # `ok` ne vaut que si quelque chose a ete LIBERE : un refractaire n'est pas un
    # succes, et le faire passer pour tel autoriserait un spawn sans place faite.
    return {"ok": libere_total > 0, "action": actions or ["noop"],
            "freed_gb": round(libere_total, 2),
            "refractaire_absolue_s": _RECLAIM_COOLDOWN_S,
            "refractaire_adaptative": _verdict_fn is not None,
            "urgence_ram": None if _urgence is None else round(_urgence, 3),
            "declares": sorted(_RECLAIMERS)}
_last_supervisor_sleep_ts: float = 0.0
_last_supervisor_wake_ts: float = 0.0


def _supervisor_auth_headers() -> dict:
    """Phase 23A : supervisor Deno :8765 exige Bearer sur /supervisor/* mutations.
    Sans ce header, POST /sleep/<X> retournait 401 silencieux → brain_worker
    restait UP même au-dessus seuil RAM (bug critique observe 2026-05-25)."""
    import os as _os

    tok = _os.environ.get("LAFORGE_SUPERVISOR_TOKEN") or _os.environ.get("FORGE_MCP_TOKEN") or ""
    # 2026-09-24 : se NOMMER. Le superviseur journalise desormais l'appelant de chaque ordre
    # (sandbox/supervisor_ordres.jsonl) ; sans nom, les mises en sommeil du regulateur etaient
    # indiscernables de celles de n'importe quel porteur du jeton partage. Declare != prouve.
    h = {"LaForge-Agent-Name": "RESOURCE_MANAGER"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _supervisor_sleep_non_essential() -> None:
    """Ask supervisor to sleep non-essential services to free RAM."""
    try:
        import urllib.request as _ur

        _h = _supervisor_auth_headers()
        for svc in _non_essential_sains():
            try:
                req = _ur.Request(f"{_SUPERVISOR_URL}/sleep/{svc}", method="POST", headers=_h)
                with _ur.urlopen(req, timeout=3):
                    pass
            except Exception:
                pass
    except Exception:
        pass


def _supervisor_wake_non_essential() -> None:
    """Ask supervisor to wake sleeping services when RAM is comfortable."""
    try:
        import urllib.request as _ur

        _h = _supervisor_auth_headers()
        # Un service endormi par un BAIL DE PRIORITE actif n'est pas rendu par la RAM qui redescend :
        # la tache prioritaire en a encore besoin, et c'est sa liberation (ou son expiration) qui le rend.
        try:
            _tenus = services_tenus_par_un_bail()
        except Exception:  # noqa: BLE001 - registre des baux illisible : comportement d'avant
            _tenus = set()
        for svc in reversed(_SUPERVISOR_WAKE_ON_RECOVERY):
            if svc in _tenus:
                continue
            try:
                req = _ur.Request(f"{_SUPERVISOR_URL}/wake/{svc}", method="POST", headers=_h)
                with _ur.urlopen(req, timeout=3):
                    pass
            except Exception:
                pass
    except Exception:
        pass


def _urgence_ram(ram_pct: float | None = None) -> float | None:
    """Pression RAM normalisee 0..1 entre les consignes que le corps PUBLIE deja.

    UNE seule definition pour tout le module : la satiete endocrine (insuline) et
    l'urgence qui autorise a franchir une refractaire RELATIVE sont la MEME
    grandeur. Deux copies auraient derive, et c'est precisement le genre d'ecart
    qui fait qu'un organe freine quand l'autre accelere.

    Rend None si la mesure est illisible. « Je ne peux pas voir » n'est pas
    « pression nulle » : l'appelant doit pouvoir distinguer, sinon un capteur muet
    se lit comme un corps au repos.
    """
    bas, haut = _SUPERVISOR_WAKE_RAM_THRESHOLD, _SUPERVISOR_SLEEP_RAM_THRESHOLD
    if haut <= bas:
        return None
    if ram_pct is None:
        try:
            ram_pct = psutil.virtual_memory().percent
        except Exception:  # noqa: BLE001
            return None  # muet-ok : le None EST le signal, l'appelant sait qu'il est aveugle
    return max(0.0, min(1.0, (float(ram_pct) - bas) / (haut - bas)))


_INSULIN_HORMONE = "INSULIN_VECTORIZATION"
_INSULIN_COOLDOWN_S = 60.0
_last_insulin_ts: float = 0.0


def _secreter_insuline(ram_pct: float) -> None:
    """LA GLANDE MANQUANTE (avis biomimetique AGY, 2026-07-30).

    AGY demandait un signal de satiete GRADUE plutot qu'un watermark binaire. La
    mesure du meme jour a montre l'inverse d'un manque de conception : l'hormone est
    DECLAREE (`forge_hormones`), elle a DEUX recepteurs — dont le frein de batch de
    `forge_rag_warmup` (`INSULIN_VECTORIZATION > 0.4 -> batch_size / 2`) — mais elle
    lisait **0.0** en permanence : personne ne la secretait. Un recepteur sans glande
    est un frein qui ne freine jamais, et brancher un garde neuf sur un signal mort
    aurait donne un garde mort.

    Le niveau est DERIVE des consignes que le corps declare deja (_SUPERVISOR_WAKE
    65 % -> _SUPERVISOR_SLEEP 78 %), pas d'un seuil choisi ici : inventer un chiffre
    quand le systeme en publie un est le motif `seuil_invente` de RULES_SHARED.

    Emission bornee (60 s) : une hormone se dose, elle ne se hurle pas a chaque tick.
    Et on ne secrete PAS un ligand sans recepteur — sinon le signal se perd en silence.
    """
    global _last_insulin_ts
    bas, haut = _SUPERVISOR_WAKE_RAM_THRESHOLD, _SUPERVISOR_SLEEP_RAM_THRESHOLD
    niveau = _urgence_ram(ram_pct)
    if niveau is None:
        return
    if niveau <= 0.0:
        return  # satiete nulle : rien a dire, la demi-vie fait retomber le reste
    if (time.time() - _last_insulin_ts) < _INSULIN_COOLDOWN_S:
        return
    try:
        from nokido_agent.app.forge_endocrine import receptors, release

        if not receptors(_INSULIN_HORMONE):
            logging.getLogger(__name__).debug(
                "[insuline] %s sans recepteur declare — pas de secretion",
                _INSULIN_HORMONE)
            return
        release(
            _INSULIN_HORMONE,
            round(niveau, 3),
            source="forge_resource_manager._sampler_loop",
            reason=f"satiete ressources : RAM {ram_pct:.1f}% dans [{bas}, {haut}]",
            meta={"ram_pct": round(float(ram_pct), 1)},
        )
        _last_insulin_ts = time.time()
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).debug(
            "[insuline] secretion impossible (%s)", type(e).__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ARBITRAGE ADAPTATIF (biomimetique) — owner 2026-08-19 : « adaptatif selon
# l'effet recherche ». Le corps n'a pas UNE strategie d'allocation, il en change
# selon l'etat :
#   B_hyperemie     — etat interactif : l'organe qui TRAVAILLE garde sa place
#                     (le muscle actif recoit le sang). Defaut PROTECTEUR.
#   C_consolidation — repos : l'assimilation affamee (backlog RAG) prime, le
#                     coder OISIF cede la place (la memoire se consolide pendant
#                     le sommeil). Se declenche AU REPOS + coder a conns=0 seulement.
#   A_plancher      — hub + embedder-tant-que-backlog ne sont JAMAIS candidats ici.
# La DECISION est pure (arbitrer_pression, testable) ; l'ACTE reste les leviers
# existants (llamacpp_native_stop) + le keeper qui reveille :8099.
_ARBITRAGE_DERNIER = 0.0
_last_arbitrage_act_ts = 0.0
_ARBITRAGE_CADENCE_S = float(os.environ.get("LAFORGE_ARBITRAGE_CADENCE_S", "60"))
_ARBITRAGE_COOLDOWN_S = float(os.environ.get("LAFORGE_ARBITRAGE_COOLDOWN_S", "300"))
_EMBED_RAM_GB = float(os.environ.get("LAFORGE_EMBED_RAM_GB", "5.0"))
_BACKLOG_AFFAME = int(os.environ.get("LAFORGE_BACKLOG_AFFAME", "5000"))

# TOLERANCE A L'INACTIVITE, par rythme (2026-09-02). Le circadien choisit
# COMBIEN DE TEMPS on supporte qu'un organe ne serve personne -- il ne choisit
# plus s'il faut le proteger. Avant, `NORMAL` suffisait a rendre l'organe
# intouchable ; il dit pourtant seulement « le systeme est eveille », rien sur
# cet organe-la.
#
#   le rythme    -> combien de temps suis-je tolerant a l'inactivite ?
#   l'etat reel  -> cet organe travaille-t-il ?
#   la demande   -> quelqu'un en a-t-il besoin ?
#   l'homeostat  -> puis-je me permettre de le conserver ?
#
# Les valeurs sont un point de depart, pas une verite mesuree : ce qui compte
# ici est le DECOUPLAGE. Elles se regleront sur les traces de la phase de
# coexistence, une fois qu'on saura la duree reelle des demandes.
_GRACE_EVEILLE_S = float(os.environ.get("LAFORGE_GRACE_EVEILLE_S", "300"))
_GRACE_PAR_RYTHME = {
    "SOMMEIL": float(os.environ.get("LAFORGE_GRACE_SOMMEIL_S", "30")),
    "DEEP": float(os.environ.get("LAFORGE_GRACE_SOMMEIL_S", "30")),
    "CONSERVE": float(os.environ.get("LAFORGE_GRACE_CONSERVE_S", "120")),
    "REPOS": float(os.environ.get("LAFORGE_GRACE_CONSERVE_S", "120")),
}


def arbitrer_pression(
    rhythm: str,
    coder_up: bool,
    coder_conns: int,
    chains_active: int,
    embed_wanted: bool,
    backlog: int,
    embedder_up: bool,
    coder_ram_gb: float,
    free_gb: float,
    seuil_backlog: int = _BACKLOG_AFFAME,
    seuil_confort_gb: float = _EMBED_RAM_GB,
    demande_active: bool | None = None,
    inutile_s: float | None = None,
) -> dict[str, Any]:
    """Selecteur adaptatif : {etat} -> {strategie}. PUR, sans effet de bord.

    L'introspection fournit tout : rythme endocrinien (interactif/repos),
    connexions actives du coder, profondeur du backlog, place libre. La fonction
    ne CHOISIT pas un chiffre, elle lit ce que le corps mesure deja et rend une
    decision LISIBLE. Ne leve jamais.

    coder_conns < 0 = mesure MANQUANTE -> on PROTEGE (prudence) : ne jamais
    evincer sur une non-mesure (regression 2026-07-26 : coder allume par l'owner,
    conns pas encore montees, evince en < 1 min).
    """
    r = (rhythm or "").upper()
    # A0-4b (2026-09-05) — RENDRE LA DECISION OBSERVABLE ET ATTRIBUABLE.
    #
    # `inconnues` et `derive` ne changent RIEN a la decision : ils exposent ce que
    # la fonction a DEJA calcule pour la prendre. Les recalculer chez l'appelant
    # aurait duplique la regle, donc cree deux verites -- le defaut repare partout
    # ailleurs dans ce module.
    #
    # `inconnues` nomme les entrees NON MESUREES, et c'est le champ qui compte : un
    # rejeu doit pouvoir distinguer « faux » de « pas su ». Mesure du jour qui le
    # rend indispensable : l'historique physiologique ne porte AUCUNE de ces quatre
    # entrees, et le contrat d'incertitude les fait toutes proteger -- un rejeu
    # naif rendrait donc 100 % de `protect_coder` sans rien apprendre. Serialiser
    # une inconnue en `false` ou `0` contaminerait la baseline exactement comme
    # l'abstention due au bug `float(ts)` a contamine les episodes du learner.
    _inconnues: list[str] = []
    if isinstance(coder_conns, int) and coder_conns < 0:
        _inconnues.append("coder_conns")
    if demande_active is None:
        _inconnues.append("demande_active")
    if not isinstance(inutile_s, (int, float)) or float(inutile_s) < 0:
        _inconnues.append("inutile_s")
    if backlog is None or int(backlog) < 0:
        _inconnues.append("backlog")
    # ON NE PROTEGE PAS CE QUI N'EXISTE PAS. Mesure A0-3 du 2026-09-05 : coder
    # ABSENT (port NON, process NON) et pourtant `inutile_s = 0` — car le keeper
    # publie 0 quand il ne constate aucun coder (`etat_constate: OFF, coder_n: 0`),
    # la MEME valeur que « il vient de servir ». La suite calculait alors
    # `assez_inactif = (0 >= grace) = False`, donc `protection_active = True`, et
    # le journal annoncait « protege : grace (0s < 300s) » pour un organe qui
    # n'etait pas la. L'effet etait nul — il n'y a rien a ceder — mais le MOTIF
    # etait faux, et un motif faux oriente activement vers la mauvaise cause
    # (invariant owner du 2026-09-04). On tranche donc AVANT toute protection.
    if not coder_up:
        return {
            "strategie": "noop", "action": "noop", "cible": None, "ram_gain_gb": 0.0,
            "raison": "aucun coder a arbitrer (coder_up=False) : ni protection ni "
                      "eviction n'ont de sens [rythme=%s]" % r,
            "inconnues": _inconnues,
            # Sortie AVANT tout calcul de tolerance : ces derives n'existent pas
            # encore. `None` dit « non calcule », a ne pas confondre avec `False`.
            "derive": {"grace_s": None, "embed_affame": None,
                       "protection_active": None, "assez_inactif": None},
        }
    # LE RYTHME NE PROTEGE PLUS, IL MODULE (2026-09-02, point 3 du chantier).
    #
    # Ce qu'il y avait avant : `r not in ("CONSERVE","SOMMEIL","DEEP","REPOS")`
    # dans le OR, donc `NORMAL` suffisait a rendre `interactif` vrai et la
    # fonction sortait en `protect_coder` AVANT de regarder quoi que ce soit
    # d'autre. Mesure du jour : rythme NORMAL, conns=0, chains=0, backlog
    # 751 305 (150x le seuil) -- protege quand meme, avec pour raison
    # « l'organe qui SERT garde sa place » alors qu'il ne servait personne.
    # Le libelle designait le service ; ce qui protegeait etait le rythme.
    #
    # `NORMAL` dit « le systeme est eveille ». Il ne dit RIEN sur cet organe.
    # Il choisit desormais la TOLERANCE a l'inactivite, pas le verdict.
    grace_s = _GRACE_PAR_RYTHME.get(r, _GRACE_EVEILLE_S)

    # L'INCERTITUDE EST CONSERVATRICE, et uniformement -- meme regle que
    # `coder_conns < 0` (mesure manquante -> on protege, regression du
    # 2026-07-26 : coder allume par l'owner, conns pas encore montees, evince
    # en moins d'une minute). Tant que la couverture de l'emetteur de demande
    # n'est pas demontree, un TROU DE TELEMETRIE ne devient pas une
    # autorisation d'eteindre : ce serait rejouer juillet sous une autre forme.
    demande_protectrice = demande_active is not False

    # Duree CONTINUE a zero connexion : c'est ELLE qui remplace le rythme comme
    # garde-fou. Contrairement a l'age d'un drapeau -- remis a zero a chaque
    # repose, donc menteur -- elle ne triche pas. Inconnue => on protege.
    _inactivite_connue = isinstance(inutile_s, (int, float)) and inutile_s >= 0
    assez_inactif = _inactivite_connue and float(inutile_s) >= grace_s

    embed_affame = bool(embed_wanted) and backlog > seuil_backlog and not embedder_up

    # `protection_active`, et non plus `interactif` : ni une demande ouverte ni
    # un delai de grace ne sont des « interactions ». Le nom precedent invitait
    # a re-deduire dans six mois que « NORMAL = interactif = protection ».
    protection_active = (
        coder_conns != 0            # >0 sert ; <0 = mesure absente -> protege
        or chains_active > 0
        or demande_protectrice
        or not assez_inactif
    )

    _derive = {"grace_s": grace_s, "embed_affame": embed_affame,
               "protection_active": protection_active, "assez_inactif": assez_inactif}
    if protection_active:
        if coder_conns != 0:
            _pourquoi = "conns=%d" % coder_conns
        elif chains_active > 0:
            _pourquoi = "chains=%d" % chains_active
        elif demande_active is None:
            _pourquoi = "demande INCONNUE (prudence)"
        elif demande_active:
            _pourquoi = "demande active"
        elif not _inactivite_connue:
            _pourquoi = "inactivite INCONNUE (prudence)"
        else:
            _pourquoi = "grace (%.0fs < %.0fs)" % (float(inutile_s), grace_s)
        return {
            "strategie": "B_hyperemie", "action": "protect_coder",
            "cible": "llama:8091", "ram_gain_gb": 0.0,
            "raison": "protege : %s [rythme=%s -> grace=%.0fs]" % (_pourquoi, r, grace_s),
            "inconnues": _inconnues, "derive": _derive,
        }

    # Plus aucune protection : l'organe est evincable. Ce qui suit est inchange
    # -- le point 3 remplace un faux proxy (le rythme) par une mesure
    # physiologique, il ne touche NI au seuil de backlog, NI a la strategie.
    #
    # C — consolidation : l'assimilation affamee prime SI le coder occupe
    # sans servir ET qu'il n'y a pas la place de charger l'embedder a cote.
    if embed_affame and coder_up and coder_conns == 0 and free_gb < seuil_confort_gb:
        return {
            "strategie": "C_consolidation", "action": "yield_coder",
            "cible": "llama:8091", "ram_gain_gb": round(float(coder_ram_gb), 2),
            "raison": "repos (rythme=%s) + backlog=%d>%d + coder oisif (conns=0) + "
                      "libre=%.1f<%.1f Go : le coder cede ~%.1f Go, l'embedder sera "
                      "reveille par le keeper (embed.wanted deja pose)"
                      % (r, backlog, seuil_backlog, free_gb, seuil_confort_gb,
                         float(coder_ram_gb)),
            "inconnues": _inconnues, "derive": _derive,
        }

    return {
        "strategie": "noop", "action": "noop", "cible": None, "ram_gain_gb": 0.0,
        "raison": "repos mais rien a arbitrer (embed_affame=%s coder_up=%s conns=%d "
                  "libre=%.1f Go)" % (embed_affame, coder_up, coder_conns, free_gb),
        "inconnues": _inconnues, "derive": _derive,
    }


def _heartbeat_keeper() -> dict:
    """Heartbeat du keeper, ou {} s'il est illisible.

    Extrait pour que `_coder_conns` et `_inutile_s_llama` lisent le MEME
    fichier par le MEME chemin : deux lectures independantes du meme etat
    finissent toujours par diverger, et le cliquet de clones aurait raison de
    le signaler.
    """
    try:
        import json as _j

        _p = Path(__file__).resolve().parent.parent / "sandbox" / "llama_keeper.heartbeat"
        d = _j.loads(_p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001 - illisible = vide, l'appelant decide
        return {}


def _coder_conns() -> int:
    """active_conns du coder depuis sandbox/llama_keeper.heartbeat. -1 = inconnu."""
    try:
        return int(_heartbeat_keeper().get("active_conns", -1))
    except Exception:  # noqa: BLE001
        return -1


def _demande_active_llama():
    """Un bail de demande est-il ouvert sur llama ? True / False / None.

    None = on n'a pas pu regarder, et ce n'est PAS False : l'arbitre traite
    l'inconnu comme protecteur, exactement comme `coder_conns < 0`. Tant que la
    couverture de l'emetteur n'est pas demontree, un trou de telemetrie ne doit
    pas devenir une autorisation d'eteindre -- ce serait rejouer juillet (73
    arrets, 312,94 Go rechargees) sous une autre forme.

    Ceci met FIN a la coexistence stricte de `forge_organ_demand` : le signal
    entre dans la decision. Il n'y entre que comme PROTECTION -- il ne peut
    jamais provoquer une eviction, seulement l'empecher.
    """
    try:
        from nokido_agent.app.forge_organ_demand import demandes_actives

        return bool(demandes_actives("llama"))
    except Exception:  # noqa: BLE001 - inconnu, surtout pas False
        return None


def _inutile_s_llama():
    """Duree CONTINUE (s) pendant laquelle le coder tourne sans servir personne.

    Lue au heartbeat du keeper, qui la tient deja (`inutile_s`, remis a zero des
    qu'une connexion apparait). C'est LE substitut au rythme comme garde-fou :
    contrairement a l'age d'un drapeau -- remis a zero a chaque repose, donc
    menteur -- cette duree ne triche pas.

    None = keeper muet ou heartbeat illisible. L'arbitre protege alors : ne
    jamais evincer sur une non-mesure (regression du 2026-07-26).
    """
    d = _heartbeat_keeper()
    v = d.get("inutile_s")
    if not isinstance(v, (int, float)):
        return None
    # Un heartbeat perime ne decrit plus le present : mieux vaut INCONNU
    # (protecteur) qu'une inactivite d'il y a une heure prise pour actuelle.
    age = _age_heartbeat_s(d, _hb_keeper_path())
    if age is None or age > 600:
        return None
    return float(v)


def _hb_keeper_path():
    """Chemin du pouls du keeper llama — temoin independant pour la contre-mesure."""
    return Path(__file__).resolve().parent.parent / "sandbox" / "llama_keeper.heartbeat"


def _age_heartbeat_s(d: dict, chemin=None):
    """Age (s) d'un heartbeat, quel que soit le FORMAT de son horodatage.

    DEFAUT MESURE LE 2026-09-05, effet massif pour une seule ligne. Les keepers
    n'ecrivent pas tous `ts` de la meme facon : `docker_keeper` publie un epoch
    (`1788569993.8`), `llama_keeper` une date ISO (`'2026-09-05T09:07:35'`).
    L'ancienne lecture faisait `float(d["ts"])`, donc `ValueError` sur l'ISO,
    avalee par un `except` qui rendait `None`.

    Consequence en chaine : `_inutile_s_llama()` rendait `None` alors que le keeper
    publiait `inutile_s = 211` ; l'arbitre lisait « inactivite INCONNUE » et
    s'abstenait PAR PRUDENCE — a chaque tick, indefiniment. `llama-server` (4,8 Go)
    n'etait donc JAMAIS evince par le regulateur, ce qui bloquait d'un coup la lane
    d'admission CI, le redemarrage du keeper Docker par le superviseur
    (`resource gate refused`) et jusqu'aux sondes de diagnostic (throttle).

    Le remede est du cote LECTEUR, pas du cote emetteur : ce lecteur agrege des
    producteurs heterogenes, et changer le format d'un keeper casserait ses autres
    lecteurs. Rend `None` quand la date est vraiment illisible — la propriete de
    securite « ne jamais evincer sur une non-mesure » est CONSERVEE, on cesse
    seulement d'appeler non-mesure ce qui etait parfaitement mesure.
    """
    brut = d.get("ts")
    if brut in (None, ""):
        return None
    try:
        return time.time() - float(brut)
    except (TypeError, ValueError):
        pass
    from datetime import datetime as _dt

    txt = str(brut).replace("Z", "+00:00")
    q = None
    # La chaine ENTIERE d'abord. Tronquer a 26 caracteres « pour couper les
    # nanosecondes » ampute le fuseau d'une date UTC complete
    # (`2026-09-05T09:07:35.123456+00:00` fait 32 caracteres) : la date devient
    # NAIVE, donc relue en heure locale, et l'age gagne le decalage du fuseau —
    # mesure 7230 s au lieu de 30 s en UTC+2. Un age faux est pire qu'un age
    # absent : il DECIDE, alors que `None` fait s'abstenir.
    for essai in (txt, txt[:26]):
        try:
            q = _dt.fromisoformat(essai)
            break
        except Exception:  # noqa: BLE001
            continue
    if q is None:
        return None
    try:
        age = time.time() - q.timestamp()
    except Exception:  # noqa: BLE001
        return None
    # CONTRE-MESURE DU REPERE (owner, 2026-09-05 : « attention a l'horloge UTC »).
    # Une date NAIVE est ici relue en heure LOCALE. Si un producteur ecrivait en UTC
    # naif, l'age gagnerait le decalage du fuseau — +7200 s en UTC+2 — et le pouls
    # serait declare PERIME : on retomberait EN SILENCE dans le defaut d'origine,
    # l'arbitre redevenant aveugle. Le `mtime` du fichier est un temoin independant,
    # ecrit par l'OS : deux mesures qui divergent fortement denoncent un repere faux.
    # On rend alors None — INCERTAIN — plutot qu'un age fabrique.
    if chemin is not None and q.tzinfo is None:
        try:
            age_disque = time.time() - os.path.getmtime(chemin)
        except OSError:
            age_disque = None
        if age_disque is not None and abs(age - age_disque) > 300.0:
            return None
    return age


def _backlog_pending_qualifie() -> tuple:
    """Backlog vectoriel REELLEMENT en attente, et l'age de la mesure.

    Rend `(pending, age_s, source)`. `pending = -1` signifie INCONNU, jamais
    zero et surtout jamais le chiffre brut.

    POURQUOI (mesure 2026-09-02). `_backlog_embeddings()` compte
    `embedding IS NULL` : 751 305 chunks. Or ce nombre melange trois etats que
    `forge_memory_availability` sait distinguer depuis le 2026-09-01 :

        626 646  REFUSED_BY_POLICY  -- `forge_tier_guard` les refuse par palier,
                                      ils n'attendent RIEN et n'attendront jamais
        124 659  PENDING            -- le vrai backlog
      1 280 037  AVAILABLE

    L'arbitre comparait donc 751 305 a son seuil de 5 000 : il lisait une famine
    six fois plus grosse que la vraie. Et la mesure du meme jour montre que le
    canal LEXICAL couvre 100 % du corpus (2 031 354 entrees) -- la memoire reste
    interrogeable malgre la dette vectorielle.

    PAS DE REPLI SUR LE BRUT. Quand le snapshot manque ou a vieilli, on rend
    INCONNU. Se rabattre sur `embedding IS NULL` recreerait exactement la
    confusion qu'on vient de lever, et le ferait en silence.

    Le chemin chaud ne calcule RIEN : lecture d'un fichier (~7 ms mesurees)
    contre 8,27 s pour le seul GROUP BY qui separe PENDING de REFUSED.
    """
    try:
        from nokido_agent.app.forge_memory_availability import snapshot

        snap = snapshot()
    except Exception as exc:  # noqa: BLE001
        return -1, None, "INCONNU (%s)" % type(exc).__name__
    if not snap.get("frais"):
        return -1, snap.get("age_s"), "INCONNU (%s)" % snap.get("raison", "?")
    return int(snap["vector_pending"]), snap.get("age_s"), "snapshot"


def _backlog_embeddings() -> int:
    """Chunks RAG sans vecteur (assimilation en attente). -1 = illisible.

    ⚠️ C'est la TABLE qui decide quelle base est la bonne, PAS l'existence du
    fichier. Mesure 2026-08-19 : `data/rag.db` EXISTE mais fait 0 octet et ne
    porte aucune table `rag%` — un candidat teste par `.exists()` rendait donc
    -1 en permanence, `backlog=-1` restait sous le seuil, et C_consolidation ne
    se serait JAMAIS armee. Un arbitre desarme par une base vide aurait passe
    tous les tests (la fonction pure, elle, est correcte) et n'aurait rien fait
    en production : exactement le faux-vert « garde qui ne mesure rien ».
    La vraie base est %NOKIDO_DATA%\embeddings.db (~17 Go, 1,17 M chunks), montee aussi en
    RAG/embeddings.db ; on garde `data/rag.db` en dernier ressort au cas ou le
    schema y migrerait un jour.
    """
    import sqlite3

    _root = Path(__file__).resolve().parent.parent
    for _cand in (Path("%NOKIDO_DATA%\embeddings.db"), _root / "RAG" / "embeddings.db",
                  _root / "data" / "rag.db"):
        try:
            if not _cand.exists():
                continue
            _c = sqlite3.connect("file:%s?mode=ro" % _cand.as_posix(), uri=True, timeout=2.0)
            try:
                _n = _c.execute(
                    "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL").fetchone()[0]
            finally:
                _c.close()
            return int(_n)
        except Exception:  # noqa: BLE001 - base absente/vide/verrouillee : candidat suivant
            continue
    return -1


def _port_ecoute(port: int) -> bool:
    """LISTEN sur 127.0.0.1:port ? Non-bloquant, ne leve jamais.

    LECTURE LOCALE D'ABORD. Mesure A0-3 du 2026-09-05 : sur un port FERME, le
    `connect_ex` consommait son timeout entier — **805 ms**, sur un chemin appele a
    chaque tick de regulation. La table des sockets se lit en memoire, sans toucher
    au reseau, et rend le meme fait en une fraction de milliseconde.

    Nuance de semantique, assumee : `net_connections` prouve qu'un socket ECOUTE,
    la connexion prouvait en plus qu'il ACCEPTE. Un serveur au backlog sature
    serait donc vu « up » ici alors qu'il refuse. C'est acceptable pour ce que
    l'arbitre en fait — composer `embed_affame`, qu'un embedder saturé nie tout
    autant qu'un embedder disponible — et le repli ci-dessous couvre le cas ou la
    table n'est pas lisible. Ne PAS reutiliser cette fonction pour prouver qu'un
    service SERT : c'est TRANSPORT, pas APPLICATIF.
    """
    try:
        import psutil as _ps

        cible = int(port)
        for c in _ps.net_connections(kind="tcp"):
            if c.status == "LISTEN" and c.laddr and c.laddr.port == cible:
                return True
        return False
    except Exception:  # noqa: BLE001 - table illisible : on retombe sur la connexion
        pass
    _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _s.settimeout(0.8)
    try:
        return _s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            _s.close()
        except Exception:  # noqa: BLE001
            pass


def _arbitrage_consolidation_tick() -> None:
    """Tick PROACTIF (cadence sampler). Au repos, libere le coder oisif pour que
    l'embedder draine le backlog. Reversible (LAFORGE_ARBITRAGE=0), cooldown large
    (anti-pompage), journal loud. Ne DEMARRE PAS l'embedder : retire l'obstacle,
    le keeper reveille :8099 sur embed.wanted deja pose (une seule responsabilite).
    """
    if os.environ.get("LAFORGE_ARBITRAGE", "1") != "1":
        observer_decision(saut="arbitrage_desactive")
        return
    global _last_arbitrage_act_ts
    if (time.time() - _last_arbitrage_act_ts) < _ARBITRAGE_COOLDOWN_S:
        observer_decision(saut="cooldown")
        return
    try:
        try:
            from nokido_agent.app.forge_endocrine_system import get_rhythm as _gr

            _rhythm = _gr()
        except Exception:  # noqa: BLE001 - rythme illisible -> "NORMAL" = interactif = protege
            _rhythm = "NORMAL"
        _intents = get_active_intents()
        _coder = llamacpp_native_status()
        _bk, _bk_age, _bk_src = _backlog_pending_qualifie()
        _ent = {
            "rhythm": _rhythm,
            "coder_up": bool(_coder.get("running") or _coder.get("port_listening")),
            "coder_conns": _coder_conns(),
            "chains_active": int(_intents.get("chains_active") or 0),
            "embed_wanted": bool(_intents.get("embed_wanted")),
            "backlog": _bk,
            "demande_active": _demande_active_llama(),
            "inutile_s": _inutile_s_llama(),
            "embedder_up": _port_ecoute(
                int(os.environ.get("LAFORGE_LLAMA_EMBED_PORT", "8099"))),
            "coder_ram_gb": float(_coder.get("ram_gb") or _LLAMACPP_NATIVE_RAM_ESTIMATE_GB),
            "free_gb": _free_now(),
        }
        _dec = arbitrer_pression(**_ent)
        # A0-4b : on observe AVANT d'agir. Une decision suivie d'un echec d'action
        # reste une decision, et le journal doit la porter -- sinon il ne
        # renseignerait que les actions reussies, biais deja paye ailleurs.
        _ent["backlog_age_s"] = _bk_age
        _ent["backlog_src"] = _bk_src
        observer_decision(_ent, _dec, coder_verdict=str(_coder.get("verdict") or ""))
        if _dec["action"] == "yield_coder":
            if llamacpp_native_stop():
                _last_arbitrage_act_ts = time.time()
                _audit_lifecycle(
                    "arbitrage", "llm", _dec["raison"],
                    target="llama-server:8091", strategie=_dec["strategie"],
                    ram_gb=_dec["ram_gain_gb"])
            else:
                _audit_lifecycle(
                    "arbitrage_echec", "llm",
                    "yield_coder decide mais stop refuse (non-admin?)",
                    target="llama-server:8091", strategie=_dec["strategie"])
    except Exception as _e:  # noqa: BLE001 - le tick ne doit jamais tuer le sampler
        logging.getLogger(__name__).debug(
            "[arbitrage] tick ignore (%s: %s)", type(_e).__name__, _e)


def _sampler_loop() -> None:
    """Daemon thread loop. Refreshes _SNAPSHOT every _SAMPLE_INTERVAL_S."""
    global _last_evict_ts, _last_supervisor_sleep_ts, _last_supervisor_wake_ts
    # Prime psutil cpu_percent — first call always returns 0.0
    if _PSUTIL_OK:
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
    while not _SAMPLER_STOP.is_set():
        try:
            new = _sample_once()
            _SNAPSHOT.update(new)
            _dump_snapshot_json()
            # Satiete graduee : la glande, pas un garde de plus (cf _secreter_insuline).
            try:
                _secreter_insuline(float(new.get("ram_pct") or 0.0))
            except Exception as e:  # noqa: BLE001
                logging.getLogger(__name__).debug(
                    "[insuline] tick ignore (%s)", type(e).__name__)
            # Phase 39 (2026-05-25) : hook SNN. Ecrit alors comme opt-in sur
            # FORGE_SNN_ENABLED=1 — variable qui n'a JAMAIS ete posee nulle part
            # (ni config, ni code, ni doc). Mesure 2026-08-04 : le capteur aurait
            # detecte les 50 episodes de detresse RAM des 9 derniers jours, il n'a
            # emis aucune adrenaline en 2,5 mois. Un garde branche sur un signal
            # que personne n'emet.
            # L'activation passe desormais AUSSI par `sandbox/snn.wanted`, le meme
            # patron d'intention que docker.wanted / llama.wanted (declare dans
            # forge_signal_coupling.SIGNAUX). Raison : une variable d'environnement
            # ne redescend pas dans un process vivant, donc l'armer exigeait un
            # restart du hub — et le desarmer aussi. Avec le fichier, poser et
            # RETIRER prennent effet au tick suivant, sans couper quoi que ce soit.
            # C'est la condition de reversibilite : en cas d'echec mesure, on
            # supprime le fichier et le corps revient a l'etat d'avant.
            _snn_flag = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "sandbox", "snn.wanted")
            if os.environ.get("FORGE_SNN_ENABLED") == "1" or os.path.exists(_snn_flag):
                try:
                    from nokido_agent.app.forge_snn_monitor import get_monitor

                    _spikes = get_monitor().feed(new)
                    if any(_spikes.values()):
                        try:
                            _transduire("snn.wanted")
                        except Exception as _e:  # noqa: BLE001
                            logging.getLogger(__name__).debug(
                                "[snn] transduction non declaree (%s)", type(_e).__name__)
                        # Journalise le TIR pour qu'il soit mesurable apres coup.
                        # `snn_spike` n'est pas dans forge_regulation_efficacy.ACTES :
                        # il sera compte comme une OBSERVATION, ce qui est exact — un
                        # spike n'est pas un acte, il en declenche chez ses recepteurs.
                        try:
                            from nokido_agent.app.forge_lifecycle_audit import record as _rec

                            # Le BACKEND dans le tir : sans lui, un spike du repli
                            # (seuil statique) est indistinguable d'un spike snntorch,
                            # et il faut remonter au pid puis a l'interpreteur pour
                            # savoir lequel a tire. Mesure 2026-08-28 : la production
                            # a emis 503 tirs en repli sans que rien ne le signale.
                            try:
                                from nokido_agent.app.forge_snn_monitor import available as _snn_av

                                _bk = "snntorch" if _snn_av() else "repli-seuil"
                            except Exception:  # noqa: BLE001
                                _bk = "inconnu"
                            _rec("snn_spike", domain="regulation",
                                 reason="backend=%s ram=%s cpu=%s gpu=%s" % (
                                     _bk, new.get("ram_pct"), new.get("cpu_pct"),
                                     new.get("gpu_pct")),
                                 target="vitals")
                        except Exception as _e:  # noqa: BLE001
                            logging.getLogger(__name__).debug(
                                "[snn] tir non journalise (%s)", type(_e).__name__)
                        from nokido_agent.app.forge_hormones import release as _hrel

                        _hrel(
                            "adrenaline",
                            level=0.8,
                            payload={
                                "source": "snn_monitor",
                                "spikes": _spikes,
                                "ram_pct": new.get("ram_pct"),
                                "cpu_pct": new.get("cpu_pct"),
                                "gpu_pct": new.get("gpu_pct"),
                            },
                            receptors=["supervisor", "agt_security"],
                        )
                except Exception as _e:  # noqa: BLE001
                    # Le thread du sampler ne doit jamais mourir ici, mais un echec
                    # SILENCIEUX rendrait le capteur indistinguable d'un capteur
                    # eteint — exactement le defaut qu'on vient de corriger.
                    logging.getLogger(__name__).warning(
                        "[snn] tick ignore (%s: %s)", type(_e).__name__, _e)
            # Derive memoire PAR SERVICE (2026-08-04). Un seuil global voit la
            # consequence — RAM a 88 % — jamais QUI derive. Mesure du jour :
            # NokidoLlamaEmbed a 10,92 Go pour 2,69 Go au demarrage, machine a
            # 0,03 Go libre, et aucun canal existant ne pouvait le dire. Branche
            # ICI plutot que dans un daemon de plus : le sampler passe deja.
            # Cadence propre (~60 s) : le tick du sampler est trop rapide pour ce
            # capteur, et psutil sur ~50 pids n'a pas besoin d'etre paye 4x/min.
            try:
                global _RSS_WATCH_DERNIER
                if time.time() - _RSS_WATCH_DERNIER >= 60.0:
                    _RSS_WATCH_DERNIER = time.time()
                    from nokido_agent.app.forge_service_rss_watch import alerter, echantillon

                    echantillon()
                    alerter()
                    # QUI appelle les ports locaux (2026-08-05). Le capteur de derive
                    # dit QUE l'embedder grossit ; celui-ci dit POURQUOI. Mesure du
                    # jour : 118 sockets en TIME_WAIT vers :8099 = ~50 requetes/min,
                    # et le RSS est redescendu de 6,07 a 5,10 Go des la fin de la
                    # rafale. Sans ce compteur, la seule lecture possible etait
                    # « il grossit » et la conclusion naturelle « il fuit » — celle
                    # que j'avais deja tiree a tort le 04/08. Meme cadence de 60 s :
                    # net_connections coute trop cher pour le tick de 15 s.
                    from nokido_agent.app.forge_port_callers import echantillon as _appels

                    _appels()
            except Exception as _e:  # noqa: BLE001
                logging.getLogger(__name__).debug(
                    "[rss_watch] tick ignore (%s)", type(_e).__name__)

            # LM Studio : allume seulement quand utile, coupe des que plus
            # necessaire (politique owner 2026-08-18). Branche ICI plutot que
            # dans un daemon de plus : le sampler passe deja. Cadence propre de
            # 60 s — le tick de 15 s ferait payer un `schtasks /query` quatre
            # fois par minute pour un fait qui bouge a l'echelle des minutes.
            # En THREAD : l'arret attend que le port se taise (jusqu'a 20 s), et
            # allonger le tick du sampler retarderait toutes les autres mesures.
            try:
                global _LMSTUDIO_IDLE_DERNIER
                if time.time() - _LMSTUDIO_IDLE_DERNIER >= 60.0:
                    _LMSTUDIO_IDLE_DERNIER = time.time()
                    threading.Thread(target=lmstudio_arret_si_inactif,
                                     name="forge_lmstudio_idle", daemon=True).start()
            except Exception as _e:  # noqa: BLE001
                logging.getLogger(__name__).debug(
                    "[lmstudio] tick inactivite ignore (%s)", type(_e).__name__)

            # ARBITRAGE ADAPTATIF (owner 2026-08-19). Au REPOS, si l'assimilation
            # est affamee et que le coder occupe sans servir, il cede la place :
            # l'embedder draine le backlog SANS attendre qu'une autre tache reclame
            # de la RAM. Cadence 60 s (comme lmstudio), en THREAD (llamacpp_native_stop
            # attend l'arret), cooldown propre au tick contre le pompage.
            try:
                global _ARBITRAGE_DERNIER
                if time.time() - _ARBITRAGE_DERNIER >= _ARBITRAGE_CADENCE_S:
                    _ARBITRAGE_DERNIER = time.time()
                    threading.Thread(target=_arbitrage_consolidation_tick,
                                     name="forge_arbitrage", daemon=True).start()
            except Exception as _e:  # noqa: BLE001
                logging.getLogger(__name__).debug(
                    "[arbitrage] tick declenchement ignore (%s)", type(_e).__name__)

            # BAUX DE PRIORITE : une tache prioritaire morte sans liberer ne garde pas le corps
            # endormi -- tout bail echu est libere. Cadence 60 s, en THREAD (le reveil attend le
            # superviseur) ; le registre des baux est un repertoire, lu sans verrou global.
            try:
                global _BAUX_DERNIER
                if time.time() - _BAUX_DERNIER >= 60.0:
                    _BAUX_DERNIER = time.time()
                    threading.Thread(target=expirer_baux, name="forge_baux_expiration",
                                     daemon=True).start()
            except Exception as _e:  # noqa: BLE001
                logging.getLogger(__name__).debug(
                    "[bail] tick d'expiration ignore (%s)", type(_e).__name__)

            ram_pct = float(new.get("ram_pct") or 0.0)
            now = time.time()
            # DETRESSE VITALE mesuree, jamais supposee. Trois etats : une valeur
            # absente ou nulle n'est PAS une detresse, c'est une mesure manquante --
            # elle ne doit rien declencher.
            _libre_gb = float(new.get("ram_free_gb") or 0.0)
            _detresse = 0.0 < _libre_gb < float(
                os.environ.get("LAFORGE_DETRESSE_LIBRE_GB", "1.5"))
            # Hard eviction: Ollama/llamacpp/Docker at 75%
            if ram_pct >= _AUTO_EVICT_RAM_THRESHOLD and (
                (now - _last_evict_ts) > _AUTO_EVICT_COOLDOWN_S
                or (_detresse and (now - _last_evict_ts) > _DETRESSE_COOLDOWN_S)
            ):
                if _detresse and (now - _last_evict_ts) <= _AUTO_EVICT_COOLDOWN_S:
                    # L'outrepassement se LIT dans le journal, il ne se devine pas.
                    _audit_lifecycle(
                        "evict_detresse", "ram",
                        "REFRACTAIRE OUTREPASSE (%.2f Go libre < seuil vital) -- "
                        "sans quoi ce creux passait sans le moindre acte" % _libre_gb,
                        target="sampler")
                _last_evict_ts = now
                threading.Thread(
                    target=request_resources,
                    kwargs={"needed_ram_gb": 4.0, "allow_evict": True},
                    name="forge_auto_evict",
                    daemon=True,
                ).start()
            # Soft eviction: sleep non-essential services via supervisor at 78%
            if (
                ram_pct >= _SUPERVISOR_SLEEP_RAM_THRESHOLD
                and (now - _last_supervisor_sleep_ts) > _AUTO_EVICT_COOLDOWN_S
            ):
                _last_supervisor_sleep_ts = now
                threading.Thread(
                    target=_supervisor_sleep_non_essential,
                    name="forge_supervisor_sleep",
                    daemon=True,
                ).start()
            # Wake: restore services when RAM drops below 65%
            elif ram_pct < _SUPERVISOR_WAKE_RAM_THRESHOLD and (now - _last_supervisor_wake_ts) > 300.0:
                _last_supervisor_wake_ts = now
                threading.Thread(
                    target=_supervisor_wake_non_essential,
                    name="forge_supervisor_wake",
                    daemon=True,
                ).start()
        except Exception:
            pass  # Never crash the sampler
        if _SAMPLER_STOP.wait(_SAMPLE_INTERVAL_S):
            return


def start_sampler(interval_s: float = 3.0) -> None:
    """Start background sampler. Idempotent — no-op if already running."""
    global _SAMPLER_THREAD, _SAMPLE_INTERVAL_S, _SAMPLER_STARTED_TS
    _SAMPLE_INTERVAL_S = max(1.0, float(interval_s))
    if _SAMPLER_THREAD is not None and _SAMPLER_THREAD.is_alive():
        return
    _SAMPLER_STOP.clear()
    # Horodate l'amorce : publie dans l'instantane pour que le PROPRIETAIRE soit
    # identifiable, la propriete etant sinon decidee par un repli implicite.
    _SAMPLER_STARTED_TS = time.time()
    _SAMPLER_THREAD = threading.Thread(
        target=_sampler_loop,
        name="forge_resource_sampler",
        daemon=True,
    )
    _SAMPLER_THREAD.start()
    # NE PAS primer ici : _sample_once() spawn un subprocess GPU Win32 SYNCHRONE.
    # Si start_sampler est appelé depuis l'event loop (resource_should_spawn ->
    # should_throttle -> get_snapshot à froid), ce subprocess.run GÈLE la boucle
    # (constaté live via forge_loop_sentinel : subprocess.run mid-block, lag s).
    # Le daemon _sampler_loop fournit le 1er échantillon (~interval) hors-loop ;
    # get_snapshot reste non-bloquant (retourne le défaut jusqu'au 1er sample).


def stop_sampler() -> None:
    """Stop background sampler. Idempotent."""
    _SAMPLER_STOP.set()


# ─────────────────────────────────────────────────────────────────────────────
# Public API — non-blocking reads
# ─────────────────────────────────────────────────────────────────────────────


# Age max d'un snapshot du file-broker encore digne de confiance pour l'amorce a
# froid. Le sampler l'ecrit toutes les _SAMPLE_INTERVAL_S (3s) ; 30s laisse de la
# marge sans jamais servir un etat perime comme s'il etait frais.
_COLD_SEED_MAX_AGE_S = 30.0


def _seed_snapshot_cold() -> None:
    """Amorce _SNAPSHOT quand AUCUN echantillon n'existe encore (ts == 0).

    LE TROU QUE CA BOUCHE : les defauts de _SNAPSHOT sont des ZEROS. Or `ram_pct=0.0`
    ne veut pas dire « je n'ai pas encore mesure », ca veut dire « charge nulle » —
    donc `should_throttle()` renvoie False. Tout process court-vif (script one-shot,
    job, handler) qui appelle should_throttle() juste apres l'import franchit donc
    TOUJOURS le garde de spawn, en SILENCE. Mesure le 2026-07-16 : get_snapshot()
    rendait ram_pct=0.0 pendant que resource_state.json disait 78.1 et psutil 79.
    A 90% de RAM reelle il aurait rendu 0.0 pareil. C'est un fail-OPEN.
    Meme pathologie que le wedge de juillet (liveness != readiness) : rendre une
    VALEUR la ou la verite est « je ne sais pas encore ».

    CE QU'ON NE FAIT SURTOUT PAS : primer le sampler. `start_sampler` l'interdit
    explicitement, et pour une raison MESUREE — `_sample_once()` spawn un subprocess
    PowerShell (GPU Win32) SYNCHRONE qui GELE l'event loop quand l'appel vient de la
    boucle (constate live via forge_loop_sentinel). Ce non-primage est un garde-fou,
    pas un oubli : on le respecte.

    Deux sources, toutes deux NON BLOQUANTES, dans l'ordre :
      1. le FILE-BROKER `sandbox/resource_state.json` — il existe DEJA « so the Deno
         supervisor (or any external process) can read resource state without HTTP ».
         Un process a froid EST exactement ce cas. Un daemon long-vif l'ecrit a chaque
         tick, donc l'etat est reel et frais. Zero echantillonnage, zero dup.
      2. a defaut, psutil pur (RAM + disque) : microsecondes, ZERO subprocess. On ne
         touche NI au GPU NI au TDR — ce sont eux qui coutent le subprocess.

    CPU volontairement EXCLU de l'amorce : `psutil.cpu_percent(interval=None)` rend
    0.0 au tout premier appel du process (c'est pourquoi `_sampler_loop` l'amorce a
    vide avant sa boucle). L'inclure ici ajouterait un mensonge au lieu d'en retirer un.

    Si les deux sources echouent, `ts` reste a 0 : le snapshot dit alors honnetement
    « je ne sais pas », au lieu d'affirmer « tout va bien ».
    """
    try:
        import json as _json

        raw = _json.loads(_SNAPSHOT_JSON_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and 0.0 < float(raw.get("ts") or 0.0):
            if (time.time() - float(raw["ts"])) <= _COLD_SEED_MAX_AGE_S:
                _SNAPSHOT.update(raw)
                return
    except Exception:
        pass  # broker absent / illisible / perime -> on tente psutil

    if not _PSUTIL_OK:
        return  # ts reste 0 -> « inconnu », jamais « tout va bien »
    try:
        vm = psutil.virtual_memory()
        _SNAPSHOT.update(
            {
                "ts": time.time(),
                "ram_pct": round(vm.percent, 1),
                "ram_used_gb": round(vm.used / 1024**3, 2),
                "ram_total_gb": round(vm.total / 1024**3, 2),
                "ram_free_gb": round(vm.available / 1024**3, 2),
            }
        )
    except Exception:
        return
    try:
        d = psutil.disk_usage(str(Path(__file__).anchor))
        _SNAPSHOT["disk_pct"] = round(d.percent, 1)
    except Exception:
        pass


_SAMPLER_AUTOSTART_ENV = "LAFORGE_SAMPLER_AUTOSTART"
_SAMPLER_OWNER_ARGV = ("nokido_hub.py",)
_SAMPLER_TAKEOVER_AFTER_S = 120.0


def _published_state_age_s() -> "float | None":
    """Age de l'etat publie, ou None s'il n'existe pas. Ne lit PAS le contenu."""
    try:
        return time.time() - _SNAPSHOT_JSON_PATH.stat().st_mtime
    except OSError:
        return None


def _should_autostart_sampler() -> bool:
    """Ce process a-t-il le DROIT d'echantillonner ? UN SEUL proprietaire.

    MESURE 2026-07-26 : `get_snapshot()` amorcait un sampler chez N'IMPORTE QUEL
    appelant, et ce sampler spawne un PowerShell par tick (sonde GPU, ~1,6 s).
    Tout module qui demandait UNE FOIS la RAM devenait donc un emetteur permanent.
    Constate dans le journal PowerShell via HostApplication : sondes GPU et TDR,
    throttlees a 60 s chacune, vues a ~2/min a l'echelle machine ; et la serie de
    vitaux ecrite par deux processus, avec un ecart NEGATIF entre deux points
    consecutifs. Un throttle par process ne borne rien quand les process se
    multiplient : la borne doit porter sur le NOMBRE d'echantillonneurs.

    Les non-proprietaires LISENT l'etat publie (`sandbox/resource_state.json`) —
    c'est exactement ce pour quoi ce file-broker existe (cf _seed_snapshot_cold).

    REPRISE : si l'etat publie manque ou est perime au-dela de
    _SAMPLER_TAKEOVER_AFTER_S, le proprietaire est mort ou absent et le premier
    appelant reprend la main. Un verrou qui laisserait le corps aveugle serait
    pire que le doublon qu'il evite.
    """
    flag = os.environ.get(_SAMPLER_AUTOSTART_ENV, "").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    try:
        if Path(sys.argv[0]).name in _SAMPLER_OWNER_ARGV:
            return True
    except Exception:  # noqa: BLE001
        pass
    age = _published_state_age_s()
    return age is None or age > _SAMPLER_TAKEOVER_AFTER_S


def get_snapshot() -> dict[str, Any]:
    """Return latest resource snapshot. Le sampler ne demarre que chez le PROPRIETAIRE.

    Reste NON BLOQUANT : l'amorce a froid lit un fichier ou interroge psutil, jamais
    un subprocess (cf _seed_snapshot_cold). Le sampler ecrasera ces valeurs au 1er
    tick (~3s) ; l'amorce ne sert qu'a ne pas mentir dans l'intervalle.
    """
    if _SAMPLER_THREAD is None or not _SAMPLER_THREAD.is_alive():
        if _should_autostart_sampler():
            start_sampler()
    # Non-proprietaire : on RE-lit l'etat publie des qu'il a vieilli. Sans ce
    # rafraichissement, l'amorce a froid ne jouerait qu'UNE fois et le process
    # rendrait a vie un instantane GELE en le presentant comme courant — un
    # capteur qui ment est pire qu'un capteur muet.
    if not _SNAPSHOT.get("ts") or (time.time() - float(_SNAPSHOT.get("ts") or 0.0)) > _COLD_SEED_MAX_AGE_S:
        _seed_snapshot_cold()
    return dict(_SNAPSHOT)  # shallow copy → caller can't mutate shared state


# Sous cortisol soutenu, on freine PLUS TOT : les seuils ressources sont durcis de
# ce nombre de points. Remplace le veto absolu, qui paralysait un corps sain.
CORTISOL_TIGHTEN_PTS = 10.0


def should_throttle(
    ram_pct_threshold: float = 85.0,
    cpu_pct_threshold: float = 90.0,
    gpu_pct_threshold: float = 95.0,
    tdr_quarantine: bool = True,
    cortisol_threshold: float = 0.85,
    disk_pct_threshold: float = 95.0,
) -> bool:
    """Return True if any resource is above threshold. Non-blocking.

    Use BEFORE spawning a heavy task (LLM call, embed batch, vector rebuild) :
        if should_throttle():
            await asyncio.sleep(2)  # or skip / queue

    tdr_quarantine=True (default) : >=1 TDR < 5min => True (quarantine GPU).
    Mettre False pour task RAM-only insensible au GPU.
    EFFERENT endocrine (cortisol_to_throttle) : un cortisol systeme soutenu >= seuil
    DURCIT les seuils ressources de CORTISOL_TIGHTEN_PTS — sous stress on freine PLUS
    TOT. Il n'oppose PAS de veto : une hormone seule ne doit jamais paralyser un corps
    aux ressources saines (mesure 2026-07-29). Best-effort, fail-safe.
    """
    # ── CORTISOL = MODULATEUR, PAS VETO (mesuré deux fois le 2026-07-29) ──────────
    # Le cortisol renvoyait True à lui seul : une hormone pouvait donc paralyser
    # intégralement un corps aux ressources SAINES. Mesures du jour :
    #   (1) au boot du matin — 471 spawns refusés avec RAM 60 %, CPU 6 %, GPU 0,6 %,
    #       disque 71 %, TDR 0 ; tout était sous seuil, seul le cortisol bloquait ;
    #   (2) après un redémarrage — 382 refus avec RAM à 37,8 %, l'hormone ayant
    #       SURVÉCU au restart (persistée, TTL 1800 s) et paralysé le corps SUIVANT.
    # Dans les deux cas le frein a empêché la guérison au lieu de protéger quoi que
    # ce soit : les organes manquants étaient précisément ceux qu'il refusait.
    # Le mandat « stress -> ralentir les spawns » est tenu autrement, et plus
    # fidèlement à la biologie : le cortisol modifie la SENSIBILITÉ, il n'arrête pas
    # la circulation. Sous stress on freine dix points plus tôt — jamais « toujours ».
    # Un appelant peut encore le neutraliser via cortisol_threshold=1.01 (ce que
    # forge_sandbox_exec faisait déjà, contournement local devenu inutile).
    ram_pct_threshold = float(os.environ.get("LAFORGE_RAM_THRESHOLD", ram_pct_threshold))
    cpu_pct_threshold = float(os.environ.get("LAFORGE_CPU_THRESHOLD", cpu_pct_threshold))
    gpu_pct_threshold = float(os.environ.get("LAFORGE_GPU_THRESHOLD", gpu_pct_threshold))
    disk_pct_threshold = float(os.environ.get("LAFORGE_DISK_THRESHOLD", disk_pct_threshold))

    try:
        from nokido_agent.app.forge_endocrine import read as _hr
        if max(float(_hr("CORTISOL_FRUSTRATION") or 0.0),
               float(_hr("CORTISOL_QUOTA_CLOUD") or 0.0)) >= cortisol_threshold:
            ram_pct_threshold -= CORTISOL_TIGHTEN_PTS
            cpu_pct_threshold -= CORTISOL_TIGHTEN_PTS
            gpu_pct_threshold -= CORTISOL_TIGHTEN_PTS
    except Exception:  # noqa: BLE001 - endocrinien absent -> on continue sur les seuils ressources
        pass
    s = get_snapshot()
    if s.get("ram_pct", 0) >= ram_pct_threshold:
        return True
    if s.get("cpu_pct", 0) >= cpu_pct_threshold:
        return True
    gpu = s.get("gpu_pct")
    if gpu is not None and gpu >= gpu_pct_threshold:
        return True
    # DISQUE : garde-fou defensif. Le disque etait mesure (get_snapshot.disk_pct) mais
    # jamais un effecteur -> a disque quasi-plein, les taches disk-heavy (embed batch,
    # vector rebuild, ecriture RAG) continuaient jusqu'au write-crash / corruption WAL.
    # Seuil haut (95%) = ne freine PAS l'usage normal (~88%), agit seulement au bord.
    if s.get("disk_pct", 0) >= disk_pct_threshold:
        return True
    if tdr_quarantine and s.get("tdr_recent", 0) >= 1:
        return True
    return False


def summary_line() -> str:
    """One-line status for TUI / status bar / hub /health response."""
    s = get_snapshot()
    gpu = s.get("gpu_pct")
    gpu_s = f"GPU {gpu:.0f}%" if gpu is not None else "GPU n/a"
    return (
        f"RAM {s.get('ram_pct', 0):.0f}% "
        f"({s.get('ram_used_gb', 0):.1f}/{s.get('ram_total_gb', 0):.1f} GB) "
        f"| CPU {s.get('cpu_pct', 0):.0f}% "
        f"| {gpu_s} "
        f"| disk {s.get('disk_pct', 0):.0f}%"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Legacy API — preserved for existing callers (forge_capability_benchmark etc.)
# ─────────────────────────────────────────────────────────────────────────────


class ResourceManager:
    def __init__(self):
        self.ollama_port = 11434
        self.docker_cmd = "docker info"
        self.python_path = os.path.expanduser(r"~\miniforge3\python.exe")

    def is_port_open(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def is_docker_running(self) -> bool:
        try:
            subprocess.run(
                self.docker_cmd,
                shell=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            return True
        except Exception:
            return False

    def check_resources(self) -> dict:
        """Combined services + system snapshot. Non-blocking."""
        return {
            "ollama": self.is_port_open(self.ollama_port),
            "docker": self.is_docker_running(),
            "system": get_snapshot(),
            "throttle": should_throttle(),
        }

    def start_ollama(self) -> bool:
        if not self.is_port_open(self.ollama_port):
            print("Demarrage Ollama...")
            try:
                subprocess.Popen(
                    ["ollama", "serve"],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except FileNotFoundError:
                # Try the known install path
                exe = os.path.expanduser(r"~\AppData\Local\Programs\Ollama\ollama.exe")
                if os.path.exists(exe):
                    subprocess.Popen(
                        [exe, "serve"],
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                else:
                    return False
            time.sleep(3)
            return self.is_port_open(self.ollama_port)
        return True

    def start_docker(self) -> bool:
        if not self.is_docker_running():
            print("Docker non lance. Demarrer Docker Desktop manuellement.")
            return False
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Dynamic allocation : Docker, Ollama, llama-server NSSM, request_resources
# ─────────────────────────────────────────────────────────────────────────────

# Cervelet (cerebellum) engines — the two local inference backends Nokido
# can throttle/evict to free RAM. Numbers tuned 2026-05-02.
_OLLAMA_PORT = int(os.environ.get("LAFORGE_OLLAMA_PORT", "11434"))
_OLLAMA_HOST = os.environ.get("LAFORGE_OLLAMA_HOST", "127.0.0.1")
_LLAMACPP_NATIVE_PORT = int(os.environ.get("LAFORGE_LLAMACPP_PORT", "8091"))
_LLAMACPP_NATIVE_HOST = os.environ.get("LAFORGE_LLAMACPP_HOST", "127.0.0.1")
_LLAMACPP_NATIVE_SERVICE = "NokidoLlamaNative"
# Estimated RAM footprint of llama-server :8091 once loaded (qwen-coder 7B q4).
_LLAMACPP_NATIVE_RAM_ESTIMATE_GB = 5.0

# Subprocess flag : keep child windows hidden on Windows, no-op elsewhere.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run_capture(cmd: list[str] | str, *, shell: bool = False, timeout: float = 3.0) -> tuple[int, str, str]:
    """Run a subprocess with hard timeout, return (rc, stdout, stderr).

    Never raises — on any exception returns (-1, "", str(exc)). All new
    functions in this module funnel through here so the timeout/safety
    contract is enforced exactly once.
    """
    try:
        r = subprocess.run(
            cmd,
            shell=shell,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError as exc:
        return -1, "", f"not_found: {exc}"
    except Exception as exc:  # pragma: no cover
        return -1, "", str(exc)


def _powershell(script: str, timeout: float = 3.0) -> tuple[int, str, str]:
    """Run a PowerShell snippet non-interactively. Never raises."""
    return _run_capture(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )


# ── Docker ──────────────────────────────────────────────────────────────────


def docker_status() -> dict[str, Any]:
    """Return Docker Desktop state via ``docker info --format '{{json .}}'``.

    Returns a dict with keys :
        up               : bool — Docker daemon reachable
        containers_running : int — currently running containers
        containers_total : int — all containers (running + stopped)
        memory_used_mb   : int — best-effort, 0 when not retrievable
        memory_limit_mb  : int — Docker MemTotal in MB
        error            : str (only when up=False)

    Non-blocking : 3s timeout. Never raises. If Docker is not installed or the
    daemon is down, returns ``{"up": False, "error": "..."}``.
    """
    rc, out, err = _run_capture(
        ["docker", "info", "--format", "{{json .}}"],
        timeout=3.0,
    )
    if rc != 0 or not out.strip():
        return {"up": False, "error": (err or "docker info failed").strip()[:200]}
    try:
        import json as _json

        info = _json.loads(out.strip().splitlines()[0])
    except Exception as exc:
        return {"up": False, "error": f"parse: {exc}"}
    running = int(info.get("ContainersRunning") or 0)
    total = int(info.get("Containers") or 0)
    mem_total_b = int(info.get("MemTotal") or 0)
    mem_limit_mb = mem_total_b // (1024 * 1024) if mem_total_b else 0
    # `docker info` n'expose PAS la memoire consommee, et `docker stats` par
    # conteneur est trop lent pour un chemin de regulation : ce champ valait donc
    # `0` en dur. Un zero par DEFAUT se lit « charge nulle » et ouvre le garde en
    # silence — la regulation ne pouvait ni peser la prothese ni decider de la
    # couper. On mesure desormais du cote HOTE, la ou la RAM est reellement prise.
    surface = docker_surface_ram()
    return {
        "up": True,
        "containers_running": running,
        "containers_total": total,
        "memory_used_mb": surface["total_mb"],
        "memory_limit_mb": mem_limit_mb,
        "surface_ram": surface,
    }


# Processus composant la surface HOTE de la prothese Docker sous Windows.
_DOCKER_PROCS = ("docker desktop", "com.docker.backend", "com.docker.build",
                 "com.docker.service", "dockerd", "vmmem", "vmmemwsl",
                 "vmmemdockerdesktop", "wslservice", "wslhost")
# MUTUALISES : toute distro WSL les alimente, pas seulement le moteur Docker.
_DOCKER_PROCS_PARTAGES = ("vmmem", "vmmemwsl", "wslservice", "wslhost")


def docker_surface_ram() -> dict[str, Any]:
    """Surface RAM HOTE de la prothese Docker, en Mo, AVEC son incertitude.

    Rend {"total_mb", "partage_mb", "propre_mb", "attribution", "detail",
    "illisibles"}. `attribution` vaut :

      - `MESUREE`     : rien de mutualise ne pese, le total est attribuable ;
      - `INDETERMINE` : `vmmemWSL` (ou un autre partage) pese, et sa part revenant
                        a Docker n'est pas mesurable depuis les comptes de service
                        (`wsl -l -v` rend « Acces refuse ») — on ne presente donc
                        PAS ce total comme acquis ;
      - `ILLISIBLE`   : psutil n'a rien pu lire.

    Trois etats, jamais deux : un processus dont la lecture est refusee est COMPTE
    dans `illisibles`, il ne disparait pas dans un total qui paraitrait complet.

    Mesure 2026-09-05 : 3 719 Mo sur 24 233, dont 2 844 Mo de `vmmemWSL` — soit
    76 % de la surface dans le poste justement mutualise. Docker est une PROTHESE :
    ce chiffre dit ce que sa presence coute, pas la sante d'un organe.
    """
    detail: dict = {}
    illisibles = 0
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return {"total_mb": 0, "partage_mb": 0, "propre_mb": 0,
                "attribution": "ILLISIBLE", "detail": {}, "illisibles": -1,
                "raison": "psutil indisponible"}
    vus = 0
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            nom = (proc.info.get("name") or "").lower()
            if nom.endswith(".exe"):
                nom = nom[:-4]
            if nom not in _DOCKER_PROCS:
                continue
            vus += 1
            mem = proc.info.get("memory_info")
            if mem is None:
                illisibles += 1
                continue
            detail[nom] = detail.get(nom, 0) + int(mem.rss)
        except Exception:  # noqa: BLE001 - process disparu ou acces refuse
            illisibles += 1
    # `vus` compte les processus RECONNUS, `detail` ceux dont la RAM a pu etre LUE.
    # Tester `vus` laissait passer le cas « je les vois tous mais je ne peux en lire
    # aucun » : total 0, attribution MESUREE — soit « 0 mesure » rendu comme
    # « 0 consomme », le faux negatif que ce module doit justement interdire.
    # Defaut attrape par son propre NR le 2026-09-05.
    if not detail and illisibles:
        return {"total_mb": 0, "partage_mb": 0, "propre_mb": 0,
                "attribution": "ILLISIBLE", "detail": {}, "illisibles": illisibles,
                "raison": "%d processus docker vus, aucun lisible" % illisibles}
    en_mo = {k: int(v / (1024 * 1024)) for k, v in detail.items()}
    partage = sum(v for k, v in en_mo.items() if k in _DOCKER_PROCS_PARTAGES)
    total = sum(en_mo.values())
    return {
        "total_mb": total,
        "partage_mb": partage,
        "propre_mb": total - partage,
        "attribution": "INDETERMINE" if partage else "MESUREE",
        "detail": en_mo,
        "illisibles": illisibles,
    }


def _docker_running_ids() -> list[str]:
    """List running container IDs via ``docker ps -q``. Empty list on failure."""
    rc, out, _ = _run_capture(["docker", "ps", "-q"], timeout=3.0)
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _docker_paused_ids() -> list[str]:
    """List paused container IDs via ``docker ps -q --filter status=paused``."""
    rc, out, _ = _run_capture(
        ["docker", "ps", "-q", "--filter", "status=paused"],
        timeout=3.0,
    )
    if rc != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


# Perception organs kept alive even under RAM duress: freezing SearXNG /
# crawl4ai blinds Nokido's web senses and silently kills any running veille.
# Override via env NOKIDO_DOCKER_PAUSE_KEEP (comma-separated name substrings).
_DOCKER_PAUSE_KEEP = tuple(
    s.strip().lower()
    for s in os.environ.get(
        "NOKIDO_DOCKER_PAUSE_KEEP", "searxng,crawl4ai"
    ).split(",")
    if s.strip()
)


def _docker_running_id_names() -> list[tuple[str, str]]:
    """List running containers as (id, name). Empty list on failure."""
    rc, out, _ = _run_capture(
        ["docker", "ps", "--format", "{{.ID}} {{.Names}}"], timeout=3.0
    )
    if rc != 0:
        return []
    pairs: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if parts:
            pairs.append((parts[0], parts[1] if len(parts) > 1 else ""))
    return pairs


def _audit_lifecycle(action: str, domain: str, reason: str = "", **extra) -> None:
    """Trace une action de cycle de vie. Best-effort, jamais fatal.

    L'homeostat ARRETE des charges (modeles, serveurs, conteneurs) sans que rien
    ne le dise : c'est ce qui l'a rendu suspect a chaque enquete alors qu'il
    faisait son travail. Une signature horodatee le disculpe ou l'accuse.
    """
    try:
        from nokido_agent.app.forge_lifecycle_audit import record as _record

        _record(action, domain=domain, reason=reason, **extra)
    except Exception:  # noqa: BLE001
        pass


def get_active_intents() -> dict:
    """Intentions VIVANTES du corps — a consulter AVANT toute eviction.

    Regulation cognitive, pas capacitive (owner 2026-07-23) : un seuil voit des
    Go, pas des intentions. On lit ce que la cognition UTILISE maintenant :
    flag docker.wanted (TTL 900s) + chains de veille actives (agent_chain_nodes
    pending/running). Best-effort, ne leve jamais.
    """
    out: dict = {"docker_wanted": False, "chains_active": 0,
                 "llama_wanted": False, "lmstudio_wanted": False,
                 "rerank_wanted": False}
    _sb = Path(__file__).resolve().parent.parent / "sandbox"
    # MEME mecanisme d'intention que Docker, etendu aux cerveaux souverains
    # (owner 2026-07-26 : « pouvoir lancer et couper a la demande »). Reutilise,
    # pas reinvente : un second mecanisme d'intention aurait donne deux verites.
    # Mesure du jour qui l'a rendu necessaire : le cerveau codeur allume par
    # l'owner a ete evince moins d'une minute plus tard, faute d'intention a
    # consulter -- l'owner allumait, le corps eteignait.
    # rerank.wanted (2026-07-27) : le reranker :8100 immobilisait 6,57 Go EN
    # PERMANENCE avec active_conns=0, maintenant la RAM au-dessus du seuil P1 et
    # bloquant tout spawn du hub. Il est hors du perimetre du keeper (default-deny
    # sur les ports geres 8080/8091) : personne ne pouvait donc le rendre. Il entre
    # ici au MEME vocabulaire que les autres cerveaux souverains -- l'intention se
    # declare d'abord, l'eviction ne suit qu'ensuite. Tant qu'aucun appelant ne pose
    # ce drapeau, le lire ne change RIEN : c'est voulu, on ne coupe pas le rerank du
    # RAG sur une absence de signal.
    # embed.wanted (2026-08-10) : le boot-trim RAM fait demarrer NokidoLlamaEmbed :8099
    # DISABLED. Sans intention a consulter, la regulation ne peut ni lepargner ni savoir
    # que quelquun lattend -- le trou exact deja paye sur llama.wanted (73 arrets en
    # 7,6 j, 312,94 Go rechargees). Le declarant existe cette fois : forge_embed_router
    # pose le drapeau des que le :8099 refuse, donc le lire CHANGE quelque chose.
    for _cle, _fic in (("docker_wanted", "docker.wanted"),
                       ("llama_wanted", "llama.wanted"),
                       ("lmstudio_wanted", "lmstudio.wanted"),
                       ("rerank_wanted", "rerank.wanted"),
                       ("embed_wanted", "embed.wanted")):
        try:
            _wf = _sb / _fic
            _frais = _wf.exists() and (time.time() - _wf.stat().st_mtime) < 900.0
            # ARBITRAGE (2026-09-01) : une intention que le corps REFUSE ne doit pas
            # etre lue comme active, sinon la regulation EPARGNE un pilier que la
            # politique vient d'ecarter -- et le client garde le dernier mot.
            if _frais:
                try:
                    from nokido_agent.app.forge_pillar_arbiter import pilier_accorde

                    _frais = pilier_accorde(_fic, "get_active_intents")
                except Exception as _exc:  # noqa: BLE001 - arbitre absent : intention gardee
                    # `logging` importe ICI : ce module n'expose pas de `logger`
                    # global, et ce handler aurait leve un NameError le jour ou
                    # l'arbitre des piliers devient indisponible -- transformant
                    # une degradation prevue en panne de la lecture d'intentions.
                    # Troisieme occurrence du meme motif le 2026-09-05, celle-ci
                    # trouvee par le garde ajoute pour les deux precedentes.
                    import logging as _lg

                    _lg.getLogger(__name__).debug(
                        "[intentions] arbitre indisponible (%r)", _exc)
            out[_cle] = _frais
        except Exception:  # noqa: BLE001
            pass
        # CONSTATER la lecture aupres du capteur de couplage. Mesure 2026-08-02 :
        # `forge_signal_coupling.couplage()` rendait `lecteurs_constates: 0` sur TOUS
        # les signaux — non pas parce que personne ne lisait, mais parce que personne
        # ne le DECLARAIT. Un capteur de couplage sans observation ne peut designer
        # aucun signal mort : il rendait « aucun probleme » faute de donnees.
        try:
            from nokido_agent.app.forge_signal_coupling import observe_signal

            observe_signal(_fic, consumer="forge_resource_manager.get_active_intents")
        except Exception:  # noqa: BLE001 - muet-ok: constater ne doit jamais gener la regulation
            pass
    try:
        import sqlite3

        from nokido_agent.app.forge_db_path import db_path

        conn = sqlite3.connect(db_path(), timeout=2.0)
        out["chains_active"] = conn.execute(
            "SELECT COUNT(*) FROM agent_chain_nodes WHERE status IN ('pending','running','retry_pending')"
        ).fetchone()[0]
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    return out


def _transduire(signal: str) -> None:
    """Declare que le signal a CHANGE le comportement, pas seulement ete lu.

    Le capteur de couplage distingue LIRE et AGIR : sans cet appel il classe le
    consommateur `DECOY_LECTEUR_PASSIF` — « lit sans agir » — et ne peut pas dire si
    la branche d'effet est vivante ou morte. Mesure 2026-08-02 : les quatre intentions
    sortaient ainsi, alors que celle de llama pilote reellement le renoncement.
    """
    try:
        from nokido_agent.app.forge_signal_coupling import transduce_signal

        transduce_signal(signal, consumer="forge_resource_manager.reclaim_step2b")
    except Exception:  # noqa: BLE001 - muet-ok: constater ne doit jamais gener la regulation
        pass


def docker_pause_all() -> int:
    """Pause running Docker containers to free RAM, EXCEPT perception organs.

    Equivalent of ``docker pause $(docker ps -q)`` but skips containers whose
    name matches ``_DOCKER_PAUSE_KEEP`` (SearXNG / crawl4ai), so pausing under
    RAM duress never blinds Nokido's web senses. Returns the number of
    containers successfully paused. 0 if Docker is down or nothing to pause.
    Never raises.
    """
    intents = get_active_intents()
    if intents.get("docker_wanted") or intents.get("chains_active"):
        # Cognition active (veille en cours / Docker reclame) : geler la
        # perception = sacrifier l'intention pour des Go (incident 23/07).
        # L'eviction doit d'abord viser les residents IDLE.
        _audit_lifecycle("pause_skipped", "docker", "intents actifs: %s" % intents)
        return 0
    pairs = _docker_running_id_names()
    ids = [
        cid
        for cid, name in pairs
        if not any(k in name.lower() for k in _DOCKER_PAUSE_KEEP)
    ]
    if not ids:
        return 0
    try:  # journal d'audit Docker — une pause n'arrete PAS le daemon, mais elle
        # gele des conteneurs : sans trace, elle reste un suspect a chaque enquete.
        from nokido_agent.app.forge_docker_audit import record as _record

        _record("pause", "reclaim RAM (hors organes de perception)", containers=len(ids))
    except Exception:  # noqa: BLE001 - jamais fatal
        pass
    rc, _out, _err = _run_capture(["docker", "pause", *ids], timeout=5.0)
    if rc != 0:
        return 0
    return len(ids)


_DOCKER_RELEASE_REFRACTORY_S = 900.0
_DOCKER_RELEASE_GAIN_MIN_MB = 800
_LAST_DOCKER_RELEASE_TS = 0.0


def docker_release_prothese() -> dict[str, Any]:
    """Eteint la prothese Docker sous detresse RAM. Rend un verdict MOTIVE.

    Pauser les conteneurs ne rend presque rien : la VM WSL et le moteur restent en
    memoire (mesure 2026-09-05 — 3 719 Mo de surface hote, dont 2 844 Mo de
    `vmmemWSL`). Quand `docker_pause_all` n'a pas suffi, l'extinction du moteur est
    le seul levier qui rende vraiment cette RAM.

    Docker est une PROTHESE, pas un organe : l'eteindre n'abime rien, c'est son etat
    nominal quand personne ne la reclame. Trois gardes cumulatifs, et la RAISON est
    toujours rendue — un garde qui refuse sans dire pourquoi se lit comme une panne :

      1. INTENTION  — une demande fraiche (`docker.wanted`) ou une chaine active
         interdit la coupure. Regulation cognitive avant capacitive, comme
         `docker_pause_all`.
      2. GAIN MESURE — on ne coupe pas une prothese pour rendre 200 Mo. Sans surface
         mesurable (`ILLISIBLE`), on s'abstient : le cout des deux erreurs n'est pas
         symetrique, rater une derive laisse un capteur muet, couper a tort aveugle
         les sens web de Nokido (crawl4ai) pour plusieurs minutes.
      3. REFRACTAIRE — un consommateur reposera `docker.wanted` et le keeper
         rallumera. Sans delai, c'est la dent de scie que l'owner interdit
         explicitement : « lancer Docker OUI, le faire BOUCLER NON ».
    """
    global _LAST_DOCKER_RELEASE_TS
    import time as _t

    surface = docker_surface_ram()
    if surface.get("attribution") == "ILLISIBLE":
        return {"fait": False, "raison": "surface RAM illisible -> abstention",
                "surface": surface}
    if surface["total_mb"] < _DOCKER_RELEASE_GAIN_MIN_MB:
        return {"fait": False, "surface": surface,
                "raison": "gain insuffisant (%d Mo < seuil %d Mo)"
                          % (surface["total_mb"], _DOCKER_RELEASE_GAIN_MIN_MB)}
    try:
        intents = get_active_intents()
    except Exception:  # noqa: BLE001
        return {"fait": False, "raison": "intentions illisibles -> abstention"}
    if intents.get("docker_wanted"):
        return {"fait": False, "raison": "docker demande par la cognition",
                "surface": surface}
    if intents.get("chains_active"):
        return {"fait": False, "surface": surface,
                "raison": "travail en cours (%s chaines actives)"
                          % intents["chains_active"]}
    reste = _DOCKER_RELEASE_REFRACTORY_S - (_t.monotonic() - _LAST_DOCKER_RELEASE_TS)
    if _LAST_DOCKER_RELEASE_TS and reste > 0:
        return {"fait": False, "surface": surface,
                "raison": "refractaire anti-sawtooth (%.0f s restantes)" % reste}
    try:
        from nokido_agent.app.forge_docker_agent import release_daemon
    except Exception as exc:  # noqa: BLE001
        return {"fait": False, "surface": surface,
                "raison": "release_daemon indisponible (%s)" % type(exc).__name__}
    detail = release_daemon()
    _LAST_DOCKER_RELEASE_TS = _t.monotonic()
    _audit_lifecycle("release", "docker",
                     "detresse RAM : surface %d Mo (%s), aucune intention"
                     % (surface["total_mb"], surface["attribution"]),
                     surface_mb=surface["total_mb"],
                     attribution=surface["attribution"])
    return {"fait": True, "surface": surface, "detail": detail}


def docker_unpause_all() -> int:
    """Unpause every paused Docker container.

    Returns the number of containers successfully unpaused. 0 if Docker is
    down or none paused. Never raises.
    """
    ids = _docker_paused_ids()
    if not ids:
        return 0
    rc, _out, _err = _run_capture(["docker", "unpause", *ids], timeout=5.0)
    if rc != 0:
        return 0
    return len(ids)


# ── Ollama ──────────────────────────────────────────────────────────────────


def _http_get_json(url: str, timeout: float = 3.0) -> Any | None:
    """GET a URL, parse JSON, return None on any error. Lazy stdlib import."""
    try:
        import json as _json
        from urllib.request import Request, urlopen  # noqa: WPS433

        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = resp.read()
        return _json.loads(data.decode("utf-8", errors="replace"))
    except Exception:
        return None


def ollama_loaded_models() -> list[dict[str, Any]]:
    """Query Ollama ``GET /api/ps`` for currently loaded models.

    Returns a list of dicts ``[{name, size_gb, processor, context, until}]``
    sorted by ``until`` (oldest expiry first → least recently used / soonest
    to be evicted). ``size_gb`` is the in-memory size, ``context`` is
    ``context_length`` if exposed, ``processor`` is the GPU/CPU ratio string.

    Returns ``[]`` if Ollama is not reachable on :11434, never raises.
    """
    payload = _http_get_json(f"http://{_OLLAMA_HOST}:{_OLLAMA_PORT}/api/ps", timeout=3.0)
    if not isinstance(payload, dict):
        return []
    raw = payload.get("models") or []
    out: list[dict[str, Any]] = []
    for m in raw:
        try:
            name = m.get("name") or m.get("model") or "?"
            size_b = int(m.get("size") or m.get("size_vram") or 0)
            details = m.get("details") or {}
            ctx = m.get("context_length") or details.get("context_length") or 0
            processor = m.get("processor") or m.get("size_vram_pct") or ""
            until = m.get("expires_at") or m.get("until") or ""
            out.append(
                {
                    "name": name,
                    "size_gb": round(size_b / 1024**3, 2) if size_b else 0.0,
                    "processor": str(processor),
                    "context": int(ctx) if ctx else 0,
                    "until": str(until),
                }
            )
        except Exception:
            continue
    # LRU-ish : oldest "until" first, empty strings last.
    out.sort(key=lambda d: (d["until"] == "", d["until"]))
    return out


def _ollama_children_rss_gb() -> float:
    """RSS cumule des runners enfants de ollama.exe, en Go. -1.0 = pas pu voir.

    C'est la SEULE mesure qui dit si un dechargement a libere quoi que ce
    soit : Ollama peut sortir un modele de sa comptabilite (/api/ps vide)
    sans tuer le process qui porte la RAM (mesure 26-07, runner de 5.59 Go
    survivant a un unload rendu « reussi »).
    """
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return -1.0
    total = 0.0
    vu = False
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() not in ("ollama.exe", "ollama"):
                continue
            for child in proc.children(recursive=True):
                try:
                    total += float(child.memory_info().rss) / (1024 ** 3)
                    vu = True
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            continue
    return round(total, 2) if vu else 0.0


def ollama_unload(model: str) -> bool:
    """Unload a specific model from Ollama VRAM/RAM.

    Uses ``ollama stop <model>`` subprocess (3s timeout). Returns True on
    success, False on any error (model not loaded, ollama CLI missing, etc).
    Never raises.
    """
    if not model or not isinstance(model, str):
        return False

    _rss_avant = _ollama_children_rss_gb()
    # In-process d'abord (API /api/generate keep_alive=0) : le chemin CLI `ollama stop`
    # depend du PATH du compte service ET d'un subprocess -- sous pression RAM le gate
    # P1 differe les spawns, donc l'eviction perdait son remede au moment exact ou il
    # fallait agir (mesure 2026-07-25 : noop a 87-90% pendant qu'un modele residait).
    try:
        import json as _json
        import urllib.request as _ur

        req = _ur.Request(
            f"http://{_OLLAMA_HOST}:{_OLLAMA_PORT}/api/generate",
            data=_json.dumps({"model": model, "keep_alive": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with _ur.urlopen(req, timeout=6.0) as r:
            if 200 <= int(getattr(r, "status", 0) or 0) < 300:
                return _rss_libere(_rss_avant)
    except Exception:
        pass
    rc, _out, _err = _run_capture(["ollama", "stop", model], timeout=3.0)
    return _rss_libere(_rss_avant) if rc == 0 else False


def _rss_libere(avant: float, seuil_gb: float = 0.5) -> bool:
    """L'EFFET, pas le code retour : la RAM des runners a-t-elle baisse ?

    Mesure 26-07 : /api/generate keep_alive=0 a rendu HTTP 200 et le modele
    a bien quitte /api/ps, mais le runner a survecu avec 5.59 Go. L'eviction
    rapportait donc « ollama_unload:deepseek-coder:6.7b(5.66GB) » comme une
    action reussie pendant que la pression RAM ne bougeait pas d'un octet,
    puis retombait en noop faute de modele a decharger. Un remede qui ne
    soulage rien ne doit pas se declarer efficace.

    avant < 0 (mesure indisponible) -> on ne peut pas trancher : on fait
    confiance au code retour plutot que d'accuser a tort.
    """
    if avant < 0:
        return True
    import time as _t

    _t.sleep(2.0)  # laisser au runner le temps de rendre la main
    apres = _ollama_children_rss_gb()
    if apres < 0:
        return True
    return (avant - apres) >= seuil_gb


# ── llama-server :8091 (NSSM service NokidoLlamaNative) ────────────────────


def llamacpp_native_status() -> dict[str, Any]:
    """Query NSSM service ``NokidoLlamaNative`` (llama-server) state.

    Le port vient de ``LAFORGE_LLAMACPP_PORT`` (defaut 8091), PAS d'un littéral :
    les mentions « :8091 » ci-dessous ne sont qu'une valeur par defaut. Cette sonde
    reste volontairement mono-service — elle repond « ce service-la tourne-t-il ? »,
    jamais « un llama-server tourne-t-il quelque part ? ». Pour la seconde question,
    c'est `_heavy_evictable_services()` qui part des process REELS : une sonde par
    port ne voit que ce qui a ete prevu a l'ecriture (le « keeper aveugle » de
    juillet), et un glouton de 5.59 GB sur un autre port lui reste invisible.

    Returns a dict :
        running       : bool — service reports Running via Get-Service
        port_listening: bool — :8091 has a LISTEN socket via Get-NetTCPConnection
        ram_gb        : float — RSS of the owning process (0 if not found)
        pid           : int — owning process PID (0 if not found)

    Non-blocking : single PowerShell call, 3s timeout. Never raises.
    """
    # QUATRE PREUVES INDEPENDANTES, AUCUNE DEDUITE D'UNE AUTRE (contrat owner
    # 2026-09-05, A0-2). Elles sont prises par `psutil` et NON par PowerShell :
    # mesure du jour, `_powershell` rend `rc=-1` depuis le compte du hub, donc
    # l'ancienne sonde tombait TOUJOURS sur son defaut `running: False,
    # port_listening: False, ram_gb: 0` — indistinguable d'un coder mort. Elle
    # n'a donc jamais rien mesure depuis ce contexte, et l'arbitre lisait « pas de
    # coder » a chaque appel. `psutil` fonctionne ici pour le port et le process,
    # et LEVE une exception nommee (`AccessDenied`) pour le service : un refus
    # explicite vaut infiniment mieux qu'un `False` muet.
    svc, svc_raison = _preuve_service_coder()
    port, pid_port = _preuve_port_coder()
    proc, ram_gb = _preuve_process_coder(pid_port, port)
    data = {"ram_gb": ram_gb, "pid": pid_port, "service_raison": svc_raison}
    http = _sonde_http_coder() if port == "OUI" else "INCONNU"
    # VERDICT COMPOSITE : `running` ne se deduit d'AUCUNE preuve isolee.
    # Le service peut etre STOPPED alors que le binaire tourne hors supervision
    # (c'est le cas nominal du reveil on-demand) : le service ne prouve donc PAS
    # la mort. Seule la conjonction port+process (et l'HTTP quand il est joignable)
    # etablit qu'un coder SERT.
    # L'ETAT DU SERVICE N'ENTRE PAS DANS LE VERDICT DE LIVENESS. C'est une preuve
    # de GESTION (ce que le gestionnaire declare), pas de SERVICE RENDU : un
    # service RUNNING sans port ni process ne sert personne, et un service STOPPED
    # coexiste avec un binaire lance hors supervision — c'est meme le mode nominal
    # du reveil on-demand. Le faire peser ici, c'est deduire une preuve d'une autre,
    # ce que le contrat interdit. Il reste RAPPORTE, jamais determinant.
    if port == "OUI" and proc == "OUI" and http in ("OUI", "INCONNU"):
        verdict = "VIVANT"
        raison = "port en ecoute + process vivant" + (
            " + http OK" if http == "OUI" else " (http non concluant)")
    elif port == "NON" and proc == "NON":
        verdict = "MORT"
        raison = "aucun port en ecoute, aucun process porteur (service=%s)" % svc
    else:
        verdict = "INCERTAIN"
        raison = "preuves partielles (service=%s port=%s process=%s http=%s)" % (
            svc, port, proc, http)
    return {
        # Compat : `running` garde son sens HISTORIQUE — l'etat du SERVICE NSSM —
        # et rien d'autre. Le nom a induit en erreur assez longtemps pour qu'on
        # cesse de lui faire dire « le coder tourne » : c'est `verdict` qui le dit.
        "running": svc == "RUNNING",
        "port_listening": port == "OUI",
        "ram_gb": float(data.get("ram_gb") or 0.0),
        "pid": int(data.get("pid") or 0),
        "service": svc,
        "service_raison": str(data.get("service_raison") or ""),
        "port": port,
        "process": proc,
        "http": http,
        "verdict": verdict,
        "raison": raison,
    }


def _preuve_service_coder() -> tuple:
    """Etat du SERVICE NSSM : RUNNING / STOPPED / ABSENT / INCONNU (+ raison).

    Un service STOPPED ne prouve PAS que le coder est mort : le reveil on-demand
    lance le binaire HORS supervision, c'est son mode nominal. Cette preuve dit
    seulement ce que le gestionnaire de services declare.
    """
    try:
        import psutil as _ps

        return ("RUNNING" if _ps.win_service_get(_LLAMACPP_NATIVE_SERVICE).status()
                == "running" else "STOPPED"), ""
    except Exception as exc:  # noqa: BLE001
        nom = type(exc).__name__
        if "NoSuchProcess" in nom or "NoSuchService" in nom:
            return "ABSENT", "service non declare"
        # AccessDenied sous compte sandbox : REFUS, pas absence. Mesure du jour —
        # `Get-Service` rendait « INTROUVABLE » ici et `Stopped` sous SYSTEM.
        return "INCONNU", nom


def _preuve_port_coder() -> tuple:
    """Le port ecoute-t-il ? OUI / NON / INCONNU, plus le pid proprietaire."""
    try:
        import psutil as _ps

        for c in _ps.net_connections(kind="tcp"):
            if c.status == "LISTEN" and c.laddr and c.laddr.port == _LLAMACPP_NATIVE_PORT:
                return "OUI", int(c.pid or 0)
        return "NON", 0
    except Exception:  # noqa: BLE001 - enumeration refusee : on ne tranche pas
        return "INCONNU", 0


def _preuve_process_coder(pid: int, port_etat: str) -> tuple:
    """Le porteur du port est-il vivant ? OUI / NON / INCONNU, plus son RSS.

    N'est PAS deduite du port : un socket peut survivre brievement a son process,
    et un pid peut etre illisible sans etre mort (cf. `UNKNOWN != NO`).
    """
    if pid <= 0:
        return ("NON", 0.0) if port_etat == "NON" else ("INCONNU", 0.0)
    try:
        import psutil as _ps

        p = _ps.Process(pid)
        return "OUI", round(p.memory_info().rss / (1024 ** 3), 2)
    except Exception as exc:  # noqa: BLE001
        return ("NON", 0.0) if "NoSuchProcess" in type(exc).__name__ else ("INCONNU", 0.0)


def _sonde_http_coder() -> str:
    """Le coder REPOND-il ? OUI / NON / INCONNU — jamais deduit du port.

    Un port en ecoute prouve un TRANSPORT, pas une CAPACITE : le socket peut etre
    tenu par un process qui charge encore son modele. C'est la distinction
    TRANSPORT != APPLICATIF de la constitution semantique.
    """
    import urllib.error
    import urllib.request

    url = "http://127.0.0.1:%s/health" % _LLAMACPP_NATIVE_PORT
    try:
        with urllib.request.urlopen(url, timeout=2.0) as r:
            return "OUI" if 200 <= getattr(r, "status", 200) < 500 else "NON"
    except urllib.error.HTTPError:
        # Le serveur a REPONDU, meme en erreur applicative : il est joignable.
        return "OUI"
    except Exception:  # noqa: BLE001 - injoignable OU sonde empechee : on ne tranche pas
        return "INCONNU"


def llamacpp_native_stop() -> bool:
    """Stop llama-server :8091 — par le SUPERVISEUR, puis par le PORT servi.

    Refonte 2026-07-26 : les DEUX chemins d'origine etaient morts, et leur echec
    conjoint est la raison pour laquelle l'eviction rendait `noop` pendant que le
    gate P1 bloquait toute la machine a 87-90 % (mesure repetee CINQ fois ce jour,
    trace `llamacpp_native_stop:failed(non-admin?)`).

      * NSSM `Stop-Service` exige l'admin, qu'AUCUN compte client ne possede :
        `LaForgeTrusted` n'a meme pas SeDebugPrivilege — son « trusted » qualifie
        la revue du CODE, pas des droits systeme.
      * Le repli psutil filtrait sur `cmdline`, or `psutil.cmdline()` leve
        AccessDenied sur 308 process sur 308 depuis un compte de service (mesure
        26-07, deja documentee le 17-07 : « meme sous le compte owner »). La
        chaine testee etait donc TOUJOURS vide et le test ne matchait JAMAIS.
        Un repli qui ne peut pas voir n'est pas un repli.

    Deux corrections, aucune invention :
      1. DEMANDER AU SUPERVISEUR — il a spawne le process, il en a les droits.
         Meme chemin que `_supervisor_sleep_non_essential` ci-dessus.
      2. Identifier par CAPACITE SERVIE (le port), regle posee le 17-07 apres le
         « keeper aveugle » et deja implementee dans
         `forge_llama_keeper._serving_pids` : le port se demande a l'OS sans ACL.
    """
    import urllib.request as _ur

    # Chemin 1 : le proprietaire du process.
    try:
        req = _ur.Request(
            f"{_SUPERVISOR_URL}/sleep/{_LLAMACPP_NATIVE_SERVICE}",
            method="POST",
            headers=_supervisor_auth_headers(),
        )
        with _ur.urlopen(req, timeout=8.0) as r:
            if 200 <= int(getattr(r, "status", 0) or 0) < 300:
                return True
    except Exception:  # noqa: BLE001 - on tente le repli, sans masquer l'echec
        pass

    # Chemin 2 : qui ECOUTE le port gere. Jamais le nom, jamais la cmdline.
    if not _PSUTIL_OK:
        return False
    killed = False
    try:
        for c in psutil.net_connections("tcp"):
            if (c.status == "LISTEN" and c.laddr and c.pid
                    and int(c.laddr.port) == _LLAMACPP_NATIVE_PORT):
                try:
                    psutil.Process(int(c.pid)).kill()
                    killed = True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    except Exception:  # noqa: BLE001
        pass
    return killed


def llamacpp_native_start() -> bool:
    """Start the ``NokidoLlamaNative`` NSSM service via ``Start-Service``.

    Will fail if non-admin. Returns True on success, False on error.
    Never raises.
    """
    # ACCOLADES : dans une f-string, `{{` rend `{` et `}}` rend `}`. La forme
    # historique ecrivait `}}}}` et `{{{{`, donc PowerShell recevait
    # `... 'OK' }} catch {{ 'ERR' }}` -- un script INVALIDE. Mesure 2026-07-26 :
    # ParserError « Le bloc Catch ou Finally manque dans l'instruction Try ».
    # rc != 0 systematique => cette fonction rendait TOUJOURS False, quel que
    # soit le compte : le corps savait ARRETER son cerveau codeur (echelle
    # d'eviction, etape 2b) sans jamais pouvoir le RALLUMER. Une regulation a
    # sens unique se lit comme une panne de privileges ; c'etait une accolade.
    script = (
        f"try {{ Start-Service -Name '{_LLAMACPP_NATIVE_SERVICE}' -ErrorAction Stop; 'OK' }} catch {{ 'ERR' }}"
    )
    rc, out, _err = _powershell(script, timeout=10.0)
    return rc == 0 and "OK" in (out or "")


# ── Smart allocator ─────────────────────────────────────────────────────────


# ── LM STUDIO : rendre la RAM des MODELES sans tuer le serveur ──────────────
# MESURE 2026-08-18 : 5,7 Go tenus par les modeles residents, sur une machine a
# 98,5 % — Docker refuse par le garde d'admission, veille bloquee. Le plus gros
# consommateur du parc n'etait dans AUCUN chemin de liberation : ni service
# supervise (il n'existe pas de `NokidoLMStudio`), ni reclaimer.
#
# `unload` et non `stop` : un reclaimer rend du RECONSTRUCTIBLE et ne casse rien
# (contrat de `run_reclaimers`, qui tourne sans garde cognitif). Decharger laisse
# le serveur :1234 vivant et joignable — il rechargera a la demande — donc le
# slot de routage `lmstudio_native` survit a la liberation. Arreter le serveur
# reste possible, mais c'est une EVICTION, pas une reclamation :
# `nokido_ensure_service{lmstudio, stopped}`.
_LMSTUDIO_PORT = 1234
_LMSTUDIO_IDLE_DERNIER = 0.0


def _lmstudio_sert() -> bool:
    """Y a-t-il un serveur sur :1234 ? Question posee a l'OS, jamais au nom du
    process : `psutil.cmdline()` leve AccessDenied sur 308 process sur 308
    depuis un compte de service (mesure 2026-07-26)."""
    try:
        with socket.create_connection(("127.0.0.1", _LMSTUDIO_PORT), timeout=1.0):
            return True
    except Exception:  # noqa: BLE001 - port ferme = rien a rendre
        return False


def lmstudio_unload_all() -> float:
    """Decharge les modeles LM Studio. Rend les Go REELLEMENT liberes.

    LM Studio est per-user : l'ordre ne vaut que dans la session console de
    l'owner (`forge_owner_bridge`, deja ecrit pour Docker/WSL, qui posent le
    meme probleme). Lance sous SYSTEM, il chercherait les modeles dans
    `config\\systemprofile` et ne trouverait rien a decharger.
    """
    if not _lmstudio_sert():
        return 0.0
    avant = _free_now()
    try:
        import sys as _sys
        _t = str(Path(__file__).resolve().parent.parent / "tools")
        if _t not in _sys.path:  # chemin chaud : un insert par appel gonflerait sys.path
            _sys.path.insert(0, _t)
        # 1) La tache planifiee : SEUL canal mesure qui s'execute sous l'identite
        #    de l'owner. Le pont, lui, rend `laforgetrusted` et se fait refuser
        #    l'acces au profil (mesure 2026-08-18).
        from nokido_agent.tools.forge_ensure_service import declencher_tache

        if declencher_tache("Nokido-LMStudio-Unload") is None:
            # 2) Repli : le pont. Il echouera tant que l'ACL du profil ferme le
            #    binaire, mais un canal qui echoue en le DISANT vaut mieux qu'un
            #    zero silencieux qu'on lirait « rien a rendre ».
            from nokido_agent.tools.forge_owner_bridge import run_in_owner

            profil = os.environ.get("LAFORGE_OWNER_PROFILE", r"%USERPROFILE%")
            run_in_owner([" || ".join([
                "lms unload --all",
                f'"{profil}\\.lmstudio\\bin\\lms.exe" unload --all',
            ])], timeout=45.0)
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning(
            "[lmstudio] unload impossible (%s) | consequence: ces Go restent "
            "tenus, la pression RAM ne baissera pas par ici", type(e).__name__)
        return 0.0
    time.sleep(2.0)  # la RAM se rend apres le retour du CLI, pas pendant
    # Le delta MESURE, jamais la taille annoncee du modele : un unload qui
    # echoue en rendant 0 doit se voir comme 0, sinon on croit avoir fait de la
    # place et on autorise un spawn qui fera tomber la machine.
    return max(0.0, round(_free_now() - avant, 2))


def lmstudio_arret_si_inactif() -> dict:
    """Coupe LM Studio quand il ne sert plus a rien.

    POLITIQUE OWNER (2026-08-18) : « lance-le quand c'est utile, coupe-le des que
    plus necessaire ». L'arret est donc INCONDITIONNEL a la pression memoire :
    attendre 85 % de RAM pour rendre 5,7 Go inutiles reviendrait a garder le cout
    tant que la machine respire encore — c'est l'inverse de la consigne.

    Trois abstentions explicites, chacune pour un motif distinct :
      * il ne sert pas -> rien a faire ;
      * Nokido ne l'a pas allume -> c'est l'outil de l'owner, on n'y touche pas ;
      * aucun usage date -> « je ne sais pas » n'est pas « inactif ».
    """
    if not _lmstudio_sert():
        return {"action": "noop", "raison": "ne sert pas"}
    try:
        import sys as _sys
        _t = str(Path(__file__).resolve().parent.parent / "tools")
        if _t not in _sys.path:
            _sys.path.insert(0, _t)
        from nokido_agent.tools.forge_ensure_service import _INACTIVITE_S, ensure, est_pilote, inactif_depuis
    except Exception as e:  # noqa: BLE001
        return {"action": "noop", "raison": f"pilotage hors de portee ({type(e).__name__})"}

    if not est_pilote("lmstudio"):
        return {"action": "noop",
                "raison": "allume hors Nokido : ne pas retirer l'outil de l'owner"}
    depuis = inactif_depuis("lmstudio")
    if depuis is None:
        return {"action": "noop", "raison": "aucun usage date : NON MESURE, pas inactif"}
    if depuis < _INACTIVITE_S:
        # DECLARANT MANQUANT DE `lmstudio.wanted` (mesure 2026-08-25).
        # `forge_signal_coupling` rendait ce signal DECOY_LECTEUR_PASSIF avec ZERO
        # emetteur connu : `_evict_conditions_met` le LIT pour epargner LM Studio, et
        # comme personne ne le posait, le lire ne changeait RIEN. Or l'usage est DEJA
        # mesure ici — `inactif_depuis` rend des secondes. Un fait mesure fait un bien
        # meilleur emetteur qu'une intention devinee : « il a servi il y a N s » EST la
        # preuve que quelqu'un le veut, et c'est le seul moment ou on peut le dire.
        try:
            import sys as _s2

            _a = str(Path(__file__).resolve().parent)
            if _a not in _s2.path:
                _s2.path.insert(0, _a)
            from nokido_agent.app.forge_embed_router import declare_wanted as _dw

            _dw("lmstudio.wanted",
                motif="usage mesure il y a %d s (< seuil %d s)"
                      % (int(depuis), int(_INACTIVITE_S)))
        except Exception as _ie:  # noqa: BLE001
            logging.getLogger(__name__).debug(
                "[lmstudio] intention NON posee (%s) — il reste evincable alors qu'il "
                "vient de servir", type(_ie).__name__)
        return {"action": "noop",
                "raison": f"utilise il y a {int(depuis)} s (seuil {int(_INACTIVITE_S)} s)"}
    r = ensure("lmstudio", "stopped") or {}
    logging.getLogger(__name__).info(
        "[lmstudio] coupe apres %d s sans usage | %s", int(depuis), r.get("detail"))
    _audit_lifecycle("stop", "llm", "inactif depuis %d s (politique : allume "
                     "seulement quand utile)" % int(depuis), target="lmstudio")
    return {"action": "stopped", "inactif_s": int(depuis), "detail": r.get("detail")}


# Declare A L'IMPORT, pas depuis un appelant : le 2026-08-03,
# `reclaimers_declares()` rendait `[]` — le mecanisme existait, personne ne
# s'etait enregistre. Un levier qui depend de la memoire d'un appelant est
# precisement celui qu'on decouvre absent le jour de la saturation.
register_reclaimer("lmstudio_models", lmstudio_unload_all)


def _evict_conditions_met() -> dict:
    """Faut-il ARMER l'eviction par capacite ? (consultation souveraine 2026-07-26)

    Rend {"ok", "raison", "libre_gb", "libre_pct"} -- la RAISON et pas seulement
    un booleen : un garde qui refuse sans dire pourquoi se lit comme une panne.

    Conditions, dans l'ordre ou elles sont verifiees :
      1. URGENCE MESUREE, jamais supposee -- moins de 2.5 Go libres OU moins de
         15 % libres, lus EN DIRECT (psutil). L'instantane publie est proscrit
         ici : c'est cette lecture perimee qui faisait decider sur une photo
         d'avant l'action (corrige le 2026-07-26).
      2. AUCUN TRAVAIL EN COURS -- une chaine active ou une demande Docker
         vivante interdisent d'evincer. Regulation cognitive, pas capacitive.

    La 3e condition de l'avis -- « les leviers NOMMES n'ont pas suffi » -- est
    STRUCTURELLE, donc pas re-testee ici : l'echelle de `request_resources`
    execute ollama_unload puis llamacpp_native_stop AVANT ce palier ; s'ils
    avaient suffi, le palier ne serait pas atteint. La re-tester serait inventer
    une mesure la ou l'ordre d'execution fait deja preuve.

    Toute incertitude (memoire ou intentions illisibles) rend False : le cout des
    deux erreurs n'est pas symetrique -- rater une derive laisse un capteur muet,
    endormir un organe utile tue le RAG.
    """
    try:
        import psutil

        vm = psutil.virtual_memory()
        libre_gb = float(vm.available) / (1024 ** 3)
        libre_pct = 100.0 - float(vm.percent)
    except Exception:  # noqa: BLE001
        return {"ok": False, "raison": "memoire non mesurable -> abstention"}

    etat = {"libre_gb": round(libre_gb, 2), "libre_pct": round(libre_pct, 1)}
    if libre_gb >= _EVICT_URGENCE_LIBRE_GB and libre_pct >= _EVICT_URGENCE_LIBRE_PCT:
        return {"ok": False, "raison": "pas d'urgence (%.2f Go / %.1f %% libres, "
                                       "seuil %.2f Go / %.1f %%)"
                % (libre_gb, libre_pct,
                   _EVICT_URGENCE_LIBRE_GB, _EVICT_URGENCE_LIBRE_PCT), **etat}
    try:
        intents = get_active_intents()
    except Exception:  # noqa: BLE001
        return {"ok": False, "raison": "intentions illisibles -> abstention", **etat}
    if intents.get("chains_active"):
        return {"ok": False, "raison": "travail en cours (%s chaines actives)"
                % intents["chains_active"], **etat}
    if intents.get("docker_wanted"):
        return {"ok": False, "raison": "docker demande par la cognition", **etat}
    if intents.get("llama_wanted") or intents.get("lmstudio_wanted"):
        return {"ok": False, "raison": "cerveau souverain voulu a la demande "
                                       "(llama.wanted / lmstudio.wanted)", **etat}
    return {"ok": True, "raison": "urgence mesuree (%.2f Go / %.1f %% libres), aucun travail en cours"
            % (libre_gb, libre_pct), **etat}


def _publish_evict_trace(cand: dict, libre_avant: float, libre_apres: float, raison: str) -> None:
    """Trace OBLIGATOIRE d'une eviction dynamique (avis AGY 2026-07-26).

    Porte le pid, le composant, la raison, et le differentiel RAM MESURE APRES
    l'action -- pas estime. Cle UNIQUE par evenement : la table fait un upsert
    sur (zone, key), donc une cle fixe ferait remplacer chaque trace par la
    suivante -- et une trace qui ecrase la precedente n'est plus une trace.

    Best-effort : un echec de publication ne bloque jamais la regulation, le
    journal lifecycle ayant deja consigne l'acte.
    """
    try:
        import json as _json

        from nokido_agent.app.forge_swarm_blackboard import _write_fact

        _write_fact(
            "discovered_facts",
            "evict_dynamic_trace:%s:%d" % (cand.get("service", "?"), int(time.time())),
            _json.dumps({
                "service": cand.get("service"),
                "pid": cand.get("pid"),
                "process": cand.get("name"),
                "ram_gb_attendu": cand.get("ram_gb"),
                "raison": raison,
                "libre_gb_avant": round(float(libre_avant), 2),
                "libre_gb_apres": round(float(libre_apres), 2),
                "delta_gb_mesure": round(float(libre_apres) - float(libre_avant), 2),
            }, ensure_ascii=False),
            "regulation", 0.9, "RESOURCE_MANAGER")
    except Exception:  # noqa: BLE001
        pass


def _heavy_evictable_services(min_ram_gb: float = 1.0) -> list[dict]:
    """Gros consommateurs RAM qu'on a le DROIT d'endormir, identifiés par CAPACITÉ.

    Mesuré 2026-07-24 : l'échelle d'éviction rendait `noop` trois fois de suite
    alors que le glouton était un llama-server de 5.59 GB — invisible parce que
    `llamacpp_native_status()` ne connaît QUE le port 8091, et parce que
    `_SUPERVISOR_NON_ESSENTIAL` est une liste de NOMS figée. Identifier par port
    ou par nom, c'est le « keeper aveugle » de juillet : ça rate tout ce qui n'a
    pas été prévu à l'écriture.

    Ici on part des process RÉELS, on demande au registre à QUI ils sont, et on
    demande au world-model si les arrêter est sans conséquence. Trois abstentions
    volontaires — un process qu'on n'arrive pas à rattacher à un service, un
    service qu'on ne sait pas juger, un verdict autre que `safe` — sont laissées
    tranquilles : le coût d'évincer à tort (organe sain arrêté) dépasse celui de
    refuser un spawn.
    """
    # DESARME PAR DEFAUT (2026-07-24, apres degat mesure). Journal lifecycle :
    # cette selection a endormi NokidoQdrantServer (10:06), NokidoLlamaEmbed
    # (10:28) et NokidoLlamaReranker (11:55) — les TROIS piliers du RAG :
    # vecteurs, embeddings, reranking. Le monde-modele les juge `safe` parce
    # qu'aucun service ne DECLARE en dependre, et le filtre « rechargeable » les
    # autorise parce que ce sont des llama-server. Deux heuristiques justes
    # separement, fausses ensemble.
    #
    # Le manque n'est pas un filtre de plus : c'est qu'aucune source ne dit
    # quelles CAPACITES un service porte. Tant qu'elle n'existe pas, refuser un
    # spawn (comportement d'avant) coute infiniment moins cher qu'eteindre le RAG.
    # CONDITIONNEMENT (consultation souveraine du 2026-07-26 ; avis complet au
    # blackboard, discovered_facts/evict_dynamic_consultation_20260726). AGY :
    # « pas d'activation brute par defaut, mais conditionnement automatique sous
    # garde stricte ». D'ou trois etats plutot qu'un tout-ou-rien :
    #   "0" / absent   -> DESARME (defaut inchange : aucun changement aujourd'hui)
    #   "conditioned"  -> ARME SOUS GARDE : urgence mesuree + intentions consultees
    #   "1"            -> historique, SANS condition (conserve pour compatibilite)
    # Le mode conditionne est pret et testable ; le basculer reste une decision
    # owner, et l'avis demande 24 h d'activite sans recidive avant tout defaut
    # permanent (le correctif du capteur perime date du jour meme).
    # ARME EN MODE CONDITIONNE — decision owner du 2026-08-03. L'avis souverain du
    # 26/07 disait « pret et testable ; le basculer reste une decision owner » : elle
    # est prise. Le defaut passe de "0" (desarme) a "conditioned", PAS a "1" : les
    # gardes de `_evict_conditions_met` restent tous exiges -- urgence LUE EN DIRECT
    # (< 2,5 Go ou < 15 % libres), aucune chaine active, aucune intention posee -- et
    # `is_critical` continue d'ecarter les piliers du RAG. Essai a blanc le jour meme,
    # a 5,50 Go libres : 0 candidat, refus motive « pas d'urgence ». C'est bien un
    # armement SOUS GARDE, pas une ouverture.
    _mode = os.environ.get("LAFORGE_EVICT_DYNAMIC", "conditioned").strip().lower()
    if _mode not in ("1", "conditioned", "auto"):
        return []
    if _mode in ("conditioned", "auto"):
        _cond = _evict_conditions_met()
        if not _cond.get("ok"):
            _audit_lifecycle("evict_skipped", "service",
                             "conditions non reunies: " + str(_cond.get("raison")),
                             target="_heavy_evictable_services")
            return []
    out: list[dict] = []
    # Capacité RECHARGEABLE : seuls les porteurs de modèle LLM sont évinçables, car
    # ils se rechargent à la demande sans rien perdre. Un moteur d'index ou une base
    # (qdrant, sqlite) porte de l'ÉTAT : l'endormir casse ses lecteurs.
    #
    # Sans ce filtre, la première version de cette fonction retenait comme unique
    # candidat NokidoQdrantServer (1.2 Go) — jugé `safe` par le world-model faute de
    # dépendant DÉCLARÉ — et épargnait le llama-server de 4.82 Go : elle aurait cassé
    # la recherche dense du RAG pour libérer six fois moins de mémoire. Le graphe des
    # dépendances de services.toml ne voit pas les capacités consommées applicativement.
    reloadable = {"llama-server.exe", "ollama.exe", "lms.exe", "llama-server", "ollama"}
    try:
        import psutil

        # 1. À qui appartiennent les ports ? (registre superviseur = SSoT)
        try:
            import sys as _s

            _app = os.path.dirname(os.path.abspath(__file__))
            if _app not in _s.path:
                _s.path.insert(0, _app)
            from nokido_agent.app.forge_port_reconcile import _is_descendant, _supervisor_ports

            claimed = _supervisor_ports()  # {port: (service, pid)}
        except Exception:  # noqa: BLE001
            return []
        if not claimed:
            return []  # registre muet -> on ne devine pas

        by_pid: dict[int, str] = {}
        for _port, (svc, spid) in claimed.items():
            by_pid[int(spid)] = svc

        try:
            from nokido_agent.app.forge_body_world_model import predict_impact
        except Exception:  # noqa: BLE001
            return []  # sans anticipation, on n'évince rien

        seen: set[str] = set()
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                _mi = proc.info["memory_info"]
                # MEME GRANDEUR QUE LE CAPTEUR (forge_service_rss_watch, mesure
                # 2026-08-19) : sous Windows `rss` est le WORKING SET, donc une
                # grandeur PAGINABLE. Plus l'OS paginait un process gourmand, plus il
                # paraissait petit -- le selecteur devenait aveugle exactement dans le
                # cas qu'il existe pour voir. Un capteur et un effecteur qui ne
                # mesurent pas la meme chose ne peuvent pas se repondre.
                _prive = getattr(_mi, "private", None)
                rss = float(_prive or _mi.rss) / (1024 ** 3)
            except Exception:  # noqa: BLE001
                continue
            if rss < min_ram_gb:
                continue
            if (proc.info.get("name") or "").lower() not in reloadable:
                continue  # porte de l'état -> pas notre affaire
            pid = int(proc.info["pid"])
            svc = by_pid.get(pid)
            if svc is None:
                # Le registre note parfois un LAUNCHER dont l'ENFANT tient le port.
                for spid, sname in by_pid.items():
                    try:
                        if _is_descendant(pid, spid, 3):
                            svc = sname
                            break
                    except Exception:  # noqa: BLE001
                        continue
            if not svc or svc in seen:
                continue  # non rattaché = on s'abstient
            # TROISIEME source, celle qui manquait le 24-07 : ce que le service SERT.
            # `predict_impact` ne voit que les dependances DECLAREES (ordre de
            # demarrage) et le filtre process ne voit qu'un nom d'executable ; ni
            # l'un ni l'autre ne sait que ce llama-server porte l'embedding de tout
            # le RAG. Sans cette consultation, l'eviction avait endormi Qdrant,
            # l'embedder et le reranker en deux heures.
            try:
                from nokido_agent.app.forge_service_capabilities import is_critical, why_critical

                if is_critical(svc):
                    # EXEMPTION COGNITIVE (owner 2026-08-20 : « sous condition
                    # cognitive du corps »). Une capacite critique ne se protege
                    # plus parce qu'elle porte une ETIQUETTE, mais parce qu'elle
                    # SERT une pensee EN COURS. C'est la doctrine deja ecrite dans
                    # `get_active_intents` (« regulation cognitive, pas capacitive »)
                    # et dans `arbitrer_pression` (« l'organe qui sert garde sa
                    # place ») — elle n'avait jamais ete branchee ICI.
                    # MESURE QUI L'A RENDUE NECESSAIRE (2026-08-20) : 61 evictions
                    # de detresse en 7 jours, TOUTES avortees sur cette exemption,
                    # pendant que la RAM saturait. Le regulateur voyait le probleme
                    # et s'interdisait d'agir sur ses deux seules cibles utiles —
                    # « exemption = zone non balayee ».
                    # FAIL-SAFE INTEGRAL : toute mesure impossible => on PROTEGE,
                    # exactement comme `coder_conns < 0` protege plus haut. On
                    # n'evince JAMAIS sur une non-mesure.
                    _sert, _pourquoi = True, "mesure indisponible -> prudence"
                    # URGENCE VITALE — clause ajoutee le 2026-08-20 APRES avoir vu
                    # mon propre garde a l'oeuvre : « eviction refusee: cognition
                    # active (chains=5) » a 98,8 % de RAM et 0,29 Go libre.
                    # Proteger la pensee en laissant mourir la machine qui la porte
                    # n'est pas de la protection, c'est du deni. Le reste du code
                    # connait deja cette notion (`REFRACTAIRE OUTREPASSE ... < seuil
                    # vital`) ; elle manquait ICI. Sous le seuil, la cognition ne
                    # protege plus : un modele evince se RECHARGE, pas un OOM.
                    try:
                        _libre_gb = psutil.virtual_memory().available / (1024 ** 3)
                    except Exception:  # noqa: BLE001
                        _libre_gb = None
                    _vital = _libre_gb is not None and _libre_gb < _EVICT_SEUIL_VITAL_GB
                    if _vital:
                        _sert = False
                        _pourquoi = ("URGENCE VITALE : %.2f Go libres < %.2f — "
                                     "protection cognitive outrepassee"
                                     % (_libre_gb, _EVICT_SEUIL_VITAL_GB))
                        _audit_lifecycle("evict_urgence_vitale", "service",
                                         why_critical(svc) + " MAIS " + _pourquoi,
                                         target=svc)
                    try:
                        _ch = 0 if _vital else int(
                            (get_active_intents() or {}).get("chains_active") or 0)
                        if _vital:
                            pass  # verdict deja pose : on ne reconsulte pas la cognition
                        elif _ch > 0:
                            _pourquoi = "%d chaine(s) cognitive(s) active(s)" % _ch
                        else:
                            _etab = [c for c in psutil.Process(pid).net_connections(kind="inet")
                                     if c.status == "ESTABLISHED"]
                            if _etab:
                                _pourquoi = "%d connexion(s) etablie(s)" % len(_etab)
                            else:
                                _sert = False
                                _pourquoi = "aucune chaine active, aucune connexion etablie"
                    except Exception:  # noqa: BLE001
                        _sert, _pourquoi = True, "usage illisible -> prudence"
                    if _sert:
                        _audit_lifecycle("evict_skipped", "service",
                                         why_critical(svc) + " — " + _pourquoi,
                                         target=svc)
                        continue
                    # Critique MAIS inactif : il redevient candidat. Il reste soumis
                    # a TOUS les gardes en aval (predict_impact != safe -> intouchable),
                    # donc ceci ouvre une porte, ca n'en force aucune.
                    _audit_lifecycle("evict_critique_inactif", "service",
                                     why_critical(svc) + " MAIS " + _pourquoi
                                     + " -> candidat rechargeable", target=svc)
            except Exception:  # noqa: BLE001
                # Sans la source des capacites, on ne peut pas juger -> s'abstenir.
                continue

            try:
                verdict = (predict_impact(svc, "stop") or {}).get("verdict")
            except Exception:  # noqa: BLE001
                continue
            if verdict != "safe":
                continue  # essentiel ou dépendants -> intouchable
            seen.add(svc)
            out.append({"service": svc, "pid": pid, "ram_gb": round(rss, 2),
                        "name": proc.info.get("name")})
    except Exception:  # noqa: BLE001
        return []
    out.sort(key=lambda d: d["ram_gb"], reverse=True)
    return out


def _sleep_service_verdict(service: str) -> tuple[bool, str]:
    """Endort UN service via le superviseur (son propriétaire), jamais par kill.

    Rend (accepte, motif). Avant (2026-09-27) toute exception rendait False sans trace :
    un 401 -- l'appelant n'a pas le jeton, un REFUS DE POLITIQUE -- se lisait comme
    « rien a endormir », et l'eviction affichait `['noop']`. DISABLED_BY_POLICY !=
    RESOURCE_UNAVAILABLE : le refus se nomme. Accepte != atteint : l'appelant remesure."""
    import urllib.error as _ue
    import urllib.request as _ur

    headers = _supervisor_auth_headers()
    try:
        req = _ur.Request(f"{_SUPERVISOR_URL}/sleep/{service}", method="POST", headers=headers)
        with _ur.urlopen(req, timeout=4):
            return True, "ACCEPTE"
    except _ue.HTTPError as e:
        if e.code in (401, 403):
            return False, "REFUS_POLITIQUE(HTTP %d%s)" % (
                e.code, "" if "Authorization" in headers else ", jeton absent de l'appelant")
        return False, "HTTP %d" % e.code
    except Exception as e:  # noqa: BLE001
        return False, "SUPERVISEUR_INJOIGNABLE(%s)" % type(e).__name__


def _sleep_service(service: str) -> bool:
    """Forme booleenne historique de `_sleep_service_verdict`."""
    return _sleep_service_verdict(service)[0]


_last_pillar_restart_ts: float = 0.0
# Cooldown LARGE : cycler un pilier en boucle = le pompage des 312 Go du 2026-07-30.
_PILLAR_RESTART_COOLDOWN_S = float(os.environ.get("LAFORGE_PILLAR_RESTART_COOLDOWN_S", "600"))
# Seuil de BLOAT : on restart un pilier RAG quand son RSS dépasse ce cap. Mesuré le
# 2026-08-06 : la baseline SAINE de l'embedder est ~2,7 Go et il DÉRIVE en continu sous
# charge (7,72 Go au repos observé, 12,1 Go en pic). Le seuil initial de 8 Go RATAIT la
# dérive de 7,72 (elle passait juste dessous, régulation muette à 87 % RAM). Abaissé à
# 6 Go sur ordre owner « faire marcher la régulation » : un embedder au-delà de 6 Go est
# déjà 2,2x sa baseline = du KV/bloat récupérable par un restart (reload BGE-M3 en s).
# Le reranker (~6,5 Go quand chargé) est on-demand ; s'il apparaît ici c'est qu'il est
# chargé ET que la RAM est en détresse (garde _evict_conditions_met), donc éligible.
_PILLAR_BLOAT_GB = float(os.environ.get("LAFORGE_PILLAR_BLOAT_GB", "6.0"))


def _service_est_vivant(service: str) -> bool:
    """Le registre du superviseur voit-il ce service avec un pid ?

    Le registre est l'autorite d'identite d'un service (pid + start_time) : on ne la
    devine pas depuis une liste de process. Rend False AUSSI quand le registre est
    illisible -- mais le DIT dans le journal, parce qu'un capteur qui confond
    "absent" et "je n'ai pas pu regarder" fabrique des faux negatifs indetectables.
    """
    import json as _j
    import logging as _lg
    import urllib.request as _ur

    _log = _lg.getLogger(__name__)
    for _essai in range(_WAKE_VERIFY_TRIES):
        try:
            with _ur.urlopen(f"{_SUPERVISOR_URL}/status", timeout=5) as r:
                _d = _j.loads(r.read())
        except Exception as exc:  # noqa: BLE001
            _log.warning("[wake] registre du superviseur illisible (%s) : ni vivant "
                         "ni mort, on s'abstient de conclure", type(exc).__name__)
            return False
        if ((_d.get("services") or {}).get(service) or {}).get("pid"):
            return True
        time.sleep(_WAKE_VERIFY_DELAY_S)
    return False


def _wake_service(service: str) -> bool:
    """Réveille UN service via le superviseur (POST /wake) — miroir de _sleep_service."""
    try:
        import urllib.request as _ur

        req = _ur.Request(f"{_SUPERVISOR_URL}/wake/{service}", method="POST",
                          headers=_supervisor_auth_headers())
        with _ur.urlopen(req, timeout=_WAKE_TIMEOUT_S):
            return True
    except Exception:  # noqa: BLE001
        # MESURE 2026-08-25 : la route /supervisor/wake rend `ok: true` de facon
        # INCONDITIONNELLE (supervisor.ts L1925) -- elle ne refuse JAMAIS. Un echec
        # ici n'etait donc pas un refus mais une attente ecourtee : le superviseur
        # ne repond qu'APRES avoir relance le service, ce qui depasse 4 s des qu'un
        # llama-server recharge son modele. Quatre `restart_failed` en 7 jours ont
        # annonce "wake refuse -- pilier a risque" sur des reveils qui aboutissaient,
        # et un pilier declare a risque a tort appelle des remedes qui, eux, coutent.
        # On ne conclut donc plus depuis notre propre impatience : on VERIFIE.
        return _service_est_vivant(service)


def _restart_pillar(service: str) -> bool:
    """RESTART gouverné d'un pilier récupérable = sleep (stop -> RAM rendue) puis wake
    (spawn frais -> RSS baseline). Le superviseur reste propriétaire ; jamais de kill.
    Rend True seulement si le réveil est accepté — sinon l'organe resterait endormi et
    l'appelant DOIT le journaliser en échec."""
    if not _sleep_service(service):
        return False
    time.sleep(1.0)
    return _wake_service(service)


def _bloated_recoverable_pillars(min_ram_gb: float) -> list[dict]:
    """Piliers RAG CRITIQUES *mais* rechargeables (llama-server) dont le RSS a ballonné.

    Symétrique EXACT de `_heavy_evictable_services` : là on ÉCARTE les `is_critical`
    (on ne les endort pas) ; ici on ne garde QU'EUX — car un pilier ne s'endort pas,
    il se RESTART (le sleep+wake purge le bloat et le rend en secondes).

    Motif mesuré 2026-08-06 : l'embedder :8099 à 12,1 Go était le glouton, mais
    `is_critical` l'écartait de toute éviction -> `request_resources` rendait `noop`
    à 89 % de RAM. Le corps n'avait aucun levier sur son propre plus gros porteur.
    """
    reloadable = {"llama-server.exe", "ollama.exe", "lms.exe", "llama-server", "ollama"}
    out: list[dict] = []
    try:
        import psutil

        try:
            from nokido_agent.app.forge_port_reconcile import _is_descendant, _supervisor_ports

            claimed = _supervisor_ports()
        except Exception:  # noqa: BLE001
            return []
        if not claimed:
            return []
        by_pid: dict[int, str] = {int(spid): svc for _p, (svc, spid) in claimed.items()}
        try:
            from nokido_agent.app.forge_service_capabilities import is_critical
        except Exception:  # noqa: BLE001
            return []  # sans la source des capacités, on ne devine pas un pilier
        seen: set[str] = set()
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                _mi = proc.info["memory_info"]
                # Meme correction qu'a l'etage `_heavy_evictable_services` : on mesure
                # l'engagement prive, pas le working set paginable.
                _prive = getattr(_mi, "private", None)
                rss = float(_prive or _mi.rss) / (1024 ** 3)
            except Exception:  # noqa: BLE001
                continue
            if rss < min_ram_gb:
                continue
            if (proc.info.get("name") or "").lower() not in reloadable:
                continue
            pid = int(proc.info["pid"])
            svc = by_pid.get(pid)
            if svc is None:
                for spid, sname in by_pid.items():
                    try:
                        if _is_descendant(pid, spid, 3):
                            svc = sname
                            break
                    except Exception:  # noqa: BLE001
                        continue
            if not svc or svc in seen:
                continue
            try:
                # is_critical OU pilier RAG NOMMÉ (embed/rerank) : mesuré 2026-08-06,
                # NokidoLlamaEmbed est marqué essential=False par le superviseur donc
                # is_critical rend False -> Step 2d le RATAIT alors qu'il est LE plus
                # gros porteur (7,72 Go). Restart d'un llama-server embed/rerank est
                # toujours sûr (reload à la baseline), donc on le capte quel que soit
                # le flag. Le cerveau CHAT (:8091, non-embed) reste hors de cette liste.
                _pilier = is_critical(svc) or any(
                    _k in svc.lower() for _k in ("embed", "rerank"))
                if not _pilier:
                    continue  # ni critique ni embed/rerank -> _heavy_evictable s'en charge
            except Exception:  # noqa: BLE001
                continue
            seen.add(svc)
            out.append({"service": svc, "pid": pid, "ram_gb": round(rss, 2)})
    except Exception:  # noqa: BLE001
        return []
    out.sort(key=lambda d: d["ram_gb"], reverse=True)
    return out


def _free_now() -> float:
    """RAM libre MESUREE a l'instant, pas l'etat publie.

    MESURE 2026-07-26 : `get_snapshot()` ne mesure rien — il rend l'instantane
    PUBLIE par l'echantillonneur, rafraichi a SON rythme. Verifier l'effet d'une
    eviction avec lui revient a relire une photo prise AVANT l'action : apres avoir
    libere 4,82 Go (arret REEL du llama-server, confirme par la chute 85,2 % ->
    55,8 % et 3,51 -> 10,46 Go libres), le planificateur annoncait encore
    « manque 0,78 Go ».
    Deux consequences, la seconde pire que la premiere :
      1. un refus de spawn injustifie ;
      2. les etapes SUIVANTES continuent d'evincer sur cette lecture perimee — le
         corps se coupe des organes dont il n'a plus besoin de se couper.
    C'est la regle « verifier l'EFFET, pas la commande » appliquee au capteur
    lui-meme : une sonde ponctuelle ne vaut que si elle est FRAICHE.
    """
    try:
        import psutil as _ps

        return float(_ps.virtual_memory().available) / (1024 ** 3)
    except Exception:  # noqa: BLE001 — sans psutil, l'etat publie vaut mieux que rien
        return float(get_snapshot().get("ram_free_gb") or 0.0)


# ── DELEGATION AU HUB (owner 2026-09-28 : « pas d'impasse sur la securite, reste conforme
# au RFC et a l'authentification mise en place ») ─────────────────────────────────────────
# Mesure : hors du hub, un processus (compte bac a sable, run_job, CLI) n'a pas le jeton du
# superviseur dans son environnement ; ses ordres de sommeil rendaient 401. Lui donner ce
# jeton ferait d'un DEMANDEUR un proprietaire (CONTROL != OWNERSHIP) et distribuerait un
# porteur statique. On fait l'inverse : l'appelant DECLARE un besoin au hub, qui tient deja
# le controle, et c'est le hub qui choisit quoi rendre, sous sa propre politique. L'appelant
# ne nomme jamais une victime.
#
# Authentification : celle en place, rien de plus. L'appelant presente l'identite d'organe
# de `forge_hub_client.entetes_organe` (jamais le maitre) ; le hub la resout par
# `_exiger_identite`. Statuts : 401 + WWW-Authenticate (RFC 6750 section 3), 403
# `insufficient_scope` (RFC 6750 section 3.1) quand le ring ne porte pas l'eviction, 429 +
# Retry-After (RFC 6585 section 4) pendant un refractaire ou une eviction deja en cours.
_DELEGATION_RING_MAX_EVICTION = 3
_DELEGATION_MAX_GB = float(os.environ.get("LAFORGE_DELEGATION_MAX_GB", "12"))
_DELEGATION_REFRACTAIRE_S = float(os.environ.get("LAFORGE_DELEGATION_REFRACTAIRE_S", "30"))
_DELEGATION_TIMEOUT_S = float(os.environ.get("LAFORGE_DELEGATION_TIMEOUT_S", "90"))
_DELEGATION_VERROU = threading.Lock()
_DELEGATION_DERNIERE: dict[str, float] = {}


def decider_demande_deleguee(principal: str, ring: int, corps: Any) -> tuple[int, dict, dict]:
    """Decision de `POST /api/resource/request` : (statut HTTP, corps JSON, en-tetes).

    Le hub n'y ajoute aucune politique : il authentifie (`_exiger_identite`) puis appelle
    ceci HORS de sa boucle. DECLARER un besoin (verification seule) est ouvert a tout organe
    authentifie ; EVINCER exige ring <= 3 -- un demandeur ring 4 (SERVICES, agents non
    fiables) ne fait pas endormir des organes en le demandant. Un refractaire par principal
    et un verrou global bornent le pompage : deux echelles concurrentes evinceraient deux
    fois pour un seul manque. Accepte != atteint : `ok` dit si la RAM libre REMESUREE couvre
    le besoin."""
    if not isinstance(corps, dict):
        return 400, {"ok": False, "error": "invalid_request",
                     "detail": "corps JSON objet attendu"}, {}
    if "bail" in corps:
        return _decider_bail(principal, ring, corps.get("bail"))
    try:
        besoin = float(corps.get("needed_ram_gb"))
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "invalid_request",
                     "detail": "needed_ram_gb numerique requis"}, {}
    # `not 0 < x <= max` ecarte aussi NaN : toute comparaison avec NaN est fausse.
    if not 0 < besoin <= _DELEGATION_MAX_GB:
        return 400, {"ok": False, "error": "invalid_request",
                     "detail": "needed_ram_gb hors de ]0, %g]" % _DELEGATION_MAX_GB}, {}
    if corps.get("allow_evict") is not True:
        res = dict(request_resources(besoin, allow_evict=False, deleguer=False))
        res.update(delegue="hub", principal=principal)
        return 200, res, {}
    if ring > _DELEGATION_RING_MAX_EVICTION:
        _audit_lifecycle("delegation_refusee", "ram", "eviction demandee par %s (ring %d)"
                         % (principal, ring), target=principal, needed_gb=besoin)
        return 403, {"ok": False, "error": "insufficient_scope",
                     "detail": "eviction reservee au ring <= %d (%s est ring %d)"
                               % (_DELEGATION_RING_MAX_EVICTION, principal, ring)}, {
            "WWW-Authenticate": 'Bearer realm="nokido-hub", error="insufficient_scope", '
                                'error_description="eviction requires ring <= %d"'
                                % _DELEGATION_RING_MAX_EVICTION}
    if not _DELEGATION_VERROU.acquire(blocking=False):
        return 429, {"ok": False, "error": "eviction_en_cours", "retry_after_s": 5}, {
            "Retry-After": "5"}
    try:
        # Le refractaire se lit SOUS le verrou : lu avant, deux demandes du meme principal
        # le franchiraient ensemble.
        reste = _DELEGATION_REFRACTAIRE_S - (time.time()
                                             - _DELEGATION_DERNIERE.get(principal, 0.0))
        if reste > 0:
            return 429, {"ok": False, "error": "refractaire",
                         "retry_after_s": int(reste) + 1}, {"Retry-After": str(int(reste) + 1)}
        _DELEGATION_DERNIERE[principal] = time.time()
        res = dict(request_resources(besoin, allow_evict=True, deleguer=False))
    finally:
        _DELEGATION_VERROU.release()
    _audit_lifecycle("delegation", "ram", "eviction demandee au hub par %s (ring %d)"
                     % (principal, ring), target=principal, needed_gb=besoin,
                     ok=bool(res.get("ok")))
    res.update(delegue="hub", principal=principal)
    return 200, res, {}


def _resultat_sans_action(needed: float, motif: str, etat: str) -> dict:
    """Resultat FINAL d'une delegation qui n'a rien fait ici : on remesure, on n'agit pas."""
    libre = _free_now()
    return {"ok": libre >= needed, "action": [motif], "delegue": etat, "freed_gb": 0.0,
            "before_free": libre, "after_free": libre,
            "missing_gb": round(max(0.0, needed - libre), 2)}


# ── Bail de priorite (owner 2026-10-06) ──────────────────────────────────────────────────────────
# Owner : « les taches prioritaires doivent prendre le dessus, tout en gardant a l'esprit qu'une fois
# finies elles ne doivent pas empecher le redemarrage de ce qui a ete interrompu a tort ; les
# intentions doivent etre conservees, avec une notion de travail long / travail court ». Mesure du
# 2026-10-04 : la CI GitHub de 0.20.8 tuee deux fois par des timeouts d'E/S disque tant que
# NokidoDeportEmbed lisait ~76 Mo/s ; endormi a la main par un agent, l'essai suivant etait vert.
# Le bail rend ce geste au CORPS. La tache prioritaire DECLARE (motif, court|long, ttl) ; le hub
# CHOISIT qui cede -- jamais l'appelant --, INSCRIT chaque interrompu avec son intention et son
# travail, et le REVEILLE a la liberation, ou a l'EXPIRATION si la tache meurt sans liberer.
# OBSERVATION par defaut (journaliser ce qui aurait cede) : armer = `sandbox/bail_priorite.switch`
# contenant « arme », ou LAFORGE_BAIL_PRIORITE=1. Observer avant d'enforcer.
_BAUX_DIR = Path(__file__).resolve().parent.parent / "sandbox" / "baux_priorite"
_BAIL_SWITCH = Path(__file__).resolve().parent.parent / "sandbox" / "bail_priorite.switch"
_SERVICES_TOML = Path(__file__).resolve().parent.parent / "proxy_deno" / "core" / "services.toml"
_BAIL_TTL_MAX_S = {"court": 3600.0, "long": 4 * 3600.0}
_BAIL_LONG_SILENCE_MAX_S = 900.0  # un bail long qui ne se renouvelle pas en 15 min expire
_BAIL_SEUIL_IO_MBS = float(os.environ.get("LAFORGE_BAIL_SEUIL_IO_MBS", "5"))
_BAIL_SEUIL_CPU_PCT = float(os.environ.get("LAFORGE_BAIL_SEUIL_CPU_PCT", "20"))
_BAIL_FENETRE_COUT_S = 3.0
# Travail des interrompus. LONG : un travail de fond qui reprend ou il en etait -- a reveiller ET a
# verifier. COURT : un passage periodique qui se rattrape au tick suivant. Listes curatees, MESUREES ;
# tout autre service est INCONNU, jamais range « court » par defaut (INCONNU != NON), et il est
# reveille comme un long.
_TRAVAIL_LONG = frozenset({"NokidoDeportEmbed", "NokidoIngestDaemon"})
_TRAVAIL_COURT = frozenset({"NokidoRSSWatcher", "NokidoCapture"})
_BAUX_VERROU = threading.Lock()
_BAUX_DERNIER = 0.0


def _bail_arme() -> bool:
    if os.environ.get("LAFORGE_BAIL_PRIORITE") == "1":
        return True
    try:
        return _BAIL_SWITCH.read_text(encoding="utf-8").strip().lower() == "arme"
    except OSError:
        return False


def _travail(service: str) -> str:
    return "long" if service in _TRAVAIL_LONG else "court" if service in _TRAVAIL_COURT else "INCONNU"


def _services_du_toml() -> dict | None:
    """{nom: declaration} de services.toml ; None si illisible (jamais {} : vide != illisible)."""
    try:
        import tomllib

        d = tomllib.loads(_SERVICES_TOML.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - illisible, dit par l'appelant
        return None
    brut = d.get("services") or d.get("service") or []
    liste = brut.values() if isinstance(brut, dict) else brut
    return {v["name"]: v for v in liste if isinstance(v, dict) and v.get("name")}


def _statut_superviseur() -> dict | None:
    """{service: etat} du registre du superviseur ; None si illisible."""
    import json as _j
    import urllib.request as _ur

    try:
        with _ur.urlopen(f"{_SUPERVISOR_URL}/status", timeout=5) as r:
            return (_j.loads(r.read()) or {}).get("services") or {}
    except Exception:  # noqa: BLE001
        return None


def _cout_des_pids(pids: dict) -> dict:
    """{service: (E/S Mo/s, CPU %)} mesures sur une fenetre, enfants compris ; absent = illisible."""
    if not _PSUTIL_OK:
        return {}

    def _arbre(pid):
        try:
            p = psutil.Process(pid)
            return [p] + p.children(recursive=True)
        except Exception:  # noqa: BLE001
            return []

    def _releve(procs):
        io = cpu = 0.0
        for p in procs:
            try:
                c = p.io_counters()
                io += c.read_bytes + c.write_bytes
                t = p.cpu_times()
                cpu += t.user + t.system
            except Exception:  # noqa: BLE001
                continue
        return io, cpu

    arbres = {svc: _arbre(pid) for svc, pid in pids.items()}
    avant = {svc: _releve(a) for svc, a in arbres.items() if a}
    time.sleep(_BAIL_FENETRE_COUT_S)
    out = {}
    for svc, (io0, cpu0) in avant.items():
        io1, cpu1 = _releve(arbres[svc])
        out[svc] = ((io1 - io0) / _BAIL_FENETRE_COUT_S / 2 ** 20,
                    100.0 * (cpu1 - cpu0) / _BAIL_FENETRE_COUT_S)
    return out


def _candidats_bail() -> tuple[list | None, str]:
    """Qui CEDERAIT a une tache prioritaire : (liste, motif). Liste None = illisible, et dit pourquoi.

    Non essentiel ET sans neverSleep au TOML, jamais un porteur de capacite critique
    (`forge_service_capabilities`, la garde deja opposee au sommeil RAM), vivant au registre du
    superviseur, et COUTEUX maintenant (E/S ou CPU mesures au-dessus du seuil) : on n'endort pas
    un service qui ne gene pas la tache prioritaire."""
    toml = _services_du_toml()
    if toml is None:
        return None, "services.toml ILLISIBLE"
    etat = _statut_superviseur()
    if etat is None:
        return None, "registre du superviseur ILLISIBLE"
    try:
        from nokido_agent.app.forge_service_capabilities import is_critical
    except Exception:  # noqa: BLE001 - sans la garde des capacites, on s'abstient
        return None, "forge_service_capabilities INDISPONIBLE : aucune garde des capacites critiques"
    pids = {}
    for nom, decl in toml.items():
        if decl.get("essential") is not False or decl.get("neverSleep") or decl.get("disabled"):
            continue
        pid = ((etat.get(nom) or {}).get("pid"))
        if not pid:
            continue
        try:
            if is_critical(nom):
                continue
        except Exception:  # noqa: BLE001 - verdict indisponible = on s'abstient pour ce service
            continue
        pids[nom] = int(pid)
    couts = _cout_des_pids(pids)
    out = []
    for nom, (io, cpu) in sorted(couts.items(), key=lambda kv: -(kv[1][0] + kv[1][1] / 10.0)):
        if io < _BAIL_SEUIL_IO_MBS and cpu < _BAIL_SEUIL_CPU_PCT:
            continue
        decl = toml.get(nom) or {}
        out.append({"service": nom, "pid": pids[nom], "io_mbs": round(io, 1), "cpu_pct": round(cpu, 1),
                    "intention": decl.get("intention"), "objectif": decl.get("objectif"),
                    "travail": _travail(nom)})
    return out, "%d candidat(s) sur %d non-essentiel(s) vivant(s), %d sans cout mesurable" % (
        len(out), len(pids), len(pids) - len(couts))


def _lire_baux() -> list:
    import json as _j

    out = []
    try:
        fichiers = sorted(_BAUX_DIR.glob("bail_*.json"))
    except OSError:
        return out
    for f in fichiers:
        try:
            out.append(_j.loads(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - un bail illisible ne s'invente pas
            continue
    return out


def _ecrire_bail(bail: dict) -> None:
    import json as _j

    _BAUX_DIR.mkdir(parents=True, exist_ok=True)
    cible = _BAUX_DIR / ("%s.json" % bail["id"])
    tmp = cible.with_suffix(".tmp")
    tmp.write_text(_j.dumps(bail, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, cible)


def _expire_le(bail: dict) -> float:
    fin = bail["cree_le"] + bail["ttl_s"]
    if bail.get("classe") == "long":
        fin = min(fin, bail.get("renouvele_le", bail["cree_le"]) + _BAIL_LONG_SILENCE_MAX_S)
    return fin


def services_tenus_par_un_bail(sauf: str | None = None) -> set:
    """Services endormis par un bail ACTIF (autre que `sauf`) : ni le reveil RAM ni la liberation
    d'un autre bail ne doivent les rendre pendant qu'une tache prioritaire en a besoin."""
    return {s["service"] for b in _lire_baux() if b.get("etat") == "ACTIF" and b.get("id") != sauf
            for s in b.get("interrompus", []) if s.get("endormi")}


def acquerir_bail(principal: str, motif: str, classe: str = "court", ttl_s: float = 3600.0) -> dict:
    """La tache prioritaire declare ; le hub choisit, inscrit et (arme) endort. Rend le bail."""
    candidats, note = _candidats_bail()
    arme = _bail_arme()
    maintenant = time.time()
    bail = {"id": "bail_%d_%s" % (int(maintenant), os.urandom(3).hex()), "principal": principal,
            "motif": str(motif)[:200], "classe": classe, "ttl_s": float(ttl_s), "cree_le": maintenant,
            "renouvele_le": maintenant, "mode": "ARME" if arme else "OBSERVATION", "etat": "ACTIF",
            "selection": note, "interrompus": []}
    if candidats is None:
        bail.update(etat="ILLISIBLE", interrompus=[])
        _audit_lifecycle("bail_illisible", "priorite", "%s : %s" % (principal, note), target=principal)
        return bail
    with _BAUX_VERROU:
        for c in candidats:
            if arme:
                ok, pourquoi = _sleep_service_verdict(c["service"])
                c.update(endormi=bool(ok), motif_sommeil=pourquoi)
            else:
                c.update(endormi=False, motif_sommeil="OBSERVATION : aurait cede")
            bail["interrompus"].append(c)
        bail["expire_le"] = _expire_le(bail)
        _ecrire_bail(bail)
    _audit_lifecycle("bail_acquis", "priorite", "%s (%s, %s) : %s" % (
        principal, classe, bail["mode"], [c["service"] for c in bail["interrompus"]]),
        target=principal, bail=bail["id"])
    return bail


def renouveler_bail(principal: str, ident: str) -> tuple[int, dict]:
    with _BAUX_VERROU:
        bail = next((b for b in _lire_baux() if b.get("id") == ident), None)
        if bail is None or bail.get("etat") != "ACTIF":
            return 404, {"ok": False, "error": "bail_inconnu_ou_clos", "id": ident}
        if bail.get("principal") != principal:
            return 403, {"ok": False, "error": "bail_d_un_autre", "id": ident}
        bail["renouvele_le"] = time.time()
        bail["expire_le"] = _expire_le(bail)
        _ecrire_bail(bail)
    return 200, {"ok": True, "bail": bail}


def liberer_bail(ident: str, raison: str = "LIBERE", principal: str | None = None) -> tuple[int, dict]:
    """Rend ce qui a ete interrompu : reveille chaque service ENDORMI par ce bail, sauf s'il est
    tenu par un autre bail actif, et VERIFIE qu'il vit (accepte != atteint)."""
    with _BAUX_VERROU:
        bail = next((b for b in _lire_baux() if b.get("id") == ident), None)
        if bail is None or bail.get("etat") != "ACTIF":
            return 404, {"ok": False, "error": "bail_inconnu_ou_clos", "id": ident}
        if principal is not None and bail.get("principal") != principal:
            return 403, {"ok": False, "error": "bail_d_un_autre", "id": ident}
        tenus = services_tenus_par_un_bail(sauf=ident)
        for s in bail.get("interrompus", []):
            if not s.get("endormi"):
                continue
            if s["service"] in tenus:
                s["reprise"] = "TENU_PAR_UN_AUTRE_BAIL"
                continue
            accepte = _wake_service(s["service"])
            s["reprise"] = "VIVANT" if _service_est_vivant(s["service"]) else (
                "ACCEPTE_NON_VERIFIE" if accepte else "REFUSE")
        bail.update(etat=raison, clos_le=time.time())
        _ecrire_bail(bail)
    _audit_lifecycle("bail_" + raison.lower(), "priorite", "%s : %s" % (
        bail.get("principal"), [(s["service"], s.get("reprise")) for s in bail.get("interrompus", [])
                                if s.get("endormi")]), target=bail.get("principal"), bail=ident)
    return 200, {"ok": True, "bail": bail}


def expirer_baux() -> list:
    """Une tache prioritaire morte ne garde pas le corps endormi : tout bail echu est libere."""
    echus = [b["id"] for b in _lire_baux() if b.get("etat") == "ACTIF" and time.time() > _expire_le(b)]
    for ident in echus:
        liberer_bail(ident, raison="EXPIRE")
    return echus


def _decider_bail(principal: str, ring: int, demande) -> tuple[int, dict, dict]:
    """Decision de `POST /api/resource/request` avec un corps `{"bail": {...}}`."""
    if not isinstance(demande, dict) or demande.get("action") not in ("acquerir", "renouveler", "liberer", "etat"):
        return 400, {"ok": False, "error": "invalid_request",
                     "detail": "bail.action attendu : acquerir | renouveler | liberer | etat"}, {}
    action = demande["action"]
    if action == "etat":
        return 200, {"ok": True, "arme": _bail_arme(),
                     "actifs": [b for b in _lire_baux() if b.get("etat") == "ACTIF"]}, {}
    if action in ("renouveler", "liberer"):
        ident = str(demande.get("id") or "")
        code, corps = (renouveler_bail(principal, ident) if action == "renouveler"
                       else liberer_bail(ident, "LIBERE", principal=principal))
        return code, corps, {}
    if "services" in demande or "victimes" in demande:
        return 400, {"ok": False, "error": "invalid_request",
                     "detail": "le demandeur ne nomme jamais qui cede : le hub choisit"}, {}
    classe = demande.get("classe", "court")
    if classe not in _BAIL_TTL_MAX_S:
        return 400, {"ok": False, "error": "invalid_request", "detail": "classe : court | long"}, {}
    try:
        ttl = float(demande.get("ttl_s", _BAIL_TTL_MAX_S[classe]))
    except (TypeError, ValueError):
        ttl = float("nan")
    if not 0 < ttl <= _BAIL_TTL_MAX_S[classe]:
        return 400, {"ok": False, "error": "invalid_request",
                     "detail": "ttl_s hors de ]0, %g] pour un bail %s" % (_BAIL_TTL_MAX_S[classe], classe)}, {}
    # En OBSERVATION le bail n'endort rien : tout organe authentifie peut mesurer qui AURAIT cede.
    # Mesure du 2026-10-06 : un job detache (identite d'organe sans nom) recevait 403, donc la CI de
    # reference -- lancee en job -- ne pouvait meme pas OBSERVER. Arme, le ring <= 3 reste exige.
    if _bail_arme() and ring > _DELEGATION_RING_MAX_EVICTION:
        return 403, {"ok": False, "error": "insufficient_scope",
                     "detail": "bail ARME reserve au ring <= %d (%s est ring %d)"
                               % (_DELEGATION_RING_MAX_EVICTION, principal, ring)}, {
            "WWW-Authenticate": 'Bearer realm="nokido-hub", error="insufficient_scope", '
                                'error_description="priority lease requires ring <= %d"'
                                % _DELEGATION_RING_MAX_EVICTION}
    bail = acquerir_bail(principal, demande.get("motif") or "?", classe, ttl)
    return (200 if bail.get("etat") == "ACTIF" else 503), {"ok": bail.get("etat") == "ACTIF", "bail": bail}, {}


def demander_bail(action: str, **champs) -> dict:
    """Cote tache prioritaire : envoie la demande au hub. Ne leve jamais ; une tache prioritaire ne
    doit pas echouer parce que la regulation est injoignable -- elle le DIT et continue."""
    import json as _json
    import urllib.error as _ue
    import urllib.request as _ur

    try:
        from nokido_agent.app import forge_hub_client as _hc
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "CLIENT_HUB_INDISPONIBLE(%s)" % type(e).__name__}
    nom = os.environ.get("LAFORGE_AGENT_NAME") or os.environ.get("FORGE_AGENT_NAME") or ""
    req = _ur.Request(_hc._BASE_URL + "/api/resource/request", method="POST",
                      data=_json.dumps({"bail": dict(champs, action=action)}).encode(),
                      headers=_hc.entetes_organe(nom))
    try:
        with _ur.urlopen(req, timeout=60) as r:
            return _json.loads(r.read().decode("utf-8", "replace") or "{}")
    except _ue.HTTPError as e:
        return {"ok": False, "error": "HTTP_%d" % e.code}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "HUB_INJOIGNABLE(%s)" % type(getattr(e, "reason", e)).__name__}


@contextlib.contextmanager
def bail_priorite(motif: str, classe: str = "court", ttl_s: float = 3600.0):
    """`with bail_priorite("CI de reference 741c65341"):` -- acquiert, rend la main, LIBERE toujours.

    Si la tache meurt sans passer par le `finally`, le bail expire et le hub rend ce qu'il avait pris."""
    res = demander_bail("acquerir", motif=motif, classe=classe, ttl_s=ttl_s)
    ident = ((res or {}).get("bail") or {}).get("id")
    try:
        yield res
    finally:
        if ident:
            demander_bail("liberer", id=ident)


def _deleguer_au_hub(needed: float):
    """Demande au hub d'evincer pour ce processus. Rend un resultat FINAL (dict) ou une NOTE
    (str) qui dit pourquoi l'appelant reprend son echelle locale.

    Final : 200 (le hub a traite), 429 (differe -- agir ici doublerait l'eviction), delai
    depasse (REQUESTED != ACHIEVED : le hub agit peut-etre encore). Note : hub injoignable,
    route absente, refus de politique. Apres un refus, l'echelle locale ne tire que les
    leviers que l'appelant tenait DEJA par ses propres droits ; le sommeil d'organe y rendra
    son refus nomme. Ce n'est pas un contournement : aucune autorite n'est empruntee."""
    import json as _json
    import urllib.error as _ue
    import urllib.request as _ur

    try:
        from nokido_agent.app import forge_hub_client as _hc
    except Exception as e:  # noqa: BLE001
        return "delegation:CLIENT_HUB_INDISPONIBLE(%s)" % type(e).__name__
    nom = os.environ.get("LAFORGE_AGENT_NAME") or os.environ.get("FORGE_AGENT_NAME") or ""
    req = _ur.Request(_hc._BASE_URL + "/api/resource/request", method="POST",
                      data=_json.dumps({"needed_ram_gb": needed, "allow_evict": True}).encode(),
                      headers=_hc.entetes_organe(nom))
    try:
        with _ur.urlopen(req, timeout=_DELEGATION_TIMEOUT_S) as r:
            res = _json.loads(r.read().decode("utf-8", "replace") or "{}")
    except _ue.HTTPError as e:
        if e.code == 429:
            retry = (e.headers.get("Retry-After") if e.headers else None) or "?"
            return _resultat_sans_action(
                needed, "delegation:DIFFERE(HTTP 429, Retry-After=%s)" % retry, "differe")
        if e.code in (401, 403):
            return "delegation:REFUS_POLITIQUE(HTTP %d)" % e.code
        return "delegation:HTTP_%d" % e.code
    except Exception as e:  # noqa: BLE001
        if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
            return _resultat_sans_action(
                needed, "delegation:SANS_REPONSE(%gs, demande peut-etre en cours cote hub)"
                % _DELEGATION_TIMEOUT_S, "sans_reponse")
        return "delegation:HUB_INJOIGNABLE(%s)" % type(getattr(e, "reason", e)).__name__
    if not isinstance(res, dict):
        return _resultat_sans_action(needed, "delegation:REPONSE_ILLISIBLE", "illisible")
    res.setdefault("delegue", "hub")
    return res


def request_resources(
    needed_ram_gb: float,
    allow_evict: bool = False,
    deleguer: bool = True,
) -> dict[str, Any]:
    """Reserve `needed_ram_gb` of RAM, evicting low-priority loads if needed.

    Strategy (run only when ``allow_evict=True``) :
        1. Snapshot current RAM. If ``ram_free_gb >= needed_ram_gb`` → noop.
        2. Score loaded resources by criticality (least critical first) :
            a) Each Ollama loaded model, ordered by ``until`` ascending
               (LRU — soonest-to-expire first).
            b) llama-server :8091 (~5 GB) if running.
            c) Pause all Docker containers (single bulk action, frees roughly
               their summed working set).
        3. Evict in that order, re-checking RAM after each step. Stop as soon
           as we have enough.
        4. If still short, return ``{ok: False, missing_gb: ...}``.

    Always returns a dict (never raises). Keys :
        ok          : bool
        action      : "noop" | list[str] of human-readable actions taken
        freed_gb    : float — RAM delta vs initial snapshot (best-effort)
        before_free : float — initial ram_free_gb
        after_free  : float — final ram_free_gb
        missing_gb  : float (only when ok=False)

    Args:
        needed_ram_gb : target free RAM in GB.
        allow_evict   : if False, only check (no side effects); when not
                        enough RAM, return ok=False with no eviction.
        deleguer      : hors du hub (pas de jeton superviseur), declarer le
                        besoin au hub au lieu d'agir sans autorite (cf.
                        `_deleguer_au_hub`). False = echelle locale seule --
                        c'est ce que la route du hub demande.
    """
    try:
        needed = float(needed_ram_gb)
    except (TypeError, ValueError):
        return {"ok": False, "action": "noop", "missing_gb": 0.0, "error": "invalid needed_ram_gb"}

    snap0 = get_snapshot()
    # free0 sert de BASELINE et de court-circuit : le lire dans l'instantane publie
    # ferait decider sur une photo perimee (cf. _free_now).
    free0 = _free_now()

    if free0 >= needed:
        return {
            "ok": True,
            "action": "noop",
            "freed_gb": 0.0,
            "before_free": free0,
            "after_free": free0,
        }

    if not allow_evict:
        return {
            "ok": False,
            "action": "noop",
            "missing_gb": round(needed - free0, 2),
            "before_free": free0,
            "after_free": free0,
        }

    # Sans jeton superviseur, l'echelle locale ne peut pas endormir un organe : DECLARER le
    # besoin au hub, qui tient ce controle. Dans le hub, ou sur `deleguer=False` : inchange.
    _note_delegation = None
    if deleguer and "Authorization" not in _supervisor_auth_headers():
        _delegation = _deleguer_au_hub(needed)
        if isinstance(_delegation, dict):
            return _delegation
        _note_delegation = _delegation

    actions: list[str] = [_note_delegation] if _note_delegation else []

    def _refresh_free() -> float:
        # Laisser l'OS rendre les pages, PUIS mesurer pour de vrai.
        time.sleep(0.5)
        return _free_now()

    # Step 1bis — RENDRE SA PROPRE GRAISSE AVANT D'AMPUTER UN ORGANE.
    # Mesure 2026-07-30 : a 86-90 % de RAM l'echelle rendait `noop` en manquant
    # 1.07 Go, parce que TOUS les gros porteurs etaient legitimement intouchables
    # — llama embed et reranker proteges par `is_critical` (piliers RAG), qdrant
    # porteur d'etat. Le corps n'avait donc AUCUN levier : il refusait des spawns
    # sans jamais pouvoir liberer quoi que ce soit. Or le plus gros bloc
    # reclamable etait le cache dense du hub lui-meme : ~2.3 Go de vecteurs
    # float32 dont Qdrant detient la copie sur disque, avec un TTL de 30 min.
    # Un cache reconstructible n'est pas un organe : il se rend AVANT tout arret
    # de service, et sa perte ne coute qu'une reconstruction.
    if _free_now() < needed:
        _rec = run_reclaimers(needed)
        if _rec.get("ok"):
            actions.extend(_rec["action"])
            _refresh_free()

    # Step 2a — Ollama LRU eviction
    try:
        loaded = ollama_loaded_models()
    except Exception:
        loaded = []
    for m in loaded:
        cur_free = _free_now()
        if cur_free >= needed:
            break
        if ollama_unload(m["name"]):
            actions.append(f"ollama_unload:{m['name']}({m.get('size_gb', 0)}GB)")
            _audit_lifecycle("evict", "llm", "reclaim RAM (LRU ollama)",
                             target=m["name"], size_gb=m.get("size_gb", 0))
            _refresh_free()

    # Step 2b — llama-server :8091
    # GARDE D'INTENTION : ne pas reprendre ce qu'on vient de poser. Ce levier est
    # NOMME, donc il echappait au conditionnement pose sur l'eviction par
    # capacite -- et c'est LUI qui a evince le cerveau codeur allume a la demande
    # le 2026-07-26 (`llamacpp_native_stop(~5.29GB)`, moins d'une minute apres).
    # Un levier nomme n'est pas plus sage qu'un levier dynamique : il est
    # seulement plus ancien.
    cur_free = _free_now()
    try:
        _llama_voulu = bool(get_active_intents().get("llama_wanted"))
    except Exception:  # noqa: BLE001
        _llama_voulu = False
    # DETRESSE VITALE : une intention n'est PAS un droit absolu (mesure 2026-08-02).
    # Ce soir-la, a 99,2 % de RAM et 0,18 Go libre — le niveau exact ou `dwm.exe` est
    # tombe le matin meme, forcant un redemarrage manuel de l'owner — ce garde a ecrit
    # `skip(intention llama.wanted)` et n'a RIEN rendu. L'intention etait FRAICHE et
    # LEGITIME (TTL respecte, reveilleur declarant correctement) : le defaut n'est donc
    # ni un declarant manquant ni un TTL casse, c'est l'absence de contre-poids. Un
    # corps qui etouffe passe outre ce qu'il voulait. En deca du seuil vital on evince,
    # et on le DIT — l'outrepassement doit se lire dans le journal, jamais se deviner.
    _seuil_detresse = float(os.environ.get("LAFORGE_DETRESSE_LIBRE_GB", "1.5"))
    _detresse = cur_free < _seuil_detresse
    # ARBITRAGE ADAPTATIF : une intention fraiche protege le coder TANT QU'IL SERT.
    # Au repos, coder oisif (conns=0) + embedder affame -> l'intention CEDE
    # (hyperemie active). La detresse vitale reste un outrepassement DISTINCT.
    _arb_yield = False
    if _llama_voulu and cur_free < needed and not _detresse:
        try:
            from nokido_agent.app.forge_endocrine_system import get_rhythm as _gr

            _rhythm_rr = _gr()
        except Exception:  # noqa: BLE001
            _rhythm_rr = "NORMAL"
        _st_coder = llamacpp_native_status()
        _intents_rr = get_active_intents()
        _bk_rr, _bk_rr_age, _bk_rr_src = _backlog_pending_qualifie()
        _dec_rr = arbitrer_pression(
            rhythm=_rhythm_rr,
            # VERDICT COMPOSITE, pas `running or port_listening` : le premier terme
            # mesure le SERVICE NSSM (invisible sous le compte sandbox), le second un
            # TRANSPORT. Leur OR melangeait deux preuves de nature differente pour en
            # tirer une conclusion qu'aucune ne portait. `coder_up` n'autorise qu'une
            # chose — la branche `yield_coder` — donc un INCERTAIN doit s'y lire
            # comme False : on ne cede pas un organe sur une preuve incomplete.
            coder_up=(_st_coder.get("verdict") == "VIVANT"),
            coder_conns=_coder_conns(),
            chains_active=int(_intents_rr.get("chains_active") or 0),
            embed_wanted=bool(_intents_rr.get("embed_wanted")),
            backlog=_bk_rr,
            demande_active=_demande_active_llama(),
            inutile_s=_inutile_s_llama(),
            embedder_up=_port_ecoute(int(os.environ.get("LAFORGE_LLAMA_EMBED_PORT", "8099"))),
            coder_ram_gb=float(_st_coder.get("ram_gb") or _LLAMACPP_NATIVE_RAM_ESTIMATE_GB),
            free_gb=cur_free,
        )
        # A0-4b : second site d'invocation de la meme politique. Il repond a une
        # DEMANDE explicite la ou le tick est proactif -- deux contextes, une seule
        # politique, donc un seul journal, avec le contexte en clair.
        observer_decision(
            {"rhythm": _rhythm_rr, "coder_up": (_st_coder.get("verdict") == "VIVANT"),
             "coder_conns": _coder_conns(),
             "chains_active": int(_intents_rr.get("chains_active") or 0),
             "embed_wanted": bool(_intents_rr.get("embed_wanted")),
             "backlog": _bk_rr, "backlog_age_s": _bk_rr_age, "backlog_src": _bk_rr_src,
             "demande_active": _demande_active_llama(),
             "inutile_s": _inutile_s_llama(),
             "embedder_up": _port_ecoute(
                 int(os.environ.get("LAFORGE_LLAMA_EMBED_PORT", "8099"))),
             "coder_ram_gb": float(_st_coder.get("ram_gb")
                                   or _LLAMACPP_NATIVE_RAM_ESTIMATE_GB),
             "free_gb": cur_free, "contexte": "request_resources"},
            _dec_rr, coder_verdict=str(_st_coder.get("verdict") or ""))
        if _dec_rr["action"] == "yield_coder":
            _arb_yield = True
            actions.append("llamacpp_native_stop:ARBITRAGE %s (%s)"
                           % (_dec_rr["strategie"], _dec_rr["raison"]))
        else:
            # L'AGE FAIT PARTIE DU SIGNAL : une decision prise sur un backlog
            # de six heures n'a pas la meme valeur qu'une prise sur une mesure
            # fraiche, et un lecteur du journal doit pouvoir en juger.
            #
            # ET SURTOUT LE MOTIF REEL. Mesure 2026-09-04 : ce message nommait
            # l'intention et le backlog, alors que NI L'UN NI L'AUTRE ne decide ici
            # — `arbitrer_pression` protege sur `conns`, `chains`, une demande
            # ouverte ou un delai de grace, et le backlog sert au contraire a FAIRE
            # CEDER le coder (branche `C_consolidation`). La `raison` etait donc
            # calculee, precise... et JETEE par l'appelant. Resultat : deux lecteurs
            # du journal (dont l'auteur de ce commentaire) ont bati une chaine
            # causale « backlog fige => llama retenu » qui n'existe pas dans le code.
            # Un journal qui affiche un chiffre sans rapport avec la decision est
            # pire qu'un journal muet : il oriente activement vers la mauvaise cause.
            # INVARIANT (owner, 2026-09-04) : aucune decision regulatrice ne doit
            # etre interpretable causalement a partir d'un signal qui n'est pas
            # EXPLICITEMENT marque comme causal. On separe donc les deux, en toutes
            # lettres — la simple proximite de deux chiffres dans une ligne suffit a
            # ce que l'oeil reconstruise une causalite fausse, et c'est ce qui s'est
            # produit ici : `backlog=109053` voisinait `intention llama.wanted`, et
            # DEUX lecteurs ont conclu « le backlog retient llama » alors que la
            # cause etait un delai de grace de 300 s et que le backlog sert, lui, a
            # faire CEDER le coder (branche C_consolidation).
            actions.append("llamacpp_native_stop:skip(CAUSAL: %s | strategie=%s"
                           " || CONTEXTE (n'a PAS decide): backlog=%s src=%s age=%s)"
                           % (_dec_rr.get("raison") or "motif non rendu",
                              _dec_rr.get("strategie") or "?",
                              _bk_rr, _bk_rr_src,
                              "?" if _bk_rr_age is None else "%.0fs" % _bk_rr_age))
        _transduire("llama.wanted")
    elif _llama_voulu and _detresse:
        actions.append("llamacpp_native_stop:INTENTION OUTREPASSEE "
                       "(detresse: %.2f Go libre < %.2f)" % (cur_free, _seuil_detresse))
        _transduire("llama.wanted")
    if cur_free < needed and (not _llama_voulu or _detresse or _arb_yield):
        st = llamacpp_native_status()
        # Ici l'objectif est INVERSE de `coder_up` : il s'agit d'ARRETER. Un
        # INCERTAIN ne doit donc pas empecher la tentative — `llamacpp_native_stop()`
        # est idempotent et rend False s'il n'y a rien a arreter. Refuser d'essayer
        # sur une preuve partielle laisserait la RAM prise par un process qu'on voit
        # pourtant peser (mesure 2026-09-05 : 4,65 Go, `running=False`, port ouvert).
        if st.get("verdict") in ("VIVANT", "INCERTAIN") or st.get("port_listening"):
            if llamacpp_native_stop():
                actions.append(f"llamacpp_native_stop(~{st.get('ram_gb') or _LLAMACPP_NATIVE_RAM_ESTIMATE_GB}GB)")
                _audit_lifecycle("stop", "llm", "reclaim RAM",
                                 target="llama-server:8091",
                                 ram_gb=st.get("ram_gb") or _LLAMACPP_NATIVE_RAM_ESTIMATE_GB)
                _refresh_free()
            else:
                actions.append("llamacpp_native_stop:failed(non-admin?)")

    # Step 2b-bis — Gros consommateurs identifiés par CAPACITÉ (owner 2026-07-24).
    # Les étapes 2a/2b ne connaissent que des cibles NOMMÉES à l'avance ; celle-ci
    # part des process réels et n'endort que ce que le world-model juge `safe`.
    cur_free = _free_now()
    if cur_free < needed:
        for cand in _heavy_evictable_services(min_ram_gb=1.0):
            # Mesure AVANT l'acte, pour que le differentiel publie soit un ecart
            # entre deux mesures et non entre une mesure et une estimation.
            _avant = _free_now()
            if _avant >= needed:
                break
            _accepte, _motif = _sleep_service_verdict(cand["service"])
            if not _accepte:
                actions.append(f"sleep:{cand['service']}:{_motif}")
                _audit_lifecycle("sleep_refused", "service", _motif, target=cand["service"],
                                 ram_gb=cand["ram_gb"])
            else:
                actions.append(f"sleep:{cand['service']}(~{cand['ram_gb']}GB)")
                _audit_lifecycle("sleep", "service", "reclaim RAM (evictable, verdict safe)",
                                 target=cand["service"], ram_gb=cand["ram_gb"],
                                 pid=cand["pid"])
                _apres = _refresh_free()
                _publish_evict_trace(cand, _avant, _apres,
                                     "reclaim RAM (evictable, verdict safe)")

    # Step 2c — Pause all Docker containers
    cur_free = _free_now()
    if cur_free < needed:
        paused = docker_pause_all()
        if paused > 0:
            actions.append(f"docker_pause_all:{paused}")
            _refresh_free()

    # Step 2c-bis — COUPER la prothese, pas seulement pauser ses conteneurs.
    # La pause laisse la VM WSL et le moteur en RAM ; c'est l'extinction qui rend
    # la surface. Gardes (intention / gain mesure / refractaire) dans la fonction.
    cur_free = _free_now()
    if cur_free < needed:
        verdict = docker_release_prothese()
        if verdict.get("fait"):
            actions.append("docker_release:%d Mo"
                           % (verdict.get("surface") or {}).get("total_mb", 0))
            _refresh_free()
        else:
            _audit_lifecycle("release_skipped", "docker",
                             str(verdict.get("raison"))[:160])

    # Step 2d — DERNIER RECOURS SOUS DÉTRESSE : restart d'un pilier CRITIQUE ballonné.
    # LATITUDE SUR TOUTE LA SURFACE (directive owner 2026-08-06). Quand le glouton est
    # un pilier RAG (embedder/reranker) que `is_critical` écarte — à juste titre — de
    # l'éviction, les paliers 2a-2c n'ont AUCUN levier : mesuré ce jour-là, embedder à
    # 12,1 Go, `request_resources` -> noop, RAM 89 %. Un RESTART (≠ kill) purge le bloat
    # et rend l'organe en secondes (reload BGE-M3). Gardes stricts, car cycler un pilier
    # en boucle = le pompage des 312 Go (2026-07-30) :
    #   - urgence + absence de travail = `_evict_conditions_met()` (mesure LIVE, pas le
    #     besoin théorique : un gros `needed` ne suffit pas, il faut une vraie pression) ;
    #   - COOLDOWN large contre le pompage ;
    #   - SEUIL de bloat : on ne touche que le pathologique, jamais une baseline saine ;
    #   - JOURNAL loud : outrepasser un critique se LIT, ne se devine pas.
    global _last_pillar_restart_ts
    # GATE PROPRE au restart d'un pilier embed/rerank : urgence RAM mesurée EN DIRECT +
    # aucune chaîne active. On N'utilise PAS `_evict_conditions_met` ici car il s'abstient
    # sur llama.wanted / lmstudio.wanted — les CERVEAUX CHAT (:8091/:1234), orthogonaux au
    # pilier embedding. Mesuré 2026-08-06 : ce mis-gate laissait la régulation MUETTE à
    # 87 % RAM (embedder à 7,72 Go) parce qu'un llama.wanted du chat bloquait tout.
    try:
        _vm = psutil.virtual_memory()
        _urgence_pilier = ((_vm.available / (1024 ** 3) < _EVICT_URGENCE_LIBRE_GB)
                           or (100.0 - _vm.percent < _EVICT_URGENCE_LIBRE_PCT))
    except Exception:  # noqa: BLE001 - muet-ok : sans mesure RAM on ne restart pas
        _urgence_pilier = False
    try:
        _chaines = bool(get_active_intents().get("chains_active"))
    except Exception:  # noqa: BLE001 - intentions illisibles -> prudence, pas de restart
        _chaines = True
    if (_free_now() < needed
            and (time.time() - _last_pillar_restart_ts) > _PILLAR_RESTART_COOLDOWN_S
            and _urgence_pilier and not _chaines):
        for _pil in _bloated_recoverable_pillars(_PILLAR_BLOAT_GB):
            if _restart_pillar(_pil["service"]):
                _last_pillar_restart_ts = time.time()
                actions.append(
                    f"pillar_restart:{_pil['service']}(bloat~{_pil['ram_gb']}GB->baseline)")
                _audit_lifecycle("restart", "pillar",
                                 "DETRESSE: purge bloat pilier critique recuperable",
                                 target=_pil["service"], ram_gb=_pil["ram_gb"])
            else:
                actions.append(
                    f"pillar_restart:{_pil['service']}:ECHEC(reveil NON CONFIRME)")
                _audit_lifecycle("restart_failed", "pillar",
                                 "DETRESSE: sleep ok, reveil NON CONFIRME au registre "
                                 "apres attente -- ni refus ni preuve de mort, pilier "
                                 "a instruire",
                                 target=_pil["service"], ram_gb=_pil["ram_gb"])
            _refresh_free()
            break  # un pilier par appel : on remesure, on ne cascade pas

    after = _free_now()
    freed = round(after - free0, 2)

    if after >= needed:
        return {
            "ok": True,
            "action": actions or ["noop"],
            "freed_gb": freed,
            "before_free": free0,
            "after_free": after,
        }
    # Echec : dire QUI porte la pression. Une eviction qui n'a rien rendu parce que la
    # memoire est hors du corps n'est pas la meme panne qu'une eviction refusee.
    global _ATTRIB_DERNIER_AUDIT_TS
    try:
        _attrib = attribuer_pression()
    except Exception as e:  # noqa: BLE001
        _attrib = {"verdict": "INCERTAIN", "raison": "attribution KO: %s" % type(e).__name__}
    if (_attrib.get("verdict") in ("NON_SOI", "NOYAU")
            and _attrib.get("mesure_ts", 0) != _ATTRIB_DERNIER_AUDIT_TS):
        _ATTRIB_DERNIER_AUDIT_TS = _attrib.get("mesure_ts", 0)
        _audit_lifecycle("pression_hors_corps", "ram", resume_attribution(_attrib)[:400],
                         target="request_resources", missing_gb=round(needed - after, 2))
    return {
        "ok": False,
        "action": actions or ["noop"],
        "freed_gb": freed,
        "before_free": free0,
        "after_free": after,
        "missing_gb": round(needed - after, 2),
        "attribution": _attrib,
    }


# ── Brain picker — endpoint routing ─────────────────────────────────────────


def brain_pick(task_kind: str, task_size: str = "medium") -> str:
    """Pick the best inference endpoint for a task kind.

    Decision matrix :

    +------------+------------------------------+------------------------------+
    | task_kind  | preferred order              | rationale                    |
    +============+==============================+==============================+
    | code       | llamacpp_native, ollama,     | qwen-coder dedicated on 8091 |
    |            | cloud_groq                   |                              |
    | reasoning  | ollama (deepseek-r1),        | local thinking models        |
    |            | cloud_groq, llamacpp_native  |                              |
    | embedding  | ollama (only)                | nomic-embed-text on Ollama   |
    | fast       | cloud_groq, ollama,          | groq if available is fastest |
    |            | llamacpp_native              |                              |
    | summary    | ollama, cloud_groq,          | small model on local         |
    |            | llamacpp_native              |                              |
    +------------+------------------------------+------------------------------+

    Health gates :
    - If ``should_throttle()`` AND not cloud-eligible → return ``"throttle"``.
    - llamacpp_native : require service running OR port listening.
    - ollama : require :11434 open.
    - cloud_groq : require ``GROQ_API_KEY`` env var.

    Returns endpoint URL string OR ``"throttle"`` when nothing healthy.
    Never raises.
    """
    kind = (task_kind or "").lower().strip()
    size = (task_size or "medium").lower().strip()

    # Endpoint URLs — env-configurable for Docker (LAFORGE_OLLAMA_HOST, LAFORGE_LLAMACPP_HOST)
    URL_OLLAMA = f"http://{_OLLAMA_HOST}:{_OLLAMA_PORT}"
    URL_LLAMA = f"http://{_LLAMACPP_NATIVE_HOST}:{_LLAMACPP_NATIVE_PORT}"
    URL_GROQ = "https://api.groq.com/openai/v1"

    # Health probes (all cheap, ms-scale)
    def _ollama_up() -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex((_OLLAMA_HOST, _OLLAMA_PORT)) == 0
        except Exception:
            return False

    def _llama_up() -> bool:
        if not _LLAMACPP_NATIVE_HOST:
            return False  # explicitly disabled in Docker
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                return s.connect_ex((_LLAMACPP_NATIVE_HOST, _LLAMACPP_NATIVE_PORT)) == 0
        except Exception:
            return False

    def _groq_ok() -> bool:
        return bool(get_secret("GROQ_API_KEY") or "".strip())

    health = {
        "ollama": _ollama_up(),
        "llamacpp_native": _llama_up(),
        "cloud_groq": _groq_ok(),
    }

    # Preference table per task_kind. Keys must match `health`.
    PREF: dict[str, list[str]] = {
        "code": ["llamacpp_native", "ollama", "cloud_groq"],
        "reasoning": ["ollama", "cloud_groq", "llamacpp_native"],
        "embedding": ["ollama"],
        "fast": ["cloud_groq", "ollama", "llamacpp_native"],
        "summary": ["ollama", "cloud_groq", "llamacpp_native"],
    }
    order = PREF.get(kind, ["ollama", "llamacpp_native", "cloud_groq"])

    URLS = {
        "ollama": URL_OLLAMA,
        "llamacpp_native": URL_LLAMA,
        "cloud_groq": URL_GROQ,
    }

    throttling = should_throttle()

    for choice in order:
        if not health.get(choice):
            continue
        # If local stack is throttling and we have a cloud option → take cloud.
        if throttling and choice in ("ollama", "llamacpp_native"):
            # Try to fall through to cloud first if eligible later in `order`.
            if "cloud_groq" in order and health["cloud_groq"]:
                # cloud_groq comes later; check if it appears later in remaining order
                if order.index("cloud_groq") > order.index(choice):
                    continue
        # Heavy task on small endpoint warning : oversized requests on tiny
        # backends. We don't refuse, but pick a heavier alt when available.
        if size in ("xl", "huge") and choice == "llamacpp_native":
            if health.get("ollama"):
                return URLS["ollama"]
        return URLS[choice]

    # Fallback : if cloud is the only option and we somehow filtered it out.
    if health["cloud_groq"]:
        return URL_GROQ
    return "throttle"


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser(description="Nokido resource monitor")
    p.add_argument(
        "cmd",
        nargs="?",
        default="snapshot",
        choices=["snapshot", "watch", "throttle", "summary", "legacy", "docker", "request", "brain", "ollama", "llama"],
    )
    p.add_argument("arg", nargs="?", default=None, help="Arg for `request <gb>` or `brain <kind>`")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--n", type=int, default=10, help="Watch iterations")
    p.add_argument("--evict", action="store_true", help="With `request`, allow eviction")
    args = p.parse_args()

    if args.cmd == "snapshot":
        s = get_snapshot()
        print(json.dumps(s, indent=2, ensure_ascii=False))
    elif args.cmd == "summary":
        print(summary_line())
    elif args.cmd == "throttle":
        print(should_throttle())
    elif args.cmd == "watch":
        start_sampler(interval_s=args.interval)
        try:
            for _ in range(args.n):
                time.sleep(args.interval)
                print(summary_line(), flush=True)
        finally:
            stop_sampler()
    elif args.cmd == "legacy":
        rm = ResourceManager()
        print(json.dumps(rm.check_resources(), indent=2, ensure_ascii=False, default=str))
    elif args.cmd == "docker":
        print(json.dumps(docker_status(), indent=2, ensure_ascii=False))
    elif args.cmd == "ollama":
        print(json.dumps(ollama_loaded_models(), indent=2, ensure_ascii=False))
    elif args.cmd == "llama":
        print(json.dumps(llamacpp_native_status(), indent=2, ensure_ascii=False))
    elif args.cmd == "request":
        try:
            gb = float(args.arg) if args.arg else 4.0
        except ValueError:
            gb = 4.0
        result = request_resources(needed_ram_gb=gb, allow_evict=args.evict)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.cmd == "brain":
        kind = args.arg or "code"
        print(brain_pick(kind))
