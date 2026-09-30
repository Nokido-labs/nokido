# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = interface/vital-signals
SIGNAUX VITAUX — l'anatomie cognitive de Nokido rendue LISIBLE (doc interface §2/§4 P0).

Le dashboard est le miroir du hub : tu exposes un signal, la moulinette genere son
panneau. Ce module expose l'etat INTERNE vivant (la couche cognitive batie cette
session : affect/agentivite/temps-subjectif/flux/percept + organes existants) en
fonctions 0-arg -> dict, pretes a etre (a) enregistrees comme tools hub, (b) couvertes
par forge_ui_vitals_cover -> panneaux auto-generes.

Chaque fonction est GARDEE : un organe indispo -> {"unavailable": ...}, jamais une
exception qui casserait un panneau. 0 LLM, 0 cloud.
"""
from __future__ import annotations
import os, sys

APP = os.path.dirname(os.path.abspath(__file__))
if APP not in sys.path:
    sys.path.insert(0, APP)


def _guard(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return {"unavailable": f"{type(e).__name__}: {str(e)[:80]}"}


# ── Couche cognitive (cette session) ──────────────────────────────────────────
def subjective_tempo() -> dict:
    """Temporalite subjective : tempo ressenti (flow=file, vigilance=dilate)."""
    return _guard(lambda: __import__("forge_subjective_time").tempo_now())


def affective_state() -> dict:
    """Etat affectif 6D ambiant (valence/arousal/dominance/urgency/warmth/frustration)."""
    def _():
        s = __import__("forge_phenomenological_buffer").sense()
        return {"affect": s.get("affect", {}), "digest": s.get("digest", "")}
    return _guard(_)


def phenomenal_flow() -> dict:
    """Flux introspectif (qualia fonctionnel) : 3 derniers instants vecus, 1ere personne."""
    def _():
        pb = __import__("forge_phenomenological_buffer")
        return {"recent": pb.get_recent_flow(3) or "(vide)"}
    return _guard(_)


def parietal_percept() -> dict:
    """Espace de travail global : percept multimodal unifie (salience + focus)."""
    def _():
        p = __import__("forge_parietal_fusion").fuse()
        return {"salience": p.get("salience"), "priority": p.get("priority"),
                "tag": p.get("tag"), "focus": p.get("focus", [])[:5]}
    return _guard(_)


def narrative_self() -> dict:
    """Conscience narrative : taille + tete du 'roman de soi' persiste."""
    def _():
        n = __import__("forge_narrator")
        s = n._load_self()
        return {"chars": len(s), "head": (s[:280] or "(non consolide)")}
    return _guard(_)


# ── Organes physiologiques existants ──────────────────────────────────────────
def homeostasis_threshold() -> dict:
    """Regulation : seuil dynamique d'homeostasie (lit CPU + hormones)."""
    def _():
        h = __import__("forge_homeostasis_orchestrator")
        fr = h.FlowRegulator()
        return {"threshold": fr.get_dynamic_threshold(), "endocrine_factor": fr._endocrine_factor()}
    return _guard(_)


def active_hormones() -> dict:
    """Endocrine : hormones actives (signal lent), niveaux decayes."""
    def _():
        fe = __import__("forge_endocrine")
        return {"hormones": sorted(((r.name, round(float(r.level), 2)) for r in fe.scan()),
                                   key=lambda x: -x[1])[:8]}
    return _guard(_)


def mood_state() -> dict:
    """Humeur globale diffuse (energie/curiosite/fatigue/stress)."""
    def _():
        return {"summary": str(__import__("forge_system_mood").mood_summary())}
    return _guard(_)


def snn_substrate() -> dict:
    """Substrat spiking : backend (snntorch/pur-torch) dispo."""
    return _guard(lambda: __import__("forge_snn_core").available())


# ── Nouveaux organes infra (dims hybrides / flotte edge) ──────────────────────
def dim_policy_state() -> dict:
    """Politique dimensionnelle HYBRIDE par-organe (reflex 384 / rag 1024 / fusion 4096)."""
    return _guard(lambda: __import__("forge_dim_policy").policy())


def edge_fleet_state() -> dict:
    """Flotte edge : noeuds enregistres + gain transmission world-vector compresse."""
    def _():
        ef = __import__("forge_edge_fleet")
        edges = ef.list_edges()
        return {"edges": len(edges), "names": [e.get("name") for e in edges][:6],
                "wv_transport": ef.world_vector_transport_stats(4096)}
    return _guard(_)


# -- Boucles autonomes + metabolisme energetique (rubriques reelles) -----------
def cognitive_metabolism() -> dict:
    """Metabolisme energetique : mode d'energie compute + charge instantanee (reel)."""
    def _():
        m = __import__("forge_metabolism")
        st = m.get_compute_energy_state()
        if isinstance(st, (list, tuple)) and len(st) >= 2:
            mode, load = st[0], st[1]
        else:
            mode, load = str(st), None
        return {"energy_mode": mode,
                "load": round(float(load), 3) if load is not None else None}
    return _guard(_)


def autonomous_loops() -> dict:
    """Boucles d'autonomisation : patterns actifs + sante (last_status/runs/due) (reel)."""
    def _():
        st = __import__("forge_autonomous_loops").status()
        pats = st.get("patterns", []) if isinstance(st, dict) else []
        active = [p for p in pats if p.get("enabled")]
        return {"active": len(active), "total": len(pats),
                "loops": [{"name": p.get("name"), "status": p.get("last_status"),
                           "runs": p.get("runs_total"), "ok": p.get("runs_success"),
                           "age_min": p.get("age_minutes"), "due_s": p.get("due_in_seconds")}
                          for p in pats][:8]}
    return _guard(_)


def jobs_progress() -> dict:
    """Jobs detaches : barres de progression live (pct/bar/phase/ETA) + actifs."""
    def _():
        import sys as _s
        from pathlib import Path as _P
        _tools = str(_P(__file__).resolve().parent.parent / "tools")
        if _tools not in _s.path:
            _s.path.insert(0, _tools)
        jp = __import__("forge_job_progress")
        act = jp.all_active(900) or []
        return {"active": len(act), "jobs": list(act)[:8]}
    return _guard(_)


# Registre des signaux (nom -> callable 0-arg). Source pour forge_ui_vitals_cover
# ET pour un futur enregistrement comme tools hub (doc interface P0).
VITAL_SIGNALS = {
    "subjective_tempo": subjective_tempo,
    "affective_state": affective_state,
    "phenomenal_flow": phenomenal_flow,
    "parietal_percept": parietal_percept,
    "narrative_self": narrative_self,
    "homeostasis_threshold": homeostasis_threshold,
    "active_hormones": active_hormones,
    "mood_state": mood_state,
    "snn_substrate": snn_substrate,
    "dim_policy": dim_policy_state,
    "edge_fleet": edge_fleet_state,
    "cognitive_metabolism": cognitive_metabolism,
    "autonomous_loops": autonomous_loops,
    "jobs_progress": jobs_progress,
}


# Cache TTL du snapshot complet. MESURE 2026-08-26 : `all_vitals()` coute entre 5 et
# 50 s selon la charge de la machine (variable, donc jamais un chiffre a citer seul) --
# `parietal_percept` en represente l'essentiel, via `forge_organ_pulse` et
# `get_anatomy_state`. Or le flux SSE `/api/vitals/sse` le redemande toutes les 5 s,
# ET une fois PAR CLIENT : sans cache, N pages ouvertes = N recalculs complets.
# Prendre le pouls ne doit pas fatiguer le patient.
_CACHE_TTL_S = 5.0
_cache: dict = {"ts": 0.0, "valeur": None}


def all_vitals(frais: bool = False) -> dict:
    """Snapshot de TOUS les signaux vitaux (1 appel = l'anatomie cognitive complete).

    Sert un snapshot de moins de `_CACHE_TTL_S` secondes s'il y en a un. `frais=True`
    force le recalcul. Le TTL est court exprès : il absorbe les demandes simultanees
    sans jamais servir un etat qu'on pourrait croire courant alors qu'il ne l'est plus.
    Le champ `age_s` DIT l'age du snapshot rendu -- un cache muet ferait passer une
    mesure d'il y a cinq secondes pour une mesure de maintenant."""
    import time as _t
    maintenant = _t.monotonic()
    if not frais and _cache["valeur"] is not None:
        age = maintenant - _cache["ts"]
        if age < _CACHE_TTL_S:
            return dict(_cache["valeur"], age_s=round(age, 2))
    valeur = {name: fn() for name, fn in VITAL_SIGNALS.items()}
    _cache["ts"], _cache["valeur"] = _t.monotonic(), valeur
    return dict(valeur, age_s=0.0)


if __name__ == "__main__":
    import json
    print(json.dumps(all_vitals(), ensure_ascii=False, indent=2, default=str))
