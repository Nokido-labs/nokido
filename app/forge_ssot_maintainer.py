#!/usr/bin/env python
# -*- coding: utf-8 -*-
# __FORGE_COLOR__ = "memoire/memory SSoT maintainer, garde les etats structures frais"
"""forge_ssot_maintainer.py — garde les SSoT structurés FRAIS (#2 du build SSoT).

Généralisé multi-domaines : chaque domaine a un `build_doc()` DÉTERMINISTE (0 LLM)
qui produit le JSON structuré écrit dans docs/<domain>_state.json. Doit tourner en
contexte TRUSTED (user hub/user/LaForgeTrusted, PAS le sandbox qui n'a pas le write
sur l'arbre Nokido) → consult_ssot bascule en 'structured' = uniforme déterministe.

  - refresh_state(domain) / refresh_all() : régénère le(s) SSoT. CHEAP, 0 LLM.
  - regen_full(domain)                    : générateur LOURD (roadmap synth), cadence rare.

Ajouter un domaine = 1 build_doc + 1 entrée MAINTAINERS (+ 1 entrée forge_ssot.DOMAINS).
Wiring trigger : hook POST_COMMIT + schtask LaForge-SSoTMaintainer (5min).

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `etat_roadmap` — Rend l'etat declare d'un item de roadmap : un marqueur de cloture, ou OUVERT.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Journal du mainteneur. Les except ci-dessous s'en servent : un chemin d'erreur
# qui NOMME un logger inexistant leve une erreur de nom et devient PIRE qu'un
# `pass` — motif deja paye le 2026-08-05 (`_signaler_perte` appelee sans exister).
_LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


# ── Captures déterministes (0 LLM) ───────────────────────────────────────
def _roadmap_capture_state() -> dict:
    import sys
    sys.path.insert(0, str(ROOT))
    from nokido_agent.tools.forge_roadmap_synth import _capture_state
    return _capture_state()


def _read_arch_rules(limit: int = 60) -> list:
    """Source unique des RÈGLES = zone blackboard architecture_rules."""
    import sys
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_swarm_blackboard import read_zone
    raw = read_zone("architecture_rules", limit=limit)
    facts = raw.get("facts") if isinstance(raw, dict) else raw
    out = []
    for f in (facts or []):
        if isinstance(f, dict):
            out.append({
                "key": f.get("key", ""),
                "summary": _coupe(f.get("value") or f.get("fact") or "", 200),
                "trust": f.get("trust", f.get("effective_trust")),
            })
    return out


def _read_lessons_tail(n: int = 25) -> list:
    """Mémoire chronologique Nokido = logs/lessons_learned.md (têtes d'entrées)."""
    p = ROOT / "logs" / "lessons_learned.md"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    heads = [ln.strip() for ln in lines if ln.startswith("#") or ln.lstrip().startswith("- ")]
    return heads[-n:]


def _plafonne(items: list, n: int, refs: list | None = None) -> list:
    """Plafonne une LISTE en le DISANT. Un cap muet se lit « voila tout ».

    `v[:10]` rendait dix elements sans jamais signaler qu il y en avait douze :
    le lecteur du SSoT croyait tenir la liste ENTIERE. C est le meme mensonge
    que la troncature de phrase corrigee juste au-dessus, applique au nombre --
    et c est precisement l antipatron « pas de cap silencieux » : si on borne,
    on dit ce qu on a laisse dehors.

    `refs` (2026-08-10, demande owner) : cles des elements laisses DEHORS. Dire
    « 6 autres » sans dire LESQUELS oblige a re-fouiller la zone entiere. Nommer
    les cles rend le plafond REVERSIBLE, la ou il n'etait qu'honnete.
    """
    items = list(items or [])
    if len(items) <= n:
        return items
    reste = len(items) - n
    hors = [k for k in list(refs or [])[n:] if k]
    if hors:
        adresse = "bb:architecture_rules/{%s}" % ", ".join(hors[:12])
    else:
        adresse = "lire la zone blackboard (category=roadmap)"
    return items[:n] + ["… %d autre(s) non affiche(s) — %s" % (reste, adresse)]


def _coupe(txt: str, n: int, ref: str = "") -> str:
    """Tronque SANS mentir : sur une frontiere de mot, et en le DISANT.

    Les coupes brutes `[:200]` / `[:160]` rendaient des phrases mutilees en plein
    mot -- mesure 2026-07-26 dans le point roadmap : « exposer un job_kill cot »,
    « echec meme en lectur », « NokidoWebHub ... n ecrit ». Rien ne signalait
    l'amputation, donc un fait coupe se lisait comme un fait COMPLET, et une
    phrase qui s'arrete avant son verbe change de sens. Meme famille que les faux
    negatifs deja payes ce jour-la : ne jamais laisser une lecture partielle
    passer pour une lecture entiere.

    Ne coupe rien si le texte tient. Sinon recule au dernier espace et pose « … ».

    `ref` (2026-08-10, demande owner) : POINTEUR de retour vers la trace complete.
    Dire qu'on tronque ne suffit pas — le lecteur voit « … » sans AUCUN moyen de
    retrouver le fait entier. Un « … » sans adresse, c'est de la tracabilite
    d'action perdue, pas seulement abregee. Avec ref, la coupe est REVERSIBLE.
    """
    t = (txt or "").strip()
    if len(t) <= n:
        return t
    bout = t[:n]
    espace = bout.rfind(" ")
    if espace > n * 0.6:  # on ne recule pas jusqu'a vider la ligne
        bout = bout[:espace]
    coupe = bout.rstrip(" ,;:-") + " …"
    return coupe + (" [→ %s]" % ref if ref else "")


# ── Builders de doc structuré par domaine ────────────────────────────────
# LISTE BLANCHE des marqueurs qui FERMENT un item de roadmap. Rien d'autre ne
# ferme : ni un marqueur inconnu, ni l'absence de marqueur.
#
# La zone porte DEJA des marqueurs en tete de fait — `[MESURE le ...]`,
# `[DIRECTIVE OWNER]`, `[ETAPE B]`, `[CARTO COMPLETE]`, `[PARTIAL / STRUCTURAL]`.
# Ceux-la QUALIFIENT un travail, ils ne le closent pas, et les ranger du cote
# fini effacerait des chantiers vivants. Une liste NOIRE ferait tomber toute
# valeur inattendue du cote sain par defaut : c'est exactement ce que la
# constitution semantique interdit.
_ROADMAP_CLOTURE = frozenset({"FAIT", "CLOS", "LIVRE", "RESOLU", "TERMINE", "FERME"})


def etat_roadmap(texte) -> str:
    """Rend l'etat declare d'un item de roadmap : un marqueur de cloture, ou OUVERT.

    Le marqueur se lit UNIQUEMENT en tete, juste apres le prefixe de priorite —
    `P0: [FAIT le 2026-09-15] ...`. Le chercher au fil du texte ferait fermer un
    chantier par le mot « fait » de la phrase qui le decrit ; c'est le meme piege
    que le minage regex sur de la prose, qui rendait deja des items coupes en
    plein mot (mesure 2026-07-22).

    Absence de marqueur, marqueur inconnu, texte vide ou None : OUVERT. Ce qui
    n'est pas PROUVE fini reste a faire.
    """
    import re as _re

    if not texte or not isinstance(texte, str):
        return "OUVERT"
    m = _re.match(
        r"^\s*(?:(?:P[012]|BLOCKER|CURRENT|NEXT|FACT)\s*[:\-]\s*)?\[\s*([A-Za-zÉÀÈÊÎÔÛéàèêîôû_]+)",
        texte.strip(),
    )
    if not m:
        return "OUVERT"
    mot = (
        m.group(1)
        .upper()
        .replace("É", "E").replace("È", "E").replace("Ê", "E")
        .replace("À", "A").replace("Î", "I").replace("Ô", "O").replace("Û", "U")
    )
    return mot if mot in _ROADMAP_CLOTURE else "OUVERT"


# Plancher de confiance d'un JALON (CURRENT / NEXT). Au-dessus, le plus RECENT gagne ; en dessous, un fait ne devient
# jamais le jalon (lecon du 2026-08-10 : un detail recent ecrasait un jalon majeur).
_JALON_TRUST_MIN = 0.8


def _choisir_jalon(cands) -> str:
    """Jalon mono-valeur parmi des (trust, ts, texte). Mesure 2026-10-16 : l'arbitrage (trust, ts) gardait le CURRENT
    du 13/10 (trust 0,96) contre celui du 16/10 (0,95) -- trois jours de jalon PERIME affiche a chaque demarrage. Un
    CURRENT est un instantane date : parmi les CREDIBLES, le plus recent dit l'etat present. Sans aucun credible, repli
    sur l'ancien arbitrage (trust puis anciennete) plutot que rien."""
    if not cands:
        return ""
    credibles = [c for c in cands if c[0] >= _JALON_TRUST_MIN]
    if credibles:
        return max(credibles, key=lambda c: c[1])[2]
    return max(cands, key=lambda c: (c[0], c[1]))[2]


_ETATS_ROADMAP = ("CLOS", "PARTIEL", "OUVERT", "OWNER_PLANIFIE", "DECISION", "EN_COURS", "A_FAIRE",
                  "SANS_MARQUEUR")
_RM_CLE = r"^(?:P[0-3]|roadmap|bug|chantier)[_\-]"
_ROADMAP_ALIAS_PATH = ROOT / "config" / "roadmap_alias.json"
# RETRACTE : entree retiree, plus rien a faire. MESURE / INSTRUIT / A INSTRUIRE / CORRIGE... restent
# SANS_MARQUEUR : le tri du 7/11 les classe tetes inconnues (notes, instruction en cours, correctif non verifie).
_ROADMAP_CLOS_EXTRA = frozenset({"RETRACTE"})


def _marqueur_roadmap(texte) -> str:
    """Mot de tete normalise (`[EN COURS ...]` -> `EN_COURS`), '' sans marqueur.
    Valeur JSON : le champ `etat` fait office de marqueur. `[ETAT X` : le mot ETAT est ignore."""
    import re as _re
    import unicodedata as _ud

    if not texte or not isinstance(texte, str):
        return ""
    texte = texte.strip()
    if texte.startswith("{"):
        try:
            obj = json.loads(texte)
        except Exception:  # noqa: BLE001
            return ""
        etat = obj.get("etat") if isinstance(obj, dict) else None
        texte = f"[{etat}]" if isinstance(etat, str) and etat.strip() else ""
    m = _re.match(r"^\s*(?:(?:P[0-3]|BLOCKER|CURRENT|NEXT|FACT)\s*[:\-]\s*)?\[\s*([^\]]*)", texte)
    if not m:
        return ""
    brut = _ud.normalize("NFD", m.group(1)).encode("ascii", "ignore").decode().upper()
    brut = _re.sub(r"^\s*ETAT\s+", "", brut)
    return _re.sub(r"[^A-Z0-9]+", "_", brut).strip("_")


def _alias_roadmap() -> tuple:
    """(dict cle -> priorite, erreur). Fichier absent = vide sans erreur ; illisible = erreur DITE."""
    try:
        if not _ROADMAP_ALIAS_PATH.exists():
            return {}, ""
        al = json.loads(_ROADMAP_ALIAS_PATH.read_text(encoding="utf-8")).get("alias") or {}
        return {str(k): str((v or {}).get("priorite", "")) if isinstance(v, dict) else "" for k, v in al.items()}, ""
    except Exception as exc:  # noqa: BLE001
        return {}, f"{type(exc).__name__}: {exc}"[:200]


def etat_roadmap_fin(texte) -> str:
    """Etat DISTINCT, jamais ecrase. Marqueur inconnu ou absent : SANS_MARQUEUR (jamais OUVERT ni CLOS)."""
    mk = _marqueur_roadmap(texte)
    if not mk:
        return "SANS_MARQUEUR"
    if mk.startswith("OWNER_PLANIFIE"):
        return "OWNER_PLANIFIE"
    if mk.startswith("DECISION"):
        return "DECISION"
    if mk.startswith("EN_COURS"):
        return "EN_COURS"
    if mk.startswith("A_FAIRE"):
        return "A_FAIRE"
    tete = mk.split("_")[0]
    if tete == "PARTIEL":
        return "PARTIEL"
    if tete == "OUVERT":
        return "OUVERT"
    if tete in _ROADMAP_CLOTURE or tete in _ROADMAP_CLOS_EXTRA:
        return "CLOS"
    return "SANS_MARQUEUR"


def decompte_roadmap() -> dict:
    """Compte TOUTE la roadmap du tableau noir (lecture seule, zones sans filtre de categorie).

    Cause des 70 : l'ancien filtre ne lisait que architecture_rules category='roadmap' (limit 200) puis
    exigeait `P[012]:` en tete ou une cle `roadmap_p[012]` ; les zones roadmap/active_bugs et les cles
    P*_/bug_/chantier_ etaient ignorees, et l'inconnu etait range OUVERT.
    """
    import re as _re
    from nokido_agent.app.forge_swarm_blackboard import read_zone as _rz

    par_etat = {e: 0 for e in _ETATS_ROADMAP}
    par_zone: dict = {}
    exclus = {"tree_locks": 0, "scratch": 0, "permanent": 0}
    sans, hors = [], []
    alias, alias_err = _alias_roadmap()
    alias_comptees: dict = {}
    for z in ("tree_locks", "scratch"):
        exclus[z] = len(_rz(z, limit=100000) or [])
    for zone in ("architecture_rules", "roadmap", "active_bugs"):
        for f in _rz(zone, limit=100000) or []:
            if not isinstance(f, dict):
                continue
            key = f.get("key") or ""
            txt = f.get("value") or f.get("fact") or ""
            if not isinstance(txt, str):
                txt = str(txt)
            if _marqueur_roadmap(txt).startswith("PERMANENT"):
                exclus["permanent"] += 1
                continue
            motif = (bool(_re.match(_RM_CLE, key, _re.I)) or bool(_re.match(r"^\s*P[0-3]\s*[:\-]", txt))
                     or key in alias)
            if key in alias and zone == "architecture_rules":
                alias_comptees[key] = alias[key]
            if zone == "architecture_rules" and not motif:
                if etat_roadmap_fin(txt) != "SANS_MARQUEUR":
                    hors.append(key)
                continue
            etat = etat_roadmap_fin(txt)
            par_etat[etat] += 1
            par_zone[zone] = par_zone.get(zone, 0) + 1
            if etat == "SANS_MARQUEUR":
                sans.append({"cle": key, "zone": zone, "texte": " ".join(txt.split())[:80]})
    return {
        "total": sum(par_etat.values()), "par_etat": par_etat, "par_zone": par_zone,
        "exclus": exclus, "hors_motif_cle": len(hors), "hors_motif_cles": sorted(hors),
        "sans_marqueur": sans,
        "alias_roadmap": {"fichier": "config/roadmap_alias.json", "lues": len(alias),
                          "comptees": alias_comptees, "erreur": alias_err},
    }


def _roadmap_build_doc() -> dict:
    f = ROOT / "docs" / "roadmap_state.json"
    doc = {
        "schema_version": 1, "generated_ts": 0,
        "generated_by": "forge_ssot_maintainer",
        "system_state": {}, "current_milestone": "", "next_milestone": "",
        "blockers": [], "roadmap": {"P0": [], "P1": [], "P2": []},
        "source": "blackboard architecture_rules + KEEPERART_roadmap",
    }
    if f.exists():
        try:
            doc.update(json.loads(f.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            # PAS muet : un state.json corrompu se lit sinon comme un premier
            # demarrage, et le doc reparti de zero efface l'historique en silence.
            _LOG.warning("roadmap: state.json illisible (%r) -> doc par defaut", exc)
    try:
        doc["system_state"] = _roadmap_capture_state()
    except Exception as exc:  # noqa: BLE001
        doc["system_state"] = {"_error": f"{type(exc).__name__}: {exc}"}
    # Derive P0/P1/P2 depuis les faits roadmap du blackboard (architecture_rules) —
    # comble la dette : le maintainer captait system_state mais pas les items roadmap.
    try:
        import re as _re
        from nokido_agent.app.forge_swarm_blackboard import read_zone as _rz
        # FENETRE LARGE. A 40, les faits les plus ANCIENS sortaient du tri
        # updated_at DESC des qu'on en ajoutait de nouveaux : mesure 2026-07-27,
        # cinq notes du soir ont fait DISPARAITRE un bloqueur du SSoT (4 -> 3).
        # Un blocage qui s'efface parce qu'il a vieilli est un mensonge par
        # omission — c'est le meme cap silencieux que celui corrige plus haut.
        facts = _rz("architecture_rules", category="roadmap", limit=200) or []
        pri = {"P0": [], "P1": [], "P2": []}
        # Un fait DEDIE ("P1: <item>." en tete, ou cle roadmap_p1_*) est une declaration
        # d'intention ; une mention de "P1" au fil d'un paragraphe n'en est pas une. Le
        # minage regex sur de la prose rendait des items coupes en plein mot (mesure
        # 2026-07-22 : "stale PARTIEL) · hybride Phase 4 cable+tests 9/9"). On collecte
        # donc les deux, et le STRUCTURE prime des qu'il existe.
        structured = {"P0": [], "P1": [], "P2": []}
        # Cles alignees sur structured : elles rendent le plafond REVERSIBLE
        # (cf _plafonne(refs=...)) — un item laisse dehors reste ADRESSABLE.
        struct_keys = {"P0": [], "P1": [], "P2": []}
        # Comptage par etat et inventaire des items CLOS. Sans ce comptage, un
        # etat qui ne publie que les ouverts laisse croire que le reste n'existe
        # pas : une borne doit dire COMBIEN, pas seulement montrer ce qui reste.
        statuts: dict = {}
        clos: list = []
        for fct in facts:
            txt = (fct.get("value") or fct.get("fact") or "") if isinstance(fct, dict) else str(fct)
            key = (fct.get("key") or "") if isinstance(fct, dict) else ""
            head = _re.match(r"^\s*(P[012])\s*[:\-]\s*(.+)$", txt.strip(), _re.S)
            if head or _re.match(r"(?i)^roadmap[_\-]p[012]", key):
                p = head.group(1) if head else key[8:10].upper()
                etat = etat_roadmap(txt)
                statuts[etat] = statuts.get(etat, 0) + 1
                item = _coupe((head.group(2) if head else txt).strip().rstrip(".").strip(),
                              200, ref=("bb:%s" % key if key else ""))
                if etat != "OUVERT":
                    # Un item clos n'est PAS supprime — il change d'etat et reste
                    # adressable. « Geler, jamais supprimer » : la mesure suivante
                    # doit pouvoir le rouvrir sur une contradiction.
                    if item:
                        clos.append({"priorite": p, "etat": etat, "cle": key, "item": item})
                    continue
                if item and p in structured and item not in structured[p]:
                    structured[p].append(item)
                    struct_keys[p].append(key)
                continue
            for p in ("P0", "P1", "P2"):
                for m in _re.finditer(rf"{p}[\s\-A-Za-z]*[:\-]\s*([^.;]+?)(?=\s+P[012]\b|[.;]|$)", txt):
                    item = _coupe(m.group(1).strip(), 120)
                    if item and item not in pri[p]:
                        pri[p].append(item)
        if any(structured.values()):
            pri = structured
            pri_keys = struct_keys
        else:
            pri_keys = {"P0": [], "P1": [], "P2": []}
        if any(pri.values()):
            doc["roadmap"] = {k: _plafonne(v, 10, pri_keys.get(k))
                              for k, v in pri.items()}
            doc["source"] = "blackboard architecture_rules (category=roadmap)"
            # INVENTAIRE COMPLET, jamais plafonne ni tronque : meme un fait sorti
            # par le cap des 10 reste retrouvable ici. C'est le filet qui garantit
            # qu'AUCUNE trace d'action passee ne se perde entre blackboard et SSoT.
            doc["refs"] = {
                "zone": "architecture_rules", "category": "roadmap",
                "n_faits": len(facts),
                "keys": sorted(k for k in ((f.get("key") or "")
                                           for f in facts if isinstance(f, dict)) if k),
            }
        # Publies MEME quand aucun item structure n'a ete trouve : un comptage
        # absent ne se distingue pas d'un comptage a zero, et c'est la confusion
        # que ce champ existe pour tuer.
        statuts.setdefault("OUVERT", 0)
        doc["roadmap_statuts"] = statuts
        doc["roadmap_clos"] = clos
    except Exception as exc:  # noqa: BLE001
        # PAS muet : sans cette trace, un blackboard injoignable rend une roadmap
        # VIDE qui se lit « rien a faire » au lieu de « je n'ai pas pu regarder ».
        _LOG.warning("roadmap: derivation P0/P1/P2 ECHOUEE (%r) -> roadmap non mise a jour", exc)
    # Derive current_milestone / next_milestone / blockers depuis les MEMES faits blackboard
    # (prefixes CURRENT:/MILESTONE:, NEXT:, BLOCKER:). Blackboard = source de verite : le plus
    # recent gagne pour current/next (mono-valeur) ; blockers = liste dedup ; absence = vide.
    try:
        from nokido_agent.app.forge_swarm_blackboard import read_zone as _rz2
        cfacts = _rz2("architecture_rules", category="roadmap", limit=200) or []
        cur, nxt, blk, nxts, blk_clos = "", "", [], [], []
        # Arbitrage (trust, ts) et non ts SEUL : le jalon courant etait pris au
        # DERNIER fait ecrit, donc n'importe quel detail recent ecrasait un jalon
        # majeur. Mesure 2026-08-10 : un arbitrage Qdrant local a supplante le P0
        # « rejeu des veilles ». La confiance prime, l'anciennete departage.
        # Candidats collectes puis departages par _choisir_jalon (16/10 : la confiance seule gardait un jalon perime).
        cands_cur, cands_nxt = [], []
        for fct in cfacts:
            if not isinstance(fct, dict):
                continue
            txt = (fct.get("value") or fct.get("fact") or "").strip()
            ts = float(fct.get("updated_at") or 0)
            low = txt.lower()
            trust = float(fct.get("trust") or 0.0)
            fkey = (fct.get("key") or "")
            fref = ("bb:%s" % fkey) if fkey else ""
            if low.startswith("current:") or low.startswith("milestone:"):
                if etat_roadmap(txt) != "OUVERT":
                    continue  # un jalon marque clos/perime n'est plus l'etat courant
                cands_cur.append((trust, ts, _coupe(txt.split(":", 1)[1].strip(), 200, ref=fref)))
            elif low.startswith("next:"):
                # Meme regle que les BLOCKER (liste BLANCHE) : un « NEXT: [FAIT ...] » n'est plus un prochain pas.
                # Mesure 2026-10-16 : « NEXT: [FAIT le 2026-09-27] moisson relancee » restait parmi les next_items.
                _etat_n = etat_roadmap(txt)
                if _etat_n != "OUVERT":
                    blk_clos.append({"priorite": "NEXT", "etat": _etat_n, "cle": fkey,
                                     "item": _coupe(txt.split(":", 1)[1].strip(), 160, ref=fref)})
                    continue
                # Le JALON suivant est mono-valeur (le plus recent gagne), mais
                # les autres NEXT ne sont pas du bruit : ce sont les prochains
                # pas, et les ecraser en silence les efface. Mesure 2026-07-27 :
                # quatre notes du soir se sont mutuellement remplacees, seule la
                # derniere subsistait. On garde donc la liste A COTE du jalon.
                _n = _coupe(txt.split(":", 1)[1].strip(), 200, ref=fref)
                if _n and _n not in nxts:
                    nxts.append(_n)
                cands_nxt.append((trust, ts, _n))
            elif low.startswith("blocker:"):
                b = _coupe(txt.split(":", 1)[1].strip(), 160, ref=fref)
                # Un BLOCKER clos ([CLOS], [RESOLU], [FAIT]...) ne bloque plus : meme regle que
                # les items P0-P2 (etat_roadmap, liste BLANCHE). Mesure 2026-10-02 : un
                # « [CLOS le 2026-10-02 sur remesure] » restait affiche parmi les bloqueurs.
                _etat_b = etat_roadmap(txt)
                if _etat_b != "OUVERT":
                    blk_clos.append({"priorite": "BLOCKER", "etat": _etat_b, "cle": fkey, "item": b})
                    continue
                if b and b not in blk:
                    blk.append(b)
        cur, nxt = _choisir_jalon(cands_cur), _choisir_jalon(cands_nxt)
        doc["current_milestone"] = cur
        doc["next_milestone"] = nxt
        doc["next_items"] = _plafonne(nxts, 12)
        doc["blockers"] = _plafonne(blk, 10)
        if blk_clos:
            doc["roadmap_clos"] = list(doc.get("roadmap_clos") or []) + blk_clos
    except Exception as exc:  # noqa: BLE001
        # PAS muet : un echec ici laisse current/next/blockers aux valeurs de
        # l'ancien doc — donc un jalon PERIME passe pour l'etat courant.
        _LOG.warning("roadmap: derivation jalons/blockers ECHOUEE (%r) -> valeurs precedentes conservees", exc)
    try:
        doc["roadmap_decompte"] = decompte_roadmap()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("roadmap: decompte complet ECHOUE (%r)", exc)
    doc["generated_ts"] = int(time.time())
    doc["generated_by"] = "forge_ssot_maintainer.refresh_state"
    return doc


def _rules_build_doc() -> dict:
    try:
        rules = _read_arch_rules()
    except Exception as exc:  # noqa: BLE001
        rules = [{"_error": f"{type(exc).__name__}: {exc}"}]
    return {
        "schema_version": 1, "generated_ts": int(time.time()),
        "generated_by": "forge_ssot_maintainer.refresh_state",
        "count": len(rules), "rules": rules, "source": "blackboard:architecture_rules",
    }


def _memory_build_doc() -> dict:
    try:
        recent = _read_lessons_tail()
    except Exception as exc:  # noqa: BLE001
        recent = [f"_error {type(exc).__name__}: {exc}"]
    return {
        "schema_version": 1, "generated_ts": int(time.time()),
        "generated_by": "forge_ssot_maintainer.refresh_state",
        "count": len(recent), "recent": recent, "source": "logs/lessons_learned.md",
    }


def _providers_build_doc() -> dict:
    """SSoT providers = inventaire fédéré du registre d'endpoints (déterministe)."""
    try:
        import sys
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app import forge_agent_proxy as _P
        try:
            _P._init_registry()
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("endpoints: _init_registry indisponible (%r) -> inventaire partiel", exc)
        from nokido_agent.tools.forge_endpoint_registry import build_inventory
        inv = build_inventory().get("endpoints", {})
        provs = sorted(
            ({"id": e["id"], "model": e.get("model"), "tier": e.get("tier"),
              "key_present": e.get("key_present"), "min_ring": e.get("min_ring")}
             for e in inv.values()),
            key=lambda x: (x["tier"] or "", x["id"]),
        )
    except Exception as exc:  # noqa: BLE001
        provs = [{"_error": f"{type(exc).__name__}: {exc}"}]
    return {"schema_version": 1, "generated_ts": int(time.time()),
            "generated_by": "forge_ssot_maintainer.refresh_state",
            "count": len(provs), "providers": provs, "source": "forge_endpoint_registry"}


def _system_state_build_doc() -> dict:
    """SSoT system_state = état infra capté live (ports/services/hub, 0 LLM)."""
    try:
        st = _roadmap_capture_state()
    except Exception as exc:  # noqa: BLE001
        st = {"_error": f"{type(exc).__name__}: {exc}"}
    return {"schema_version": 1, "generated_ts": int(time.time()),
            "generated_by": "forge_ssot_maintainer.refresh_state",
            "hub_version": st.get("hub_version", ""), "master_up": st.get("master_up", False),
            "ports": st.get("ports", {}), "services_degraded": st.get("services_degraded", []),
            "source": "forge_roadmap_synth._capture_state"}


# domaine → {file, build_doc, regen_cmd?}. Ajouter un domaine = 1 entrée.
MAINTAINERS: Dict[str, Dict[str, Any]] = {
    "roadmap": {"file": ROOT / "docs" / "roadmap_state.json",
                "build_doc": _roadmap_build_doc, "regen_cmd": "tools/forge_roadmap_synth.py"},
    "rules":   {"file": ROOT / "docs" / "rules_state.json", "build_doc": _rules_build_doc},
    "memory":  {"file": ROOT / "docs" / "memory_state.json", "build_doc": _memory_build_doc},
    "providers":    {"file": ROOT / "docs" / "providers_state.json", "build_doc": _providers_build_doc},
    "system_state": {"file": ROOT / "docs" / "system_state.json", "build_doc": _system_state_build_doc},
}


def refresh_state(domain: str) -> dict:
    """Régénère le SSoT structuré d'un domaine. Écrit docs/ TRUSTED -> consult 'structured'."""
    cfg = MAINTAINERS.get(domain)
    if not cfg:
        raise KeyError(f"domaine non maintenu: {domain}")
    doc = cfg["build_doc"]()
    f = Path(cfg["file"])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"domain": domain, "file": str(f),
            "generated_ts": doc.get("generated_ts"), "keys": list(doc.keys())}


def refresh_all() -> list:
    """Rafraîchit TOUS les domaines maintenus (best-effort, ne lève jamais)."""
    out = []
    for d in MAINTAINERS:
        try:
            out.append(refresh_state(d))
        except Exception as exc:  # noqa: BLE001
            out.append({"domain": d, "error": f"{type(exc).__name__}: {exc}"})
    return out


def regen_full(domain: str) -> dict:
    """Régénère TOUT via le générateur lourd (roadmap synth). Cadence RARE, trusted."""
    import subprocess
    import sys
    cfg = MAINTAINERS.get(domain)
    if not cfg or not cfg.get("regen_cmd"):
        raise KeyError(f"pas de regen pour: {domain}")
    script = ROOT / cfg["regen_cmd"]
    r = subprocess.run([sys.executable, str(script)], capture_output=True,
                       text=True, errors="replace", timeout=600, cwd=str(ROOT))
    return {"domain": domain, "rc": r.returncode, "tail": (r.stdout or "")[-400:]}


def _selftest() -> int:
    import sys
    res = refresh_all()
    print("[selftest] refresh_all:", json.dumps(res, ensure_ascii=False))
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_ssot import consult_ssot
    for d in ("roadmap", "rules", "memory", "providers", "system_state"):
        c = consult_ssot(d)
        print(f"[selftest] consult_ssot({d}) kind={c['kind']} stale_s={c.get('stale_s')}")
        assert c["kind"] == "structured", f"{d} pas structuré"
    print("[selftest] OK — 5 domaines SSoT structurés (roadmap/rules/memory/providers/system_state)")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Maintainer SSoT — refresh structuré (trusted).")
    ap.add_argument("--selftest", action="store_true", help="boucle de validation")
    ap.add_argument("--regen", metavar="DOMAIN", help="regen_full lourd d'un domaine")
    ap.add_argument("--daemon", action="store_true", help="boucle continue (service supervisor, cross-OS portable)")
    ap.add_argument("--interval", type=int, default=300, help="secondes entre refresh (mode daemon)")
    _a = ap.parse_args()
    if _a.selftest:
        raise SystemExit(_selftest())
    if _a.regen:
        print(json.dumps(regen_full(_a.regen), ensure_ascii=False))
        raise SystemExit(0)
    if _a.daemon:
        import time as _t
        while True:
            try:
                refresh_all()
                # Pouls APRES un refresh reussi : un SSoT fige doit se voir. Recense
                # SUPERVISE le 2026-07-28 — lance sans heartbeat, donc mort silencieuse.
                try:
                    from nokido_agent.app.forge_heartbeat import beat_daemon

                    beat_daemon("ssot_maintainer", interval_s=_a.interval)
                except Exception as exc:  # noqa: BLE001
                    # Ce daemon etait deja SUPERVISE sans heartbeat (mort silencieuse).
                    # Rater le heartbeat SANS le dire recreerait exactement ce trou.
                    _LOG.warning("ssot_maintainer: heartbeat NON arme (%r) -> mort silencieuse possible", exc)
            except Exception as _e:  # noqa: BLE001
                print(f"[ssot daemon] err: {_e}", flush=True)
            _t.sleep(_a.interval)
    print(json.dumps(refresh_all(), ensure_ascii=False))
    raise SystemExit(0)
