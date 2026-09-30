"""
nokido_tray.py — Icône tray Windows Nokido
=============================================
Lance en arrière-plan au démarrage Windows.
Affiche l'état du hub, du mode, des agents dans le menu tray.

Installation :
  pip install pystray pillow --break-system-packages
  # Ajouter au démarrage Windows :
  # shell:startup → raccourci vers launch_tray.bat

Fonctionnalités :
  - Icône Nokido (marque du webhub, app/web_hub/static/nokido-mark-light.svg) ; l'état
    se lit sur le liseré et la pastille (vert=UP, rouge=DOWN, orange=CHEF, violet=admin)
  - Menu : état hub, mode actif, agents, liens rapides
  - Clic gauche → ouvre /forge/network
  - Gestes de stack CALQUÉS sur le panneau de contrôle (2026-09-26) : le tray LANCE
    `nokido_launcher.py --action <start|stop|restart|restart-hub|status>` dans une
    console visible — une seule implémentation, celle du panneau
  - Ordres de redémarrage CONFIRMÉS par l'owner (élicitation MCP) : pris au hub
    (`hub action=ordre_bureau`, app/forge_ordres_bureau.py) et exécutés par le panneau
  - Identité : jeton propre TRAY, ring 2 (décision owner 2026-09-26) ; instance unique
  - Notification Windows quand le mode change
  - Polling toutes les 10s

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `lancer_panneau` — `Nokido Control Panel.bat --action <action>` dans une console VISIBLE (`cmd /k`) ; rend False, et le DIT, si rien n'est lance.
"""

from __future__ import annotations

__FORGE_COLOR__ = "interface/ui_ : icone tray Windows lancee au demarrage"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("pip install pystray pillow")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
AUTH_F = ROOT / "config" / "authority_state.json"
HUB_URL = "http://127.0.0.1:8766"
POLL_SEC = 10
# Panneau de controle : SEULE implementation des gestes de stack (2026-09-26). Le tray le
# LANCE au lieu de copier ses .ps1 : le restart du panneau attend le signal de fin du stop
# avant le start, relance le tray, et dit ce qui s'est passe.
LANCEUR = ROOT / "tools" / "nokido_launcher.py"
# Le panneau de l'owner, celui du Bureau : le tray l'OUVRE (demande owner 2026-09-26),
# il ne lance plus le launcher en direct. Le .bat relaie ses arguments (`%*`).
PANNEAU_BAT = ROOT / "tools" / "Nokido Control Panel.bat"
ACTIONS_PANNEAU = ("start", "stop", "restart", "restart-hub", "status",
                   # Tailscale (2026-09-29) : seule la session owner peut le piloter.
                   "tailscale-statut", "funnel-ouvrir", "funnel-fermer")
MARQUE_SVG = ROOT / "app" / "web_hub" / "static" / "nokido-mark-light.svg"
TRAY_DEJA_ACTIF = 3  # code de sortie d'une seconde instance, lu par nokido_launcher._start_tray

sys.path.insert(0, str(ROOT))
try:
    from nokido_agent.app.forge_secrets import get_secret  # noqa: E402
    TRAY_TOKEN = get_secret("FORGE_TOKEN_TRAY") or ""
except Exception:
    # Le tray doit charger meme si forge_secrets/ses deps manquent dans l'env GUI :
    # le menu flotte (nokido_start/stop.ps1) n'a pas besoin du token.
    TRAY_TOKEN = ""


def _track_pid(role: str, pid: int):
    import datetime as _dt
    import json as _j

    try:
        dp = ROOT / "DIRECTORY.json"
        d = _j.loads(dp.read_text(encoding="utf-8"))
        k = f"TRAY_{role.upper()}"
        if k not in d["correspondents"]:
            d["correspondents"][k] = {"type": "tray_spawn"}
        d["correspondents"][k].update(
            {"pid": pid, "role": role, "ts": _dt.datetime.now().isoformat(), "auto": True}
        )
        dp.write_text(_j.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:  # muet-ok : le suivi de PID est un confort, jamais bloquant
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ÉTAT GLOBAL
# ─────────────────────────────────────────────────────────────────────────────

_state = {
    "hub_up": False,
    "master_dev": None,
    "master_ttl": 0,
    "master_expired": True,
    "ring": 4,
    "version": "?",
    "mode": "?",
    "agents": {},
    "errors": 0,
    "last_ok": None,
    "ordre_why": "",
}

# ─────────────────────────────────────────────────────────────────────────────
# ICÔNES — générées dynamiquement selon l'état
# ─────────────────────────────────────────────────────────────────────────────


_MARQUE: dict = {}


def _marque_nokido(taille: int = 60):
    """Marque Nokido (SVG du webhub) rendue par PyMuPDF, en cache ; None si illisible.

    MuPDF ne peint pas un trait en degrade : `url(#flux)` sortait NOIR (mesure 26/09).
    Le degrade du flux est remplace par sa teinte mediane avant le rendu."""
    if taille not in _MARQUE:
        img = None
        try:
            import io

            import fitz

            svg = MARQUE_SVG.read_bytes().replace(b'stroke="url(#flux)"', b'stroke="#F24F4F"')
            page = fitz.open(stream=svg, filetype="svg")[0]
            z = taille / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=True)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")
        except Exception as exc:
            # DIT, pas tu : une icone de repli sans motif passerait pour un choix.
            print(f"[tray] marque Nokido illisible ({type(exc).__name__}: {exc}) : icone de repli")
        _MARQUE[taille] = img
    return _MARQUE[taille]


def _make_icon(state: str = "ok") -> Image.Image:
    """Icone 64x64 : la marque Nokido sur une tuile sombre. L'ETAT se lit sur le lisere et
    la pastille : ok vert, down rouge, chef orange, warn jaune, admin violet."""
    colors = {
        "ok": "#56d364",
        "down": "#f85149",
        "chef": "#ffd670",
        "warn": "#e3b341",
        "admin": "#a371f7",
    }
    accent = colors.get(state, colors["ok"])

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([1, 1, 62, 62], radius=14, fill="#1b1826", outline=accent, width=3)
    marque = _marque_nokido()
    if marque is not None:
        img.alpha_composite(marque, ((64 - marque.width) // 2, (64 - marque.height) // 2))
    else:
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 26)
        except Exception:  # muet-ok : police absente -> police par defaut, l'icone reste
            font = ImageFont.load_default()
        draw.text((30, 31), "N", fill=accent, font=font, anchor="mm")
    draw = ImageDraw.Draw(img)
    draw.ellipse([44, 44, 62, 62], fill=accent, outline="#1b1826", width=3)
    return img


def _icon_state() -> str:
    if not _state["hub_up"]:
        return "down"
    mode = _state.get("mode", "")
    if mode == "CHEF":
        return "chef"
    if not _state.get("master_expired") and _state.get("master_dev") == "CLAUDE":
        return "admin"
    if _state["errors"] > 3:
        return "warn"
    return "ok"


# ─────────────────────────────────────────────────────────────────────────────
# POLLING HUB
# ─────────────────────────────────────────────────────────────────────────────


def _read_authority():
    try:
        d = json.loads(AUTH_F.read_text(encoding="utf-8"))
        md = d.get("master_dev", {})
        now = time.time()
        last = md.get("last_beat") or md.get("acquired_at") or 0
        ttl = md.get("ttl", 1800)
        exp = (now - last) > ttl if md.get("agent_id") else True
        _state["master_dev"] = md.get("agent_id")
        _state["master_ttl"] = max(0, int(ttl - (now - last))) if not exp else 0
        _state["master_expired"] = exp
    except Exception:  # muet-ok : fichier d'autorite absent = etat inconnu, pas une panne
        pass


def _mcp(tool, arguments=None):
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }
    ).encode()
    req = urllib.request.Request(
        f"{HUB_URL}/mcp",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Agent-Name": "TRAY",
            "Authorization": f"Bearer {TRAY_TOKEN}",
            "Connection": "close",
        },
        method="POST",
    )
    res = json.loads(urllib.request.urlopen(req, timeout=5).read())
    txt = res.get("result", {}).get("content", [{}])[0].get("text", "{}")
    try:
        return json.loads(txt)
    except:
        return txt


def _poll_hub():
    """Interroge le hub et met à jour _state."""
    _read_authority()
    try:
        # Health
        resp = urllib.request.urlopen(f"{HUB_URL}/health", timeout=3)
        data = json.loads(resp.read())
        _state["hub_up"] = True
        _state["version"] = data.get("version", "?")
        _state["errors"] = 0
        _state["last_ok"] = time.strftime("%H:%M:%S")
    except Exception:
        _state["hub_up"] = False
        _state["errors"] += 1
        return

    # Mode + agents. Deux pieges mesures le 2026-08-17 :
    #   - cette requete etait construite A LA MAIN, SANS le jeton que _mcp()
    #     presente : le hub repondait 401 et l'exception muette laissait « ? » ;
    #   - le hub rend du TEXTE (« mode=AUTO  agent=... »), pas du JSON, et un
    #     refus de droits voyage dans un `result` JSON-RPC VALIDE
    #     (« GATE_DENIED: ring 4 <= requis 2 »).
    try:
        data = _mcp("get_mode")
        prev_mode = _state["mode"]
        if isinstance(data, dict):
            _state["mode"] = data.get("mode", "?")
            _state["agents"] = data.get("agents", {})
        elif str(data).startswith("GATE_DENIED"):
            _state["mode"] = "refusé"
            _state["agents"] = {}
        else:
            txt = str(data)
            found = re.search(r"mode=(\S+)", txt)
            _state["mode"] = found.group(1) if found else "?"
            agents = {}
            for line in txt.splitlines()[1:]:
                agent, sep, status = line.partition(":")
                if sep and agent.strip():
                    agents[agent.strip()] = status.strip()
            _state["agents"] = agents
        _state["mode_why"] = ""
        # Notif si mode change
        if prev_mode != "?" and prev_mode != _state["mode"]:
            _notify(f"Nokido mode → {_state['mode']}")
    except Exception as exc:
        # Garder la RAISON : un mode « ? » sans motif a caché un 401 pendant
        # des semaines. Elle remonte dans le menu du tray.
        _state["mode"] = "?"
        _state["mode_why"] = str(exc)[:80]


def _notify(msg: str):
    """Notification Windows toast via PowerShell."""
    try:
        ps = f"""
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.ShowBalloonTip(3000, 'Nokido', '{msg}', 'Info')
Start-Sleep 4
$n.Dispose()
"""
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:  # muet-ok : une notification perdue ne doit pas tuer le tray
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ACTIONS MENU
# ─────────────────────────────────────────────────────────────────────────────


def _open_network(icon, item):
    webbrowser.open(f"{HUB_URL}/forge/network")


def _open_logs(icon, item):
    webbrowser.open(f"{HUB_URL}/api/network/history?limit=50")


# Gestes de stack = le PANNEAU DE CONTROLE (2026-09-26). Remplacent `Restart-Service
# NokidoMCP` / `Stop-Service NokidoMCP` et les .ps1 lances en fenetre cachee : le service
# NSSM NokidoMCP est arrete PAR DESIGN, le hub :8766 est un ENFANT du superviseur, et le
# relancer par NSSM ouvrait un second hub sur le meme port (voie retiree du panneau le
# 2026-09-06). Le tray ne garde plus de copie : il lance ce que lance le panneau.
def _python_console() -> str:
    """L'interpreteur du tray, en version console : sous pythonw, la console du panneau
    resterait vide."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def lancer_panneau(action: str, origine: str = "menu") -> bool:
    """`Nokido Control Panel.bat --action <action>` dans une console VISIBLE (`cmd /k` :
    elle reste ouverte, l'owner lit l'issue). Rend False, et le DIT, si rien n'est lance."""
    if action not in ACTIONS_PANNEAU:
        _notify(f"Action inconnue du panneau : {action}")
        return False
    if not PANNEAU_BAT.exists():
        _notify(f"Panneau introuvable : {PANNEAU_BAT}")
        return False
    ligne = subprocess.list2cmdline([str(PANNEAU_BAT), "--action", action])
    try:
        # Guillemets EXTERIEURS : cmd /k retire le premier et le dernier guillemet de la
        # ligne ; sans eux, le chemin du lanceur (« Script python IA ») serait coupe.
        subprocess.Popen(f'cmd.exe /k "{ligne}"', cwd=str(ROOT),
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    except Exception as e:
        _notify(f"Panneau non lancé ({action}) : {e}")
        return False
    _notify(f"Panneau : {action} ({origine})")
    return True


def _panneau(action: str):
    def _action(icon=None, item=None):
        lancer_panneau(action)

    return _action


# ── Self-heal au demarrage (main) — le tray tourne EN-SESSION donc le spawn interactif
#    des services :7400/:7420/:7500/:8099 marche (vs supervisor SYSTEM au boot qui ne
#    peut pas). Les gestes du MENU passent par le panneau (lancer_panneau).
def _restart_fleet(icon, item):
    """Stop PUIS start — attend la FERMETURE REELLE des ports avant de relancer.
    Le stop s'auto-eleve/detache : un Start-Sleep fixe ne suffit pas (le start
    partait avant la mort des process -> ports tenus -> remonte mal)."""
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass",
             "-File", str(ROOT / "tools" / "nokido_restart.ps1")],
            cwd=str(ROOT), creationflags=subprocess.CREATE_NO_WINDOW,
        )
        _notify("Flotte : stop → attente fermeture ports → start…")
    except Exception as e:
        _notify(f"Erreur restart flotte: {e}")


def _set_mode(mode: str):
    def _action(icon, item):
        # 2026-09-26 : cet appel MUTANT partait SANS jeton (identite DECLAREE, jamais
        # prouvee) et le tray affichait le nouveau mode sans lire la reponse. set_mode
        # exige ring 0 : TRAY (ring 2) est refuse, et le tray le DIT au lieu d'afficher
        # un mode qui n'a pas change.
        try:
            r = _mcp("set_mode", {"mode": mode, "reason": "tray"})
        except Exception as e:
            _notify(f"Erreur set_mode: {e}")
            return
        txt = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
        if txt.startswith(("GATE_DENIED", "ERR", "Error")) or "refus" in txt.lower():
            _notify(f"set_mode refusé : {txt[:120]}")
            return
        _state["mode"] = mode
        icon.title = f"Nokido — {mode}"
        _notify(f"Mode → {mode}")

    return _action


def _prendre_ordre():
    """Ordre CONFIRME par l'owner (elicitation, app/forge_ordres_bureau.py) : le prendre au
    hub et l'executer par le panneau. Le hub ne le rend qu'une fois ; le tray n'execute
    qu'une action connue du panneau."""
    if not _state["hub_up"]:
        return
    try:
        r = _mcp("hub", {"action": "ordre_bureau"})
    except Exception as exc:
        _state["ordre_why"] = f"{type(exc).__name__}: {exc}"[:80]
        return
    if not isinstance(r, dict):
        # GATE_DENIED, hub pas encore redemarre (« action inconnue »)... : le DIRE au menu.
        _state["ordre_why"] = str(r)[:80]
        return
    etat = r.get("etat")
    _state["ordre_why"] = "" if etat in ("RIEN", "ORDRE") else str(r.get("raison") or r)[:80]
    if etat != "ORDRE":
        return
    ordre = r.get("ordre") or {}
    action = ordre.get("action")
    if action not in ACTIONS_PANNEAU:
        _notify(f"Ordre {ordre.get('id')} ignoré : action inconnue {action!r}")
        return
    lancer_panneau(action, origine=f"ordre {ordre.get('id')} de {ordre.get('demandeur')}, confirmé par l'owner")


def _quit(icon, item):
    icon.stop()


# ─────────────────────────────────────────────────────────────────────────────
# MENU DYNAMIQUE
# ─────────────────────────────────────────────────────────────────────────────


def _build_menu(icon) -> pystray.Menu:
    hub_status = f"Hub v{_state['version']} — {'UP ✓' if _state['hub_up'] else 'DOWN ✗'}"
    last_ok = f"Dernier ping : {_state['last_ok'] or 'jamais'}"
    mode_why = _state.get("mode_why") or ""

    agents_items = []
    for ag, info in (_state.get("agents") or {}).items():
        status = info.get("status", "?") if isinstance(info, dict) else str(info)
        agents_items.append(pystray.MenuItem(f"  {ag} — {status}", None, enabled=False))

    return pystray.Menu(
        pystray.MenuItem(hub_status, None, enabled=False),
        pystray.MenuItem(last_ok, None, enabled=False),
        *(
            [pystray.MenuItem(f"Mode {_state['mode']} — {mode_why}", None, enabled=False)]
            if mode_why
            else [pystray.MenuItem(f"Mode : {_state['mode']}", None, enabled=False)]
        ),
        pystray.Menu.SEPARATOR,
        # Agents
        *(
            [pystray.MenuItem("Agents :", None, enabled=False)] + agents_items
            if agents_items
            else [pystray.MenuItem("Agents : aucun", None, enabled=False)]
        ),
        pystray.Menu.SEPARATOR,
        # Navigation
        pystray.MenuItem("📊 Network Monitor", _open_network, default=True),
        pystray.MenuItem("📋 Audit Logs", _open_logs),
        pystray.Menu.SEPARATOR,
        # Gestes de stack = ceux du PANNEAU DE CONTROLE (nokido_launcher.py), memes libelles
        pystray.MenuItem("▶ Start full-stack", _panneau("start")),
        pystray.MenuItem("■ Stop full-stack", _panneau("stop")),
        pystray.MenuItem("↻ Restart full-stack", _panneau("restart")),
        pystray.MenuItem("↺ Restart HUB seul (superviseur)", _panneau("restart-hub")),
        pystray.MenuItem("ℹ Statut", _panneau("status")),
        pystray.Menu.SEPARATOR,
        # Tailscale (2026-09-29) : seule la session owner peut le piloter ; un clic ici EST le geste
        # owner. Un agent passe par `hub action=demander_ordre` (question par elicitation).
        pystray.MenuItem("🌐 Tailscale : statut du Funnel", _panneau("tailscale-statut")),
        pystray.MenuItem("🌐 Tailscale : OUVRIR le Funnel (:8793)", _panneau("funnel-ouvrir")),
        pystray.MenuItem("🌐 Tailscale : FERMER le Funnel", _panneau("funnel-fermer")),
        *(
            [pystray.MenuItem(f"Ordres : {_state['ordre_why']}", None, enabled=False)]
            if _state.get("ordre_why")
            else []
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("✕ Quitter le tray", _quit),
    )


# ─────────────────────────────────────────────────────────────────────────────
# BOUCLE POLLING + UPDATE ICÔNE
# ─────────────────────────────────────────────────────────────────────────────


def _poll_loop(icon: pystray.Icon):
    while True:
        _poll_hub()
        _prendre_ordre()
        # Mettre à jour icône + title + menu
        state_key = _icon_state()
        icon.icon = _make_icon(state_key)
        mode = _state.get("mode", "?")
        hub_v = _state.get("version", "?")
        icon.title = f"Nokido v{hub_v} — {mode} — {'UP' if _state['hub_up'] else 'DOWN'}"
        icon.menu = _build_menu(icon)
        time.sleep(POLL_SEC)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────


def _instance_unique() -> bool:
    """Vrai si ce tray est le seul. Mutex NOMME de session : Windows le libere a la mort
    du process, il ne peut donc pas etre perime (un fichier-verrou le serait apres un
    kill). Cas vise : un restart lance DEPUIS le tray -- le panneau relance un tray alors
    que celui-ci vit encore (le stop l'epargne)."""
    try:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _state["_mutex"] = k32.CreateMutexW(None, False, "Local\\NokidoTray")
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception as exc:
        print(f"[tray] instance unique non verifiable ({type(exc).__name__}: {exc}) : on continue")
        return True


def main():
    if not _instance_unique():
        print(f"[tray] deja actif : cette instance sort (code {TRAY_DEJA_ACTIF})")
        sys.exit(TRAY_DEJA_ACTIF)
    # Premier poll
    _poll_hub()

    # Self-heal post-reboot : le tray tourne EN-SESSION -> si la flotte web (:7400)
    # est down au lancement, on la demarre (le supervisor SYSTEM ne peut pas au boot).
    if "--no-selfheal" in sys.argv:
        # Lance dans la foulee d'un start : la flotte vient d'etre demarree, il n'y
        # a rien a soigner. Sans ce garde, le tray sabordait le start qui venait
        # de le lancer.
        print("[tray] self-heal desactive (--no-selfheal)")
    else:
        try:
            import socket as _sk

            # La flotte web (:7400) monte APRES le hub. Un test UNIQUE et immediat
            # fabrique un faux « down » -> _restart_fleet() -> nokido_stop.ps1 :
            # un Start se transformait en Stop quelques secondes plus tard. On
            # laisse donc le port monter avant de conclure.
            _down = True
            for _ in range(20):
                _s = _sk.socket()
                _s.settimeout(0.5)
                _down = _s.connect_ex(("127.0.0.1", 7400)) != 0
                _s.close()
                if not _down:
                    break
                time.sleep(1.0)
            if _down:
                # stop+start (jamais un start nu : evite les process zombies / ports tenus
                # par une tentative supervisor en crash-loop).
                _restart_fleet(None, None)
                _notify("Flotte web down au demarrage → stop+start auto (en-session).")
        except Exception:  # muet-ok : le self-heal est opportuniste, le tray doit vivre sans
            pass

    icon = pystray.Icon(
        name="Nokido",
        icon=_make_icon(_icon_state()),
        title="Nokido — hub & flotte web",
        menu=pystray.Menu(pystray.MenuItem("Chargement...", None, enabled=False)),
    )

    # Clic gauche → Network Monitor
    icon.default_action = _open_network

    # Polling dans un thread daemon
    t = threading.Thread(target=_poll_loop, args=(icon,), daemon=True)
    t.start()

    print("[tray] Nokido tray démarré")
    icon.run()


if __name__ == "__main__":
    main()
