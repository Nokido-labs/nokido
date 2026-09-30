#!/usr/bin/env python3
"""forge_ensure_service.py — BACKEND du « Bouton Rouge » MCP nokido_ensure_service.

Absorbe une INTENTION déclarative {service, desired_state} et orchestre les
capacités SERVIES de Nokido (forge_docker_agent / forge_searxng_keeper /
forge_supervisor_ctl). ZÉRO réinvention : on câble l'existant. Lancé en
LaForgeTrusted par le handler MCP (spawn_as_trusted). Sortie = JSON (dernière ligne).

But : le client (Claude/agy) ne fait QUE déclarer « je veux SearXNG up » ; tout
l'impératif (privilèges SeTcbPrivilege, daemon Docker, conteneurs, NSSM) reste ici.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

try:
    from nokido_agent.app.forge_python_bin import LAFORGE_PYTHON
except Exception:
    LAFORGE_PYTHON = __import__("os").path.expanduser(r"~/miniforge3/python.exe")

# service convivial -> nom de service supervisor Nokido<...>
SVC_MAP = {
    "searxng": "NokidoSearxng", "docker": None, "hub": "NokidoMCP",
    "ollama": "NokidoOllama", "netcfg": "NokidoNetcfgUI", "webhub": "NokidoWebHub",
    "graph": "NokidoGraphExplorer", "embed": "NokidoLlamaEmbed",
    # `lmstudio` n'est PAS ici : aucun service Windows `NokidoLMStudio` n'existe
    # (`sc query` -> 1060). Il est intercepte plus bas et pilote par son CLI.
    "watchagent": "NokidoWatchAgent",
    # Ajoute le 2026-09-18, en meme temps que sa declaration au boot : le pont TUI
    # n'etait connu d'aucune route gouvernee. `graph` y figurait, `tui` non — donc le
    # relever exigeait un appel nu a /supervisor/restart, qui repond 401 sans le jeton.
    # Un service declare que la route gouvernee ignore est une dette de cablage : la
    # capacite existe cote superviseur et reste hors de portee de l'agent.
    "tui": "NokidoTuiBridge",
    # Ajoutes le 2026-09-18 : ces deux services sont `disabled = true` au TOML, et
    # l'owner veut qu'ils le RESTENT -- ils coutent ~4,3 Go par chargement et il les a
    # coupes pour cette raison le 2026-09-05. Ce qui manquait n'etait pas leur
    # activation, c'etait un CHEMIN pour les lancer a la demande depuis l'ecran :
    # cliquer leur tuile renvoyait vers /launcher, qui ne connait que graph, hub et
    # tui_bridge -- un renvoi vers une page sans bouton, ce que l'owner appelle avec
    # raison une « tuile morte ».
    # Le superviseur, lui, SAIT deja reveiller un service disabled : cf.
    # `proxy_deno/core/supervisor.ts` (« fix wake-disabled 2026-06-03 », log
    # `[service/start] reveil on-demand "<nom>" (disabled -> state cree)`). On ne
    # construit donc rien : on nomme la capacite pour qu'elle devienne atteignable.
    "llamacpp_chat": "NokidoLlamaNative",
    "llamacpp_api": "NokidoLlamaPython",
    # Ajoutes le 2026-09-22, meme raison qu'au-dessus : la capacite existait
    # cote superviseur et restait hors de portee de l'agent. Ce sont les DRAINS
    # des files de taches -- sans eux, `task action=assign agent=ANTIGRAVITY`
    # ecrit dans une file que PERSONNE ne depile.
    #
    # Mesure du jour : le drain s'etait arrete a 10:32 (heartbeat prouve de 60 s,
    # muet 3 h 53). Aucun nom gouverne ne permettait de le relever -- il a fallu
    # que l'owner le relance a la main, et il a raison de dire qu'il ne devrait
    # pas avoir a le faire.
    #
    #     UN SERVICE NON DECLARE NE REVIENT JAMAIS (mesure 2026-09-14).
    #     Deposer une tache oblige a verifier que le drain tourne ; encore
    #     faut-il POUVOIR le relever quand il ne tourne pas.
    "taskexec_antigravity": "NokidoTaskExecutorAntigravity",
    "taskexec_agy": "NokidoTaskExecutorAgy",
}


def _supervisor(action: str, name: str, timeout: int = 90) -> dict:
    """action in ensure|stop|restart — via l'outil servi forge_supervisor_ctl.

    Lance PAR le hub (`nokido_ensure_service`) : le marqueur dit a ctl de parler au
    superviseur directement, jamais de rappeler le hub (2026-09-28 : refus en ring 4, et
    recursion hub -> ctl -> hub si l'identite de ctl avait ete provisionnee)."""
    env = dict(os.environ)
    env["NOKIDO_CTL_DIRECT"] = "1"
    r = subprocess.run(
        [LAFORGE_PYTHON, str(ROOT / "tools" / "forge_supervisor_ctl.py"), action, name],
        capture_output=True, text=True, errors="replace", timeout=timeout, env=env,
    )
    return {"rc": r.returncode, "out": (r.stdout or "")[-400:], "err": (r.stderr or "")[-200:]}


# service convivial -> sonde readiness HTTP (url, cle_json_requise|""). rc=0 supervisor
# prouve la commande, PAS que le service SERT (un restart a deja laisse embed DOWN
# cette session). On sonde l'issue REELLE ; 503 (llama-server cold-load) => pas pret.
_HEALTH = {
    "hub": ("http://127.0.0.1:8766/health", ""),
    # 7420 = Graph Explorer (FastAPI + Cytoscape), proxy /graph/ du web hub.
    # Sans sonde, `graph` retombait sur le rc du supervisor, qui vaut 0 meme
    # quand le service n'existe pas : d'ou un `success: true` sur du vide.
    "graph": ("http://127.0.0.1:7420/", ""),
    "embed": ("http://127.0.0.1:8099/health", ""),
    "ollama": ("http://127.0.0.1:11434/api/ps", "models"),
    "lmstudio": ("http://127.0.0.1:1234/v1/models", "data"),
    "webhub": ("http://127.0.0.1:7400/", ""),
    "netcfg": ("http://127.0.0.1:7500/", ""),
}


# ── LM STUDIO : pilote par son CLI, pas par un service Windows ──────────────
# `SVC_MAP` le mappait sur `NokidoLMStudio`, qui n'existe pas (`sc query` -> 1060) :
# il n'etait donc NI demarrable NI arretable par Nokido, alors qu'il tient 5,7 Go
# de modeles residents — mesure du 2026-08-18, machine a 98,5 % de RAM, Docker
# refuse par l'homeostat, veille bloquee. Un composant qu'on ne sait pas arreter
# ne participe pas a l'autoregulation : il la subit et la fait echouer.
#
# LM Studio expose `lms server start|stop`. Le binaire vit dans le profil de
# l'owner et reste invisible aux comptes de service : on le resout par plusieurs
# chemins, et `LAFORGE_LMS_BIN` (env ou coffre) tranche quand ils echouent.
_LMS_CHEMINS = (
    r"%LOCALAPPDATA%\Programs\LM Studio\resources\app\.webpack\lms.exe",
    r"%USERPROFILE%\.lmstudio\bin\lms.exe",
    r"%USERPROFILE%\.cache\lm-studio\bin\lms.exe",
)

_PROFIL_OWNER = os.environ.get("LAFORGE_OWNER_PROFILE", r"%USERPROFILE%")
_LMS_ABSOLUS = (
    _PROFIL_OWNER + r"\.lmstudio\bin\lms.exe",
    _PROFIL_OWNER + r"\AppData\Local\Programs\LM Studio\resources\app\.webpack\lms.exe",
    _PROFIL_OWNER + r"\AppData\Roaming\npm\lms.cmd",
)


def _lms_bin() -> str | None:
    """Chemin du CLI `lms`, ou None. None = NON MESURE, jamais « absent »."""
    impose = os.environ.get("LAFORGE_LMS_BIN")
    if not impose:
        try:
            _app = str(ROOT / "app")
            if _app not in sys.path:
                sys.path.insert(0, _app)
            from nokido_agent.app.forge_secrets import get_secret

            impose = get_secret("LAFORGE_LMS_BIN") or ""
        except Exception:  # noqa: BLE001 - coffre indisponible
            impose = ""
    if impose and os.path.exists(impose):
        return impose
    for motif in _LMS_CHEMINS:
        chemin = os.path.expandvars(motif)
        if "%" not in chemin and os.path.exists(chemin):
            return chemin
    return shutil.which("lms") or shutil.which("lms.cmd")


def _lms_jeton() -> str:
    """LM Studio rend 401 sans jeton : sonder sans lui le declare mort a tort."""
    try:
        _app = str(ROOT / "app")
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret("LMSTUDIO_TOKEN") or ""
    except Exception:  # noqa: BLE001 - coffre indisponible
        return ""


# ⚠️ SOUS le cap de 120 s de l'appel MCP, jamais egal : a 120 s le depassement
# est certain, et l'appelant recoit un timeout au lieu d'un verdict.
_LMS_TIMEOUT_S = 55.0


def _lms_owner(ordre: list[str], timeout: float = _LMS_TIMEOUT_S) -> dict | None:
    """Joue `lms <ordre>` dans la SESSION CONSOLE de l'owner, ou None si le pont
    est hors de portee.

    MESURE 2026-08-18 : ni `LaForgeSbxOffline` ni `LaForgeTrusted` n'atteignent
    `%USERPROFILE%\\.lmstudio` — `PermissionError [WinError 5]`, PAS
    `FileNotFoundError` : le dossier EXISTE, l'ACL du profil le ferme. Et meme
    avec le chemin, lancer sous SYSTEM ferait chercher les modeles dans
    `config\\systemprofile` : LM Studio est per-user, il n'a de sens que dans la
    session de l'owner. D'ou `forge_owner_bridge`, deja ecrit pour Docker/WSL
    qui posent le meme probleme. ZERO reinvention.
    """
    try:
        from nokido_agent.tools.forge_owner_bridge import run_in_owner
    except Exception:  # noqa: BLE001 - pont indisponible (droits, import)
        return None
    # MESURE : le child garde le %USERPROFILE% de SYSTEM (config\systemprofile),
    # pas celui de l'owner — un chemin en %USERPROFILE% rend « chemin introuvable »
    # meme quand le binaire existe. D'ou des chemins ABSOLUS.
    args = " ".join(ordre)
    cmd = " || ".join([f'"{c}" {args}' if c.endswith((".exe", ".cmd")) else f"{c} {args}"
                       for c in ("lms", *_LMS_ABSOLUS)])
    # Si aucun candidat ne mord, la trace doit dire OU chercher, pas « echec ».
    # ⚠️ BORNE : un `where /r` sur tout le profil owner a fait depasser les 120 s
    # de l'appel MCP (mesure 2026-08-18). Un diagnostic qui coute plus cher que
    # le geste qu'il eclaire n'est pas un diagnostic. On ne balaie que les deux
    # dossiers ou LM Studio pose son CLI.
    # « Acces refuse » sur un binaire qui existe ne dit rien sans l'identite du
    # child : c'est elle qui distingue « mauvais compte » de « mauvaise ACL ».
    diag = " & ".join(
        ["whoami", "echo UP=%USERPROFILE%"]
        + ['if exist "%s" where /r "%s" lms.exe' % (d, d)
           for d in (_PROFIL_OWNER + r"\.lmstudio",
                     _PROFIL_OWNER + r"\AppData\Local\Programs\LM Studio")]
    )
    try:
        return run_in_owner([cmd, diag], timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stdout": f"{type(exc).__name__}: {exc}", "rc": None}


# Tache planifiee = le SEUL canal mesure qui execute sous l'identite de l'owner.
# MESURE 2026-08-18 : le child de `forge_owner_bridge` rend
# `desktop-xxxx\laforgetrusted` et `USERPROFILE=C:\Users\Default` — il est
# bien dans la SESSION interactive, mais avec le token LaForgeTrusted, d'ou
# « Acces refuse » sur un binaire qui EXISTE. Le docstring du pont promet la
# session console « de l'owner (user) » : la promesse porte sur la session,
# pas sur l'identite. Precedent en place : `Nokido-ConvIndex` tourne « en tant
# qu'utilisateur : user », et `bash_guard` autorise deja `schtasks Nokido-*`.
_LMS_TACHES = {"running": "Nokido-LMStudio-Start",
               "stopped": "Nokido-LMStudio-Stop"}


def _etat_tache(nom: str) -> str:
    """« ok » | « refusee » | « absente ».

    ⚠️ Les deux derniers ne sont PAS le meme fait, et les confondre coute une
    enquete : une tache creee par l'owner est invisible aux autres comptes
    (« Acces refuse » des le `/query`), et un simple booleen la ferait chercher
    comme un fantome au lieu de faire ouvrir un droit. Meme distinction que
    « chemin introuvable » (absent) contre « acces refuse » (present, ACL).
    """
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", nom], capture_output=True,
                           text=True, errors="replace", timeout=20)
    except Exception:  # noqa: BLE001 - planificateur injoignable
        return "absente"
    if r.returncode == 0:
        return "ok"
    sortie = ((r.stdout or "") + (r.stderr or "")).lower()
    # schtasks est localise : ne pas s'appuyer sur un seul libelle.
    if "refus" in sortie or "denied" in sortie or "5" == str(r.returncode):
        return "refusee"
    return "absente"


def _tache_existe(nom: str) -> bool:
    return _etat_tache(nom) == "ok"


def declencher_tache(nom: str) -> str | None:
    """Declenche une tache planifiee et rend la trace, ou None si elle n'existe
    pas. PUBLIQUE : `forge_resource_manager` s'en sert pour decharger les
    modeles LM Studio — en recopier la structure ferait mordre le detecteur de
    clones, qui groupe par forme AST et non par nom.

    `schtasks /run` rend AUSSITOT : c'est l'EFFET qui devra etre mesure ensuite,
    jamais ce code de retour.
    """
    if not nom:
        return None
    etat = _etat_tache(nom)
    if etat == "refusee":
        # On NOMME l'ACL plutot que de laisser le pont echouer sur autre chose :
        # sans ce message, la prochaine enquete cherchera une tache absente.
        # ⚠️ Et on nomme le compte MESURE, jamais un compte suppose : j'avais
        # deduit « LaForgeTrusted » de l'identite du child du pont, ce qui ne
        # prouve rien sur le parent — un droit accorde au mauvais compte se
        # solde par un refus identique, donc par une enquete pour rien.
        qui = os.environ.get("USERNAME") or "?"
        return (f"[tache {nom}] EXISTE mais INVISIBLE depuis ce compte (ACL). "
                f"Compte MESURE ici : '{qui}'. Accorder a CE compte la lecture "
                f"+ execution sur la tache (son descripteur vit dans le "
                f"registre TaskCache, pas dans le fichier XML).")
    if etat != "ok":
        return None
    try:
        r = subprocess.run(["schtasks", "/run", "/tn", nom], capture_output=True,
                           text=True, errors="replace", timeout=30)
        return f"[tache {nom} rc={r.returncode}] {(r.stdout or r.stderr or '')[-120:]}"
    except Exception as exc:  # noqa: BLE001
        return f"[tache {nom}] {type(exc).__name__}: {exc}"


def _lms_tache(desire: str) -> str | None:
    """La tache planifiee correspondant a l'etat vise, si elle existe."""
    return declencher_tache(_LMS_TACHES.get(desire) or "")


def _attendre_port(vise: bool, secondes: float = 30.0) -> bool:
    """Attend que le port prenne l'etat vise. Un demarrage de LM Studio n'est
    pas instantane : conclure des le retour du declencheur fabriquerait un
    « port muet » sur un serveur qui monte encore (defaut paye le 2026-08-18
    sur les backends locaux, ou un 7B a froid passait pour mort)."""
    fin = time.time() + secondes
    while time.time() < fin:
        if _sonde_lmstudio(timeout=2.0) is vise:
            return True
        time.sleep(2.0)
    return _sonde_lmstudio(timeout=2.0) is vise


def _lmstudio(desire: str) -> dict:
    """running | stopped | restarted, par le CLI. `stopped` LIBERE 5,7 Go."""
    binaire = _lms_bin()
    ordres = {"running": ["server", "start"], "stopped": ["server", "stop"]}
    if desire == "restarted":
        _jouer(binaire, ["server", "stop"], "stopped")
        ordre = ["server", "start"]
    else:
        ordre = ordres.get(desire) or []
    if not ordre:
        return {"service": "lmstudio", "desired": desire, "success": False,
                "detail": f"desired_state invalide: {desire}"}

    # Etat AVANT le geste : sans lui, un arret sur un port deja muet s'annonce
    # « RAM des modeles liberee » alors que rien ne tournait — un journal qui
    # credite une liberation imaginaire fait surestimer la memoire disponible.
    servait = _sonde_lmstudio(timeout=2.0)
    libre_avant = _ram_libre_go()
    if desire == "stopped" and not servait:
        marquer_pilotage(False)
        return {"service": "lmstudio", "desired": desire, "success": True,
                "detail": "deja arrete : port 1234 muet, RIEN a liberer"}

    trace = _jouer(binaire, ordre, "running" if desire == "restarted" else desire)
    if trace is None:
        return {"service": "lmstudio", "desired": desire, "success": False,
                "detail": "NON MESURE : ni CLI local ni pont session owner "
                          "(forge_owner_bridge). Poser LAFORGE_LMS_BIN, ou lancer "
                          "depuis un contexte detenant SeTcbPrivilege"}

    if desire == "stopped":
        # Un arret se prouve par le port QUI SE TAIT, jamais par le rc du CLI.
        ok = _attendre_port(False, 20.0)
        if not ok:
            return {"service": "lmstudio", "desired": desire, "success": False,
                    "detail": f"port toujours ouvert apres stop : {trace[-160:]}"}
        # Le delta MESURE, jamais « RAM rendue » par principe : un serveur sans
        # modele resident ne rend rien en s'arretant, et l'annoncer ferait
        # surestimer la memoire disponible dans le journal de regulation.
        rendu = round(_ram_libre_go() - libre_avant, 2)
        marquer_pilotage(False)
        return {"service": "lmstudio", "desired": desire, "success": True,
                "detail": (f"arrete : port 1234 s'est tu, {rendu:+.2f} Go rendus"
                           if abs(rendu) >= 0.1 else
                           "arrete : port 1234 s'est tu, RAM inchangee "
                           "(aucun modele n'etait resident)")}
    ok = _attendre_port(True, 30.0)
    if ok:
        marquer_pilotage(True)
    return {"service": "lmstudio", "desired": desire, "success": ok,
            "detail": "modeles servis sur 1234" if ok
                      else f"port muet apres start : {trace[-200:]}"}


def _jouer(binaire: str | None, ordre: list[str], desire: str = "") -> str | None:
    """Joue un ordre `lms` par le premier canal disponible. Rend la trace, ou
    None si AUCUN canal n'a pu jouer — NON MESURE, pas « en panne ».

    Ordre des canaux, du plus direct au plus indirect :
      1. le binaire, s'il est visible depuis ce compte (jamais le cas en service) ;
      2. la tache planifiee, seul canal qui s'execute SOUS l'identite de l'owner ;
      3. le pont session interactive — reste en echec tant que l'ACL du profil
         ferme le binaire a LaForgeTrusted, mais sa trace nomme la cause.
    """
    if binaire:
        try:
            r = subprocess.run([binaire, *ordre], capture_output=True, text=True,
                               errors="replace", timeout=120)
            return f"rc={r.returncode} {(r.stdout or '') + (r.stderr or '')}"
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}"
    par_tache = _lms_tache(desire)
    if par_tache is not None:
        return par_tache
    pont = _lms_owner(ordre)
    if pont is None:
        return None
    return (f"[pont user={pont.get('user') or '?'} rc={pont.get('rc')}] "
            f"{pont.get('stdout') or ''}")


# ── POLITIQUE OWNER (2026-08-18) : « lance-le quand c'est utile, coupe-le des
# que plus necessaire ». LM Studio n'est donc PAS un service a maintenir up : sa
# presence est un COUT (5,7 Go quand des modeles sont residents) et sa valeur ne
# dure que le temps d'un appel. Deux gestes symetriques en decoulent :
#   * reveil A LA DEMANDE, par le runtime qui va s'en servir ;
#   * arret sur INACTIVITE, par l'homeostat.
# Les deux ont besoin d'un seul fait partage : la date du dernier usage reel.
_USAGE = ROOT / "sandbox" / "lmstudio_usage.json"
_INACTIVITE_S = float(os.environ.get("LAFORGE_LMSTUDIO_INACTIVITE_S", "900"))


def marquer_usage(service: str = "lmstudio") -> None:
    """Date un usage REEL (une completion servie), jamais une simple sonde.
    Marquer sur une sonde rendrait le serveur eternellement « utile » : les
    sondes de sante tournent en boucle et l'arret n'arriverait jamais.
    """
    try:
        try:
            hist = json.loads(_USAGE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - premier usage
            hist = {}
        hist[service] = time.time()
        _USAGE.parent.mkdir(parents=True, exist_ok=True)
        _USAGE.write_text(json.dumps(hist), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        # Muet serait pire qu'inutile : sans date, l'arret sur inactivite
        # couperait un serveur en pleine utilisation.
        print(f"[usage] date NON ECRITE ({type(e).__name__}) | consequence: "
              f"l'arret sur inactivite ne peut pas savoir si {service} sert",
              flush=True)


def marquer_pilotage(actif: bool, service: str = "lmstudio") -> None:
    """Note que c'est NOKIDO qui a allume (ou eteint) ce serveur.

    Sans ce fait, l'arret sur inactivite couperait aussi le serveur que l'owner
    a lance lui-meme pour s'en servir : une vieille date d'usage suffirait a le
    declarer inutile. On ne retire pas un outil des mains de son proprietaire.
    """
    try:
        try:
            hist = json.loads(_USAGE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - premier passage
            hist = {}
        hist[f"{service}_pilote"] = bool(actif)
        if actif:
            # Un demarrage compte comme un usage : sans quoi un serveur allume
            # puis pas encore sollicite serait coupe au tick suivant.
            hist[service] = time.time()
        _USAGE.parent.mkdir(parents=True, exist_ok=True)
        _USAGE.write_text(json.dumps(hist), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[usage] pilotage NON NOTE ({type(e).__name__}) | consequence: "
              f"l'arret sur inactivite s'abstiendra par prudence", flush=True)


def est_pilote(service: str = "lmstudio") -> bool:
    """Nokido a-t-il allume ce serveur ? False = ne pas y toucher."""
    try:
        return bool(json.loads(_USAGE.read_text(encoding="utf-8"))
                    .get(f"{service}_pilote"))
    except Exception:  # noqa: BLE001 - pas de fait => on s'abstient
        return False


def inactif_depuis(service: str = "lmstudio") -> float | None:
    """Secondes depuis le dernier usage, ou None si AUCUN usage n'est date.

    None n'est pas « inactif depuis toujours » : c'est « je ne sais pas ». Un
    serveur demarre a la main par l'owner n'a pas de date d'usage, et le couper
    au motif de ce silence serait lui retirer son outil sous les doigts.
    """
    try:
        hist = json.loads(_USAGE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - jamais utilise
        return None
    dernier = float(hist.get(service) or 0.0)
    return (time.time() - dernier) if dernier else None


def _ram_libre_go() -> float:
    """RAM disponible en Go, 0.0 si illisible — on ne devine pas un chiffre."""
    try:
        import psutil

        return float(psutil.virtual_memory().available) / (1024 ** 3)
    except Exception:  # noqa: BLE001 - psutil absent : le delta sera nul
        return 0.0


def _port_ouvert(port: int = 1234, timeout: float = 3.0) -> bool:
    """Quelqu'un ECOUTE-t-il ? Question posee a la pile TCP, qui repond meme
    quand l'application est trop occupee pour le faire."""
    import socket

    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        s.close()


def _sonde_lmstudio(timeout: float = 4.0) -> bool:
    """Le serveur est-il LA ? (pas « repond-il vite ».)

    Trois faits, un seul verdict :
      * HTTP repond -> vivant ;
      * 401/403 -> vivant aussi (une auth qui refuse n'est pas un port muet) ;
      * HTTP MUET mais port TCP ouvert -> vivant et OCCUPE.

    ⚠️ MESURE 2026-08-18 : pendant le chargement d'un modele, LM Studio cesse de
    repondre a son API — machine a 99,4 % de RAM, `/api/v0/models` en timeout,
    et le port TCP pourtant OUVERT. Avec une sonde purement HTTP, `stopped`
    a repondu « deja arrete : RIEN a liberer » alors que le serveur tenait la
    memoire. Une regulation qui croit avoir libere ce qu'elle n'a pas libere est
    pire qu'une regulation absente : elle autorise la suite.
    """
    import urllib.error
    import urllib.request

    entetes = {"User-Agent": "nokido-ensure"}
    jeton = _lms_jeton()
    if jeton:
        entetes["Authorization"] = f"Bearer {jeton}"
    try:
        with urllib.request.urlopen(
                urllib.request.Request("http://127.0.0.1:1234/v1/models", headers=entetes),
                timeout=timeout) as r:
            return bool((json.loads(r.read()) or {}).get("data"))
    except urllib.error.HTTPError as he:
        return he.code < 500
    except Exception:  # noqa: BLE001 - muet : le TCP tranche entre absent et occupe
        return _port_ouvert()


def _declare_au_superviseur(name: str) -> bool:
    """Ce nom figure-t-il dans la SSoT du superviseur ?

    On lit le FICHIER, pas l'API : la declaration existe meme quand le
    superviseur est injoignable, et c'est justement dans ces moments qu'on a
    besoin de savoir si un service est cense exister.
    """
    toml = ROOT / "proxy_deno" / "core" / "services.toml"
    try:
        txt = toml.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    import re as _re

    return bool(_re.search(r'^\s*name\s*=\s*"%s"\s*$' % _re.escape(name), txt, _re.M))


def _installe(name: str):
    """Le service existe-t-il pour le gestionnaire ? None si on ne peut pas savoir.

    On ne rend jamais False par defaut : ne pas pouvoir interroger `sc` n'est pas
    une preuve d'absence, et transformer une incertitude en verdict est
    exactement le travers qu'on corrige ici.
    """
    try:
        r = subprocess.run(["sc.exe", "query", name], capture_output=True,
                           text=True, errors="replace", timeout=15)
    except Exception:  # noqa: BLE001 - sc absent (hors Windows), droits, timeout
        return None
    if r.returncode == 0:
        return True
    sortie = (r.stdout or "") + (r.stderr or "")
    # 1060 = ERROR_SERVICE_DOES_NOT_EXIST. Tout autre code (5 = acces refuse)
    # signifie « je n'ai pas pu regarder », pas « il n'existe pas ».
    if "1060" not in sortie:
        return None
    # ⚠️ Nokido a DEUX registres de services, et le SCM n'est que le premier.
    # Le second est le superviseur Deno (`proxy_deno/core/services.toml`, 85
    # services). Un service peut parfaitement vivre dans le second sans exister
    # dans le premier : c'est le cas de TOUT le pool Llama et des piliers RAG.
    # MESURE 2026-08-19 : `ensure(embed, running)` refusait de demarrer
    # `NokidoLlamaEmbed` avec « NON INSTALLE (sc query -> 1060) », alors que le
    # keeper le reclamait legitimement (intention embed.wanted, RAM 59 %). Les
    # 172 607 chunks sans vecteur attendaient derriere ce refus.
    # Conclure « inexistant » sur la lecture d'UN SEUL registre revient a
    # declarer indemarrable la moitie de sa propre surface.
    return True if _declare_au_superviseur(name) else False


def _serving(svc: str):
    """True/False si sonde connue (HTTP<500 [+ cle JSON non vide]) ; None si aucune sonde."""
    spec = _HEALTH.get(svc)
    if not spec:
        return None
    import urllib.error as _ue
    import urllib.request as _ur
    url, key = spec
    try:
        with _ur.urlopen(_ur.Request(url, method="GET"), timeout=3) as r:
            if getattr(r, "status", 200) >= 500:
                return False
            if key:
                return bool((json.loads(r.read()) or {}).get(key))
            return True
    except _ue.HTTPError as he:
        return he.code < 500  # 401/403/404 = serveur up (auth/route), pas down
    except Exception:  # noqa: BLE001  (refus/timeout/503 = pas pret)
        return False


def _wait_serving(svc: str, secs: int = 40):
    """Poll jusqu'a ce que le service serve (retour rapide des qu'il sert). None si pas de sonde."""
    if _serving(svc) is None:
        return None
    end = time.time() + secs
    while time.time() < end:
        if _serving(svc):
            return True
        time.sleep(3)
    return _serving(svc) is True


def _ensure_docker(timeout_s: int = 140) -> bool:
    """Poste docker.wanted via forge_docker_agent (le keeper lance Docker Desktop
    en session user), puis attend le daemon. Réutilise forge_searxng_keeper._docker_daemon_up."""
    # GARDE ANTI-SAWTOOTH (2026-07-25) — CORRIGEE le 2026-08-14 : sa condition
    # etait AUTO-REALISATRICE et fermait la seule porte d'entree de Docker.
    #
    # Le keeper est `monitor_only` PARCE QUE `docker.wanted` est absent (c'est son
    # etat NOMINAL au repos, cf. doctrine « Docker est dynamique »). L'ancienne
    # garde refusait donc de poser le flag *parce que* le keeper etait
    # monitor_only, et SUPPRIMAIT en plus toute demande pendante : deux appels
    # successifs s'annulaient l'un l'autre et Docker ne pouvait plus JAMAIS
    # demarrer par ce chemin (mesure 2026-08-14 : flag absent, keeper vivant
    # iter 179, tool repondant « daemon still down » sans rien poser).
    #
    # Le sawtooth que la garde visait est REEL, mais il ne se caracterise pas
    # ainsi : c'est un keeper qui reste monitor_only ALORS QUE la demande est
    # FRAICHE — la, il ignore vraiment le flag (AUTOLAUNCH=0 + refus WTS) et le
    # refus fail-loud est justifie. Le flag absent ou perime est au contraire le
    # cas nominal ou l'on DOIT poser la demande.
    try:
        import json as _json

        _flag = ROOT / "sandbox" / "docker.wanted"
        _frais = False
        try:
            _frais = _flag.exists() and (time.time() - _flag.stat().st_mtime) < 900
        except OSError:
            _frais = False
        _hb = _json.loads((ROOT / "sandbox" / "docker_keeper.heartbeat")
                          .read_text(encoding="utf-8", errors="replace"))
        _stats = _hb.get("stats") or {}
        if _stats.get("monitor_only") and not _stats.get("daemon_up") and _frais:
            try:
                _flag.unlink(missing_ok=True)
            except OSError:
                pass
            print("[ensure_docker] REFUS: demande FRAICHE deja posee et keeper "
                  "toujours monitor_only -> il ignore le flag (AUTOLAUNCH=0 ou "
                  "refus de lancement en session owner). Lancer Docker Desktop "
                  "cote owner avant de redemander.", flush=True)
            return False
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger("forge.ensure").warning(
            "[ensure_docker] heartbeat du keeper ILLISIBLE (%s: %s) | consequence: "
            "on ne sait pas s'il peut agir, on POSE la demande quand meme (fail-open "
            "assume : ne jamais fermer la seule porte d'entree de Docker)",
            type(e).__name__, str(e)[:90])
    subprocess.run(
        [LAFORGE_PYTHON, str(ROOT / "app" / "forge_docker_agent.py"), "--ensure-daemon", "--timeout", "120"],
        capture_output=True, text=True, errors="replace", timeout=40,
    )
    from nokido_agent.tools import forge_searxng_keeper as k
    if k._docker_daemon_up():
        return True
    for _ in range(int(timeout_s / 8)):
        time.sleep(8)
        if k._docker_daemon_up():
            return True
    return k._docker_daemon_up()


# ── GARDE D'ADMISSION DES REVEILS COUTEUX (2026-08-14) ──────────────────────
# Un reveil de backend LLM ou de Docker charge la RAM pour des dizaines de
# secondes. MESURE du jour : trois reveils enchaines (llamacpp, lmstudio,
# router_local) sans attendre le premier, PENDANT un job actif, sur une machine
# a ~80 % -> le HUB EST TOMBE (`Services CRITIQUES DOWN: ['hub_mcp']`), et sept
# boots Docker se sont ajoutes a la charge en quinze minutes.
#
# La regle manquante etait pourtant deja ECRITE (23/07, apres le doom-loop du
# keeper) : « NE PAS armer le keeper quand la RAM est > 85 % — c'est le boot lent
# qui fait le faux KO ». Elle n'avait jamais ete cablee : elle reposait sur la
# discipline du client. Un client discipline n'est pas une garantie, un garde
# en est une — meme raisonnement que la periode refractaire du force-recycle,
# ou que la `lane` de run_job (un job lourd a la fois).
#
# `stopped` n'est JAMAIS refuse : on doit toujours pouvoir liberer des ressources.
_COUTEUX = {"llamacpp", "lmstudio", "embed", "graph", "ollama", "router_local", "docker"}
_REVEIL_REFRACTAIRE_S = 180.0
_RAM_PLAFOND_PCT = 85.0
_REVEILS = ROOT / "sandbox" / "ensure_reveils.json"


def _ram_pct() -> float:
    """% de RAM utilisee ; 0.0 si illisible (on n'invente pas un chiffre)."""
    try:
        import psutil

        return float(psutil.virtual_memory().percent)
    except Exception as e:  # noqa: BLE001
        print(f"[admission] RAM ILLISIBLE ({type(e).__name__}: {str(e)[:60]}) | "
              f"consequence: le plafond RAM ne peut pas s'appliquer, seule la "
              f"refractaire protege", flush=True)
        return 0.0


# Place LIBRE exigee avant de reveiller, en Go. Un plafond en POURCENTAGE juge
# l'etat AVANT le geste ; il ne dit rien de ce que le geste va couter. MESURE
# 2026-08-18 : LM Studio demarre a 53 % de RAM, puis le chargement d'un 7B a
# porte la machine a 99,4 % — l'API du serveur a cesse de repondre et le hub
# etait a un cheveu de la RCA connue. 85 % « autorisait » ce reveil.
_MIN_LIBRE_GO = {"lmstudio": 7.0}


def _admission(s: str, st: str) -> dict | None:
    """Refus motive d'un reveil trop rapproche ou sous RAM saturee, sinon None."""
    if s not in _COUTEUX or st == "stopped":
        return None
    besoin = _MIN_LIBRE_GO.get(s)
    if besoin:
        libre = _ram_libre_go()
        # 0.0 = RAM illisible : on n'invente pas un chiffre, et on ne refuse pas
        # sur une mesure absente — la refractaire et le plafond protegent encore.
        if 0.0 < libre < besoin:
            return {"service": s, "desired": st, "success": False,
                    "refus": "place_insuffisante",
                    "detail": f"{libre:.1f} Go libres, il en faut {besoin:.0f} : "
                              f"le modele charge apres le reveil coute ~6 Go, et "
                              f"un pourcentage ne mesure que l'etat AVANT le geste."}
    ram = _ram_pct()
    if ram >= _RAM_PLAFOND_PCT:
        return {"service": s, "desired": st, "success": False,
                "refus": "ram_saturee",
                "detail": f"RAM a {ram:.1f} % (plafond {_RAM_PLAFOND_PCT:.0f} %) : "
                          f"un reveil ici produit un boot lent juge KO, donc une "
                          f"boucle de relance. Liberer d'abord (stopped) ou attendre."}
    try:
        hist = json.loads(_REVEILS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        hist = {}
    dernier = float(hist.get(s) or 0.0)
    depuis = time.time() - dernier
    if dernier and depuis < _REVEIL_REFRACTAIRE_S:
        return {"service": s, "desired": st, "success": False,
                "refus": "refractaire",
                "detail": f"reveil de '{s}' demande il y a {depuis:.0f} s "
                          f"(refractaire {_REVEIL_REFRACTAIRE_S:.0f} s). Le "
                          f"precedent n'a pas fini de produire son effet : "
                          f"attendre plutot que d'empiler."}
    hist[s] = time.time()
    try:
        _REVEILS.parent.mkdir(parents=True, exist_ok=True)
        _REVEILS.write_text(json.dumps(hist), encoding="utf-8")
    except OSError as e:
        print(f"[admission] historique NON persiste ({e}) | consequence: la "
              f"refractaire ne tiendra pas au prochain appel", flush=True)
    return None


def _stop_docker_gouverne() -> dict:
    """Retire l'intention `docker.wanted` puis demande au keeper de relacher.

    Trois refus possibles, chacun DIT : une chaine de travail active (le keeper
    interdit la coupe), un conteneur tiers present (le moteur reste allume, les
    conteneurs Nokido sont quand meme arretes), ou un keeper illisible.
    """
    import importlib

    detail: dict = {}
    flag = ROOT / "sandbox" / "docker.wanted"
    try:
        if flag.exists():
            flag.unlink()
            detail["intention"] = "docker.wanted retiree"
        else:
            detail["intention"] = "aucune intention posee"
    except Exception as e:  # noqa: BLE001
        return {"service": "docker", "desired": "stopped", "success": False,
                "detail": f"intention non retiree ({type(e).__name__}) -- on ne coupe pas "
                          f"sans avoir d'abord retire la demande"}

    # Intention AVANT capacite : une veille en cours interdit la relache (meme regle
    # que `_maybe_release` du keeper -- on ne duplique pas le critere, on le rejoue).
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_resource_manager import get_active_intents

        if (get_active_intents() or {}).get("chains_active"):
            return {"service": "docker", "desired": "stopped", "success": False,
                    "detail": "chaine de travail active -- relache refusee", **detail}
    except Exception as e:  # noqa: BLE001
        return {"service": "docker", "desired": "stopped", "success": False,
                "detail": f"intentions illisibles ({type(e).__name__}) -- fail-closed, "
                          f"on ne coupe pas sur une non-mesure", **detail}

    try:
        sys.path.insert(0, str(ROOT))
        keeper = importlib.import_module("forge_docker_keeper")
        detail.update(keeper._release_docker() or {})
    except Exception as e:  # noqa: BLE001
        return {"service": "docker", "desired": "stopped", "success": False,
                "detail": f"keeper indisponible ({type(e).__name__}: {e})", **detail}

    # EFFET, pas accuse de reception : le daemon repond-il encore ? La sonde est
    # IMPORTEE explicitement (regle d'or `laforge-appel-nom-non-lie` : un appel resolu
    # par `globals()` n'est pas verifiable statiquement -- et un nom absent rendrait
    # `None`, c'est-a-dire un INCONNU deguise en mesure).
    encore = None
    try:
        from nokido_agent.tools import forge_searxng_keeper as _k

        encore = _k._docker_daemon_up()
    except Exception as e:  # noqa: BLE001
        detail["sonde_daemon"] = f"illisible ({type(e).__name__}) -- effet NON verifie"
    detail["daemon_encore_up"] = encore
    ok = (encore is False) or bool(detail.get("stopped"))
    return {"service": "docker", "desired": "stopped", "success": ok, "detail": detail}


def ensure(service: str, state: str) -> dict:
    s = service.lower().strip()
    st = state.lower().strip()
    _refus = _admission(s, st)
    if _refus is not None:
        return _refus

    if s == "docker":
        if st in ("running", "restarted"):
            up = _ensure_docker()
            return {"service": "docker", "desired": st, "success": up,
                    "detail": "daemon up" if up else "daemon still down (keeper/owner)"}
        # ARRET GOUVERNE (2026-09-06, demande owner : « lancer/couper en regulant »).
        # Auparavant : refus sec. Le keeper SAIT pourtant relacher (`_release_docker` :
        # arret de NOS conteneurs puis `docker desktop stop`, jamais de taskkill, et
        # refus d'eteindre le moteur si un conteneur TIERS tourne) -- mais seulement
        # apres TTL 900 s + grace 900 s, soit une demi-heure. Or Docker coute 3,99 Go
        # de RAM (mesure du jour) et la place manquait a l'instant meme pour LM Studio.
        # On ne tue pas : on RETIRE l'intention puis on demande la relache, avec les
        # memes gardes que le keeper. Le verdict porte sur l'EFFET (conteneurs arretes,
        # moteur eteint), jamais sur l'accuse de reception.
        return _stop_docker_gouverne()

    if s == "lmstudio" and st == "stopped":
        pass  # traite plus bas par la voie generique des services

    if s == "searxng":
        if st in ("running", "restarted"):
            if not _ensure_docker():
                return {"service": "searxng", "desired": st, "success": False, "detail": "docker daemon down"}
            from nokido_agent.tools import forge_searxng_keeper as k
            try:
                k._ensure_running()
            except Exception as e:  # noqa: BLE001
                return {"service": "searxng", "desired": st, "success": False, "detail": f"ensure err: {e}"}
            ok, info = k._probe_http()
            return {"service": "searxng", "desired": st, "success": bool(ok), "detail": str(info)[:140]}
        if st == "stopped":
            r = _supervisor("stop", "NokidoSearxng")
            return {"service": "searxng", "desired": st, "success": r["rc"] == 0, "detail": r}

    # LM Studio n'a pas de service Windows : il se pilote par son CLI. Le faire
    # AVANT le chemin generique, sinon on retombe sur `NokidoLMStudio` absent.
    if s == "lmstudio":
        return _lmstudio(st)

    # service supervisé générique
    name = SVC_MAP.get(s) or (service if service.startswith("Nokido") else None)
    if not name:
        return {"service": service, "success": False, "detail": f"service inconnu (connus: {sorted(SVC_MAP)})"}
    act = {"running": "ensure", "restarted": "restart", "stopped": "stop"}.get(st)
    if not act:
        return {"service": service, "success": False, "detail": f"desired_state invalide: {st}"}
    # GATE world-model (owner 2026-07-23) : refuser un STOP qui cascade sur un organe
    # ESSENTIEL (verdict dangerous) sauf LAFORGE_LIFECYCLE_FORCE. Le corps anticipe.
    #
    # Un RESTART CONTIENT un arret : le laisser hors du gate laissait passer
    # exactement ce que le gate refuse en `stop`. Le trou n'etait pas visible en
    # lecture -- `act == "stop"` se lit comme correct tant qu'on ne se demande pas
    # ce que vaut `restart`. Mesure 2026-09-01 : un appel sur un service SECONDAIRE
    # a fait redemarrer le control-plane, SANDBOX_EXEC est reparti vide, toute
    # execution suivante est passee en compte owner -- et le service demande n'a
    # jamais demarre. Le gate n'a pas cede : il n'etait pas sur le chemin.
    if act in ("stop", "restart"):
        # L'echappatoire etait ANNONCEE dans deux messages de refus et lue NULLE
        # PART : un agent qui suivait le conseil se cassait le nez. Elle existe
        # maintenant, sinon le refus est un mur sans porte.
        _force = (os.environ.get("LAFORGE_LIFECYCLE_FORCE", "") or "").strip().lower() in (
            "1", "true", "on", "yes")
        try:
            import sys as _s
            _app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
            if _app not in _s.path:
                _s.path.insert(0, _app)
            from nokido_agent.app.forge_body_world_model import guard as _guard
            # On interroge l'impact d'un ARRET meme pour un restart : c'est la
            # phase destructrice du geste, et c'est elle qui cascade.
            _g = _guard(name, "stop")
        except Exception as e:  # noqa: BLE001
            # TROISIEME ETAT : le world-model est ILLISIBLE, ni autorise ni refuse.
            # Le `pass` d'origine desarmait ce gate EN SILENCE -- un garde qu'une
            # erreur d'import neutralise sans trace ne garde rien, et c'est le
            # defaut meme que ce gate est cense empecher ailleurs.
            # Le cout des deux erreurs n'est pas symetrique : refuser a tort coute
            # une relance avec LAFORGE_LIFECYCLE_FORCE=1 ; laisser passer a tort a
            # coute le control-plane le 2026-09-01.
            print(f"[lifecycle] world-model ILLISIBLE ({type(e).__name__}: {str(e)[:90]}) "
                  f"| acte={act} service={name} | consequence: impact non evaluable",
                  flush=True)
            if not _force:
                return {"service": service, "mapped": name, "desired": st, "success": False,
                        "refus": "world_model_illisible", "acte": act,
                        "detail": f"impact NON EVALUABLE ({type(e).__name__}) : un acte "
                                  "destructeur ne passe pas sur un verdict absent. "
                                  "LAFORGE_LIFECYCLE_FORCE=1 pour outrepasser."}
            _g = {"allowed": True, "impact": {"reason": "world-model illisible, FORCE"}}
        if not _g.get("allowed", True) and not _force:
            return {"service": service, "mapped": name, "desired": st, "success": False,
                    "impact": _g["impact"], "refus": "world_model_dangerous", "acte": act,
                    "detail": f"REFUSE par world-model (dangerous, acte={act}): "
                              f"{_g['impact'].get('reason')} -- un restart contient un "
                              "arret, il tombe sous le meme impact. "
                              "LAFORGE_LIFECYCLE_FORCE=1 pour outrepasser"}
    # Un service ABSENT du gestionnaire ne peut pas etre demarre : le dire ici,
    # sinon le rc=0 du supervisor se traduit en `success: true` sur du vide.
    # Mesure du 2026-08-15 : ensure_service(graph) rendait
    # `success: true, starting: NokidoGraphExplorer` alors que `sc query` rend
    # 1060 (service inexistant) -- le composant tournait par un autre chemin,
    # et l'appel n'y etait pour rien.
    if _installe(name) is False:
        return {"service": service, "mapped": name, "desired": st, "success": False,
                "detail": f"service '{name}' NON INSTALLE (sc query -> 1060) : "
                          "rien a demarrer, verifier SVC_MAP ou installer le service"}

    # Un RESTART qui part trop tot laisse le service ARRETE. Mesure 2026-08-26 sur
    # NokidoWebHub : le stop rend `held_process: true` (le process tient encore le
    # port), le start qui suit annonce `starting`, entre en collision, et le
    # superviseur laisse `stopped` — l'appelant lit un `success: False` sans savoir
    # que le service est desormais MOINS vivant qu'avant son geste. Un arret se
    # prouve par le port QUI SE TAIT, jamais par le rc de l'ordre : le motif etait
    # deja applique a LM Studio et manquait au chemin generique.
    if act == "restart":
        _supervisor("stop", name)
        _fin = time.time() + 25
        while time.time() < _fin:
            if _serving(s) is not True:   # None (pas de sonde) ou False -> on peut y aller
                break
            time.sleep(2)
        else:
            print(f"[ensure] {name}: port toujours servi apres 25 s — start quand meme")
        r = _supervisor("start", name)
    else:
        r = _supervisor(act, name)
    ok = r["rc"] == 0
    # Verifie l'ISSUE REELLE : sonde jusqu'a ce que le service SERVE. Si un restart a
    # laisse le service DOWN (vu cette session sur embed), escalade UN start on-demand
    # (jamais de kill = ca reste le job du supervisor).
    if act in ("ensure", "restart"):
        served = _wait_serving(s)
        if served is False and act == "restart":
            _supervisor("start", name)
            served = _wait_serving(s)
        if served is not None:
            ok = bool(served)
    return {"service": service, "mapped": name, "desired": st, "success": ok, "detail": r}


def main() -> int:
    ap = argparse.ArgumentParser(description="Bouton rouge déclaratif: assure l'état d'un service Nokido")
    ap.add_argument("--service", required=True)
    ap.add_argument("--state", default="running")
    a = ap.parse_args()
    try:
        res = ensure(a.service, a.state)
    except Exception as e:  # noqa: BLE001
        import traceback
        res = {"success": False, "detail": f"{type(e).__name__}: {e}", "tb": traceback.format_exc()[-300:]}
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
