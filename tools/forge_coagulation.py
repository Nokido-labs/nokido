#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_coagulation.py — agent COAGULATION : consomme les signaux critiques + soigne (borné).

La sentinelle anti-embolie (forge_organ_pulse) VOIT ; la COAGULATION SOIGNE. Elle draine
forge_critical_events (processed_at IS NULL = le caillot que personne ne consommait), TRIAGE
chaque signal, RÉAGIT, puis mark_processed -> le caillot se vide. Complément immunitaire
(P1 census organe×agent : la détection appelait un réacteur).

TRIAGE -> 3 voies :
  - ESCALADE : sécurité (cve/breach/quarantine) OU service dégradé OU haute sévérité ->
               notify facteur (humain), PUIS mark (acquitté-escaladé, jamais caché).
  - HEAL     : remédiable (embed/db/orphan/stale/quota) -> forge_remediation (moteur borné,
               `armed` requis pour AGIR ; dry-run par défaut). Fédère, ne réinvente pas.
  - ACK      : info/low/vieux -> acquitté + purge des très vieux.

GARDE-FOU NON-NÉGO : AUCUN restart/kill de service en solo (reload=lanceur). Tout heal risqué
= ESCALADE. forge_remediation n'AGIT que si armed=True (autorisation explicite user).
Sur drainage complet : release DOPAMINE (l'organisme ressent le soulagement -> efferent gate).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

HEARTBEAT = ROOT / "sandbox" / "coagulation.heartbeat"
LOG = ROOT / "logs" / "coagulation.log"


def _stamped(msg: str) -> str:
    """Préfixe une ligne via l'autorité unique des timecodes (forge_timecode).

    Mandat owner 2026-07-26 : tout organe qui a besoin d'un horodatage s'y
    inscrit. Ce journal écrivait 3 Mo de lignes sans une seule date.
    Repli local si le module manque : une date approximative vaut mieux qu'aucune.
    """
    try:
        import sys as _s

        _app = str(ROOT / "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_timecode import stamp_line

        return stamp_line(msg)
    except Exception:  # noqa: BLE001
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        return "%s %s" % (_dt.now(tz=_tz.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), msg)

_SECURITY = ("cve", "breach", "quarantine", "injection", "exfil", "intrusion", "security")
_SERVICE = ("crash", "degraded", "service_down", "wedge", "oom", "down", "service")
_REMEDIABLE = ("embed", "backlog", "orphan", "stale", "db", "lock", "balance", "402",
               "oauth", "quota", "contention", "phantom")


def _sev_num(ev: dict) -> float:
    s = str(ev.get("severity", "")).strip().lower()
    try:
        return float(s)
    except ValueError:
        return {"critical": 1.0, "high": 0.9, "warn": 0.6, "medium": 0.5,
                "low": 0.2, "info": 0.1}.get(s, 0.3)


def _triage(ev: dict) -> tuple:
    """Classe un signal -> (voie, raison). Pur, testable."""
    blob = f"{ev.get('kind', '')} {ev.get('severity', '')} {ev.get('payload', '')}".lower()
    if any(s in blob for s in _SECURITY):
        return "escalate", "sécurité — humain requis"
    if any(s in blob for s in _SERVICE):
        return "escalate", "service dégradé — restart=lanceur (humain)"
    if any(s in blob for s in _REMEDIABLE):
        return "heal", "remédiable (forge_remediation borné)"
    if _sev_num(ev) >= 0.9:
        return "escalate", "haute sévérité non classée — prudence"
    return "ack", "low/info — acquitté"


def _log(msg: str) -> None:
    try:
        LOG.parent.mkdir(exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(_stamped(msg) + "\n")
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # On bascule sur un AUTRE canal : signaler l'echec du journal dans le journal
        # qui vient d'echouer ne dirait rien a personne.
        _lg.getLogger(__name__).error(
            "[coagulation] journal %s inaccessible (%s: %s) — message perdu : %s | "
            "consequence: la trace de coagulation a un trou, et un drain silencieux "
            "ressemble a un drain sans travail",
            LOG, type(e).__name__, str(e)[:70], str(msg)[:90])


def _escalate(ev: dict, reason: str) -> None:
    """Notify facteur (hub) — réveille l'humain/coagulation. Best-effort."""
    msg = f"[COAGULATION][ESCALADE] {ev.get('kind')} sev={ev.get('severity')} — {reason}"
    _log(msg)
    # 2026-08-05 — CE BLOC NE MARCHAIT PAS, ET PERSONNE NE POUVAIT LE SAVOIR.
    # L'ancien POST envoyait {"tool":..., "args":...}, qui n'est PAS du JSON-RPC 2.0,
    # SANS en-tete Authorization, et avalait l'echec par `except: pass`. Resultat
    # mesure : chaque escalade partait dans le vide, et ce daemon comptait dans les
    # 4 730 rejets `no_auth` du hub sur 24 h. Une escalade qui ne part pas est pire
    # qu'une escalade absente : elle donne l'illusion d'une surveillance.
    import logging as _logging
    _jlog = _logging.getLogger(__name__)
    try:
        import sys as _sys
        _app = str(Path(__file__).resolve().parent.parent / "app")
        if _app not in _sys.path:
            _sys.path.insert(0, _app)
        from nokido_agent.app.forge_hub_client import HubClient  # client GOUVERNE (identite + coffre)

        _rep = HubClient(agent="COAGULATION").notify(json.dumps({
            "intent": "NEED_HUMAN_APPROVAL",
            "pointer_ref": "critical_events:%s" % ev.get("kind"),
            "confidence": 1.0,
            "detail": msg,
        }, ensure_ascii=False))
        if _rep is None:
            _jlog.error("[COAGULATION] ESCALADE NON DELIVREE (hub injoignable) : %s "
                        "| consequence: cet evenement critique n'a alerte PERSONNE", msg)
        elif isinstance(_rep, str) and ("GATE_DENIED" in _rep or "Erreur" in _rep):
            _jlog.error("[COAGULATION] ESCALADE REFUSEE par le hub : %s | message: %s "
                        "| remede: verifier le ring de COAGULATION dans "
                        "config/agent_identities.json (notify exige ring <= 3)",
                        _rep, msg)
        else:
            _jlog.info("[COAGULATION] escalade delivree au hub : %s", msg)
    except Exception as _e:  # noqa: BLE001
        _jlog.error("[COAGULATION] ESCALADE IMPOSSIBLE (%s: %s) : %s | consequence: "
                    "cet evenement critique n'a alerte PERSONNE",
                    type(_e).__name__, str(_e)[:120], msg)


def coagulate(limit: int = 200, armed: bool = False, max_rounds: int = 30) -> dict:
    """Draine le caillot : consomme les signaux non traités par lots, triage, réagit, marque.
    armed=True -> forge_remediation AGIT (sinon dry-run). Boucle jusqu'à drainage."""
    try:
        from nokido_agent.app.forge_critical_events import unprocessed, mark_processed, purge_older_than
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"critical_events indispo: {e}"}
    tally = {"consumed": 0, "escalate": 0, "heal": 0, "ack": 0, "rounds": 0}
    heal_needed = False
    for _ in range(max_rounds):
        batch = unprocessed(limit)
        if not batch:
            break
        ids = []
        for ev in batch:
            voie, reason = _triage(ev)
            tally[voie] += 1
            if voie == "escalate":
                _escalate(ev, reason)
            elif voie == "heal":
                heal_needed = True
            ids.append(ev.get("id"))
        tally["consumed"] += mark_processed([i for i in ids if i is not None])
        tally["rounds"] += 1
        if len(batch) < limit:
            break
    # heal BORNÉ (une passe) via le moteur existant — n'AGIT que si armed.
    if heal_needed:
        try:
            from nokido_agent.app.forge_opsec import is_human_locked
            if armed and is_human_locked():
                # Corrigibility (A#2): verrou humain -> pas de remediation autonome armee.
                tally["remediation"] = {"ok": False, "skipped": "human_locked"}
            else:
                from nokido_agent.app.forge_remediation import run_remediation_cycle
                tally["remediation"] = run_remediation_cycle(armed=armed)
        except Exception as e:  # noqa: BLE001
            tally["remediation"] = {"ok": False, "error": str(e)}
    try:
        tally["purged_old"] = purge_older_than(7)
    except Exception:  # noqa: BLE001
        tally["purged_old"] = 0
    # Soulagement : drain réussi -> dopamine (l'organisme ressent, alimente l'efferent gate).
    if tally["consumed"] > 0:
        try:
            from nokido_agent.app.forge_endocrine import release
            release("DOPAMINE_SUCCESS", level=min(0.8, tally["consumed"] / 500.0),
                    ttl_s=900, source="coagulation")
        except Exception:  # noqa: BLE001
            pass
    _log(f"[COAGULATION] {json.dumps(tally, ensure_ascii=False)}")
    return tally


def watch(interval: int = 300, rounds: int = 0, armed: bool = False) -> int:
    """Boucle (supervisée). Coagule tous les `interval`s ; HEARTBEAT toutes les ~60s
    (frais malgré le drain espacé -> pas de restart-loop superviseur). rounds=0 -> infini."""
    i, last, last_n = 0, 0.0, 0
    while rounds == 0 or i < rounds:
        now = time.time()
        if i == 0 or now - last >= interval:
            t = coagulate(armed=armed)
            last, last_n = now, t.get("consumed", 0)
            print(json.dumps({"consumed": last_n, "escalate": t.get("escalate")},
                             ensure_ascii=False), flush=True)
        # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : il inscrit le
        # `pid` absent ici, et ne leve jamais — le `try` local devient inutile.
        from nokido_agent.app.forge_heartbeat import beat_daemon

        beat_daemon("coagulation", consumed=last_n)
        i += 1
        if rounds and i >= rounds:
            break
        time.sleep(60)
    return 0


def _main() -> int:
    ap = argparse.ArgumentParser(description="Agent coagulation — draine les signaux critiques")
    ap.add_argument("--coagulate", action="store_true", help="une passe de drainage")
    ap.add_argument("--watch", type=int, metavar="SECONDS", help="boucle périodique")
    ap.add_argument("--armed", action="store_true", help="forge_remediation AGIT (sinon dry-run)")
    ap.add_argument("--rounds", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.watch:
        return watch(a.watch, a.rounds, a.armed)
    print(json.dumps(coagulate(armed=a.armed), ensure_ascii=False, indent=2))
    return 0


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    chk(_triage({"kind": "cve_detected", "severity": "high"})[0] == "escalate", "cve -> escalade")
    chk(_triage({"kind": "service_crash", "severity": "high"})[0] == "escalate", "crash -> escalade")
    chk(_triage({"kind": "embed_backlog", "severity": "warn"})[0] == "heal", "embed -> heal (borné)")
    chk(_triage({"kind": "info_tick", "severity": "low"})[0] == "ack", "info -> ack")
    chk(_triage({"kind": "x", "severity": "0.95"})[0] == "escalate", "haute sévérité num -> escalade")
    chk(_sev_num({"severity": "high"}) == 0.9 and _sev_num({"severity": "0.5"}) == 0.5,
        "_sev_num gère texte + nombre")
    chk(callable(coagulate) and callable(watch), "coagulate/watch callables")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_main())
