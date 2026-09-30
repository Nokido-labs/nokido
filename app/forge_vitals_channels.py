# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "regulation/canaux-vitaux"
CANAUX VITAUX -- source UNIQUE des grandeurs echantillonnees dans le temps.

POURQUOI CE MODULE EXISTE
=========================
Jusqu'au 2026-08-05, la serie `sandbox/vitals_history.jsonl` ne portait que des
scalaires GLOBAUX de la machine (ram/cpu/disk/gpu). Quatre bancs neuromorphiques
successifs ont perdu contre `if ram > 85` sur ce vecteur, et le verdict portait sur
le SIGNAL, pas sur l'architecture : les TENNs sont *spatio*temporels, leur force est
la correlation ENTRE canaux -- avec un seul canal utile, le seuil gagne par
construction.

Or le corps produisait DEJA les grandeurs manquantes, sans jamais les journaliser :
- `forge_service_rss_watch` reecrit son etat EN PLACE (pas de serie),
- `forge_vitals_tools` expose 13 signaux cognitifs au seul dashboard,
- psutil porte le detail (coeur sature, debits, commutations) que la moyenne masque.

Ce module est le point unique ou un canal est DEFINI. `forge_resource_manager` en
journalise le palier `serie` ; `tools/forge_vitals_channel_probe` mesure TOUS les
paliers avant d'en promouvoir un. Deux definitions du meme canal divergeraient.

CE QUI EST ENTRE, ET POURQUOI
=============================
Campagne du 2026-08-05 (10 echantillons / 191 s, 133 candidats) :
- `cmax` (coeur le plus charge) sort a un ecart-type de 20,3 pour une moyenne CPU
  plate : c'est le canal qui manquait, celui du glouton qui tient un coeur sans
  faire bouger la moyenne.
- `ior` (lecture disque) va de 0,07 a 143,5 Mo/s, `nr` (reseau recu) de 2 a 383 ko/s.
- Les ratios de derive par service viennent de l'etat deja produit a 60 s : cout
  0,35 ms, on JOINT un capteur existant, on ne le double pas.

CE QUI EST RESTE DEHORS, ET POURQUOI (ne pas le recabler sans mesurer)
=====================================================================
- `handles`/`threads` des 49 services : 350 ms par tour. Surtout, une fuite de
  handles a pour dimension la JOURNEE : une fenetre de 150 s ne peut pas la juger.
  Verdict = "non mesurable ici", PAS "inutile". Palier `sonde`.
- Signaux cognitifs (fusion parietale, metabolisme, homeostasie) : 4 709 ms en
  regime etabli, 7 350 ms a froid. Inconcevable a 15 s. Palier `sonde`.

TROIS ETATS, JAMAIS DEUX
========================
Un canal rend None quand il est ILLISIBLE (droit refuse, module absent, compteur
reinitialise), jamais 0. Un zero signifie "mesure a zero" ; confondre les deux
fabrique un faux negatif indetectable une fois dans la serie.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

_APP = os.path.dirname(os.path.abspath(__file__))
if _APP not in sys.path:
    sys.path.insert(0, _APP)

_ROOT = Path(_APP).parent
_ETAT_RSS = _ROOT / "sandbox" / "service_rss_state.json"

# Cle COURTE -> nom lisible. La serie s'ecrit 4x/minute : une cle de 20 caracteres
# repetee des centaines de milliers de fois coute des megaoctets d'historique, donc
# de la PROFONDEUR perdue pour les bancs. Le sens vit ici, pas dans le fichier.
SCHEMA = {
    "cmax": "cpu.coeur_max_pct",
    "cect": "cpu.coeur_ecart",
    "ctx": "cpu.ctx_switch_s",
    "irq": "cpu.interrupts_s",
    "np": "cpu.procs_n",
    "ior": "io.lecture_mb_s",
    "iow": "io.ecriture_mb_s",
    "nr": "net.recu_kb_s",
    "ns": "net.envoye_kb_s",
    "swp": "mem.swap_pct",
    "dbsy": "disque.occupation_pct",
    "dq": "disque.file_attente",
    "emax": "endo.niveau_max",
    "esum": "endo.niveau_somme",
    "en": "endo.actives_n",
    "s": "svc.<nom> -> [rss_go, ratio_derive]",
    "q8099": "appels.embedder_req_min",
    "q8100": "appels.reranker_req_min",
    "q8091": "appels.llama_natif_req_min",
    "q11434": "appels.ollama_req_min",
    "q8766": "appels.hub_req_min",
    # Process du HUB, joints depuis la boite noire (deja ecrite ~11 s).
    "hth": "hub.threads",
    "hhd": "hub.handles",
    "hfd": "hub.fds",
    "hrs": "hub.rss_go",
    "hcp": "hub.cpu_pct",
    # Requetes du hub : latence et volume PAR APPEL, joints depuis promcp_tool_metrics.
    "ln": "req.appels_60s",
    "lp95": "req.latence_p95_ms",
    "lmax": "req.latence_max_ms",
    "lerr": "req.echecs_pct",
    "lbi": "req.entree_kb",
    "lbo": "req.sortie_kb",
    # Bus d'evenements : ce que le corps se dit a lui-meme, par seconde.
    "bev": "bus.evts_s",
    "berr": "bus.erreurs_s",
    "bag": "bus.agents_actifs",
    # Cycle de vie, domaine GOUVERNANCE seulement (cf grp_cycle_vie).
    "lcg": "vie.gate_actions_s",
    # Journal Windows : AGE du dernier evenement d'erreur, pas son compte.
    "wse": "win.systeme_derniere_erreur_s",
    "wae": "win.application_derniere_erreur_s",
    # L'ORGANISME lui-meme. On ne compte PAS les organes qui battent : l'extinction
    # a la demande rend ce chiffre illisible. On compte les CONTRADICTIONS.
    # NE COMPTE QUE LES AFFERENCES DECLAREES. Un organe qui n'en declare aucune est
    # non innerve PAR CONCEPTION (binaire tiers, prothese) : ce n'est pas une panne.
    "ords": "organes.afference_declaree_mais_muette",
    "orsa": "organes.afference_declaree_jamais_cablee",
    "ordm": "organes.silence_le_plus_long_s",
    "ipd": "inspecteur.ports_down",
    "izo": "inspecteur.zombies",
    "cgo": "coagulation.plaies_ouvertes",
    "cga": "coagulation.derniere_s",
}

# Etat des compteurs cumulatifs entre deux appels (debits). Le sampler appelle ce
# module en boucle dans un thread unique ; la sonde passe son propre dict.
_PREV: dict = {}


def _f(x):
    """Numerique ou None. Un bool n'est pas un canal continu."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _debit(prev: dict, cle: str, cumul: float):
    """Compteur cumulatif -> debit/s. Le PREMIER appel rend None (pas de reference),
    jamais 0 : un debit inconnu n'est pas un debit nul. Un compteur qui RECULE
    (service redemarre) rend None aussi, plutot qu'un pic negatif fantome."""
    now = time.time()
    ancien = prev.get(cle)
    prev[cle] = (cumul, now)
    if not ancien:
        return None
    v0, t0 = ancien
    dt = now - t0
    if dt <= 0 or cumul < v0:
        return None
    return round((cumul - v0) / dt, 3)


# ---------------------------------------------------------------------------
# Palier `serie` : bon marche (~21 ms cumules), journalise a chaque tick.
# ---------------------------------------------------------------------------
def grp_memoire(prev: dict) -> tuple[dict, str]:
    import psutil

    # `dispo_gb` n'est PAS repris : la serie porte deja ram_free_gb. Le swap, lui,
    # dit la NATURE de la pression -- une machine qui pagine n'est pas une machine
    # qui remplit sa RAM, et aucun seuil global ne les distingue.
    #
    # MESURE 2026-08-05, et la PORTEE compte : `psutil.swap_memory()` leve
    # `RuntimeError: PdhAddEnglishCounterW failed. Performance counters may be
    # disabled.` sous le COMPTE SANDBOX (LaForgeSbxOffline), alors que sous le
    # compte du hub le meme appel rend 1,9 % sans broncher. Ce n'est donc PAS une
    # machine sans compteurs de performance, c'est un compte sans acces aux
    # compteurs -- j'avais d'abord ecrit "HS ici", ce qui aurait fait chercher une
    # panne systeme inexistante. Le canal est ILLISIBLE POUR CET APPELANT, ce qui
    # n'est pas "swap a zero" : une machine qui pagine ressemblerait au repos. On
    # rend la RAISON plutot qu'un chiffre invente.
    try:
        sw = psutil.swap_memory()
    except Exception as e:  # noqa: BLE001
        return {}, ("swap ILLISIBLE (%s: %s) -- compteurs de performance Windows "
                    "inaccessibles A CE COMPTE (mesure : le compte du hub y accede, "
                    "le compte sandbox non) ; ce n'est pas un swap a zero"
                    % (type(e).__name__, str(e)[:90]))
    return {"swp": _f(sw.percent)}, "psutil.swap_memory"


def grp_cpu(prev: dict) -> tuple[dict, str]:
    import psutil

    par_coeur = psutil.cpu_percent(percpu=True)
    st = psutil.cpu_stats()
    return ({
        "cmax": _f(max(par_coeur) if par_coeur else None),
        "cect": _f(statistics.pstdev(par_coeur) if len(par_coeur) > 1 else None),
        "ctx": _debit(prev, "ctx", st.ctx_switches),
        "irq": _debit(prev, "irq", st.interrupts),
        "np": _f(len(psutil.pids())),
    }, "psutil.cpu_percent(percpu) + cpu_stats")


def grp_io(prev: dict) -> tuple[dict, str]:
    import psutil

    d = psutil.disk_io_counters()
    n = psutil.net_io_counters()
    vals: dict = {}
    if d is not None:
        vals["ior"] = _debit(prev, "dr", d.read_bytes / 1e6)
        vals["iow"] = _debit(prev, "dw", d.write_bytes / 1e6)
    if n is not None:
        vals["nr"] = _debit(prev, "nr", n.bytes_recv / 1e3)
        vals["ns"] = _debit(prev, "ns", n.bytes_sent / 1e3)
    if not vals:
        return {}, "compteurs io indisponibles"
    return vals, "psutil.disk_io_counters + net_io_counters"


# --- Occupation du disque : le seul signal qui distingue « plein » de « saturé » ---
#
# MESURE 2026-09-05. Le regulateur ne connaissait que la RAM. L'owner a vu « ram 86 %
# ET nvme 100 % » : deux symptomes qu'aucun canal ne reliait, alors que c'est
# probablement UN phenomene -- une machine qui pagine ecrit sur le disque. Le swap
# etait justement le canal muet depuis le 2026-08-05 (`swp` ci-dessus), et pour la
# MEME cause que celle-ci : les compteurs de performance Windows sont refuses aux
# comptes de service. Corrige le 2026-09-05 en ajoutant les trois comptes au groupe
# `S-1-5-32-559` (lecture de compteurs UNIQUEMENT, aucun droit fichier ni reseau).
#
# POURQUOI PDH ET PAS `typeperf` : ce groupe vit dans le palier `serie`, ~21 ms au
# total. `typeperf` coute ~2 s (un compteur de RATIO exige deux echantillons espaces
# d'une seconde) -- il multiplierait le tick du regulateur par cent. PDH garde la
# requete OUVERTE entre les appels : mesure a 0,22 ms pour trois compteurs.
#
# ET PAS `psutil` : il n'expose aucun equivalent de `% Disk Time`. Ses `read_time` /
# `write_time` sont inutilisables sous Windows -- mesure du jour : 1 ms cumulee sur
# 2001 ms pendant que le disque lisait 87 Mo/s. Un garde branche dessus dirait
# toujours 0 %. `busy_time`, lui, est absent de la plateforme.
#
# `PdhAddEnglishCounterW` prend les noms ANGLAIS quelle que soit la langue du
# systeme. Ce point n'est pas cosmetique : sur cette machine les compteurs
# s'appellent « \Disque physique(_Total)\Pourcentage du temps disque », donc un
# chemin anglais passe en dur a `typeperf` echoue en « aucun compteur valide » --
# un echec qui se lit comme une absence de compteurs et envoie chercher une panne
# systeme qui n'existe pas.
_PDH: dict = {"query": None, "compteurs": {}, "amorce": False, "panne": ""}

_PDH_COMPTEURS = (
    ("dbsy", r"\PhysicalDisk(_Total)\% Disk Time"),
    ("dq", r"\PhysicalDisk(_Total)\Current Disk Queue Length"),
)


def _pdh_ouvrir() -> str:
    """Ouvre la requete PDH une seule fois. Rend "" si prete, sinon la RAISON."""
    if _PDH["query"] is not None or _PDH["panne"]:
        return _PDH["panne"]
    try:
        import ctypes
        import ctypes.wintypes as wt

        pdh = ctypes.WinDLL("pdh.dll")
        q = wt.HANDLE()
        rc = pdh.PdhOpenQueryW(None, 0, ctypes.byref(q)) & 0xFFFFFFFF
        if rc:
            _PDH["panne"] = "PdhOpenQueryW rc=0x%08x" % rc
            return _PDH["panne"]
        for cle, chemin in _PDH_COMPTEURS:
            h = wt.HANDLE()
            rc = pdh.PdhAddEnglishCounterW(q, chemin, 0, ctypes.byref(h)) & 0xFFFFFFFF
            if rc == 0:
                _PDH["compteurs"][cle] = h
        if not _PDH["compteurs"]:
            # Cas MESURE avant le 2026-09-05 : compteurs refuses au compte. Ce
            # n'est PAS « disque au repos », et le dire evite qu'un lecteur
            # cherche une panne materielle.
            _PDH["panne"] = ("aucun compteur PhysicalDisk ajoute -- compteurs de "
                             "performance refuses A CE COMPTE (groupe local "
                             "S-1-5-32-559) ; ce n'est pas un disque au repos")
            return _PDH["panne"]
        _PDH["pdh"], _PDH["query"] = pdh, q
        return ""
    except Exception as e:  # noqa: BLE001
        _PDH["panne"] = "%s: %s" % (type(e).__name__, str(e)[:90])
        return _PDH["panne"]


def grp_disque(prev: dict) -> tuple[dict, str]:
    panne = _pdh_ouvrir()
    if panne:
        return {}, "occupation disque ILLISIBLE (%s)" % panne
    import ctypes

    pdh, q = _PDH["pdh"], _PDH["query"]
    if pdh.PdhCollectQueryData(q) & 0xFFFFFFFF:
        return {}, "PdhCollectQueryData a echoue"
    if not _PDH["amorce"]:
        # Meme contrat que `_debit` : un ratio n'existe pas avant sa deuxieme
        # collecte. Rendre 0 ici ferait passer un disque satue pour un disque
        # au repos a chaque demarrage du regulateur.
        _PDH["amorce"] = True
        return {}, "premiere collecte (un ratio n'a pas de valeur sans reference)"

    class _Fmt(ctypes.Structure):
        _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]

    vals: dict = {}
    v = _Fmt()
    for cle, h in _PDH["compteurs"].items():
        rc = pdh.PdhGetFormattedCounterValue(h, 0x00000200, None, ctypes.byref(v)) & 0xFFFFFFFF
        if rc == 0:
            # `% Disk Time` peut DEPASSER 100 : il somme le temps de service des
            # requetes, et une file profonde en sert plusieurs a la fois. On ne
            # borne donc PAS a 100 -- ce serait ecraser precisement le signal de
            # saturation qu'on vient chercher. Deux decimales suffisent : la
            # valeur brute en portait seize, illisibles dans le journal.
            vals[cle] = _f(round(v.doubleValue, 2))
    if not vals:
        return {}, "compteurs ajoutes mais aucune valeur formatable"
    return vals, "pdh.dll PdhAddEnglishCounterW (PhysicalDisk _Total)"


def grp_endocrine(prev: dict) -> tuple[dict, str]:
    try:
        from nokido_agent.app import forge_endocrine as FE  # type: ignore

        rec = list(FE.scan())
    except Exception as e:  # noqa: BLE001
        return {}, "endocrine indisponible: %s" % type(e).__name__
    niveaux = [v for v in (_f(getattr(r, "level", None)) for r in rec) if v is not None]
    if not niveaux:
        return {"emax": None, "esum": None, "en": 0.0}, "aucune hormone active"
    return ({"emax": _f(max(niveaux)), "esum": _f(round(sum(niveaux), 4)),
             "en": _f(len(niveaux))}, "forge_endocrine.scan")


def grp_appels(prev: dict) -> tuple[dict, str]:
    """Debit de requetes par port surveille, LU depuis l'etat que forge_port_callers
    produit deja a 60 s. On joint, on ne redouble pas : `psutil.net_connections()`
    coute 50-200 ms, inconcevable au tick de 15 s.

    Ce canal repond a la question que le capteur de derive RSS ne pouvait pas
    trancher : un service qui grossit TRAVAILLE-T-IL ? Mesure du 2026-08-05 :
    l'embedder a gonfle de 2,73 a 6,07 Go sous ~50 requetes/min, puis a rendu la
    memoire des l'arret de la rafale. Sans le debit a cote du RSS, les deux courbes
    se lisaient « fuite »."""
    try:
        from nokido_agent.app import forge_port_callers as PC  # type: ignore

        vals = PC.canaux()
    except Exception as e:  # noqa: BLE001
        return {}, "compteur d'appels indisponible: %s" % type(e).__name__
    if not vals:
        return {}, "etat absent (compteur jamais passe)"
    return vals, "port_callers_state.json (%d ports)" % len(vals)


def grp_services(prev: dict) -> tuple[dict, str]:
    """Derive memoire par service NOMME, LUE depuis l'etat que forge_service_rss_watch
    produit deja a 60 s. On joint un capteur existant, on ne le redouble pas."""
    if not _ETAT_RSS.exists():
        return {}, "etat absent (capteur jamais passe)"
    try:
        etat = json.loads(_ETAT_RSS.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {}, "etat illisible: %s" % type(e).__name__
    svc: dict = {}
    for nom, e in etat.items():
        ref, cur = _f(e.get("rss_min")), _f(e.get("rss_dernier"))
        # ratio None = SANS REFERENCE (delai d'amorcage), pas "va bien".
        svc[nom] = [cur, round(cur / ref, 3) if (ref and cur) else None]
    return ({"s": svc} if svc else {}), "service_rss_state.json (%d services)" % len(etat)


# ---------------------------------------------------------------------------
# Palier `sonde` : mesure a la demande, JAMAIS dans la serie (cout ou dimension).
# ---------------------------------------------------------------------------
def grp_handles(prev: dict) -> tuple[dict, str]:
    """Handles/threads des services nommes. Pathologie que le RSS ne voit PAS : une
    fuite de handles n'augmente presque pas la memoire et finit en 'Insufficient
    system resources'. Le registre des pids vient du capteur, pas d'un nom devine."""
    try:
        import psutil

        from nokido_agent.app import forge_service_rss_watch as W  # type: ignore
    except Exception as e:  # noqa: BLE001
        return {}, "module indisponible: %s" % type(e).__name__
    try:
        registre = W._registre()
    except Exception as e:  # noqa: BLE001
        return {}, "registre superviseur illisible: %s" % type(e).__name__
    if not registre:
        return {}, "superviseur injoignable (0 service)"
    vals, refus = {}, 0
    for nom, pid in sorted(registre.items()):
        try:
            p = psutil.Process(pid)
            vals["svc.%s.handles" % nom] = _f(p.num_handles())
            vals["svc.%s.threads" % nom] = _f(p.num_threads())
        except Exception:  # noqa: BLE001
            vals["svc.%s.handles" % nom] = None  # refus != 0 handle
            vals["svc.%s.threads" % nom] = None
            refus += 1
    return vals, "%d/%d process lisibles (%d refus)" % (
        len(registre) - refus, len(registre), refus)


def grp_cognitif(prev: dict) -> tuple[dict, str]:
    """Signaux internes exposes au dashboard. MESURE 2026-08-05 : 4 709 ms en regime
    etabli -- et `nokido_vitals.js` les rappelle toutes les 5 s. Hors serie."""
    vals, notes = {}, []
    try:
        from nokido_agent.app import forge_metabolism as M  # type: ignore

        st = M.get_compute_energy_state()
        if isinstance(st, (list, tuple)) and len(st) >= 2:
            vals["cog.charge_compute"] = _f(st[1])
    except Exception as e:  # noqa: BLE001
        notes.append("metabolism:%s" % type(e).__name__)
    try:
        from nokido_agent.app import forge_homeostasis_orchestrator as H  # type: ignore

        fr = H.FlowRegulator()
        vals["cog.seuil_homeostasie"] = _f(fr.get_dynamic_threshold())
        vals["cog.facteur_endocrine"] = _f(fr._endocrine_factor())
    except Exception as e:  # noqa: BLE001
        notes.append("homeostasie:%s" % type(e).__name__)
    try:
        from nokido_agent.app import forge_parietal_fusion as P  # type: ignore

        p = P.fuse()
        vals["cog.salience"] = _f(p.get("salience"))
        vals["cog.priorite"] = _f(p.get("priority"))
    except Exception as e:  # noqa: BLE001
        notes.append("parietal:%s" % type(e).__name__)
    return vals, ("ok" if not notes else "partiel: " + ", ".join(notes))


def _derniere_ligne_json(p, fenetre_o: int = 8192):
    """Derniere ligne JSON d'un flux append-only, sans le relire en entier.

    Rend None si le fichier est absent, vide ou illisible -- jamais un dict vide,
    qui se lirait comme « mesure a zero »."""
    try:
        with open(p, "rb") as fh:
            fh.seek(0, 2)
            n = fh.tell()
            fh.seek(max(0, n - fenetre_o))
            morceaux = fh.read().splitlines()
    except Exception:  # noqa: BLE001
        return None
    for b in reversed(morceaux):
        b = b.strip()
        if not b:
            continue
        try:
            return json.loads(b.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001  # muet-ok : la fenetre lue commence au
            # milieu d'une ligne, donc la PREMIERE candidate est tronquee par
            # construction. Journaliser ce cas attendu, 4 fois par minute, noierait
            # les vraies pannes. On remonte au-dessus jusqu'a une ligne entiere ;
            # si aucune n'est valide, le None final le dit a l'appelant.
            continue
    return None


_WIN_JOURNAUX = ("System", "Application")
_WIN_TTL_S = 60.0          # la requete coute ~44 ms : au plus une par minute
_WIN_FENETRE_MS = 30 * 24 * 3600 * 1000   # 30 jours de recherche


def _win_derniere_erreur(journal: str):
    """Horodatage epoch du dernier evenement de niveau ERREUR d'un journal Windows.

    Rend (ts, note). `ts is None` avec la raison quand on ne SAIT pas -- module
    absent, journal refuse, aucun evenement dans la fenetre. Surtout PAS 0, ni un
    age plafonne : `_sample_tdr_recent_win32` rend 0 sur n'importe quel echec, et
    « 0 evenement » s'y lit « tout va bien » (defaut assume dans sa docstring)."""
    try:
        import win32evtlog  # type: ignore
    except Exception as e:  # noqa: BLE001
        return None, "win32evtlog indisponible (%s)" % type(e).__name__
    xpath = ("*[System[Level=2 and TimeCreated[timediff(@SystemTime) <= %d]]]"
             % _WIN_FENETRE_MS)
    try:
        h = win32evtlog.EvtQuery(journal, win32evtlog.EvtQueryReverseDirection, xpath, None)
        evts = win32evtlog.EvtNext(h, 1)
        if not evts:
            return None, "aucune erreur dans les 30 derniers jours"
        xml = win32evtlog.EvtRender(evts[0], win32evtlog.EvtRenderEventXml)
    except Exception as e:  # noqa: BLE001
        return None, "journal %s illisible (%s)" % (journal, type(e).__name__)
    import re as _re
    m = _re.search(r"SystemTime='([^']+)'", xml)
    if not m:
        return None, "horodatage absent du rendu XML"
    brut = m.group(1).replace("Z", "+00:00")
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(brut).timestamp(), ""
    except Exception as e:  # noqa: BLE001
        return None, "horodatage illisible %r (%s)" % (brut[:32], type(e).__name__)


def grp_windows(prev: dict) -> tuple[dict, str]:
    """AGE du dernier evenement d'erreur des journaux Windows.

    POURQUOI UN AGE ET NON UN COMPTE. Mesure 2026-08-23 : cette machine produit
    ZERO erreur System par heure (verifie que ce n'est pas un acces refuse -- une
    requete sans filtre rend bien des evenements). Un canal de TAUX vaudrait donc
    0 a presque tous les ticks, serait quasi constant, et `selectionner_canaux`
    l'ecarterait comme il a ecarte `tdr_recent` : « constant, aucune information ».
    L'age, lui, croit entre deux evenements et retombe quand il s'en produit un --
    il varie toujours.

    COUT BORNE : la requete pese ~44 ms, impensable a chaque tick de 15 s. On
    interroge UN journal au plus par TTL, en alternance, et entre deux on
    EXTRAPOLE : le temps ecoule depuis un evenement passe se calcule, il ne se
    re-interroge pas."""
    if sys.platform != "win32":
        return {}, "journaux Windows absents de cette plateforme"
    now = time.time()
    etat = prev.setdefault("_win", {})
    a_rafraichir = None
    for j in _WIN_JOURNAUX:
        vu = etat.get(j)
        if vu is None or now - vu[1] >= _WIN_TTL_S:
            a_rafraichir = j
            break
    if a_rafraichir:
        ts, note = _win_derniere_erreur(a_rafraichir)
        etat[a_rafraichir] = (ts, now, note)

    vals, pannes = {}, []
    for j, cle in zip(_WIN_JOURNAUX, ("wse", "wae")):
        vu = etat.get(j)
        if not vu or vu[0] is None:
            pannes.append("%s: %s" % (j, (vu[2] if vu else "pas encore interroge")))
            continue
        vals[cle] = _f(round(now - vu[0], 1))
    if not vals:
        return {}, "; ".join(pannes) or "aucun journal lu"
    return vals, ("age du dernier evenement d'erreur" +
                  (" | non lus -> %s" % "; ".join(pannes) if pannes else ""))


# 300 s et non 60 : le scan coute 116 ms (12 028 entrees dans `sandbox/` + une
# lecture du superviseur), et une discordance de cette nature se compte en heures
# -- celle mesuree le 2026-08-23 durait 105 h. Rafraichir toutes les minutes
# paierait un prix reel pour une resolution dont personne n'a l'usage.
_ORG_TTL_S = 300.0
_ORG_FRAIS_S = 600.0


_SERVICES_TOML = _ROOT / "proxy_deno" / "core" / "services.toml"
_HB_DECLARES: dict | None = None


def _limite_fraicheur(service: str) -> float:
    """Seuil de silence PAR ORGANE, jamais uniforme.

    On ne juge pas un rythme cardiaque, une respiration et un cycle circadien avec
    la meme constante de temps. 29 des 45 afferences declarees sont `slow` : au
    seuil uniforme de 600 s, elles ressortent toutes « muettes » alors qu'elles
    tiennent leur cadence.

    ERREUR PAYEE TROIS FOIS. Le 26-07, un seuil uniforme de 900 s accusait
    `log_retention` (24 h) et `skill_curator` (6 h) ; le 22-07 la meme famille de
    seuils fixes a produit une embolie cortisol ; le 23-08, la premiere version de
    ce groupe a recommence et rapportait SIX organes muets dont aucun ne l'etait.

    On REUTILISE la primitive qui porte deja la cadence declaree plutot que d'en
    recoder une -- deux seuils divergeraient, et c'est celui qui crie qui gagnerait."""
    try:
        from nokido_agent.app.forge_sensor_fusion_probe import _heartbeat_limit  # type: ignore

        return float(_heartbeat_limit(service))
    except Exception:  # noqa: BLE001  # muet-ok : le repli sur le seuil global est
        # EXPLICITE et documente ci-dessous ; il ne se confond pas avec un succes.
        return _ORG_FRAIS_S


def _heartbeats_declares() -> dict:
    """{service: chemin} tel que DECLARE dans services.toml.

    ON DEMANDE AU REGISTRE, ON NE DEVINE PAS. Apparier par convention de nom
    (`<service>.heartbeat`) est un travers deja paye : mesure du 24-07,
    `NokidoWebHub`, qui ne declare AUCUN heartbeat, se voyait attribuer un residu
    de 20,6 jours et etait rapporte « capteur gele ». La premiere version de ce
    groupe, ecrite le 23-08, a REPRODUIT cette erreur et comptait 22 services
    « denerves » qui, en verite, ne declarent simplement pas de heartbeat.

    La distinction est physiologique, pas cosmetique : un organe qui ne declare
    aucune afference est un tissu NON INNERVE PAR CONCEPTION -- du cartilage, une
    prothese, un binaire tiers. Un organe qui en declare une et se tait est un
    NERF SECTIONNE. Seul le second est une pathologie."""
    global _HB_DECLARES
    if _HB_DECLARES is not None:
        return _HB_DECLARES
    out: dict = {}
    try:
        import re as _re

        txt = _SERVICES_TOML.read_text(encoding="utf-8", errors="replace")
        for bloc in txt.split("[[service]]")[1:]:
            m = _re.search(r'name\s*=\s*"([^"]+)"', bloc)
            hb = _re.search(r'^\s*heartbeat\s*=\s*"([^"]+)"', bloc, _re.M)
            if m and hb:
                out[m.group(1)] = hb.group(1)
    except Exception:  # noqa: BLE001  # muet-ok : l'absence du registre est
        # signalee par le dict VIDE, que l'appelant traite comme « je ne sais pas »
        # et non comme « aucun service ne declare de heartbeat ».
        return {}
    _HB_DECLARES = out
    return out


def grp_organes(prev: dict) -> tuple[dict, str]:
    """CONTRADICTIONS entre ce que le superviseur declare et ce que les organes font.

    POURQUOI PAS UN DECOMPTE DE VIVANTS (recadrage owner, 2026-08-23). J'avais
    d'abord publie « combien d'organes battent ». Chiffre ILLISIBLE : sur 14
    heartbeats perimes mesures ce jour-la, 10 n'avaient AUCUN service au
    superviseur -- des fichiers residuels laisses par des outils qui ont tourne une
    fois il y a des semaines (lmstudio_keeper : 846 h). Les compter comme organes
    morts est faux ; et les organes reellement eteints le sont le plus souvent A
    DESSEIN, on-demand, faux positif deja clos le 31-07. Un thermometre que
    l'extinction volontaire et les cadavres de fichiers brouillent ne mesure rien.

    CE QUI SE MESURE SANS AMBIGUITE, c'est la CONTRADICTION : un service que le
    registre dit `running` et dont le heartbeat est mort. Mesure du jour :
    `NokidoRSSWatcher` declare vivant, muet depuis 105 h. Meme doctrine que partout
    ailleurs dans le corps -- le registre ment, on croise avec le reel.

    `orsa` compte l'ANGLE MORT : les services `running` qui n'ont pas de heartbeat
    du tout. Leur mort serait silencieuse par construction (cf `RULES_SHARED`,
    statut SUPERVISE). Ne pas le publier reviendrait a surestimer la couverture.

    COUT : un scan de `sandbox/` (19,6 ms, non pas a cause des ~42 heartbeats mais
    des 12 028 entrees du dossier) plus une lecture du superviseur, le tout mis en
    cache a TTL -- une contradiction de cette nature se juge en minutes."""
    now = time.time()
    vu = prev.get("_org")
    if vu is None or now - vu[2] >= _ORG_TTL_S:
        declares = _heartbeats_declares()
        if not declares:
            return {}, "registre des heartbeats illisible -- une discordance ne se constate pas"
        try:
            import json as _js
            import urllib.request as _url

            brut = _js.load(_url.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=0.5))
        except Exception as e:  # noqa: BLE001
            return {}, ("superviseur injoignable (%s) -- sans registre, une "
                        "discordance ne se constate pas" % type(e).__name__)
        svc = brut.get("services") or brut
        paires = svc.items() if isinstance(svc, dict) else [(s.get("name"), s) for s in svc]

        muets = coupes = 0
        pire = 0.0
        for nom, v in paires:
            statut = v.get("status") if isinstance(v, dict) else str(v)
            if statut != "running":
                continue
            chemin = declares.get(str(nom))
            if chemin is None:
                continue        # non innerve PAR CONCEPTION : pas une pathologie
            p = _ROOT / str(chemin).lstrip("./")
            try:
                age = now - p.stat().st_mtime
            except OSError:
                coupes += 1     # afference DECLAREE mais jamais cablee
                continue
            limite = _limite_fraicheur(str(nom))
            # On ne diagnostique pas une bradycardie sur un coeur qui vient de
            # repartir : un organe a cycle long est LEGITIMEMENT muet tant qu'il
            # n'a pas eu le temps de battre une fois. Mesure 2026-08-23 :
            # NokidoRSSWatcher, cycle de 6 h, relance depuis 199 s, sortait
            # « muet depuis 106 h » — c'est le pouls du processus PRECEDENT.
            depuis = _f((v or {}).get("uptime_s")) if isinstance(v, dict) else None
            if depuis is not None and depuis < limite:
                continue
            pire = max(pire, age)
            if age >= limite:
                muets += 1
        # `ordm` porte l'information que le COMPTE ecrase : un seuil a 600 s range
        # dans le meme panier un organe muet depuis 106 h et un autre en retard de
        # douze minutes. Le silence le plus long, lui, discrimine sans seuil.
        vu = (muets, coupes, now, round(pire, 1))
        prev["_org"] = vu
    return ({"ords": _f(vu[0]), "orsa": _f(vu[1]), "ordm": _f(vu[3])},
            "afferences declarees (%d muettes, %d declarees mais jamais cablees, "
            "silence max %.1f h)" % (vu[0], vu[1], vu[3] / 3600.0))


def grp_organes_sante(prev: dict) -> tuple[dict, str]:
    """Ce que les organes de SURVEILLANCE disent d'eux-memes.

    `inspector_log` = le bulbe rachidien (ports tombes, zombies) ;
    `coagulation_events` = les blessures detectees et leur resolution.

    GARDE DE FRAICHEUR : mesure 2026-08-23, `inspector_log` s'arretait a 16:27
    alors qu'il etait 18:30 -- l'inspecteur n'ecrivait plus. Servir sa derniere
    ligne aurait publie « 0 port tombe » sur la foi d'un capteur muet. Au-dela de
    la peremption on rend None avec la raison.

    PAS DE FUITE D'ETIQUETTE ici, contrairement au cycle de vie : la coagulation
    reagit a des workers (gemini_poll, biblio_worker, health_diagnostic,
    hebbian_linker), jamais a la RAM dont l'etiquette de detresse est tiree."""
    chemin = _ROOT / "RAG" / "embeddings.db"
    if not chemin.exists():
        return {}, "base absente"
    try:
        import sqlite3

        con = sqlite3.connect("file:%s?mode=ro" % chemin.as_posix(), uri=True, timeout=0.2)
        try:
            # `inspector_log` est un JOURNAL qui suit `sandbox/journaux.switch` ;
            # `coagulation_events` reste dans la base du RAG. Les deux etaient lus
            # par la MEME connexion : le jour de la bascule, cette fonction aurait
            # lu un journal FIGE en croyant lire le courant, sans la moindre erreur.
            # Une connexion DEDIEE au journal, ouverte seulement pour lui, et le
            # meme timeout court et delibere que ci-dessous (un capteur qui ralentit
            # le corps qu'il observe est pire que le canal qu'il apporte).
            # `Path` est importe LOCALEMENT : la premiere version de ce bloc
            # utilisait `_Path`, un nom qui n'existe pas dans ce module. Elle
            # aurait leve NameError AU MOMENT DE LA BASCULE, c'est-a-dire
            # exactement quand cette ligne doit fonctionner -- et le `except`
            # englobant l'aurait avalee. Meme piege que le logger absent de
            # `forge_web_fetch`, invisible a la relecture, visible en UNE
            # execution.
            from pathlib import Path as _CheminLocal

            try:
                from nokido_agent.app.forge_db_path import journal_path as _jp
                _base_insp = _jp("inspector_log")
            except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
                _base_insp = str(chemin)
            if _base_insp == str(chemin):
                con_insp, _fermer_insp = con, False
            else:
                con_insp = sqlite3.connect(
                    "file:%s?mode=ro" % _CheminLocal(_base_insp).as_posix(),
                    uri=True, timeout=0.2)
                _fermer_insp = True
            try:
                insp = con_insp.execute("SELECT ts, ports_down, zombies FROM inspector_log "
                                        "ORDER BY rowid DESC LIMIT 1").fetchone()
            finally:
                if _fermer_insp:
                    con_insp.close()
            ouvertes = con.execute("SELECT COUNT(*) FROM coagulation_events "
                                   "WHERE ts_resolved IS NULL").fetchone()[0]
            dernier = con.execute("SELECT MAX(ts_detected) FROM coagulation_events").fetchone()[0]
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        return {}, "organes de surveillance illisibles (%s)" % type(e).__name__

    vals: dict = {"cgo": _f(ouvertes)}
    pannes = []

    age = _age_iso(dernier)
    if age is None:
        pannes.append("coagulation sans horodatage exploitable")
    else:
        vals["cga"] = _f(round(age, 1))

    age_i = _age_iso(insp[0]) if insp else None
    if age_i is None:
        pannes.append("inspecteur sans ligne lisible")
    elif age_i > _ORG_FRAIS_S:
        pannes.append("inspecteur PERIME (%.0f min) -- il n'ecrit plus" % (age_i / 60))
    else:
        vals["ipd"] = _f(insp[1])
        vals["izo"] = _f(insp[2])
    return vals, ("organes de surveillance" +
                  (" | non lus -> %s" % "; ".join(pannes) if pannes else ""))


def _age_iso(brut):
    """Secondes ecoulees depuis un horodatage texte, ou None s'il est illisible."""
    if not brut:
        return None
    from datetime import datetime as _dt
    for forme in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return time.time() - _dt.strptime(str(brut)[:19], forme).timestamp()
        except Exception:  # noqa: BLE001  # muet-ok : on essaie la forme suivante,
            # et l'echec de TOUTES est signale par le None final.
            continue
    return None


def grp_hub_process(prev: dict) -> tuple[dict, str]:
    """Compteurs du PROCESS hub (threads, handles, fds, rss, cpu).

    On JOINT `forge_hub_blackbox`, qui les ecrit deja toutes les ~11 s : le cout est
    donc deja paye, contrairement au groupe `handles` qui interroge les 49 services
    et coute 350 ms. La reserve du 2026-08-05 -- « une fuite de handles a pour
    dimension la JOURNEE » -- vaut toujours pour juger une fuite sur une fenetre
    courte, mais elle n'interdit pas de JOURNALISER le compteur : c'est meme la
    seule facon d'obtenir un jour la profondeur qui manque.

    Peremption : au-dela de 120 s la ligne ne decrit plus l'instant, on rend None
    plutot qu'une valeur figee -- un capteur en retard ment plus qu'il n'informe."""
    ligne = _derniere_ligne_json(_ROOT / "sandbox" / "hub_blackbox.jsonl")
    if not ligne:
        return {}, "boite noire du hub absente ou illisible"
    age = time.time() - (_f(ligne.get("ts")) or 0.0)
    if age > 120.0:
        return {}, "boite noire PERIMEE (%.0f s) -- le hub n'ecrit plus" % age
    h = ligne.get("hub") or {}
    if not isinstance(h, dict) or not h:
        return {}, "ligne sans bloc 'hub' (hub mort au dernier echantillon ?)"
    return ({
        "hth": _f(h.get("threads")),
        "hhd": _f(h.get("handles")),
        "hfd": _f(h.get("fds")),
        "hrs": _f(h.get("rss_gb")),
        "hcp": _f(h.get("cpu_pct")),
    }, "forge_hub_blackbox (age %.0f s)" % age)


def _lire_ajouts(prev: dict, cle: str, chemin, plafond_o: int = 4_000_000):
    """Lignes AJOUTEES a un flux append-only depuis le dernier appel, et le delai.

    Rend (lignes, dt, note). `lignes is None` signale qu'on ne SAIT pas, avec la
    raison ; une liste vide signale qu'on a regarde et que rien n'a ete ecrit --
    deux choses differentes qu'un zero confondrait.

    Premiere lecture : aucune reference, donc None, exactement comme `_debit`. Un
    flux TRONQUE ou tourne remet la reference a zero et rend None pour ce tick,
    plutot qu'un pic fantome de plusieurs milliers d'evenements."""
    now = time.time()
    try:
        taille = os.path.getsize(chemin)
    except Exception as e:  # noqa: BLE001
        return None, None, "flux illisible (%s)" % type(e).__name__
    ancien = prev.get(cle)
    prev[cle] = (taille, now)
    if not ancien:
        return None, None, "premiere lecture (aucune reference de debit)"
    pos, t0 = ancien
    dt = now - t0
    if taille < pos:
        return None, None, "flux tronque ou tourne -- reference remise a zero"
    if dt <= 0:
        return None, None, "horloge non progressive"
    if taille == pos:
        return [], dt, ""
    a_lire = min(taille - pos, plafond_o)
    try:
        with open(chemin, "rb") as fh:
            fh.seek(taille - a_lire)
            brut = fh.read(a_lire)
    except Exception as e:  # noqa: BLE001
        return None, None, "lecture impossible (%s)" % type(e).__name__
    lignes = []
    for b in brut.split(b"\n"):
        b = b.strip()
        if not b:
            continue
        try:
            lignes.append(json.loads(b.decode("utf-8", "replace")))
        except Exception:  # noqa: BLE001  # muet-ok : la fenetre commence au milieu
            # d'une ligne, la premiere candidate est donc tronquee par construction.
            continue
    return lignes, dt, ""


def grp_bus(prev: dict) -> tuple[dict, str]:
    """Debit du BUS d'evenements : ce que le corps se dit a lui-meme.

    Premier canal reellement EVENEMENTIEL de la serie -- il compte des faits
    discrets, la ou tous les autres echantillonnent une grandeur continue. Lu par
    accroissement de fichier (quelques kilo-octets par tick), pas par relecture."""
    lignes, dt, note = _lire_ajouts(prev, "bus", _ROOT / "sandbox" / "event_bus_replay.jsonl")
    if lignes is None:
        return {}, note
    n = len(lignes)
    err = sum(1 for d in lignes if str(d.get("kind")) == "error")
    agents = {str(d.get("agent")) for d in lignes if d.get("agent")}
    return ({"bev": _f(round(n / dt, 3)),
             "berr": _f(round(err / dt, 4)),
             "bag": _f(len(agents))},
            "event_bus_replay (%d evts / %.0f s)" % (n, dt))


def grp_cycle_vie(prev: dict) -> tuple[dict, str]:
    """Actions du cycle de vie, RESTREINTES au domaine `gate`.

    Restriction DELIBEREE, et c'est le point important. Les actions dominantes du
    flux -- `rss_derive_detected` (3700 sur 5803), `evict_detresse`, `snn_spike` --
    sont des REACTIONS du regulateur a une RAM basse. Or l'etiquette que les bancs
    cherchent a predire est precisement « ram_free_gb sous un seuil »
    (`episodes_detresse`). Les compter apprendrait au modele « le regulateur a
    reagi » a la place de « la detresse arrive » : un score flatteur, et faux.

    Le domaine `gate` porte des decisions de gouvernance, sans lien avec la RAM.
    Les actions ecartees restent lisibles dans le flux pour qui voudra mener
    l'experience en connaissance de cause -- ce qui n'est pas la meme chose que
    les faire entrer par defaut."""
    lignes, dt, note = _lire_ajouts(prev, "vie", _ROOT / "sandbox" / "lifecycle_actions.jsonl")
    if lignes is None:
        return {}, note
    gate = sum(1 for d in lignes if str(d.get("domain")) == "gate")
    return ({"lcg": _f(round(gate / dt, 4))},
            "lifecycle_actions (%d actions / %.0f s, %d en gate)" % (len(lignes), dt, gate))


def grp_hub_requetes(prev: dict) -> tuple[dict, str]:
    """Latence et volume PAR REQUETE sur la derniere minute, joints depuis
    `promcp_tool_metrics` (colonnes ts, duration_ms, ok, payload_bytes, result_bytes).

    C'est le capteur EVENEMENTIEL que les scalaires a 15 s ne portent pas : une
    moyenne de CPU ne voit pas un appel qui passe de 90 ms a 160 s, or c'est
    exactement la forme qu'a la detresse cote hub.

    Trois etats : zero appel est une mesure REELLE (ln=0), mais la latence d'un
    ensemble vide est INCONNUE (None), pas nulle."""
    chemin = _ROOT / "RAG" / "embeddings.db"
    if not chemin.exists():
        return {}, "base de metriques absente"
    try:
        import sqlite3

        # timeout COURT et delibere : lecture seule, donc aucun verrou pris, mais un
        # ecrivain qui tient une transaction ferait ATTENDRE la lecture. A 4 ticks par
        # minute, une seconde d'attente calerait le sampler ; 0,2 s le fait echouer
        # NET, et l'echec est journalise comme tel. Un capteur qui ralentit le corps
        # qu'il observe est pire que le canal qu'il apporte.
        con = sqlite3.connect("file:%s?mode=ro" % chemin.as_posix(), uri=True, timeout=0.2)
        try:
            lignes = con.execute(
                "SELECT duration_ms, ok, payload_bytes, result_bytes "
                "FROM promcp_tool_metrics WHERE ts >= ?", (time.time() - 60.0,)
            ).fetchall()
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        return {}, "metriques illisibles (%s: %s)" % (type(e).__name__, str(e)[:90])

    n = len(lignes)
    if not n:
        return ({"ln": 0.0, "lp95": None, "lmax": None, "lerr": None,
                 "lbi": None, "lbo": None}, "aucun appel dans la minute")
    durees = sorted(v for v in (_f(r[0]) for r in lignes) if v is not None)
    echecs = sum(1 for r in lignes if r[1] in (0, False, "0"))
    entree = sum(_f(r[2]) or 0.0 for r in lignes)
    sortie = sum(_f(r[3]) or 0.0 for r in lignes)
    p95 = durees[min(len(durees) - 1, int(len(durees) * 0.95))] if durees else None
    return ({
        "ln": _f(n),
        "lp95": _f(round(p95, 1)) if p95 is not None else None,
        "lmax": _f(round(durees[-1], 1)) if durees else None,
        "lerr": _f(round(100.0 * echecs / n, 1)),
        "lbi": _f(round(entree / 1024.0, 2)),
        "lbo": _f(round(sortie / 1024.0, 2)),
    }, "promcp_tool_metrics (%d appels/60 s)" % n)


# Derniere raison d'echec par groupe : sert a ne journaliser qu'au CHANGEMENT.
# Un capteur muet est indistinguable d'un capteur eteint -- c'est le defaut que ce
# module denonce, et il a ete commis ICI meme le 2026-08-05 : `swp` disparaissait
# de la serie sans qu'aucune ligne ne le dise.
_DERNIERE_PANNE: dict = {}


# nom -> (fonction, palier). `serie` = journalise ; `sonde` = mesure a la demande.
GROUPES = {
    "memoire": (grp_memoire, "serie"),
    "cpu": (grp_cpu, "serie"),
    "io": (grp_io, "serie"),
    "disque": (grp_disque, "serie"),
    "endocrine": (grp_endocrine, "serie"),
    "services": (grp_services, "serie"),
    "appels": (grp_appels, "serie"),
    "handles": (grp_handles, "sonde"),
    "cognitif": (grp_cognitif, "sonde"),
    # PROMUS en `serie` apres chiffrage du 2026-08-23 : hub_process 0,09 ms median
    # (0,18 max), hub_requetes 2,40 ms (2,67 max) -- lecture seule, timeout 0,2 s.
    # Ce sont les premiers canaux EVENEMENTIELS de la serie : les scalaires a 15 s
    # ne voient pas un appel qui passe de 90 ms a 160 s, et c'est cette forme-la
    # qu'a la detresse cote hub.
    "hub_process": (grp_hub_process, "serie"),
    "hub_requetes": (grp_hub_requetes, "serie"),
    # PROMUS en `serie` apres chiffrage du 2026-08-23 : bus 0,24 ms median,
    # cycle_vie 0,21 ms -- lecture par ACCROISSEMENT de fichier, donc le cout ne
    # depend pas de la taille du flux mais de ce qui vient d'y etre ecrit.
    "bus": (grp_bus, "serie"),
    "cycle_vie": (grp_cycle_vie, "serie"),
    # PROMU en `serie` apres chiffrage du 2026-08-23 : 8,6 ms sur le tick qui
    # rafraichit (un journal, une fois par minute), 0,003 ms sur tous les autres.
    # Demander LE DERNIER evenement en marche arriere coute 8,6 ms la ou COMPTER
    # ceux d'une fenetre en coutait 44 : choisir l'age plutot que le taux a rendu
    # le canal plus informatif ET cinq fois moins cher.
    "windows": (grp_windows, "serie"),
    # PROMUS en `serie` apres chiffrage du 2026-08-23 : organes 16,2 ms au scan
    # (une fois par minute) puis 0,00 ms grace au cache ; organes_sante 3,63 ms.
    "organes": (grp_organes, "serie"),
    "organes_sante": (grp_organes_sante, "serie"),
}

PALIER_SERIE = tuple(n for n, (_, t) in GROUPES.items() if t == "serie")


def echantillon(palier: str = "serie", prev: dict | None = None) -> dict:
    """Canaux du palier demande, aplatis. NE LEVE JAMAIS : un capteur qui casse son
    appelant serait pire que le trou qu'il laisse. Un groupe en echec est ABSENT du
    resultat -- il n'y injecte pas de zeros."""
    import logging

    log = logging.getLogger(__name__)
    p = _PREV if prev is None else prev
    out: dict = {}
    for nom, (fn, tier) in GROUPES.items():
        if palier != "tout" and tier != palier:
            continue
        try:
            vals, note = fn(p)
            panne = note if not vals else ""
        except Exception as e:  # noqa: BLE001
            vals, panne = {}, "EXCEPTION %s: %s" % (type(e).__name__, str(e)[:120])
        # On parle au CHANGEMENT d'etat, pas a chaque tick (4x/minute) : la panne
        # qui s'installe est dite UNE fois, et sa disparition aussi.
        if panne != _DERNIERE_PANNE.get(nom, ""):
            if panne:
                log.warning(
                    "[canaux] groupe '%s' (palier %s) NE REND AUCUN CANAL : %s | "
                    "consequence: ces grandeurs sortent de la serie, une absence "
                    "n'est PAS une valeur nulle", nom, tier, panne)
            else:
                log.info("[canaux] groupe '%s' (palier %s) REPARE, %d canaux de "
                         "nouveau mesures", nom, tier, len(vals))
            _DERNIERE_PANNE[nom] = panne
        out.update(vals)
    return out


def lisible(row: dict) -> dict:
    """Traduit une ligne de serie (cles courtes) en noms complets -- pour un humain
    ou un banc qui prefere l'explicite au compact."""
    return {SCHEMA.get(k, k): v for k, v in row.items()}


if __name__ == "__main__":
    print(json.dumps({"serie": echantillon("serie"),
                      "schema": SCHEMA}, ensure_ascii=False, indent=2, default=str))
