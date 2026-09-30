#!/usr/bin/env python3
"""forge_boot_diagnostic.py — diagnostic démarrage + TRACKER résiduel Nokido.

v1 (2026-06-12) : « rien ne devrait se lancer avant le lanceur » — log des AUTO_START fautifs.
v2 (2026-06-12, « il faut que tu track tout ») : snapshots/diff de l'écosystème COMPLET :
  - arbre process (pid/ppid/parent vivant ?/cmdline/user/RSS/âge) python+deno+nssm+llm+docker
  - ORPHELINS : parent mort = lancé par un cmd éphémère (trace les lanceurs fantômes)
  - DOUBLONS : même script xN (ex. 2 superviseurs, 2 watchdogs, 2 netcfg)
  - services par REGISTRE/SCM complet, pas une liste fixe (attrape gemini_poll_daemon & co)
    + commande réelle nssm (Parameters\\Application) + start type (AUTO=fautif/DEMAND/DISABLED)
  - ports LISTEN -> pid (qui squatte :8765/:8766/:7500...)
  - attendu services.toml (enabled) vs réel

Usage (SESSION user pour cmdlines complètes ; sandbox = données partielles) :
  LAFORGE_PYTHON tools/forge_boot_diagnostic.py                 # rapport boot + snapshot 'boot'
  LAFORGE_PYTHON tools/forge_boot_diagnostic.py --snap <label>  # snapshot étiqueté
  LAFORGE_PYTHON tools/forge_boot_diagnostic.py --diff A B      # diff 2 labels ou chemins .json

Protocole restart-lanceur : --snap avant -> stop via lanceur -> --snap stop (SURVIVANTS = fuites)
-> start -> --snap apres -> --diff avant apres.
Sorties : logs/boot_diagnostic.log (résumés, append) + logs/proc_tracker/*.json (snapshots).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "boot_diagnostic.log"
SNAP_DIR = ROOT / "logs" / "proc_tracker"
_SVC_HINT = ("laforge", "netcfg", "deno", "ollama", "docker", "wsl", "gemini", "forge", "caddy")
_ECO_EXE = {"deno.exe", "nssm.exe", "ollama.exe", "llama-server.exe", "caddy.exe", "node.exe"}
_PY_HINT = ("forge", "laforge", "netcfg", "gemini", "supervisor", "watchdog", "poll_daemon", "uvicorn")
_PORTS = (8765, 8766, 8767, 8768, 7400, 7401, 7420, 7500, 7600, 7611,
          8000, 8080, 8099, 9200, 11434, 1234, 5557, 3210)
# sigs génériques jamais comptées en doublon (multiples = normal ou cmdline illisible)
_DUP_IGNORE = {"conhost.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "pythonw.exe"}
_AUX = {
    "ollama": ("ollama.exe", "ollama app.exe"),
    "llama.cpp": ("llama-server.exe",),
    "lmstudio": ("lm studio.exe", "lms.exe"),
    "docker": ("docker desktop.exe", "com.docker.backend.exe", "com.docker.service",
               "dockerd.exe", "vpnkit.exe", "vmmem", "vmmemwsl", "wslservice.exe"),
}


def _all_procs() -> dict:
    """Table pid -> (name, create_time) de TOUS les process (pour test parent vivant)."""
    import psutil
    t = {}
    for p in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            t[p.info["pid"]] = (p.info["name"] or "?", p.info["create_time"] or 0)
        except Exception:
            continue
    return t


def _sig(name: str, cmd: str) -> str:
    """Signature doublon : basename du script (.py/.ts/.bat/.ps1) sinon exe (+ modèle llama)."""
    toks = [t.strip('"') for t in cmd.split()]
    script = next((Path(t).name for t in toks
                   if t.lower().endswith((".py", ".ts", ".bat", ".ps1"))), None)
    s = script or name
    if "llama-server" in name.lower():
        try:
            s += ":" + Path(toks[toks.index("-m") + 1]).name
        except (ValueError, IndexError):
            pass
    return s


def _procs_full():
    """Arbre écosystème : sélection nom/cmdline + enfants récursifs des pids retenus."""
    import psutil
    allp = _all_procs()
    now = time.time()
    rows: dict[int, dict] = {}

    def _row(p):
        i = p.info
        cmd = " ".join(i.get("cmdline") or [])
        if not cmd:
            try:
                cmd = "[exe] " + (p.exe() or "?")
            except Exception:
                cmd = "[cmdline refusee]"
        ppid = i.get("ppid") or 0
        ctime = i.get("create_time") or now
        if ppid in allp:
            pn, pct = allp[ppid]
            parent = f"{pn}({ppid})" if pct <= ctime else f"REUSE({ppid})=ORPHELIN"
        else:
            parent = f"MORT({ppid})=ORPHELIN"
        try:
            rss = round(p.memory_info().rss / 1e6)
        except Exception:
            rss = None
        try:
            user = p.username().split("\\")[-1]
        except Exception:
            user = "?"
        return {"pid": i["pid"], "ppid": ppid, "parent": parent, "name": i["name"], "user": user,
                "age_s": round(now - ctime), "rss_MB": rss, "ctime": round(ctime, 2),
                "sig": _sig(i["name"] or "?", cmd), "cmd": cmd[:300]}

    cands = []
    for p in psutil.process_iter(["pid", "ppid", "name", "cmdline", "create_time"]):
        try:
            nm = (p.info["name"] or "").lower()
            cl = " ".join(p.info["cmdline"] or []).lower()
            cands.append(p)
            if (nm in _ECO_EXE
                    or ("python" in nm and any(h in cl for h in _PY_HINT))
                    or any(a in nm for a in ("vmmem", "wslservice", "docker", "lm studio"))):
                rows[p.info["pid"]] = _row(p)
        except Exception:
            continue
    # rattacher les enfants opaques (python sans cmdline lisible, wrappers cmd) — fixpoint
    grew = True
    while grew:
        grew = False
        for p in cands:
            try:
                pid, ppid = p.info["pid"], p.info.get("ppid") or 0
                nm = (p.info["name"] or "").lower()
                if (pid not in rows and ppid in rows and nm in
                        ("python.exe", "pythonw.exe", "cmd.exe", "powershell.exe", "pwsh.exe")):
                    rows[pid] = _row(p)
                    grew = True
            except Exception:
                continue
    out = sorted(rows.values(), key=lambda r: r["ctime"])
    orphelins = [r for r in out if "ORPHELIN" in r["parent"]]
    sigs: dict[str, list] = {}
    for r in out:
        sigs.setdefault(r["sig"], []).append(r["pid"])
    doublons = {s: pids for s, pids in sigs.items() if len(pids) > 1 and s not in _DUP_IGNORE}
    return out, orphelins, doublons


def _ports_listen(sel_pids: set) -> dict:
    """Ports LISTEN -> pids (écosystème ou ports Nokido connus)."""
    import psutil
    res: dict[int, set] = {}
    err = None
    try:
        for c in psutil.net_connections("inet"):
            if "LISTEN" not in str(c.status) or not c.laddr:
                continue
            if c.pid in sel_pids or c.laddr.port in _PORTS:
                res.setdefault(c.laddr.port, set()).add(c.pid or -1)
    except Exception as e:  # noqa: BLE001
        err = str(e)[:80]
    out = {str(k): sorted(v) for k, v in sorted(res.items())}
    if err:
        out["err"] = err
    return out


def _nssm_params(name: str):
    """Commande réelle d'un service nssm via registre (lisible sans admin)."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           rf"SYSTEM\CurrentControlSet\Services\{name}\Parameters")
        app = str(winreg.QueryValueEx(k, "Application")[0])
        try:
            par = str(winreg.QueryValueEx(k, "AppParameters")[0])[:160]
        except OSError:
            par = ""
        winreg.CloseKey(k)
        return app, par
    except OSError:
        return None, None


# Un service NSSM redirige sa sortie vers deux fichiers declares au registre. Ce
# sont les SEULS endroits ou atterrit le stderr d'un service qui meurt au boot :
# le superviseur ne capture pas la sortie des siens, et AUCUNE des 7 afferences
# sous contrat de `forge_trace_spine` ne la porte (mesure 2026-09-05 :
# `hub_blackbox` = 2791 evenements sur 8 h, 0 mention des daemons tombes).
# Il a fallu relancer chaque daemon a la main pour lui voler son traceback ;
# cette fonction rend ce detour inutile.
_MOTS_ERREUR = ("traceback", "error", "exception", "denied", "refus", "fatal",
                "critical", "no module", "address in use")


def _flux_nssm(chemin: str, lignes: int = 3) -> dict:
    """Etat d'UN flux de log NSSM. Quatre etats, jamais deux.

    `ABSENT` (le fichier declare n'existe pas) et `VIDE` (il existe et pese 0)
    ne disent pas la meme chose : le premier est un service qui n'a jamais ecrit,
    le second un service dont la sortie est captee mais muette. Les confondre
    ferait lire « rien a signaler » sur un canal qui n'a jamais rien capte.
    """
    if not chemin:
        return {"etat": "NON_DECLARE"}
    try:
        taille = os.path.getsize(chemin)
    except OSError as exc:
        return {"etat": "ABSENT" if isinstance(exc, FileNotFoundError) else "ILLISIBLE",
                "chemin": chemin, "raison": type(exc).__name__}
    age_h = (time.time() - os.path.getmtime(chemin)) / 3600.0
    if taille == 0:
        return {"etat": "VIDE", "chemin": chemin, "age_h": round(age_h, 1)}
    try:
        with open(chemin, "rb") as fh:
            fh.seek(max(0, taille - 6000))
            brut = fh.read()
    except OSError as exc:
        return {"etat": "ILLISIBLE", "chemin": chemin, "raison": type(exc).__name__}
    fin = [x for x in brut.decode("utf-8", "replace").splitlines() if x.strip()][-lignes:]
    bas = " ".join(fin).lower()
    return {"etat": "ERREUR" if any(m in bas for m in _MOTS_ERREUR) else "OK",
            "chemin": chemin, "octets": taille, "age_h": round(age_h, 1),
            "fin": [x[:200] for x in fin]}


def logs_nssm() -> dict:
    """Collecte les DEUX flux de chaque service NSSM et les classe.

    Rend {"services": {...}, "compte": {...}} — le compte par etat sert de
    denominateur : sans lui, « aucune erreur trouvee » ne se distingue pas de
    « aucun log lisible ».
    """
    res: dict = {}
    try:
        import winreg
        racine = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Services")
    except OSError as exc:
        return {"services": {}, "compte": {"ILLISIBLE": 1},
                "raison": "registre illisible (%s)" % type(exc).__name__}
    i = 0
    while True:
        try:
            nom = winreg.EnumKey(racine, i)
        except OSError:
            break
        i += 1
        try:
            svc = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SYSTEM\CurrentControlSet\Services\%s" % nom)
            image = str(winreg.QueryValueEx(svc, "ImagePath")[0])
        except OSError:
            continue
        if "nssm" not in image.lower():
            continue
        flux: dict = {}
        for cle in ("AppStdout", "AppStderr"):
            try:
                par = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Services\%s\Parameters" % nom)
                chemin = str(winreg.QueryValueEx(par, cle)[0])
            except OSError:
                chemin = ""
            flux[cle] = _flux_nssm(chemin)
        res[nom] = flux
    compte: dict = {}
    for flux in res.values():
        for f in flux.values():
            compte[f["etat"]] = compte.get(f["etat"], 0) + 1
    return {"services": res, "compte": compte}


def _services_full() -> list:
    """TOUS les services écosystème via SCM psutil : nom OU binpath nssm (rien hors radar)."""
    import psutil
    svcs = []
    try:
        it = list(psutil.win_service_iter())
    except Exception as e:  # noqa: BLE001
        return [{"scm_err": str(e)[:80]}] + _services_sc_fallback()
    for s in it:
        try:
            d = s.as_dict()
            binpath = (d.get("binpath") or "").lower()
            name = d.get("name") or "?"
            if "nssm" not in binpath and not any(h in name.lower() for h in _SVC_HINT):
                continue
            e = {"service": name, "start_type": str(d.get("start_type") or "?").upper(),
                 "state": str(d.get("status") or "?").upper(), "pid": d.get("pid")}
            if "nssm" in binpath:
                app, par = _nssm_params(name)
                if app:
                    e["app"] = app
                    e["app_params"] = par
            svcs.append(e)
        except Exception:
            continue
    return svcs


def _services_sc_fallback() -> list:
    """Fallback sc.exe (v1) si SCM psutil refusé."""
    svcs = []
    try:
        r = subprocess.run(["sc", "query", "state=", "all"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        names = [ln.split(":", 1)[1].strip() for ln in (r.stdout or "").splitlines()
                 if ln.strip().startswith("SERVICE_NAME") and any(h in ln.lower() for h in _SVC_HINT)]
        for n in names:
            try:
                qc = subprocess.run(["sc", "qc", n], capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=10).stdout or ""
                st = subprocess.run(["sc", "query", n], capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=10).stdout or ""
                start = next((l.split(":", 1)[1].strip() for l in qc.splitlines() if "START_TYPE" in l), "?")
                state = next((l.split(":", 1)[1].strip() for l in st.splitlines() if "STATE" in l), "?")
                svcs.append({"service": n, "start_type": start, "state": state})
            except Exception as e:  # noqa: BLE001
                svcs.append({"service": n, "err": str(e)[:60]})
    except Exception as e:  # noqa: BLE001
        svcs.append({"sc_err": str(e)[:80]})
    return svcs


def _aux() -> dict:
    """Fournitures ANNEXES (auto-start propre hors NSSM : Docker login, LM Studio, ollama)."""
    res = {k: [] for k in _AUX}
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name", "memory_info", "create_time"]):
            try:
                nm = (p.info["name"] or "").lower()
                for k, names in _AUX.items():
                    if any(nm == n or n in nm for n in names):
                        res[k].append({"name": p.info["name"], "pid": p.info["pid"],
                                       "rss_GB": round((p.info["memory_info"].rss or 0) / 1e9, 2),
                                       "age_s": round(time.time() - p.info["create_time"])})
                        break
            except Exception:
                continue
    except Exception as e:  # noqa: BLE001
        res["err"] = str(e)[:80]
    return {k: v for k, v in res.items() if v}


def _toml_expected() -> dict:
    """Attendu superviseur : services.toml — combien d'enabled au boot."""
    f = ROOT / "proxy_deno" / "core" / "services.toml"
    try:
        import tomllib
        data = tomllib.loads(f.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"err": str(e)[:80]}
    ent: list[dict] = []

    def walk(v):
        if isinstance(v, list):
            for it in v:
                if isinstance(it, dict) and ("name" in it or "cmd" in it):
                    ent.append(it)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)

    walk(data)
    en = [str(e.get("name", "?")) for e in ent if not e.get("disabled")]
    return {"total": len(ent), "enabled_n": len(en), "disabled_n": len(ent) - len(en), "enabled": en}


def snapshot(label: str) -> dict:
    procs, orph, dups = _procs_full()
    snap = {"ts": time.time(), "label": label, "procs": procs, "orphelins": orph,
            "doublons": dups, "ports": _ports_listen({r["pid"] for r in procs}),
            "services": _services_full(), "aux": _aux(), "toml": _toml_expected()}
    fname = f"snap_{label}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    # fallbacks si logs/ refusé (sandbox) : sandbox/ écrivable par les agents, puis C:/tmp
    for base in (SNAP_DIR, ROOT / "sandbox" / "proc_tracker", Path("C:/tmp/nokido_proc_tracker")):
        try:
            base.mkdir(parents=True, exist_ok=True)
            fp = base / fname
            fp.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
            snap["_file"] = str(fp)
            break
        except OSError:
            continue
    return snap


def _summary(snap: dict) -> dict:
    run = [s for s in snap["services"] if "RUN" in str(s.get("state", "")).upper()]
    auto = [s["service"] for s in snap["services"] if "AUTO" in str(s.get("start_type", "")).upper()]
    svc_err = [s[k] for s in snap["services"] for k in ("scm_err", "sc_err") if k in s]
    return {
        **({"services_err (lancer en session user pour le SCM)": svc_err} if svc_err else {}),
        "label": snap.get("label"),
        "procs": len(snap["procs"]),
        "ORPHELINS (parent mort = lanceur fantome)": [
            f"{r['name']}({r['pid']}) <- {r['parent']} :: {r['sig']}" for r in snap["orphelins"]],
        "DOUBLONS (script x N)": snap["doublons"],
        "services_running": [
            f"{s['service']}[{s.get('start_type', '?')}]"
            + (f" pid={s['pid']}" if s.get("pid") else "")
            + (f" -> {Path(str(s.get('app_params') or s.get('app'))).name}" if s.get("app") else "")
            for s in run],
        "AUTO_START_fautifs (sc config <svc> start= demand)": auto,
        "ports": snap["ports"],
        "annexes_RAM_GB": {k: round(sum(p.get("rss_GB", 0) for p in v), 2)
                           for k, v in snap["aux"].items() if isinstance(v, list)},
        "toml_enabled_n": snap.get("toml", {}).get("enabled_n"),
        "snapshot": snap.get("_file"),
    }


def _resolve(spec: str) -> Path:
    p = Path(spec)
    if p.exists():
        return p
    hits = sorted([*SNAP_DIR.glob(f"snap_{spec}_*.json"),
                   *(ROOT / "sandbox" / "proc_tracker").glob(f"snap_{spec}_*.json"),
                   *Path("C:/tmp/nokido_proc_tracker").glob(f"snap_{spec}_*.json")],
                  key=lambda x: x.name)
    if not hits:
        raise SystemExit(f"aucun snapshot '{spec}' dans {SNAP_DIR}")
    return hits[-1]


def diff(a_spec: str, b_spec: str) -> dict:
    a = json.loads(_resolve(a_spec).read_text(encoding="utf-8"))
    b = json.loads(_resolve(b_spec).read_text(encoding="utf-8"))
    ka = {(r["pid"], r["ctime"]): r for r in a["procs"]}
    kb = {(r["pid"], r["ctime"]): r for r in b["procs"]}

    def fmt(r):
        return f"{r['sig']} pid={r['pid']} user={r['user']} age={r['age_s']}s <- {r['parent']}"

    return {
        "a": a.get("label"), "b": b.get("label"),
        "SURVIVANTS (si b=post-stop, ce sont les FUITES)": [fmt(kb[k]) for k in kb if k in ka],
        "MORTS (presents a, absents b)": [fmt(ka[k]) for k in ka if k not in kb],
        "NOUVEAUX (apparus dans b)": [fmt(kb[k]) for k in kb if k not in ka],
        "orphelins_b": [fmt(r) for r in b.get("orphelins", [])],
        "doublons_b": b.get("doublons", {}),
        "ports_b": b.get("ports", {}),
    }


def main(argv: list) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if "--diff" in argv:
        i = argv.index("--diff")
        print(json.dumps(diff(argv[i + 1], argv[i + 2]), ensure_ascii=False, indent=2))
        return 0
    label = argv[argv.index("--snap") + 1] if "--snap" in argv and argv.index("--snap") + 1 < len(argv) else "boot"
    snap = snapshot(label)
    summ = _summary(snap)
    LOG.parent.mkdir(exist_ok=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": snap["ts"], "resume": summ}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    print(json.dumps(summ, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
