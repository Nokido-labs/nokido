# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = test/integration
Harness CLOSED-LOOP INTER-ORGANES — prouve l'homeostasie de l'organisme comme un TOUT.

POURQUOI un module dedie (anti-dup, CLAUDE.md §3) :
  forge_interaction_test.py teste les interactions AGENT<->AGENT (ping_pong,
  debate, chain, rag_collab) = couche cognitive/communications. ICI on teste
  les boucles PHYSIOLOGIQUES inter-organes (endocrine -> homeostasis -> etat),
  sans LLM, sans cloud. Concern different (<50% de recouvrement) -> module
  separe plutot qu'extension semantiquement fausse.

GAP adresse (rapport vision autopoietique, manque #1) : les organes existent
(forge_organ_agents, forge_homeostasis_orchestrator, forge_endocrine, ...) mais
RIEN ne prouve que les boucles inter-organes FERMENT et regulent. Ce harness
transforme "organes cables" en "organisme mesurable".

SECURITE : stimuler un organe = MUTER l'etat du systeme vivant (endocrine ecrit
en DB). Le mode stimulus est donc GATE derriere --live. Par defaut = OBSERVE-ONLY
(zero effet de bord) : prouve quelles boucles sont *observables/instrumentees*.
--live = injecte un signal borne (TTL court) et asserte la REACTION d'un organe couple.

Usage :
  LAFORGE_PYTHON tools/forge_organ_loop_test.py            # observe-only (safe)
  LAFORGE_PYTHON tools/forge_organ_loop_test.py --live     # + stimulus/reaction (mute l'etat)
  LAFORGE_PYTHON tools/forge_organ_loop_test.py --json PATH # rapport json

Sortie : matrice {probe -> wired|open|error|skipped} + rapport json.
  wired  = boucle observable/fermee (OK)
  open   = a tourne mais aucune reaction detectee = boucle NON fermee = gap a cabler
  error  = appel impossible (signature/import) = instrumentation manquante
"""
from __future__ import annotations
import os, sys, json, time, inspect, importlib, argparse, traceback, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
for p in (APP, os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _imp(name):
    try:
        return importlib.import_module(name), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def _callable_with(fn, known):
    """Retourne kwargs jouables si tous les params requis sont satisfiables, sinon None."""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return {}
    kwargs = {}
    for pname, p in sig.parameters.items():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if pname in known:
            kwargs[pname] = known[pname]
        elif p.default is inspect.Parameter.empty:
            return None  # param requis non satisfiable -> ne pas deviner
    return kwargs


class Probe:
    def __init__(self, name, kind):
        self.name = name
        self.kind = kind  # observe|live
        self.status = "skipped"
        self.detail = ""

    def rec(self, status, detail=""):
        self.status = status
        self.detail = str(detail)[:300]
        return self


def run(live: bool):
    probes = []

    endo, e_err = _imp("forge_endocrine")
    homeo, h_err = _imp("forge_homeostasis_orchestrator")
    anat, a_err = _imp("forge_anatomy_state")
    pulse_mod, p_err = _imp("forge_organ_pulse")
    viable, v_err = _imp("forge_viable_system")

    # ---- OBSERVE-ONLY : l'organisme se percoit-il ? ----
    o1 = Probe("anatomy_state.observable", "observe"); probes.append(o1)
    if anat and hasattr(anat, "get_anatomy_state"):
        try:
            st = anat.get_anatomy_state()
            o1.rec("wired" if st else "open", f"keys={list(st)[:8]}" if isinstance(st, dict) else type(st).__name__)
        except Exception as e:  # noqa: BLE001
            o1.rec("error", e)
    else:
        o1.rec("error", a_err or "no get_anatomy_state")

    o2 = Probe("endocrine.observable", "observe"); probes.append(o2)
    if endo:
        reader = getattr(endo, "all_hormones", None) or getattr(endo, "read_full", None) or getattr(endo, "read", None)
        if reader:
            try:
                kw = _callable_with(reader, {})
                data = reader(**kw) if kw is not None else None
                o2.rec("wired" if data is not None else "error", f"{reader.__name__} -> {type(data).__name__}")
            except Exception as e:  # noqa: BLE001
                o2.rec("error", e)
        else:
            o2.rec("error", "no reader")
    else:
        o2.rec("error", e_err)

    o3 = Probe("homeostasis.threshold.observable", "observe"); probes.append(o3)
    thr_before = None
    if homeo and hasattr(homeo, "FlowRegulator"):
        try:
            fr_kw = _callable_with(homeo.FlowRegulator, {})
            fr = homeo.FlowRegulator(**fr_kw) if fr_kw is not None else None
            if fr is not None and hasattr(fr, "get_dynamic_threshold"):
                gkw = _callable_with(fr.get_dynamic_threshold, {})
                thr_before = fr.get_dynamic_threshold(**gkw) if gkw is not None else None
                o3.rec("wired" if thr_before is not None else "open", f"threshold={thr_before}")
            else:
                o3.rec("error", "FlowRegulator sans get_dynamic_threshold jouable")
        except Exception as e:  # noqa: BLE001
            o3.rec("error", e)
    else:
        o3.rec("error", h_err or "no FlowRegulator")

    o4 = Probe("organ_pulse.observable", "observe"); probes.append(o4)
    if pulse_mod and hasattr(pulse_mod, "pulse"):
        try:
            pkw = _callable_with(pulse_mod.pulse, {})
            pr = pulse_mod.pulse(**pkw) if pkw is not None else None
            o4.rec("wired" if pr else "open", f"-> {type(pr).__name__}")
        except Exception as e:  # noqa: BLE001
            o4.rec("error", e)
    else:
        o4.rec("error", p_err or "no pulse")

    o5 = Probe("viable_system.loop_status.observable", "observe"); probes.append(o5)
    if viable and hasattr(viable, "loop_status"):
        try:
            lkw = _callable_with(viable.loop_status, {})
            ls = viable.loop_status(**lkw) if lkw is not None else None
            o5.rec("wired" if ls is not None else "open", f"-> {type(ls).__name__}")
        except Exception as e:  # noqa: BLE001
            o5.rec("error", e)
    else:
        o5.rec("error", v_err or "no loop_status")

    # ---- LIVE : stimulus -> reaction (mute l'etat, gate) ----
    l1 = Probe("endocrine.self_loop(release->read)", "live"); probes.append(l1)
    l2 = Probe("endocrine->homeostasis.threshold_reacts", "live"); probes.append(l2)
    if not live:
        l1.rec("skipped", "passe --live pour stimuler (mute l'etat vivant)")
        l2.rec("skipped", "passe --live pour stimuler (mute l'etat vivant)")
    elif not endo or not hasattr(endo, "release"):
        l1.rec("error", e_err or "no release"); l2.rec("error", e_err or "no release")
    else:
        known = {"name": "loop_test", "hormone": "loop_test", "kind": "loop_test",
                 "level": 0.5, "value": 0.5, "amount": 0.5, "intensity": 0.5,
                 "ttl": 30, "ttl_s": 30, "ttl_seconds": 30, "decay": 30}
        rel_kw = _callable_with(endo.release, known)
        if rel_kw is None:
            l1.rec("error", f"release signature non satisfiable: {inspect.signature(endo.release)}")
            l2.rec("error", "release non jouable")
        else:
            try:
                endo.release(**rel_kw)
                rf = getattr(endo, "read_full", None) or getattr(endo, "read", None)
                rd = None
                if rf is not None:
                    rkw = _callable_with(rf, {"hormone": "loop_test"})
                    rd = rf(**rkw) if rkw is not None else None
                ok = bool(rd)  # read_full(loop_test) renvoie la lecture si l'hormone relachee est vivante
                l1.rec("wired" if ok else "open",
                       f"read_full(loop_test) -> {json.dumps(rd, default=str)[:120]}" if ok else "release ok mais read_full vide = self-loop ouverte")
            except Exception as e:  # noqa: BLE001
                l1.rec("error", e)
            # L2 neutralise : get_dynamic_threshold depend du CPU (bruit) ET ne lit
            # PAS 'loop_test'. Le vrai couplage hormone->threshold est teste par L3
            # (threat_salience via _endocrine_factor, deterministe, sans bruit CPU).
            l2.rec("skipped", "supersede par L3 (threshold CPU-noisy, loop_test non lu par homeostasie)")

    # ---- L3 : chaine end-to-end amygdale -> endocrine -> homeostasie ----
    l3 = Probe("amygdala->homeostasis(threat_salience module threshold)", "live"); probes.append(l3)
    if not live:
        l3.rec("skipped", "passe --live (publie threat_salience = mute l'etat)")
    else:
        try:
            from nokido_agent.app import forge_amygdala as fa
            if homeo and hasattr(homeo, "FlowRegulator"):
                base = homeo.FlowRegulator()._endocrine_factor()
                v, released = fa.appraise_and_publish(
                    "CRITICAL: exfil attack, injection breach, secret leak", floor=0.3)
                after = homeo.FlowRegulator()._endocrine_factor()
                moved = after > base
                l3.rec("wired" if moved else "open",
                       f"endocrine_factor {base:.3f}->{after:.3f} via {released} (sal={v.salience})")
            else:
                l3.rec("error", h_err or "no FlowRegulator")
        except Exception as e:  # noqa: BLE001
            l3.rec("error", e)

    return probes


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="injecte un stimulus (mute l'etat vivant)")
    ap.add_argument("--json", default=r"C:\tmp\organ_gap\organ_loop_report.json")
    args = ap.parse_args(argv)

    probes = run(args.live)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    rows = [{"probe": p.name, "kind": p.kind, "status": p.status, "detail": p.detail} for p in probes]
    summary = {}
    for p in probes:
        summary[p.status] = summary.get(p.status, 0) + 1

    print(f"=== ORGAN LOOP TEST ({'LIVE' if args.live else 'observe-only'}) {now} ===")
    for r in rows:
        mark = {"wired": "OK ", "open": "OPEN", "error": "ERR ", "skipped": "skip"}.get(r["status"], "?")
        print(f"[{mark}] {r['probe']:<48} {r['detail']}")
    print("summary:", summary)
    closed = summary.get("wired", 0)
    total_obs = sum(1 for p in probes if p.kind == "observe")
    print(f"observabilite organisme: {sum(1 for p in probes if p.kind=='observe' and p.status=='wired')}/{total_obs} organes percus")

    try:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"ts": now, "live": args.live, "summary": summary, "probes": rows}, f, ensure_ascii=False, indent=2)
        print("wrote:", args.json)
    except Exception as e:  # noqa: BLE001
        print("json write skipped:", e)

    # exit 0 si aucune ERR sur les probes observe (instrumentation saine)
    obs_err = any(p.status == "error" for p in probes if p.kind == "observe")
    return 1 if obs_err else 0


if __name__ == "__main__":
    sys.exit(main())
