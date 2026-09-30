#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_organ_agents.py — CENSUS ORGANE×AGENT de l'organisme + câblages essentiels.

Directive user : pousser l'analyse OrganAgent PAR ANALOGIE avec les familles d'organes
(CLAUDE.md §10) — repérer ce qui est essentiel à CÂBLER. Constat de la recon : les organes
EXISTENT (endocrinien forge_endocrine/forge_hormones/forge_motivation, immunitaire, etc.) ;
le gap n'est PAS l'absence d'organes mais l'absence de (a) leur AGENTIFICATION sous contrat
et surtout (b) les BOUCLES DE RÉGULATION inter-organes (feedbacks homéostatiques). Comme en
biologie : l'essentiel n'est pas un organe de plus, c'est le câblage endocrinien/nerveux qui
fait COOPÉRER les organes.

Ce module = la CARTE vivante : chaque famille d'organe -> {organe(s), rôle d'agent, TIER
(réflexe/acteur/agent, modèle validé), statut, owner, CÂBLAGE manquant}. + gaps() = les
boucles régulatrices essentielles à câbler (priorisées). Jumelle de forge_keeper_base /
forge_flow_control : on FÉDÈRE et on ANALYSE, on ne réinvente pas.

ANTI-DUP : agrège l'existant (keepers, flow_control, endocrine, motivation, autonomous_loops,
remediation, evolutionary_engine, firewall, ingest...). Recon rag_fts + grep faite.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# Tiers (modèle 3-tiers validé par débat swarm, cf. architecture_rules:organ_tiers_validated).
REFLEX = "réflexe"   # module synchrone hot-path <10ms — NE PAS agentifier
ACTOR = "acteur"     # event-driven déterministe 0-LLM (daemon/keeper)
AGENT = "agent"      # état+proactif+autonome (contrat OrganAgent)

# Statut d'agentification.
LIVE = "live"        # agentifié + câblé
DORMANT = "dormant"  # organe existe mais pas agentifié / boucle non câblée
GAP = "gap"          # câblage régulateur essentiel MANQUANT

# CARTE : famille -> (organes/owners, rôle, tier, statut, câblage manquant)
ORGAN_MAP = [
    ("SNC / cerveau", ["forge_orchestration_gate", "nokido_hub", "forge_cognitive_router"],
     "aiguilleur (tour de contrôle)", AGENT, LIVE, "—"),
    ("Mémoire / hippocampe", ["forge_self_correction", "RAG", "forge_memory_keeper"],
     "memory_keeper", AGENT, LIVE, "—"),
    ("Immunitaire", ["forge_videur", "forge_integrity", "forge_semantic_firewall", "forge_hub_gate"],
     "videur + convoyeur (accès/auth)", REFLEX, LIVE,
     "SENTINELLE proactive : agentifier forge_inspector/forge_idle_watchdog en macrophage "
     "qui CHASSE les anomalies (pas seulement gate-on-request)"),
    ("Endocrinien / neuromodulation", ["forge_endocrine", "forge_hormones", "forge_motivation"],
     "régulateur hormonal (dopamine/cortisol)", ACTOR, LIVE,
     "KEYSTONE endocrine->GATE : BOUCLE CLOSE — afferent (record_route_outcome->reward/punish) "
     "+ efferent (CORTISOL_FRUSTRATION relâche les seuils learn_adjust=escalade sous stress ; "
     "CORTISOL_QUOTA_CLOUD bloque l'escalade cloud)"),
    ("SN végétatif / autonome", ["forge_autonomous_loops", "forge_resource_manager", "keepers"],
     "daemons homéostatiques", ACTOR, LIVE, "—"),
    ("Digestif / ingestion", ["forge_ingest_self", "forge_rag_warmup", "forge_post_commit"],
     "estomac (digestion continue)", ACTOR, LIVE, "—"),
    ("Locomoteur / orchestration", ["forge_silo_engine", "forge_orchestrator", "forge_spawn_swarm"],
     "muscles (exécution déportée)", AGENT, LIVE, "—"),
    ("Sens (multimodal)", ["forge_ui_oracle", "forge_video_observe", "forge_android", "forge_crawl"],
     "agents sensoriels", AGENT, DORMANT,
     "FUSION sensorielle : unifier vision/écran/android/web sous UN contrat OrganAgent "
     "multimodal (aujourd'hui épars)"),
    ("Reproductif / régénération", ["evolutionary_engine", "forge_tool_forger", "forge_remediation"],
     "germe (auto-évolution)", AGENT, GAP,
     "BOUCLE régénération : evolution CONSOMME lessons/gaps (memory_keeper) -> propose "
     "modules/fixes -> quality_gate -> intègre. Aujourd'hui outils épars, pas de boucle close"),
    ("Circulatoire / transport", ["forge_message_frame", "forge_events", "nervous_system.ts"],
     "chef_de_gare + facteur (flux)", ACTOR, LIVE, "—"),
    ("Excréteur / détox", ["forge_secret_guard", "forge_silo_fragmenter(NoiseGuardian)"],
     "foie/rein (DLP, détox secrets)", REFLEX, LIVE, "—"),
    ("Observabilité / proprioception", ["forge_trace_viz", "forge_meta_health", "forge_loop_sentinel"],
     "proprioception (spans/santé)", ACTOR, LIVE, "—"),
]

# Câblages régulateurs ESSENTIELS manquants (priorité décroissante).
ESSENTIAL_WIRINGS = [
    ("DONE", "endocrine_to_gate",
     "BOUCLE CLOSE : afferent (record_route_outcome->reward/punish) + efferent (cortisol "
     "module learn_adjust : frustration->escalade, quota_cloud->bloque cloud). Keystone "
     "homéostase+apprentissage refermé."),
    ("DONE", "cortisol_to_throttle",
     "CÂBLÉ le 2026-07-29 : should_throttle lit CORTISOL_FRUSTRATION et CORTISOL_QUOTA_CLOUD "
     "et DURCIT les seuils ressources de CORTISOL_TIGHTEN_PTS. Le cortisol est un MODULATEUR "
     "de sensibilité, PAS un veto : rendu en veto il avait refusé 471 spawns à RAM 60 %/CPU 6 %, "
     "puis 382 à RAM 37,8 % (hormone survivant au restart) — le frein empêchait la guérison "
     "au lieu de protéger. Ne pas 're-câbler' en veto : c'est la régression déjà mesurée."),
    ("P1", "immune_sentinel",
     "agentifier forge_inspector/forge_idle_watchdog en SENTINELLE proactive sous contrat "
     "OrganAgent (sweep anomalies + alerte facteur), tier ACTEUR."),
    ("DONE", "regeneration_afferent",
     "COMMISSURE cablee le 2026-09-07 : memory_keeper.lessons() rend des RECORDS "
     "(etat LU/ILLISIBLE + items) et evolutionary_engine les consulte avant de muter, en "
     "plus de ses propres fiches. Mesure avant : 1,1 Mo de lecons exposees en PROSE "
     "seulement, ZERO reference a memory_keeper dans le germe -- deux memoires, aucune "
     "commissure. Le registre le declarait en GAP P1 ; la mesure l'a confirme, pas "
     "decouvert."),
    ("DONE", "regeneration_efferent",
     "EFFERENT cable le 2026-09-07 : le germe emet reward/punish (forge_motivation, MEME "
     "organe que endocrine_to_gate) par cible au niveau GENERATION, avec la duree "
     "mesuree la -- il ne chronometre pas par mutation, et time_s=0 ferait une dopamine "
     "maximale inventee. Les deux hormones ensemble : du cortisol sans dopamine derive "
     "vers dead_end. La decision de punish (action_recommended/dead_end) est conservee "
     "dans results. Et le post-mortem ecrit desormais dans le canal des LECONS "
     "(memory_keeper.remember), celui que lessons() lit -- avant il partait en @disco, "
     "un canal de DECOUVERTE que le germe ne relit jamais."),
    ("P1", "regeneration_loop",
     "boucle close, AFFERENT fait (regeneration_afferent) et EFFERENT endocrinien fait "
     "(regeneration_efferent) ; reste l'EFFERENT d'integration : forge_tool_forger "
     "-> forge_quality_gate -> intégration. Le système se répare/évolue depuis ses propres traces."),
    ("P2", "sensory_fusion",
     "unifier les sens multimodaux (ui_oracle/video/android/crawl) sous un contrat OrganAgent."),
]

# SONDES — ce qui atteste FACTUELLEMENT qu'un câblage est en place.
#
# POURQUOI (mesuré le 2026-08-21) : ce registre a déclaré `cortisol_to_throttle`
# « à câbler » pendant trois semaines APRÈS son câblage du 29/07, à QUATRE endroits.
# Une analyse externe l'a lu, l'a cru, et a recommandé de le passer en P0 — c'est-à-dire
# de refaire un travail fait, dans la forme (veto) précisément mesurée comme nuisible.
# Le module annonçait pourtant lui-même le risque dans regulation_gaps() :
# « une carte déclarative vieillit sans prévenir ». Elle a vieilli.
#
# Une sonde = (fichier, motif). `tests/nr/test_organ_registre_nr.py` s'en sert dans les
# DEUX sens : un câblage DONE dont la sonde ne mord plus est une RÉGRESSION ; un câblage
# déclaré à faire dont la sonde mord est un registre PÉRIMÉ. Sans sonde, une entrée n'est
# qu'une intention — c'est permis, mais alors elle ne prouve rien.
# ── V3 (2026-09-12) : LE CYCLE DE VIE, EN PHASES ─────────────────────────────
# Une sonde dit QU'UN cablage existe ; elle ne dit pas QUAND il intervient. Deux
# cablages du meme organe, l'un avant l'action et l'autre apres, etaient
# indiscernables dans ce registre — et la carte organe->module, elle, ne dit que
# le OU. D'ou une phase par sonde, et la question qu'on ne pouvait pas poser :
# quelles etapes du cycle ne sont surveillees par RIEN ?
#
# Vocabulaire FERME. Ouvert, deux cablages de la meme etape porteraient deux mots
# differents et l'agregat ne voudrait plus rien dire.
#
# ⚠️ Ce sont des DECLARATIONS, au meme titre que `__FORGE_COLOR__` : elles disent
# l'intention de l'auteur, pas une position mesuree dans le flot d'execution. Une
# phase sans cablage n'est donc PAS une etape saine, et une sonde sans phase
# n'est pas une sonde hors cycle — les deux se DISENT.
PHASES: tuple[str, ...] = ("PRE_ACT", "ACT", "POST_ACT",
                           "PRE_OBSERVE", "OBSERVE", "POST_OBSERVE", "UPDATE")

WIRING_PROBES: dict[str, tuple[str, str, str]] = {
    # decide AVANT de router : le gate s'interpose entre l'intention et l'acte
    "endocrine_to_gate": ("PRE_ACT", "app/forge_orchestration_gate.py",
                          r"record_route_outcome|forge_endocrine"),
    # freine AVANT l'allocation : un throttle qui agirait apres ne freine rien
    "cortisol_to_throttle": ("PRE_ACT", "app/forge_resource_manager.py",
                             r"CORTISOL_\w+"),
    # voie AFFERENTE = lecture d'etat, par definition du mot
    "regeneration_afferent": ("OBSERVE", "tools/evolutionary_engine.py",
                              r"forge_memory_keeper"),
    # ⚠️ 2026-09-10 — cette sonde citait `from forge_motivation import punish, reward`,
    # le chemin d'AVANT la migration vers le namespace `nokido_agent`. Le câblage
    # n'a pas bougé (evolutionary_engine.py émet toujours reward/punish) ; c'est la
    # SONDE qui a vieilli, et elle rendait `absent` — donc un câblage DONE se lisait
    # comme une RÉGRESSION dans `test_organ_registre_nr`. Une sonde textuelle porte
    # le chemin d'import du jour : elle doit être migrée AVEC lui.
    # reward/punish emis APRES un resultat : c'est l'apprentissage, donc UPDATE
    "regeneration_efferent": ("UPDATE", "tools/evolutionary_engine.py",
                              r"from nokido_agent\.app\.forge_motivation import punish, reward"),
}


def phases(registre: dict | None = None) -> dict:
    """Le registre, vu par le TEMPS et non par l'organe.

    Rend, pour chaque phase du cycle, les cablages qui s'y rattachent — y
    compris les phases VIDES, qui restent dans la table. Les taire ferait passer
    une etape que rien ne surveille pour une etape qui n'a rien a faire.

    Trois etats pour une sonde : phase valide / phase INVALIDE (hors vocabulaire)
    / SANS phase declaree.
    """
    reg = WIRING_PROBES if registre is None else registre
    par_phase: dict[str, list] = {p: [] for p in PHASES}
    invalides, sans_phase = [], []
    for cle, spec in reg.items():
        if not isinstance(spec, (tuple, list)) or len(spec) < 3:
            sans_phase.append(cle)
            continue
        ph = spec[0]
        if ph not in PHASES:
            invalides.append(cle)
            continue
        par_phase[ph].append(cle)
    return {
        "sondes_totales": len(reg),
        "par_phase": par_phase,
        "phases_SANS_cablage_observe": [p for p in PHASES if not par_phase[p]],
        "sondes_a_phase_INVALIDE": invalides,
        "sondes_SANS_phase": sans_phase,
        "rappel": "une phase sans cablage n'est pas une phase saine : c'est une "
                  "etape que rien ne surveille, et le registre ne le savait pas.",
    }


def probe(name: str) -> dict:
    """Constate si le câblage `name` est présent dans le code. Trois états, jamais deux :
    présent / absent / pas de sonde — « pas mesurable » n'est pas « pas là »."""
    import re as _re

    spec = WIRING_PROBES.get(name)
    if spec is None:
        return {"name": name, "etat": "sans_sonde", "hits": 0}
    # V3 : la sonde porte desormais sa PHASE en tete. On lit par la FIN pour que
    # les deux formes cohabitent — un desempaquetage positionnel aurait casse
    # `probe` sur toutes les sondes le jour de la migration.
    rel, motif = spec[-2], spec[-1]
    p = ROOT / rel
    if not p.exists():
        return {"name": name, "etat": "fichier_absent", "hits": 0, "file": rel}
    hits = len(_re.findall(motif, p.read_text(encoding="utf-8", errors="replace")))
    return {"name": name, "etat": "present" if hits else "absent", "hits": hits, "file": rel}


# POINTS CRITIQUES (groundés sur incidents réels) -> garde-agent à placer. Beaucoup de
# signaux sont DÉJÀ ÉMIS (critical_events, cortisol crash) mais PERSONNE NE LES CONSOMME =
# le vrai trou. (point, évidence, garde, tier, statut, owner à fédérer)
CRITICAL_POINTS = [
    ("DONE", "signaux critiques non consommés en continu — LIVRÉ",
     "SENTINELLE ANTI-EMBOLIE (forge_organ_pulse) : 8 checks cross-process périodiques "
     "(hub wedge/event-loop/signaux non consommés/RAM/disk/jobs coincés/embed/cortisol) "
     "-> cortisol+notify facteur+log. Boucle 10min INDÉPENDANTE du hub (détecte le wedge)",
     AGENT, LIVE, "forge_organ_pulse + forge_critical_events + forge_endocrine"),
    ("P0", "wedge/crash hub ×3 (juin 3-4) : spawn SYNC dans handler async bloque event-loop",
     "DISJONCTEUR SPAWN : interdit tout appel bloquant/spawn lourd hors to_thread/run_job "
     "dans une coroutine du hub (garde le hot-path)",
     REFLEX, DORMANT, "forge_mcp_registry (_run_sandboxed_*) + forge_loop_sentinel"),
    ("DONE", "signaux critiques émis sans réacteur — LIVRÉ (1120 drainés)",
     "COAGULATION (forge_coagulation) : CONSOMME forge_critical_events -> triage escalade/"
     "heal-borné(forge_remediation, armed gate)/ack + mark_processed + dopamine. Jamais de "
     "restart solo (escalade). La sentinelle VOIT, la coagulation SOIGNE",
     ACTOR, LIVE, "forge_coagulation + forge_critical_events + forge_remediation"),
    ("DONE", "RAM/OOM (Docker+embed 81% -> crash hub historique) — LIVRÉ",
     "HOMÉOSTAT RESSOURCES : should_throttle freine sur RAM/CPU/GPU/disque/TDR, et le "
     "cortisol DURCIT ces seuils de CORTISOL_TIGHTEN_PTS (efferent cortisol_to_throttle, "
     "2026-07-29). Modulateur, jamais veto — cf. ESSENTIAL_WIRINGS",
     ACTOR, LIVE, "forge_resource_manager.should_throttle + forge_endocrine"),
    ("P2", "budget cloud : CORTISOL_QUOTA_CLOUD émis, gate s'en sert, pas de gouverneur source",
     "ÉCONOME : gouverne le coût cloud (cost_usd_today/budget) -> émet le cortisol budget "
     "+ bascule local sous stress (source de l'efferent déjà câblé côté gate)",
     ACTOR, DORMANT, "forge_endocrine(CORTISOL_QUOTA_CLOUD) + forge_resolver"),
    ("P2", "egress : firewall post_flight réflexe, pas d'auditeur proactif",
     "GARDE-EGRESS : audit proactif des sorties (SSRF/canary/exfil) + drift trafic-vs-canon",
     REFLEX, LIVE, "forge_semantic_firewall + forge_knowledge_concierge(DRIFT)"),
]


def critical_points() -> list:
    """Les POINTS CRITIQUES (incidents réels) -> garde-agent à placer, priorisés.
    Le trou récurrent : des signaux émis (critical_events, cortisol) que PERSONNE ne consomme."""
    return [{"prio": p, "evidence": ev, "guard": g, "tier": t, "status": s, "federate": own}
            for p, ev, g, t, s, own in CRITICAL_POINTS]


def census() -> dict:
    """Carte complète organe->agent (tier/statut/owner/câblage). Le 'pousse l'analyse'."""
    rows = []
    for fam, organs, role, tier, status, wiring in ORGAN_MAP:
        rows.append({"family": fam, "organs": organs, "role": role, "tier": tier,
                     "status": status, "missing_wiring": wiring})
    by_status = {}
    for r in rows:
        by_status.setdefault(r["status"], 0)
        by_status[r["status"]] += 1
    return {"organism": "Nokido", "families": rows, "by_status": by_status,
            "essential_wirings": [{"prio": p, "name": n, "what": w} for p, n, w in ESSENTIAL_WIRINGS],
            "critical_points": critical_points()}


def gaps() -> list:
    """Les câblages régulateurs essentiels MANQUANTS (organe dormant/gap)."""
    return [{"family": fam, "role": role, "missing_wiring": w}
            for fam, organs, role, tier, status, w in ORGAN_MAP if status in (DORMANT, GAP)]


def regulation_gaps() -> dict:
    """Défauts d'innervation MESURÉS par organe — le pendant factuel de `gaps()`.

    `gaps()` rend ce qu'un humain a DÉCLARÉ dormant dans ORGAN_MAP ; celle-ci rend ce
    que le corps CONSTATE sur lui-même (`tools/forge_body_regulation_audit.py`, cache
    `sandbox/workspace/body_regulation.json`). Les deux sont nécessaires : une carte
    déclarative vieillit sans prévenir, une mesure seule ignore l'intention.

    Deux défauts remontés, par ordre de gravité :
      - `silent_death` : module lancé par le superviseur SANS heartbeat surveillé.
        Le pire cas — il meurt et personne ne l'apprend.
      - `dead_zone`    : aucun rattachement trouvé. À INSTRUIRE, jamais à supprimer :
        les tâches planifiées et lanceurs de boot du profil owner sont invisibles au
        capteur (mesuré : `forge_owner_daemons.py` sort en zone morte à tort).

    Retour vide et explicite si l'audit n'a jamais tourné — un capteur muet ne doit
    jamais se lire comme « tout va bien ».
    """
    import json
    from collections import defaultdict
    from pathlib import Path

    cache = Path(__file__).resolve().parents[1] / "sandbox" / "workspace" / "body_regulation.json"
    try:
        reg = json.loads(cache.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"audit jamais lance ou cache illisible ({type(e).__name__})",
                "hint": "LAFORGE_PYTHON tools/forge_body_regulation_audit.py"}

    # NATURE avant verdict (2026-07-28). Une « zone morte » n'a de sens que pour un
    # ORGANE : un outil qu'on n'invoque pas est au REPOS, pas necrose. Sur 194 zones
    # mortes mesurees, ~110 etaient des outils, des chantiers clos ou des formulaires
    # d'UI. Le bruit qu'ils produisaient a couvert la mort reelle du daemon
    # epistemique pendant 13 h le meme jour. Source unique = le census.
    import sys as _sys

    try:
        _t = str(Path(__file__).resolve().parents[1] / "tools")
        if _t not in _sys.path:
            _sys.path.insert(0, _t)
        from nokido_agent.tools.forge_module_census import nature as _nature
    except Exception:  # noqa: BLE001
        _nature = None  # census indisponible -> on ne filtre RIEN plutot que de deviner

    per_organ: dict = defaultdict(lambda: {"silent_death": [], "dead_zone": [], "total": 0})
    outils: list = []
    for mod, meta in reg.items():
        o = per_organ[meta.get("organe", "non classe")]
        o["total"] += 1
        nat = meta.get("nature") or (_nature(None, mod) if _nature else "organe")
        if meta.get("statut") == "SUPERVISE":
            o["silent_death"].append(mod)  # une mort silencieuse compte TOUJOURS
        elif meta.get("statut") == "ZONE_MORTE":
            if nat != "organe":
                outils.append(mod)
            else:
                o["dead_zone"].append(mod)
    organs = {k: v for k, v in per_organ.items() if v["silent_death"] or v["dead_zone"]}
    return {
        "ok": True,
        "modules_audited": len(reg),
        "organs_with_gaps": len(organs),
        "silent_death_total": sum(len(v["silent_death"]) for v in organs.values()),
        "dead_zone_total": sum(len(v["dead_zone"]) for v in organs.values()),
        "outils_au_repos": len(outils),
        "outils_echantillon": sorted(outils)[:15],
        "by_organ": {k: v for k, v in sorted(
            organs.items(), key=lambda kv: -(len(kv[1]["silent_death"]) * 10 + len(kv[1]["dead_zone"])))},
    }


def essentials() -> list:
    """Les boucles de régulation essentielles à câbler, priorisées."""
    return [{"prio": p, "name": n, "what": w} for p, n, w in ESSENTIAL_WIRINGS]


def integrate() -> dict:
    """Enregistre le census dans le registre central (forge_keeper_base) — découvrable portier."""
    try:
        from nokido_agent.app.forge_keeper_base import declare
        declare("organ_agents", owns="census organe×agent + câblages régulateurs essentiels",
                owner_module="forge_organ_agents", how="census/gaps/essentials")
        return {"ok": True, "registered": "organ_agents"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "note": f"keeper_base absent ({e})"}


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    c = census()
    chk(len(c["families"]) == 12, f"census 12 familles d'organes ({len(c['families'])})")
    chk(any(r["tier"] in (REFLEX, ACTOR, AGENT) for r in c["families"]), "tiers classifiés")
    g = gaps()
    chk(any("génération" in x["family"].lower() for x in g) and len(g) >= 2,
        f"régénération + sens restent des gaps ({len(g)}) ; endocrinien CLOS sort des gaps")
    es = essentials()
    chk(es[0]["name"] == "endocrine_to_gate" and es[0]["prio"] == "DONE",
        "keystone endocrine_to_gate = DONE (boucle close afferent+efferent)")
    chk(all("missing_wiring" in r for r in c["families"]), "chaque famille a un champ câblage")
    statuses = c["by_status"]
    chk("gap" in statuses or "dormant" in statuses, f"statuts agrégés: {statuses}")
    cp = critical_points()
    chk(len(cp) == 6 and cp[0]["guard"].startswith("SENTINELLE")
        and any(x["prio"] == "P0" for x in cp), f"points critiques -> gardes ({len(cp)})")
    chk("critical_points" in c and any("non consomm" in x["prio"] + x["evidence"] for x in cp),
        "trou récurrent = signaux émis non consommés (sentinelle/coagulation)")
    print(f"selftest: {ok}/{total} OK")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
