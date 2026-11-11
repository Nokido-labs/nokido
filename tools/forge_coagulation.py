#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_coagulation.py — agent COAGULATION : consomme les signaux critiques + soigne (borné).

La sentinelle anti-embolie (forge_organ_pulse) VOIT ; la COAGULATION SOIGNE. Elle draine
forge_critical_events (processed_at IS NULL = le caillot que personne ne consommait), TRIAGE
chaque signal, RÉAGIT, puis mark_processed -> le caillot se vide. Complément immunitaire
(P1 census organe×agent : la détection appelait un réacteur).

TRIAGE -> 4 voies (SOIN ajoutee le 7/11, entre service et heal : integrite de livraison re-mesuree et soignee
par forge_remediation.check_delivery_integrity ; seules les DECISIONS remontent a l'owner) :
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
import re
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
# Periode refractaire (20/10, fin de la CIVD) : apres un soin complet, pas de nouveau soin avant REFRACTAIRE_S --
# comme l'hemostase, qui ne relance pas la cascade sur un caillot deja forme.
REFRACTAIRE_S = 1800
_REFRACTAIRE = ROOT / "sandbox" / "coagulation_refractaire.json"


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


def _produit_du_soin(blob: str) -> bool:
    return '"origine": "forge_remediation"' in blob or "'origine': 'forge_remediation'" in blob


# Integrite de livraison (7/11, owner : « si le corps recoit des signaux il doit savoir les traiter de facon
# autonome » ; « a part les relayer je ne peux pas en faire grand chose »). Ces constats allaient TOUS chez l'owner
# (« haute severite non classee »). Le corps les re-mesure et les soigne (forge_remediation.check_delivery_integrity) ;
# vers l'owner ne remonte que ce qui EXIGE une decision humaine (push, secret, geste irreversible, droits).
_INTEGRITE = "delivery_integrity"
_INTEGRITE_SOIGNABLES = ("attestation_commit_anterieur", "travail_non_commite", "file_non_drainee",
                         "submodule_non_bumpe", "ci_en_echec")
_INTEGRITE_ETATS = ("commits_non_pousses",)   # un etat, lisible au scan : pas une alerte
_INTEGRITE_DECISIONS = {
    "branche_sans_upstream": "choisir l'upstream de la branche et decider du push",
    "submodule_illisible": "ouvrir la lecture du submodule au compte du scan (droits) ou l'accepter aveugle",
}
_RE_CONSTAT = re.compile(r"^\s*([a-z_]+)\s*:")


def _constat_integrite(ev: dict):
    """Type du constat d'integrite porte par le signal ; None si le signal n'en est pas un, "" si illisible."""
    if _INTEGRITE not in str(ev.get("kind", "")):
        return None
    payload = ev.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:  # muet-ok : constat illisible rendu "" -> tri historique, jamais perdu
            payload = None
    m = _RE_CONSTAT.match(str(payload.get("detail") or "")) if isinstance(payload, dict) else None
    return m.group(1) if m else ""


def _triage(ev: dict) -> tuple:
    """Classe un signal -> (voie, raison). Pur, testable."""
    blob = f"{ev.get('kind', '')} {ev.get('severity', '')} {ev.get('payload', '')}".lower()
    if any(s in blob for s in _SECURITY):
        return "escalate", "sécurité — humain requis"
    # Embolie d'absence seule -> soin avant la regle service.
    try:
        from tools.forge_organ_pulse import ABSENCE_SIGNS
    except Exception:  # noqa: BLE001
        ABSENCE_SIGNS = set()
    _emb = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
    _embs = _emb.get("embolies") or []
    if ev.get("kind") == "organ_pulse:heartbeat" and _embs and set(_embs) <= set(ABSENCE_SIGNS):
        return "soin", "embolie d'absence — soin par le corps"
    if any(s in blob for s in _SERVICE):
        return "escalate", "service dégradé — diagnostic avant toute relance"
    constat = _constat_integrite(ev)
    if constat:
        if _produit_du_soin(blob):
            return "ack", "produit du soin (inhibiteur) : ne relance pas le soin"
        if constat in _INTEGRITE_ETATS:
            return "ack", "etat, pas une alerte : %s reste lisible au scan d'integrite" % constat
        if constat in _INTEGRITE_SOIGNABLES or constat in _INTEGRITE_DECISIONS:
            return "soin", "integrite de livraison : re-mesure et soin par le corps"
        # constat d'un autre type : tri historique ci-dessous, rien n'est perdu
    if any(s in blob for s in _REMEDIABLE):
        # Inhibiteur (20/10) : un signal SIGNE par la remediation est le produit du soin, pas une lesion -- le
        # soigner relancait la remediation qui le reemettait (CIVD, toutes les ~5 min). L'alarme, elle, passe :
        # securite et service sont tries AVANT ce point.
        if _produit_du_soin(blob):
            return "ack", "produit du soin (inhibiteur) : ne relance pas la remediation"
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


_CAUSE_MAX = 160


def _cause_escalade(ev: dict) -> str:
    """Le `detail` du payload (forge_homeostasis_orchestrator.py:816), borne ; sinon le dire, sans deviner (6/11)."""
    payload = ev.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:  # muet-ok : payload illisible rendu `cause: ILLISIBLE` juste en dessous
            payload = None
    detail = ""
    if isinstance(payload, dict):
        # 6/11 : self_care porte `fault`, les crashs `service` : l'alerte disait ILLISIBLE alors que la cause etait la.
        detail = str(payload.get("detail") or payload.get("fault") or "").strip()
        if not detail and payload.get("service"):
            detail = str(payload["service"])
            if payload.get("crash_count"):
                detail += " : %s crashs en %s s" % (payload["crash_count"], payload.get("window_s", "?"))
            elif payload.get("code") not in (None, ""):
                detail += " : sortie code %s" % payload["code"]
    if not detail:
        return "cause: ILLISIBLE"
    if len(detail) > _CAUSE_MAX:
        return f"{detail[:_CAUSE_MAX]} (+{len(detail) - _CAUSE_MAX} car.)"
    return detail


_URLS_CRITIQUES = {"hub_mcp": "http://127.0.0.1:8766/health", "web_hub": "http://127.0.0.1:7400/health"}
_RE_CRITIQUES_DOWN = re.compile(r"Services CRITIQUES DOWN\s*:\s*\[([^\]]*)\]")


def _sonde_http(url: str):
    """Statut HTTP, ou None si la sonde est muette."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001 - muet-ok : sonde muette rendue None, donc jamais lue comme saine
        return None


def _panne_resolue(ev: dict) -> bool:
    """Un `self_care` « CRITIQUES DOWN » tient-il encore ? La coagulation passe toutes les 5 min : le 6/11, web_hub dit
    DOWN a 19:48:14 demarrait a 19:48:18, et l'owner recevait la fenetre a 19:53:08. Liste BLANCHE : vrai seulement si
    CHAQUE service nomme a une sonde connue qui rend 200 ; un service inconnu ou une sonde muette laisse partir l'alerte."""
    if ev.get("kind") != "self_care":
        return False
    payload = ev.get("payload")
    try:
        payload = json.loads(payload) if isinstance(payload, str) else payload
        m = _RE_CRITIQUES_DOWN.search(str(payload.get("fault") or ""))
    except (ValueError, AttributeError):  # muet-ok : signal illisible = pas de preuve de resolution, l'alerte part
        return False
    noms = re.findall(r"[\w-]+", m.group(1)) if m else []
    return bool(noms) and all(n in _URLS_CRITIQUES and _sonde_http(_URLS_CRITIQUES[n]) == 200 for n in noms)


def _escalate(ev: dict, reason: str) -> None:
    """Notify facteur (hub) — réveille l'humain/coagulation. Best-effort."""
    msg = f"[COAGULATION][ESCALADE] {ev.get('kind')} sev={ev.get('severity')} ({_cause_escalade(ev)}) — {reason}"
    if _panne_resolue(ev):
        _log("[COAGULATION][RESOLUE AVANT REMISE] " + msg)
        return
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
        from nokido_agent.app.forge_critical_events import alerter_owner

        # 4/11 : notify sans destinataire finissait dans EVENTBUS_ARCHIVE (~390 par jour, journalisees « delivree »).
        _rep = alerter_owner(str(ev.get("kind")), str(ev.get("severity") or "warn"), msg, "COAGULATION")
        if _rep == "echec":
            _jlog.error("[COAGULATION] ESCALADE NON REMISE au registre : %s | consequence: "
                        "cet evenement critique n'a alerte PERSONNE", msg)
        else:
            _jlog.info("[COAGULATION] escalade au registre owner (%s) : %s", _rep, msg)
    except Exception as _e:  # noqa: BLE001
        _jlog.error("[COAGULATION] ESCALADE IMPOSSIBLE (%s: %s) : %s | consequence: "
                    "cet evenement critique n'a alerte PERSONNE",
                    type(_e).__name__, str(_e)[:120], msg)


def _soigner_integrite(armed: bool) -> dict:
    """Soin des constats d'integrite par le moteur EXISTANT (forge_remediation, lesion ciblee). Hors periode
    refractaire : il n'emet aucun signal, donc ne peut pas s'auto-entretenir. N'agit que si `armed`, et jamais sous
    verrou humain. Rend le resultat du controle check_delivery_integrity."""
    try:
        from nokido_agent.app.forge_opsec import is_human_locked
        if armed and is_human_locked():
            return {"ok": False, "skipped": "human_locked : soin arme suspendu"}
        from nokido_agent.app.forge_remediation import run_remediation_cycle
        r = run_remediation_cycle(armed=armed, lesions=[_INTEGRITE])
        return (r.get("debts") or {}).get("delivery_integrity") or {
            "ok": False, "error": "soin sans resultat"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "soin impossible (%s: %s)" % (type(e).__name__, str(e)[:120])}


def coagulate(limit: int = 200, armed: bool = False, max_rounds: int = 30, armed_integrite: bool = False) -> dict:
    """Draine le caillot : consomme les signaux non traités par lots, triage, réagit, marque.
    armed=True -> forge_remediation AGIT (sinon dry-run). armed_integrite=True -> arme le SEUL soin d'integrite
    (orphelins, ports et autres soins restent desarmes). Boucle jusqu'à drainage."""
    try:
        from nokido_agent.app.forge_critical_events import unprocessed, mark_processed, purge_older_than
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"critical_events indispo: {e}"}
    tally = {"consumed": 0, "escalate": 0, "heal": 0, "ack": 0, "soin": 0, "rounds": 0}
    heal_needed = False
    lesions: list = []
    a_soigner: list = []
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
                lesions.append(str(ev.get("kind", "")))
            elif voie == "soin":
                a_soigner.append(ev)
            ids.append(ev.get("id"))
        tally["consumed"] += mark_processed([i for i in ids if i is not None])
        tally["rounds"] += 1
        if len(batch) < limit:
            break
    if a_soigner:
        # UNE passe de soin pour tout le lot (le soin relit toute la table des constats, pas un signal a la fois),
        # puis l'owner ne recoit que les DECISIONS, en une ligne portant le resultat du soin.
        soin = _soigner_integrite(armed or armed_integrite)
        tally["soin_integrite"] = soin
        resume = str(soin.get("resume") or soin.get("error") or soin.get("skipped") or "soin muet")
        vus: set = set()
        for ev in a_soigner:
            constat = _constat_integrite(ev)
            decision = _INTEGRITE_DECISIONS.get(constat or "")
            if decision and constat not in vus:
                vus.add(constat)
                tally["escalate"] += 1
                _escalate(ev, "DECISION OWNER : %s ; %s" % (decision, resume))
    # heal BORNÉ (une passe) via le moteur existant — n'AGIT que si armed ; jamais deux soins dans la periode
    # refractaire (le dernier soin est consigne dans _REFRACTAIRE).
    if heal_needed:
        try:
            dernier = float(json.loads(_REFRACTAIRE.read_text(encoding="utf-8")).get("dernier_soin", 0))
        except (OSError, ValueError, TypeError):
            dernier = 0.0  # muet-ok : aucun soin consigne = pas de periode refractaire en cours
        reste = REFRACTAIRE_S - (time.time() - dernier)
        if reste > 0:
            heal_needed = False
            tally["remediation"] = {"ok": True, "differe": "periode refractaire : %d s restantes" % int(reste)}
    if heal_needed:
        try:
            _REFRACTAIRE.write_text(json.dumps({"dernier_soin": time.time()}), encoding="utf-8")
        except OSError:  # muet-ok : periode refractaire non consignee = le prochain soin n'attend pas, il se fait
            pass
        try:
            from nokido_agent.app.forge_opsec import is_human_locked
            if armed and is_human_locked():
                # Corrigibility (A#2): verrou humain -> pas de remediation autonome armee.
                tally["remediation"] = {"ok": False, "skipped": "human_locked"}
            else:
                from nokido_agent.app.forge_remediation import run_remediation_cycle
                tally["remediation"] = run_remediation_cycle(armed=armed, lesions=lesions)
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
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_coagulation.py', 196, exc_info=True)
    _log(f"[COAGULATION] {json.dumps(tally, ensure_ascii=False)}")
    return tally


def _travail_differe() -> bool:
    try:
        from nokido_agent.app.forge_resource_manager import travail_differe
    except ImportError:
        return False  # muet-ok : gestionnaire de ressources absent = aucun bail lisible, la passe se fait comme avant
    return travail_differe("NokidoCoagulation")


def watch(interval: int = 300, rounds: int = 0, armed: bool = False, armed_integrite: bool = False) -> int:
    """Boucle (supervisée). Coagule tous les `interval`s ; HEARTBEAT toutes les ~60s
    (frais malgré le drain espacé -> pas de restart-loop superviseur). rounds=0 -> infini."""
    i, last, last_n = 0, 0.0, 0
    while rounds == 0 or i < rounds:
        now = time.time()
        if (i == 0 or now - last >= interval) and _travail_differe():
            # Bail prioritaire actif : le pouls continue, la passe lourde attend (retentee a chaque tour).
            print(json.dumps({"differe": "bail prioritaire actif : passe lourde differee"}), flush=True)
        elif i == 0 or now - last >= interval:
            t = coagulate(armed=armed, armed_integrite=armed_integrite)
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
    ap.add_argument("--armer-integrite", action="store_true", dest="armer_integrite",
                    help="arme le SEUL soin d'integrite de livraison (le reste reste desarme sans --armed)")
    ap.add_argument("--rounds", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.watch:
        return watch(a.watch, a.rounds, a.armed, a.armer_integrite)
    print(json.dumps(coagulate(armed=a.armed, armed_integrite=a.armer_integrite), ensure_ascii=False, indent=2))
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
