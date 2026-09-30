# -*- coding: utf-8 -*-
"""Allumer / eteindre A LA DEMANDE les cerveaux souverains locaux.

POURQUOI CET OUTIL (mesure 2026-07-26)
--------------------------------------
Le cerveau codeur a ete demarre par l'owner (`:8091 UP via /health`) et le
homeostat l'a EVINCE moins d'une minute plus tard --
`llamacpp_native_stop(~5.29GB)`. Allumer ne suffit donc pas : il faut aussi que
le corps SACHE qu'on le veut, sinon la regulation reprend aussitot ce qu'on
vient de poser. C'est la meme asymetrie que celle relevee le meme jour sur
`llamacpp_native_start` (script PowerShell invalide : le corps savait eteindre
sans pouvoir rallumer).

Le mecanisme d'intention existe deja pour Docker (`sandbox/docker.wanted`, TTL,
lu par `forge_resource_manager.get_active_intents`). On le REUTILISE tel quel
plutot que d'en inventer un second : `up` pose le drapeau puis lance, `down`
retire le drapeau puis arrete. Un drapeau sans arret laisserait une intention
mensongere ; un arret sans retrait du drapeau bloquerait la regulation.

CHEMINS D'EXECUTION -- pourquoi cet outil doit tourner cote OWNER
------------------------------------------------------------------
Les deux binaires vivent dans le profil owner (`services.toml [vars]`) :
  LLAMA   = %USERPROFILE%/llama-vulkan/llama-server.exe
  LMS_EXE = %USERPROFILE%/.lmstudio/bin/lms.exe
Mesure du 2026-07-26, trois comptes, trois echecs distincts :
  - bac a sable : ne VOIT pas le profil owner -> `exists=False` trompeur ;
  - compte privilegie : trouve le binaire, charge les backends, puis le serveur
    meurt a l'instant ou l'appel MCP est coupe (2 fois, meme point, Vulkan ET
    CPU) ;
  - superviseur : `disabled = true` sur NokidoLlamaNative (garde deliberе du
    2026-06-02, `--mlock` immobilisait 7 Go au boot) -> son start sort aussitot
    tout en publiant `running` sur un pid mort.
D'ou l'exposition par TACHES PLANIFIEES `Nokido-*` : `schtasks Nokido-*` est un
passthrough autorise, donc n'importe quel agent peut declencher l'action sans
qu'aucun compte de service n'ait besoin d'atteindre le profil owner.

Usage :
  LAFORGE_PYTHON tools/forge_llm_ondemand.py up   llama|lmstudio|all
  LAFORGE_PYTHON tools/forge_llm_ondemand.py down llama|lmstudio|all
  LAFORGE_PYTHON tools/forge_llm_ondemand.py status
"""
import json
import os
import subprocess
import sys
import time
import tomllib
import urllib.error
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
SANDBOX = ROOT / "sandbox"
TOML = ROOT / "proxy_deno" / "core" / "services.toml"

# TTL aligne sur celui de docker.wanted (900 s) : une intention qui ne PERIME
# jamais n'est plus une intention, c'est un blocage permanent de la regulation.
WANTED_TTL_S = 900.0

# Journal hors depot : ecrit par le compte owner via la tache planifiee, et
# lisible par les comptes de service (C:/tmp est le terrain commun).
JOURNAL = r"C:/tmp/llm_ondemand.log"

CIBLES = {
    "llama": {
        "drapeau": SANDBOX / "llama.wanted",
        "sonde": "http://127.0.0.1:8091/health",
        "port": 8091,
        "libelle": "cerveau codeur (llama-server :8091)",
    },
    "lmstudio": {
        "drapeau": SANDBOX / "lmstudio.wanted",
        "sonde": "http://127.0.0.1:1234/v1/models",
        "port": 1234,
        "libelle": "LM Studio (:1234)",
    },
}


def _vars() -> dict:
    return (tomllib.loads(TOML.read_text(encoding="utf-8")).get("vars") or {})


def _sert(url: str, timeout: float = 3.0) -> bool:
    """Le service REPOND-il ? -- pas « me laisse-t-il entrer ».

    Mesure 2026-07-26 : LM Studio ecoutait bel et bien sur :1234 et rendait
    401. `urlopen` LEVE sur 401, donc un `except Exception` generique comptait
    un serveur vivant mais protege comme « ne sert pas » -- et l'appelant
    retirait l'intention, puis rallumait en boucle un service deja debout.
    Un refus d'authentification PROUVE qu'un serveur est la ; seule une absence
    de reponse prouve le contraire. Meme regle que forge_ensure_service._serving
    (« 401/403/404 = serveur up (auth/route), pas down »).
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return getattr(r, "status", 200) < 500
    except urllib.error.HTTPError as he:
        return he.code < 500
    except Exception:  # noqa: BLE001  (refus de connexion / timeout = pas la)
        return False


def _attendre(url: str, secondes: float) -> bool:
    """Laisse au service le temps de SERVIR avant de conclure.

    Sans cette attente, `up` sondait dans la seconde qui suit le lancement et
    concluait a l'echec pendant que le demon demarrait -- puis retirait
    l'intention, donc la regulation reprenait aussitot ce qu'on venait de poser.
    Un faux negatif ici ne coute pas un message : il coute l'action elle-meme.
    """
    fin = time.time() + secondes
    while time.time() < fin:
        if _sert(url):
            return True
        time.sleep(3)
    return _sert(url)


def _poser_drapeau(cible: str) -> None:
    """L'intention est posee AVANT le lancement : si la regulation passe pendant
    le chargement du modele (60-120 s), elle doit deja voir qu'on le veut."""
    p = CIBLES[cible]["drapeau"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ts": time.time(), "by": "forge_llm_ondemand"}), encoding="utf-8")
    # CONSTATER l'emission. C'est CETTE ligne que l'analyse statique ne savait pas
    # trouver : l'ecriture passe par `CIBLES[cible]["drapeau"]`, donc un grep sur
    # « llama.wanted » rendait 14 lectures et ZERO ecriture -- verdict faux, paye le
    # 2026-07-30. Un emetteur se constate a l'execution, il ne s'infere pas du code.
    try:
        import sys as _s
        _s.path.insert(0, str(SANDBOX.parent / "app"))
        from nokido_agent.app.forge_signal_coupling import emit_signal
        emit_signal(p.name, emitter="forge_llm_ondemand._poser_drapeau")
    except Exception:
        pass  # muet-ok : l'observabilite ne casse jamais la pose d'intention


def poser_intention(cible: str = "llama") -> str:
    """Primitive PUBLIQUE : declarer que le corps VEUT ce cerveau souverain.

    Elle existe parce que six chemins savent REVEILLER :8091 et qu'un seul savait
    le DECLARER (mesure 2026-07-30 : `forge_wake_llama_native`, `forge_backend_power`,
    `forge_local_pool_wake`, `forge_llama_keeper` et `forge_demand_proxy` allumaient
    sans poser le drapeau). Consequence chiffree : 73 arrets de llama-server:8091 en
    7,6 jours et 312,94 Go recharges, parce que la garde d'intention du reclaimer
    (`forge_resource_manager` step 2b) ne lisait jamais autre chose que False. Le
    garde etait juste ; c'est la declaration qui manquait.

    Un reveilleur appelle DONC ceci, il ne recopie pas l'ecriture du drapeau : un
    second mecanisme d'intention donnerait deux verites, ce que ce module refuse
    explicitement depuis sa creation. Le TTL de 900 s reste le garde-fou de sens
    inverse -- une intention qu'on ne renouvelle pas PERIME, et le reclaimer
    retrouve son droit d'evincer. Sans TTL, declarer reviendrait a immobiliser
    5 Go pour toujours.
    """
    if cible not in CIBLES:
        raise KeyError("cible d'intention inconnue: %r (connues: %s)"
                       % (cible, ", ".join(sorted(CIBLES))))
    _poser_drapeau(cible)
    return str(CIBLES[cible]["drapeau"])


def _retirer_drapeau(cible: str) -> None:
    try:
        CIBLES[cible]["drapeau"].unlink(missing_ok=True)
    except OSError:
        pass  # muet-ok : un drapeau deja absent est l'etat voulu, rien a signaler


def _tuer_par_wmi(pid: int) -> bool:
    """Arret par le meme service que la creation. Rend True si le pid a disparu."""
    ps = ("$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%d' -ErrorAction SilentlyContinue; "
          "if ($p) { (Invoke-CimMethod -InputObject $p -MethodName Terminate).ReturnValue } "
          "else { 'absent' }" % int(pid))
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, errors="replace", timeout=60)
    except Exception:  # noqa: BLE001
        return False
    time.sleep(2)
    try:
        import psutil
        return not psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001
        return False


def _pids_du_port(port: int) -> list:
    """Qui ECOUTE ce port, mesure -- on ne devine pas le proprietaire."""
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return []
    out = []
    for c in psutil.net_connections(kind="inet"):
        if c.status == "LISTEN" and c.laddr and c.laddr.port == port and c.pid:
            out.append(int(c.pid))
    return sorted(set(out))


# ── llama-server ──────────────────────────────────────────────────────────────

def llama_up(profil: str = "--lite", fg: bool = False) -> dict:
    if _sert(CIBLES["llama"]["sonde"]):
        _poser_drapeau("llama")
        return {"cible": "llama", "action": "up", "ok": True, "detail": "deja actif"}
    _poser_drapeau("llama")
    # REUTILISATION : l'outil du depot construit l'argv depuis services.toml,
    # applique le profil allege et fait le healthcheck. Rien n'est reecrit ici.
    #
    # fg=True : le lanceur NE REND PAS la main. Sous une tache planifiee c'est
    # le seul mode qui tient -- le Job Object refuse la sortie (WinError 5), donc
    # des que l'action se termine le serveur est tue avec elle. L'intention est
    # posee AVANT de bloquer, sinon personne ne saurait qu'on le veut pendant le
    # chargement du modele.
    outil = ROOT / "tools" / "forge_wake_llama_native.py"
    argv = [sys.executable, str(outil), profil] + (["--fg"] if fg else [])
    r = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                       timeout=None if fg else 300)
    # Laisser le serveur finir de servir avant de conclure : mesure 2026-07-26,
    # une sonde immediate rendait False pendant le warmup et RETIRAIT l'intention
    # au moment precis ou elle etait le plus utile (le keeper faisait sa ronde).
    ok = _attendre(CIBLES["llama"]["sonde"], 30)
    if not ok:
        _retirer_drapeau("llama")  # intention mensongere sinon
    return {"cible": "llama", "action": "up", "ok": ok, "rc": r.returncode,
            "detail": (r.stdout or "")[-300:]}


def llama_down() -> dict:
    _retirer_drapeau("llama")   # d'abord l'intention, sinon un keeper le relance
    # CHEMIN PRINCIPAL : terminer la TACHE qui porte le serveur. Elle le tient
    # dans son Job Object ; fermer le job emporte le serveur, sans avoir a
    # posseder le processus. C'est la symetrie exacte de l'allumage, et le seul
    # chemin qui ne bute pas sur un AccessDenied (mesure 2026-07-26 : ni
    # psutil.terminate ni Win32_Process.Terminate n'y arrivaient).
    try:
        subprocess.run(["schtasks", "/End", "/TN", "Nokido-Llama-Up"],
                       capture_output=True, text=True, errors="replace", timeout=60)
        time.sleep(3)
    except Exception:  # noqa: BLE001
        pass
    if not _sert(CIBLES["llama"]["sonde"]):
        return {"cible": "llama", "action": "down", "ok": True,
                "detail": "tache Nokido-Llama-Up terminee, job ferme"}
    pids = _pids_du_port(CIBLES["llama"]["port"])
    if not pids:
        return {"cible": "llama", "action": "down", "ok": True, "detail": "deja eteint"}
    try:
        import psutil
    except Exception as exc:  # noqa: BLE001
        return {"cible": "llama", "action": "down", "ok": False, "detail": "psutil absent: %s" % exc}
    arretes, echecs = [], []
    for pid in pids:
        try:
            p = psutil.Process(pid)
            p.terminate()
            p.wait(timeout=15)
            arretes.append(pid)
            continue
        except Exception as exc:  # noqa: BLE001
            premier = type(exc).__name__
        # SYMETRIE : le serveur est CREE par WMI (seul moyen de sortir du Job
        # Object du planificateur), il n'appartient donc pas au processus qui
        # tente de l'arreter -- d'ou le AccessDenied mesure le 2026-07-26. On
        # l'arrete par le meme chemin qui l'a cree. Qui cree par WMI tue par WMI.
        if _tuer_par_wmi(pid):
            arretes.append(pid)
        else:
            echecs.append("%s(%s)" % (pid, premier))
    if echecs:
        return {"cible": "llama", "action": "down", "ok": False,
                "detail": "refus: %s | arretes: %s" % (", ".join(echecs), arretes)}
    return {"cible": "llama", "action": "down", "ok": True, "detail": "arretes: %s" % arretes}


# ── LM Studio ─────────────────────────────────────────────────────────────────

def _lms(*argv: str) -> dict:
    """Lance `lms <argv>` et rend sa sortie. Aucune supposition sur le succes :
    c'est la sonde du port qui tranche, pas le code retour."""
    v = _vars()
    exe, wd = v.get("LMS_EXE"), v.get("LMS_DIR")
    if not exe:
        return {"ok": False, "detail": "LMS_EXE non declare dans services.toml"}
    try:
        r = subprocess.run([exe, *argv], cwd=wd, capture_output=True,
                           text=True, errors="replace", timeout=180)
    except OSError as exc:
        return {"ok": False, "detail": "lancement refuse par l'OS: %s" % exc}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "detail": ((r.stdout or "") + (r.stderr or "")).strip()[-220:]}


def _lms_cmd(sous_commande: str) -> dict:
    v = _vars()
    exe, wd = v.get("LMS_EXE"), v.get("LMS_DIR")
    if not exe:
        return {"ok": False, "detail": "LMS_EXE non declare dans services.toml"}
    # NE PAS confondre « absent » et « je ne peux pas voir ». Mesure 2026-07-26 :
    # `Path(exe).exists()` a rendu False depuis le compte privilegie sur un
    # fichier qui EXISTE (verifie cote owner) -- le profil owner lui est ferme.
    # Un garde base sur cette lecture transformait une ACL en « binaire absent »
    # et abandonnait avant d'essayer. On tente donc l'execution, et c'est
    # l'erreur systeme REELLE qui fait foi. Meme tolerance que
    # forge_wake_llama_native._exists (« exists peut lever WinError5 hors
    # contexte user »).
    try:
        _vu = Path(exe).exists()
    except OSError as _e:
        _vu = "illisible(WinError %s)" % getattr(_e, "winerror", "?")
    try:
        r = subprocess.run([exe, "daemon", sous_commande], cwd=wd, capture_output=True,
                           text=True, errors="replace", timeout=180)
    except OSError as exc:
        return {"ok": False, "vu": _vu,
                "detail": "lancement refuse par l'OS: %s (%s)" % (exc, exe)}
    return {"ok": r.returncode == 0, "rc": r.returncode, "vu": _vu,
            "detail": ((r.stdout or "") + (r.stderr or ""))[-300:]}


def lmstudio_up() -> dict:
    if _sert(CIBLES["lmstudio"]["sonde"]):
        _poser_drapeau("lmstudio")
        return {"cible": "lmstudio", "action": "up", "ok": True, "detail": "deja actif"}
    _poser_drapeau("lmstudio")
    # DEUX etages, et c'est TOUT le piege. `lms daemon up` demarre le DEMON ;
    # il n'ouvre PAS le point d'acces compatible OpenAI. Mesure 2026-07-26 :
    # le demon tournait (PID 16448, confirme cote owner) pendant que :1234
    # restait ferme -- un service declare « demarre » qui ne sert rien.
    # `services.toml` ne declare que l'etage demon, d'ou le limbo `starting`
    # sans fin cote superviseur. Le serveur se lance separement.
    etapes = {"daemon": _lms("daemon", "up")}
    etapes["server"] = _lms("server", "start", "--port",
                            str(CIBLES["lmstudio"]["port"]))
    sert = _attendre(CIBLES["lmstudio"]["sonde"], 60)
    if not sert:
        _retirer_drapeau("lmstudio")
    return {"cible": "lmstudio", "action": "up", "ok": bool(sert), "etapes": etapes}


def lmstudio_down() -> dict:
    _retirer_drapeau("lmstudio")
    # On coupe le SERVEUR (ce qui consomme la RAM et sert le port) et on laisse
    # le demon : c'est lui qui permettra de rallumer sans relancer l'appli.
    # Couper les deux rendrait le prochain `up` plus lent sans rien liberer de
    # plus -- le demon seul ne charge aucun modele.
    etapes = {"server": _lms("server", "stop")}
    eteint = not _sert(CIBLES["lmstudio"]["sonde"])
    return {"cible": "lmstudio", "action": "down", "ok": eteint, "etapes": etapes}


# ── etat ──────────────────────────────────────────────────────────────────────

def status() -> dict:
    out = {}
    for nom, spec in CIBLES.items():
        drapeau = spec["drapeau"]
        age = None
        if drapeau.exists():
            age = round(time.time() - drapeau.stat().st_mtime, 1)
        out[nom] = {
            "libelle": spec["libelle"],
            "sert": _sert(spec["sonde"]),
            "pids_du_port": _pids_du_port(spec["port"]),
            "voulu": bool(age is not None and age < WANTED_TTL_S),
            "drapeau_age_s": age,
        }
    return out


ACTIONS = {
    ("up", "llama"): llama_up, ("down", "llama"): llama_down,
    ("up", "lmstudio"): lmstudio_up, ("down", "lmstudio"): lmstudio_down,
}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    profil = "--cpu" if "--cpu" in sys.argv else "--lite"
    fg = "--fg" in sys.argv
    if not args or args[0] == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=1))
        return 0
    action = args[0]
    cible = args[1] if len(args) > 1 else "all"
    if action not in ("up", "down"):
        print("usage: up|down llama|lmstudio|all  |  status")
        return 1
    cibles = ["llama", "lmstudio"] if cible == "all" else [cible]
    resultats = []
    for c in cibles:
        fn = ACTIONS.get((action, c))
        if not fn:
            resultats.append({"cible": c, "ok": False, "detail": "cible inconnue"})
            continue
        try:
            resultats.append(fn(profil, fg) if (action, c) == ("up", "llama") else fn())
        except Exception as exc:  # noqa: BLE001
            resultats.append({"cible": c, "action": action, "ok": False,
                              "detail": "%s: %s" % (type(exc).__name__, str(exc)[:160])})
    sortie = json.dumps(resultats, ensure_ascii=False, indent=1)
    print(sortie)
    # TRACE : lance par une tache planifiee, ce script n'a AUCUNE sortie lisible
    # -- la console appartient au planificateur. Mesure 2026-07-26 : deux
    # declenchements de Nokido-LMStudio-Up sans demon au bout, et pas une ligne
    # pour dire pourquoi. Un levier dont on ne peut pas lire l'echec est aveugle.
    try:
        with open(JOURNAL, "a", encoding="utf-8", errors="replace") as fh:
            fh.write("%s  %s %s\n%s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"),
                                          action, cible, sortie))
    except OSError:
        pass
    return 0 if all(r.get("ok") for r in resultats) else 4


if __name__ == "__main__":
    raise SystemExit(main())
