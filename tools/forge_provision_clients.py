#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_provision_clients.py — provisionne les tokens par-agent + émet les configs client.

À LANCER EN SESSION OWNER (DPAPI vault) :
    LAFORGE_PYTHON tools/forge_provision_clients.py            # provisionne + émet
    LAFORGE_PYTHON tools/forge_provision_clients.py --dry-run  # rien n'écrit

CE QUE ÇA FAIT :
  1. Pour chaque agent client : si FORGE_TOKEN_<AGENT> absent du vault -> mint
     (secrets.token_hex) + set_secret (DPAPI). Idempotent (garde l'existant).
  2. Lit les tokens du vault.
  3. ÉMET les blocs de config client (avec les VRAIS tokens) -> C:/tmp/mcp_client_configs.txt.
     (N'écrase AUCUN client en cours : tu colles/revues toi-même.)
  4. --apply : POSE les jetons en variables d'environnement UTILISATEUR (HKCU\\Environment).
     C'est le geste qui manquait. Mesure 2026-08-03 : `~/.codex/config.toml` déclare
     `bearer_token_env_var = 'FORGE_TOKEN_CODEX'` et l'URL correcte, le jeton est au coffre
     et le hub l'accepte (HTTP 200) — mais la VARIABLE n'existait nulle part, donc codex
     affichait « laforge — Auth: Bearer token, Tools: (none) ». Émettre un bloc de config
     ne suffit pas quand le client lit l'ENVIRONNEMENT : il faut l'y écrire.

Les rings vivent dans config/agent_identities.json (déjà provisionnés : CLAUDE=1, GEMINI=2,
CODEX=2, CLINE=1, CLAUDE_DESKTOP=2, VSCODE=2, LMSTUDIO=3, ANTIGRAVITY=2). Reload hub requis
pour charger les NOUVEAUX tokens (_AGENT_TOKENS = import-cached). Le ring, lui, reload live (mtime).
"""
from __future__ import annotations

import hashlib
import json
import secrets as _secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = r"C:\tmp\mcp_client_configs.txt"
URL = "http://127.0.0.1:8766/mcp"
PY = __import__("os").path.expanduser("~/miniforge3/python.exe")
BRIDGE = str(ROOT / "tools" / "mcp_stdio_bridge.py").replace("\\", "/")

# client -> (LaForge-Agent-Name, est_nouveau)
AGENTS = [
    "CLAUDE", "GEMINI", "CODEX", "CLINE", "CLAUDE_DESKTOP", "VSCODE", "LMSTUDIO",
    "ANTIGRAVITY", "DSPY_ROUTER",
]
NEW = {"CLAUDE_DESKTOP", "VSCODE", "LMSTUDIO", "ANTIGRAVITY", "DSPY_ROUTER"}


def _cfg_blocks(tok: dict) -> str:
    def hdr(name):
        return f'"Authorization": "Bearer {tok[name]}", "LaForge-Agent-Name": "{name}"'
    b = []
    b.append("===== Claude Code  (~/.claude.json -> mcpServers) =====\n" + json.dumps(
        {"laforge-sovereign-hub": {"type": "http", "url": URL,
         "headers": {"Authorization": f"Bearer {tok['CLAUDE']}", "LaForge-Agent-Name": "CLAUDE"}}}, indent=2))
    b.append("===== Gemini CLI  (~/.gemini/settings.json -> mcpServers) =====\n" + json.dumps(
        {"laforge-sovereign-hub": {"url": URL,
         "headers": {"Authorization": f"Bearer {tok['GEMINI']}", "LaForge-Agent-Name": "GEMINI"},
         "timeout": 30000}}, indent=2))
    b.append("===== Codex  (~/.codex/config.toml) =====\n"
             f'[mcp_servers.nokido]\nurl = "{URL}"\n'
             f'http_headers = {{ "Authorization" = "Bearer {tok["CODEX"]}", "LaForge-Agent-Name" = "CODEX" }}\n'
             "# (si ta version codex ne supporte pas http_headers inline : "
             'bearer_token_env_var = "FORGE_TOKEN_CODEX" + exporter cette var pour le process codex)')
    b.append("===== Cline/Roo  (cline_mcp_settings.json -> mcpServers) =====\n" + json.dumps(
        {"laforge": {"type": "streamableHttp", "url": URL,
         "headers": {"Authorization": f"Bearer {tok['CLINE']}", "LaForge-Agent-Name": "CLINE"}}}, indent=2))
    b.append("===== VS Code  (.vscode/mcp.json) =====\n" + json.dumps(
        {"servers": {"laforge": {"type": "http", "url": URL,
         "headers": {"Authorization": f"Bearer {tok['VSCODE']}", "LaForge-Agent-Name": "VSCODE"}}}}, indent=2))
    b.append("===== LM Studio  (mcp.json) =====\n" + json.dumps(
        {"mcpServers": {"laforge": {"url": URL,
         "headers": {"Authorization": f"Bearer {tok['LMSTUDIO']}", "LaForge-Agent-Name": "LMSTUDIO"}}}}, indent=2))
    b.append("===== Claude Desktop  (claude_desktop_config.json -> mcpServers ; STDIO bridge) =====\n" + json.dumps(
        {"laforge": {"command": PY, "args": [BRIDGE],
         "env": {"FORGE_TOKEN_CLAUDE_DESKTOP": tok["CLAUDE_DESKTOP"], "LAFORGE_AGENT_NAME": "CLAUDE_DESKTOP"}}}, indent=2))
    b.append("===== Antigravity (agy)  (mcpServers) =====\n" + json.dumps(
        {"mcpServers": {"laforge-sovereign-hub": {"type": "http", "url": URL,
         "headers": {"Authorization": f"Bearer {tok['ANTIGRAVITY']}", "LaForge-Agent-Name": "ANTIGRAVITY"}}}}, indent=2))
    return "\n\n".join(b)


def _empreinte(v: str) -> str:
    """sha8 d'un jeton — de quoi COMPARER deux valeurs sans jamais en afficher une.

    Un rapport de synchronisation doit pouvoir dire « ces deux-là diffèrent » sans
    recopier le secret dans un terminal, un journal ou un transcript d'agent.
    """
    return hashlib.sha256((v or "").encode()).hexdigest()[:8]


def _poser_env_utilisateur(nom: str, valeur: str) -> str:
    """Écrit une variable d'environnement UTILISATEUR et notifie les fenêtres.

    Registre plutôt que `setx` : `setx` tronque à 1024 caractères et fait passer la
    valeur par une ligne de commande — donc un secret devient lisible dans l'historique
    et dans la cmdline du process. Le registre l'évite.

    Le piège, lui, est le même quel que soit le moyen et il est déjà consigné : écrire
    la variable NE RECHARGE PAS les process en cours. Un CLI déjà ouvert gardera l'ancienne
    valeur et paraîtra mal configuré alors que tout est correct. D'où la diffusion
    WM_SETTINGCHANGE ci-dessous pour ceux qui l'écoutent, et la consigne de ROUVRIR le
    terminal pour les autres.
    """
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            try:
                ancienne, _typ = winreg.QueryValueEx(k, nom)
            except FileNotFoundError:
                ancienne = None
            if ancienne == valeur:
                return "deja a jour"
            winreg.SetValueEx(k, nom, 0, winreg.REG_SZ, valeur)
            etat = "MISE A JOUR" if ancienne else "POSEE"
    except PermissionError:
        # Trois etats, jamais deux : un acces refuse n'est pas une absence.
        return "REFUSE (ce compte n'a pas acces au HKCU de l'owner -- lancer en session owner)"
    except Exception as exc:  # noqa: BLE001
        return "ECHEC %s" % type(exc).__name__
    try:
        import ctypes

        # HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG, 5 s
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)
    except Exception as exc:  # noqa: BLE001
        return "%s (diffusion KO: %s -- rouvrir le terminal)" % (etat, type(exc).__name__)
    return "%s (rouvrir les terminaux deja ouverts)" % etat


def _patch_codex(jeton: str, dry: bool) -> list[str]:
    """Bascule ~/.codex/config.toml de `bearer_token_env_var` vers `http_headers`.

    POURQUOI. Un jeton lu dans l'ENVIRONNEMENT est otage du process qui a lance le
    client : une variable mise a jour dans le registre ne redescend JAMAIS dans un
    process deja vivant, ni dans ses enfants. Mesure 2026-08-03 : coffre et registre
    alignes sur la meme empreinte, et la session portait encore l'ancienne — codex
    envoyait donc un jeton mort et recevait « HTTP 401 Unauthorized » des l'initialize.
    Ecrit dans le fichier, le jeton ne depend plus de qui a lance quoi, ni dans quel
    ordre. C'est deja ainsi que fonctionne Claude Code (Bearer dans `.mcp.json`).

    PRUDENCE. Une cle non supportee dans ce fichier ne casse pas seulement son bloc :
    elle casse le CHARGEMENT DE TOUTE la config codex (mesure consignee sur
    `wire_api`). D'ou sauvegarde horodatee AVANT, et relecture TOML APRES — en cas
    d'echec de parse, on restaure et on le dit.
    """
    import os as _os
    import shutil as _sh
    import time as _t

    out = []
    cfg = _os.path.expanduser("~/.codex/config.toml")
    if not _os.path.exists(cfg):
        return ["  config codex introuvable: %s" % cfg]
    txt = open(cfg, encoding="utf-8").read()
    if "[mcp_servers.laforge]" not in txt:
        return ["  section [mcp_servers.laforge] absente -> rien touche"]

    entete = "[mcp_servers.laforge]"
    lignes, dedans, neuf = txt.splitlines(), False, []
    for ligne in lignes:
        brut = ligne.strip()
        if brut == entete:
            dedans = True
            neuf.append(ligne)
            neuf.append('http_headers = { "Authorization" = "Bearer %s", '
                        '"LaForge-Agent-Name" = "CODEX" }' % jeton)
            continue
        if dedans and brut.startswith("["):
            dedans = False
        if dedans and (brut.startswith("bearer_token_env_var")
                       or brut.startswith("http_headers")):
            out.append("  retire: %s" % brut.split("=")[0].strip())
            continue
        neuf.append(ligne)
    rendu = "\n".join(neuf) + "\n"

    if dry:
        out.append("  [dry] config codex serait reecrite (http_headers, jeton sha8=%s)"
                   % _empreinte(jeton))
        return out
    sauve = "%s.bak-%s" % (cfg, _t.strftime("%Y%m%d-%H%M%S"))
    _sh.copy2(cfg, sauve)
    open(cfg, "w", encoding="utf-8").write(rendu)
    try:
        import tomllib

        with open(cfg, "rb") as fh:
            tomllib.load(fh)
    except Exception as exc:  # noqa: BLE001
        _sh.copy2(sauve, cfg)
        out.append("  TOML INVALIDE (%s) -> config RESTAUREE depuis %s"
                   % (type(exc).__name__, sauve))
        return out
    out.append("  config codex reecrite (jeton sha8=%s), sauvegarde: %s"
               % (_empreinte(jeton), sauve))
    out.append("  RELANCER codex — il relit sa config au demarrage")
    return out


def _check_env(tok: dict) -> list[str]:
    """Compare, pour chaque agent : coffre / registre utilisateur / session courante.

    Les TROIS peuvent diverger, et chaque divergence a une conséquence différente :
      - registre ABSENT      -> le provisionnement n'a pas eu lieu (ou pas sous ce compte)
      - registre OK, session ABSENTE  -> le terminal date d'avant l'écriture ; un process
        lancé là lit ses défauts et paraît mal configuré alors que tout est en place
      - session != coffre    -> valeur PÉRIMÉE : le client s'authentifie et se fait
        refuser en 401, ce qui se manifeste par « 0 outil » sans message d'erreur
    Aucune valeur n'est affichée, seulement des empreintes.
    """
    import os as _os

    out = []
    for a in AGENTS:
        nom = "FORGE_TOKEN_%s" % a
        coffre = tok.get(a)
        coffre = None if (not coffre or coffre == "<MISSING>") else coffre
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                try:
                    reg, _t = winreg.QueryValueEx(k, nom)
                except FileNotFoundError:
                    reg = None
        except Exception:  # noqa: BLE001
            reg = None
        sess = _os.environ.get(nom)
        e_c, e_r, e_s = _empreinte(coffre or ""), _empreinte(reg or ""), _empreinte(sess or "")
        if not coffre:
            verdict = "SANS JETON AU COFFRE"
        elif not reg:
            verdict = "registre ABSENT -> relancer --apply en session owner"
        elif e_r != e_c:
            verdict = "registre PERIME -> --apply"
        elif not sess:
            verdict = "session ABSENTE -> ROUVRIR le terminal (registre OK)"
        elif e_s != e_c:
            verdict = "session PERIMEE -> ROUVRIR le terminal"
        else:
            verdict = "ALIGNE"
        out.append("  %-28s coffre=%s registre=%s session=%s  %s"
                   % (nom, e_c if coffre else "----", e_r if reg else "----",
                      e_s if sess else "----", verdict))
    return out


def _sync_env(tok: dict, dry: bool) -> list[str]:
    """Aligne l'environnement utilisateur sur le coffre, agent par agent."""
    out = []
    for a in AGENTS:
        v = tok.get(a)
        if not v or v == "<MISSING>":
            out.append("  %-28s pas de jeton au coffre -> ignore" % ("FORGE_TOKEN_%s" % a))
            continue
        nom = "FORGE_TOKEN_%s" % a
        if dry:
            out.append("  [dry] %-22s serait pose (sha8=%s)" % (nom, _empreinte(v)))
        else:
            out.append("  %-28s %s (sha8=%s)" % (nom, _poser_env_utilisateur(nom, v), _empreinte(v)))
    return out


def main() -> int:
    dry = "--dry-run" in sys.argv
    from nokido_agent.app.forge_secrets import get_secret, set_secret  # type: ignore
    report = []
    for a in AGENTS:
        key = f"FORGE_TOKEN_{a}"
        cur = get_secret(key)
        if cur:
            # sha8 et NON les 6 derniers caracteres du jeton : une queue de secret
            # affichee reste un morceau de secret, et elle atterrit dans le terminal,
            # dans l'historique du shell et dans le transcript de l'agent qui lit la
            # sortie. L'empreinte permet de comparer deux valeurs sans en divulguer
            # aucune -- c'est tout ce dont un rapport de provisioning a besoin.
            report.append(f"  have  {a:<16} sha8={_empreinte(cur)}")
            continue
        tok = _secrets.token_hex(24)
        if dry:
            report.append(f"  [dry] would mint+seed {a}")
        else:
            ok = set_secret(key, tok)
            report.append(f"  SEED  {a:<16} {'ok' if ok else 'FAIL'} sha8={_empreinte(tok)}")
    # relire (post-seed)
    tok = {a: (get_secret(f"FORGE_TOKEN_{a}") or "<MISSING>") for a in AGENTS}
    missing = [a for a in AGENTS if tok[a] == "<MISSING>"]
    if not dry:
        Path(OUT).write_text(_cfg_blocks(tok), encoding="utf-8")
    print("=== provisioning tokens par-agent ===")
    print("\n".join(report))
    print(f"\nmissing après seed: {missing or 'aucun'}")
    if not dry:
        print(f"configs (VRAIS tokens, en clair) -> {OUT}")
        print("  ATTENTION : ce fichier porte les jetons de TOUS les agents en clair, hors"
              " coffre. Le supprimer une fois les configs collees.")
    else:
        print("[dry-run] aucune config écrite")
    if "--patch-codex" in sys.argv:
        print("\n=== bascule de la config codex vers http_headers ===")
        _j = tok.get("CODEX")
        if not _j or _j == "<MISSING>":
            print("  aucun jeton CODEX au coffre -> abandon")
        else:
            print("\n".join(_patch_codex(_j, dry)))
    if "--check" in sys.argv:
        print("\n=== etat coffre / registre / session (aucune ecriture) ===")
        print("\n".join(_check_env(tok)))
    if "--apply" in sys.argv:
        print("\n=== synchronisation de l'environnement utilisateur ===")
        print("\n".join(_sync_env(tok, dry)))
    else:
        print("\n(--apply pour POSER les jetons en variables d'environnement — "
              "requis par les clients qui lisent bearer_token_env_var, dont codex)")
    print("\nSUITE: reload hub (stop/start desktop UAC) pour charger les nouveaux tokens.")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
