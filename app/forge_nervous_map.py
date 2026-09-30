#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_nervous_map.py — CARTE NERVEUSE : inventaire unifié des composants internes,
PLUGGÉS au CORTEX (routage/décision) et au SYSTÈME NERVEUX (bus d'événements + hormones).

Directive user : lister daemons / rôles / agents / organ-agents / skills / hooks + le
CORTEX et le SYSTÈME NERVEUX, et les PLUGGER (chaque composant doit être adressable par le
cortex ET signalable par le SN). Découverte LIVE (résiste aux ajouts — on lit les sources
réelles : services.toml, AgentRole, registres keeper/flow/organ, ~/.claude/skills, .githooks).

Le PLUG de chaque type :
  - CORTEX  = qui DÉCIDE/ROUTE vers lui (forge_orchestration_gate / forge_cognitive_router /
              forge_spike_router / forge_mcp_registry dispatch / RoleOrchestrator / keeper registry).
  - SN      = comment il est SIGNALÉ (forge_events pub/sub, nervous_system.ts SystemBus/BloodCell,
              forge_endocrine hormones, heartbeats superviseur, hooks = réflexes spinaux).

ANTI-DUP : fédère forge_keeper_base / forge_flow_control / forge_organ_agents + découvre le
reste. N'EXÉCUTE rien — c'est la carte (jumelle du census, niveau organisme entier).
"""
from __future__ import annotations

__FORGE_COLOR__ = "snc/registry : carte nerveuse, inventaire des composants plugges au cortex"  # organe declare le 2026-09-06 (audit de raccordement)

import importlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "app"):  # ROOT requis pour les imports style `from app.core...`
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"
AGENTS_PY = ROOT / "app" / "forge_agents.py"
BASELINE = ROOT / "sandbox" / "nervous_baseline.json"

# Modules CŒUR dont l'import DOIT réussir — un import KO = un nerf SECTIONNÉ.
_CORE_NERVES = ["forge_orchestration_gate", "forge_cognitive_router", "forge_spike_router",
                "forge_nlu", "forge_byte_router", "forge_mcp_registry", "forge_event_stream",
                "forge_message_frame", "forge_endocrine", "forge_critical_events",
                "forge_keeper_base", "forge_flow_control", "forge_organ_agents"]

# ── CORTEX (cerveau décisionnel) : les routeurs/décideurs, plug d'ENTRÉE des composants ──
CORTEX = {
    "forge_orchestration_gate": "VOIE (native/local/deport/cloud) + apprentissage actif + endocrine",
    "forge_cognitive_router": "complexité -> backend",
    "forge_spike_router": "réflexe SNN (cervelet, stratégies apprises)",
    "forge_nlu": "thalamus (tri chat/action/rag)",
    "forge_byte_router": "moelle épinière (13 sentinels)",
    "forge_mcp_registry": "SN périphérique (dispatch handle_* × ring)",
}
# ── SYSTÈME NERVEUX : le transport du signal, plug de SORTIE/réveil des composants ──
NERVOUS = {
    "nervous_system.ts": "SystemBus / BloodCell (bus événementiel inter-organes, Deno)",
    "forge_event_stream": "pub/sub Python (EventStream SQLite WAL)",
    "forge_message_frame": "files par agent (CQRS, hydrate au boot)",
    "forge_endocrine": "signal HORMONAL typé (demi-vie, récepteurs) — adrénaline/cortisol/dopamine",
    "forge_critical_events": "axone de classe critique (survit au restart)",
}


def _names_from_toml() -> list:
    if not SERVICES_TOML.exists():
        return []
    txt = SERVICES_TOML.read_text("utf-8", "ignore")
    # Rename LaForge -> Nokido : cette regex figee sur "LaForge\w+" ne matchait
    # plus que le residu NokidoMCP -> daemons() rendait 1 nom sur 64 et
    # _check_nerve_plug declarait 63 organes VANISHED a tort (mesure 2026-07-22).
    return re.findall(r'^\s*name\s*=\s*"((?:LaForge|Nokido)\w+)"', txt, re.M)


def _enum_members(file: Path, classname: str) -> list:
    if not file.exists():
        return []
    txt = file.read_text("utf-8", "ignore")
    m = re.search(rf"class {classname}\b.*?(?=\nclass |\Z)", txt, re.S)
    if not m:
        return []
    return sorted(set(re.findall(r"^\s+([A-Z][A-Z_]+)\s*=\s*[\"']", m.group(0), re.M)))


def daemons() -> list:
    """Daemons supervisés (services.toml). Plug : CORTEX=superviseur ; SN=heartbeat+hormones."""
    return _names_from_toml()


def roles() -> list:
    """Rôles-persona (forge_agents.AgentRole). Plug : CORTEX=RoleOrchestrator/router."""
    return _enum_members(AGENTS_PY, "AgentRole")


def organ_agents() -> dict:
    """Organ-agents : keepers + équipe flux + census organe. Plug : CORTEX=registre keeper/
    portier ; SN=facteur(announce)+hormones."""
    out = {"keepers": [], "flow_control": [], "organ_families": []}
    try:
        from nokido_agent.app import forge_keeper_base as kb
        out["keepers"] = sorted(kb.discover().keys())
    except Exception:  # noqa: BLE001
        pass
    try:
        from nokido_agent.app import forge_flow_control as fc
        out["flow_control"] = sorted(fc.team()["agents"].keys())
    except Exception:  # noqa: BLE001
        pass
    try:
        from nokido_agent.app import forge_organ_agents as oa
        out["organ_families"] = [r["family"] for r in oa.census()["families"]]
    except Exception:  # noqa: BLE001
        pass
    return out


def skills() -> list:
    """Skills locaux (SKILL.md). Plug : CORTEX=dispatch skill ; SN=—. Cross-CLI."""
    found = set()
    for base in (Path.home() / ".claude" / "skills", ROOT / ".claude" / "skills",
                 ROOT / "docs" / "skills"):
        if base.exists():
            for sk in base.glob("**/SKILL.md"):
                found.add(sk.parent.name)
    return sorted(found)


def hooks() -> list:
    """Hooks locaux = RÉFLEXES SPINAUX (fire sur événement, 0 token). Plug : SN=événementiel."""
    out = []
    gh = ROOT / ".githooks"
    if gh.exists():
        out += [f"git:{h.name}" for h in gh.iterdir() if h.is_file() and h.suffix != ".ps1"]
    # hooks Claude (guards + offload) = scripts tools/
    for pat in ("bash_guard.py", "hook_search_guard.py", "hook_posttool_validate.py",
                "hook_*.py", "*_guard.py"):
        for h in (ROOT / "tools").glob(pat):
            tag = f"claude:{h.stem}"
            if tag not in out:
                out.append(tag)
    return sorted(set(out))


def nervous_map() -> dict:
    """Carte NERVEUSE complète : tout composant interne + son plug cortex/SN."""
    oa = organ_agents()
    inv = {
        "daemons": {"items": daemons(), "cortex": "superviseur LaForge-Master (wave/deps)",
                    "nervous": "heartbeat sandbox/*.heartbeat + hormones (forge_endocrine)"},
        "roles": {"items": roles(), "cortex": "RoleOrchestrator / IntentRouter (forge_agents)",
                  "nervous": "—"},
        "organ_agents": {"items": oa, "cortex": "registre keeper + portier (present_any/consult)",
                         "nervous": "facteur announce + hormones"},
        "skills": {"items": skills(), "cortex": "dispatch skill (forge_skill_sync)", "nervous": "—"},
        "hooks": {"items": hooks(), "cortex": "—", "nervous": "réflexe spinal (event-driven, 0 token)"},
        "cortex": {"items": list(CORTEX.keys()), "role": CORTEX},
        "nervous_system": {"items": list(NERVOUS.keys()), "role": NERVOUS},
    }
    counts = {k: (len(v["items"]) if isinstance(v.get("items"), list)
                  else sum(len(x) for x in v["items"].values()))
              for k, v in inv.items()}
    return {"organism": "Nokido", "inventory": inv, "counts": counts,
            "total": sum(counts.values())}


def reachability() -> list:
    """Nerfs SECTIONNÉS : modules cœur qui ne s'importent plus (.ts Deno exclus, non-Python)."""
    severed = []
    for name in _CORE_NERVES:
        try:
            importlib.import_module(name)
        except Exception as e:  # noqa: BLE001
            severed.append(f"{name}: {type(e).__name__}")
    return severed


def _component_names() -> list:
    """Ensemble plat des noms de composants (pour le diff baseline)."""
    m = nervous_map()
    names = []
    for kind, v in m["inventory"].items():
        it = v.get("items")
        if isinstance(it, list):
            names += [f"{kind}:{x}" for x in it]
        elif isinstance(it, dict):
            for sub, lst in it.items():
                names += [f"{kind}.{sub}:{x}" for x in lst]
    return sorted(set(names))


def snapshot() -> dict:
    """Fige l'inventaire courant comme baseline (référence du diff 'nerf qui lâche')."""
    names = _component_names()
    try:
        BASELINE.parent.mkdir(exist_ok=True)
        BASELINE.write_text(json.dumps(sorted(names), ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "count": len(names)}


def drift() -> dict:
    """Diff vs baseline : VANISHED = composant qui a disparu (un nerf qui lâche) ; NEW = ajout.
    Pas de baseline -> on la crée (premier passage, aucun drift)."""
    cur = set(_component_names())
    if not BASELINE.exists():
        snapshot()
        return {"vanished": [], "new": [], "baseline": "créée"}
    try:
        base = set(json.loads(BASELINE.read_text("utf-8", "ignore")))
    except Exception:  # noqa: BLE001
        return {"vanished": [], "new": [], "baseline": "illisible"}
    return {"vanished": sorted(base - cur), "new": sorted(cur - base)}


def plug_report() -> dict:
    """État des plugs : SEVERED (nerf sectionné=import KO) + VANISHED (drift baseline) +
    orphelins type-level. C'est ce que la sentinelle anti-embolie consomme."""
    m = nervous_map()
    severed = reachability()
    d = drift()
    type_orphans = []
    for kind, v in m["inventory"].items():
        if kind in ("cortex", "nervous_system"):
            continue
        if v.get("cortex", "—") == "—" and v.get("nervous", "—") == "—":
            type_orphans.append(kind)
    return {"total": m["total"], "severed": severed, "vanished": d.get("vanished", []),
            "new": d.get("new", []), "type_orphans": type_orphans,
            "healthy": not severed and not d.get("vanished")}


# ── AUTORITES PAR ORGANE (chantier topologie 2026-09-05) ──────────────────────
# `daemons()` rend des NOMS. Un nom ne dit pas qui lance l'organe, qui le supervise,
# qui a le droit de le redemarrer, ni qui atteste qu'il vit. Cas qui a impose ces
# champs : `service_crash_watcher` bat, il est ABSENT de services.toml, et personne
# n'a su dire d'ou il venait apres 578 h de silence — le watcher de crash etait
# precisement celui que personne ne surveillait.
#
# QUATRE ETATS par champ, jamais deux : `declare` (un registre le dit) · `derive`
# (deduit d'une regle explicite, ecrite ici) · `absent` (personne) · `illisible`
# (on n'a PAS pu regarder). Le quatrieme est le seul qui empeche de lire un scanner
# muet comme une absence.
#
# VOIR n'est pas SUPERVISER. `forge_health_diagnostic` enumere tous les pouls du
# disque depuis le 2026-09-04, donc il VOIT les organes hors registre — mais ils ne
# pesent pas sur le score et aucun superviseur ne les releve. Confondre les deux
# ferait declarer supervise un organe que personne ne peut redemarrer.

def _services_declares() -> tuple:
    """{nom: spec} depuis services.toml. Second membre = raison si ILLISIBLE."""
    try:
        import tomllib

        d = tomllib.loads(SERVICES_TOML.read_text("utf-8"))
        return {s["name"]: s for s in (d.get("service") or []) if s.get("name")}, None
    except Exception as e:  # noqa: BLE001
        return {}, "%s: %s" % (type(e).__name__, e)


def _taches_planifiees() -> tuple:
    """Taches planifiees Windows. `None` = ILLISIBLE, pas `aucune`.

    ZONE D'OMBRE DECLAREE : `RULES_SHARED` note que le capteur d'organes ne voit ni
    les taches planifiees ni les lanceurs de boot du profil owner, et que
    `ZONE_MORTE` n'autorise donc AUCUNE suppression. On tente la lecture, et on dit
    quand elle echoue au lieu de conclure a l'absence de lanceur.
    """
    import subprocess

    try:
        out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"],
                             capture_output=True, text=True, errors="replace",
                             timeout=30)
        if out.returncode != 0:
            return None, (out.stderr or "").strip()[:120] or "rc=%d" % out.returncode
        noms = []
        for ligne in out.stdout.splitlines():
            if ligne.strip():
                noms.append(ligne.split(",")[0].strip('"').lstrip("\\"))
        return noms, None
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


# ── LIVENESS : la MESURE et l'INFERENCE ne se confondent plus ─────────────────
# Defaut mesure le 2026-09-05 : `alive` valait la seule FRAICHEUR du pouls, donc
# `tdr_sentinel` et `docker_keeper` sortaient « vivants » alors que
# `forge_process_inventory` disait au meme instant « bat encore alors que le pid
# declare est mort ». Deux instruments se contredisaient et c'est le plus optimiste
# qui gagnait : un pouls d'ORPHELIN rehabilitait son organe.
#
# Le pouls reste OBSERVE — on ne supprime pas le signal, il est la preuve d'un
# dysfonctionnement, pas d'une sante. C'est l'INFERENCE qu'on corrige.
VIVANT_OUI = "OUI"
VIVANT_NON = "NON"
VIVANT_INCERTAIN = "INCERTAIN"
VIVANT_INCONNU = "INCONNU"


def _porteur_existe(pid):
    """Un processus porte-t-il ce pid ? `None` = on n'a PAS pu regarder.

    On interroge l'EXISTENCE, jamais l'identite : la cmdline est illisible pour 331
    process sur 339 quand ils appartiennent a un autre compte (mesure 2026-07-30).
    Un pid qui existe ne prouve donc pas que c'est NOTRE processus — la nuance vit
    dans `producteur_preuve`, pas dans un verdict trop confiant.
    """
    try:
        import psutil

        return psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001 - muet-ok : sonde indisponible -> etat INCONNU
        return None


def liveness(etat_hb: dict, pid) -> tuple:
    """(producteur_vivant, producteur_preuve) — quatre etats, jamais deux.

    L'ABSENCE de pid ne vaut PAS mort : ce serait remplacer une sur-deduction par une
    autre. 24 pouls sur 49 n'ecrivent aucun pid (reimplementations non migrees vers
    `beat_daemon`) ; les declarer morts fabriquerait 24 pannes fictives. Ils sortent
    INCERTAIN avec la raison, ce qui laisse la migration les faire basculer.
    """
    if not etat_hb:
        return VIVANT_INCONNU, "aucun_pouls"
    frais = etat_hb.get("alive")
    if frais is None:
        return VIVANT_INCONNU, "pouls_illisible"
    if frais is False:
        # Un pouls perime ne peut jamais valoir OUI, quel que soit l'etat du pid.
        return VIVANT_NON, "heartbeat_stale"
    if pid is None:
        return VIVANT_INCERTAIN, "heartbeat_frais_sans_pid (identity_unbound)"
    existe = _porteur_existe(pid)
    if existe is False:
        # LE CAS QUI FERME LE TROU : le pouls est frais, son porteur n'existe plus.
        return VIVANT_NON, "heartbeat_frais_pid_mort (ORPHELIN)"
    if existe is None:
        return VIVANT_INCERTAIN, "heartbeat_frais_pid_non_observable"
    return VIVANT_OUI, "heartbeat_frais_pid_present"


def _champ(valeur, etat: str) -> dict:
    return {"valeur": valeur, "etat": etat}


def dependances_bloquantes(organe: str, timeout: float = 1.5) -> dict:
    """Les dependances DECLAREES de cet organe repondent-elles ?

    SONDE A LA DEMANDE, jamais dans `autorites()` : ouvrir N sockets a chaque appel
    de la carte en ferait un emetteur de trafic, et une carte doit LIRE.

    POURQUOI CET ETAT EXISTE. Mesure du 2026-09-05 : `NokidoEpistemicSoif` declare
    `deps = [8099, 8100, 6333]`. Deux de ces trois ports ne repondent pas, donc le
    superviseur ne le demarre jamais — il journalise « starting » et aucun processus
    n'atteint sa premiere ligne de log. Lu sans les dependances, l'organe paraissait
    MORT depuis 62 h sans cause ; lu avec, il est BLOQUE EN AMONT, ce qui n'appelle
    pas du tout le meme geste. La chaine complete etait : une decision owner eteint
    les embedders -> leurs ports se taisent -> un organe COGNITIF sans rapport devient
    indemarrable, et personne ne nommait le lien.

    Trois etats par port : `ECOUTE` · `MUET` · `ILLISIBLE` (la sonde elle-meme a
    echoue pour une raison qui n'est pas un refus de connexion).
    """
    import socket

    svcs, err = _services_declares()
    if err:
        return {"organe": organe, "etat": "illisible", "raison": err, "ports": {}}
    spec = None
    for nom, s in svcs.items():
        hb = s.get("heartbeat")
        if hb and Path(hb).stem == organe:
            spec = s
            break
    if spec is None:
        return {"organe": organe, "etat": "hors_registre", "ports": {}}
    deps = [d for d in (spec.get("deps") or []) if isinstance(d, int)]
    if not deps:
        return {"organe": organe, "etat": "sans_dependance_port", "ports": {}}
    ports = {}
    for port in deps:
        s = socket.socket()
        s.settimeout(timeout)
        try:
            s.connect(("127.0.0.1", port))
            ports[port] = "ECOUTE"
        except ConnectionRefusedError:
            ports[port] = "MUET"
        except Exception as exc:  # noqa: BLE001
            # Un timeout n'est pas un refus : on ne sait pas si rien n'ecoute ou si
            # le chemin est filtre. Nommer la nuance evite d'accuser un service.
            ports[port] = "MUET (%s)" % type(exc).__name__
        finally:
            s.close()
    muets = [p for p, e in ports.items() if e != "ECOUTE"]
    return {"organe": organe, "service": spec.get("name"),
            "etat": "BLOQUE_PAR_DEPENDANCE" if muets else "dependances_satisfaites",
            "ports": ports, "muets": muets,
            "raison": ("le superviseur ne demarre pas un service dont %d dependance(s) "
                       "declaree(s) ne repondent pas" % len(muets)) if muets else None}


def _pids_des_pouls() -> dict:
    """{organe: pid} lu dans les pouls. Valeur `None` = pouls illisible ou sans pid.

    ETAT DYNAMIQUE, pas une declaration : `forge_heartbeat.beat_daemon` ecrit le pid
    du processus qui bat. Deux organes qui partagent un pid tournent dans le MEME
    processus — c'est ainsi qu'on attribue un hote a un organe absent du registre,
    sans interroger `psutil` dont la cmdline est vide pour 331 process sur 339 quand
    ils appartiennent a un autre compte.
    """
    out = {}
    base = ROOT / "sandbox"
    try:
        pouls = sorted(base.glob("*.heartbeat"))
    except OSError as e:
        # Le defaut que ce module combat partout : rendre {} ici ferait lire
        # « aucun pouls ne porte de pid » la ou on n'a PAS PU regarder le dossier.
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[nervous_map] sandbox illisible (%s) | consequence : aucun hote ne peut "
            "etre attribue, les launchers sortiront ILLISIBLE et non absent",
            type(e).__name__)
        return out
    for p in pouls:
        try:
            out[p.stem] = json.loads(p.read_text("utf-8", "ignore")).get("pid")
        except Exception:  # noqa: BLE001 - muet-ok : pouls illisible -> pid inconnu
            out[p.stem] = None
    return out


def autorites() -> dict:
    """Qui lance, supervise, redemarre et atteste chaque organe qui bat."""
    svcs, err_toml = _services_declares()
    taches, err_taches = _taches_planifiees()

    # Organe <- pouls declare, pour joindre services.toml et les fichiers du disque.
    par_pouls = {}
    for nom, s in svcs.items():
        hb = s.get("heartbeat")
        if hb:
            par_pouls[Path(hb).stem] = nom

    pouls_disque, err_hb = {}, None
    try:
        from nokido_agent.app import forge_health_diagnostic as _h

        pouls_disque = _h.audit_workers_heartbeat()
    except Exception as e:  # noqa: BLE001
        err_hb = "%s: %s" % (type(e).__name__, e)

    pids = _pids_des_pouls()
    # pid -> organes DU REGISTRE qui battent avec ce pid : l'hote possible.
    hotes = {}
    for org_reg in par_pouls:
        pid = pids.get(org_reg)
        if pid:
            hotes.setdefault(pid, []).append(org_reg)

    organes = sorted(set(par_pouls) | set(pouls_disque))
    fiches = []
    for org in organes:
        nom_svc = par_pouls.get(org)
        spec = svcs.get(nom_svc) if nom_svc else None
        etat_hb = pouls_disque.get(org) or {}
        eteint = etat_hb.get("eteint_par_decision")

        if err_toml:
            f = {k: _champ(None, "illisible") for k in
                 ("owner", "launcher", "supervisor", "restart_authority",
                  "liveness_authority")}
        elif spec is not None:
            runas = spec.get("runAs")
            f = {
                "owner": _champ(runas, "declare") if runas
                else _champ("compte du superviseur", "derive"),
                "launcher": _champ("superviseur services.toml (%s)"
                                   % spec.get("cmd", "?"), "declare"),
                "supervisor": _champ("eteint par decision (disabled=true)", "declare")
                if spec.get("disabled") else _champ("superviseur services.toml",
                                                    "declare"),
                "restart_authority": _champ(
                    "owner (remettre disabled=false)", "derive") if spec.get("disabled")
                else _champ("superviseur (wave/deps)", "derive"),
                "liveness_authority": _champ(
                    "superviseur via heartbeat=%s (tier %s, max %ss)"
                    % (spec.get("heartbeat"), spec.get("heartbeat_tier"),
                       spec.get("heartbeat_max_s")), "declare")
                if spec.get("heartbeat") else _champ(None, "absent"),
            }
        else:
            # Organe qui BAT sans etre au registre. C'est le cas `service_crash_watcher`.
            lanceur = None
            etat_lanceur = "derive"
            # 1. HOTE MESURE : meme pid qu'un organe supervise => il tourne DANS lui.
            _pid = pids.get(org)
            _hotes = hotes.get(_pid) or [] if _pid else []
            if _hotes:
                lanceur = "in-process dans %s (pid %s partage)" % (
                    "/".join(par_pouls[h] for h in _hotes), _pid)
            elif taches is not None:
                for t in taches:
                    if org.lower() in t.lower():
                        lanceur = "tache planifiee %s" % t
                        break
            f = {
                "owner": _champ(None, "absent"),
                # ILLISIBLE et jamais `absent`. Deux raisons MESUREES : (a) nos
                # capteurs ne voient ni les lanceurs de boot du profil owner ni les
                # scripts lances a la main -- c'est la ZONE_MORTE que RULES_SHARED
                # interdit de lire comme une absence ; (b) 24 des 49 pouls n'ecrivent
                # AUCUN pid (ils reimplementent le geste au lieu d'appeler
                # `beat_daemon`), donc la jointure par processus ne peut pas trancher.
                # Dire « aucun lanceur » ici, ce serait conclure d'une source muette.
                "launcher": _champ(lanceur, etat_lanceur) if lanceur
                else _champ(None, "illisible"),
                # Un organe HEBERGE herite de l'autorite de son hote : relever l'hote
                # le releve. Ce n'est pas une supervision propre -- sa mort SEULE
                # reste silencieuse -- donc `derive`, jamais `declare`.
                "supervisor": _champ("via l'hote %s" % lanceur, "derive") if _hotes
                else _champ(None, "absent"),
                "restart_authority": _champ(
                    "superviseur, en relevant l'hote", "derive") if _hotes
                else _champ(None, "absent"),
                # Il est VU, sans etre supervise : la nuance est tout le sujet.
                "liveness_authority": _champ(
                    "forge_health_diagnostic (VOIT, ne pese pas sur le score)",
                    "derive") if etat_hb else _champ(None, "absent"),
            }
        # MESURE BRUTE (`bat` = fraicheur du pouls) et INFERENCE (`producteur_vivant`)
        # cote a cote, jamais fondues : on garde de quoi rejuger sans re-mesurer.
        _vivant, _preuve = liveness(etat_hb, pids.get(org))
        f.update({"organe": org, "service": nom_svc,
                  "au_registre": nom_svc is not None,
                  "eteint_par_decision": eteint,
                  "producteur_vivant": _vivant, "producteur_preuve": _preuve,
                  # `pid` absent = pouls qui n'est PAS ecrit par `beat_daemon` : son
                  # porteur est inattribuable. C'est la condition qui bloque la
                  # jointure, donc elle se rapporte au lieu de disparaitre.
                  "pid": pids.get(org),
                  "bat": etat_hb.get("alive"), "age_s": etat_hb.get("age_s")})
        fiches.append(f)

    return {"organes": fiches, "n": len(fiches),
            "sources": {"services.toml": err_toml or "ok (%d services)" % len(svcs),
                        "taches_planifiees": err_taches or ("ok (%d)" % len(taches)
                                                            if taches is not None
                                                            else "illisible"),
                        "pouls_disque": err_hb or "ok (%d)" % len(pouls_disque)}}


def lacunes_autorite() -> list:
    """Organes sans autorite de redemarrage, ou dont on n'a PAS pu lire l'autorite.

    Un organe eteint par decision n'est pas une lacune : c'est un choix, et l'accuser
    fabrique un faux positif de plus.
    """
    out = []
    a = autorites()
    for f in a["organes"]:
        if f.get("eteint_par_decision"):
            continue
        # Un organe supervise qui ne bat pas peut etre BLOQUE EN AMONT plutot que mort :
        # on le qualifie avant de le compter comme lacune (sonde a la demande, sur les
        # seuls organes silencieux — pas sur toute la flotte).
        if f.get("au_registre") and f.get("producteur_vivant") == VIVANT_NON:
            dep = dependances_bloquantes(f["organe"])
            if dep.get("etat") == "BLOQUE_PAR_DEPENDANCE":
                out.append({"organe": f["organe"], "etat": "BLOQUE_PAR_DEPENDANCE",
                            "bat": False, "age_s": f.get("age_s"),
                            "liveness": f["liveness_authority"]["valeur"],
                            "launcher": f["launcher"]["valeur"],
                            "raison": "%s — ports muets: %s" % (dep["raison"],
                                                                dep["muets"])})
                continue
        ra = f["restart_authority"]
        if ra["etat"] in ("absent", "illisible"):
            out.append({"organe": f["organe"], "etat": ra["etat"],
                        "bat": f.get("bat"), "age_s": f.get("age_s"),
                        "liveness": f["liveness_authority"]["valeur"],
                        "launcher": f["launcher"]["valeur"],
                        "raison": "aucun superviseur ne peut le relever ; sa mort "
                                  "n'a pas de suite" if ra["etat"] == "absent"
                                  else "autorite NON LUE, ce n'est pas une absence"})
    return out


def integrate() -> dict:
    try:
        from nokido_agent.app.forge_keeper_base import declare
        declare("nervous_map", owns="inventaire unifié + plug cortex/SN de tous les composants",
                owner_module="forge_nervous_map", how="nervous_map/plug_report")
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "note": str(e)}


def _selftest() -> int:
    ok = total = 0

    def chk(c, label):
        nonlocal ok, total
        total += 1
        ok += bool(c)
        print(f"  [{'OK' if c else 'FAIL'}] {label}")

    m = nervous_map()
    c = m["counts"]
    chk(c["daemons"] >= 20, f"daemons découverts (services.toml): {c['daemons']}")
    chk(c["roles"] >= 10, f"rôles découverts (AgentRole): {c['roles']}")
    chk(c["organ_agents"] >= 20, f"organ-agents (keepers+flux+census): {c['organ_agents']}")
    chk(c["hooks"] >= 3, f"hooks locaux découverts: {c['hooks']}")
    chk(c["cortex"] == len(CORTEX) and c["nervous_system"] == len(NERVOUS),
        f"cortex={c['cortex']} SN={c['nervous_system']}")
    pr = plug_report()
    chk("severed" in pr and "vanished" in pr and "healthy" in pr,
        f"plug report v2 — severed={len(pr['severed'])} vanished={len(pr['vanished'])} sain={pr['healthy']}")
    chk(isinstance(reachability(), list) and isinstance(drift(), dict),
        "reachability (nerf sectionné) + drift (baseline) opérationnels")
    chk(m["total"] >= 60, f"inventaire total >= 60 composants ({m['total']})")
    print(f"selftest: {ok}/{total} OK | total composants = {m['total']}")
    return 0 if ok == total else 1


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--plugs", action="store_true")
    ap.add_argument("--snapshot", action="store_true", help="fige l'état courant comme baseline")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    if a.snapshot:
        print(json.dumps(snapshot(), ensure_ascii=False))
        raise SystemExit(0)
    if a.plugs:
        print(json.dumps(plug_report(), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    print(json.dumps(nervous_map(), ensure_ascii=False, indent=2))
