"""forge_job_runner.py — backend partagé des jobs détachés longue-durée.

POURQUOI un module (et pas juste les endpoints REST `/admin/run_job`) :
la logique de lancement vivait dans une *closure* request-bound de
`tools/nokido_hub.py::admin_run_job` — non appelable depuis le registre MCP
(`forge_mcp_registry.handle_run`). On l'extrait ici pour la partager entre le
verbe MCP `run.run_job` / `run.job_status` ET l'endpoint REST. Aucune nouvelle
primitive : réutilise `forge_sandbox_exec.spawn_as_sandbox_detached` (même
privilège que `run network:true`, AUCUNE escalade).

Un job = un script .py lancé DÉTACHÉ comme l'utilisateur sandbox. État 100 %
sur disque sous C:/tmp/nokido_jobs/{job_id}.{log,err,rc,json} → survit au
restart du hub et à la déconnexion du client. **Resumability** : il n'y a rien
à « reprendre » côté flux — on re-`read_job(job_id)` (l'état est sur disque),
ce qui est strictement plus robuste qu'un SSE `Last-Event-ID` (un blip réseau
ne perd rien). Découple durée-tâche de durée-connexion : le pattern « OS ».
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Owner 2026-07-28 : PLUS AUCUNE ecriture dans C:/tmp. Les logs de jobs vivent
# desormais SOUS LE REPO (sandbox/jobs), avec le cap de taille du wrapper en garde.
# L'incident du jour (3 logs de 70 Go dans C:/tmp/nokido_jobs -> disque plein) a
# montre que /tmp etait la zone d'explosion. Override possible par env si besoin.
JOBS_DIR = Path(os.environ.get(
    "LAFORGE_JOBS_DIR",
    str(Path(__file__).resolve().parent.parent / "sandbox" / "jobs")))


def _root() -> Path:
    # app/forge_job_runner.py -> racine repo = parent.parent
    return Path(__file__).resolve().parent.parent


def params_depuis_corps(body: dict) -> dict:
    """Traduit un corps de requete HTTP en arguments de `launch_job`.

    POURQUOI ICI, et pas dans le hub : la traduction appartient a l'organe qui
    LANCE, sinon chaque appelant relit le corps a sa facon et l'un d'eux oublie
    un champ. C'est exactement l'etat mesure le 2026-09-21 --
    `tools/nokido_hub.py::admin_run_job` lisait `script` et `online`, et
    IGNORAIT `lane` : l'anti-saturation ne pouvait donc pas s'appliquer, quoi
    que demande l'appelant.

    PURE et sans effet : testable sans demarrer le hub.
    """
    body = body or {}
    cap = body.get("rss_cap_mb")
    try:
        cap = int(cap) if cap else None
    except (TypeError, ValueError):
        cap = None
    return {
        "script": str(body.get("script", "")),
        "online": bool(body.get("online", False)),
        "lane": str(body.get("lane") or ""),
        "script_args": str(body.get("script_args") or ""),
        "rss_cap_mb": cap,
    }


def launch_job(script: str, online: bool = False, lane: str = "",
               rss_cap_mb: int | None = None, script_args: str = "") -> dict:
    """Lance `script` (.py) détaché. Retourne {ok, job_id, pid} ou {ok:False,error}.

    `script` doit être un .py existant sous C:/tmp ou la racine Nokido.
    `online=True` -> sandbox-online (réseau sortant), sinon offline.
    `script_args` : arguments CLI de la cible, chaîne style shell (parsée via
    shlex), symétrique de `trusted_script`. MANQUE MESURE 2026-08-20 : sans lui
    un `--once` était silencieusement perdu et un drain one-shot repartait en
    `daemon infini` — un job détaché qui ne peut PAS recevoir de mode ne peut
    pas non plus s'arrêter tout seul.
    """
    try:
        sp = Path(script).resolve()
    except Exception:
        return {"ok": False, "error": "bad script path"}
    root = _root()
    allowed = [Path("C:/tmp").resolve(), root.resolve()]
    if not any(str(sp) == str(a) or str(sp).startswith(str(a) + os.sep) for a in allowed):
        return {"ok": False, "error": "script must be under C:/tmp or Nokido root"}
    if not sp.is_file() or sp.suffix != ".py":
        return {"ok": False, "error": "script must be an existing .py file"}

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = "job_" + uuid.uuid4().hex[:12]
    # Signature d'appartenance (decision owner 2026-08-21) : chaque spawn porte
    # run_id + service_id et s'inscrit au registre superviseur (pid+start_time).
    try:
        from nokido_agent.app.forge_process_identity import get_hub_run_id, record as _pid_record
        _rid = get_hub_run_id()
    except Exception:  # muet-ok : l'identite ne bloque jamais un spawn
        _rid, _pid_record = "", None
    _svc = "job." + sp.stem
    log_f = JOBS_DIR / f"{job_id}.log"
    err_f = JOBS_DIR / f"{job_id}.err"
    rc_f = JOBS_DIR / f"{job_id}.rc"
    wrap_f = JOBS_DIR / f"{job_id}_wrap.py"
    rec_f = JOBS_DIR / f"{job_id}.json"
    py = sys.executable
    # Liste d'arguments : jamais de shell, donc pas d'injection possible ; shlex
    # respecte les guillemets pour les chemins à espaces (« Script python IA »).
    import shlex as _shlex

    try:
        _extra = _shlex.split(script_args or "")
    except ValueError as _e:
        return {"ok": False, "error": f"script_args illisible: {_e}"}
    # GARDE MEMOIRE (incident 2026-08-02) : le wrapper bornait la taille du LOG, mais
    # RIEN ne bornait la RAM. Un decoupeur en boucle a gonfle a 15 Go par URL, x12 ->
    # famine RAM, dwm.exe tue par l'iGPU (sa VRAM est prise dans la RAM), bureau fige,
    # redemarrage manuel de l'owner. Cap explicite > env LAFORGE_JOB_RSS_CAP_MB > 6000.
    _cap_mb = int(rss_cap_mb) if rss_cap_mb else int(
        os.environ.get("LAFORGE_JOB_RSS_CAP_MB", "6000")
    )
    # Wrapper : exécute la cible + GARDE DE TAILLE sur le log. Mesure 2026-07-28 :
    # trois jobs ont ecrit 70 Go CHACUN (« SSH_HOST obligatoire » en boucle infinie,
    # stdout capture sans limite) -> 211 Go, disque plein, hub mort. Un log de job
    # legitime ne depasse jamais quelques Mo ; au-dela de LOG_CAP c'est une boucle
    # folle qu'on TUE au lieu de la laisser remplir le disque.
    wrap_f.write_text(
        "import subprocess, threading, os, time\n"
        "LOG_CAP = int(os.environ.get('LAFORGE_JOB_LOG_CAP_MB', '200')) * 1024 * 1024\n"
        f"RSS_CAP = {_cap_mb} * 1024 * 1024\n"
        "try:\n"
        "    import psutil\n"
        "except Exception:\n"
        "    psutil = None\n"
        "_tue = False\n"
        f"_log = r'{log_f}'\n"
        f"_err = r'{err_f}'\n"
        f"_rc = r'{rc_f}'\n"
        # L'enfant herite de l'env : le script du job peut emettre sa progression
        # (forge_job_progress.emit) sous SON id, jointe ensuite par read_job.
        f"os.environ['LAFORGE_JOB_ID'] = '{job_id}'\n"
        f"os.environ['NOKIDO_HUB_RUN_ID'] = '{_rid}'\n"
        f"os.environ['NOKIDO_SERVICE_ID'] = '{_svc}'\n"
        f"_p = subprocess.Popen([r'{py}', r'{sp}'] + {_extra!r})\n"
        "def _dire(_m):\n"
        "    # Le .err est le stderr HERITE du hub : l'ouvrir par chemin peut rendre\n"
        "    # PermissionError (mesure 2026-09-05, job_18467ae0f9a1). Le garde mourait\n"
        "    # la-dessus AVANT d'ecrire le .rc : job tue mais 'running' a vie, lane\n"
        "    # jamais relachee, motif perdu. sys.stderr d'abord, le chemin ensuite,\n"
        "    # et JAMAIS d'exception : un journal qui echoue ne desarme pas un garde.\n"
        "    import sys as _s\n"
        "    for _f in (lambda: (_s.stderr.write(_m), _s.stderr.flush()),\n"
        "               lambda: open(_err, 'a', encoding='utf-8').write(_m)):\n"
        "        try:\n"
        "            _f()\n"
        "            return\n"
        "        except Exception:\n"
        "            pass\n"
        "def _tuer_enfants():\n"
        # `Popen.kill()` ne tue que LE process vise : sous Windows un petit-enfant
        # ne recoit rien. Mesure 2026-09-13 : le pytest du lot pur (8,6 Go) a
        # SURVECU au kill de son wrapper (50 Mo) -- rc 137 ecrit, job compte mort,
        # memoire jamais rendue, et le run suivant demarre sur une machine deja
        # chargee. Le garde bornait la memoire sur le papier : il tuait le petit et
        # laissait le gros. Meme doctrine que `forge_job_stop._arreter_arbre`, qui
        # porte deja cette regle pour l'arret manuel : enfants d'abord, parent
        # ensuite. Ne leve JAMAIS : un garde ne se desarme pas sur l'echec de son
        # propre nettoyage (meme raison que `_dire`).
        "    if psutil is None:\n"
        "        return\n"
        "    try:\n"
        "        _enfants = psutil.Process(_p.pid).children(recursive=True)\n"
        "    except Exception:\n"
        "        return\n"
        "    for _c in _enfants:\n"
        "        try:\n"
        "            _c.kill()\n"
        "        except Exception:\n"
        "            pass\n"
        "def _guard():\n"
        "    global _tue\n"
        "    _dit = False\n"
        "    while _p.poll() is None:\n"
        "        try:\n"
        "            if os.path.exists(_log) and os.path.getsize(_log) > LOG_CAP:\n"
        "                _tuer_enfants()\n"
        "                _p.kill()\n"
        "                _tue = True\n"
        "                open(_rc, 'w').write('137')\n"
        "                _dire("
        "'\\n[job_runner] TUE : log > %d Mo (boucle probable)\\n' % (LOG_CAP // 1048576))\n"
        "                return\n"
        "        except Exception:\n"
        "            pass\n"
        "        if psutil is None:\n"
        "            if not _dit:\n"
        "                _dit = True\n"
        "                _dire("
        "'[job_runner] GARDE RSS INACTIF : psutil absent, ce job n est PAS borne en memoire\\n')\n"
        "        else:\n"
        "            try:\n"
        "                _pr = psutil.Process(_p.pid)\n"
        "                _rss = _pr.memory_info().rss\n"
        "                for _c in _pr.children(recursive=True):\n"
        "                    try:\n"
        "                        _rss += _c.memory_info().rss\n"
        "                    except Exception:\n"
        "                        pass\n"
        "                if _rss > RSS_CAP:\n"
        "                    _tuer_enfants()\n"
        "                    _p.kill()\n"
        "                    _tue = True\n"
        "                    open(_rc, 'w').write('137')\n"
        "                    _dire("
        "'\\n[job_runner] TUE : RSS %d Mo > cap %d Mo (fuite memoire)\\n'"
        " % (_rss // 1048576, RSS_CAP // 1048576))\n"
        "                    return\n"
        "            except psutil.NoSuchProcess:\n"
        "                pass\n"
        "            except Exception as _e:\n"
        "                if not _dit:\n"
        "                    _dit = True\n"
        "                    _dire("
        "'[job_runner] GARDE RSS EN DEFAUT (%s) : memoire NON bornee\\n' % type(_e).__name__)\n"
        "        time.sleep(2)\n"
        "threading.Thread(target=_guard, daemon=True).start()\n"
        "rc = _p.wait()\n"
        # Le garde a deja ecrit 137 + le motif dans le .err : ne PAS l'ecraser par le
        # code de sortie du process tue (mesure 2026-08-02 : 1 sous Windows), sinon un
        # kill de regulation devient indistinguable d'une erreur applicative.
        "if not _tue:\n"
        "    open(_rc, 'w').write(str(rc))\n",
        encoding="utf-8",
    )
    try:
        sys.path.insert(0, str(root))
        from nokido_agent.app.forge_sandbox_exec import spawn_as_sandbox_detached

        res = spawn_as_sandbox_detached(
            f'"{py}" "{wrap_f}"', str(log_f), str(err_f), online=online
        )
    except Exception as e:
        return {"ok": False, "error": f"spawn failed: {str(e)[:200]}"}

    if _pid_record and res.get("pid"):
        _pid_record(res["pid"], _svc, extra={"job_id": job_id})
    rec = {
        "job_id": job_id,
        "hub_run_id": _rid,
        "script": str(sp),
        "online": online,
        "lane": lane or "",
        "rss_cap_mb": _cap_mb,
        "pid": res.get("pid"),
        "log": str(log_f),
        "rc_file": str(rc_f),
        "started": datetime.now().isoformat(),
        "status": "running",
    }
    rec_f.write_text(json.dumps(rec), encoding="utf-8")
    return {"ok": True, "job_id": job_id, "pid": res.get("pid")}


def read_job(job_id: str, tail: int = 4000) -> dict:
    """État d'un job : {ok, status(running|done), rc, pid, log_tail, started}.

    Idempotent, lit l'état disque -> sert de mécanisme de reprise (poll).
    """
    if not job_id or "/" in job_id or "\\" in job_id:
        return {"ok": False, "error": "bad job_id"}
    rec_f = JOBS_DIR / f"{job_id}.json"
    if not rec_f.exists():
        return {"ok": False, "error": "unknown job_id"}
    try:
        rec = json.loads(rec_f.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "error": "corrupt job record"}
    rc_f = Path(rec.get("rc_file", ""))
    log_f = Path(rec.get("log", ""))
    rc = None
    status = rec.get("status", "running")
    if rc_f.exists():
        status = "done"
        try:
            rc = int(rc_f.read_text(encoding="utf-8").strip())
        except Exception:
            rc = -1
        # PERSISTER la reconciliation. Mesure 2026-08-02 : le statut n'etait corrige
        # qu'en MEMOIRE, donc la fiche gardait `running` a vie — 51 fiches en cours
        # alors que leur `.rc` etait deja sur le disque. Tout ce qui balaye le dossier
        # (inventaires, audits) lisait un registre faux, et seul qui appelait read_job
        # voyait juste.
        if rec.get("status") == "running":
            rec["status"] = "done"
            rec["rc"] = rc
            try:
                rec_f.write_text(json.dumps(rec), encoding="utf-8")
            except OSError:  # muet-ok: lire un statut ne doit pas echouer sur une ecriture
                pass
    if rec.get("status") == "killed":
        status = "killed"
    # Un `running` sans rc_file dont le PID n'existe plus est un MENSONGE de
    # fiche (mesure 2026-08-21 : job tue par le restart du hub -> fiche
    # `running` a vie, lecteur induit en erreur). On le dit : `dead`.
    if status == "running":
        try:
            import psutil  # noqa: PLC0415
            if rec.get("pid") and not psutil.pid_exists(int(rec["pid"])):
                status = "dead"
        except Exception:  # muet-ok: enrichissement best-effort, jamais bloquant
            pass
    out = ""
    if log_f.exists():
        try:
            out = log_f.read_text(encoding="utf-8", errors="replace")[-tail:]
        except Exception:
            out = ""
    # Jointure PROGRESSION (forge_job_progress) : la barre vit dans un etat
    # partage dedie ; la joindre ici donne la MEME verite a tous les clients
    # (Claude/Gemini/Codex/Web) sans canal ni polling supplementaire.
    progress = None
    try:
        import sys as _s
        _tools = str(Path(__file__).resolve().parent.parent / "tools")
        if _tools not in _s.path:
            _s.path.insert(0, _tools)
        from nokido_agent.tools.forge_job_progress import read as _jp_read  # noqa: PLC0415
        progress = _jp_read(job_id)
    except Exception:  # muet-ok: enrichissement best-effort, jamais bloquant
        pass
    return {
        "ok": True,
        "job_id": job_id,
        "status": status,
        "rc": rc,
        "pid": rec.get("pid"),
        "started": rec.get("started"),
        "log_tail": out,
        "progress": progress,
    }


def reconcile_jobs(apply: bool = False) -> dict:
    """Reconcilie les fiches de job avec le REEL. Ne supprime JAMAIS une fiche.

    Mesure 2026-08-02 : 51 fiches annoncaient `running`, la plupart avec leur `.rc`
    deja sur le disque — `read_job` corrigeait en memoire sans reecrire, et rien ne
    balayait le dossier.

    Trois etats, jamais deux : `done` (rc present), `dead` (pas de rc et le process
    n'est plus la), `indetermine` (on n'a PAS PU regarder — psutil absent, fiche
    illisible, process opaque). Un pid qui « existe » ne prouve rien : apres un
    redemarrage il est RECYCLE, donc on compare la naissance du process a la date de
    la fiche. Un job `dead` rend aussi sa lane, sinon le bail reste orphelin 2 h.
    """
    try:
        import psutil
    except Exception:
        psutil = None
    out: dict = {"vus": 0, "done": 0, "dead": 0, "vivants": 0, "indetermine": 0,
                 "psutil_dispo": psutil is not None, "applique": apply, "details": []}
    for rec_f in sorted(JOBS_DIR.glob("*.json")):
        out["vus"] += 1
        try:
            rec = json.loads(rec_f.read_text(encoding="utf-8"))
        except Exception:
            out["indetermine"] += 1
            out["details"].append({"fiche": rec_f.name, "verdict": "indetermine",
                                   "raison": "fiche illisible"})
            continue
        if rec.get("status") != "running":
            continue
        job_id = rec.get("job_id") or rec_f.stem
        rc_f = Path(rec.get("rc_file") or str(JOBS_DIR / f"{job_id}.rc"))
        if rc_f.exists():
            try:
                rec["rc"] = int(rc_f.read_text(encoding="utf-8").strip())
            except Exception:
                rec["rc"] = -1
            verdict, raison = "done", "rc=%s sur disque" % rec["rc"]
        elif psutil is None:
            out["indetermine"] += 1
            out["details"].append({"fiche": rec_f.name, "verdict": "indetermine",
                                   "raison": "psutil absent : vitalite non observable"})
            continue
        else:
            pid = rec.get("pid")
            vivant = "indetermine"
            try:
                if pid:
                    proc = psutil.Process(int(pid))
                    ref = None
                    try:
                        if rec.get("started"):
                            ref = datetime.fromisoformat(rec["started"]).timestamp()
                    except Exception:
                        ref = None
                    if ref is None:
                        ref = rec_f.stat().st_mtime
                    # ne APRES la fiche = pid RECYCLE par l'OS, ce n'est pas notre job
                    vivant = proc.create_time() <= ref + 60
                else:
                    vivant = False
            except psutil.NoSuchProcess:
                vivant = False
            except Exception as e:
                out["details"].append({"fiche": rec_f.name, "verdict": "indetermine",
                                       "raison": "process opaque (%s)" % type(e).__name__})
                out["indetermine"] += 1
                continue
            if vivant is True:
                out["vivants"] += 1
                continue
            verdict, raison = "dead", "aucun rc, et le process n'est plus la (ou pid recycle)"
        rec["status"] = verdict
        rec["reconcilie_le"] = datetime.now().isoformat()
        rec["reconcilie_raison"] = raison
        out[verdict] += 1
        detail = {"fiche": rec_f.name, "verdict": verdict, "raison": raison}
        out["details"].append(detail)
        if apply:
            try:
                rec_f.write_text(json.dumps(rec), encoding="utf-8")
            except OSError as e:
                detail["ECRITURE_REFUSEE"] = type(e).__name__
                continue
            if verdict == "dead" and rec.get("lane"):
                try:
                    app_dir = str(_root() / "app")
                    if app_dir not in sys.path:
                        sys.path.insert(0, app_dir)
                    from nokido_agent.app.forge_lane_admission import release

                    release(rec["lane"], job_id)
                    detail["lane_liberee"] = rec["lane"]
                except Exception as e:
                    detail["lane_release_error"] = type(e).__name__
    return out


def kill_job(job_id: str, force: bool = False) -> dict:
    """Arrete un job detache DEPUIS LE HUB — son ancetre, seul compte qui le
    peut (AccessDenied mesure sous 4 formes cote clients, blocker SSoT).

    Reutilise tools/forge_job_stop.stop_job (gardes d'identification, arbre
    enfants PUIS wrapper), puis repare les deux mensonges connus post-kill :
    - fiche status=killed + rc 137 -> read_job cesse de dire 'running' ;
    - lane d'admission liberee -> pas de bail orphelin (TTL 2 h sinon).
    """
    if not job_id or "/" in job_id or "\\" in job_id:
        return {"ok": False, "error": "bad job_id"}
    tools_dir = str(_root() / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        from nokido_agent.tools.forge_job_stop import stop_job
    except Exception as e:
        return {"ok": False, "error": f"import forge_job_stop: {str(e)[:160]}"}
    res = stop_job(job_id, kill=True, force=force)
    rec_f = JOBS_DIR / f"{job_id}.json"
    rec: dict = {}
    try:
        if rec_f.exists():
            rec = json.loads(rec_f.read_text(encoding="utf-8"))
    except Exception:
        rec = {}
    if res.get("ok"):
        rc_f = Path(rec.get("rc_file") or str(JOBS_DIR / f"{job_id}.rc"))
        try:
            if not rc_f.exists():
                rc_f.write_text("137", encoding="utf-8")
        except Exception as e:
            res["rc_write_error"] = str(e)[:120]
        if rec:
            rec["status"] = "killed"
            rec["killed_at"] = datetime.now().isoformat()
            try:
                rec_f.write_text(json.dumps(rec), encoding="utf-8")
            except Exception as e:
                res["record_write_error"] = str(e)[:120]
        lane = rec.get("lane") or ""
        if lane:
            try:
                from nokido_agent.app.forge_lane_admission import release

                release(lane, job_id)
                res["lane_released"] = lane
            except Exception as e:
                res["lane_release_error"] = str(e)[:120]
    return res
