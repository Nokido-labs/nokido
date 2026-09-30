"""forge_homeostasis_orchestrator.py — Chef d'orchestre biomimétique Nokido.

Mapping bio↔code :
- Hypothalamus master = forge_health_diagnostic (mesure périodique)
- Hypophyse           = forge_endocrine (relâche les hormones)
- SNC autonome        = ce module (coordonne tous les organes en fonction)
- Glandes             = workers (rag_warmup, biblio, hebbian, renal, etc.)
- Réflexes            = pluripotent_workers (différenciation rapide)

PROBLÈME RÉEL ADRESSÉ
=====================
Pour économiser tokens + ressources :
- 1 seul daemon NSSM au lieu de 6 (un service par module = duplication PID/RAM)
- Nokido contrôle le rythme — pas de polling concurrent qui se gêne
- Cycle séquencé : santé → hormones → différenciation pluripotente → exécutions ciblées
- Comparaison périodique d'efficacité tools (forge_tool_efficiency)

CYCLE
=====
Chaque tick (1× / 5 min) :
1. forge_health_diagnostic.run_cycle()         # Monitor
2. (déjà fait dans health) → release hormones    # Analyze
3. forge_renal_clearance dry-run pour estimation  # Plan
4. PluripotentWorker.cycle() ×N selon hormones    # Execute (différencié)
5. forge_coagulation_cascade.run_cycle()         # Self-healing
6. forge_immune_adaptive.run_cycle() (1/12 cycles = 1/h)  # Self-protecting
7. forge_hebbian_linker.run_cycle() (1/72 cycles = 1/6h)  # Knowledge consolidation
8. forge_skill_enricher --once (1/12 cycles)               # Capitalisation
9. forge_tool_efficiency.run_cycle() (1/24 cycles = 2h)    # Self-comparing

ECONOMIES
=========
- Avant : 6 daemons × overhead Python (~50 MB chacun) = 300 MB RAM
- Après : 1 daemon orchestrateur (~80 MB) qui appelle les modules en in-process
- Avant : 6 services NSSM = 6 ServiceControlManager entries
- Après : 1 service `NokidoOrchestrator`

Si un module spécifique doit garder son daemon dédié (ex: gemini_poll qui est
event-driven), il reste séparé. L'orchestrateur ne dédoublonne pas, il
remplace les modules `--daemon` que je peux appeler en `--once` de manière
coordonnée.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import torch

# Force utf-8 stdout/stderr (NSSM default = cp1252, casse les arrow Unicode).
# JAMAIS sous pytest : `sys.stdout` y est le flux de CAPTURE, et le reconfigurer le
# referme pour les tests SUIVANTS du même worker (mesure 2026-09-04, 20 des 38 échecs
# du premier run xdist). Le `try/except` n'y peut rien — l'appel réussit, c'est son
# effet qui casse.
if "pytest" not in sys.modules:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"
HEARTBEAT = SANDBOX / "homeostasis_orchestrator.heartbeat"
STATE_FILE = SANDBOX / "homeostasis_state.json"

DAEMON_WATCHDOGS = [
    {
        "name": "gemini_poll_daemon",
        "heartbeat": SANDBOX / "gemini_poll_daemon.heartbeat",
        "cmd": [sys.executable, str(ROOT / "tools" / "gemini_poll_daemon.py")],
        "stale_s": 600,
    },
    {
        "name": "ingestion_pipeline",
        "heartbeat": SANDBOX / "ingestion_pipeline.heartbeat",
        "cmd": [sys.executable, str(ROOT / "app" / "forge_ingestion_pipeline.py"), "--daemon"],
        "stale_s": 600,
    },
]

# Gardes du watchdog. PERSISTES : un cooldown garde en memoire disparait au respawn du
# regulateur, donc il ne borne rien -- et c'est precisement pendant une crise que le
# regulateur respawne.
_WATCHDOG_ETAT = SANDBOX / "watchdog_daemons_state.json"
_WATCHDOG_COOLDOWN_S = float(os.environ.get("LAFORGE_WATCHDOG_COOLDOWN_S", "900"))
_WATCHDOG_BUDGET = int(os.environ.get("LAFORGE_WATCHDOG_BUDGET", "3"))
_WATCHDOG_QUARANTAINE_S = float(os.environ.get("LAFORGE_WATCHDOG_QUARANTAINE_S", "21600"))


def _watchdog_etat_lire() -> dict:
    try:
        return json.loads(_WATCHDOG_ETAT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — premier tour ou etat illisible : on repart neuf
        return {}


def _watchdog_etat_ecrire(etat: dict) -> None:
    try:
        _WATCHDOG_ETAT.write_text(json.dumps(etat, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        # Le DIRE : sans persistance, les gardes retombent a zero a chaque respawn et
        # le watchdog redevient la boucle ouverte qu'on vient de fermer.
        print(f"  [watchdog] etat NON persiste ({type(e).__name__}) — gardes affaiblis",
              flush=True)


def _watchdog_au_repos(nom: str, exempts) -> bool:
    """Ce daemon est-il eteint VOLONTAIREMENT ?

    Le nom cote watchdog et le nom cote registre ne coincident pas toujours
    (`gemini_poll_daemon` ici, `gemini_poll` la-bas). Exiger l'egalite stricte
    fabriquerait une exemption qui existe et ne s'applique jamais — le motif exact
    qu'on est en train de corriger.
    """

    def _norm(s: str) -> str:
        s = str(s).lower()
        for suf in ("_daemon", "_worker", "_agent", "_pipeline"):
            if s.endswith(suf):
                s = s[: -len(suf)]
                break
        return s.strip("_")

    n = _norm(nom)
    return any(_norm(e) == n for e in exempts)

DEFAULT_TICK_S = int(os.environ.get("LAFORGE_HOMEO_TICK_S", "300"))  # 5 min
RAM_SLEEP_PCT = int(os.environ.get("LAFORGE_HOMEO_RAM_SLEEP_PCT", "85"))  # warn + slow tick

# RYTHMES PROPRES PAR ORGANE (2026-09-06) — un corps n'a pas UN rythme, il en a
# plusieurs. Mesure sur 12 ticks consecutifs (tools/forge_homeostasis_tick_profil.py,
# 700 s au total) : `health` prend 487 s (70 %, 40,6 s par appel) et `pluripotent`
# 116 s (17 %) ; TOUS les reflexes reunis -- watchdog, reconcile, coagulation,
# flap_journal, econome, reboot_sentinel, task_runner, algedonique -- coutent 1,6 s.
# Faire battre un bilan complet au rythme des reflexes, c'est prendre un
# electrocardiogramme a chaque battement. Le RSS, lui, est plat (0,337 Go, aucune
# accumulation sur 12 ticks) : le probleme de cet organe n'a JAMAIS ete la memoire.
RYTHME_HEALTH = int(os.environ.get("LAFORGE_HOMEO_RYTHME_HEALTH", "3"))        # bilan : 1 tick sur 3
RYTHME_PLURIPOTENT = int(os.environ.get("LAFORGE_HOMEO_RYTHME_PLURIPOTENT", "2"))  # travail : 1 sur 2

sys.path.insert(0, str(ROOT))

# Le pouls ne se fabrique plus ici : il vient du COEUR (`forge_cardiac_node`) et
# transite par l'organe du battement. Le `_heartbeat` local ecrit ce matin a ete
# retire — au recensement du 2026-07-28, 39 modules avaient chacun le leur.
from nokido_agent.app.forge_heartbeat import Cadence


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"tick_count": 0, "started_at": time.time()}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tick_count": 0, "started_at": time.time()}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _safe_call(fn_name: str, fn, timeout_s: float = 90.0) -> dict:
    """Appelle une fonction de phase en attrapant toute exception ET en bornant sa
    durée (fix wedge 2026-07-05). fn() tourne dans un thread daemon ; si elle dépasse
    timeout_s (embed/LLM/probe bloqué SANS lever d'exception), on l'ABANDONNE et le
    tick REPART — un organe coincé ne fige plus la boucle homéostasie. Caveat : le
    thread bloqué sur un appel C survit (non tuable) mais meurt avec le process ;
    l'essentiel = la boucle continue de réguler autour de l'organe coincé."""
    import threading

    box: dict = {}

    def _runner() -> None:
        try:
            box["result"] = fn()
        except Exception as e:  # noqa: BLE001
            box["err"] = f"{type(e).__name__}: {str(e)[:160]}"

    t = threading.Thread(target=_runner, name=f"phase_{fn_name}", daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        print(f"  [homeo] phase {fn_name} TIMEOUT >{timeout_s:.0f}s -> abandonnee (tick continue)", flush=True)
        return {"ok": False, "err": f"TIMEOUT >{timeout_s:.0f}s", "timeout": True}
    if "err" in box:
        return {"ok": False, "err": box["err"]}
    return {"ok": True, "result": box.get("result")}


class FlowRegulator:
    """Régule la sensibilité cognitive selon la charge CPU.

    Formule : tau = base * (1 + exp((cpu - 70) / 15))
    CPU 10% → tau ≈ 0.051 (hyper-vigilant)
    CPU 50% → tau ≈ 0.063 (normal)
    CPU 90% → tau ≈ 0.241 (tunnel-vision, ignore le bruit)
    """

    def __init__(self, base_threshold: float = 0.05):
        self.base_threshold = base_threshold

    def get_dynamic_threshold(self) -> float:
        try:
            import psutil
            import math

            cpu = psutil.cpu_percent(interval=0.1)
            tau = self.base_threshold * (1 + math.exp((cpu - 70) / 15))
            tau *= self._endocrine_factor()   # boucle endocrine->homeostasie (amygdale/cortisol)
            tau *= self._prediction_error_factor()  # precision-weighting (Active Inference)
            return round(tau, 4)
        except Exception:
            return self.base_threshold

    def _endocrine_factor(self) -> float:
        """Salience de menace (amygdale threat_salience / cortisol) -> vigilance
        accrue. Ferme la boucle endocrine->homeostasie (cf tools/forge_organ_loop_test.py).
        Borné +0..50%, fail-safe -> 1.0 (no-op) si endocrine indispo."""
        try:
            from nokido_agent.app import forge_endocrine as fe
            lvl = 0.0
            for h in ("threat_salience", "cortisol"):
                r = fe.read(h)
                v = getattr(r, "level", r) if r is not None else None
                v = v.get("level") if isinstance(v, dict) else v
                if isinstance(v, (int, float)):
                    lvl = max(lvl, float(v))
            return 1.0 + 0.5 * max(0.0, min(1.0, lvl))
        except Exception:
            return 1.0

    def _prediction_error_factor(self) -> float:
        """Precision-weighting : quand le modele generatif se trompe (surprise
        recente elevee), le prior merite moins de confiance -> on ABAISSE tau
        pour laisser entrer la nouveaute au lieu de la filtrer comme du bruit.
        Modele fiable (surprise nulle) -> 1.0, on garde le filtrage nominal.

        Fenetre glissante et non moyenne all-time : un seuil pilote par une
        moyenne figee ne regule plus rien. Borne 0.6..1.0, fail-safe -> 1.0.
        """
        try:
            from nokido_agent.app import forge_active_inference as ai

            r = ai.recent_surprise(window_s=604800.0, last_n=20)
            # Trop peu d'observations recentes = pas de quoi conclure : no-op.
            if not r.get("ok") or int(r.get("n", 0)) < 3:
                return 1.0
            ratio = max(0.0, min(1.0, float(r.get("ratio", 0.0))))
            return round(1.0 - 0.4 * ratio, 4)
        except Exception:
            return 1.0

    def inject_to_novelty(self, novelty_engine) -> None:
        if hasattr(novelty_engine, "set_threshold"):
            novelty_engine.set_threshold(self.get_dynamic_threshold())


_novelty = None  # lazy-loaded on first tick to avoid loading torch at startup


def _get_novelty() -> object:
    global _novelty
    if _novelty is None:
        try:
            from nokido_agent.app.forge_novelty_organ import AugmentedNovelty

            _novelty = AugmentedNovelty(input_dim=64, base_threshold=0.05)
        except Exception:
            _novelty = False  # sentinel: tried and failed, don't retry
    return _novelty if _novelty is not False else None


_flow_regulator = FlowRegulator()


def _watchdog_daemons() -> dict:
    """Relance un daemon dont le heartbeat est rance — sous gardes.

    MESURE 2026-08-25 : le heartbeat de `gemini_poll_daemon` avait 535 776 s, soit
    6,2 jours, alors que le service porte `disabled = true` par decision owner. La
    condition « relancer » etait donc vraie a CHAQUE tick de 300 s depuis six jours,
    et rien ne l'arretait. Deux defauts distincts se cumulaient :

    1. un heartbeat rance ne prouve pas qu'un organe est mort — il peut etre eteint
       volontairement, ou c'est sa SONDE qui est morte pendant qu'il vit ;
    2. `Popen` qui rend la main n'est pas un accuse de reception physiologique. Rien
       ne verifiait que la relance produisait quoi que ce soit, donc l'echec ne
       pouvait pas etre compte, donc il ne pouvait pas arreter les frais.

    Quatre gardes, dans cet ordre :
      1. etat DECLARE — un daemon eteint expres n'est pas en panne. On reutilise le
         verdict du diagnostic (`_daemons_au_repos_declare`) au lieu d'en ecrire un
         second : deux organes qui lisent le meme vocabulaire avec des armements
         opposes, c'est exactement ce qui a produit ce defaut ;
      2. COOLDOWN — pas deux tentatives dans la meme fenetre ;
      3. POST-CONDITION — la reussite se mesure au tick SUIVANT, sur la fraicheur du
         heartbeat. Une relance dont le heartbeat ne repart pas est un ECHEC compte ;
      4. BUDGET puis QUARANTAINE — N echecs d'affilee arretent les frais et le DISENT.
    """
    import subprocess
    from datetime import datetime as _dt

    try:
        from nokido_agent.app.forge_health_diagnostic import _daemons_au_repos_declare

        _exempts, _pourquoi = _daemons_au_repos_declare()
        _declare_lisible = True
    except Exception as e:  # noqa: BLE001
        _exempts, _pourquoi = (), f"etat declare ILLISIBLE ({type(e).__name__})"
        _declare_lisible = False

    etat = _watchdog_etat_lire()
    results: dict[str, str] = {}
    now = time.time()

    for d in DAEMON_WATCHDOGS:
        name = d["name"]
        hb_path = d["heartbeat"]
        mem = etat.setdefault(
            name,
            {"echecs": 0, "derniere_tentative": 0.0, "quarantaine_jusqua": 0.0,
             "verdict_rendu": 0.0},
        )

        if not hb_path.exists():
            results[name] = "missing_heartbeat"
            continue
        try:
            data = json.loads(hb_path.read_text(encoding="utf-8"))
            age = now - _dt.fromisoformat(data.get("ts", "")).timestamp()
        except Exception as e:  # noqa: BLE001
            results[name] = f"err:{e}"
            continue

        # --- Garde 3 : verdict sur la tentative PRECEDENTE, avant toute decision neuve
        tentative = mem.get("derniere_tentative", 0.0)
        if tentative and mem.get("verdict_rendu", 0.0) != tentative:
            heartbeat_ts = now - age
            if heartbeat_ts > tentative:
                mem.update({"echecs": 0, "quarantaine_jusqua": 0.0,
                            "verdict_rendu": tentative})
            elif now - tentative > d["stale_s"]:
                mem["echecs"] = mem.get("echecs", 0) + 1
                mem["verdict_rendu"] = tentative
                print(f"  [watchdog] {name} relance SANS EFFET "
                      f"(echec {mem['echecs']}/{_WATCHDOG_BUDGET})", flush=True)

        if age <= d["stale_s"]:
            results[name] = f"ok({age:.0f}s)"
            continue

        # --- Garde 1 : eteint volontairement ?
        if _watchdog_au_repos(name, _exempts):
            results[name] = f"au_repos_declare({age:.0f}s) — {_pourquoi}"
            continue
        if not _declare_lisible:
            # On ignore si ce daemon est eteint expres. Relancer a l'aveugle peut
            # dupliquer un process sain ; s'abstenir ne coute qu'un tick. Le prix des
            # deux erreurs n'est pas le meme.
            results[name] = f"indetermine({age:.0f}s) — {_pourquoi}"
            continue

        # --- Garde 4 : quarantaine en cours, ou budget epuise
        if now < mem.get("quarantaine_jusqua", 0.0):
            results[name] = (f"quarantaine({(mem['quarantaine_jusqua'] - now) / 60:.0f}"
                             " min restantes)")
            continue
        if mem.get("echecs", 0) >= _WATCHDOG_BUDGET:
            mem["quarantaine_jusqua"] = now + _WATCHDOG_QUARANTAINE_S
            mem["echecs"] = 0
            results[name] = f"QUARANTAINE ({_WATCHDOG_BUDGET} relances sans effet)"
            print(f"  [watchdog] {name} -> QUARANTAINE "
                  f"{_WATCHDOG_QUARANTAINE_S / 3600:.0f} h apres {_WATCHDOG_BUDGET} "
                  "relances sans effet", flush=True)
            continue

        # --- Garde 2 : cooldown
        if now - mem.get("derniere_tentative", 0.0) < _WATCHDOG_COOLDOWN_S:
            results[name] = f"cooldown({age:.0f}s)"
            continue

        try:
            proc = subprocess.Popen(
                d["cmd"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception as e:  # noqa: BLE001
            mem["echecs"] = mem.get("echecs", 0) + 1
            results[name] = f"spawn_echec:{type(e).__name__}"
            continue
        mem["derniere_tentative"] = now
        results[name] = f"relance(stale={age:.0f}s, pid={proc.pid})"
        print(f"  [watchdog] {name} stale={age:.0f}s -> relance pid={proc.pid} "
              "(verification au prochain tick)", flush=True)

    _watchdog_etat_ecrire(etat)
    return results


def _ram_pct() -> float:
    try:
        import psutil

        vm = psutil.virtual_memory()
        return round(vm.percent, 1)
    except Exception:
        return 0.0


def _get_novelty_vector() -> Optional["torch.Tensor"]:
    """Génère un vecteur 64-dim des métriques système pour l'Autoencoder."""
    try:
        import torch
        import psutil
        import math

        vec = [0.0] * 64
        # 0-4: Stress système de base
        vec[0] = psutil.cpu_percent() / 100.0
        vm = psutil.virtual_memory()
        vec[1] = vm.percent / 100.0
        vec[2] = psutil.disk_usage(str(ROOT)).percent / 100.0
        net = psutil.net_io_counters()
        vec[3] = (math.log1p(net.bytes_sent) / 30.0) % 1.0
        vec[4] = (math.log1p(net.bytes_recv) / 30.0) % 1.0
        # 5-7: État des processus (zombies, threads)
        vec[5] = len(psutil.pids()) / 1000.0
        # Reste : Padding ou bruit déterministe
        return torch.FloatTensor(vec).unsqueeze(0)
    except Exception:
        return None


def _algedonic_signals(out: dict) -> list[dict]:
    """Extrait du tick les signaux qui MERITENT S5 (identite/perimetre), pas le bruit.

    Severite conservatrice A DESSEIN : un canal d'alarme qui porte du routinier ne se
    lit plus. `medium` est trace mais N'ESCALADE PAS (cf. algedonic_to_police : hot =
    high|critical). Elargir ce mapping demande une mesure de frequence reelle, pas une
    intuition -- 288 ticks/jour a 5 min.
    """
    sigs: list[dict] = []
    ph = out.get("phases") or {}

    # Du DECLARE fait qui ne l'est pas = probleme d'IDENTITE, donc S5 et pas S3.
    _di = (ph.get("delivery_integrity") or {}).get("result") or {}
    for _f in (_di.get("findings") or []):
        if _f.get("severity") == "high":
            sigs.append({"kind": "delivery_integrity", "severity": "high",
                         "detail": f"{_f.get('kind')}:{_f.get('target')} {_f.get('detail')}"})

    # Des listeners fantomes ont ete termines = le perimetre du soi a bouge.
    _rc = (ph.get("reconcile") or {}).get("result") or {}
    if isinstance(_rc, dict) and _rc.get("reconciled"):
        sigs.append({"kind": "port_reconcile", "severity": "high",
                     "detail": f"listeners fantomes termines: {_rc['reconciled']}"})

    # Anomalie de l'environnement = signal S4. Trace, n'escalade pas seule.
    _nov = out.get("novelty") or {}
    if _nov.get("alert"):
        sigs.append({"kind": "novelty_anomaly", "severity": "medium",
                     "detail": f"score={_nov.get('score')} tau={_nov.get('threshold')}"})

    # CELLULE VIVANTE, ORGANE MORT : le keeper bat, l'organe ne repond pas, et
    # quelqu'un le RECLAME. Meme famille que `delivery_integrity` -- un DECLARE (le
    # pouls) contredit par le fait (la fonction) -- donc S5 et pas S3.
    #
    # `medium` A DESSEIN, et c'est la docstring ci-dessus qui l'impose : un organe
    # mort le reste d'un tick au suivant, donc ce signal se repeterait 288 fois par
    # jour. Le promouvoir en `high` sans avoir mesure la duree mediane d'un organe
    # mort remplirait le canal d'alarme de routinier -- « elargir ce mapping demande
    # une mesure de frequence reelle, pas une intuition ». Il est TRACE des
    # maintenant, ce qui suffit a fournir cette mesure.
    _he = (ph.get("health") or {}).get("result") or {}
    for _o in (_he.get("organes_morts") or []):
        sigs.append({"kind": "organe_mort", "severity": "medium",
                     "detail": "%s: %s" % (_o.get("organe"), _o.get("motif"))})

    # Derive CHRONIQUE du modele du monde (S4) : la severite vient du ratio mesure,
    # elle n'est pas decidee ici -- sinon le seuil vivrait a deux endroits.
    _s4 = out.get("s4_drift") or {}
    if _s4.get("severity"):
        sigs.append({"kind": "world_model_drift", "severity": _s4["severity"],
                     "detail": f"surprise ratio={_s4.get('ratio')} sur n={_s4.get('n')} obs"})

    return sigs


def tick(state: dict) -> dict:
    """Un tick d'orchestration biomimétique."""
    tc = state.get("tick_count", 0)
    tau = _flow_regulator.get_dynamic_threshold()
    ram = _ram_pct()
    out: dict = {"tick": tc, "ts": datetime.now().isoformat(), "tau_novelty": tau, "ram_pct": ram, "phases": {}}
    if ram > RAM_SLEEP_PCT:
        print(f"[homeo] WARNING RAM {ram}% > {RAM_SLEEP_PCT}% — tick interval extended", flush=True)

    # 0. Novelty Analysis (AugmentedNovelty) — lazy-loaded, torch stays out of startup
    _nov = _get_novelty()
    if _nov:
        data = _get_novelty_vector()
        if data is not None:
            res = _nov.check_and_alert(data)
            out["novelty"] = res
            if res.get("alert"):
                print(f"  [novelty] ⚠ ANOMALY DETECTED (score={res['score']} > tau={res['threshold']})", flush=True)
            _nov.learn_pattern(data)

    # W. Daemon watchdog (chaque tick — léger, redémarre les daemons stale)
    out["phases"]["watchdog"] = _safe_call("watchdog", _watchdog_daemons)

    # RB. Sentinel de reboot (owner 2026-07-23) : le corps SENT son propre redémarrage.
    try:
        from nokido_agent.app.forge_reboot_sentinel import run_cycle as reboot_cycle

        _rb = _safe_call("reboot_sentinel", reboot_cycle)
        out["phases"]["reboot_sentinel"] = _rb
        if isinstance(_rb.get("result"), dict) and _rb["result"].get("rebooted"):
            print("  [reboot] DÉTECTÉ : boot_time changé -> reconcile post-boot", flush=True)
    except ImportError as _e_rb:
        out["phases"]["reboot_sentinel"] = {"ok": False, "err": str(_e_rb)}

    # R. Reconcile proprioceptif (owner 2026-07-23) : registre superviseur vs listeners
    # reels -> terminate les enfants perdus du registre (zombie-gap boot) sur TOUS les
    # ports geres. Nokido = organisme vivant qui se regule. Gardes anti-stale + anti-fork.
    try:
        from nokido_agent.app.forge_port_reconcile import run_cycle as reconcile_cycle

        _rc = _safe_call("reconcile", reconcile_cycle)
        out["phases"]["reconcile"] = _rc
        _res = _rc.get("result") or {}
        if isinstance(_res, dict) and _res.get("reconciled"):
            print(f"  [reconcile] {len(_res['reconciled'])} listener(s) fantome(s) termine(s): "
                  f"{_res['reconciled']}", flush=True)
    except ImportError as e:
        out["phases"]["reconcile"] = {"ok": False, "err": str(e)}

    # R2. Moisson des orphelins llama hors-registre (owner 2026-08-27). Un runner
    # enfant d'ollama.exe alors qu'/api/ps declare 0 modele echappe aux TROIS
    # regulateurs (eviction noop, port_reconcile port-only, keeper coder-only) : c'est
    # le glouton 5.59 Go tue a la main le 2026-07-25. Le reaper EXISTAIT depuis lors
    # SANS emetteur (organe non cable, dette ouverte) ; on lui en donne un ICI, a cote
    # de reconcile -- meme famille (proprioception + acte). Critere CONSERVATEUR (kill
    # seulement 0-modele declare + gros), cap par run, boucle fermee (effet RAM mesure).
    try:
        from nokido_agent.tools.forge_orphan_reaper import run_cycle as reaper_cycle

        _or = _safe_call("orphan_reaper", lambda: reaper_cycle(kill=True))
        out["phases"]["orphan_reaper"] = _or
        _ores = _or.get("result") or {}
        if isinstance(_ores, dict) and _ores.get("reaped"):
            print(f"  [reaper] {len(_ores['reaped'])} orphelin(s) llama moissonne(s): "
                  f"{_ores['reaped']} (RAM {_ores.get('delta_pt')} pt)", flush=True)
    except ImportError as e:
        out["phases"]["orphan_reaper"] = {"ok": False, "err": str(e)}

    # 1. Monitor + Analyze : health diag (émet aussi les hormones)
    #
    # CE QUI NE DOIT PAS SE PERDRE EN ESPACANT CE BILAN : `_algedonic_signals` lit
    # `phases.health.result` pour detecter « cellule vivante, organe mort ». Un tick
    # sans bilan ne doit donc PAS rendre ce canal aveugle : on rejoue le dernier
    # resultat connu en le marquant de son AGE -- le consommateur sait alors qu'il lit
    # une mesure precedente et non l'instant present. Un bilan jamais effectue se DIT,
    # il ne se remplace pas par un vert par defaut.
    _tc_health = int(state.get("tick_count", 0))
    if (_tc_health % RYTHME_HEALTH == 0) or bool(state.get("health_urgent")):
        try:
            from nokido_agent.app.forge_health_diagnostic import run_cycle as health_cycle

            out["phases"]["health"] = _safe_call("health", health_cycle)
            state["health_dernier"] = out["phases"]["health"]
            state["health_dernier_tick"] = _tc_health
            state["health_urgent"] = False
        except ImportError as e:
            out["phases"]["health"] = {"ok": False, "err": str(e)}
    elif state.get("health_dernier"):
        out["phases"]["health"] = dict(state["health_dernier"], rejoue=True,
                                       age_ticks=_tc_health - int(state.get("health_dernier_tick", _tc_health)))
    else:
        out["phases"]["health"] = {"ok": False, "err": "bilan pas encore effectue",
                                   "rejoue": True, "age_ticks": None}

    # E. Économe (owner 2026-07-23) : gouverneur du coût cloud (organe P2 réveillé).
    # Lit coût+quota RÉELS et ÉMET CORTISOL_QUOTA_CLOUD -> l'efferent déjà câblé
    # (router local-first + gate cloud-block) fire sur le budget réel, pas 1×/jour.
    try:
        from nokido_agent.app.forge_econome import run_cycle as econome_cycle

        _ec = _safe_call("econome", econome_cycle)
        out["phases"]["econome"] = _ec
        _er = _ec.get("result") or {}
        if isinstance(_er, dict) and _er.get("cortisol_emitted"):
            print(f"  [econome] budget stress {_er.get('stress')} -> CORTISOL_QUOTA_CLOUD "
                  f"(cost ${_er.get('cost_usd_today')}/{_er.get('daily_budget')}, "
                  f"quota_exhausted {_er.get('quota_pressure')})", flush=True)
    except ImportError as e:
        out["phases"]["econome"] = {"ok": False, "err": str(e)}

    # 2. Plan + Execute : pluripotent worker selon hormones
    # (via _safe_call = timeout dur : le rag_warmer embed = suspect n1 du wedge)
    try:
        from nokido_agent.app.forge_pluripotent_workers import PluripotentWorker

        worker = PluripotentWorker(name=f"orchestrator_stem_{tc}")
        # Rythme propre : du TRAVAIL cognitif (9,7 s par appel, 17 % du temps mesure),
        # pas une sonde -- il peut attendre un tick sur deux.
        _pp = (_safe_call("pluripotent", worker.cycle) if tc % RYTHME_PLURIPOTENT == 0
               else {"ok": True, "result": f"saute (rythme 1/{RYTHME_PLURIPOTENT})"})
        out["phases"]["pluripotent"] = {
            "ok": _pp["ok"],
            "role": getattr(worker, "current_role", None),
            "action": _pp.get("result"),
            **({} if _pp["ok"] else {"err": _pp.get("err")}),
        }
    except Exception as e:
        out["phases"]["pluripotent"] = {"ok": False, "err": f"{type(e).__name__}: {e}"}

    # 3. Self-healing : coagulation cascade (chaque tick — peu coûteux)
    try:
        from nokido_agent.app.forge_coagulation_cascade import run_cycle as coag_cycle

        out["phases"]["coagulation"] = _safe_call("coagulation", coag_cycle)
    except ImportError as e:
        out["phases"]["coagulation"] = {"ok": False, "err": str(e)}

    # 4. Self-protecting : immune adaptive (chaque heure = 1/12 ticks 5min)
    if tc % 12 == 0:
        try:
            from nokido_agent.app.forge_immune_adaptive import run_cycle as imm_cycle

            out["phases"]["immune"] = _safe_call("immune", imm_cycle)
        except ImportError as e:
            out["phases"]["immune"] = {"ok": False, "err": str(e)}

    # 5. Knowledge consolidation : hebbian (chaque 6h = 1/72 ticks 5min)
    if tc % 72 == 0:
        try:
            from nokido_agent.app.forge_hebbian_linker import run_cycle as heb_cycle

            out["phases"]["hebbian"] = _safe_call("hebbian", heb_cycle)
        except ImportError as e:
            out["phases"]["hebbian"] = {"ok": False, "err": str(e)}

    # 6. Capitalisation : skill_enricher (chaque heure)
    if tc % 12 == 0:
        try:
            from nokido_agent.app.forge_skill_enricher import run_cycle as skill_cycle

            out["phases"]["skills"] = _safe_call(
                "skills", lambda: skill_cycle(threshold=2, since_ts=0, auto_review=False)
            )
        except ImportError as e:
            out["phases"]["skills"] = {"ok": False, "err": str(e)}

    # 7. Renal clearance dry-run quotidien (chaque 24h = 1/288 ticks 5min)
    if tc % 288 == 0 and tc > 0:
        try:
            from nokido_agent.app.forge_renal_clearance import run_cycle as ren_cycle

            out["phases"]["renal"] = _safe_call(
                "renal", lambda: ren_cycle(dry_run=True, do_vacuum=False, dedup_chunks=False)
            )
        except ImportError as e:
            out["phases"]["renal"] = {"ok": False, "err": str(e)}

    # T. Task runner — drain agt_daemon queue via GOAP (via _safe_call = timeout dur ;
    # une task GOAP peut ask_llm sans timeout = suspect secondaire du wedge)
    try:
        from nokido_agent.app.forge_goap import drain_queue

        _tr = _safe_call("task_runner", lambda: drain_queue(agent="agt_daemon", max_tasks=5, ring_max=3))
        out["phases"]["task_runner"] = _tr
        result = _tr.get("result") or {}
        if isinstance(result, dict) and result.get("tasks", 0) > 0:
            print(
                f"  [task_runner] {result['tasks']} tasks: "
                f"{result.get('completed', 0)} done {result.get('failed', 0)} failed",
                flush=True,
            )
    except Exception as e:
        out["phases"]["task_runner"] = {"ok": False, "err": f"{type(e).__name__}: {str(e)[:120]}"}

    # 8. Tool efficiency comparison (chaque 2h = 1/24 ticks)
    if tc % 24 == 0:
        try:
            from nokido_agent.app.forge_tool_efficiency import run_cycle as eff_cycle

            out["phases"]["efficiency"] = _safe_call("efficiency", eff_cycle)
        except ImportError as e:
            out["phases"]["efficiency"] = {"ok": False, "err": str(e)}

    # S. Self-awareness (owner 2026-07-23) : le corps SENT son etat complet
    # (organes locaux + capacites cloud + quotas + budget) et le persiste au
    # SSoT de soi (sandbox/self_state.json), lisible par tout organe/agent sans
    # recalcul. Nokido "a conscience de soi et de ses capacites cloud avec quotas".
    # Horaire (1/12 ticks 5min) : get_all_quotas = lectures DB, peu couteux.
    if tc % 12 == 0:
        try:
            from nokido_agent.app.forge_self_awareness import publish_self_state

            out["phases"]["self_awareness"] = _safe_call("self_awareness", publish_self_state)
        except ImportError as e:
            out["phases"]["self_awareness"] = {"ok": False, "err": str(e)}

    # DI. Integrite de livraison (owner 2026-07-24) : confronte ce qui est DECLARE
    # fait au REEL (git + tasks.db). Ne du constat que la roadmap avait ete ecrite
    # sur des attestations d'agents jamais verifiees -- une task revenue OK_DONE en
    # citant un commit ANTERIEUR a sa propre creation. Deterministe, zero token.
    # Toutes les 2h (1/24 ticks 5min) : signal lent (push, bump, files gelees).
    if tc % 24 == 0:
        try:
            from nokido_agent.app.forge_delivery_integrity import scan as delivery_scan

            _di = _safe_call("delivery_integrity", delivery_scan)
            out["phases"]["delivery_integrity"] = _di
            _dr = _di.get("result") or {}
            for _f in (_dr.get("findings") or []):
                # Un finding qui ne remonte nulle part est un capteur muet : on le DIT.
                if _f.get("severity") == "high":
                    print(f"  [delivery] ⚠ {_f['kind']} ({_f['target']}): {_f['detail']}",
                          flush=True)
        except ImportError as e:
            out["phases"]["delivery_integrity"] = {"ok": False, "err": str(e)}

    # F. Journal de FLAP (2026-07-25) : prealable MESURABLE au S2 anti-oscillateur.
    # Le `restarts` du superviseur repart de zero a chaque boot : un flap chronique
    # etait donc structurellement indetectable -- on lisait un instant t d'un fait
    # TEMPOREL. Chaque tick et pas moins : un flap peut etre rapide, l'echantillonner
    # aux 2 h le raterait. N'ESCALADE RIEN (severity warn) : on observe avant de
    # reguler, les seuils de l'amortisseur viendront du journal et non d'une intuition.
    # Anti-dup : le backoff de RESPAWN existe deja cote superviseur (`backoffIdx`).
    try:
        from nokido_agent.app.forge_flap_journal import run_cycle as flap_cycle

        _fl = _safe_call("flap_journal", flap_cycle)
        out["phases"]["flap_journal"] = _fl
        _fr = _fl.get("result") or {}
        if isinstance(_fr, dict) and _fr.get("flapping"):
            print(f"  [flap] {len(_fr['flapping'])} service(s) redemarre(s) : "
                  f"{_fr['flapping']}", flush=True)
    except ImportError as e:
        out["phases"]["flap_journal"] = {"ok": False, "err": str(e)}

    # S4. Homeostat 3-4-5 (2026-07-25) : S4 (modele du monde) -> S5. `recent_surprise`
    # a ete CALIBREE le 2026-07-24 (fenetre par COMPTAGE, car l'all-time est domine par
    # l'archeologie) et personne ne la lit : sa propre docstring anticipait qu'un
    # regulateur branche dessus "serait decoratif" s'il ratait la fenetre. Une surprise
    # CHRONIQUE dit que le modele interne ne predit plus le corps -- fait d'identite,
    # donc S5. C'est le couplage S3<->S4 que le corpus VSM designe comme le point
    # d'echec habituel : ici S3 etait hypertrophie et S4 ne retroagissait pas.
    # Calibrage MESURE 2026-07-25 : seuil high = 2.0 ; fenetre 7j/20 obs -> ratio
    # 0.0925 (mean 0.185) ; l'all-time aurait dit 1.2252, soit 13x = un faux cri.
    # Marge x10 avant le premier signal. `n >= 10` car une moyenne sur moins de points
    # n'est pas une tendance -- le debit reel est ~3 observations/jour, d'ou 1 tick
    # sur 24 (2h) : un tick de 5 min ne verrait rien de neuf.
    if tc % 24 == 0:
        try:
            from nokido_agent.app.forge_active_inference import recent_surprise

            _rs = _safe_call("world_model_surprise", recent_surprise)
            out["phases"]["world_model_surprise"] = _rs
            _r = _rs.get("result") or {}
            if isinstance(_r, dict) and _r.get("ok") and int(_r.get("n") or 0) >= 10:
                _ratio = float(_r.get("ratio") or 0.0)
                if _ratio >= 1.0:
                    out["s4_drift"] = {"severity": "high", "ratio": _ratio, "n": _r["n"]}
                elif _ratio >= 0.5:
                    out["s4_drift"] = {"severity": "medium", "ratio": _ratio, "n": _r["n"]}
        except ImportError as e:
            out["phases"]["world_model_surprise"] = {"ok": False, "err": str(e)}

    # A. Canal ALGEDONIQUE S3 -> S5 (2026-07-25). Les alarmes ci-dessus ne faisaient
    # qu'un print() : elles mouraient avec le stdout du daemon, donc AUCUNE n'atteignait
    # la Police. `forge_viable_system` (VSM, Beer) tranche l'escalade et
    # `forge_critical_events` (append-only, survit au restart) porte le signal.
    # Pourquoi ici : le VSM etait ecrit + teste + documente depuis 2026-06-14
    # (docs/CYBERNETIC_ORGANIZATION_VSM.md) mais AUCUN module ne l'importait -- le doc
    # nommait deja cette boucle S5<-S3 comme "le vrai chantier". Fail-open total : le
    # regulateur ne doit JAMAIS tomber a cause de son propre canal d'alarme.
    try:
        from nokido_agent.app import forge_viable_system as _vsm
        from nokido_agent.app.forge_critical_events import persist as _crit_persist

        _sigs = _algedonic_signals(out)
        _escalated = []
        for _s in _sigs:
            _verdict = _vsm.algedonic_to_police(_s)
            if _verdict.get("escalate"):
                _crit_persist(
                    kind=f"algedonic:{_s['kind']}",
                    severity=_s["severity"],
                    payload={"detail": _s.get("detail"), "tick": tc,
                             "vsm_action": _verdict.get("action")},
                )
                _escalated.append(_s["kind"])
                print(f"  [algedonic] ⚠ {_s['kind']} -> S5 ({_verdict.get('action')}): "
                      f"{_s.get('detail')}", flush=True)
            else:
                # Un signal TRACE mais non escalade ne doit pas mourir dans un
                # compteur : `out` n'est PAS persiste (seul `state` l'est), donc sans
                # cette ligne « signals: 3 » serait tout ce qui reste -- un nombre
                # sans consommateur, exactement le defaut qu'on repare ici. Le log du
                # daemon est date : c'est lui qui porte la dimension TEMPS dont la
                # promotion de severite a besoin.
                print(f"  [algedonic] ~ {_s['kind']} ({_s['severity']}, non escalade): "
                      f"{_s.get('detail')}", flush=True)
        out["phases"]["algedonic"] = {
            "ok": True, "signals": len(_sigs), "escalated": _escalated,
            "traces": [{"kind": _s["kind"], "severity": _s["severity"],
                        "detail": _s.get("detail")} for _s in _sigs],
        }
    except Exception as e:  # noqa: BLE001 — canal d'alarme, jamais bloquant
        out["phases"]["algedonic"] = {"ok": False, "err": f"{type(e).__name__}: {e}"}

    return out


def main() -> int:
    import sys as _sys, io as _io

    if hasattr(_sys.stdout, "buffer"):
        _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Nokido homeostasis orchestrator")
    ap.add_argument("--once", action="store_true", help="1 tick puis exit")
    ap.add_argument("--daemon", action="store_true", help="boucle 5 min")
    ap.add_argument("--tick", type=int, default=DEFAULT_TICK_S)
    args = ap.parse_args()
    if not args.once and not args.daemon:
        ap.error("--once ou --daemon requis")

    state = _load_state()
    if args.daemon:
        try:
            (SANDBOX / "homeostasis.pid").write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

    # Le TICK metier reste celui de l'homeostasie ; le POULS suit le coeur.
    cad = Cadence("homeostasis_orchestrator", cycle_s=args.tick)
    while True:
        out = tick(state)
        ok_phases = [p for p, d in out["phases"].items() if d.get("ok")]
        ko_phases = [p for p, d in out["phases"].items() if not d.get("ok")]
        print(
            f"[homeo] tick #{state['tick_count']} tau={out.get('tau_novelty', '?')} ram={out.get('ram_pct', '?')}% : ok={ok_phases} ko={ko_phases}",
            flush=True,
        )
        for p, d in out["phases"].items():
            if not d.get("ok"):
                print(f"  KO {p}: {d.get('err', '?')[:120]}", flush=True)
            elif p == "pluripotent":
                print(f"  -> role={d.get('role')}", flush=True)
            elif p == "health":
                r = d.get("result", {})
                if isinstance(r, dict):
                    print(
                        f"  -> health score={r.get('score', '?')}/100 hormones={r.get('hormones_released', [])}",
                        flush=True,
                    )

        state["tick_count"] = state.get("tick_count", 0) + 1
        state["last_tick_ts"] = time.time()
        _save_state(state)
        cad.cycle_termine(ok=True, ram_pct=out.get("ram_pct", 0.0),
                          tick_count=state.get("tick_count"))

        if args.once:
            return 0
        # Le TRAVAIL ralentit sous pression RAM (300 -> 600 s) ; le POULS, lui, ne
        # ralentit pas — il suit le coeur. C'est le COUPLAGE des deux qui evinçait cet
        # organe au moment precis ou il sert le plus : 238 relances sous ce nom, 463
        # sous l'ancien. Ralentir le travail sous charge reste une bonne politique ;
        # ralentir le signe de vie avec lui etait le defaut.
        ram = out.get("ram_pct", 0.0)
        cad.cycle_s = args.tick * 2 if ram > RAM_SLEEP_PCT else args.tick
        while not cad.tour():
            cad.dormir()


if __name__ == "__main__":
    sys.exit(main())
