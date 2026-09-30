"""
nokido_launcher.py — Lanceur bureau Nokido
=============================================
Double-cliquer sur le raccourci bureau pour obtenir
un panneau de contrôle rapide en console Windows.

Fonctions :
  [1] Start full-stack (nokido_start.ps1) + Tray
  [2] Stop full-stack (nokido_stop.ps1)
  [3] Restart full-stack (stop -> start)
  [4] Ouvrir Network Monitor (navigateur)
  [5] Ouvrir Audit Log (navigateur)
  [6] Status rapide (hub + mode + agents)
  [Q] Quitter

Style : terminal dark, couleurs ANSI, ASCII art Nokido
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import webbrowser
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
HUB_URL = "http://127.0.0.1:8766"

# ── Mode CLI (owner 2026-09-06 : « il devra etre appelable depuis n'importe quel CLI ») ──
# `python tools/nokido_launcher.py --action status` : aucune pause, aucune saisie, un code
# de retour. Les actions du menu appellent `input()` en fin de course ; en mode CLI ce
# remplacant de module rend "" au lieu de bloquer (ou de lever EOFError sans console).
INTERACTIF = True
_input_builtin = input


def input(prompt: str = "") -> str:  # noqa: A001 - ombrage VOULU du builtin
    return _input_builtin(prompt) if INTERACTIF else ""


def _compte_de_service() -> bool:
    """Vrai sous un compte sans bureau interactif (comptes hub, SYSTEM, runner)."""
    u = (os.environ.get("USERNAME") or "").lower()
    return u.startswith(("laforgesbx", "laforgetrusted")) or u in ("system", "systeme") or u.endswith("$")

# ─── Couleurs ANSI ────────────────────────────────────────────────────────────
R = "\033[0m"  # reset
B = "\033[1m"  # bold
DIM = "\033[2m"  # dim
GR = "\033[38;5;84m"  # vert Nokido
OR = "\033[38;5;214m"  # orange CHEF
RE = "\033[38;5;196m"  # rouge DOWN
YE = "\033[38;5;220m"  # jaune WARN
CY = "\033[38;5;117m"  # cyan HUB
MA = "\033[38;5;183m"  # mauve GEMINI
WH = "\033[38;5;255m"  # blanc

LOGO = f"""{GR}{B}
  ███╗   ██╗ ██████╗ ██╗  ██╗██╗██████╗  ██████╗
  ████╗  ██║██╔═══██╗██║ ██╔╝██║██╔══██╗██╔═══██╗
  ██╔██╗ ██║██║   ██║█████╔╝ ██║██║  ██║██║   ██║
  ██║╚██╗██║██║   ██║██╔═██╗ ██║██║  ██║██║   ██║
  ██║ ╚████║╚██████╔╝██║  ██╗██║██████╔╝╚██████╔╝
  ╚═╝  ╚═══╝ ╚═════╝ ╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝{R}
{DIM}  Sovereign Multi-Agent Hub — Control Panel{R}
"""


def _clear():
    os.system("cls" if os.name == "nt" else "clear")


def _hub_status() -> dict:
    try:
        resp = urllib.request.urlopen(f"{HUB_URL}/health", timeout=1.0)
        return {"up": True, **json.loads(resp.read())}
    except Exception:
        return {"up": False, "version": "?"}


def _hub_token() -> str:
    """Jeton du hub, lu dans le coffre — jamais en dur, jamais affiche."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret("FORGE_MCP_TOKEN") or ""
    except Exception as exc:
        print(f"  {DIM}(coffre illisible : {exc}){R}")
        return ""


def _supervisor_token() -> str:
    """Jeton du superviseur :8765, lu dans le coffre ; repli sur celui du hub (meme
    ordre que nokido_stop.ps1). Jamais en dur, jamais affiche."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret("LAFORGE_SUPERVISOR_TOKEN") or get_secret("FORGE_MCP_TOKEN") or ""
    except Exception as exc:
        print(f"  {DIM}(coffre illisible : {exc}){R}")
        return ""


def _parse_mode(text: str) -> dict:
    """Lit la reponse de `get_mode`, qui n'est PAS du JSON.

    Le hub rend du texte (« mode=AUTO  agent=CLAUDE » puis une ligne par agent),
    et un refus de droits voyage dans un `result` JSON-RPC parfaitement VALIDE
    (« GATE_DENIED: ring 4 <= requis 2 »). L'ancienne version faisait un
    `json.loads()` aveugle : elle affichait « ? » aussi bien pour un hub muet
    que pour un refus, ce qui a masque le vrai probleme longtemps.
    """
    if not text:
        return {"mode": "?"}
    if text.startswith("GATE_DENIED"):
        return {"mode": "refusé", "why": text}
    try:
        return json.loads(text)
    except ValueError:  # muet-ok : le format texte est le cas NORMAL, JSON = tolerance
        pass
    out: dict = {"mode": "?", "agents": {}}
    m = re.search(r"mode=(\S+)", text)
    if m:
        out["mode"] = m.group(1)
    for line in text.splitlines()[1:]:
        agent, sep, status = line.partition(":")
        if sep and agent.strip():
            out["agents"][agent.strip()] = status.strip()
    return out


def _hub_mode() -> dict:
    try:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_mode", "arguments": {}},
            }
        ).encode()
        req = urllib.request.Request(
            f"{HUB_URL}/mcp",
            data=body,
            headers={
                "Content-Type": "application/json",
                # Le lanceur du bureau, c'est l'OWNER, avec le jeton MAITRE : il le DIT
                # (contrat AUTH-2 du 24/09 — le maitre ne prend pas un nom d'organe ;
                # « LAUNCHER » n'etait meme pas une identite du registre).
                "X-Agent-Name": "MASTER",
                "Authorization": f"Bearer {_hub_token()}",
            },
            method="POST",
        )
        result = json.loads(urllib.request.urlopen(req, timeout=4).read())
        text = result.get("result", {}).get("content", [{}])[0].get("text", "")
    except Exception as exc:
        return {"mode": "?", "why": str(exc)}
    return _parse_mode(text)


def _service_action(action: str) -> bool:
    """Lance une action sc.exe en mode admin via powershell runas."""
    cmd = f"Start-Process powershell -Verb RunAs -ArgumentList '-Command {action} NokidoMCP' -Wait"
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True, timeout=15
    )
    return r.returncode == 0


def _set_mode(mode: str) -> bool:
    try:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "set_mode", "arguments": {"mode": mode, "reason": "launcher"}},
            }
        ).encode()
        req = urllib.request.Request(
            f"{HUB_URL}/mcp",
            data=body,
            # 2026-09-24 : cet appel MUTANT (set_mode) partait SANS AUCUN jeton, avec
            # un simple en-tete -- une identite DECLAREE, jamais prouvee (AUTH-1/AUTH-4).
            headers={"Content-Type": "application/json", "X-Agent-Name": "MASTER",
                     "Authorization": f"Bearer {_hub_token()}"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=4)
        return True
    except Exception:
        return False


def _header():
    print(LOGO)
    hs = _hub_status()
    up = hs.get("up", False)
    v = hs.get("version", "?")

    hub_line = f"{GR}● HUB UP  v{v}{R}" if up else f"{RE}● HUB DOWN{R}"
    print(f"  {hub_line}   {DIM}{HUB_URL}{R}")

    if up:
        md = _hub_mode()
        mode = md.get("mode", "?")
        agents = md.get("agents", {})
        mc = OR if mode == "CHEF" else (GR if mode == "AUTO" else CY)
        if md.get("why"):
            mc = YE
        print(f"  Mode : {mc}{B}{mode}{R}", end="")
        if md.get("why"):
            print(f"  {DIM}({md['why'][:60]}){R}", end="")
        if agents:
            ag_str = "  ".join(
                f"{MA}{ag}{R}:{DIM}{(v.get('status', '?') if isinstance(v, dict) else v)[:6]}{R}"
                for ag, v in list(agents.items())[:4]
            )
            print(f"   Agents : {ag_str}", end="")
        print()

    print(f"\n  {DIM}{'─' * 62}{R}\n")


def _menu():
    entries = [
        ("1", GR, "Start  full-stack (nokido_start.ps1) + Tray"),
        ("2", RE, "Stop   full-stack (nokido_stop.ps1)"),
        ("3", OR, "Restart full-stack (stop -> start)"),
        ("H", OR, "Restart HUB seul (:8766) — sans toucher au reste"),
        ("─", DIM, ""),
        ("4", CY, "Ouvrir Network Monitor  [navigateur]"),
        ("5", CY, "Ouvrir Audit Log        [navigateur]"),
        ("─", DIM, ""),
        ("6", WH, "Status rapide"),
        ("─", DIM, ""),
        ("Q", RE, "Quitter"),
    ]
    for key, col, label in entries:
        if key == "─":
            print(f"  {DIM}{'─' * 40}{R}")
        else:
            print(f"  {col}{B}[{key}]{R}  {label}")
    print()


SUPERVISOR_URL = "http://127.0.0.1:8765"
# Services llmPool ou Llama lourds — reveil a la demande, pas au boot.
_WAKE_SKIP = {
    "NokidoLlamaNative",
    "NokidoLlamaRouter",
    "NokidoLMStudio",
    "NokidoLlamaPython",
    "NokidoLlamaEmbed",
    "NokidoLlamaReranker",
}


def _supervisor_status() -> dict:
    try:
        with urllib.request.urlopen(f"{SUPERVISOR_URL}/supervisor/status", timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def _wake(name: str) -> bool:
    try:
        req = urllib.request.Request(
            f"{SUPERVISOR_URL}/supervisor/wake/{name}", data=b"", method="POST"
        )
        urllib.request.urlopen(req, timeout=8).read()
        return True
    except Exception:
        return False


def _wake_daemons():
    """Reveille tous les services 'sleeping' non-llmPool. Silencieux par defaut."""
    st = _supervisor_status()
    services = st.get("services", {})
    targets = [
        n for n, s in services.items() if s.get("status") == "sleeping" and n not in _WAKE_SKIP
    ]
    if not targets:
        return
    woke = sum(1 for n in targets if _wake(n))
    time.sleep(4)
    st2 = _supervisor_status().get("services", {})
    running = sum(1 for n in targets if st2.get(n, {}).get("status") == "running")
    fails = [n for n in targets if st2.get(n, {}).get("status") not in ("running", "starting")]
    print(f"  {GR}✓ Daemons réveillés : {running}/{woke}{R}")
    if fails:
        head = ", ".join(fails[:6]) + (" …" if len(fails) > 6 else "")
        print(f"  {YE}  ⚠ pas encore UP : {head}{R}")


PS_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def _run_stack_script(script_name: str, *extra_args: str) -> bool:
    """Lance un script de gestion stack (nokido_start.ps1 / nokido_stop.ps1)
    dans sa propre fenêtre PowerShell. Le ps1 s'auto-élève (RunAs -> UAC) et fait
    le VRAI boot/arrêt full-stack (Master Tier-0, flotte dynamique, reaping
    orphelins). Non-bloquant côté launcher. Source canonique start/stop."""
    script = ROOT / "tools" / script_name
    if not script.exists():
        print(f"  {RE}✗ script introuvable : {script}{R}")
        return False
    exe = PS_EXE if os.path.exists(PS_EXE) else "powershell.exe"
    subprocess.Popen(
        [exe, "-ExecutionPolicy", "Bypass", "-WindowStyle", "Normal", "-File", str(script),
         *extra_args]
    )
    return True


def _wait_hub(label: str, tries: int = 45, delay: float = 2.0) -> bool:
    for _ in range(tries):
        time.sleep(delay)
        hs = _hub_status()
        if hs.get("up"):
            print(f"  {GR}✓ Hub UP v{hs.get('version')} ({label}){R}")
            return True
    print(f"  {YE}  Hub pas encore UP — suivre la fenêtre {label}{R}")
    return False


def _pid_hub():
    """PID de NokidoMCP selon le superviseur ; None si illisible (superviseur en rebond)."""
    try:
        resp = urllib.request.urlopen(f"{SUPERVISOR_URL}/supervisor/status", timeout=2.0)
        return ((json.loads(resp.read()).get("services") or {}).get("NokidoMCP") or {}).get("pid")
    except Exception:  # muet-ok : None = « illisible », jamais « pas de hub »
        return None


def _attendre_rebond_hub(pid_avant, delai_max: float = 420.0, pas: float = 0.5) -> bool:
    """Rebond du hub = un pid NokidoMCP DIFFÉRENT de celui d'avant le restart, hub qui répond.

    Le hub reste debout pendant le stop (-GarderHub) : le voir « UP » après le start ne
    prouve pas qu'il a redémarré. Mesure au passage la durée sans hub vue d'ici, au pas
    de sondage près, face au budget de reconnexion de Claude Code (15 s)."""
    debut = time.monotonic()
    chute = None
    while time.monotonic() - debut < delai_max:
        if not _hub_status().get("up"):
            if chute is None:
                chute = time.monotonic()
        else:
            pid = _pid_hub()
            neuf = pid is not None and pid != pid_avant
            if not neuf:
                chute = None  # hub revenu SANS rebond (lenteur passagère) : la chute ne comptait pas
            elif pid_avant is not None or chute is not None:
                if chute is None:
                    print(f"  {GR}✓ Hub rebondi (pid {pid_avant} → {pid}), absence plus brève "
                          f"que le pas de sondage ({pas}s){R}")
                else:
                    trou = time.monotonic() - chute
                    couleur = GR if trou < 15 else YE
                    print(f"  {couleur}✓ Hub rebondi (pid {pid_avant} → {pid}) : ~{trou:.0f}s sans hub vu "
                          f"d'ici (Claude Code abandonne la reconnexion MCP après 15 s){R}")
                return True
        time.sleep(pas)
    print(f"  {YE}  Pas de rebond du hub en {delai_max:.0f}s — suivre la fenêtre start{R}")
    return False


def _tray_python() -> str:
    """Interpreteur capable de faire tourner le tray.

    `sys.executable` est celui qui lance CE launcher (raccourci bureau) : rien
    ne garantit qu'il porte pystray/pillow, et sans eux `nokido_tray` sort en
    `sys.exit(1)`. On prefere donc l'interpreteur documente du projet
    (miniforge, cf. LAFORGE_PYTHON), verifie present sur disque.
    """
    for cand in (
        os.environ.get("LAFORGE_PYTHON_BIN"),
        str(Path.home() / "miniforge3" / "python.exe"),
    ):
        if cand and os.path.exists(cand):
            return cand
    return sys.executable


def _start_tray():
    """Lance l'icone tray et VERIFIE qu'elle survit.

    L'ancienne version envoyait stdout/stderr dans DEVNULL puis annoncait
    « ✓ Tray lancé » sans rien verifier : un tray qui mourait aussitot — le
    Python courant n'ayant ni pystray ni pillow, `nokido_tray` sort en
    `sys.exit(1)` — laissait un message vert et AUCUNE trace. On journalise
    la sortie et on ne confirme que sur la survie reelle du process.
    """
    tray = ROOT / "tools" / "nokido_tray.py"
    if not tray.exists():
        print(f"  {YE}  ⚠ tray introuvable : {tray}{R}")
        return
    log_path = ROOT / "logs" / "tray.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    exe = _tray_python()
    with open(log_path, "a", encoding="utf-8", errors="replace") as log:
        log.write("\n=== %s lancement via %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), exe))
        log.flush()
        proc = subprocess.Popen(
            # DETACHED_PROCESS + nouveau groupe : sans cela le tray reste un
            # ENFANT de ce panneau et meurt avec lui — fermer la console
            # emportait l'icone. Il doit survivre au lanceur qui l'a ouvert.
            # --no-selfheal : la flotte vient d'etre demarree ; sans ce drapeau,
            # le tray croit :7400 mort (il monte apres le hub) et declenche un
            # stop+start, transformant le Start en Stop.
            # -u : sans lui, Python bufferise vers un fichier et le journal reste
            # vide au moment ou on en a besoin — c'est-a-dire quand le tray meurt.
            [exe, "-u", str(tray), "--no-selfheal"],
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
            ),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    time.sleep(2.0)
    if proc.poll() is None:
        print(f"  {GR}✓ Tray lancé (pid {proc.pid}){R}")
        return
    if proc.returncode == 3:
        # nokido_tray.TRAY_DEJA_ACTIF (instance unique, 2026-09-26) : un tray tourne deja --
        # cas d'un restart lance DEPUIS le tray, que le stop epargne. Ce n'est pas une mort.
        print(f"  {GR}✓ Tray déjà actif (instance unique){R}")
        return
    print(f"  {RE}✗ Tray mort aussitôt (code {proc.returncode}){R}")
    print(f"  {DIM}    python : {exe}{R}")
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
    except OSError as exc:
        tail = ["(log illisible : %s)" % exc]
    for line in tail:
        if line.strip():
            print(f"  {DIM}    {line}{R}")
    print(f"  {DIM}    log : {log_path}{R}")


def _action_start():
    print(f"\n  {GR}Démarrage Nokido — full-stack (nokido_start.ps1)...{R}")
    if not _run_stack_script("nokido_start.ps1"):
        input(f"\n  {DIM}[Entrée pour continuer]{R} ")
        return
    print(f"  {DIM}Boot dans une fenêtre dédiée (UAC) : Master Tier-0 → flotte.{R}")
    if _wait_hub("start"):
        _start_tray()
    input(f"\n  {DIM}[Entrée pour continuer]{R} ")


def _action_stop():
    print(f"\n  {RE}Arrêt Nokido — full-stack (nokido_stop.ps1)...{R}")
    _run_stack_script("nokido_stop.ps1")
    print(f"  {DIM}Arrêt dans une fenêtre dédiée (UAC) : flotte → MCP → Master + reaping.{R}")
    input(f"\n  {DIM}[Entrée pour continuer]{R} ")


def _action_restart():
    print(f"\n  {OR}Restart Nokido — flotte arrêtée hub debout, puis rebond du hub (~9 s)...{R}")
    was_up = _hub_status().get("up")
    pid_avant = _pid_hub()
    # -NoWait : en restart, la fenêtre du stop ne doit pas rester bloquée sur
    # « appuyer sur une touche » — personne ne la regarde, et le start suit.
    # -GarderHub / -RelanceHub (2026-09-26) : Claude Code abandonne la reconnexion MCP
    # après 15 s (5 essais). L'arrêt complet laissait le hub à terre ~4 min 20, d'où un
    # `/mcp` manuel. Le stop arrête désormais la flotte par l'API du superviseur en
    # gardant superviseur + hub ; le start redémarre LaForge-Master après ses preflights,
    # et le hub n'est absent que le temps de ce rebond.
    if not _run_stack_script("nokido_stop.ps1", "-NoWait", "-GarderHub"):
        input(f"\n  {DIM}[Entrée pour continuer]{R} ")
        return
    print(f"  {DIM}Stop lancé (UAC). Attente du SIGNAL de fin du stop...{R}")
    # Le stop coupe Ollama, Docker et les orphelins APRÈS la flotte (et, s'il n'a
    # pas pu garder le hub, après lui). Guetter un port faisait donc partir le
    # start au milieu du carnage — c'est pourquoi seul un stop-puis-start MANUEL
    # fonctionnait, l'humain fermant la fenêtre entre les deux. On attend le
    # signal que nokido_stop.ps1 écrit APRÈS son dernier kill.
    flag = ROOT / "sandbox" / "nokido_stop.done"
    try:
        flag.unlink()
    except FileNotFoundError:  # muet-ok : signal absent = cas NORMAL, pas une panne
        pass
    except OSError as exc:
        print(f"  {DIM}(signal non effaçable : {exc}){R}")
    done = False
    for _ in range(120):  # ~240s, le stop touche 26 services + Docker + Ollama
        time.sleep(2)
        if flag.exists():
            done = True
            break
    if done:
        print(f"  {GR}✓ Stop terminé (signal reçu) — lancement start...{R}")
    else:
        print(f"  {YE}  Pas de signal après 240s — start quand même "
              f"(la fenêtre du stop attend peut-être une touche){R}")
    _run_stack_script("nokido_start.ps1", "-RelanceHub")
    print(f"  {DIM}Start lancé (UAC) : preflights, puis rebond du hub.{R}")
    # Le restart relancait la stack mais JAMAIS le tray, contrairement au Start :
    # l'icone ne revenait pas et le restart semblait sans effet.
    # Le hub est GARDÉ pendant le stop : `_wait_hub` le verrait « UP » avant le rebond.
    if _attendre_rebond_hub(pid_avant):
        _start_tray()
    input(f"\n  {DIM}[Entrée pour continuer]{R} ")


def _action_mode():
    modes = ["AUTO", "CHEF", "CLINE", "DEBAT", "PING"]
    print(f"\n  {MA}Choisir le mode :{R}")
    for i, m in enumerate(modes, 1):
        col = OR if m == "CHEF" else (GR if m == "AUTO" else CY)
        print(f"    {col}[{i}]{R} {m}")
    print()
    choice = input(f"  {DIM}Numéro : {R}").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(modes):
        mode = modes[int(choice) - 1]
        ok = _set_mode(mode)
        col = GR if ok else RE
        print(f"  {col}{'✓' if ok else '✗'} Mode → {mode}{R}")
    else:
        print(f"  {RE}Annulé{R}")
    input(f"\n  {DIM}[Entrée pour continuer]{R} ")


def _action_restart_hub():
    """Redemarre le SEUL hub :8766, sans toucher au reste de la stack.

    Le menu n'offrait que du full-stack : 26 services, Docker et Ollama arretes,
    deux elevations UAC et jusqu'a 240 s d'attente d'un signal -- pour recharger
    un module Python. `_service_action` existait DEJA pour ce cas (ligne 136) et
    n'etait appelee NULLE PART : la capacite etait ecrite et debranchee, ce qui
    obligeait a passer par les raccourcis stop/start du bureau.

    Deux voies, la plus douce d'abord. Le SUPERVISEUR :8765 redemarre un service
    SANS elevation ; l'appel `sc.exe` via `-Verb RunAs` ne sert qu'en repli et
    demande l'UAC. On DIT laquelle a servi : un repli silencieux ferait passer
    une elevation pour une fatalite.
    """
    print(f"\n  {OR}Restart du hub seul (NokidoMCP :8766)...{R}")
    avant = _hub_status()
    # Le superviseur exige un jeton (401 mesure le 2026-09-26 sur un POST sans en-tete) :
    # sans lui ce geste echouait TOUJOURS, et le disait « superviseur muet ».
    jeton = _supervisor_token()
    entetes = {"Authorization": f"Bearer {jeton}"} if jeton else {}
    voie = None
    refus = None
    for etape in ("stop", "start"):
        try:
            req = urllib.request.Request(
                f"{SUPERVISOR_URL}/supervisor/service/{etape}/NokidoMCP",
                data=b"", method="POST", headers=entetes)
            urllib.request.urlopen(req, timeout=20)
            voie = "superviseur :8765 (sans UAC)"
        except urllib.error.HTTPError as exc:
            # Il a REPONDU : un refus n'est pas un silence.
            refus = (etape, exc.code)
            voie = None
            break
        except Exception as exc:
            print(f"  {DIM}superviseur indisponible sur '{etape}' ({type(exc).__name__}){R}")
            voie = None
            break
        time.sleep(2)

    if refus:
        etape, code = refus
        cause = "jeton refuse" if jeton else "aucun jeton lisible dans le coffre"
        print(f"  {RE}Superviseur :8765 a REFUSE '{etape}' (HTTP {code}) : {cause}.{R}")
        if etape == "start":
            print(f"  {RE}Le hub est ARRETE et n'a pas ete relance : 'Nokido - Restart stack'.{R}")
        input(f"\n  {DIM}[Entree pour continuer]{R} ")
        return

    if voie is None:
        # PAS de repli sur `Restart-Service NokidoMCP` (retire le 2026-09-06) : le
        # service NSSM NokidoMCP est arrete PAR DESIGN, le hub :8766 est un ENFANT du
        # superviseur. Le relancer par NSSM ouvrirait un second hub sur le meme port
        # (collision :8766, crash-loop documentee dans CLAUDE.md regle 10). Superviseur
        # muet = la stack est a relancer par le lanceur du Bureau, on le DIT.
        print(f"  {RE}Superviseur :8765 muet : le hub ne se relance pas seul. "
              f"Relancer la stack par 'Nokido - Restart stack' (Bureau owner).{R}")
        input(f"\n  {DIM}[Entree pour continuer]{R} ")
        return

    if _wait_hub("restart hub"):
        print(f"  {GR}Hub de retour via {voie}.{R}")
    else:
        # Le hub etait peut-etre deja a terre AVANT : le dire evite d'imputer
        # au restart une panne qui le precede.
        etat = "deja hors ligne avant l'operation" if not avant.get("up") else "toujours muet"
        print(f"  {RE}Hub {etat} apres restart via {voie}.{R}")
    input(f"\n  {DIM}[Entree pour continuer]{R} ")


def _action_status():
    print(f"\n  {CY}Status détaillé :{R}\n")
    hs = _hub_status()
    print(
        f"  Hub        : {GR if hs.get('up') else RE}{'UP' if hs.get('up') else 'DOWN'}{R}  v{hs.get('version', '?')}"
    )
    if hs.get("up"):
        md = _hub_mode()
        print(f"  Mode       : {OR if md.get('mode') == 'CHEF' else GR}{md.get('mode', '?')}{R}")
        agents = md.get("agents", {})
        for ag, info in agents.items():
            status = info.get("status", "?") if isinstance(info, dict) else str(info)
            last = info.get("last_task", "")[:40] if isinstance(info, dict) else ""
            print(f"  {MA}{ag:10}{R} : {status}  {DIM}{last}{R}")

    # Service Windows
    r = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "(Get-Service NokidoMCP -EA SilentlyContinue).Status",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    errors="replace")
    svc = r.stdout.strip() or "?"
    # Hub :8766 = spawné par le SUPERVISEUR (process enfant) ; le service NSSM
    # NokidoMCP reste Stopped PAR DESIGN (cf nokido_start.ps1). Pas d'alarme rouge.
    note = "  (normal — hub géré par superviseur)" if "Running" not in svc else ""
    print(f"  NSSM Svc   : {DIM}{svc}{note}{R}")
    sv = _supervisor_status()
    svcs = sv.get("services", {}) if isinstance(sv, dict) else {}
    if svcs:
        running = sum(1 for s in svcs.values() if s.get("status") == "running")
        print(f"  Superviseur: {GR}{running}/{len(svcs)} running{R}  {DIM}:8765{R}")
    print(f"  Endpoint   : {DIM}{HUB_URL}/mcp{R}")
    input(f"\n  {DIM}[Entrée pour continuer]{R} ")


# ---------------------------------------------------------------------------
# Tailscale (owner 2026-09-29 : « tailscale par le tray »). L'API locale de Tailscale Windows
# ne repond qu'a l'utilisateur de la session -- mesure : un compte de service recoit 401
# « Tailscale already in use by DESKTOP-...\user ». Ces actions tournent donc depuis le tray
# (session owner), sur ordre confirme (forge_ordres_bureau) ou depuis le panneau.
# ---------------------------------------------------------------------------
TAILSCALE_EXE = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
PORT_PAIRS = 8793                                   # NokidoPairMCP, seule cible du Funnel
ETAT_TAILSCALE = ROOT / "logs" / "tailscale_etat.json"


def _tailscale(*args) -> subprocess.CompletedProcess:
    return subprocess.run([str(TAILSCALE_EXE), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def _action_tailscale_statut() -> dict:
    """Lecture seule : etat du Funnel, ecrit dans logs/tailscale_etat.json (lisible par le hub)."""
    etat = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "rc": None, "funnel": None, "erreur": None}
    if not TAILSCALE_EXE.exists():
        etat["erreur"] = "tailscale.exe ABSENT : %s" % TAILSCALE_EXE
    else:
        r = _tailscale("funnel", "status", "--json")
        etat["rc"] = r.returncode
        if r.returncode == 0:
            try:
                etat["funnel"] = json.loads(r.stdout or "{}")
            except ValueError:
                etat["erreur"] = "sortie non JSON : %s" % (r.stdout or "")[:200]
        else:
            etat["erreur"] = (r.stderr or r.stdout or "")[:300]
    try:
        ETAT_TAILSCALE.parent.mkdir(parents=True, exist_ok=True)
        ETAT_TAILSCALE.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        etat["erreur"] = (etat["erreur"] or "") + " | etat NON ecrit (%s)" % type(exc).__name__
    print("[tailscale] %s" % ("ERREUR : " + etat["erreur"] if etat["erreur"]
                              else "Funnel : %s" % (json.dumps(etat["funnel"], ensure_ascii=False)[:400] or "vide")))
    return etat


def _action_funnel(ouvrir: bool) -> None:
    """Ouvre (--bg <port>) ou ferme (--https=443 off) le Funnel vers le connecteur des pairs,
    puis RELIT l'etat : une commande acceptee n'est pas un etat atteint."""
    if not TAILSCALE_EXE.exists():
        print("[tailscale] tailscale.exe ABSENT : %s -- rien fait" % TAILSCALE_EXE)
        return
    args = ("funnel", "--bg", str(PORT_PAIRS)) if ouvrir else ("funnel", "--https=443", "off")
    r = _tailscale(*args)
    print("[tailscale] %s -> rc=%s %s" % (" ".join(args), r.returncode, (r.stdout + r.stderr).strip()[:300]))
    _action_tailscale_statut()


# Actions exposees au mode CLI. start/stop/restart lancent les .ps1 du Bureau, qui
# s'AUTO-ELEVENT (UAC) : depuis un compte de service la fenetre UAC n'apparait jamais
# et l'action pend en silence -- donc REFUS dit, jamais un faux depart.
ACTIONS = {
    "status": lambda: _action_status(),
    "restart-hub": lambda: _action_restart_hub(),
    "wake": lambda: _wake_daemons(),
    "start": lambda: _action_start(),
    "stop": lambda: _action_stop(),
    "restart": lambda: _action_restart(),
    "tailscale-statut": lambda: _action_tailscale_statut(),
    "funnel-ouvrir": lambda: _action_funnel(True),
    "funnel-fermer": lambda: _action_funnel(False),
}
ACTIONS_BUREAU_SEULEMENT = ("start", "stop", "restart")


def _cli(action: str) -> int:
    """Mode non interactif : 0 fait, 2 action inconnue, 3 refuse (droits)."""
    global INTERACTIF
    INTERACTIF = False
    if action in ("list", "--list", "help"):
        print("actions : " + ", ".join(ACTIONS) + " (start/stop/restart = Bureau owner seulement)")
        return 0
    fn = ACTIONS.get(action)
    if fn is None:
        print(f"action inconnue : {action} ; connues : {', '.join(ACTIONS)}")
        return 2
    if action in ACTIONS_BUREAU_SEULEMENT and _compte_de_service():
        print(f"REFUS : '{action}' lance un script qui s'auto-eleve (UAC) ; depuis le compte "
              f"{os.environ.get('USERNAME', '?')} il n'y a pas de bureau pour repondre. "
              "Geste owner : raccourci 'Nokido START/STOP/Restart stack' du Bureau.")
        return 3
    fn()
    return 0


def _console_couleurs(titre: str):
    """Couleurs ANSI + titre de la console Windows. Aussi en mode `--action` : le tray
    ouvre une console pour le panneau (2026-09-26), qui sinon afficherait les codes bruts."""
    os.system("color")
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.windll.kernel32
        kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)
        ctypes.windll.kernel32.SetConsoleTitleW(titre)


def main():
    argv = sys.argv[1:]
    if "--action" in argv:
        i = argv.index("--action")
        action = argv[i + 1] if i + 1 < len(argv) else "list"
        if sys.stdout.isatty():
            _console_couleurs(f"Nokido Control Panel — {action}")
        return _cli(action)
    _console_couleurs("Nokido Control Panel")

    while True:
        _clear()
        _header()
        _menu()

        try:
            choice = input(f"  {WH}Choix → {R}").strip().upper()
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "1":
            _action_start()
        elif choice == "2":
            _action_stop()
        elif choice == "3":
            _action_restart()
        elif choice == "H":
            _action_restart_hub()
        elif choice == "4":
            webbrowser.open(f"{HUB_URL}/forge/network")
        elif choice == "5":
            webbrowser.open(f"{HUB_URL}/api/network/history?limit=100")
        elif choice == "6":
            _action_status()
        elif choice == "Q":
            break

    _clear()
    print(f"\n  {DIM}Nokido Control Panel fermé.{R}\n")


if __name__ == "__main__":
    # Le code de retour de _cli (0 fait / 2 inconnue / 3 refus) doit TRAVERSER main()
    # jusqu'au processus : sans SystemExit, tout CLI lisait 0 (mesure 2026-09-06, meme
    # piege que `--check` du census le matin meme). NR par sous-processus.
    raise SystemExit(main() or 0)
