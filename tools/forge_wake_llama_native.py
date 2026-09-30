"""Reveil RUNTIME de NokidoLlamaNative (:8091) sans toucher disabled=true.

Lit services.toml, resout ${VAR}, lance llama-server detache, healthcheck :8091.
Le service reste disabled au boot (non-regression du fix RAM 2026-06-02) ; le
LlamaKeeper le liberera si RAM>=FREE_AT.

Usage : LAFORGE_PYTHON tools/forge_wake_llama_native.py [--dry] [--lite] [--cpu]

--- HISTORIQUE (2026-07-17) : POURQUOI CE FICHIER VIT ICI ---
Il vivait dans C:\\tmp\\wake_llama_native.py. Le renommage LaForge->Nokido du
2026-07-08 a balaye le DEPOT ; C:\\tmp n'est pas le depot, donc le lookup
`name == "LaForgeLlamaNative"` y est reste perime alors que services.toml
declarait desormais "NokidoLlamaNative". Consequence mesuree : sys.exit(2)
-> forge_llama_keeper._start_local() tombait en Chemin 2 (fallback pip
llama-cpp-python = un python.exe/uvicorn) -> invisible a _llama_pids() qui
filtrait sur le NOM d'executable -> coder_n=0 -> la regle free_at=80 ne se
declenchait JAMAIS -> ~5 GB jamais rendus a RAM 78-95%, 3 respawns en 28 min.
Un organe du boot ne doit pas dependre d'un scratch que rien ne balaie :
tracke ici, il suit les renommages. Cf blackboard active_bugs
CLAUDE_ram_churn_boot_2026-07-17.
"""
import os
import re
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
TOML = ROOT / "proxy_deno" / "core" / "services.toml"
LOG = Path(r"C:/tmp/llama_native_8091.log")
SERVICE = os.environ.get("LAFORGE_LLAMA_NATIVE_SERVICE", "NokidoLlamaNative")
DRY = "--dry" in sys.argv
LITE = "--lite" in sys.argv      # profil iGPU 780M : pas de draft, offload partiel
CPU = "--cpu" in sys.argv        # ultra-sur : 0 GPU, tout CPU (lent mais aucun crash Vulkan)
# --fg : ne rend PAS la main, on attend le serveur. Seul mode viable sous une
# tache planifiee : son Job Object REFUSE la sortie (BREAKAWAY -> WinError 5,
# mesure 2026-07-26), donc tout enfant meurt a la fin de l'action. En restant
# vivant, le lanceur garde le job ouvert et le serveur avec lui ; l'extinction
# devient `schtasks /End`, qui est justement un passthrough autorise.
FG = "--fg" in sys.argv


def make_lite(argv):
    """Allege argv : retire le draft model (gourmand), reduit ctx + slots, offload
    GPU partiel. --cpu : offload 0 (pur CPU, zero risque Vulkan).

    2026-07-17 : retire AUSSI --mlock. Le profil LITE est le chemin ON-DEMAND, et
    --mlock VERROUILLE ~7 GB non swappables -- exactement ce que le `disabled = true`
    de services.toml interdit depuis le 2026-06-02 ("mlock 7.1GB immobilisait la RAM
    au boot (85% -> tout job lourd OOM le hub)"). Charger en LITE *avec* mlock aurait
    re-introduit le defaut que ce meme profil est cense eviter. Le profil FULL
    (sans --lite) garde --mlock : la, c'est un choix explicite.
    """
    drop_flags = {"-md", "-ngld", "--draft-max", "--draft-min", "--draft-p-min", "-cd"}
    drop_bare = {"--mlock"}
    out, skip = [], False
    for tok in argv:
        if skip:
            skip = False
            continue
        if tok in drop_flags:
            skip = True  # saute aussi sa valeur
            continue
        if tok in drop_bare:
            continue     # flag sans valeur
        out.append(tok)

    def set_opt(flag, val):
        if flag in out:
            out[out.index(flag) + 1] = val
        else:
            out.extend([flag, val])

    set_opt("-c", "16384")
    set_opt("-np", "2")
    set_opt("-ngl", "0" if CPU else "20")
    return out


def resolve(val, vars_):
    def sub(m):
        k = m.group(1)
        if k == "ROOT":
            return str(ROOT)
        return vars_.get(k) or os.environ.get(k) or m.group(0)
    if isinstance(val, str):
        return re.sub(r"\$\{(\w+)\}", sub, val)
    if isinstance(val, list):
        return [resolve(v, vars_) for v in val]
    return val


def _creer_hors_job(argv, cwd, log_path):
    """Cree le processus via WMI -> il n'herite PAS du Job Object appelant.

    Rend le pid, ou None si le chemin echoue (on rebascule alors sur le repli).
    La redirection passe par `cmd /c` : Win32_Process.Create ne sait pas rediriger.
    """
    inner = " ".join(f'"{a}"' if (" " in str(a) or not str(a)) else str(a) for a in argv)
    cmdline = f'cmd.exe /c "{inner} > "{log_path}" 2>&1"'
    ps = (
        "$cl = '" + cmdline.replace("'", "''") + "'; "
        "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
        "-Arguments @{CommandLine=$cl; CurrentDirectory='" + str(cwd).replace("'", "''") + "'}; "
        "Write-Output \"$($r.ReturnValue) $($r.ProcessId)\""
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, text=True, errors="replace", timeout=60)
    except Exception as exc:  # noqa: BLE001
        print(f"[wake] WMI indisponible: {type(exc).__name__}: {exc}", flush=True)
        return None
    sortie = (r.stdout or "").strip().split()
    if len(sortie) == 2 and sortie[0] == "0":
        return int(sortie[1])
    print(f"[wake] WMI ReturnValue={sortie or (r.stderr or '').strip()[:120]}", flush=True)
    return None


def health(timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for path in ("/health", "/v1/models", "/props"):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:8091{path}", timeout=3) as r:
                    if r.status == 200:
                        return True, path
            except Exception:
                pass
        time.sleep(2)
    return False, None


def main():
    data = tomllib.loads(TOML.read_text(encoding="utf-8"))
    vars_ = data.get("vars", {})
    svc = next((s for s in data.get("service", []) if s.get("name") == SERVICE), None)
    if not svc:
        # Ne PAS se contenter de "absent" : lister ce qui existe. Un nom perime apres
        # renommage est muet autrement (30 jours de fallback silencieux, 2026-07-17).
        known = [s.get("name") for s in data.get("service", []) if "Llama" in (s.get("name") or "")]
        print(f"[wake] {SERVICE} absent du registre -- services Llama connus: {known}")
        sys.exit(2)

    cmd = resolve(svc["cmd"], vars_)
    args = resolve(svc.get("args", []), vars_)
    cwd = resolve(svc.get("cwd", str(ROOT)), vars_)
    argv = [cmd] + args
    if LITE or CPU:
        argv = [cmd] + make_lite(args)
        print(f"[wake] PROFIL {'CPU (ngl=0)' if CPU else 'LITE (ngl=20, no draft, no mlock)'}")

    # sanity chemins (exists peut lever WinError5 hors contexte user -> tolerant)
    def _exists(p):
        try:
            return Path(p).exists()
        except OSError as e:
            return f"?({e.winerror})"
    print(f"[wake] LLAMA bin: {cmd} | exists={_exists(cmd)}")
    mi = argv.index("-m") if "-m" in argv else -1
    if mi > -1:
        print(f"[wake] MODEL: {argv[mi + 1]} | exists={_exists(argv[mi + 1])}")
    print(f"[wake] argv ({len(argv)} tokens), cwd={cwd}")

    # DECLARER avant de reveiller. Le commentaire du mode --fg affirmait deja que le
    # keeper etait « tenu par l'intention llama.wanted » -- sauf que personne ne la
    # POSAIT : mesure 2026-07-30, 73 arrets de llama-server:8091 en 7,6 jours et
    # 312,94 Go recharges, la garde d'intention du reclaimer lisant toujours False.
    # On declare AVANT le healthcheck, et donc AUSSI quand le serveur est deja debout :
    # un reveil demande sur un serveur vivant est une demande comme une autre, et sans
    # drapeau la regulation l'evince dans la minute qui suit. DRY est exclu -- une
    # simulation qui declare une intention est une intention mensongere.
    if not DRY:
        try:
            sys.path.insert(0, str(ROOT))
            from nokido_agent.tools.forge_llm_ondemand import poser_intention
            print("[wake] intention posee : %s" % poser_intention("llama"), flush=True)
        except Exception as exc:  # noqa: BLE001
            # On NE recopie PAS l'ecriture du drapeau ici : deux ecrivains = deux
            # verites. On crie, et le reveil continue en sachant qu'il est evincable.
            print("[wake] ATTENTION intention NON posee (%s: %s) -- le serveur sera "
                  "evincable par la regulation" % (type(exc).__name__, exc), flush=True)

    # deja up ?
    ok, p = health(2)
    if ok:
        print(f"[wake] :8091 DEJA actif ({p}) -- rien a faire")
        return
    if DRY:
        print("[wake] DRY -- pas de lancement")
        print("  " + " ".join(f'"{a}"' if " " in a else a for a in argv))
        return

    if _exists(cmd) is False:
        print("[wake] ABORT -- binaire llama-server introuvable")
        sys.exit(3)

    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    BREAKAWAY = 0x01000000              # CREATE_BREAKAWAY_FROM_JOB
    logf = open(LOG, "w", encoding="utf-8", errors="replace")
    # DETACHED_PROCESS ne fait PAS sortir d'un Job Object : seul BREAKAWAY le
    # fait. Mesure 2026-07-26 : lance depuis une tache planifiee, le serveur a
    # servi (`:8091 UP`) puis est mort a la SECONDE ou la tache s'est terminee --
    # le planificateur ferme son job et tue toute la descendance. Le journal
    # s'arretait sur « all slots are idle », sans arret propre, et le journal de
    # cycle de vie ne portait AUCUN stop : ce n'etait pas une eviction. Le meme
    # lancement en console owner survivait, faute de job.
    # Repli : si le job interdit la sortie (JOB_OBJECT_LIMIT_BREAKAWAY_OK
    # absent), Windows refuse la creation -- on relance alors sans le drapeau
    # plutot que d'echouer, ce qui rend le comportement historique.
    proc = None
    if FG:
        # EN MODE --fg ON VEUT RESTER DANS LE JOB, et c'est un choix, pas un pis-aller.
        # Sortir du job (BREAKAWAY, puis WMI) faisait bien survivre le serveur, mais
        # plus personne ne pouvait l'ARRETER : cree par le service WMI, il n'appartient
        # ni au lanceur ni a la tache, et les deux chemins d'arret ont rendu
        # AccessDenied (mesure 2026-07-26, pid 17580). Dans le job, l'extinction est
        # GRATUITE et symetrique : `schtasks /End` ferme le job et emporte le serveur.
        # Ce qui tuait le serveur dans le job n'etait pas le job -- c'etait le keeper,
        # desormais tenu par l'intention llama.wanted.
        print("[wake] mode --fg : serveur gardé DANS le job "
              "(arret = schtasks /End sur la tache)", flush=True)
        proc = subprocess.Popen(
            argv, cwd=cwd, stdout=logf, stderr=subprocess.STDOUT,
            creationflags=DETACHED, close_fds=True,
        )
        print(f"[wake] llama-server lance pid={proc.pid}, log={LOG}", flush=True)
    try:
        if proc is None:
            proc = subprocess.Popen(
                argv, cwd=cwd, stdout=logf, stderr=subprocess.STDOUT,
                creationflags=DETACHED | BREAKAWAY, close_fds=True,
            )
    except OSError as _e:
        # Le job du planificateur REFUSE la sortie (WinError 5, mesure 26-07).
        # Porte de sortie : faire creer le processus par le service WMI. Le
        # nouveau processus appartient a WmiPrvSE, PAS a notre job -- il survit
        # donc a la fin de la tache. C'est la meme intention que BREAKAWAY, par
        # un chemin que le job ne controle pas.
        print(f"[wake] BREAKAWAY refuse ({_e}) -- creation hors job via WMI", flush=True)
        _pid = _creer_hors_job(argv, cwd, str(LOG))
        if _pid:
            print(f"[wake] llama-server cree hors job pid={_pid}, log={LOG}", flush=True)
        else:
            print("[wake] WMI a echoue -- repli dans le job "
                  "(le serveur mourra avec son lanceur)", flush=True)
            proc = subprocess.Popen(
                argv, cwd=cwd, stdout=logf, stderr=subprocess.STDOUT,
                creationflags=DETACHED, close_fds=True,
            )
    print(f"[wake] llama-server lance detache pid={proc.pid}, log={LOG}")
    print("[wake] warmup...")
    ok, p = health(120)
    print(f"[wake] :8091 {'UP via ' + p if ok else 'PAS pret apres 120s -- voir log'}", flush=True)
    if ok and FG and proc is not None:
        # Attente utile SEULEMENT si le serveur est reste dans notre job : hors
        # job (WMI), il n'a plus besoin de nous et bloquer ne ferait qu'immobiliser
        # la tache -- on rend donc la main tout de suite dans ce cas.
        print("[wake] mode --fg : le lanceur reste vivant pour garder le job ouvert "
              "(arret = schtasks /End, ou l'extinction a la demande)", flush=True)
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        print("[wake] llama-server termine", flush=True)
    elif ok and FG:
        print("[wake] serveur hors job : pas d'attente necessaire", flush=True)
    sys.exit(0 if ok else 4)


if __name__ == "__main__":
    main()
