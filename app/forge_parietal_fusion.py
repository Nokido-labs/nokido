# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = cortex/parietal-fusion
CORTEX PARIETAL — fusion multimodale -> ESPACE DE TRAVAIL GLOBAL (percept unifie publie).

POURQUOI un module dedie (anti-dup, CLAUDE.md §3) :
  Les flux existent mais DISJOINTS :
    - forge_anatomy_state.get_anatomy_state() = snapshot 9 flux (organs/flows/hormones/
      daemons/rag/embed_pct/recent_lessons) MAIS lecture ponctuelle, non diffusee.
    - forge_organ_pulse.pulse() = watchdog SANTE (anomalies), pas un percept.
    - forge_system_mood.broadcast_mood() = humeur SEULE.
    - forge_nervous_map = carte STATIQUE des composants.
  Aucun ne BIND les modalites en UN percept unifie, classe par salience, et le
  DIFFUSE en continu au tableau noir = l'espace de travail global (conscience,
  principe #6 Emergence de la vision). C'est le cortex parietal d'association.

INTEGRATION : la salience du percept est calculee via forge_amygdala (gap #2) sur
le digest des "concerns" courants -> lie amygdale+anatomie+endocrine. Diffusion via
forge_swarm_blackboard.apply_fact (zone global_workspace). 0 LLM, 0 cloud.

  LAFORGE_PYTHON app/forge_parietal_fusion.py            # fuse + affiche (sans publier)
  LAFORGE_PYTHON app/forge_parietal_fusion.py --publish  # + diffuse au blackboard
  LAFORGE_PYTHON app/forge_parietal_fusion.py --serve 30 20  # boucle 20x toutes les 30s
"""
from __future__ import annotations
import os, sys, json, math, time, argparse, datetime

APP = os.path.dirname(os.path.abspath(__file__))
if APP not in sys.path:
    sys.path.insert(0, APP)


def _sat(x, k=2.0):
    return 1.0 - math.exp(-max(0.0, x) / k)


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def _active_hormones() -> dict:
    """Niveaux ACTIFS courants (scan = endocrine_signals released + decay applique),
    PAS le catalogue de types. {name: level}."""
    try:
        from nokido_agent.app import forge_endocrine as fe
        return {r.name: round(float(r.level), 3) for r in fe.scan()}
    except Exception:
        return {}


def _concerns(state, hormones, pulse) -> list:
    """Extrait les signaux saillants des flux (defensif sur la structure)."""
    c = []
    organs = state.get("organs") if isinstance(state, dict) else None
    if isinstance(organs, dict):
        for k, v in organs.items():
            s = v.get("status") if isinstance(v, dict) else v
            if isinstance(s, str) and s.lower() in ("down", "degraded", "critical", "error", "stale", "dead"):
                c.append(f"organ {k}={s}")
    if isinstance(hormones, dict):
        for k, v in hormones.items():
            lvl = v.get("level") if isinstance(v, dict) else v
            if isinstance(lvl, (int, float)) and lvl > 0.6:
                c.append(f"hormone {k}={lvl:.2f}")
    if isinstance(pulse, dict):
        al = pulse.get("alerts")
        if isinstance(al, list):
            c += [f"alert {a}" for a in al[:6]]
        else:
            for k, v in pulse.items():
                if isinstance(v, dict) and str(v.get("status", "")).lower() in ("warn", "alert", "critical", "down"):
                    c.append(f"pulse {k}={v.get('status')}")
    return c


_PERCEPT_TTL_S = 3.0
_PERCEPT_VERROU = None      # cree paresseusement : pas de cout a l'import
_PERCEPT_CACHE = {"ts": 0.0, "val": None}


def fuse() -> dict:
    """Percept unifie, avec un TRAIT UNIQUE en vol et un age assume.

    MESURE du 2026-09-17, sur le chemin `/api/vital/parietal_percept` :

        1 appel   ->  2,2 s   (/health max 234 ms)
        4 appels  ->  5,9 s   (/health max 796 ms)
        20 appels -> 44,5 s   (/health max 5359 ms)

    44,5 vaut 20 x 2,2 : le travail ne se parallelise pas, il SERIALISE. Et la
    route appelante est declaree `def`, donc chaque requete immobilise un
    ouvrier du threadpool anyio pendant toute la duree -- `/health`, synchrone
    lui aussi, se met en file derriere et son delai monte avec la charge. C'est
    le mecanisme qui faisait lire une SATURATION comme une PANNE.

    Or ceci est un PERCEPT : un instantane de l'etat ambiant. Le recalculer
    vingt fois par seconde ne produit aucune connaissance supplementaire, et
    `fuse` agrege cinq organes dont un que les regles du depot signalent deja
    comme recomptant sur la grosse base.

    D'ou un cache a TRAIT UNIQUE : le premier appelant calcule, les autres
    attendent ce meme calcul et recoivent sa valeur. Vingt appels coutent donc
    UN calcul, pas vingt.

    L'age est RENDU (`cache_age_s`), il n'est pas masque : un percept servi
    depuis le cache est une observation datee, pas une mesure de l'instant, et
    un signal qui ne dit pas son age se fait prendre pour une preuve de vie.
    """
    import threading
    import time as _t

    global _PERCEPT_VERROU
    if _PERCEPT_VERROU is None:
        _PERCEPT_VERROU = threading.Lock()

    def _servir(val, age):
        copie = dict(val)
        copie["cache_age_s"] = round(age, 2)
        return copie

    maintenant = _t.monotonic()
    val, ts = _PERCEPT_CACHE["val"], _PERCEPT_CACHE["ts"]
    if val is not None and (maintenant - ts) < _PERCEPT_TTL_S:
        return _servir(val, maintenant - ts)

    with _PERCEPT_VERROU:
        # re-lecture SOUS le verrou : pendant l'attente, un autre appelant a
        # peut-etre deja fait le calcul. Sans cette seconde lecture, N appelants
        # bloques recalculeraient N fois a la file -- le pompage qu'on evite.
        maintenant = _t.monotonic()
        val, ts = _PERCEPT_CACHE["val"], _PERCEPT_CACHE["ts"]
        if val is not None and (maintenant - ts) < _PERCEPT_TTL_S:
            return _servir(val, maintenant - ts)
        frais = _fuse_calcule()
        _PERCEPT_CACHE["val"] = frais
        _PERCEPT_CACHE["ts"] = _t.monotonic()
        return _servir(frais, 0.0)


def _fuse_calcule() -> dict:
    """Lie les flux en UN percept unifie classe par salience."""
    from nokido_agent.app import forge_anatomy_state as fas
    state, e_state = _safe(fas.get_anatomy_state)
    state = state or {}

    hormones = _active_hormones()
    mood, _ = _safe(lambda: __import__("forge_system_mood").mood_summary())
    pulse = None
    try:
        sys.path.insert(0, os.path.dirname(APP))
        from nokido_agent.tools import forge_organ_pulse as fop
        pulse, _ = _safe(fop.pulse)
    except Exception:
        pulse = None

    concerns = _concerns(state, hormones, pulse)
    digest = "; ".join(concerns) if concerns else "systeme nominal"

    # salience numerique (severite) + overlay affectif amygdale (gap #2)
    sev = 0.5 * len(concerns)
    if isinstance(hormones, dict):
        sev += sum(1.0 for v in hormones.values() if isinstance(v, (int, float)) and v > 0.6)
    salience = round(_sat(sev), 3)
    valence, tag = 0.0, "neutral"
    try:
        from nokido_agent.app import forge_amygdala as fa
        v = fa.appraise(digest)
        valence, tag = v.valence, v.tag
        salience = round(max(salience, v.salience), 3)
    except Exception:
        pass

    priority = 3 if salience >= 0.75 else 2 if salience >= 0.5 else 1 if salience >= 0.25 else 0
    return {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "salience": salience, "priority": priority, "valence": valence, "tag": tag,
        "focus": concerns[:8],
        "streams": {
            "organs": list(state.get("organs", {}))[:12] if isinstance(state.get("organs"), dict) else state.get("organs"),
            "hormones": hormones if isinstance(hormones, (dict, list)) else str(hormones),
            "mood": mood,
            "rag": state.get("rag"),
            "embed_pct": state.get("embed_pct"),
            "daemons": (lambda d: f"{d.get('alive')}/{d.get('total')} alive" if isinstance(d, dict) and "alive" in d else d)(state.get("daemons")),
            "recent_lessons": (state.get("recent_lessons") or [])[:3],
        },
        "errors": {"anatomy": e_state} if e_state else {},
    }


def publish(percept: dict) -> str:
    """Diffuse le percept au tableau noir (zone global_workspace = conscience partagee)."""
    try:
        import asyncio
        from nokido_agent.app import forge_swarm_blackboard as bb
        r = bb.apply_fact(zone="global_workspace",
                          fact=json.dumps(percept, ensure_ascii=False, default=str),
                          category="percept", trust=0.7, key="parietal_percept",
                          source="parietal_fusion", ring=1)
        if asyncio.iscoroutine(r):  # apply_fact est async -> driver la coroutine
            asyncio.run(r)
        return "published"
    except Exception as e:  # noqa: BLE001
        return f"ERR:{type(e).__name__}:{e}"


def serve(interval: int = 30, rounds: int = 0) -> None:
    """Boucle de diffusion continue (rounds=0 -> infini). Pour schtask/run_job."""
    i = 0
    while rounds == 0 or i < rounds:
        p = fuse()
        # Pouls APRES une fusion reussie (SUPERVISE sans port, recensement 2026-07-28).
        try:
            from nokido_agent.app.forge_heartbeat import beat_daemon

            beat_daemon("parietal_fusion", interval_s=interval)
        except Exception:  # noqa: BLE001
            pass
        print(f"[{p['ts']}] sal={p['salience']} P{p['priority']} {p['tag']} focus={len(p['focus'])} -> {publish(p)}")
        i += 1
        if rounds and i >= rounds:
            break
        time.sleep(interval)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--serve", nargs="*", type=int, help="[interval rounds]")
    args = ap.parse_args(argv)

    if args.serve is not None:
        interval = args.serve[0] if len(args.serve) >= 1 else 30
        rounds = args.serve[1] if len(args.serve) >= 2 else 0
        serve(interval, rounds)
        return 0

    p = fuse()
    print("=== PARIETAL FUSION (global workspace percept) ===")
    print(f"salience={p['salience']} priority=P{p['priority']} valence={p['valence']} tag={p['tag']}")
    print(f"focus ({len(p['focus'])}): {p['focus']}")
    print(f"streams: organs={p['streams']['organs']}")
    print(f"         hormones={p['streams']['hormones']}")
    print(f"         mood={p['streams']['mood']} rag={p['streams']['rag']} embed_pct={p['streams']['embed_pct']}")
    if p["errors"]:
        print("errors:", p["errors"])
    if args.publish:
        print("publish ->", publish(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
