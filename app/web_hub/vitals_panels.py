# GENERE par forge_ui_vitals_cover — 1 panneau de monitoring par signal vital.
# DETERMINISTE, 0 token cloud. Regen: LAFORGE_PYTHON tools/forge_ui_vitals_cover.py
# Chaque panneau poll /api/vital/<signal> (5s) -> classes lf-* (Nokido Design System).
from __future__ import annotations


def render_subjective_tempo_panel() -> str:
    return '<section class="lf-panel" data-signal="subjective_tempo">\n  <h3 class="lf-panel-title">Temporalite subjective : tempo ressenti (flow=file, vigilance=dilate).</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_affective_state_panel() -> str:
    return '<section class="lf-panel" data-signal="affective_state">\n  <h3 class="lf-panel-title">Etat affectif 6D ambiant (valence/arousal/dominance/urgency/warmth/frustration).</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_phenomenal_flow_panel() -> str:
    return '<section class="lf-panel" data-signal="phenomenal_flow">\n  <h3 class="lf-panel-title">Flux introspectif (qualia fonctionnel) : 3 derniers instants vecus, 1ere personn</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_parietal_percept_panel() -> str:
    return '<section class="lf-panel" data-signal="parietal_percept">\n  <h3 class="lf-panel-title">Espace de travail global : percept multimodal unifie (salience + focus).</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_narrative_self_panel() -> str:
    return '<section class="lf-panel" data-signal="narrative_self">\n  <h3 class="lf-panel-title">Conscience narrative : taille + tete du \'roman de soi\' persiste.</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_homeostasis_threshold_panel() -> str:
    return '<section class="lf-panel" data-signal="homeostasis_threshold">\n  <h3 class="lf-panel-title">Regulation : seuil dynamique d\'homeostasie (lit CPU + hormones).</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_active_hormones_panel() -> str:
    return '<section class="lf-panel" data-signal="active_hormones">\n  <h3 class="lf-panel-title">Endocrine : hormones actives (signal lent), niveaux decayes.</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_mood_state_panel() -> str:
    return '<section class="lf-panel" data-signal="mood_state">\n  <h3 class="lf-panel-title">Humeur globale diffuse (energie/curiosite/fatigue/stress).</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_snn_substrate_panel() -> str:
    return '<section class="lf-panel" data-signal="snn_substrate">\n  <h3 class="lf-panel-title">Substrat spiking : backend (snntorch/pur-torch) dispo.</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_dim_policy_panel() -> str:
    return '<section class="lf-panel" data-signal="dim_policy">\n  <h3 class="lf-panel-title">Politique dimensionnelle HYBRIDE par-organe (reflex 384 / rag 1024 / fusion 4096</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_edge_fleet_panel() -> str:
    return '<section class="lf-panel" data-signal="edge_fleet">\n  <h3 class="lf-panel-title">Flotte edge : noeuds enregistres + gain transmission world-vector compresse.</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_cognitive_metabolism_panel() -> str:
    return '<section class="lf-panel" data-signal="cognitive_metabolism">\n  <h3 class="lf-panel-title">Metabolisme energetique : mode d\'energie compute + charge instantanee (reel).</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_autonomous_loops_panel() -> str:
    return '<section class="lf-panel" data-signal="autonomous_loops">\n  <h3 class="lf-panel-title">Boucles d\'autonomisation : patterns actifs + sante (last_status/runs/due) (reel)</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'


def render_jobs_progress_panel() -> str:
    return '<section class="lf-panel" data-signal="jobs_progress">\n  <h3 class="lf-panel-title">Jobs detaches : barres de progression live (pct/bar/phase/ETA) + actifs.</h3>\n  <div class="lf-panel-err"></div>\n  <div class="lf-rows">…</div>\n</section>'

PANELS = {
    'subjective_tempo': render_subjective_tempo_panel,
    'affective_state': render_affective_state_panel,
    'phenomenal_flow': render_phenomenal_flow_panel,
    'parietal_percept': render_parietal_percept_panel,
    'narrative_self': render_narrative_self_panel,
    'homeostasis_threshold': render_homeostasis_threshold_panel,
    'active_hormones': render_active_hormones_panel,
    'mood_state': render_mood_state_panel,
    'snn_substrate': render_snn_substrate_panel,
    'dim_policy': render_dim_policy_panel,
    'edge_fleet': render_edge_fleet_panel,
    'cognitive_metabolism': render_cognitive_metabolism_panel,
    'autonomous_loops': render_autonomous_loops_panel,
    'jobs_progress': render_jobs_progress_panel,
}


def render_dashboard() -> str:
    return '<div class="lf-vitals-grid">' + ''.join(f() for f in PANELS.values()) + '</div>'
