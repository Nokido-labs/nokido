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
import json
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


def _declares(timeout: float = 10.0) -> dict:
    """Ce que le superviseur AFFIRME. Peut mentir sur un pid mort — d'ou le croisement."""
    try:
        with urllib.request.urlopen(SUPERVISOR, timeout=timeout) as resp:
            payload = json.loads(resp.read())
    except Exception as exc:  # superviseur injoignable != aucun service
        return {"__erreur__": {"status": f"superviseur injoignable: {exc}"[:120]}}
    raw = payload.get("services") or payload
    items = raw.items() if isinstance(raw, dict) else [(s.get("name"), s) for s in raw]
    out = {}
    for name, svc in items:
        if name and isinstance(svc, dict):
            out[str(name)] = {
                "status": svc.get("status"),
                "pid": svc.get("pid"),
                "uptime_s": svc.get("uptime_s"),
                "restarts": svc.get("restarts"),
            }
    return out


def _prevus() -> dict:
    """Ce que services.toml PREVOIT : script d'entree + fichier de heartbeat."""
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
        out[m_name.group(1)] = {
            "script": script,
            "heartbeat": m_hb.group(1) if m_hb else None,
            "interval_s": interval,
            "heartbeat_max_s": int(m_hbmax.group(1)) if m_hbmax else None,
            "tier": m_tier.group(1) if m_tier else TIER_DEFAUT,
            "disabled": "disabled = true" in bloc,
            "runAs": m_runas.group(1) if m_runas else None,
        }
    return out


def _vivants() -> tuple[dict, int]:
    """Ce qui TOURNE. `illisibles` compte les cmdline refusees : ne jamais lire
    une cmdline vide comme une absence de process."""
    import psutil

    now = time.time()
    procs, illisibles = {}, 0
    for proc in psutil.process_iter(
        ["pid", "ppid", "name", "create_time", "memory_info", "username"]
    ):
        try:
            info = proc.info
            try:
                cmd = " ".join(proc.cmdline()) or None
            except Exception:  # muet-ok : cmdline refusee -> None, comptee juste en dessous dans `illisibles`
                cmd = None
            if cmd is None:
                illisibles += 1
            mem = info.get("memory_info")
            procs[info["pid"]] = {
                "nom": info.get("name"),
                "ppid": info.get("ppid"),
                # memoire refusee (vmmemWSL protege) = INCONNUE, jamais 0 (audit RAM 18/10)
                "rss_mo": round(mem.rss / 1e6, 1) if mem else None,
                "age_min": round((now - (info.get("create_time") or now)) / 60),
                "cree": info.get("create_time"),
                "user": info.get("username"),
                "cmd": cmd,
            }
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
_BATTEMENT_FRAIS_S = 900.0


def identifier_processus(vivants, pid_service, jobs, battements, maintenant=None, profondeur=8):
    """(identites {pid: {identite, preuve}}, non_identifies [...]) pour les RUNTIMES, par cascade de preuves :
    superviseur -> job -> battement -> parente. Un job ou un battement n'identifie un pid que s'il est COHERENT dans le
    temps avec la creation du processus (19/10 : pid 1988 « matchait » un job du 10/09 -- pid recycle)."""
    maintenant = time.time() if maintenant is None else maintenant

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


def _battements_par_pid() -> dict:
    """pid -> {identite, ts} depuis sandbox/*.heartbeat (JSON avec pid) ; ts = date d'ecriture du fichier."""
    out = {}
    for f in (_donnees() / "sandbox").glob("*.heartbeat"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out[int(d["pid"])] = {"identite": f.name, "ts": f.stat().st_mtime}
        except (OSError, ValueError, KeyError, TypeError):
            continue  # muet-ok : battement non JSON ou sans pid, il n'identifie personne
    return out


def collect() -> dict:
    now = time.time()
    declares, prevus = _declares(), _prevus()
    vivants, illisibles = _vivants()
    ports = _ports()

    fantomes, pid_service = [], {}
    for nom, decl in declares.items():
        if nom.startswith("__") or decl.get("status") != "running":
            continue
        pid = decl.get("pid")
        if not pid or int(pid) not in vivants:
            fantomes.append(
                {"service": nom, "pid_declare": pid, "uptime_annonce_s": decl.get("uptime_s"),
                 "qualification": _qualifier_fantome(prevus.get(nom, {}), now)}
            )
        else:
            pid_service[int(pid)] = nom

    # un enfant herite de l'identite de son lanceur (gotcha wrapper -> enfant)
    herite = {}
    for pid, proc in vivants.items():
        parent = proc.get("ppid")
        if pid not in pid_service and parent in pid_service:
            herite[pid] = {"via_parent": pid_service[parent], "nom": proc["nom"], "ppid": parent}

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

    identification = _identification(vivants, pid_service)
    inconnus = []
    for port, pid in sorted(ports.items()):
        if pid in pid_service or pid in herite or str(pid) in identification["identites"]:
            continue  # un port n'est inconnu que si son processus n'a AUCUNE identite prouvee (19/10)
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
            par_script.setdefault(noms[-1], []).append(pid)
    doublons = {
        k: v for k, v in par_script.items() if len(v) > 1 and k != Path(__file__).name
    }

    return {
        "horodatage": time.strftime("%Y-%m-%d %H:%M:%S"),
        "totaux": {
            "process_vivants": len(vivants),
            "cmdline_illisibles": illisibles,
            "services_declares": len([k for k in declares if not k.startswith("__")]),
            "declares_avec_pid_vivant": len(pid_service),
            "ports_lus": len(ports),
        },
        "fantomes": fantomes,
        "figes": figes,
        "inconnus": inconnus,
        "doublons": doublons,
        "protheses": _protheses(vivants),
        "pid_vers_service": {str(k): v for k, v in sorted(pid_service.items())},
        "enfants_herites": {str(k): v for k, v in sorted(herite.items())},
        **identification,
    }


def _identification(vivants, pid_service) -> dict:
    """Identites de TOUS les runtimes (owner 19/10) ; les non-identifies sont listes ET comptes, jamais tus."""
    ids, non = identifier_processus(vivants, pid_service, _jobs_par_pid(), _battements_par_pid())
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
        f"[inventaire] {tot['process_vivants']} process "
        f"({tot['cmdline_illisibles']} cmdline illisibles = angle mort du compte) | "
        f"{tot['declares_avec_pid_vivant']}/{tot['services_declares']} services avec pid vivant"
    )
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
