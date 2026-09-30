"""app/forge_circadian.py - rythme circadien Nokido (homeostasie, autopoiese).

Inspiration biomimetique : le corps humain regule ses fonctions cognitives
par horloge interne (noyau suprachiasmatique du hypothalamus). Cortisol
au reveil, melatonine au crepuscule, glymphatique nettoyage en REM,
hippocampe consolidation en sommeil profond. Nokido applique la meme
discipline a ses daemons : chacun a une fenetre PHYSIOLOGIQUE optimale.

Cartographie Nokido -> corps :

  06:00 - AURORE (cortisol)        : reveil services critiques (hub, brain_worker)
                                     forge_health_diagnostic + ping_monitor
  09:00 - PIC JOUR (eveil cortical): plein regime agentique
                                     handle_task_result + ingest + mpc_live
  18:00 - CREPUSCULE (melatonine)  : ralentissement, traitement queue
                                     forge_auto_compact (DELETE chunks vieux)
  22:00 - SOMMEIL LEGER (NREM-1)   : consolidation hippocampe
                                     forge_memory_consolidator cycle
  02:00 - SOMMEIL PROFOND (NREM-3) : replay batch (offline learning)
                                     forge_offline_trainer cycle complet
  04:00 - REM (reve, glymphatique) : nettoyage + reorganisation
                                     forge_auto_evolution_loop + skill_curator
                                     forge_session_anchor

Principe autopoietique : chaque phase declenche les daemons appropries
+ verifie heartbeat de la phase precedente. Si une fonction physiologique
manque (ex : pas de consolidation NREM-1), un signal "dette de sommeil"
declenche un rattrapage prioritaire au prochain cycle.

Module standalone : utilise schtasks Windows ou systemd cron Linux pour
le scheduling reel. Ce fichier expose les phases + handlers ; le binding
au scheduler est dans tools/forge_circadian_runner.py (a venir).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from enum import Enum
from pathlib import Path
from typing import Callable

logger = logging.getLogger("Nokido.Circadian")


# === Phases physiologiques ====================================================


class Phase(str, Enum):
    AURORE = "AURORE"  # 06:00 reveil cortical, cortisol peak
    JOUR = "JOUR"  # 09:00-18:00 plein regime
    CREPUSCULE = "CREPUSCULE"  # 18:00 melatonine, ralentissement
    NREM1 = "NREM1"  # 22:00 consolidation hippocampe legere
    NREM3 = "NREM3"  # 02:00 sommeil profond, replay batch
    REM = "REM"  # 04:00 reve, nettoyage glymphatique


# Fenetre [start, end) en heure locale (24h)
PHASE_WINDOWS: dict[Phase, tuple[dtime, dtime]] = {
    Phase.AURORE: (dtime(6, 0), dtime(9, 0)),
    Phase.JOUR: (dtime(9, 0), dtime(18, 0)),
    Phase.CREPUSCULE: (dtime(18, 0), dtime(22, 0)),
    Phase.NREM1: (dtime(22, 0), dtime(2, 0)),  # passe minuit
    Phase.NREM3: (dtime(2, 0), dtime(4, 0)),
    Phase.REM: (dtime(4, 0), dtime(6, 0)),
}


# === Services Nokido mappes aux phases (analogie organes) ====================


@dataclass
class PhaseAction:
    """Action a executer au debut d une phase."""

    name: str  # nom physiologique (cortisol_release, ...)
    service: str | None  # nom du service supervisor Nokido a (re)start
    handler: Callable[[], dict] | None = None  # ou un handler Python direct
    organ: str = ""  # organe biomimetique correspondant
    why: str = ""  # raison physiologique


def _mesurer_couverture_pour_phase() -> dict:
    """Indirection testable : la mesure des deux metriques de couverture."""
    from nokido_agent.tools.forge_couverture_perimetre import mesurer_couverture

    return mesurer_couverture()


def _generer_appui_pour_phase(cibles) -> dict:
    """Indirection testable : la generation des tests d'appui manquants."""
    from nokido_agent.tools.forge_generer_appui import generer

    return generer(cibles, appliquer=True)


# Combien de modules on instrumente par nuit. Borne volontaire : chaque cible coute
# un import en sous-processus, et un lot illimite ferait deborder la fenetre de phase.
_APPUI_PAR_NUIT = 40


def _regenerer_perimetre_mesure() -> dict:
    """Rafraichit la couverture de mesure et instrumente les modules qui n'en ont pas.

    POURQUOI ICI. Sans passage periodique, la couverture est une PHOTO DATEE : un
    module repare, ou simplement ecrit apres coup, resterait sans perimetre, et
    `forge_mutation_judge.juger_module_avec_gain` continuerait a rendre
    GAIN_INDECIDABLE sur lui sans que personne ne le sache. C'est le motif deja paye
    deux fois : un garde branche sur un signal que PERSONNE n'emet. Meme raison que
    l'audit de conformite pose juste au-dessus le 2026-09-04.

    DEUX METRIQUES, jamais fusionnees (arbitrage owner 2026-09-08) : `perimetre non
    vide` peut monter par generation ; `couverture prouvee` ne monte que par du test
    ecrit a la main. Aucun agregat n'est rendu — ce serait la cible que Goodhart vise.

    Best-effort mais JAMAIS muet : la mesure est en lecture seule et passe sous tout
    compte ; l'ecriture dans `tests/nr/` est ACL-fermee aux comptes de service, donc
    un refus est NOMME avec son chemin de reprise, comme le fait le registre de
    vitalite. Un handler qui echouerait en silence ferait croire a une regeneration
    qui n'a jamais lieu.
    """
    try:
        m = _mesurer_couverture_pour_phase()
    except Exception as e:  # noqa: BLE001 — une action de phase n'emporte pas les suivantes
        return {"ok": False, "motif": "%s: %s" % (type(e).__name__, str(e)[:200]),
                "etape": "mesure"}

    out = {
        "ok": True,
        "denominateur": m.get("denominateur"),
        "perimetre_non_vide": m.get("perimetre_non_vide", {}).get("n"),
        "couverture_prouvee": m.get("couverture_prouvee", {}).get("n"),
        "sans_perimetre": len(m.get("sans_perimetre", [])),
    }
    cibles = list(m.get("sans_perimetre", []))[:_APPUI_PAR_NUIT]
    if not cibles:
        out["generation"] = "RIEN_A_FAIRE"
        out["generes"] = 0
        return out
    try:
        g = _generer_appui_pour_phase(cibles)
    except PermissionError as e:
        out["generation"] = "REFUSEE"
        out["motif"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        out["remede"] = ("tests/nr est ACL-ferme aux comptes de service : rejouer par "
                         "`run action=trusted_script path=tools/forge_generer_appui.py "
                         "script_args=\"--apply\"`")
        return out
    except Exception as e:  # noqa: BLE001
        out["generation"] = "ECHEC"
        out["motif"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        return out
    out["generation"] = "OK"
    out["generes"] = len(g.get("ecrits", []))
    out["non_importables"] = len(g.get("non_importables", {}))
    return out


def _verifier_conformite_normative() -> dict:
    """Rejoue l'audit de conformite NPSC — pendant le sommeil leger.

    Pose ici le 2026-09-04 apres un constat mesure : le moteur de conformite
    est ne le matin meme et n'avait tourne QUE parce que je le lancais a la
    main, huit fois. Entre 08:34 et 14:06 il n'a pas tourne une seule fois,
    pendant que le corps produisait 121 rapports de sante. Un audit qui depend
    d'un agent pour s'executer n'est pas une capacite du systeme.

    Ce que ce handler rend visible et que rien d'autre ne surveille : une
    surface protocolaire NEUVE (un `import websockets`, un `prefer_grpc=True`)
    rend applicable une norme que personne n'a instruite, et une exigence deja
    satisfaite peut cesser de l'etre au detour d'un correctif.

    Memes gardes que la reconstruction FTS, pour les memes raisons mesurees :
    etre APPELE n'est pas etre en situation, et une tache de production ne part
    jamais d'un harnais de test.
    """
    import os as _os
    import sys as _sy
    from pathlib import Path as _P

    if _os.environ.get("PYTEST_CURRENT_TEST"):
        return {"npsc": "sous pytest",
                "pourquoi": "tache de production non declenchee depuis un test"}
    if current_phase() is not Phase.NREM1:
        return {"npsc": "hors phase", "phase": current_phase().value,
                "attendu": Phase.NREM1.value}

    _racine = _P(__file__).resolve().parent.parent
    _outils = str(_racine / "tools")
    if _outils not in _sy.path:
        _sy.path.insert(0, _outils)
    try:
        from nokido_agent.tools.forge_npsc import charger_registre, evaluer
        from nokido_agent.tools.forge_npsc_scan import inventorier, sauver_inventaire
    except Exception as exc:
        # Le moteur absent est un fait a DIRE, pas un silence : sans lui, plus
        # personne ne mesure la conformite, et le rapport de sante resterait muet.
        return {"npsc": "moteur indisponible", "erreur": "%s: %s" % (type(exc).__name__, exc)}

    try:
        registre, err = charger_registre()
        if registre is None:
            return {"npsc": "NO_VERDICT", "erreur": err}
        surfaces, diag = inventorier(registre, _racine)
        sauver_inventaire(surfaces, diag)
        lignes = evaluer(registre, surfaces, diag, racine=_racine)
    except Exception as exc:
        return {"npsc": "echec", "erreur": "%s: %s" % (type(exc).__name__, exc)}

    compte: dict = {}
    for ligne in lignes:
        compte[ligne["verdict"]] = compte.get(ligne["verdict"], 0) + 1
    violations = [l["standard"] for l in lignes if l["verdict"] == "VIOLATION"]
    sans_verdict = [l["standard"] for l in lignes if l["verdict"] == "NO_VERDICT"]
    prouvees = sum(1 for m in surfaces.values() if m.get("etat") == "PROVEN")
    resultat = {
        "npsc": "OK", "surfaces_prouvees": prouvees, "verdicts": compte,
        "instrument_ok": diag.get("instrument_ok"),
    }
    # Une violation ou une absence de verdict ne se noient pas dans un compteur :
    # elles sont NOMMEES, sinon personne ne saura laquelle instruire.
    if violations:
        resultat["VIOLATIONS"] = violations
    if sans_verdict:
        resultat["NON_MESURES"] = sans_verdict
    return resultat


def _mesurer_dependances_vulnerables(hist=None, lanceur=None) -> dict:
    """Relance la mesure `pip-audit` — DEPORTEE, parce qu'elle exige l'egress.

    `hist` et `lanceur` ne servent qu'aux tests : sans eux, un NR lirait le VRAI
    historique, dont l'age change chaque jour — le test passerait aujourd'hui et
    changerait de verdict dans trois jours. Un test qui lit un artefact de
    production n'est pas un test (paye le 2026-09-16 sur le registre de
    vitalite, ou la fixture ne patchait qu'une des deux sources).

    MESURE QUI L'IMPOSE (2026-09-17). Le gate `pip-audit` ne mesure pas : il
    JUGE la fraicheur d'un rapport depose dans `sandbox/pip_audit_history/`
    (TTL 7 j). Or ce rapport n'avait AUCUN producteur declare — ni service, ni
    tache planifiee, ni workflow. Trois fichiers en dix jours (07/09, 09/09,
    16/09), chacun produit parce qu'un agent y a pense ; entre le 09/09 et le
    16/09 il s'est ecoule exactement 7 jours, soit le TTL. Sans un passage
    manuel la veille, le suppleant serait perime aujourd'hui et un domaine
    CRITIQUE n'aurait plus aucune mesure, sans que rien ne le signale.

    C'est le motif « un garde branche sur un signal que personne n'emet » :
    consommateur present, emetteur absent.

    POURQUOI UN JOB ET PAS UN APPEL DIRECT. `pypi.org` est refuse depuis un
    compte sans egress. Mesure du 2026-09-17, meme machine, meme instant :
    `laforgesbxoffline` rend HTTP 000 en 0,03 s — un refus LOCAL immediat, pas
    un timeout — la ou `laforgesbxonline` rend HTTP 200 en 0,33 s. C'est donc
    `DISABLED_BY_POLICY`, jamais `RESOURCE_UNAVAILABLE` : installer l'outil n'y
    changerait rien, il tourne. Le seul chemin qui obtient l'egress est
    `launch_job(online=True)`.

    Ce handler rend REQUESTED, jamais ACHIEVED : lancer un job prouve le SPAWN,
    pas l'execution. Le verdict reste celui du rapport, lu par le gate.
    """
    import os as _os
    import time as _t
    from datetime import date as _date
    from pathlib import Path as _P

    if _os.environ.get("PYTEST_CURRENT_TEST"):
        return {"pip_audit": "sous pytest",
                "pourquoi": "tache de production non declenchee depuis un test"}
    if current_phase() is not Phase.NREM1:
        return {"pip_audit": "hors phase", "phase": current_phase().value,
                "attendu": Phase.NREM1.value}

    _racine = _P(__file__).resolve().parent.parent
    if hist is None:
        _hist = _racine / "sandbox" / "pip_audit_history"
    elif isinstance(hist, str):
        _hist = _P(hist)
    else:
        _hist = hist        # Path deja construit, ou double de test
    # Ne pas POMPER : un rapport frais n'a pas besoin d'etre refait chaque nuit.
    # Le seuil est sous le TTL du gate (7 j), pour qu'une nuit ratee ne suffise
    # pas a perimer le suppleant.
    try:
        _ages = sorted((_t.time() - f.stat().st_mtime) / 86400.0
                       for f in _hist.glob("pip_audit_*.json"))
    except OSError as exc:
        return {"pip_audit": "historique ILLISIBLE",
                "erreur": "%s: %s" % (type(exc).__name__, exc)}
    if _ages and _ages[0] < 3.0:
        return {"pip_audit": "frais", "age_j": round(_ages[0], 2),
                "pourquoi": "sous le seuil de 3 j — relancer serait du pompage"}

    launch_job = lanceur
    if launch_job is None:
        try:
            from nokido_agent.app.forge_job_runner import launch_job
        except Exception as exc:
            # Un producteur qu'on ne peut pas lancer est un fait a DIRE : sans
            # lui le suppleant se perime, et le gate criera ANERGIQUE sans cause.
            return {"pip_audit": "lanceur indisponible",
                    "erreur": "%s: %s" % (type(exc).__name__, exc)}
    # ⚠️ LE PRODUCTEUR ET LE CONSOMMATEUR NE VISAIENT PAS LE MEME DOSSIER
    # (mesure 2026-09-17, prise en forcant ce job a la main). Par defaut le
    # script ecrit `sandbox/pip_audit_<date>.json` -- volontairement, car c'est
    # la que `forge_deps_reconcilier.rapport_courant()` cherche. Mais le GATE,
    # lui, lit `sandbox/pip_audit_history/`. Sans `--sortie`, ce handler aurait
    # donc produit chaque nuit un rapport que personne ne lit : un mecanisme
    # present, un effet nul. Et `sandbox/*.json` est gitignore, donc le rapport
    # aurait ete invisible d'un worktree detache par-dessus le marche.
    # Deux consommateurs, deux conventions, un seul producteur : on vise
    # EXPLICITEMENT le dossier versionne que le gate lit.
    _cible = "sandbox/pip_audit_history/pip_audit_%s.json" % _date.today().isoformat()
    try:
        res = launch_job("tools/forge_pip_audit_mesure.py", online=True,
                         lane="audit", script_args="--sortie %s" % _cible)
    except Exception as exc:
        return {"pip_audit": "lancement refuse",
                "erreur": "%s: %s" % (type(exc).__name__, exc)}
    return {"pip_audit": "REQUESTED",
            "job": (res or {}).get("job_id"),
            "cible": _cible,
            "age_rapport_le_plus_frais_j": round(_ages[0], 2) if _ages else None,
            "pourquoi": "REQUESTED != ACHIEVED — le verdict reste celui du "
                        "rapport, juge par le gate a la prochaine CI"}


def _reconstruire_index_fts() -> dict:
    """Reconstruit `rag_fts` — UNIQUEMENT pendant le sommeil profond.

    Consigne owner : les reconstructions appartiennent aux cycles de repos du
    corps. Lancee de jour le 2026-08-14, celle-ci a tenu le verrou 30 minutes
    sans finir (1,15 M lignes) pendant que le systeme travaillait.

    Le handler est pose ICI, dans `forge_circadian`, et non dans
    `forge_circadian_loop` : ce dernier definit un joli cycle en quatre phases
    que PERSONNE n'appelle (verifie — aucun appelant hors de son fichier). Le
    programme reellement execute est `PHASE_PROGRAM`, et c'est `circadian_state`
    qui le prouve, avec ses phases horodatees. Cabler dans la belle boucle
    morte aurait produit un garde de plus qui ne garde rien.

    Deux refus explicites, jamais silencieux :
      * une ingestion qui ecrit -> report (un rebuild lui ferait perdre ses
        ecritures, source perdue le 2026-07-25) ;
      * une derive inferieure au seuil -> inutile, on ne refait pas des heures
        de travail chaque nuit pour un index deja sain.
    """
    import sqlite3 as _s
    import sys as _sy
    from pathlib import Path as _P

    # GARDE D'HORAIRE, et il n'est pas theorique : le test existant
    # `test_fire_phase_invokes_restart_for_services` appelle `fire_phase(NREM3)`
    # et declenchait donc une reconstruction de 1,15 M lignes A CHAQUE PASSAGE
    # DE LA CI (constate 2026-08-15). Une action lourde attachee a une phase
    # doit verifier qu'elle est REELLEMENT dans cette phase : etre appelee n'est
    # pas etre en situation. Sans cela, tout appelant — test, sonde, curiosite —
    # declenche des heures de travail.
    import os as _os

    # Garde de CONTEXTE, complementaire de l'horaire. La CI a tourne a 02h07,
    # DANS la fenetre NREM3 : le garde d'horaire etait donc satisfait et le test
    # `test_fire_phase_invokes_restart_for_services` a relance une vraie
    # reconstruction de 1,15 M lignes. Une tache de production ne doit jamais
    # partir d'un harnais de test, quelle que soit l'heure — la CI passe a
    # n'importe quelle heure, et c'est elle qui doit s'adapter, pas l'inverse.
    if _os.environ.get("PYTEST_CURRENT_TEST"):
        return {"fts": "sous pytest", "pourquoi": "tache de production non "
                "declenchee depuis un test"}
    if current_phase() is not Phase.NREM3:
        return {"fts": "hors phase", "phase": current_phase().value,
                "attendu": Phase.NREM3.value}

    _racine = _P(__file__).resolve().parent.parent
    _sy.path.insert(0, str(_racine / "tools"))
    try:
        with _s.connect(f"file:{_racine / 'RAG' / 'embeddings.db'}?mode=ro",
                        uri=True, timeout=10) as _c:
            _src = _c.execute("SELECT count(*) FROM rag_chunks").fetchone()[0]
            _idx = _c.execute("SELECT count(*) FROM rag_fts_docsize").fetchone()[0]
            _idx_moteur = _c.execute(
                "SELECT count(*) FROM rag_chunks_fts_docsize").fetchone()[0]
    except Exception as e:  # noqa: BLE001
        return {"fts": "INDETERMINE", "pourquoi": f"{type(e).__name__}: {str(e)[:90]}"}

    # L'INDEX QUI SERT LES LECTURES PASSE EN PREMIER (mesure 2026-08-23).
    # Deux index lexicaux coexistent et la maintenance n'entretenait que l'autre :
    # `rebuild_fts_index` (rag_fts) est appelee ici, par forge_mcp_registry et par
    # forge_self_correction, tandis que `rebuild_chunks_fts_index` (rag_chunks_fts,
    # celui que `forge_rag_engine._lexical()` interroge) n'avait AUCUN appelant.
    # Le remede existait, il fonctionnait, et rien ne le declenchait : lance a la
    # main le 2026-08-23 il a ramene 600 orphelins a 0 et fait passer un terme
    # temoin de 2 a 66 correspondances. Un organe repare une derive qu'il ne
    # mesure pas seulement s'il est REVEILLE pour le faire.
    # A noter : les deux derivent en sens OPPOSES — rag_fts accumule des fantomes
    # (references vers des lignes disparues, que sa reconstruction ne nettoie pas,
    # faute de jointure), rag_chunks_fts accumule des MANQUANTS. Meme seuil absolu
    # de 20 000, pour la meme raison qu'en dessous : un seuil en pourcentage
    # laisserait passer 36 000 references mortes comme negligeables.
    ecart_moteur = abs(_idx_moteur - _src)
    if ecart_moteur > 20_000:
        try:
            from nokido_agent.tools.forge_fts_repair import ingestion_active

            _actifs = ingestion_active()
            if _actifs:
                return {"fts": "reporte", "index": "rag_chunks_fts",
                        "ingestion_active": len(_actifs), "ecart": ecart_moteur}
            from nokido_agent.app.forge_self_correction import rebuild_chunks_fts_index

            logger.info("[circadian] rag_chunks_fts derive de %d lignes - "
                        "reconstruction de l'index qui sert les lectures",
                        ecart_moteur)
            return {"fts": "reconstruit", "index": "rag_chunks_fts",
                    "ecart_avant": ecart_moteur,
                    "detail": rebuild_chunks_fts_index(verbeux=False)}
        except Exception as e:  # noqa: BLE001
            logger.error("[circadian] reconstruction rag_chunks_fts impossible : "
                         "%s: %s", type(e).__name__, str(e)[:140])
            return {"fts": "ECHEC", "index": "rag_chunks_fts",
                    "pourquoi": f"{type(e).__name__}: {str(e)[:90]}"}

    # LA FUITE LEXICALE SE COLMATE A CHAQUE PASSE, PAS UNE FOIS (2026-08-23).
    # Supprimer un chunk de rag_chunks ne supprime pas son entree dans rag_fts :
    # l'index est autonome, personne ne le previent. La fuite avait accumule
    # 501 255 entrees mortes, soit 27 % de l'index, ce qui faussait les frequences
    # documentaires de BM25 et degradait le classement de TOUTES les recherches.
    # Le stock a ete purge ce jour-la ; sans cette passe, il repart exactement
    # pareil. On applique la meme retenue qu'en dessous : si une ingestion tourne,
    # on reporte plutot que de travailler contre elle.
    try:
        from nokido_agent.tools.forge_fts_repair import ingestion_active

        if ingestion_active():
            _purge = {"reporte": "ingestion active"}
        else:
            from nokido_agent.app.forge_self_correction import purge_rag_fts_fantomes

            _purge = purge_rag_fts_fantomes(verbeux=False)
    except Exception as e:  # noqa: BLE001
        logger.error("[circadian] purge des fantomes lexicaux impossible : %s: %s",
                     type(e).__name__, str(e)[:140])
        _purge = {"ok": False, "pourquoi": f"{type(e).__name__}: {str(e)[:90]}"}

    ecart = abs(_idx - _src)
    # Seuil ABSOLU : mesure du 2026-08-14 — 1 186 356 entrees pour 1 150 407
    # chunks, soit 35 949 fantomes (3,1 %). Un seuil en pourcentage aurait
    # laisse passer 36 000 references mortes comme negligeables.
    if ecart <= 20_000:
        return {"fts": "a jour", "ecart": ecart, "purge_fantomes": _purge}
    try:
        from nokido_agent.tools.forge_fts_repair import ingestion_active

        actifs = ingestion_active()
        if actifs:
            return {"fts": "reporte", "ingestion_active": len(actifs), "ecart": ecart,
                    "purge_fantomes": _purge}
        from nokido_agent.app.forge_self_correction import rebuild_fts_index

        logger.info("[circadian] rag_fts derive de %d lignes — reconstruction", ecart)
        return {"fts": "reconstruit", "ecart_avant": ecart,
                "detail": rebuild_fts_index(), "purge_fantomes": _purge}
    except Exception as e:  # noqa: BLE001
        logger.error("[circadian] reconstruction FTS impossible : %s: %s",
                     type(e).__name__, str(e)[:140])
        return {"fts": "ECHEC", "pourquoi": f"{type(e).__name__}: {str(e)[:90]}"}


def _rafraichir_snapshot_memoire() -> dict:
    """Recalcule `sandbox/memory_availability_snapshot.json`.

    POURQUOI ICI. `forge_resource_manager` LIT ce snapshot pour arbitrer les
    evictions (couper ou non un service de plusieurs Go). Passe son seuil de
    peremption (26 h) il rend `pending = -1`, c'est-a-dire INCONNU, et le
    regulateur decide a l'aveugle.

    Mesure 2026-09-04 : le snapshot datait de **28 h** (101 001 s) et
    `forge_memory_snapshot_refresh` n'etait cite par AUCUN module, declare dans
    AUCUN `services.toml`. Producteur ecrit, jamais lance — le consommateur,
    lui, tournait. C'est le motif « garde branche sur un signal que personne
    n'emet », pris du cote de l'emetteur.

    Ce que le snapshot apporte et qu'aucun raccourci ne remplace : le backlog
    REEL de vectorisation (109 053) contre les 735 699 que rendrait
    `embedding IS NULL` — 6,7x trop, parce que 626 646 chunks sont REFUSED par
    politique et n'attendent rien.

    ~92 s : tache de sommeil, jamais de chemin chaud.
    """
    # APPEL DIRECT, jamais de sous-processus : `subprocess.Popen` est REFUSE par
    # le WORKSPACE_GUARD en zone restreinte (mesure 2026-09-04 — le handler y
    # rendait « ECHEC: subprocess.Popen interdit »). Le module cible n'importe
    # que `sys` et `time` : rien ne justifiait un processus separe.
    import sys as _sys
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parent.parent
    outils = str(racine / "tools")
    if outils not in _sys.path:
        _sys.path.insert(0, outils)
    try:
        from nokido_agent.tools.forge_memory_snapshot_refresh import main as _refresh
    except ImportError as e:
        return {"snapshot": "ABSENT", "pourquoi": "%s: %s" % (type(e).__name__, e)}
    try:
        rc = _refresh()
    except Exception as e:  # noqa: BLE001
        # On DIT l'echec : un snapshot muet fait arbitrer le regulateur a l'aveugle.
        logger.warning("[circadian] snapshot memoire NON rafraichi (%s: %s)",
                       type(e).__name__, str(e)[:140])
        return {"snapshot": "ECHEC", "pourquoi": "%s: %s" % (type(e).__name__, str(e)[:120])}
    # Le verdict se lit sur l'ARTEFACT, jamais sur le code de retour.
    snap = racine / "sandbox" / "memory_availability_snapshot.json"
    try:
        # `time`, pas `_time` : le module importe `time`. Un alias inexistant ne
        # leve qu'a l'EXECUTION, invisible au compile() — c'est ce qui a tue
        # l'observateur du hub 12 h le 2026-09-03, avale par son propre except.
        age_s = int(time.time() - snap.stat().st_mtime)
    except OSError:
        return {"snapshot": "NON ECRIT", "rc": rc}
    return {"snapshot": "a jour" if age_s < 300 else "SUSPECT",
            "age_s": age_s, "rc": rc}


PHASE_PROGRAM: dict[Phase, list[PhaseAction]] = {
    Phase.AURORE: [
        PhaseAction(
            "cortisol_release", "NokidoWatchdog", organ="surrenales", why="reveil cortical, services critiques up"
        ),
        PhaseAction("hub_alive_check", None, organ="cortex_prefrontal", why="verifier hub :8766 + brain_worker :5557"),
    ],
    Phase.JOUR: [
        PhaseAction(
            "ingest_loop", "NokidoIngestDaemon", organ="estomac", why="absorption documents, ingest URL/files"
        ),
        PhaseAction("mpc_active", None, organ="cortex_moteur", why="boucle MPC active pour decisions temps reel"),
        PhaseAction(
            "agentic_workload", "NokidoAutonomousLoops", organ="cortex_associatif", why="agents traitent task queue"
        ),
    ],
    Phase.CREPUSCULE: [
        PhaseAction("melatonin_release", None, organ="pineale", why="signal preparation sommeil"),
        # RETIRE LE 2026-09-21 -- decision owner, option B.
        #
        # `PhaseAction("rag_compaction", "NokidoAutoCompact", organ="rein")`
        # reveillait ce service chaque CREPUSCULE alors qu'il n'etait declare
        # dans AUCUN services.toml : 7 des 8 services du programme l'etaient,
        # lui seul manquait. Le superviseur repondait « service non declare
        # dans services.toml » et `supervisor.ts` le CONSTATAIT en commentaire
        # depuis le cutover du 2026-07-09 sans jamais le solder.
        #
        # CE QUI A TRANCHE : `tools/forge_auto_compact.py` fait un
        # `DELETE FROM rag_chunks` sur `RAG/embeddings.db`, la base de 25 Go --
        # operation que le module qualifie lui-meme d'IRREVERSIBLE. Declarer le
        # service aurait ajoute un ecrivain AUTOMATIQUE et QUOTIDIEN au verrou
        # RAG, a rebours du P0 du 2026-09-19 dont le critere est que cette base
        # CESSE de recevoir.
        #
        # L'OUTIL N'EST PAS SUPPRIME : il reste invocable a la main, avec son
        # `--dry-run` qui ne mute rien. On retire un DECLENCHEMENT, pas une
        # capacite. Le jumeau `proxy_deno/core/supervisor.ts` -- celui qui
        # S'EXECUTE -- a ete retire dans le meme commit ; corriger le seul
        # Python aurait ete un correctif applique au jumeau mort.
    ],
    Phase.NREM1: [
        PhaseAction(
            "memory_consolidation",
            "NokidoMemoryConsolidator",
            organ="hippocampe",
            why="distillation traces high-value -> experiences narratives",
        ),
        PhaseAction(
            "memory_snapshot_refresh",
            None,
            handler=_rafraichir_snapshot_memoire,
            organ="hippocampe",
            why="le regulateur arbitre les evictions sur ce snapshot ; perime "
                "(>26 h) il rend INCONNU et decide a l'aveugle",
        ),
        PhaseAction(
            "regeneration_perimetre_mesure",
            None,
            handler=_regenerer_perimetre_mesure,
            organ="systeme_immunitaire",
            why="sans passage periodique la couverture de mesure est une photo datee : "
                "un module repare ou neuf reste sans perimetre, et le juge a gain ne "
                "peut rendre que GAIN_INDECIDABLE sur lui, en silence",
        ),
        PhaseAction(
            "conformite_normative",
            None,
            handler=_verifier_conformite_normative,
            organ="systeme_immunitaire",
            why="une surface protocolaire neuve rend applicable une norme que "
                "personne n'a instruite ; sans passage periodique l'audit ne "
                "tourne que si un agent y pense",
        ),
        PhaseAction(
            "audit_dependances",
            None,
            handler=_mesurer_dependances_vulnerables,
            organ="systeme_immunitaire",
            why="le gate `pip-audit` (domaine CRITIQUE) ne mesure pas lui-meme : "
                "il JUGE la fraicheur d'un rapport deporte, dont le producteur "
                "n'etait declare NULLE PART. Trois rapports en dix jours, "
                "chacun produit parce qu'un agent y pensait, et un TTL de 7 j "
                "frole le 2026-09-16 : sans passage periodique, un domaine "
                "critique se retrouve sans aucune mesure, en silence",
        ),
    ],
    Phase.NREM3: [
        PhaseAction(
            "offline_replay",
            "NokidoOfflineTrainer",
            organ="cortex_visuel_v1",  # remap dorsal
            why="batch replay sur execution_traces, train 6 nets AMI",
        ),
        PhaseAction(
            "night_train", "NokidoNightTrainer", organ="cortex_temporal", why="LoRA fine-tune des modeles locaux"
        ),
        PhaseAction(
            "fts_rebuild",
            None,
            handler=_reconstruire_index_fts,
            organ="hippocampe",
            why="resynchronise rag_fts et purge les entrees dont le chunk est mort",
        ),
    ],
    Phase.REM: [
        PhaseAction(
            "glymphatic_clearance",
            "NokidoSelfPatcher",
            organ="systeme_glymphatique",
            why="nettoyage : detecte+patch lessons recurrentes",
        ),
        PhaseAction(
            "session_anchor",
            None,
            organ="cortex_prefrontal_medial",
            why="anchor solutions session vers RAG, append lessons.md",
        ),
        PhaseAction(
            "auto_evolution",
            "NokidoAutonomousLoops",
            organ="systeme_immunitaire_b",
            why="scan heartbeats, restart degrades, proposals",
        ),
    ],
}


# === Detection de phase courante ==============================================


def current_phase(now: datetime | None = None) -> Phase:
    """Retourne la phase physiologique active a l instant donne."""
    now = now or datetime.now()
    t = now.time()
    for phase, (start, end) in PHASE_WINDOWS.items():
        if start <= end:
            if start <= t < end:
                return phase
        else:  # fenetre traverse minuit (NREM1)
            if t >= start or t < end:
                return phase
    return Phase.JOUR  # fallback (ne devrait pas arriver)


# === Dette physiologique ======================================================


@dataclass
class PhysiologicalState:
    """Etat homeostatique. Chaque phase qui n a pas tourne = dette."""

    last_completed: dict[Phase, float] = field(default_factory=dict)

    def mark_completed(self, phase: Phase) -> None:
        self.last_completed[phase] = time.time()

    def debt_hours(self, phase: Phase) -> float:
        """Heures depuis derniere completion de la phase. inf si jamais."""
        last = self.last_completed.get(phase)
        if last is None:
            return float("inf")
        return (time.time() - last) / 3600.0

    def has_sleep_debt(self) -> bool:
        """True si NREM1 ou NREM3 pas tourne dans les 48h."""
        return self.debt_hours(Phase.NREM1) > 48 or self.debt_hours(Phase.NREM3) > 48


# === Phase handlers ===========================================================

SUPERVISOR_URL = "http://127.0.0.1:8765"


def _restart_service(name: str) -> dict:
    """Restart via supervisor :8765/supervisor/restart/<name>. Non-bloquant."""
    # Corrigibility (A#2): self-heal autonome respecte le verrou humain.
    #
    # ⚠️ CE `except` ETAIT MUET *ET* FAIL-OPEN (corrige le 2026-09-17). Si
    # `is_human_locked()` levait — module absent, base verrouillee, ACL — on
    # tombait dans `pass` et le redemarrage PARTAIT QUAND MEME. Autrement dit
    # le verrou humain se contournait tout seul des que son capteur cassait,
    # sans une ligne de journal pour le dire.
    #
    # Un garde de corrigibilite est FAIL-CLOSED par construction : ne pas
    # pouvoir lire le verrou n'autorise pas a agir. `UNKNOWN != NO`, et ici
    # l'inconnu doit retenir le geste, pas le permettre. Le cout des deux
    # erreurs n'est pas symetrique — un restart de trop contre un verrou humain
    # est exactement ce que ce garde existe pour empecher.
    try:
        from nokido_agent.app.forge_opsec import is_human_locked
        if is_human_locked():
            return {"ok": False, "name": name, "skipped": "human_locked"}
    except Exception as exc:  # noqa: BLE001
        logging.warning(
            "[circadien] verrou humain ILLISIBLE (%s: %s) — restart de %s REFUSE "
            "par prudence : ne pas savoir n'autorise pas a agir",
            type(exc).__name__, exc, name)
        return {"ok": False, "name": name,
                "skipped": "verrou_humain_illisible",
                "erreur": "%s: %s" % (type(exc).__name__, exc)}
    try:
        req = urllib.request.Request(f"{SUPERVISOR_URL}/supervisor/restart/{name}", method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return {"ok": True, "status": r.status, "name": name, "body": r.read().decode("utf-8", "replace")[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "name": name, "error": str(e)}


def fire_phase(phase: Phase, state: PhysiologicalState | None = None, dry_run: bool = False) -> dict:
    """Execute toutes les PhaseAction d une phase.
    dry_run=True : log seulement, n appelle pas supervisor."""
    state = state or PhysiologicalState()
    actions = PHASE_PROGRAM.get(phase, [])
    results: list[dict] = []
    logger.info(
        "[circadian] phase=%s actions=%d organes=%s",
        phase.value,
        len(actions),
        ",".join(a.organ for a in actions if a.organ),
    )
    for act in actions:
        if dry_run:
            results.append({"name": act.name, "service": act.service, "organ": act.organ, "dry_run": True})
            continue
        if act.service:
            r = _restart_service(act.service)
            r["action"] = act.name
            r["organ"] = act.organ
            results.append(r)
        elif act.handler:
            try:
                r = act.handler() or {}
                r["action"] = act.name
                r["organ"] = act.organ
                results.append(r)
            except Exception as e:  # noqa: BLE001
                results.append({"action": act.name, "error": str(e), "organ": act.organ})
        else:
            # action symbolique (juste log)
            results.append({"action": act.name, "organ": act.organ, "symbolic": True})

    # Une phase ne se solde pas parce qu'on l'a PARCOURUE, mais parce que ses actions
    # ont ABOUTI. `mark_completed` etait appele inconditionnellement : une phase dont
    # toutes les actions echouaient effacait quand meme la dette de sommeil, donc le
    # corps se croyait repose sans avoir guéri. Pire, l'appel avait lieu AUSSI en
    # `dry_run` -- une SIMULATION mutait l'etat physiologique. Un banc d'essai qui
    # modifie le patient n'est pas un banc d'essai.
    echecs = [r.get("action") for r in results
              if r.get("error") or r.get("ok") is False]
    if dry_run:
        complete = False
        motif = "dry_run : aucun effet, donc rien a solder"
    elif echecs:
        complete = False
        motif = f"{len(echecs)} action(s) en echec : {echecs}"
    else:
        complete = True
        motif = "toutes les actions ont abouti"
        state.mark_completed(phase)
    if not complete:
        logger.warning("[circadian] phase=%s NON soldee — %s (la dette est CONSERVEE)",
                       phase.value, motif)
    return {
        "phase": phase.value,
        "ts": time.time(),
        "results": results,
        "completed": complete,
        "motif": motif,
        "echecs": echecs,
        "sleep_debt": state.has_sleep_debt(),
    }


# === Persistence state ========================================================

_STATE_PATH = Path(__file__).resolve().parent.parent / "sandbox" / "circadian_state.json"


def load_state() -> PhysiologicalState:
    if not _STATE_PATH.exists():
        return PhysiologicalState()
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        st = PhysiologicalState()
        # DEUX formats, parce que le LECTEUR et l'ECRIVAIN ne parlaient pas le meme mot
        # (mesure 2026-09-08) : le fichier reel porte `last_fired`, ecrit par un autre
        # producteur, quand cette fonction ne cherchait que `last_completed`. Le dict
        # etait donc TOUJOURS vide, `debt_hours` rendait `inf` pour toute phase, et
        # `needs_recovery` etait vrai en PERMANENCE sur un corps qui dormait tres bien.
        # On ne touche pas a l'ecrivain, qu'on ne controle pas ici : on rend le lecteur
        # capable des deux formes, `last_fired` d'abord puisque c'est ce qui existe.
        brut = data.get("last_fired") or data.get("last_completed") or {}
        lu = {}
        for k, v in brut.items():
            try:
                lu[Phase(k)] = float(v)
            except (ValueError, TypeError):
                # Nom de phase retire du code : on ignore CETTE entree, pas le fichier
                # entier — sinon un seul nom perime rendrait tout l'etat illisible.
                logger.debug("[circadian] phase inconnue dans l'etat : %r", k)
        st.last_completed = lu
        return st
    except Exception:  # noqa: BLE001
        return PhysiologicalState()


def save_state(state: PhysiologicalState) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(
            json.dumps(
                {
                    "last_completed": {p.value: ts for p, ts in state.last_completed.items()},
                    "saved_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("[circadian] state save failed: %s", e)


# === CLI / runner =============================================================


def report_status() -> dict:
    """Etat courant : phase active, dettes, derniere completion par phase."""
    state = load_state()
    phase = current_phase()
    return {
        "active_phase": phase.value,
        "active_organs": [a.organ for a in PHASE_PROGRAM.get(phase, []) if a.organ],
        "sleep_debt": state.has_sleep_debt(),
        "debt_hours": {p.value: round(state.debt_hours(p), 1) for p in Phase},
        "last_completed": {p.value: state.last_completed.get(p) for p in Phase},
    }
