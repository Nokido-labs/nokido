#!/usr/bin/env python
"""forge_process_inventory.py — QUI TOURNE, ET QUI FAIT QUOI. Lecture seule.

POURQUOI (mesure 2026-07-29)
    Sur 339 process vivants, **331 lignes de commande sont illisibles** depuis un
    compte client : Windows refuse la cmdline des process d'un autre compte. Tout
    agent qui sonde `psutil`/`Get-CimInstance` lit donc un trou noir et conclut
    « ce service ne tourne pas » alors qu'il tourne. Ce faux negatif a ete paye
    plusieurs fois dans la meme journee.

    Deuxieme source de confusion, mesuree le meme jour : le superviseur note le
    pid du LANCEUR, et c'est son ENFANT qui tient le port.
        NokidoQdrantServer -> pid 20184 (python) ; qdrant.exe 18072 ecoute 6333
        NokidoOllama       -> pid 7132  (ollama) ; llama-server 10872 ecoute 61781
    Un llama-server « non declare » n'est donc PAS forcement un orphelin : il faut
    REMONTER l'arbre avant d'accuser (cf. RULES_SHARED, gotcha launcher).

CE QU'IL FAIT
    Croise les trois seules sources qui font autorite, sans rien tuer :
      1. DECLARE  : /supervisor/status (service -> pid, uptime, restarts)
      2. PREVU    : proxy_deno/core/services.toml (script, heartbeat, disabled)
      3. REEL     : psutil (pid, ppid, RSS, age) + arbre parent/enfant

    Et signale ce qui ne se recoupe pas :
      - FANTOME   : declare `running`, pid inexistant (uptime_s grimpe quand meme)
      - FIGE      : pid vivant mais heartbeat perime -> boucle morte
      - INCONNU   : process qui ecoute alors qu'aucun service ne le revendique
      - DOUBLON   : meme script porte par plusieurs pid

    N'ARRETE RIEN, NE REDEMARRE RIEN : un constat n'est pas une action. La
    reconciliation reste un geste explicite (forge_supervisor_ctl stop/start).

USAGE
    LAFORGE_PYTHON tools/forge_process_inventory.py            # tableau lisible
    LAFORGE_PYTHON tools/forge_process_inventory.py --json     # brut
"""

from __future__ import annotations

__FORGE_COLOR__ = "proprioception/identite-process"

import argparse
import getpass
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES_TOML = ROOT / "proxy_deno" / "core" / "services.toml"


def _donnees() -> Path:
    """Racine des DONNEES (forge_db_path), jamais derivee de __file__ (cliquet racine_donnees, 20/10)."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        try:
            from forge_db_path import racine_donnees
        except ImportError:  # app/ hors sys.path : checkout, donnees = depot
            return ROOT
    return Path(racine_donnees())
SUPERVISOR = "http://127.0.0.1:8765/supervisor/status"
_REGISTRE_SUPERVISEUR_DEFAUT = _donnees() / "sandbox" / "health.json"
REGISTRE_SUPERVISEUR = _REGISTRE_SUPERVISEUR_DEFAUT
_PUBLIES_COURANTS: dict[int, dict] | None = None
# Un heartbeat n'est PERIME que relativement au rythme ATTENDU du daemon. Ne PAS
# inventer un seuil ici : services.toml declare deja `heartbeat_tier` et
# supervisor.ts fixe la convention (HEARTBEAT_TIERS). On reprend SES chiffres,
# sinon le capteur juge le corps selon une regle que le corps ne connait pas.
#   fast   poll 5s  | degraded 30s   | restart 90s
#   normal poll 30s | degraded 300s  | restart 600s
#   slow   poll 60s | degraded 1800s | restart 3600s
TIER_RESTART_S = {"fast": 90, "normal": 600, "slow": 3600}
TIER_DEFAUT = "normal"
HEARTBEAT_CYCLES_TOLERES = 3
NOKIDO_RE = re.compile(r"forge_|Nokido|LaForge|proxy_deno|laforge", re.I)
# Un port tenu par Windows n'est pas une anomalie Nokido : sans ce filtre, 20 lignes
# de bruit (svchost/lsass/System) noient les 2 vrais ecoutants non revendiques.
SYSTEM_NOMS = frozenset(
    {
        "system",
        "svchost.exe",
        "lsass.exe",
        "wininit.exe",
        "services.exe",
        "spoolsv.exe",
        "vmms.exe",
        "ss_conn_service.exe",
        "ss_conn_service2.exe",
        "asusupdatecheck.exe",
        "ditto.exe",
    }
)


# ── Contexte d'execution : SOUS QUEL COMPTE une mesure a ete prise ────────────────────────────────────────────────
# Constat 24/10 : une meme sonde rend des resultats differents selon le compte qui l'execute (LaForgeSbxOffline n'a
# pas de reseau, LaForgeSbxOnline ne lit ni les FORGE_TOKEN_* ni les sessions OAuth du profil owner, sous SYSTEM
# Path.home() vaut systemprofile). Deux mesures incomparables ne doivent plus etre melangees sans le dire.
HOTE_TEMOIN_RESEAU = ("api.groq.com", 443)
SECRET_TEMOIN_COFFRE = "FORGE_MCP_TOKEN"
DRAPEAUX_RESEAU = ("LAFORGE_JOB_ONLINE", "LAFORGE_SANDBOX_ONLINE", "LAFORGE_ONLINE")
_VRAIS = frozenset({"1", "true", "oui", "yes", "on", "online"})
_FAUX = frozenset({"0", "false", "non", "no", "off", "offline"})


def _drapeau_reseau() -> bool | None:
    """Drapeau du job s'il est pose, sinon None (on sonde). Un drapeau illisible est ignore, jamais devine."""
    for nom in DRAPEAUX_RESEAU:
        valeur = os.environ.get(nom)
        if valeur is None or not valeur.strip():
            continue
        v = valeur.strip().lower()
        if v in _VRAIS:
            return True
        if v in _FAUX:
            return False
    return None


def _sonde_reseau(hote=HOTE_TEMOIN_RESEAU, timeout: float = 0.4) -> bool | str:
    """Connexion TCP courte vers un hote connu. True joignable, False refuse/timeout, INCONNU si la sonde elle-meme
    echoue pour une raison qui ne dit rien du reseau (import casse, erreur inattendue)."""
    import socket

    try:
        with socket.create_connection(hote, timeout=timeout):
            return True
    except OSError:
        return False
    except Exception:  # noqa: BLE001 - la sonde ne peut pas conclure : UNKNOWN, jamais un faux False
        return "INCONNU"


def _coffre_lisible() -> bool | str:
    """Le coffre rend-il un nom temoin non vide ? On ne lit JAMAIS la valeur : True/False, ou INCONNU si la lecture
    leve. Une exception n'est pas « coffre vide » (UNKNOWN != NO)."""
    try:
        try:
            from nokido_agent.app.forge_secrets import get_secret
        except ImportError:  # repli checkout
            from forge_secrets import get_secret
    except Exception:  # noqa: BLE001 - coffre non importable : on ne peut pas conclure
        return "INCONNU"
    try:
        return bool(get_secret(SECRET_TEMOIN_COFFRE))
    except Exception:  # noqa: BLE001 - coffre muet/refuse : INCONNU, surtout pas False
        return "INCONNU"


def _est_service(compte: str) -> bool:
    """SYSTEM ou un compte de service LaForge* (le domaine eventuel est retire)."""
    nom = str(compte or "").split("\\")[-1].strip().upper()
    return nom == "SYSTEM" or nom.startswith("LAFORGE")


def _profil_reel() -> str:
    """Profil PROPRIETAIRE, pas le home du compte courant (sous SYSTEM : config\\systemprofile)."""
    return os.environ.get("LAFORGE_OWNER_HOME") or str(Path.home())


def contexte_execution() -> dict:
    """Sous quel contexte cette mesure tourne : compte, profil reel, reseau, coffre, service.

    `reseau` vaut True/False/INCONNU ; `coffre_lisible` vaut True/False/INCONNU et ne transporte jamais la valeur.
    """
    compte = getpass.getuser()
    drapeau = _drapeau_reseau()
    return {
        "compte": compte,
        "profil_reel": _profil_reel(),
        "reseau": _sonde_reseau() if drapeau is None else drapeau,
        "coffre_lisible": _coffre_lisible(),
        "est_service": _est_service(compte),
    }


def _normaliser_entree_service(nom: str, svc: dict) -> dict:
    """Normalise une entree de service publiee par le superviseur (HTTP /supervisor/status ou sandbox/health.json)."""
    return {
        "status": svc.get("status") or "running",
        "pid": svc.get("pid"),
        "ppid": svc.get("ppid"),
        "cmdline": svc.get("cmdline") or svc.get("cmd"),
        "service": str(svc.get("service") or nom),
        "intention": svc.get("intention"),
        "objectif": svc.get("objectif"),
        "compte": svc.get("compte"),
        "heure": svc.get("heure"),
        "uptime_s": svc.get("uptime_s"),
        "restarts": svc.get("restarts"),
        "port": svc.get("port"),
    }


def _decoder_registre_payload(payload: object) -> dict:
    """Decode le contenu JSON du registre superviseur ; rend __erreur__ ILLISIBLE si le format est invalide."""
    if not isinstance(payload, dict) or not payload:
        return {"__erreur__": {"status": "ILLISIBLE", "motif": "registre vide ou non-dict"}}
    if "__erreur__" in payload:
        return payload
    has_services_key = "services" in payload
    raw = payload.get("services") if has_services_key else payload
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, list):
        items = [(s.get("service") or s.get("name"), s) for s in raw if isinstance(s, dict)]
    else:
        return {"__erreur__": {"status": "ILLISIBLE", "motif": "champ services invalide"}}
    out = {}
    for name, svc in items:
        if name and not str(name).startswith("__") and isinstance(svc, dict):
            if has_services_key or any(k in svc for k in ("pid", "status", "intention", "cmdline", "cmd", "service")):
                out[str(name)] = _normaliser_entree_service(str(name), svc)
    if not out and not has_services_key:
        return {"__erreur__": {"status": "ILLISIBLE", "motif": "aucune entree de service reconnue"}}
    return out


def _lire_registre_superviseur(chemin: Path | str | None = None) -> dict:
    """Lit le fichier de registre publie par le superviseur (sandbox/health.json).
    Un registre absent, tronque ou corrompu rend __erreur__=ILLISIBLE, jamais {} ni 0."""
    cible = Path(chemin) if chemin is not None else Path(REGISTRE_SUPERVISEUR)
    try:
        texte = cible.read_text(encoding="utf-8")
        payload = json.loads(texte)
    except Exception as exc:  # noqa: BLE001 - registre illisible != 0 service
        return {"__erreur__": {"status": "ILLISIBLE", "motif": f"registre illisible ({cible.name}): {exc}"[:120]}}
    return _decoder_registre_payload(payload)


def _pids_publies(declares: dict | None, prevus: dict | None = None) -> dict[int, dict]:
    """Table pid -> {service, intention, objectif, cmdline, ppid, compte, heure} extraite du registre publie."""
    if not isinstance(declares, dict) or "__erreur__" in declares:
        return {}
    prevus_map = prevus if isinstance(prevus, dict) else {}
    out: dict[int, dict] = {}
    for nom, decl in declares.items():
        if str(nom).startswith("__") or not isinstance(decl, dict):
            continue
        if decl.get("status") not in (None, "running", "starting", "degraded"):
            continue
        pid = decl.get("pid")
        if not pid:
            continue
        try:
            pid_int = int(pid)
        except (ValueError, TypeError):
            # 9/11 (visibilite des processus) : un service au pid illisible ne disparait plus en silence.
            print("[inventaire] pid illisible au registre pour %s : %r -- service non attribue" % (nom, pid),
                  file=sys.stderr)
            continue
        prevu = prevus_map.get(nom) or {}
        out[pid_int] = {
            "service": str(decl.get("service") or nom),
            "intention": decl.get("intention") or prevu.get("intention"),
            "objectif": decl.get("objectif") or prevu.get("objectif"),
            "cmdline": decl.get("cmdline") or decl.get("cmd"),
            "ppid": decl.get("ppid"),
            "compte": decl.get("compte"),
            "heure": decl.get("heure"),
        }
    return out


def _declares(timeout: float = 10.0, chemin_registre: Path | str | None = None) -> dict:
    """Ce que le superviseur PUBLIE (registre fichier sandbox/health.json et/ou HTTP /supervisor/status).
    Peut mentir sur un pid mort — d'ou le croisement."""
    if chemin_registre is not None or Path(REGISTRE_SUPERVISEUR) != _REGISTRE_SUPERVISEUR_DEFAUT:
        return _lire_registre_superviseur(chemin_registre or REGISTRE_SUPERVISEUR)
    depuis_fichier = _lire_registre_superviseur(REGISTRE_SUPERVISEUR)
    try:
        with urllib.request.urlopen(SUPERVISOR, timeout=timeout) as resp:
            payload = json.loads(resp.read())
        depuis_http = _decoder_registre_payload(payload)
    except Exception as exc:  # superviseur injoignable != aucun service
        depuis_http = {"__erreur__": {"status": f"superviseur injoignable: {exc}"[:120]}}
    if "__erreur__" not in depuis_http:
        if "__erreur__" not in depuis_fichier:
            for nom, info_f in depuis_fichier.items():
                if nom in depuis_http and isinstance(info_f, dict):
                    for cle in ("ppid", "cmdline", "service", "intention", "objectif", "compte", "heure"):
                        if not depuis_http[nom].get(cle) and info_f.get(cle):
                            depuis_http[nom][cle] = info_f[cle]
                elif nom not in depuis_http:
                    depuis_http[nom] = info_f
        return depuis_http
    if "__erreur__" not in depuis_fichier:
        return depuis_fichier
    return {"__erreur__": {"status": "ILLISIBLE", "motif": depuis_http["__erreur__"].get("status", "ILLISIBLE")}}


def _prevus() -> dict:
    """Ce que services.toml PREVOIT : script d'entree + fichier de heartbeat + intention/objectif."""
    out = {}
    try:
        text = SERVICES_TOML.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"__erreur__": {"script": f"services.toml illisible: {exc}"[:110]}}
    for bloc in re.split(r"\n\[\[", text):
        m_name = re.search(r'name\s*=\s*"([^"]+)"', bloc)
        if not m_name:
            continue
        script = ""
        m_args = re.search(r"args\s*=\s*\[([^\]]*)\]", bloc, re.S)
        if m_args:
            for tok in re.findall(r'"([^"]+)"', m_args.group(1)):
                if tok.endswith((".py", ".ts")):
                    script = tok.split("/")[-1]
                    break
        m_hb = re.search(r'heartbeat\s*=\s*"([^"]+)"', bloc)
        interval = None
        if m_args:
            toks = re.findall(r'"([^"]+)"', m_args.group(1))
            for i, tok in enumerate(toks[:-1]):
                if tok in ("--interval", "--sleep", "--period") and toks[i + 1].isdigit():
                    interval = int(toks[i + 1])
                    break
        # 19/10 : la cadence DECLAREE (cycle_s, heartbeat_max_s) prime sur la deduction par drapeaux -- sans elle,
        # DeportEmbed (--watch 3600) et le consolidateur (12 h) etaient « figes » a tort. Lignes de commentaire exclues.
        m_cycle = re.search(r"^\s*cycle_s\s*=\s*(\d+)", bloc, re.M)
        m_hbmax = re.search(r"^\s*heartbeat_max_s\s*=\s*(\d+)", bloc, re.M)
        if m_cycle:
            interval = int(m_cycle.group(1))
        m_tier = re.search(r'heartbeat_tier\s*=\s*"(fast|normal|slow)"', bloc)
        m_runas = re.search(r'runAs\s*=\s*"([^"]+)"', bloc)
        m_intention = re.search(r'^\s*intention\s*=\s*"([^"]+)"', bloc, re.M)
        m_objectif = re.search(r'^\s*objectif\s*=\s*"([^"]+)"', bloc, re.M)
        out[m_name.group(1)] = {
            "script": script,
            "heartbeat": m_hb.group(1) if m_hb else None,
            "interval_s": interval,
            "heartbeat_max_s": int(m_hbmax.group(1)) if m_hbmax else None,
            "tier": m_tier.group(1) if m_tier else TIER_DEFAUT,
            "disabled": "disabled = true" in bloc,
            "runAs": m_runas.group(1) if m_runas else None,
            "intention": m_intention.group(1) if m_intention else None,
            "objectif": m_objectif.group(1) if m_objectif else None,
        }
    return out


def _vivants(publies: dict[int, dict] | None = None) -> tuple[dict, int]:
    """Ce qui TOURNE. Lit le registre publie par le superviseur AVANT de tenter proc.cmdline() :
    un pid publie recoit directement sa cmdline, son service et son intention sans se heurter au refus OS inter-comptes.
    `illisibles` compte les cmdline refusees : ne jamais lire une cmdline vide comme une absence de process."""
    import psutil

    actifs = publies if publies is not None else (_PUBLIES_COURANTS or {})
    now = time.time()
    procs, illisibles = {}, 0
    for proc in psutil.process_iter(
        ["pid", "ppid", "name", "create_time", "memory_info", "username"]
    ):
        try:
            info = proc.info
            pid = info["pid"]
            pub = actifs.get(pid)
            if pub and pub.get("cmdline"):
                cmd = pub["cmdline"]
            else:
                try:
                    cmd = " ".join(proc.cmdline()) or None
                except Exception:  # muet-ok : cmdline refusee -> None, comptee juste en dessous dans `illisibles`
                    cmd = None
            if cmd is None:
                illisibles += 1
            mem = info.get("memory_info")
            entree = {
                "nom": info.get("name"),
                "ppid": pub.get("ppid") if (pub and pub.get("ppid") is not None and info.get("ppid") is None) else info.get("ppid"),
                # memoire refusee (vmmemWSL protege) = INCONNUE, jamais 0 (audit RAM 18/10)
                "rss_mo": round(mem.rss / 1e6, 1) if mem else None,
                "age_min": round((now - (info.get("create_time") or now)) / 60),
                "cree": info.get("create_time"),
                "user": info.get("username") or (pub.get("compte") if pub else None),
                "cmd": cmd,
            }
            if pub:
                entree["service"] = pub.get("service")
                entree["intention"] = pub.get("intention")
                entree["objectif"] = pub.get("objectif")
            procs[pid] = entree
        except Exception:  # muet-ok : processus disparu ou refuse entre l'iteration et la lecture -> compte illisible
            illisibles += 1
    return procs, illisibles


def _ports() -> dict:
    """port -> pid. Best effort : Windows refuse souvent les sockets d'autrui."""
    try:
        import psutil

        out = {}
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" and conn.laddr and conn.pid:
                out[int(conn.laddr.port)] = int(conn.pid)
        return out
    except Exception:
        return {}


def _qualifier_fantome(prevu: dict, now: float) -> str:
    """Un pid mort ne dit PAS la meme chose selon le service (mesure 2026-08-02).

    Trois cas etaient jetes dans le meme sac « FANTOME », dont deux ne sont pas des
    pannes :
      - `runAs=interactive` : le superviseur note le pid du LANCEUR, qui meurt aussitot
        apres avoir demarre le vrai process. Pid mort = ATTENDU, ca ne conclut rien
        (cf. RULES_SHARED, gotcha launcher).
      - aucun heartbeat declare : le service tourne SANS capteur de vitalite, sa mort
        est silencieuse par construction — il faut croiser port/process avant d'accuser.
      - heartbeat declare : c'est la seule branche ou un verdict est possible, et c'est
        sa FRAICHEUR qui parle, pas le pid.
    Fichier de heartbeat absent ou illisible => INDETERMINE, jamais « mort ».
    """
    if prevu.get("runAs") == "interactive":
        return "launcher (runAs=interactive) : le pid note est celui du lanceur — NON CONCLUANT"
    hb = prevu.get("heartbeat")
    if not hb:
        return "supervise SANS heartbeat : mort silencieuse par construction — croiser port/process"
    try:
        age = now - (SERVICES_TOML.parents[2] / hb).stat().st_mtime
    except OSError as exc:
        return f"heartbeat declare mais illisible ({type(exc).__name__}) : INDETERMINE, pas « mort »"
    seuil = (prevu.get("interval_s") or 300) * 2
    if age <= seuil:
        return f"INCOHERENT : bat encore (il y a {int(age)}s) alors que le pid declare est mort — pid perdu"
    return f"mort silencieuse probable : dernier battement il y a {int(age)}s (seuil {int(seuil)}s)"


# Protheses : moteurs tiers que le corps pilote sans les etre (audit RAM 18/10). Reconnues par le NOM du
# processus, sans casse ; l'executif Hamilton les actionne en dernier recours (keep_alive, arret WSL).
_PROTHESES = (
    ("wsl", re.compile(r"^(vmmem(wsl)?|wslservice\.exe|wslhost\.exe|wsl\.exe)$", re.I)),
    ("docker", re.compile(r"^(docker desktop\.exe|com\.docker\..*|dockerd(\.exe)?)$", re.I)),
    ("ollama", re.compile(r"^ollama( app)?(\.exe)?$|^ollama_llama_server(\.exe)?$", re.I)),
    ("llama", re.compile(r"^llama-server(\.exe)?$", re.I)),
    ("lmstudio", re.compile(r"^(lm studio\.exe|lms\.exe)$", re.I)),
)


def famille_prothese(nom: str | None) -> str | None:
    """Famille de prothese d'un processus d'apres son nom ; None si ce n'en est pas une."""
    for famille, motif in _PROTHESES:
        if nom and motif.match(nom):
            return famille
    return None


def _protheses(vivants: dict) -> dict:
    """{famille: {pids, rss_mo, rss_illisibles}} ; rss_mo None si AUCUNE memoire de la famille n'est lisible."""
    out: dict = {}
    for proc in vivants.values():
        famille = famille_prothese(proc.get("nom"))
        if famille is None:
            continue
        f = out.setdefault(famille, {"pids": 0, "rss_mo": None, "rss_illisibles": 0})
        f["pids"] += 1
        rss = proc.get("rss_mo")
        if rss is None:
            f["rss_illisibles"] += 1
        else:
            f["rss_mo"] = round((f["rss_mo"] or 0.0) + rss, 1)
    return out


# Processus d'EXECUTION dont le corps doit pouvoir dire qui ils sont (owner 19/10 : « TOUT doit etre identifiable »).
RUNTIMES = frozenset({"python.exe", "pythonw.exe", "py.exe", "opencode.exe", "deno.exe", "node.exe",
                      "llama-server.exe", "ollama.exe", "qdrant.exe"})
_JOB_TOLERANCE_S = 120.0      # le wrapper run_job demarre son worker en quelques secondes
# Le nom du PARENT comme preuve (inventaire reel 19/10) : le superviseur est lance par NSSM et absent de son propre
# statut ; un processus lance par un shell ou un CLI du poste est un CLIENT, hors du corps.
_PARENTS_NOMMES = {"nssm.exe": "superviseur LaForge-Master (lance par NSSM)",
                   "bash.exe": "client (shell du poste, hors corps)", "claude.exe": "client Claude Code (hors corps)",
                   "pwsh.exe": "client (console du poste, hors corps)",
                   "powershell.exe": "client (console du poste, hors corps)"}
# PROTHESES (owner 30/10 « rien ne doit t'echapper, Nokido ou ses protheses ») : un outil EXTERNE que le corps pilote
# (ensure_service, reclaimer) porte ses enfants hors du superviseur. Mesure 30/10 : node.exe 5,36 Go, enfant de
# llmster.exe (demon LM Studio), range non-soi -> RAM 99 % sans rien a evincer. Preuve `prothese` = SOI evincable.
_PARENTS_PROTHESES = {"llmster.exe": "prothese lmstudio (demon llmster, worker de modele)",
                      "lm studio.exe": "prothese lmstudio (interface)",
                      "ollama.exe": "prothese ollama (serveur llm)",
                      "com.docker.backend.exe": "prothese docker (interface)",
                      "qdrant.exe": "prothese qdrant (serveur vecteur)",
                      "agy.exe": "prothese agy (executeur CLI)",
                      "opencode.exe": "prothese opencode (executeur CLI)"}
_BATTEMENT_FRAIS_S = 900.0


def ancetre_identifie(pid, vivants, pid_service, identites, profondeur=8):
    """Identite heritee du plus proche ANCETRE identifie (pid du superviseur, ou identite deja prouvee), quel que soit
    le NOM du processus et a toute profondeur. 28/10 : docker-mcp.exe (port 8811) sortait « non revendique » alors
    qu'il descend de NokidoDockerMcpGateway (lanceur runas -> gardien -> docker.exe -> docker-mcp.exe) ; l'heritage ne
    remontait qu'un parent. None = aucun ancetre identifie (jamais devine par le nom)."""
    vus, anc, niveau = set(), (vivants.get(pid) or {}).get("ppid"), 1
    while anc is not None and anc not in vus and niveau <= profondeur:
        vus.add(anc)
        if anc in pid_service:
            return {"identite": "descendant de %s" % pid_service[anc], "preuve": "parente", "profondeur": niveau}
        connue = (identites or {}).get(str(anc))
        if connue and connue.get("identite"):
            return {"identite": "descendant de %s" % connue["identite"], "preuve": "parente", "profondeur": niveau}
        anc, niveau = (vivants.get(anc) or {}).get("ppid"), niveau + 1
    return None


def service_porteur(declares=None, chaine=None, timeout=5.0):
    """(service, profondeur, motif) : le service du superviseur dont CE process descend -- la propriete se DEMANDE a
    l'organe qui lance, jamais au nom du process ni a sa cmdline.

    `runAs interactive` : le superviseur note le pid du LANCEUR et son ENFANT execute (RULES_SHARED, 5 questions, 4) --
    d'ou la remontee de parente, jamais l'egalite de pid. Superviseur muet, parente illisible, aucun ancetre declare :
    (None, None, motif), et le motif le dit (UNKNOWN n'est pas OUI). Primitive UNIQUE (30/10) : l'identite d'un
    executeur au claim (forge_task_executor) et le principal exempte du coffre cloisonne (forge_secrets, COF-1).
    `declares` et `chaine` sont injectables pour les NR."""
    if declares is None:
        declares = _declares(timeout=timeout)
    if "__erreur__" in (declares or {}):
        return None, None, str(declares["__erreur__"].get("status") or "superviseur injoignable")[:120]
    if chaine is None:
        try:
            import psutil

            moi = psutil.Process(os.getpid())
            chaine = [moi.pid] + [p.pid for p in moi.parents()]
        except Exception as e:  # noqa: BLE001
            return None, None, "parente ILLISIBLE (%s)" % type(e).__name__
    pid_service = {d.get("pid"): nom for nom, d in (declares or {}).items() if isinstance(d, dict) and d.get("pid")}
    for i, pid in enumerate(chaine or []):
        if pid in pid_service:
            return pid_service[pid], i, "descendant (profondeur %d) du pid declare de %s" % (i, pid_service[pid])
    return None, None, "aucun ancetre de ce process n'est un pid declare par le superviseur"


def _parse_ts(val, default=0.0):
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            pass  # muet-ok : pas un epoch, on essaie le format ISO juste apres
        try:
            return time.mktime(time.strptime(val[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError):
            pass  # muet-ok : format inconnu -> `default`, que l'appelant traite comme date ILLISIBLE
    return default


def identifier_processus(vivants, pid_service, jobs, battements, maintenant=None, profondeur=8):
    """(identites {pid: {identite, preuve}}, non_identifies [...]) pour les RUNTIMES, par cascade de preuves :
    superviseur -> job -> battement -> parente. Un job ou un battement n'identifie un pid que s'il est COHERENT dans le
    temps avec la creation du processus (19/10 : pid 1988 « matchait » un job du 10/09 -- pid recycle)."""
    maintenant = time.time() if maintenant is None else maintenant

    enfants_par_pid = {}
    for exec_pid, b in (battements or {}).items():
        for enf in (b.get("enfants") or []):
            try:
                enf_int = int(enf)
                ts_cand = _parse_ts(b.get("ts") or b.get("payload_ts"))
                if enf_int not in enfants_par_pid or ts_cand > enfants_par_pid[enf_int][0]:
                    enfants_par_pid[enf_int] = (ts_cand, b)
            except (ValueError, TypeError):
                print("[inventaire] pid enfant illisible %r dans le battement de %s" % (enf, exec_pid), file=sys.stderr)
                continue

    def directe(pid):
        cree = (vivants.get(pid) or {}).get("cree")
        if pid in pid_service:
            return {"identite": pid_service[pid], "preuve": "superviseur"}
        j = jobs.get(pid)
        if j and cree is not None and abs(float(j.get("debut") or 0) - float(cree)) <= _JOB_TOLERANCE_S:
            return {"identite": j["identite"], "preuve": "job"}
        b = battements.get(pid)
        if (b and cree is not None and float(b.get("ts") or 0) >= float(cree)
                and maintenant - float(b.get("ts") or 0) <= _BATTEMENT_FRAIS_S):
            return {"identite": b["identite"], "preuve": "battement"}
        if pid in enfants_par_pid:
            ts_enf, b_enf = enfants_par_pid[pid]
            if cree is None or not ts_enf or ts_enf >= float(cree) - _JOB_TOLERANCE_S:
                ident = b_enf.get("identite") or b_enf.get("executeur") or "executeur"
                return {"identite": ident, "preuve": "battement_enfant"}
        return None

    ids, non = {}, []
    for pid, proc in vivants.items():
        if (proc.get("nom") or "").lower() not in RUNTIMES:
            continue
        ident, anc, vus = directe(pid), proc.get("ppid"), set()
        for _ in range(profondeur):
            if ident or anc is None or anc in vus:
                break
            vus.add(anc)
            d = directe(anc)
            if d:
                ident = {"identite": "descendant de %s" % d["identite"], "preuve": "parente"}
            anc = (vivants.get(anc) or {}).get("ppid")
        parent_nom = ((vivants.get(proc.get("ppid")) or {}).get("nom") or "").lower()
        if not ident and parent_nom in _PARENTS_PROTHESES:
            ident = {"identite": _PARENTS_PROTHESES[parent_nom], "preuve": "prothese"}
        if not ident and parent_nom in _PARENTS_NOMMES:
            ident = {"identite": _PARENTS_NOMMES[parent_nom], "preuve": "parent"}
        if ident:
            ids[pid] = ident
        else:
            non.append({"pid": pid, "nom": proc.get("nom"), "ppid": proc.get("ppid"),
                        "parent": (vivants.get(proc.get("ppid")) or {}).get("nom"), "rss_mo": proc.get("rss_mo"),
                        "user": proc.get("user")})
    return ids, sorted(non, key=lambda n: n["pid"])


def _jobs_par_pid() -> dict:
    """pid -> {identite, debut} depuis sandbox/jobs/*.json (une fiche illisible n'identifie personne)."""
    import datetime as _dt

    out = {}
    for f in (_donnees() / "sandbox" / "jobs").glob("job_*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            debut = _dt.datetime.fromisoformat(str(d["started"])).timestamp()
            out[int(d["pid"])] = {"identite": "%s (%s)" % (f.stem, Path(str(d.get("script") or "?")).name),
                                  "debut": debut}
        except (OSError, ValueError, KeyError, TypeError):
            continue  # muet-ok : fiche illisible ou incomplete, ce job n'identifie personne
    return out


_RE_AGENT_CMD = re.compile(r"--agent[ =]+[\"']?([\w.-]+)", re.I)


def cle_doublon(script: str, cmd: str | None, service: str | None) -> str:
    """Owner 9/11 (« visibilite parfaite, sinon pas d'autoregulation ») : 9 `forge_task_executor.py` d'agents
    differents etaient comptes en DOUBLONS (groupement par nom de script). Un doublon = meme script ET meme organe :
    le service du registre prime (ligne de commande souvent ILLISIBLE hors compte proprietaire), puis `--agent`,
    sinon le script seul."""
    if service:
        return "%s@%s" % (script, service)
    m = _RE_AGENT_CMD.search(cmd or "")
    return "%s@%s" % (script, m.group(1).upper()) if m else script


def _battements_par_pid() -> dict:
    """pid -> {identite, ts, ...} depuis sandbox/*.heartbeat (JSON avec pid) ; ts = date d'ecriture du fichier."""
    out = {}
    for f in (_donnees() / "sandbox").glob("*.heartbeat"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            pid = int(d["pid"])
            enfants = [int(x) for x in d.get("enfants") or [] if isinstance(x, int) or (isinstance(x, str) and str(x).lstrip("-").isdigit())]
            out[pid] = {
                "identite": f.name,
                "ts": f.stat().st_mtime,
                "payload_ts": d.get("ts"),
                "agent": d.get("agent"),
                "enfants": enfants,
            }
        except (OSError, ValueError, KeyError, TypeError):
            continue  # muet-ok : battement non JSON ou sans pid, il n'identifie personne
    return out


def _orphelins_prouves(vivants: dict, battements: dict) -> list[dict]:
    """Processus declares enfants par le DERNIER battement d'un executeur dont le pid est MORT (ou dont le parent est mort).

    Sans cette preuve : jamais « orphelin » (INCERTAIN) — constitution UNKNOWN != NO.
    Rend [{pid, nom, rss_mo, executeur, battement_ts}, ...].
    """
    if not vivants or not battements:
        return []

    derniers = {}
    for exec_pid, b in battements.items():
        cle = b.get("identite") or b.get("executeur") or str(exec_pid)
        ts = _parse_ts(b.get("ts") or b.get("payload_ts"))
        if cle not in derniers or ts > derniers[cle][0]:
            derniers[cle] = (ts, exec_pid, b)

    orphelins = []
    vus = set()
    for cle, (ts, exec_pid, b) in derniers.items():
        # Relecture Claude 9/11 : seul un executeur MORT prouve des orphelins (un executeur vivant dont le lanceur
        # est mort a toujours ses enfants ; les dire orphelins serait une sur-deduction).
        if exec_pid in vivants:
            continue

        enfants = b.get("enfants") or []
        for enf_pid in enfants:
            try:
                enf_pid_int = int(enf_pid)
            except (ValueError, TypeError):
                print("[inventaire] pid enfant illisible %r (executeur %s) : non juge" % (enf_pid, cle), file=sys.stderr)
                continue
            if enf_pid_int in vus:
                continue
            proc = vivants.get(enf_pid_int)
            if not proc:
                continue
            b_ts = b.get("ts") if b.get("ts") is not None else (b.get("payload_ts") or ts)
            # Pid RECYCLE (relecture Claude 9/11) : l'enfant doit etre ne AVANT le battement qui le declare ; date de
            # creation illisible -> INCERTAIN, jamais « orphelin » (UNKNOWN != NO).
            cree = proc.get("cree")
            if cree is None or float(cree) > _parse_ts(b_ts, ts) + _JOB_TOLERANCE_S:
                continue
            vus.add(enf_pid_int)
            orphelins.append({
                "pid": enf_pid_int,
                "nom": proc.get("nom"),
                "rss_mo": proc.get("rss_mo"),
                "executeur": b.get("identite") or b.get("executeur") or cle,
                "battement_ts": b_ts,
            })

    return sorted(orphelins, key=lambda o: o["pid"])


def collect(registre: Path | str | dict | None = None) -> dict:
    global _PUBLIES_COURANTS
    now = time.time()
    if registre is not None:
        declares = (
            _decoder_registre_payload(registre)
            if isinstance(registre, dict)
            else _lire_registre_superviseur(registre)
        )
    elif Path(REGISTRE_SUPERVISEUR) != _REGISTRE_SUPERVISEUR_DEFAUT:
        declares = _lire_registre_superviseur(REGISTRE_SUPERVISEUR)
    else:
        declares = _declares()
    prevus = _prevus()
    registre_illisible = not isinstance(declares, dict) or "__erreur__" in declares
    publies = _pids_publies(declares, prevus)
    _PUBLIES_COURANTS = publies
    try:
        vivants, illisibles = _vivants()
    finally:
        _PUBLIES_COURANTS = None

    for pid_pub, pub in publies.items():
        if pid_pub in vivants:
            if vivants[pid_pub].get("cmd") is None and pub.get("cmdline"):
                vivants[pid_pub]["cmd"] = pub["cmdline"]
                illisibles = max(0, illisibles - 1)
            vivants[pid_pub]["service"] = pub.get("service")
            vivants[pid_pub]["intention"] = pub.get("intention")
            vivants[pid_pub]["objectif"] = pub.get("objectif")

    ports = _ports()

    fantomes, pid_service = [], {}
    if not registre_illisible:
        for nom, decl in declares.items():
            if str(nom).startswith("__") or not isinstance(decl, dict) or decl.get("status") != "running":
                continue
            pid = decl.get("pid")
            if not pid or int(pid) not in vivants:
                fantomes.append(
                    {"service": nom, "pid_declare": pid, "uptime_annonce_s": decl.get("uptime_s"),
                     "qualification": _qualifier_fantome(prevus.get(nom, {}), now)}
                )
            else:
                pid_service[int(pid)] = str(decl.get("service") or nom)

    # Liste blanche (consigne owner 8/11 : LE SUPERVISEUR PUBLIE) :
    # - un pid publie = identifie (service, intention, cmdline) ;
    # - les descendants d'un pid publie heritent a toute profondeur (ancetre_identifie, commit 9cb92a322) ;
    # - ce qui reste non publie et non herite = ILLISIBLE nomme, jamais compte sain.
    identifies_registre = {}
    herite = {}
    liste_illisibles = []
    if registre_illisible:
        for pid, proc in sorted(vivants.items()):
            liste_illisibles.append(
                {
                    "pid": pid,
                    "nom": proc.get("nom"),
                    "ppid": proc.get("ppid"),
                    "user": proc.get("user"),
                    "statut": "ILLISIBLE",
                    "motif": "registre_illisible",
                }
            )
        if not liste_illisibles:
            liste_illisibles.append(
                {
                    "pid": None,
                    "nom": None,
                    "ppid": None,
                    "user": None,
                    "statut": "ILLISIBLE",
                    "motif": "registre_illisible",
                }
            )
    else:
        for pid, proc in sorted(vivants.items()):
            if pid in pid_service:
                pub = publies.get(pid) or {}
                nom_svc = pub.get("service") or pid_service[pid]
                decl_svc = (declares.get(nom_svc) if isinstance(declares, dict) else None) or {}
                prevu_svc = (prevus.get(nom_svc) if isinstance(prevus, dict) else None) or {}
                intention_svc = pub.get("intention") or decl_svc.get("intention") or prevu_svc.get("intention")
                objectif_svc = pub.get("objectif") or decl_svc.get("objectif") or prevu_svc.get("objectif")
                cmd_svc = pub.get("cmdline") or decl_svc.get("cmdline") or proc.get("cmd")
                identifies_registre[str(pid)] = {
                    "pid": pid,
                    "ppid": pub.get("ppid") if pub.get("ppid") is not None else proc.get("ppid"),
                    "service": nom_svc,
                    "intention": intention_svc,
                    "objectif": objectif_svc,
                    "cmdline": cmd_svc,
                    "compte": pub.get("compte") or decl_svc.get("compte") or proc.get("user"),
                    "heure": pub.get("heure") or decl_svc.get("heure"),
                    "nom": proc.get("nom"),
                    "statut": "IDENTIFIE",
                    "preuve": "registre_superviseur",
                }
                continue
            anc = ancetre_identifie(pid, vivants, pid_service, {})
            if anc is not None:
                service_anc = anc["identite"].removeprefix("descendant de ")
                decl_anc = (declares.get(service_anc) if isinstance(declares, dict) else None) or {}
                prevu_anc = (prevus.get(service_anc) if isinstance(prevus, dict) else None) or {}
                intention_anc = decl_anc.get("intention") or prevu_anc.get("intention")
                objectif_anc = decl_anc.get("objectif") or prevu_anc.get("objectif")
                herite[pid] = {
                    "via_parent": service_anc,
                    "service": service_anc,
                    "intention": intention_anc,
                    "objectif": objectif_anc,
                    "nom": proc.get("nom"),
                    "ppid": proc.get("ppid"),
                    "profondeur": anc["profondeur"],
                    "statut": "HERITE",
                    "preuve": "parente",
                }
                proc.setdefault("service", service_anc)
                proc.setdefault("intention", intention_anc)
            else:
                liste_illisibles.append(
                    {
                        "pid": pid,
                        "nom": proc.get("nom"),
                        "ppid": proc.get("ppid"),
                        "user": proc.get("user"),
                        "statut": "ILLISIBLE",
                        "motif": "non_publie_non_herite",
                    }
                )

    figes = []
    for nom, prevu in prevus.items():
        if nom.startswith("__") or not prevu.get("heartbeat"):
            continue
        if declares.get(nom, {}).get("status") != "running":
            continue
        hb = ROOT / prevu["heartbeat"]
        if not hb.exists():
            figes.append({"service": nom, "heartbeat": "ABSENT"})
            continue
        age_min = (now - hb.stat().st_mtime) / 60
        tier = prevu.get("tier") or TIER_DEFAUT
        seuil = TIER_RESTART_S.get(tier, TIER_RESTART_S[TIER_DEFAUT]) / 60.0
        interval_s = prevu.get("interval_s")
        if interval_s:  # un cycle plus long que son tier prime sur le tier
            seuil = max(seuil, HEARTBEAT_CYCLES_TOLERES * interval_s / 60.0)
        if prevu.get("heartbeat_max_s"):  # borne DECLAREE par l'organe dans services.toml : elle prime aussi
            seuil = max(seuil, prevu["heartbeat_max_s"] / 60.0)
        if age_min > seuil:
            figes.append(
                {
                    "service": nom,
                    "heartbeat_age_min": round(age_min),
                    "seuil_min": round(seuil),
                    "tier": tier,
                    "interval_s": interval_s,
                }
            )

    battements = _battements_par_pid()
    identification = _identification(vivants, pid_service, battements=battements)
    orphelins_prouves = _orphelins_prouves(vivants, battements)
    for k_pid, info_reg in identifies_registre.items():
        if k_pid in identification["identites"]:
            identification["identites"][k_pid]["service"] = info_reg["service"]
            identification["identites"][k_pid]["intention"] = info_reg["intention"]
            identification["identites"][k_pid]["cmdline"] = info_reg["cmdline"]
    for k_pid_int, info_her in herite.items():
        k_pid = str(k_pid_int)
        if k_pid in identification["identites"]:
            identification["identites"][k_pid]["service"] = info_her["service"]
            identification["identites"][k_pid]["intention"] = info_her["intention"]

    inconnus = []
    for port, pid in sorted(ports.items()):
        if pid in pid_service or pid in herite or str(pid) in identification["identites"]:
            continue  # un port n'est inconnu que si son processus n'a AUCUNE identite prouvee (19/10)
        if ancetre_identifie(pid, vivants, pid_service, identification["identites"]):
            continue  # descendant d'un service, a toute profondeur (28/10 : docker-mcp.exe du gateway)
        proc = vivants.get(pid)
        if not proc or (proc.get("nom") or "").lower() in SYSTEM_NOMS:
            continue
        inconnus.append(
            {
                "port": port,
                "pid": pid,
                "nom": proc["nom"],
                "rss_mo": proc["rss_mo"],
                # tri-etat VOLONTAIRE : None = cmdline illisible. Rendre False ici
                # ferait dire « ce n'est pas Nokido » a un capteur qui n'a rien vu.
                "nokido": (
                    None
                    if proc.get("cmd") is None
                    else bool(NOKIDO_RE.search(proc["cmd"]))
                ),
            }
        )

    # S'exclure soi-meme : un inventaire qui se compte en doublon lit sa propre trace
    # (le wrapper run_job + son worker portent le meme script).
    import os

    moi = {os.getpid(), (vivants.get(os.getpid()) or {}).get("ppid")}
    par_script = {}
    for pid, proc in vivants.items():
        if pid in moi:
            continue
        noms = re.findall(r"([\w\-]+\.(?:py|ts))", proc.get("cmd") or "")
        if noms:
            svc = pid_service.get(pid) or (herite.get(pid) or {}).get("service")
            par_script.setdefault(cle_doublon(noms[-1], proc.get("cmd"), svc), []).append(pid)
    doublons = {
        k: v for k, v in par_script.items() if len(v) > 1 and k.split("@", 1)[0] != Path(__file__).name
    }

    nb_identifies = "ILLISIBLE" if registre_illisible else len(identifies_registre)
    nb_herites = "ILLISIBLE" if registre_illisible else len(herite)
    nb_illisibles = "ILLISIBLE" if registre_illisible else len(liste_illisibles)

    return {
        "horodatage": time.strftime("%Y-%m-%d %H:%M:%S"),
        "etat_registre": "ILLISIBLE" if registre_illisible else "OK",
        "totaux": {
            "process_vivants": len(vivants),
            "identifies": nb_identifies,
            "herites": nb_herites,
            "illisibles": nb_illisibles,
            "ILLISIBLE": nb_illisibles,
            "cmdline_illisibles": "ILLISIBLE" if registre_illisible else illisibles,
            "services_declares": "ILLISIBLE" if registre_illisible else len([k for k in declares if not str(k).startswith("__")]),
            "declares_avec_pid_vivant": "ILLISIBLE" if registre_illisible else len(pid_service),
            "ports_lus": len(ports),
        },
        "identifies": "ILLISIBLE" if registre_illisible else identifies_registre,
        "herites": "ILLISIBLE" if registre_illisible else {str(k): v for k, v in sorted(herite.items())},
        "illisibles": liste_illisibles,
        "ILLISIBLE": liste_illisibles,
        "fantomes": fantomes,
        "figes": figes,
        "inconnus": inconnus,
        "doublons": doublons,
        "protheses": _protheses(vivants),
        "pid_vers_service": {str(k): v for k, v in sorted(pid_service.items())},
        "enfants_herites": {str(k): v for k, v in sorted(herite.items())},
        "orphelins_prouves": orphelins_prouves,
        **identification,
    }


def _identification(vivants, pid_service, battements=None) -> dict:
    """Identites de TOUS les runtimes (owner 19/10) ; les non-identifies sont listes ET comptes, jamais tus."""
    if battements is None:
        battements = _battements_par_pid()
    ids, non = identifier_processus(vivants, pid_service, _jobs_par_pid(), battements)
    return {"identites": {str(k): v for k, v in sorted(ids.items())}, "non_identifies": non,
            "runtimes": {"identifies": len(ids), "non_identifies": len(non)}}


def main() -> int:
    ap = argparse.ArgumentParser(description="Inventaire read-only des process Nokido.")
    ap.add_argument("--json", action="store_true", help="sortie brute")
    args = ap.parse_args()
    rapport = collect()
    if args.json:
        print(json.dumps(rapport, indent=1, ensure_ascii=False))
        return 0
    tot = rapport["totaux"]
    print(
        f"[inventaire] {tot['process_vivants']} process | "
        f"identifies={tot['identifies']} / herites={tot['herites']} / ILLISIBLE={tot['ILLISIBLE']} | "
        f"({tot['cmdline_illisibles']} cmdline illisibles = angle mort du compte) | "
        f"{tot['declares_avec_pid_vivant']}/{tot['services_declares']} services avec pid vivant"
    )
    print(f"\nILLISIBLE (non publies et non herites): {len(rapport['illisibles'])}")
    for item in rapport["illisibles"]:
        print("   ", json.dumps(item, ensure_ascii=False))
    for cle, titre in (
        ("fantomes", "FANTOMES (declare running, pid mort)"),
        ("figes", "FIGES (pid vivant, heartbeat perime)"),
        ("inconnus", "ECOUTANTS non revendiques"),
    ):
        lignes = rapport[cle]
        print(f"\n{titre}: {len(lignes)}")
        for item in lignes:
            print("   ", json.dumps(item, ensure_ascii=False))
    if rapport["doublons"]:
        print(f"\nDOUBLONS: {rapport['doublons']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
