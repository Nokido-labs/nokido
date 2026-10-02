#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""APPLICATEUR de propositions — reflexe medullaire vs decision corticale.

Le corps produisait des propositions que personne n'appliquait : 17 lignes dans
`orchestrator_recommendations`, 0 appliquee, alors que la table porte depuis toujours
`applied_at`, `applied_by` et `rolled_back_at`. La chaine s'arretait un maillon avant
le geste.

## Le partage, et pourquoi il est biomimetique (revue AGY 2026-07-30)

Un organisme n'arbitre pas tout au cortex. La moelle epiniere execute seule ce qui est
REVERSIBLE : le reflexe myotatique retire la main avant que le cerveau ait vu la
brulure. Ce qui engage l'organisme durablement, en revanche, remonte.

  ETAGE REFLEXE (medullaire) : `reclaim_cache`, `unload_idle`. S'execute seul.
      Critere d'appartenance, donne par AGY et retenu tel quel : la reversibilite est
      PURE -- on perd de la performance et du temps de reconstruction, JAMAIS de
      l'etat. Un cache rendu se reconstruit ; un service arrete casse ce qui l'utilise.
  ETAGE CORTICAL : `stop_service`, `topology_change`, et TOUT type inconnu. Exige
      `owner_armed`. Le defaut d'un type non reconnu est le cortex, jamais le reflexe :
      une action qu'on ne sait pas classer n'est pas reversible par optimisme.

## Mesure du succes : l'observable VISE, la sante globale en VETO seulement

AGY, tour 2 R3 : valider le rollback sur la delta-mesure de l'observable vise, et
n'utiliser la sante globale que comme circuit-breaker. La raison est symetrique et les
deux erreurs sont reelles : un score global peut chuter pour une cause etrangere a
l'action (rollback injustifie), et il peut ne pas bouger alors qu'on a casse une chose
precise (degat invisible).

Un mot sur la contamination, car elle a decide de l'implementation : `free_ram_mb` est
CONTAMINE -- un autre process peut liberer ou consommer pendant la fenetre, et
l'applicateur s'attribuerait son merite. On mesure donc en priorite le RSS du pid
PORTEUR quand il est lisible, et l'on RETIENT la mesure auto-declaree par le
reclaimer comme repli EXPLICITEMENT etiquete `auto_declare` : une mesure auto-declaree
n'est pas interdite, elle est SUSPECTE, et le seul tort serait de ne pas dire laquelle
des deux on a utilisee.

## Ce module est DESARME par defaut

`LAFORGE_APPLIER_ARMED` absent => `dry_run` intégral, y compris l'etage reflexe. On
n'arme pas l'auto-application d'un corps sans que son proprietaire l'ait decide : ce
serait exactement le geste que la regle « confirmer l'irreversible » interdit. Le
mode desarme fait TOUT le travail de mesure et de journal, sans muter -- il rend donc
le plan d'application verifiable avant d'etre autorise.

Usage :
    LAFORGE_PYTHON app/forge_proposal_applier.py              # plan, sans muter
    LAFORGE_PYTHON app/forge_proposal_applier.py --json
    (arme) LAFORGE_APPLIER_ARMED=1 ... appliquer l'etage reflexe

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `cible_protegee` — Premiere cible protegee visee par l'action, ou None. Chemin normalise en `/`.
- `porte_evolution` — Etat de la porte UNIQUE d'evolution, lu a chaque appel. Fail-closed.
- `empreinte_l1` — sha256 de l'etat L1 canonique. L'« arbre » du niveau L1 : un retour arriere est
- `valeur_l1` — Lecteur pour les organes : valeur L1 courante, sinon le defaut DECLARE, sinon `defaut`.
"""

from __future__ import annotations

__FORGE_COLOR__ = "sn-vegetatif/applicateur-propositions"

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

DB = ROOT / "RAG" / "embeddings.db"

REFLEXE = {"reclaim_cache", "unload_idle"}
CORTICAL = {"stop_service", "topology_change"}

# ── L1 `set_param` (mission regeneration du 2026-10-01, note RSI §2.2) ─────────────
# Le premier niveau de la boucle proposer -> verifier -> appliquer -> mesurer est le plus
# reversible : un PARAMETRE, pas du code. Trois conditions avant qu'un reglage parte seul :
#   1. le parametre est DECLARE ici (liste BLANCHE, vide par defaut : declarer un reglage
#      est une decision owner -- un nom absent reste CORTICAL, jamais execute) ;
#   2. il porte une MESURE (`mesure` = "module:fonction" rendant {dimension: score}, plus
#      haut = mieux) et sa bande de BRUIT par dimension : un reglage qu'on ne sait pas
#      mesurer ne s'applique pas seul, et sans bruit declare on ne sait pas dire « revenu » ;
#   3. la porte d'evolution est ARMEE (`forge_mutation_judge.evolution_autorisee`).
# Schema : {"nom": {"type": "float"|"int"|"bool"|"str", "min": x, "max": y, "defaut": v,
#                   "mesure": "module:fonction", "bruit": {"dimension": 0.01}}}
PARAMS_L1: dict[str, dict] = {}
# Valeurs COURANTES des reglages L1. Chaque entree garde l'entree qu'elle remplace
# (`precedente`) : un process qui meurt entre l'acte et la mesure laisse de quoi revenir.
PARAMS_L1_FICHIER = ROOT / "sandbox" / "parametres_l1.json"

# Seuil de confiance de l'etage reflexe (AGY tour 1) : au-dessous, meme une action
# reversible attend un arbitrage. Ce n'est pas un chiffre invente ici -- c'est celui
# que produit deja la derivation de confiance de `pat_self_improvement` pour un
# depassement de budget CONSTATE (0.75), donc le reflexe s'aligne sur la mesure.
CONF_REFLEXE = 0.75
# Fenetre de surveillance apres l'acte (AGY tour 1) : le contrecoup d'un reclaim se
# voit en dizaines de secondes, pas en minutes.
FENETRE_S = 60.0
# Chute de sante globale au-dela de laquelle on annule MEME si l'observable vise s'est
# ameliore : detection d'un effet secondaire sur un autre organe (AGY tour 2 R3).
VETO_CHUTE_PCT = 15.0


# ── BARRIERE (2026-09-24, veilles lot_C_12 / lot_C_01b, decision owner) ───────────
# « Reward hacking » : un systeme qui optimise ses propres controles finit par les
# affaiblir. Aucune action de cet applicateur n'ecrit de fichier AUJOURD'HUI ; la
# barriere est posee AVANT qu'un type d'action le permette. Une action dont UNE
# cible designe une zone protegee passe a l'etage REFUSE, qui n'est JAMAIS execute,
# arme ou non. Le controle ne peut pas etre modifie par ce qu'il controle.
_CLES_CIBLE = ("path", "paths", "file", "files", "fichier", "fichiers", "target", "cible",
               "cibles", "module")
_PREFIXES_PROTEGES = ("tests/", ".github/workflows/", "tools/hook_")
_FICHIERS_PROTEGES = {"tools/ci_local.py", "tools/bash_guard.py", "app/forge_scorecard.py",
                      "app/forge_proposal_applier.py", "tools/forge_governed_edit.py"}
_MOTIFS_PROTEGES = ("ratchet", "cliquet", "conftest")


def cible_protegee(action) -> str | None:
    """Premiere cible protegee visee par l'action, ou None. Chemin normalise en `/`."""
    if not isinstance(action, dict):
        return None
    cibles = []
    for k in _CLES_CIBLE:
        v = action.get(k)
        if isinstance(v, str):
            cibles.append(v)
        elif isinstance(v, (list, tuple)):
            cibles.extend(x for x in v if isinstance(x, str))
    for c in cibles:
        n = c.replace("\\", "/").lower()
        while n.startswith("./"):           # PAS lstrip("./") : il mangerait le « . » de .github
            n = n[2:]
        if (n.startswith(_PREFIXES_PROTEGES) or n in _FICHIERS_PROTEGES
                or any(m in n.rsplit("/", 1)[-1] for m in _MOTIFS_PROTEGES)):
            return c
        try:
            from nokido_agent.app.forge_mcp_security import _is_critical
            if _is_critical(n):
                return c
        except Exception:  # noqa: BLE001  # muet-ok : la liste locale ci-dessus reste appliquee
            pass
    return None


def arme() -> bool:
    """L'owner a-t-il arme l'auto-application ? Defaut : NON."""
    return str(os.environ.get("LAFORGE_APPLIER_ARMED", "")).strip().lower() in (
        "1", "true", "yes", "on")


def porte_evolution() -> dict:
    """Etat de la porte UNIQUE d'evolution, lu a chaque appel. Fail-closed.

    `forge_mutation_judge.evolution_autorisee()` porte le verrou humain, le frein
    `sandbox/evolution.halt` et l'armement. Une porte ABSENTE (version du juge qui ne la
    connait pas) ou qui LEVE rend `INCONNU`, donc non autorisee : je ne peux pas voir
    n'est pas « tout va bien ».
    """
    try:
        from nokido_agent.app import forge_mutation_judge as _juge
        f = getattr(_juge, "evolution_autorisee", None)
        if f is None:
            return {"autorisee": False, "etat": "INCONNU",
                    "motif": "porte absente de forge_mutation_judge (version anterieure)"}
        r = f() or {}
        return {"autorisee": r.get("autorisee") is True, "etat": r.get("etat") or "INCONNU",
                "motif": r.get("motif") or ""}
    except Exception as exc:  # noqa: BLE001 - porte illisible = fermee, et le DIRE
        return {"autorisee": False, "etat": "INCONNU",
                "motif": "porte illisible (%s: %s)" % (type(exc).__name__, str(exc)[:120])}


# ── Magasin L1 : lecture, ecriture canonique, empreinte ──────────────────────────
def _lire_l1() -> dict:
    """Valeurs L1 courantes. Fichier absent = {} ; fichier ILLISIBLE leve : ecrire par-dessus
    effacerait des reglages qu'on n'a pas su lire."""
    try:
        brut = PARAMS_L1_FICHIER.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    d = json.loads(brut)
    if not isinstance(d, dict):
        raise ValueError("magasin L1 non conforme (attendu un objet JSON)")
    return d


def _ecrire_l1(d: dict) -> None:
    """Ecriture CANONIQUE (cles triees) et atomique : deux etats egaux ont les memes octets,
    ce qui rend l'empreinte comparable avant et apres un retour arriere."""
    PARAMS_L1_FICHIER.parent.mkdir(parents=True, exist_ok=True)
    tmp = PARAMS_L1_FICHIER.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, sort_keys=True, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, PARAMS_L1_FICHIER)


def empreinte_l1() -> str:
    """sha256 de l'etat L1 canonique. L'« arbre » du niveau L1 : un retour arriere est
    PROUVE quand cette empreinte redevient celle d'avant l'acte."""
    import hashlib
    canon = json.dumps(_lire_l1(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def valeur_l1(nom: str, defaut=None):
    """Lecteur pour les organes : valeur L1 courante, sinon le defaut DECLARE, sinon `defaut`.

    Un magasin illisible rend le defaut declare, et ne leve pas : le reglage courant est
    perdu pour ce lecteur, l'organe ne doit pas l'etre."""
    decl = PARAMS_L1.get(nom) or {}
    try:
        e = _lire_l1().get(nom)
    except Exception:  # noqa: BLE001 - muet-ok : le defaut declare reste une valeur sure
        e = None
    if isinstance(e, dict) and "valeur" in e:
        return e["valeur"]
    return decl.get("defaut", defaut)


def _valeur_conforme(nom: str, valeur) -> str | None:
    """None si `valeur` est conforme a la declaration de `nom`, sinon le motif du refus."""
    decl = PARAMS_L1.get(nom)
    if decl is None:
        return "parametre %r hors liste blanche L1" % nom
    typ = decl.get("type")
    if typ == "bool":
        ok = isinstance(valeur, bool)
    elif typ == "int":
        ok = isinstance(valeur, int) and not isinstance(valeur, bool)
    elif typ == "float":
        ok = isinstance(valeur, (int, float)) and not isinstance(valeur, bool)
    elif typ == "str":
        ok = isinstance(valeur, str)
    else:
        return "type declare inconnu %r pour %r" % (typ, nom)
    if not ok:
        return "valeur %r n'est pas du type %s" % (valeur, typ)
    if typ in ("int", "float"):
        if "min" in decl and valeur < decl["min"]:
            return "valeur %r sous le minimum %r" % (valeur, decl["min"])
        if "max" in decl and valeur > decl["max"]:
            return "valeur %r au-dessus du maximum %r" % (valeur, decl["max"])
    return None


def _etage_set_param(action: dict, conf: float, porte: dict) -> tuple[str, str]:
    """(etage, motif) d'un `set_param`. CORTICAL tant que la porte n'est pas armee."""
    nom = action.get("param")
    if nom not in PARAMS_L1:
        return "CORTICAL", ("parametre %r hors liste blanche L1 — le declarer reglable est "
                            "une decision owner" % nom)
    if "valeur" not in action:
        return "REFUSE", "set_param sans `valeur` — jamais execute"
    refus = _valeur_conforme(nom, action["valeur"])
    if refus:
        return "REFUSE", refus + " — jamais executee"
    decl = PARAMS_L1[nom]
    if not decl.get("mesure") or not isinstance(decl.get("bruit"), dict):
        return "CORTICAL", ("aucune mesure (ou bande de bruit) declaree pour %r : un reglage "
                            "qu'on ne sait pas mesurer ne s'applique pas seul" % nom)
    if not porte.get("autorisee"):
        return "CORTICAL", "porte d'evolution %s : %s" % (porte.get("etat"), porte.get("motif"))
    if float(conf or 0) < CONF_REFLEXE:
        return "CORTICAL", "L1 reversible mais confiance %.2f < %.2f" % (float(conf or 0), CONF_REFLEXE)
    return "REFLEXE", ("L1 reversible : valeur precedente memorisee, mesure declaree, porte %s"
                       % porte.get("etat"))


def _set_param(action: dict) -> dict:
    """Pose la valeur ; rend la TRACE qui permet d'y revenir a l'octet pres.

    La trace porte l'entree REMPLACEE entiere (ou son absence) : la restaurer redonne
    exactement l'etat d'avant, metadonnees comprises -- donc la meme empreinte.
    """
    nom = action["param"]
    refus = _valeur_conforme(nom, action.get("valeur"))
    if refus:
        return {"ok": False, "detail": refus}
    d = _lire_l1()
    ancienne = d.get(nom)
    d[nom] = {"valeur": action["valeur"], "precedente": ancienne,
              "pose_le": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "exp_id": action.get("exp_id")}
    _ecrire_l1(d)
    return {"ok": True, "param": nom, "nouvelle": action["valeur"],
            "existait": ancienne is not None, "ancienne_entree": ancienne}


def _restaurer_param(trace: dict) -> dict:
    """Retour arriere L1 : remet l'entree remplacee, ou retire la cle si elle n'existait pas."""
    nom = trace["param"]
    d = _lire_l1()
    if trace.get("existait"):
        d[nom] = trace.get("ancienne_entree")
    else:
        d.pop(nom, None)
    _ecrire_l1(d)
    return {"ok": True, "param": nom}


def _mesure_declaree(nom: str):
    """La fonction de mesure declaree pour `nom` ("module:fonction"), resolue a l'appel."""
    import importlib
    mod, _, fn = str(PARAMS_L1[nom]["mesure"]).partition(":")
    try:
        m = importlib.import_module("nokido_agent.app." + mod)
    except ImportError:
        m = importlib.import_module(mod)
    return getattr(m, fn)


def _conn_ro() -> sqlite3.Connection:
    return sqlite3.connect("file:%s?mode=ro" % DB.as_posix(), uri=True)


def _action_de(evidence) -> dict | None:
    """Extrait l'action MACHINE d'une proposition. None = proposition diagnostique.

    Une proposition dont `suggested_value` est de la prose n'est PAS appliquee : elle
    decrit un remede a un humain. Confondre les deux ferait executer une phrase.
    """
    if not evidence:
        return None
    try:
        ev = json.loads(evidence) if isinstance(evidence, str) else dict(evidence)
    except Exception:
        return None  # muet-ok : une preuve illisible ne devient pas une action
    a = ev.get("action")
    if isinstance(a, dict) and a.get("type"):
        return a
    return None


def _sante_globale() -> float | None:
    """Score de sante consolide. None = illisible, ce qui INTERDIT le reflexe.

    On demande au diagnostic existant (`forge_health_diagnostic`) au lieu de recomposer
    un score : un second bareme de sante donnerait deux verites.
    """
    try:
        from nokido_agent.app.forge_health_diagnostic import run_cycle
        r = run_cycle() or {}
        for k in ("score", "health_score", "global_score"):
            if isinstance(r.get(k), (int, float)):
                return float(r[k])
        return None
    except Exception:
        return None


def _observable(action: dict) -> dict:
    """Mesure l'observable VISE par cette action, en nommant sa provenance.

    `source` vaut `rss_pid` (propre), `free_ram` (contamine, dit) ou `indisponible`.
    """
    typ = action.get("type")
    pid = action.get("pid")
    if typ in ("reclaim_cache", "unload_idle") and pid:
        try:
            import psutil
            return {"source": "rss_pid", "pid": int(pid),
                    "valeur_go": round(psutil.Process(int(pid)).memory_info().rss / 1e9, 3)}
        except Exception:
            pass  # muet-ok : on retombe sur la mesure contaminee, en le DISANT
    try:
        import psutil
        return {"source": "free_ram", "contamine": True,
                "valeur_go": round(psutil.virtual_memory().available / 1e9, 3)}
    except Exception:
        return {"source": "indisponible", "valeur_go": None}


def _executer(action: dict) -> dict:
    """Execute une action REFLEXE. Rend ce qui a REELLEMENT ete libere, ou 0."""
    typ = action.get("type")
    if typ == "reclaim_cache":
        from nokido_agent.app.forge_resource_manager import run_reclaimers
        r = run_reclaimers(float(action.get("needed_gb") or 0.0)) or {}
        return {"ok": bool(r.get("ok")), "auto_declare_go": r.get("freed_gb"),
                "detail": (r.get("action") or [])[:4]}
    if typ == "unload_idle":
        from nokido_agent.app.forge_resource_manager import ollama_unload
        nom = action.get("model")
        if not nom:
            return {"ok": False, "detail": "unload_idle sans `model`"}
        return {"ok": bool(ollama_unload(nom)), "detail": "ollama_unload:%s" % nom}
    return {"ok": False, "detail": "type non reflexe: %r" % typ}


def _marquer(rec_id: int, applied_by: str, rolled_back: bool) -> bool:
    """Ecrit le cycle de vie de la proposition. Par le writer gouverne."""
    try:
        from nokido_agent.app.forge_db_path import write_retry

        def _corps(cx):
            cx.execute(
                "UPDATE orchestrator_recommendations SET applied_at=datetime('now'), "
                "applied_by=? WHERE id=?", (applied_by, int(rec_id)))
            if rolled_back:
                cx.execute("UPDATE orchestrator_recommendations "
                           "SET rolled_back_at=datetime('now') WHERE id=?", (int(rec_id),))
            return True

        return bool(write_retry(_corps))
    except Exception as exc:
        print("[applicateur] marquage PERDU pour #%s (%s) — une application non tracee "
              "serait reappliquee en boucle" % (rec_id, type(exc).__name__), file=sys.stderr)
        return False


def plan() -> list[dict]:
    """Ce qui serait applique, et a quel etage. Aucune mutation."""
    try:
        cx = _conn_ro()
        rows = cx.execute(
            "SELECT id, param, confidence, evidence, reason FROM orchestrator_recommendations "
            "WHERE applied_at IS NULL ORDER BY confidence DESC").fetchall()
        cx.close()
    except Exception as exc:
        return [{"erreur": "propositions ILLISIBLES: %s" % type(exc).__name__}]

    out = []
    porte = None  # lue au plus UNE fois par plan, et seulement si un set_param la demande
    for rid, param, conf, ev, reason in rows:
        action = _action_de(ev)
        typ = (action or {}).get("type")
        protegee = cible_protegee(action)
        if protegee:
            etage, motif = "REFUSE", ("cible protegee %r (test, cliquet, garde ou fichier "
                                      "critique) — jamais executee, armee ou non" % protegee)
        elif not action:
            etage, motif = "DIAGNOSTIC", ("aucune action machine declaree — remede en prose, "
                                          "lecture humaine")
        elif typ == "set_param":
            if porte is None:
                porte = porte_evolution()
            etage, motif = _etage_set_param(action, conf, porte)
        elif typ in REFLEXE and float(conf or 0) >= CONF_REFLEXE:
            etage, motif = "REFLEXE", "reversible pur et confiance %.2f >= %.2f" % (
                float(conf or 0), CONF_REFLEXE)
        elif typ in REFLEXE:
            etage, motif = "CORTICAL", "reversible mais confiance %.2f < %.2f" % (
                float(conf or 0), CONF_REFLEXE)
        else:
            etage, motif = "CORTICAL", "type %r non reversible ou inconnu — le defaut est le cortex" % typ
        out.append({"id": rid, "param": param, "confiance": conf, "etage": etage,
                    "action": action, "motif": motif, "raison": (reason or "")[:110]})
    return out


def appliquer(dry_run: bool | None = None) -> dict:
    """Applique l'etage REFLEXE. Desarme => plan seul, rien n'est mute.

    Sequence pour chaque acte, dans cet ordre exact :
      observable AVANT -> sante AVANT -> acte -> attente FENETRE_S -> observable APRES
      -> sante APRES -> verdict. Le veto de sante s'applique MEME si l'observable
      s'est ameliore.
    """
    dry = (not arme()) if dry_run is None else bool(dry_run)
    p = plan()
    res = {"arme": arme(), "dry_run": dry, "plan": p,
           "reflexe": len([x for x in p if x.get("etage") == "REFLEXE"]),
           "cortical": len([x for x in p if x.get("etage") == "CORTICAL"]),
           "diagnostic": len([x for x in p if x.get("etage") == "DIAGNOSTIC"]),
           "refuse": len([x for x in p if x.get("etage") == "REFUSE"]),
           "actes": []}
    if dry:
        res["note"] = ("DESARME : aucune mutation. Poser LAFORGE_APPLIER_ARMED=1 arme "
                       "l'etage reflexe UNIQUEMENT (decision owner).")
        return res

    for x in p:
        if x.get("etage") != "REFLEXE":
            continue
        action = x["action"]
        if action.get("type") == "set_param":
            res["actes"].append(_appliquer_set_param(x))
            continue
        obs_av = _observable(action)
        sante_av = _sante_globale()
        if sante_av is None:
            res["actes"].append({"id": x["id"], "fait": False,
                                 "pourquoi": "sante globale ILLISIBLE — pas de reflexe sans "
                                             "veto disponible (je ne peux pas voir != tout va bien)"})
            continue
        fait = _executer(action)
        time.sleep(FENETRE_S)
        obs_ap = _observable(action)
        sante_ap = _sante_globale()

        # DOUBLE VALIDATION PAR LE MINIMUM (revue AGY tour 3, T3.3) :
        #     credit = max(0, min(delta_mesure, libere_declare))
        # Ni la mesure seule (contaminee par les autres process) ni le declaratif seul
        # (auto-declare, donc suspect) ne font foi. Le minimum donne la propriete qui
        # compte : le declaratif ne peut que PLAFONNER la mesure, jamais la gonfler, et
        # si le RSS de la cible ne baisse pas pendant la fenetre le credit est ZERO
        # quelle que soit la promesse du reclaimer.
        mesure = None
        if obs_av.get("valeur_go") is not None and obs_ap.get("valeur_go") is not None:
            d = obs_ap["valeur_go"] - obs_av["valeur_go"]
            mesure = (-d) if obs_av["source"] == "rss_pid" else d
        declare = fait.get("auto_declare_go")
        if mesure is None and declare is None:
            gagne = None                      # rien de mesurable : trois etats
        elif mesure is None:
            # Declaratif SEUL : on ne l'accepte pas comme un gain, on le plafonne a 0.
            # « Je ne peux pas voir » ne devient jamais « ca a marche ».
            gagne = 0.0
        elif declare is None:
            gagne = mesure
        else:
            gagne = max(0.0, min(float(mesure), float(declare)))

        chute = None
        if sante_ap is not None and sante_av:
            chute = (sante_av - sante_ap) / abs(sante_av) * 100.0

        veto = bool(chute is not None and chute > VETO_CHUTE_PCT)
        succes = bool(fait.get("ok")) and (gagne is None or gagne > 0) and not veto
        _marquer(x["id"], "forge_proposal_applier", rolled_back=not succes)
        res["actes"].append({
            "id": x["id"], "fait": bool(fait.get("ok")), "succes": succes,
            "veto_sante": veto, "chute_sante_pct": None if chute is None else round(chute, 1),
            "observable": obs_av.get("source"), "contamine": obs_av.get("contamine", False),
            "gain_go": None if gagne is None else round(gagne, 3),
            "gain_mesure_go": None if mesure is None else round(float(mesure), 3),
            "auto_declare_go": declare,
            "formule": "max(0, min(mesure, declare))",
            "detail": fait.get("detail"),
        })
    return res


def _appliquer_set_param(x: dict) -> dict:
    """Un `set_param` REFLEXE : la boucle complete passe par le CONTROLEUR de mutation.

    L'applicateur pose et sait defaire ; le controleur relit la porte juste avant l'acte,
    mesure avant et apres sur la MESURE DECLAREE, garde ou revient en arriere, et le
    PROUVE (empreinte L1 egale a celle d'avant ET mesure revenue dans la bande). Le
    marquage `rolled_back_at` suit le verdict du controleur, pas l'absence d'erreur.
    """
    from nokido_agent.app.forge_mutation_controller import appliquer_et_mesurer

    action = dict(x["action"])
    nom = action["param"]
    trace: dict = {}

    def _appliquer():
        trace.update(_set_param(action))
        return trace

    def _reverter():
        return _restaurer_param(trace) if trace.get("ok") else {"ok": False,
                                                                  "detail": "rien a defaire"}

    r = appliquer_et_mesurer(
        niveau="L1", cible="param:%s" % nom, exp_id=action.get("exp_id"),
        # Resolue A L'APPEL : une mesure introuvable echoue DANS le controleur (qui s'abstient
        # alors d'appliquer), au lieu d'interrompre la boucle de l'applicateur.
        appliquer=_appliquer, reverter=_reverter, mesurer=lambda: _mesure_declaree(nom)(),
        empreinte=empreinte_l1, bruit=dict(PARAMS_L1[nom].get("bruit") or {}))
    applique = bool(r.get("applique"))
    if applique:
        _marquer(x["id"], "forge_proposal_applier", rolled_back=r.get("verdict") != "CONSERVE")
    return {"id": x["id"], "fait": applique, "succes": r.get("verdict") == "CONSERVE",
            "niveau": "L1", "param": nom, "verdict": r.get("verdict"),
            "exp_id": r.get("exp_id"), "preuve": r.get("preuve"), "frein": r.get("frein")}


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Applicateur deux etages (reflexe / cortical).")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--appliquer", action="store_true",
                    help="tenter l'etage reflexe (sans effet si non arme)")
    args = ap.parse_args(argv)

    r = appliquer(dry_run=None if args.appliquer else True)
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        return 0
    print("APPLICATEUR — arme=%s  dry_run=%s" % (r["arme"], r["dry_run"]))
    print("=" * 92)
    print("reflexe=%d  cortical=%d  diagnostic=%d"
          % (r["reflexe"], r["cortical"], r["diagnostic"]))
    print("-" * 92)
    for x in r["plan"]:
        if x.get("erreur"):
            print("  ERREUR :", x["erreur"]); continue
        print("  #%-4s %-10s %-30s conf=%-5s %s"
              % (x["id"], x["etage"], str(x["param"])[:30], x["confiance"], x["motif"][:38]))
    if r.get("note"):
        print("\n" + r["note"])
    for a in r["actes"]:
        print("  acte #%s fait=%s succes=%s veto=%s gain=%s Go (obs %s%s)"
              % (a["id"], a["fait"], a.get("succes"), a.get("veto_sante"),
                 a.get("gain_go"), a.get("observable"),
                 ", CONTAMINE" if a.get("contamine") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
