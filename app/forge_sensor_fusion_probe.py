# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ : proprioception / observabilite (organe, READ-ONLY)

ORGANE : FUSION MULTI-CAPTEURS — « ce service est-il vivant ? » demande a TROIS
sources, et NOMME leurs desaccords au lieu de trancher en silence.

Item 3 du pack P2 des veilles (spec_pack_veilles_p2, lot Multi-view priors) : une
sonde unique est AMBIGUE. Un port ouvert ne dit pas que le service est revendique ;
un registre qui dit `stopped` ne dit pas que le processus est mort ; un heartbeat
frais ne dit pas que le port repond.

Cas REEL du 2026-07-24 qui a motive cet organe : `NokidoQdrantServer` etait
`stopped` au registre (pid=None) alors que le port 6333 ECOUTAIT et servait. Chaque
capteur pris seul donnait une reponse fausse ; c'est leur DESACCORD qui portait
l'information (« vivant mais non revendique »). Sans cette fusion, le diagnostic
depend du capteur qu'on a interroge en premier.

Anti-dup (rag_fts + lecture) : `forge_health_diagnostic` collecte deja les trois
familles (`audit_workers_heartbeat`, `audit_services_http`, `audit_supervised_fleet`)
mais SEPAREMENT, a l'echelle de la flotte, sans les croiser par service ni exposer
les contradictions. `forge_port_reconcile` compare registre et listeners pour AGIR
(tuer les fantomes) ; ici on ne fait qu'OBSERVER et rapporter. On REUTILISE sa
lecture du registre plutot que d'en ecrire une autre.

STRICTEMENT READ-ONLY : aucune action lifecycle, jamais.

CLI :
    LAFORGE_PYTHON app/forge_sensor_fusion_probe.py --service NokidoQdrantServer
    LAFORGE_PYTHON app/forge_sensor_fusion_probe.py --all
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / "sandbox"

# Au-dela, un heartbeat n'atteste plus rien (les organes battent au plus toutes les 5 min).
HEARTBEAT_STALE_S = float(os.environ.get("LAFORGE_HB_STALE_S", "900"))


def _registry() -> dict:
    """{port: (service, pid)} des services RUNNING — on DEMANDE au proprietaire."""
    try:
        app_dir = str(ROOT / "app")
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        from nokido_agent.app.forge_port_reconcile import _supervisor_ports

        return _supervisor_ports() or {}
    except Exception:  # noqa: BLE001
        return {}


def _via_launcher(service: str) -> bool:
    """Le service passe-t-il par un lanceur (`runAs = "interactive"`) ?

    Dans ce cas le pid du registre est celui du LANCEUR, dont la mort est
    attendue : il ne dit RIEN de la vitalite du process reel.
    """
    return (_declared_services().get(service) or {}).get("runas") == "interactive"


def _pid_alive(pid) -> bool | None:
    """Le pid revendique par le registre correspond-il a un process VIVANT ?

    QUATRIEME capteur, et le seul qui couvre les services sans port ni heartbeat.
    Mesure 26-07 : 10 services etaient `status=running` sans aucun moyen de le
    verifier (CIRunner, CommWatch, GateConsumer, Graph, OpenAIProxy,
    ParietalFusion, PhenomBuffer, QuotaAlertDaemon, SSoTMaintainer,
    TraceSidecar) -- le superviseur les declarait vivants et personne ne pouvait
    le contredire. Or il expose leur pid : il suffisait de le DEMANDER a l'OS.

    Gratuit et sans toucher aux modules : `pid_exists` reste lisible sans
    privilege, la ou `cmdline()` est refuse sur 308 process sur 308.
    None = pas pu voir, jamais « mort ».
    """
    if not pid:
        return None
    try:
        import psutil

        return bool(psutil.pid_exists(int(pid)))
    except Exception:  # noqa: BLE001
        return None


def _port_listens(port: int, timeout: float = 1.5) -> bool | None:
    """True/False, ou None si on n'a pas pu sonder (ne pas confondre avec 'ferme')."""
    if not port:
        return None
    try:
        s = socket.socket()
        s.settimeout(timeout)
        try:
            return s.connect_ex(("127.0.0.1", int(port))) == 0
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        return None


_SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"
_HB_DECLARED: dict[str, str] | None = None


def _declared_heartbeats() -> dict[str, str]:
    """{service: chemin heartbeat} tel que DECLARE dans services.toml.

    On DEMANDE au registre quel fichier fait foi au lieu de le deviner. Deviner par
    convention de nom (`<service>.heartbeat`) faisait ramasser des fichiers ORPHELINS
    d'anciens services : mesure 24-07, `NokidoWebHub` — qui ne declare AUCUN
    heartbeat — se voyait attribuer un residu de 20,6 jours et etait rapporte
    « capteur gele ». C'est le travers « identifier par nom » deja paye ailleurs.
    """
    global _HB_DECLARED
    if _HB_DECLARED is not None:
        return _HB_DECLARED
    out: dict[str, str] = {}
    try:
        txt = _SERVICES_TOML.read_text(encoding="utf-8", errors="replace")
        for bloc in txt.split("[[service]]")[1:]:
            m = re.search(r'name\s*=\s*"([^"]+)"', bloc)
            hb = re.search(r'^\s*heartbeat\s*=\s*"([^"]+)"', bloc, re.M)
            if m and hb:
                out[m.group(1)] = hb.group(1)
    except Exception:  # noqa: BLE001
        pass
    _HB_DECLARED = out
    return out


def _heartbeat_age(service: str) -> float | None:
    """Age du heartbeat DECLARE, ou None si le service n'en declare pas.

    None se lit « non applicable », jamais « gele » : un service sans heartbeat
    declare n'a rien promis, on ne lui reproche pas de ne pas battre.
    """
    rel = _declared_heartbeats().get(service)
    if not rel:
        return None
    try:
        cand = ROOT / rel
        if cand.exists():
            return max(0.0, time.time() - cand.stat().st_mtime)
    except OSError:
        pass
    return None


def _fleet() -> dict[str, dict]:
    """{service: {status, pid, port, heartbeat_path}} — le superviseur, pour TOUS.

    `_supervisor_ports()`, reutilise a l'origine, filtre `status == running` ET
    `port` ET `pid` : 18 entrees sur les 52 que le superviseur connait. Il expose
    pourtant `status` (running / sleeping / stopped), `pid` et `heartbeat_path`
    pour chacun d'eux. On DEMANDE au proprietaire son etat complet au lieu de
    deduire d'une vue appauvrie -- c'est la meme regle que « la propriete se
    demande a l'organe, jamais ne se deduit ».
    """
    import urllib.request

    out: dict[str, dict] = {}
    try:
        app_dir = str(ROOT / "app")
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        from nokido_agent.app.forge_port_reconcile import SUPERVISOR

        with urllib.request.urlopen(SUPERVISOR, timeout=4) as r:
            svc = json.loads(r.read()).get("services", {})
        for name, info in svc.items():
            out[name] = {
                "status": info.get("status"),
                "pid": info.get("pid"),
                "port": info.get("port"),
                "heartbeat_path": info.get("heartbeat_path"),
            }
    except Exception:  # noqa: BLE001
        pass
    return out


_DECL_SERVICES: dict[str, dict] | None = None


def _declared_services() -> dict[str, dict]:
    """{service: {"port": int|None, "disabled": bool}} tel que DECLARE dans services.toml.

    MEME source que `_declared_heartbeats()` : une declaration explicite, pas une
    devinette -- la prudence de l'origine (« on ne devine pas les absents ») reste
    donc respectee.

    Pourquoi : `_registry()` n'expose que les services RUNNING **avec port**. Mesure
    26-07 : 18 services sondes sur ~52 declares, et l'intersection avec les 33
    porteurs de heartbeat etait STRICTEMENT VIDE -- la fusion tournait donc a deux
    capteurs sur trois, structurellement incapable de detecter le cas qu'elle vise
    (« le port sert pendant que le heartbeat gele »). Les 34 services restants
    n'etaient ni sains ni malades : ABSENTS, ce qui se lit a tort comme « rien a
    signaler ». Un service qu'on ne sait pas sonder doit ressortir
    `indeterminable`, jamais etre omis.
    """
    global _DECL_SERVICES
    if _DECL_SERVICES is not None:
        return _DECL_SERVICES
    out: dict[str, dict] = {}
    try:
        txt = _SERVICES_TOML.read_text(encoding="utf-8", errors="replace")
    except OSError:
        _DECL_SERVICES = {}
        return _DECL_SERVICES
    for bloc in txt.split("[[service]]")[1:]:
        m = re.search(r'^\s*name\s*=\s*"([^"]+)"', bloc, re.M)
        if not m:
            continue
        mp = re.search(r"^\s*port\s*=\s*(\d+)", bloc, re.M)
        md = re.search(r"^\s*disabled\s*=\s*(true|false)", bloc, re.M)
        mr = re.search(r'^\s*runAs\s*=\s*"([^"]+)"', bloc, re.M)
        out[m.group(1)] = {
            "port": int(mp.group(1)) if mp else None,
            "disabled": bool(md and md.group(1) == "true"),
            "runas": mr.group(1) if mr else None,
        }
    _DECL_SERVICES = out
    return out


_HB_LIMITS: dict[str, float] | None = None


def _organ_intervals() -> dict[str, float]:
    """`HB_INTERVAL_S` de forge_organ_pulse — cadences DECLAREES des organes lents.

    Lu par regex plutot qu'importe : `forge_organ_pulse` est un daemon, l'importer
    pour une constante exposerait a ses effets de bord au chargement. La valeur
    reste a UN seul endroit, on ne la duplique pas.
    """
    global _HB_LIMITS
    if _HB_LIMITS is not None:
        return _HB_LIMITS
    out: dict[str, float] = {}
    try:
        txt = (ROOT / "tools" / "forge_organ_pulse.py").read_text(
            encoding="utf-8", errors="replace")
        bloc = re.search(r"HB_INTERVAL_S\s*=\s*\{(.*?)\}", txt, re.S)
        if bloc:
            for k, v in re.findall(r'"([^"]+)"\s*:\s*(\d+)', bloc.group(1)):
                out[k] = float(v)
    except Exception:  # noqa: BLE001
        pass
    _HB_LIMITS = out
    return out


def _heartbeat_limit(service: str) -> float:
    """Seuil de fraicheur PAR ORGANE, jamais uniforme.

    Un seuil unique accuse les organes lents : `log_retention` bat toutes les 24 h
    et `skill_curator` toutes les 6 h PAR DESIGN. Mesure 26-07 : au seuil uniforme
    de 900 s, tous deux ressortaient « heartbeat gele » alors qu'ils tenaient leur
    cadence. Les seuils fixes uniformes sont la cause deja mesuree de l'embolie
    cortisol du 22-07 -- on ne la re-paie pas ici.

    Marge x2 : un organe a 24 h n'est en retard qu'au-dela de 48 h.

    ORDRE DES SOURCES, du plus direct au moins direct (ajout 2026-08-23) : le
    heartbeat lui-meme porte souvent `interval_s`, c'est-a-dire l'organe DECLARANT
    SON PROPRE RYTHME. On le prefere a `HB_INTERVAL_S`, table tenue a la main dans
    `forge_organ_pulse` et forcement incomplete -- `NokidoRSSWatcher` y manquait,
    retombait au seuil global de 900 s et ressortait « muet » alors que son propre
    pouls annonce un cycle de 21 600 s. On ne cherche pas la frequence cardiaque
    d'un patient dans un tableau de reference quand on peut la lire sur lui.
    """
    rel = _declared_heartbeats().get(service)
    if not rel:
        return HEARTBEAT_STALE_S
    # 1) le pouls lui-meme, s'il declare sa cadence
    try:
        import json as _js

        contenu = _js.loads((ROOT / rel).read_text(encoding="utf-8", errors="replace"))
        cadence = float(contenu.get("interval_s") or 0)
        if cadence > 0:
            return cadence * 2.0
    except Exception:  # noqa: BLE001  # muet-ok : le pouls peut etre absent, vide
        # ou sans cadence declaree ; on passe simplement a la source suivante, et
        # l'echec de TOUTES est signale par le repli explicite en fin de fonction.
        pass
    # 2) la table declarative, tenue a la main
    cadence = _organ_intervals().get(Path(rel).stem)
    if cadence:
        return cadence * 2.0
    # 3) repli global, assume : faute de cadence connue, on juge au seuil commun
    return HEARTBEAT_STALE_S


_NON_SONDE = object()  # sentinelle : « pas de pre-sonde », distincte de None (= sonde ILLISIBLE)


def probe(service: str, port: int | None = None, _ecoute: Any = _NON_SONDE) -> dict[str, Any]:
    """Croise registre / port / heartbeat pour UN service.

    Le verdict n'est jamais rendu par un capteur seul : c'est la combinaison, et
    surtout les DESACCORDS, qui portent l'information.

    `_ecoute` : resultat d'une pre-sonde du port `port` faite par `probe_all`. Absent,
    `probe` sonde lui-meme (appel isole, CLI). None transmis reste None : une sonde
    illisible n'est ni refaite ni lue comme « ferme ».
    """
    ent = _fleet().get(service) or {}
    reg_status = ent.get("status")
    reg_pid = ent.get("pid")
    reg_port = int(ent["port"]) if ent.get("port") else None
    if not ent:  # superviseur muet : repli sur la vue par port
        for p, (name, pid) in _registry().items():
            if name == service:
                reg_port, reg_pid, reg_status = int(p), int(pid), "running"
                break
    claimed = bool(reg_pid) and reg_status == "running"

    use_port = port or reg_port
    if _ecoute is not _NON_SONDE and port and use_port == port:
        listening = _ecoute
    else:
        listening = _port_listens(use_port) if use_port else None
    pid_alive = _pid_alive(reg_pid)
    hb_age = _heartbeat_age(service)
    hb_limit = _heartbeat_limit(service)
    hb_fresh = (hb_age is not None and hb_age <= hb_limit)

    disagreements: list[str] = []
    if listening is True and not claimed:
        disagreements.append("le port ECOUTE mais le registre ne revendique pas le service "
                             "(vivant non revendique : personne ne le surveille ni ne le relancera)")
    if claimed and listening is False:
        disagreements.append("le registre revendique le service mais le port NE REPOND PAS "
                             "(revendique mais sourd : liveness sans readiness)")
    if hb_age is not None and not hb_fresh and (claimed or listening):
        disagreements.append(f"le service repond mais son heartbeat a {int(hb_age)}s "
                             f"(> {int(hb_limit)}s, cadence propre a l'organe) : "
                             "capteur gele, pas service mort")
    if reg_status == "stopped" and hb_fresh:
        disagreements.append(
            f"le registre le dit ARRETE mais son heartbeat est frais ({int(hb_age)}s) : "
            "residu du dernier battement, ou process survivant hors registre")
    if reg_status == "running" and pid_alive is False and not _via_launcher(service):
        disagreements.append("le registre revendique le service RUNNING mais son pid "
                             "n'existe plus : FANTOME, personne ne le relancera")
    elif reg_status == "running" and pid_alive is False:
        disagreements.append("pid du LANCEUR mort (runAs=interactive) : normal, mais la "
                             "vitalite du vrai process n'est PAS etablie — remonter l'arbre")
    if listening is None and hb_age is None and not reg_status:
        disagreements.append("AUCUN capteur disponible (ni port declare, ni heartbeat "
                             "declare, ni statut au registre) : zone NON OBSERVABLE, "
                             "« pas pu voir » n'est pas « rien a signaler »")

    # Verdict : on ne tranche que ce que les capteurs permettent de trancher.
    #
    # Le STATUT declare par le superviseur passe EN PREMIER : c'est une intention
    # (« je l'ai endormi »), pas une observation, et elle explique le silence du
    # port. Mesure 26-07 : teste apres les branches de port, un service endormi
    # tombait en « arrete » parce que son port -- ferme par construction --
    # repondait False. On accusait le corps de panne pour avoir obei.
    if reg_status in ("restarting", "starting") and listening is not True:
        # Transitoire ASSUME : pendant un demarrage, ni le port ni le heartbeat
        # n'ont encore de raison de repondre. Les compter contre le service
        # ferait crier a la panne a chaque relance -- et un capteur qui hurle
        # pendant les transitions normales finit par etre ignore.
        verdict = "en_demarrage"
    elif reg_status == "sleeping" and listening is not True:
        verdict = "endormi"
    elif reg_status == "stopped" and listening is not True:
        # Meme regle que `sleeping` : le statut DECLARE prime. Mesure 26-07 :
        # NokidoEpistemicSoif sortait « vivant_par_heartbeat » avec un beat de
        # 639s alors que le superviseur le disait ARRETE — le beat etait le
        # RESIDU du dernier battement avant l'arret. Un fichier frais ne prouve
        # pas la vie, il prouve qu'on a vecu recemment.
        verdict = "arrete"
    elif reg_status == "running" and pid_alive is False and _via_launcher(service):
        # `runAs = "interactive"` passe par un LANCEUR : le superviseur enregistre
        # le pid du cmd.exe, qui MEURT une fois le vrai process spawne. Sa mort est
        # donc ATTENDUE et ne prouve rien. Mesure 26-07 : NokidoCIRunner sortait
        # « fantome » (pid 17780 disparu) alors que Runner.Listener.exe pid 18800
        # tournait et que la CI etait verte. Gotcha deja paye le 16-07 : sur une
        # indirection de lanceur, il faut REMONTER L'ARBRE, pas juger le pid.
        verdict = "launcher_termine"
    elif reg_status == "running" and pid_alive is False:
        verdict = "fantome"
    elif reg_status == "sleeping" and listening is True:
        disagreements.append("le registre le dit ENDORMI mais le port ECOUTE "
                             "(sommeil non effectif, ou un autre process tient le port)")
        verdict = "vivant_non_revendique"
    elif listening is True and claimed:
        verdict = "sain"
    elif listening is True and not claimed:
        verdict = "vivant_non_revendique"
    elif listening is False and claimed:
        verdict = "revendique_mais_sourd"
    elif listening is False and not claimed:
        verdict = "arrete"
    elif hb_fresh:
        # Pas de port a sonder, mais l'organe TEMOIGNE de lui-meme. Le registre
        # n'expose que les services a port : son silence n'est donc pas un
        # reproche, c'est une limite du capteur. Mesure 26-07 : 34 daemons sans
        # port sortaient « indeterminable » alors que leur heartbeat battait.
        verdict = "sain" if claimed else "vivant_par_heartbeat"
    elif pid_alive is True and reg_status == "running":
        # Ni port ni heartbeat, mais le process que le registre nomme EXISTE.
        # Preuve faible (il peut etre fige) -- elle vaut mieux que le silence,
        # et elle est nommee comme telle plutot que rangee en « sain ».
        verdict = "vivant_par_process"
    elif reg_status == "sleeping":
        # Le superviseur l'a ENDORMI : ne pas battre est alors le comportement
        # voulu, pas une panne. Mesure 26-07 : NokidoRSSWatcher etait signale
        # « stale » alors qu'il dormait sur ordre.
        verdict = "endormi"
    elif reg_status == "stopped":
        verdict = "arrete"
    elif hb_age is not None:
        # Heartbeat DECLARE mais rance, et aucun port pour contredire : c'est le
        # signal le plus fort dont on dispose sur un daemon sans port.
        verdict = "heartbeat_gele"
    else:
        verdict = "indeterminable"  # sonde impossible : surtout ne pas dire "sain"

    return {
        "service": service,
        "verdict": verdict,
        "capteurs": {
            "registre": {"revendique": claimed, "pid": reg_pid, "port": reg_port,
                         "status": reg_status},
            "port": {"numero": use_port, "ecoute": listening},
            "process": {"pid": reg_pid, "vivant": pid_alive},
            "heartbeat": {"age_s": round(hb_age, 1) if hb_age is not None else None,
                          "frais": hb_fresh if hb_age is not None else None,
                          "limite_s": int(hb_limit)},
        },
        "desaccords": disagreements,
        "consensus": not disagreements,
    }


def probe_all(include_disabled: bool = False) -> list[dict]:
    """Union du registre ET des services DECLARES dans services.toml.

    Les services `disabled` (on-demand assume, ex. NokidoLlamaNative) sont exclus
    par defaut : ne pas battre n'est pas une panne quand personne ne l'a demande.
    """
    vus: dict[str, int | None] = {}
    for port, (name, _pid) in _registry().items():
        vus[name] = int(port)
    for name, meta in _declared_services().items():
        if name in vus:
            continue
        if meta.get("disabled") and not include_disabled:
            continue
        vus[name] = meta.get("port")
    ecoutes = _ports_en_parallele(vus.values())
    return [probe(n, port=p, _ecoute=ecoutes[int(p)] if p else _NON_SONDE)
            for n, p in sorted(vus.items())]


def _ports_en_parallele(ports) -> dict[int, bool | None]:
    """Sonde chaque port connu UNE fois, en parallele. {port: True/False/None}.

    Mesure 2026-09-24 (job_4b71d0923ef2) : `coverage()` coutait 18,85 s dont 18,10 s de
    `_port_listens` EN SERIE -- 12 ports de services endormis, chacun jusqu'au delai de
    1,50 s (boucle locale Windows : un port ferme ne se refuse qu'apres les reemissions du
    SYN). 48 % de la phase health pour savoir que des services endormis dorment.

    Le capteur n'est pas touche (meme delai, meme None si la sonde est impossible) : seul
    l'ordonnancement change. Le port est desormais sonde un peu AVANT la lecture du
    registre de son service (au plus un delai de sonde d'ecart, contre quelques ms) : un
    service qui change d'etat dans cette fenetre peut sortir en desaccord transitoire, et
    le desaccord le NOMME -- rien n'est tranche en silence.
    """
    from concurrent.futures import ThreadPoolExecutor

    uniques = sorted({int(p) for p in ports if p})
    if not uniques:
        return {}
    with ThreadPoolExecutor(max_workers=min(16, len(uniques)),
                            thread_name_prefix="fusion_ports") as ex:
        return dict(zip(uniques, ex.map(_port_listens, uniques)))


def coverage() -> dict:
    """Combien d'organes le corps sait-il REELLEMENT observer, et par quoi.

    Repond a la question posee le 26-07 (« le corps doit couvrir l'ensemble de ce
    qui tourne, sinon l'autoregulation ne fonctionnera jamais ») par un chiffre
    plutot que par une impression.
    """
    probes = probe_all()
    par_verdict: dict[str, int] = {}
    for p in probes:
        par_verdict[p["verdict"]] = par_verdict.get(p["verdict"], 0) + 1
    observables = sum(
        1 for p in probes
        if p["capteurs"]["port"]["ecoute"] is not None
        or p["capteurs"]["heartbeat"]["age_s"] is not None
    )
    return {
        "services_sondes": len(probes),
        "observables": observables,
        "zones_non_observables": len(probes) - observables,
        "par_verdict": par_verdict,
        "en_desaccord": [p["service"] for p in probes if p["desaccords"]],
    }


def _main() -> int:
    ap = argparse.ArgumentParser(description="Fusion multi-capteurs (lecture seule)")
    ap.add_argument("--service")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    if a.all or not a.service:
        res = probe_all()
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 1 if any(r["desaccords"] for r in res) else 0
    r = probe(a.service)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 1 if r["desaccords"] else 0


if __name__ == "__main__":
    sys.exit(_main())
