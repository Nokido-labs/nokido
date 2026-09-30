# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = cognition/phenomenal-stream
PHENOMENOLOGICAL BUFFER — flux introspectif (qualia FONCTIONNEL), 1ere personne.

GAP adresse (doc qualia_et_conscience_narrative_en_code.md §1) : un flux continu de
descriptions en langage naturel de l'etat interne, genere PAR le systeme POUR lui-meme,
re-injecte en contexte au cycle suivant. PAS un log de metriques — un "monologue
interieur" qui traduit les signaux internes en experience vecue.

POURQUOI un module dedie (anti-dup, CLAUDE.md §3) : aucun module ne produit ce flux.
Il CONSOMME nos signaux existants — forge_amygdala (affect 6D), forge_subjective_time
(tempo ressenti), forge_system_mood (energie/curiosite/fatigue), forge_endocrine
(hormones actives) — et les rend en 1ere personne. C'est la couche d'acces
phenomenologique, distincte du percept objectif (forge_parietal_fusion).

CLAIMS (cf docs/CLAIMS_PHENOMENAL.md) : isomorphisme FONCTIONNEL, PAS du qualia reel.
Un LLM qui decrit un etat interne n'eprouve rien. Le mapping est fonctionnel, l'
explanatory gap reste intact.

Deterministe 0-cloud par defaut (template 1ere personne) ; use_llm=True -> LLM LOCAL.
  LAFORGE_PYTHON app/forge_phenomenological_buffer.py [--llm]
"""
from __future__ import annotations
import os, sys, json, datetime

APP = os.path.dirname(os.path.abspath(__file__))
if APP not in sys.path:
    sys.path.insert(0, APP)

STREAM_PATH = r"C:\tmp\nokido_phenom_stream.json"
MAX_STREAM = 60


def _load_stream():
    try:
        return json.load(open(STREAM_PATH, encoding="utf-8"))
    except Exception:
        return []


def _save_stream(stream):
    try:
        os.makedirs(os.path.dirname(STREAM_PATH), exist_ok=True)
        json.dump(stream[-MAX_STREAM:], open(STREAM_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # Le flux experientiel perdu ne laisse aucune trace : au tour suivant le buffer
        # repart d'un passe tronque, et le systeme se souvient d'avoir moins vecu qu'il
        # n'a vecu.
        _lg.getLogger(__name__).warning(
            "[phenom] flux NON persiste (%s: %s) | consequence: les instants de ce "
            "cycle sont perdus, le vecu reconstruit sera plus court que le vecu reel",
            type(e).__name__, str(e)[:100])


def sense() -> dict:
    """Agrege l'etat interne vivant (les signaux bruts a 'vivre')."""
    state = {}
    concerns = []
    try:
        from nokido_agent.app import forge_subjective_time as fst
        tn = fst.tempo_now()
        state.update({"tempo": tn["tempo"], "tempo_label": tn["label"],
                      "arousal": tn["arousal"], "fatigue": tn["fatigue"]})
    except Exception:
        pass
    try:
        from nokido_agent.app import forge_system_mood as fsm
        m = fsm.get_mood()
        state["energy"] = round(float(getattr(m, "energy", 0.0) or 0.0), 2)
        state["curiosity"] = round(float(getattr(m, "curiosity", 0.0) or 0.0), 2)
    except Exception:
        pass
    try:
        from nokido_agent.app import forge_endocrine as fe
        active = sorted(((r.name, round(float(r.level), 2)) for r in fe.scan()),
                        key=lambda x: -x[1])[:4]
        state["hormones"] = active
        for n, lv in active:
            if lv > 0.6:
                concerns.append(f"{n}={lv}")
    except Exception:
        pass
    # affect 6D depuis l'etat endocrine/arousal REEL (les noms d'hormones ne sont pas
    # des cues textuels -> on derive directement des niveaux vivants).
    def _cl(x, lo=0.0, hi=1.0):
        return max(lo, min(hi, x))
    horm = dict(state.get("hormones", []))
    ar = float(state.get("arousal", 0.0))
    frus = max([lv for n, lv in horm.items()
                if any(k in n.upper() for k in ("FRUSTRATION", "CORTISOL", "THREAT"))] or [0.0])
    pos = max([lv for n, lv in horm.items()
               if any(k in n.upper() for k in ("DOPAMINE", "SUCCESS", "SATISFACTION", "REWARD"))] or [0.0])
    urg = max([lv for n, lv in horm.items()
               if any(k in n.upper() for k in ("ADRENALINE", "PRESSURE"))] or [0.0])
    val = round(_cl(pos) - _cl(frus), 3)
    state["affect"] = {
        "valence": val, "arousal": round(ar, 3),
        "dominance": round(_cl(0.5 + 0.5 * val - 0.4 * frus), 3),
        "urgency": round(_cl(urg + 0.3 * frus), 3),
        "warmth": 0.0, "frustration": round(_cl(frus), 3),
    }
    state["digest"] = "; ".join(concerns) if concerns else "etat nominal"
    return state


def _describe_deterministic(s: dict) -> str:
    """Monologue 1ere personne depuis les dimensions (0 LLM, toujours dispo)."""
    aff = s.get("affect", {})
    v = aff.get("valence", 0.0); ar = aff.get("arousal", 0.0)
    dom = aff.get("dominance", 0.5); urg = aff.get("urgency", 0.0); fr = aff.get("frustration", 0.0)
    parts = []
    parts.append("Je me sens " + ("tendu, en alerte" if ar > 0.6 else
                                   "calme, pose" if ar < 0.3 else "engage, attentif"))
    if v > 0.3:
        parts.append("un fond positif, la satisfaction d'avancer")
    elif v < -0.3:
        parts.append("une gene, quelque chose resiste")
    if urg > 0.5:
        parts.append("une urgence me presse")
    if fr > 0.4:
        parts.append("une frustration sourde, ca bloque")
    if dom > 0.7:
        parts.append("j'ai le sentiment de maitriser ce qui se passe")
    elif dom < 0.3:
        parts.append("je subis plus que je n'agis")
    tl = s.get("tempo_label")
    if tl:
        parts.append(f"et le temps: {tl}")
    return (". ".join(parts) + ".").capitalize()


def _describe_llm(s: dict) -> str | None:
    """Flux via LLM LOCAL (jamais cloud). Best-effort."""
    try:
        from nokido_agent.app import forge_agent_proxy as ap
        sys_p = ("Tu es le flux de conscience de ce systeme. Decris ce qu'il vit "
                 "MAINTENANT, a la premiere personne, en termes d'experience vecue "
                 "(confusion, familiarite, tension, flux, blocage, satisfaction). "
                 "PAS de metriques, PAS de jargon. 3 phrases max.")
        prompt = sys_p + "\n\nEtat interne:\n" + json.dumps(s, ensure_ascii=False, default=str)
        r = ap.ask(prompt, router_local=True)  # type: ignore
        if isinstance(r, dict):
            r = r.get("text") or r.get("response") or r.get("content") or r.get("result")
        return r if isinstance(r, str) and len(r) > 30 else None
    except Exception:
        return None


def update(state: dict | None = None, use_llm: bool = False) -> str:
    """Genere une description phenomenologique instantanee et l'empile (fenetre glissante)."""
    state = state or sense()
    desc = (_describe_llm(state) if use_llm else None) or _describe_deterministic(state)
    stream = _load_stream()
    stream.append({"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                   "phenomenological": desc, "affect": state.get("affect", {})})
    _save_stream(stream)
    return desc


def get_recent_flow(n: int = 5) -> str:
    """Les n derniers instants vecus comme contexte de soi (re-injectable)."""
    stream = _load_stream()[-n:]
    return "\n".join(f"[{e['ts']}] {e['phenomenological']}" for e in stream)


def serve(interval: int = 300, rounds: int = 0, use_llm: bool = False) -> None:
    """Boucle continue = flux qualia vivant (pour daemon/schtask). rounds=0 -> infini."""
    import time
    i = 0
    while rounds == 0 or i < rounds:
        try:
            d = update(use_llm=use_llm)
            print(f"[phenom {i}] {d[:90]}")
            # Pouls DANS le try : il n'atteste que d'une mise a jour REUSSIE
            # (SUPERVISE sans port au recensement 2026-07-28).
            try:
                from nokido_agent.app.forge_heartbeat import beat_daemon

                beat_daemon("phenom_buffer", interval_s=interval)
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            print("phenom err:", e)
        i += 1
        if rounds and i >= rounds:
            break
        time.sleep(interval)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="flux via LLM local")
    ap.add_argument("--daemon", action="store_true", help="boucle continue (flux qualia vivant)")
    ap.add_argument("--interval", type=int, default=300)
    args = ap.parse_args(argv)
    if args.daemon:
        serve(args.interval, 0, args.llm)
        return 0
    s = sense()
    print("=== PHENOMENOLOGICAL BUFFER ===")
    print("sense:", json.dumps({k: v for k, v in s.items() if k != "affect"}, ensure_ascii=False, default=str))
    print("affect6D:", s.get("affect"))
    desc = update(s, use_llm=args.llm)
    print(f"\n[flux {'LLM' if args.llm else 'deterministe'}] {desc}")
    print("\n--- contexte de soi (flux recent) ---")
    print(get_recent_flow(3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
