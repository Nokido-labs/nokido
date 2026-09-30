#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_nosology.py — NOSOLOGIE de Nokido : symptome -> pathologie -> gravite -> remede,
et la douleur recoit une GRAVITE au lieu d'un mot.

__FORGE_COLOR__ = "observabilite/nosologie"

POURQUOI (mandat owner 2026-07-26, brique UMLS)
----------------------------------------------
Le tableau des pathologies de CLAUDE.md §10 (auto-immunite, epilepsie, sclerose,
hemorragie, septicemie, coma) est de la PROSE : aucun code ne peut s'en servir.
A l'inverse, `forge_health_diagnostic` produit des lacunes marquees ❌ / ⚠ / ~ et
`forge_inspector.ACTION_MATRIX` porte des remedes — mais rien ne relie un symptome
MESURE a une pathologie nommee, a sa gravite et a son remede. Resultat : le canal
algedonique recevait des chaines de caracteres, pas des douleurs graduees.

UMLS/SNOMED donnaient la FORME (code stable, definition, synonymes). On la reprend ;
on ne telecharge pas le Metathesaurus (licence UTS nominative, plusieurs Go, aucune
valeur ici). Les codes sont donc ceux de Nokido — `NOK-nnn` — et l'alignement vers
des CUI UMLS reste possible plus tard, en ajoutant un champ. Dire « UMLS » en
n'ayant que ses propres codes serait un mensonge d'etiquette.

CE QUI N'EST PAS DUPLIQUE
-------------------------
  - Escalade : `forge_viable_system.algedonic_to_police(signal)` decide (high/critical
    -> escalade S5). On l'APPELLE.
  - Persistance : `forge_critical_events.persist(kind, severity, payload)` (fail-safe).
  - Remedes : les cles de `forge_inspector.ACTION_MATRIX` sont referencees, pas recopiees.
  - Debit des effecteurs : `tools/forge_regulation_loops.py`.

REGLE DE PEUPLEMENT
-------------------
Une pathologie n'entre ici que si elle a ete OBSERVEE, avec la date et le fait qui
l'a revelee. Pas de maladie imaginaire : une nosologie inventee pollue le diagnostic
exactement comme une etiquette d'organe devinee pollue l'atlas.

COUT SYSTEME
------------
Zero resident : aucun daemon, aucun thread, aucune dependance externe.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

SEVERITY_ORDER = ("low", "medium", "high", "critical")

# Marqueurs deja produits par forge_health_diagnostic -> gravite.
MARKER_SEVERITY = {"❌": "critical", "⚠": "medium", "~": "low"}

# code · nom · organe · gravite · comment on le DETECTE · remede · ou c'est mesure
PATHOLOGIES: list[dict] = [
    # ── Classiques de CLAUDE.md §10, rendues detectables ────────────────────
    {"code": "NOK-001", "nom": "auto-immunite", "organe": "Immunitaire (firewall/garde)",
     "gravite": "medium", "detect": r"(?i)rejet.*legitime|blocked.*trust|faux positif.*gate",
     "definition": "un bouclier refuse du trafic legitime",
     "remede": "affiner la tolerance interne (whitelist trust>0.8), jamais debrancher le garde",
     "mesure": "CLAUDE.md §10 (table pathologies)"},
    {"code": "NOK-002", "nom": "crise d'epilepsie", "organe": "SN vegetatif (autonome)",
     "gravite": "high", "detect": r"(?i)cascade.*re-?tentative|retry.*infini|boucle de relance",
     "definition": "cascade de re-tentatives sans periode refractaire",
     "remede": "tools/forge_regulation_loops.py (refractaire absolue + relative)",
     "mesure": "CLAUDE.md §10"},
    {"code": "NOK-003", "nom": "hemorragie", "organe": "SN vegetatif (autonome)",
     "gravite": "high", "detect": r"(?i)fuite m[ée]moire|memory leak|RSS.*croissa|orphelin.*Go",
     "definition": "consommation memoire qui ne revient pas",
     "remede": "tools/forge_orphan_reaper.py + verification de l'effet (delta_pt)",
     "mesure": "CLAUDE.md §10 ; orphelin llama 5,6 Go (2026-07-25)"},
    {"code": "NOK-004", "nom": "septicemie", "organe": "Immunitaire (firewall/garde)",
     "gravite": "critical", "detect": r"(?i)exfiltr|beacon|canary.*leak|SSRF",
     "definition": "un composant compromis emet vers l'exterieur",
     "remede": "membrane wrap + post_flight (detection de balise), coupure d'egress",
     "mesure": "CLAUDE.md §10"},
    {"code": "NOK-005", "nom": "coma", "organe": "SNC (cerveau/moelle/SNP)",
     "gravite": "critical", "detect": r"(?i)heartbeat.*(gel|stale)|UP mais ne repond|wedge",
     "definition": "le service est vivant (liveness) mais ne repond plus (readiness)",
     "remede": "sondes de readiness + restart supervise (stopped puis running)",
     "mesure": "CLAUDE.md §10 ; wedge hub 2026-07-01"},

    # ── Pathologies MESUREES le 2026-07-26 (chacune a coute une panne) ───────
    {"code": "NOK-010", "nom": "tetanie d'effecteur", "organe": "SN vegetatif (autonome)",
     "gravite": "critical",
     "detect": r"(?i)dent de scie|sawtooth|force[- ]recycle|redemarrages? r[ée]p[ée]t",
     "definition": "un remede se re-declenche sur son propre contrecoup, faute de periode "
                   "refractaire couvrant le temps de recuperation de sa cible",
     "remede": "refractaire ABSOLUE >= contrecoup + budget de debit par gravite "
               "(tools/forge_regulation_loops.py)",
     "mesure": "2026-07-26 : 3 force-recycles Docker a 133 s d'intervalle, 3 boots REUSSIS"},
    {"code": "NOK-011", "nom": "ligand sans recepteur", "organe": "vegetatif/endocrine",
     "gravite": "medium",
     "detect": r"(?i)sans entr[ée]e RECEPTORS|hormone orphelin|aucun lecteur",
     "definition": "un signal est emis, aucun consommateur ne le lit : l'effet est nul "
                   "et rien ne le signalait",
     "remede": "declarer RECEPTORS ou motiver l'absence (app/forge_endocrine.py)",
     "mesure": "2026-07-26 : ADRENALINE_HUB_PRESSURE emise, aucun lecteur"},
    {"code": "NOK-012", "nom": "capteur aveugle", "organe": "Observabilite/Trace",
     "gravite": "high",
     "detect": r"(?i)UnicodeDecodeError|rien trouv[ée].*pas pu|0 r[ée]sultat.*acc[èe]s refus",
     "definition": "un capteur qui ne PEUT pas voir rend un resultat qui se lit comme "
                   "« rien a signaler »",
     "remede": "errors='replace', et imprimer le diagnostic (chemin, outil, sortie brute) "
               "pour distinguer « rien trouve » de « je ne peux pas voir »",
     "mesure": "2026-07-26 : netstat non-UTF8 faisait echouer TOUTE la sentinelle de ports"},
    {"code": "NOK-013", "nom": "ecriture perdue sur verrou", "organe": "Memoire (hippocampe/RAG)",
     "gravite": "high",
     "detect": r"(?i)database is locked|OperationalError.*lock",
     "definition": "une ecriture SQLite refusee sur verrou est PERDUE si personne ne la reprend",
     "remede": "forge_db_path.write_retry (recul + jitter) et PERSISTER sur disque avant "
               "d'ecrire en base",
     "mesure": "2026-07-26 : 223 325 chars de veille detruits ; emission hormonale perdue"},
    {"code": "NOK-014", "nom": "no-op muet", "organe": "Qualite/Build/Spec",
     "gravite": "high",
     "detect": r"(?i)NameError.*aval|except.*pass.*silenc|no-?op muet",
     "definition": "un garde tombe dans un except large : le code existe, ne sert jamais, "
                   "et aucune trace ne le dit",
     "remede": "verifier que les noms utilises EXISTENT ; ne jamais avaler une erreur "
               "de programmation dans un except destine aux erreurs d'environnement",
     "mesure": "2026-07-26 : _json manquant (historique) puis sys non importe dans "
               "forge_inspector — deux gardes inertes"},
    {"code": "NOK-015", "nom": "alerte sur cadavre", "organe": "Observabilite/Trace",
     "gravite": "low",
     "detect": r"(?i)faux positif|croissance illimit[ée]e(?!.*mesur)",
     "definition": "un avertissement porte sur un etat qui n'existe plus ou n'a jamais existe",
     "remede": "mesurer AVANT d'agir sur un avertissement ; dire explicitement quand "
               "c'est un faux positif",
     "mesure": "2026-07-26 : inspector_log annonce en croissance illimitee, mesure a "
               "exactement 2000 lignes (plafond de l'ecrivain fonctionnel)"},
]

_BY_CODE = {p["code"]: p for p in PATHOLOGIES}


def _sev_rank(s: str) -> int:
    return SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else 0


def classify(text: str) -> list[dict]:
    """Pathologies dont la signature apparait dans ce symptome. Plus grave d'abord.

    Le marqueur de gravite du texte (❌ / ⚠ / ~), s'il est present, RELEVE la gravite
    de la pathologie mais ne l'abaisse jamais : un symptome marque critique par le
    diagnostic ne doit pas etre adouci par une table.
    """
    marker_sev = next((v for k, v in MARKER_SEVERITY.items() if k in (text or "")), None)
    out = []
    for p in PATHOLOGIES:
        if re.search(p["detect"], text or ""):
            sev = p["gravite"]
            if marker_sev and _sev_rank(marker_sev) > _sev_rank(sev):
                sev = marker_sev
            out.append({**{k: p[k] for k in ("code", "nom", "organe", "definition",
                                             "remede", "mesure")},
                        "gravite": sev, "gravite_table": p["gravite"],
                        "gravite_marqueur": marker_sev})
    return sorted(out, key=lambda d: -_sev_rank(d["gravite"]))


def escalate(symptom: str, payload: dict | None = None, dry: bool = False) -> dict:
    """Classe le symptome, persiste l'evenement et laisse la VSM decider de l'escalade.

    On ne reimplemente pas le critere d'escalade : `algedonic_to_police` est seul juge
    (high/critical -> reevaluation du perimetre).
    """
    hits = classify(symptom)
    if not hits:
        return {"symptome": symptom[:120], "pathologie": None,
                "raison": "aucune signature connue — a instruire avant d'inventer une maladie"}
    top = hits[0]
    sig = {"severity": top["gravite"], "kind": "pathology:%s" % top["code"]}
    out = {"symptome": symptom[:120], "pathologie": top["code"], "nom": top["nom"],
           "gravite": top["gravite"], "remede": top["remede"], "autres": [h["code"] for h in hits[1:]]}
    try:
        from nokido_agent.app.forge_viable_system import algedonic_to_police

        out["algedonique"] = algedonic_to_police(sig)
    except Exception as exc:  # noqa: BLE001
        out["algedonique"] = {"error": str(exc)[:80]}
    if dry:
        out["persist"] = "dry-run"
        return out
    try:
        from nokido_agent.app.forge_critical_events import persist

        out["persist"] = persist(sig["kind"], top["gravite"],
                                 {**(payload or {}), "symptome": symptom[:400],
                                  "nom": top["nom"], "remede": top["remede"]})
    except Exception as exc:  # noqa: BLE001
        out["persist"] = "error: %s" % str(exc)[:80]
    return out


def triage(dry: bool = True) -> dict:
    """Graduation des lacunes du diagnostic de sante : chacune recoit une gravite."""
    p = ROOT / "sandbox" / "health_diagnostic.json"
    if not p.exists():
        return {"error": "sandbox/health_diagnostic.json absent — rien a trier"}
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return {"error": "diagnostic illisible: %s" % str(exc)[:80]}
    gaps = [str(g) for g in (d.get("gaps") or [])]
    graded, unknown = [], []
    for g in gaps:
        hits = classify(g)
        if hits:
            graded.append({"lacune": g[:110], "code": hits[0]["code"],
                           "nom": hits[0]["nom"], "gravite": hits[0]["gravite"]})
        else:
            unknown.append(g[:110])
    graded.sort(key=lambda x: -_sev_rank(x["gravite"]))
    return {"score": d.get("score"), "lacunes": len(gaps), "graduees": graded,
            "non_reconnues": unknown, "dry_run": dry}


def main() -> int:
    ap = argparse.ArgumentParser(description="Nosologie Nokido : symptome -> gravite -> remede.")
    ap.add_argument("--list", action="store_true", help="lister les pathologies connues")
    ap.add_argument("--classify", metavar="TEXTE", help="classer un symptome")
    ap.add_argument("--escalate", metavar="TEXTE", help="classer PUIS persister et escalader")
    ap.add_argument("--triage", action="store_true", help="graduer les lacunes du diagnostic")
    ap.add_argument("--dry-run", action="store_true", default=False)
    args = ap.parse_args()

    if args.classify:
        print(json.dumps(classify(args.classify), ensure_ascii=False, indent=2))
        return 0
    if args.escalate:
        print(json.dumps(escalate(args.escalate, dry=args.dry_run), ensure_ascii=False, indent=2))
        return 0
    if args.triage:
        print(json.dumps(triage(), ensure_ascii=False, indent=2))
        return 0

    print("NOSOLOGIE NOKIDO — %d pathologies observees\n" % len(PATHOLOGIES) + "=" * 76)
    for p in sorted(PATHOLOGIES, key=lambda x: (-_sev_rank(x["gravite"]), x["code"])):
        print("  %-8s %-9s %-26s %s" % (p["code"], p["gravite"], p["nom"][:26], p["organe"][:28]))
        print("           %s" % p["definition"][:96])
        print("           remede : %s" % p["remede"][:92])
        print("           mesure : %s" % p["mesure"][:92])
    return 0


if __name__ == "__main__":
    sys.exit(main())
