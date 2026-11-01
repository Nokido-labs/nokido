"""forge_p0_mesure_entetes_clients.py -- P0 jetons clients au coffre seul, phase 2 : MESURE en profil jetable.

POURQUOI
  L'etude (docs/P0_JETONS_CLIENTS_COFFRE_SEUL.md, section 5 bis) dit, d'apres la documentation, que
  OpenCode, Gemini CLI et Copilot CLI savent construire un en-tete HTTP depuis une variable
  d'environnement. Une doc ne vaut pas mesure (OpenCode a un bogue ouvert, #5299) : cet outil le MESURE.

CE QU'IL FAIT
  1. installe les CLI dans un prefixe npm JETABLE (sandbox/workspace/p0_profil_jetable/npm) -- jamais le
     profil de l'owner, jamais ses configs (decision owner 25/10) ;
  2. demarre un serveur MCP d'ECHO sur 127.0.0.1 qui journalise l'en-tete Authorization recu ;
  3. pour chaque client : HOME/APPDATA jetables, config qui reference la variable NOKIDO_P0_FAUX_JETON
     (valeur FACTICE), commande qui provoque la connexion MCP ;
  4. verdict : NATIF_OK (en-tete developpe) | NON_DEVELOPPE (envoye litteral) | SANS_ENTETE | AUTRE |
     AUCUNE_REQUETE (le client n'a pas parle : ce n'est PAS un refus de la forme, souvent une auth CLI).

  Aucun vrai jeton, aucun appel au hub. Rapport : sandbox/workspace/p0_profil_jetable/rapport.json.

Usage : run action=run_job online=true script=tools/forge_p0_mesure_entetes_clients.py
        script_args="--installer"     (1re fois : npm install dans le prefixe jetable)
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/coffre : mesure en profil jetable de l'en-tete MCP construit depuis une variable"  # organe declare le 2026-10-25

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
BASE = _RACINE_DONNEES / "sandbox" / "workspace" / "p0_profil_jetable"
VAR = "NOKIDO_P0_FAUX_JETON"
FAUX = "-".join(("faux", "p0", "0000"))          # factice, compose (gate egress generic_secret)
PAQUETS = {"opencode": "opencode-ai", "gemini": "@google/gemini-cli", "copilot": "@github/copilot"}
# Mesure 25/10 : le postinstall d'opencode-ai ne trouvait pas son binaire de plateforme -> npm annulait TOUT
# (Gemini et Copilot compris). Un paquet par installation, et le binaire Windows demande explicitement.
EXTRAS = {"opencode": ["opencode-windows-x64", "opencode-windows-x64-baseline"]}


def cause_silence(sortie: str) -> str:
    """Pourquoi un client n'a rien envoye : une AUCUNE_REQUETE n'est jamais un refus de la forme."""
    s = (sortie or "").lower()
    if "untrusted" in s:
        return "DOSSIER_NON_APPROUVE"
    if "no authentication" in s or "/login" in s:
        return "AUTH_CLI_REQUISE"
    if "introuvable" in s or "not found" in s or "not recognized" in s:
        return "BINAIRE_ABSENT"
    return "INCONNUE"
DELAI_S = 90


# `say` (ASCII pur : le stdout d'un run_job est en cp1252) est REUTILISE, pas recopie : la 4e copie avait
# rompu le cliquet de duplication au pre-push (25/10). Import sans effet de bord (definitions seules).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from forge_push_sovereign import say  # noqa: E402


def verdict(entetes, attendu: str) -> str:
    """En-tetes Authorization recus -> NATIF_OK | NON_DEVELOPPE | SANS_ENTETE | AUTRE | AUCUNE_REQUETE."""
    if not entetes:
        return "AUCUNE_REQUETE"
    vus = [h for h in entetes if h]
    if any(h == "Bearer " + attendu for h in vus):
        return "NATIF_OK"
    if any(("{env:" in h) or ("${" in h) or (("$" + VAR) in h) for h in vus):
        return "NON_DEVELOPPE"
    if not vus:
        return "SANS_ENTETE"
    return "AUTRE"


class _Echo(BaseHTTPRequestHandler):
    recus: list = []

    def log_message(self, *a):  # pas de bruit sur stderr
        return

    def _noter(self):
        _Echo.recus.append({"methode": self.command, "chemin": self.path,
                            "authorization": self.headers.get("Authorization", "")})

    def do_GET(self):
        self._noter()
        self.send_response(405)
        self.end_headers()

    def do_POST(self):
        self._noter()
        n = int(self.headers.get("Content-Length") or 0)
        try:
            msg = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            msg = {}
        if "id" not in msg:                       # notification : accepte, pas de corps
            self.send_response(202)
            self.end_headers()
            return
        if msg.get("method") == "initialize":
            res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                   "serverInfo": {"name": "nokido-p0-echo", "version": "0"}}
        else:
            res = {"tools": []}
        corps = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)


def _bin(nom: str) -> Path:
    return BASE / "npm" / "node_modules" / ".bin" / (nom + ".cmd")


def _profil(client: str) -> dict:
    home = BASE / client / "home"
    for d in (home, home / "AppData" / "Roaming", home / "AppData" / "Local", home / ".config"):
        d.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "COMSPEC", "PATHEXT",
                                                               "TEMP", "TMP", "WINDIR", "NUMBER_OF_PROCESSORS")}
    env.update({"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData" / "Roaming"),
                "LOCALAPPDATA": str(home / "AppData" / "Local"), "XDG_CONFIG_HOME": str(home / ".config"),
                VAR: FAUX, "NO_COLOR": "1", "CI": "1"})
    return {"home": home, "env": env}


def _configurer(client: str, url: str, p: dict) -> list:
    home = p["home"]
    if client == "opencode":
        cfg = home / "opencode.json"
        cfg.write_text(json.dumps({"$schema": "https://opencode.ai/config.json", "mcp": {"echo": {
            "type": "remote", "url": url, "oauth": False, "enabled": True,
            "headers": {"Authorization": "Bearer {env:%s}" % VAR}}}}), encoding="utf-8")
        p["env"]["OPENCODE_CONFIG"] = str(cfg)
        return [str(_bin("opencode")), "mcp", "list"]
    if client == "gemini":
        d = home / ".gemini"
        d.mkdir(exist_ok=True)
        (d / "settings.json").write_text(json.dumps({"mcpServers": {"echo": {
            "httpUrl": url, "headers": {"Authorization": "Bearer $%s" % VAR}}}}), encoding="utf-8")
        # Mesure 25/10 : « MCP servers are configured but disabled because this folder is untrusted ».
        (d / "trustedFolders.json").write_text(json.dumps({str(home): "TRUST_FOLDER"}), encoding="utf-8")
        return [str(_bin("gemini")), "mcp", "list"]
    if client == "copilot":
        cfg = {"mcpServers": {"echo": {"type": "http", "url": url, "tools": ["*"],
                                       "headers": {"Authorization": "Bearer ${%s}" % VAR}}}}
        for d in (home / ".copilot", home / ".config" / ".copilot"):
            d.mkdir(parents=True, exist_ok=True)
            (d / "mcp-config.json").write_text(json.dumps(cfg), encoding="utf-8")
        return [str(_bin("copilot")), "-p", "liste tes outils", "--allow-all-tools"]
    raise ValueError(client)


def installer() -> int:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        say("[install] npm INTROUVABLE -- rien installe")
        return 2
    (BASE / "npm").mkdir(parents=True, exist_ok=True)
    echecs = 0
    for client, paquet in PAQUETS.items():
        # Le .cmd lance DIRECTEMENT (CreateProcess passe par cmd.exe en citant le chemin) : `cmd /c <chemin>`
        # cassait sur l'espace de `C:\Program Files` (mesure 25/10 : « 'C:\Program' n'est pas reconnu »).
        cmd = [npm, "install", "--prefix", str(BASE / "npm"), "--no-audit", "--no-fund",
               "--cache", str(BASE / "npm-cache"), *EXTRAS.get(client, []), paquet]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        erreurs = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith("npm error")]
        say("[install] %-9s rc=%s %s" % (client, r.returncode, " | ".join(erreurs[:4])[:600]))
        echecs += r.returncode != 0
    return 0 if echecs < len(PAQUETS) else 1      # on mesure ce qui s'est installe ; le reste est dit


def mesurer(clients) -> dict:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/mcp" % srv.server_address[1]
    rapport = {"date": time.strftime("%Y-%m-%dT%H:%M:%S"), "url_echo": url, "clients": {}}
    for client in clients:
        if not _bin(client).exists():
            rapport["clients"][client] = {"verdict": "NON_INSTALLE"}
            say("%-9s NON_INSTALLE (lancer --installer)" % client)
            continue
        _Echo.recus = []
        p = _profil(client)
        cmd = _configurer(client, url, p)
        try:
            r = subprocess.run(cmd, env=p["env"], cwd=str(p["home"]), capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=DELAI_S)
            rc, sortie = r.returncode, (r.stdout + r.stderr)[-800:]
        except subprocess.TimeoutExpired as e:
            rc, sortie = "TIMEOUT", str(e.stdout or "")[-800:]
        auth = [x["authorization"] for x in _Echo.recus]
        v = verdict(auth, FAUX)
        # Jamais la valeur : seulement sa FORME (le faux jeton est factice, mais la regle vaut pour tout).
        formes = sorted({("Bearer <FAUX>" if a == "Bearer " + FAUX else a.replace(FAUX, "<FAUX>"))
                         for a in auth})
        cause = cause_silence(sortie) if v == "AUCUNE_REQUETE" else ""
        rapport["clients"][client] = {"verdict": v, "cause": cause, "rc": rc, "requetes": len(_Echo.recus),
                                      "formes_entete": formes, "sortie_fin": sortie}
        say("%-9s %-15s %s requetes=%d rc=%s formes=%s" % (client, v, cause, len(_Echo.recus), rc, formes))
    srv.shutdown()
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / "rapport.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    say("[rapport] %s" % (BASE / "rapport.json"))
    return rapport


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--installer", action="store_true", help="npm install des CLI dans le prefixe jetable")
    ap.add_argument("--clients", default=",".join(PAQUETS), help="liste separee par des virgules")
    a = ap.parse_args(argv)
    if a.installer:
        rc = installer()
        if rc:
            return rc
    mesurer([c for c in a.clients.split(",") if c])
    return 0


if __name__ == "__main__":
    sys.exit(main())
