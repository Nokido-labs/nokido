"""forge_cli_route.py — toggle ON/OFF du routage des CLI agentiques via les ingress Nokido.

__FORGE_COLOR__ = "metabolisme-llm"

Option B (wrapper opt-in) + toggle activable/désactivable, pour TOUS les CLI/LLM.
Anti-dup : nokido_launcher.py = contrôle stack ; forge_runas_launcher = privilège ;
aucun ne route un CLI vers les ingress. Module dédié.

PRINCIPE
  - flag partagé `sandbox/cli_route.json` (global + per-cli) = source unique.
  - `launch <cli> [args...]` : lit le flag ; si ON **et hub :8766 joignable** → set l'env
    ingress + exec le CLI (route 100% Nokido) ; si OFF **ou hub down** → exec NATIF + warn.
    => le CLI ne casse JAMAIS à cause de Nokido (0 dépendance dure, fallback natif auto).
  - `on|off|status [cli]` : bascule le flag. C'est LE point de contrôle (exposable en
    wrapper `lf-route`, en skill, ou lu par un hook SessionStart pour afficher l'état).

MAPPING INGRESS (env posé AVANT exec) :
  claude  -> ANTHROPIC_BASE_URL=:7776  (+ ANTHROPIC_AUTH_TOKEN dummy)
  gemini  -> GOOGLE_GEMINI_BASE_URL=:7778
  cline / openai-compat -> OPENAI_BASE_URL=:7777/v1 (+ OPENAI_API_KEY dummy)
  copilot -> BYOK env : COPILOT_PROVIDER_BASE_URL=:7777/v1 (+ MODEL_ID claude-sonnet-4.5
             completions + WIRE_MODEL qwen + API_KEY). GitHub auth non requise = 0 quota.

USAGE
  forge_cli_route.py status
  forge_cli_route.py on  [claude|gemini|copilot|cline|all]
  forge_cli_route.py off [claude|gemini|copilot|cline|all]
  forge_cli_route.py launch claude [args...]
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
STATE = ROOT / "sandbox" / "cli_route.json"
HUB_HEALTH = os.environ.get("FORGE_HUB_URL", "http://127.0.0.1:8766/mcp").replace("/mcp", "/health")

# cli -> (var d'env base_url, valeur, {env auth dummy})
INGRESS = {
    "claude": ("ANTHROPIC_BASE_URL", "http://127.0.0.1:7776", {"ANTHROPIC_AUTH_TOKEN": "laforge-local"}),
    "gemini": ("GOOGLE_GEMINI_BASE_URL", "http://127.0.0.1:7778", {}),
    "cline": ("OPENAI_BASE_URL", "http://127.0.0.1:7777/v1", {"OPENAI_API_KEY": "laforge-local"}),
    # copilot BYOK (cf `copilot help providers`) : COPILOT_PROVIDER_BASE_URL active le mode
    # BYOK -> GitHub auth NON requise = 0 quota GitHub. MODEL_ID well-known = active le
    # tool-support ; WIRE_MODEL = nom envoyé à :7777 (-> tool-passthrough -> ollama).
    "copilot": ("COPILOT_PROVIDER_BASE_URL", "http://127.0.0.1:7777/v1", {
        # MODEL_ID = modele well-known à wireApi "completions" (gpt-5* = "responses",
        # que :7777 ne sert PAS -> claude-* = completions + tool-support). WIRE_API forcé.
        "COPILOT_PROVIDER_MODEL_ID": "claude-sonnet-4.5",
        "COPILOT_PROVIDER_WIRE_MODEL": "qwen2.5-coder:latest",
        "COPILOT_PROVIDER_WIRE_API": "completions",
        "COPILOT_PROVIDER_API_KEY": "laforge-local",
    }),
}
# vibe (mistral-vibe) : il n'existe pas d'ingress Mistral, donc `var is None` et
# cmd_launch bascule en NATIF — le garde est déjà là. Il figure ici pour être RECONNU
# par `launch` et recevoir son environnement, qui n'est PAS du routage.
INGRESS["vibe"] = (None, None, {})

# mammouth (mammouth-ai/code, fork d'opencode) : même situation — pas d'ingress dédié,
# il est ici pour être reconnu par `launch` et recevoir son environnement.
INGRESS["mammouth"] = (None, None, {})

# Variables posées QUEL QUE SOIT le toggle : le CLI en a besoin pour fonctionner.
# Les mêler au routage les rendrait dépendantes d'un flag sans rapport.
ALWAYS_ENV = {
    "vibe": {"VIBE_HOME": str(ROOT / "config" / "clients" / "vibe")},
    # mammouth hérite d'opencode : la variable garde le préfixe OPENCODE_.
    "mammouth": {"OPENCODE_CONFIG_DIR": str(ROOT / "config" / "clients" / "mammouth")},
}

# Variable d'environnement -> clé au coffre DPAPI, résolue AU LANCEMENT.
# C'est ce qui permet au secret de ne toucher AUCUN disque : ni `.env`, ni fichier de
# config, ni registre — il ne vit que dans la mémoire du process lancé. vibe ne sait
# lire une clé que depuis l'environnement (`ProviderConfig.api_key_env_var` ne porte
# qu'un NOM de variable, et il n'existe aucun mécanisme de commande), donc c'est
# l'appelant qui doit la fournir.
# TOKEN DERIVE, PAS LE MAITRE (mesure 2026-09-02). `FORGE_MCP_TOKEN` est le token
# MAITRE : le videur lui accorde `via=master_token`, ce qui CONSERVE l'agent declare
# dans l'en-tete et son ring. Le distribuer aux clients en fait un passe-partout
# d'identite -- un porteur pouvait se declarer CLAUDE et obtenir ring 1. Chaque
# client porte donc `FORGE_TOKEN_<AGENT>`, apparie a lui seul (`via=token`), ce qui
# rend son ring PROUVE et non emprunte.
SECRET_ENV = {
    "vibe": {
        "MISTRAL_API_KEY": "MISTRAL_API_KEY",
        "FORGE_TOKEN_VIBE": "FORGE_TOKEN_VIBE",
    },
    # mammouth s'authentifie chez son propre fournisseur ; cote Nokido, seul le token
    # du hub le concerne -- et c'est le SIEN, pas le maitre.
    "mammouth": {"FORGE_TOKEN_MAMMOUTH": "FORGE_TOKEN_MAMMOUTH"},
}

ALL = list(INGRESS)


def _load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"enabled": False, "clis": {c: True for c in ALL}, "isolate": {c: False for c in ALL}}


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2), encoding="utf-8")


def _hub_up() -> bool:
    try:
        with urllib.request.urlopen(HUB_HEALTH, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _routing_active(st: dict, cli: str) -> bool:
    return bool(st.get("enabled")) and bool(st.get("clis", {}).get(cli, True))


def cmd_status() -> int:
    st = _load()
    print(json.dumps({"state": st, "hub_up": _hub_up(), "ingress": {c: INGRESS[c][1] for c in ALL}}, indent=2))
    return 0


def cmd_toggle(on: bool, target: str) -> int:
    st = _load()
    if target in ("all", "", None):
        st["enabled"] = on
        st["clis"] = {c: on for c in ALL}
    else:
        if target not in INGRESS:
            print(f"cli inconnu: {target} (attendu: {', '.join(ALL)}|all)")
            return 2
        st["enabled"] = st.get("enabled", False) or on
        st.setdefault("clis", {c: True for c in ALL})[target] = on
        if not on and not any(st["clis"].get(c) for c in ALL):
            st["enabled"] = False
    _save(st)
    print(f"routage Nokido {'ON' if on else 'OFF'} pour {target or 'all'} -> {STATE}")
    return 0


def _inject_env(cli: str, env: dict) -> None:
    """Pose l'environnement propre au CLI : constantes, puis secrets du coffre.

    Best-effort et JAMAIS bloquant : coffre illisible ou clé absente, on laisse
    l'environnement tel quel et le CLI signalera lui-même ce qui lui manque — un
    message du CLI vaut mieux qu'un échec opaque ici.
    On n'écrase jamais une variable déjà présente : l'appelant reste souverain.
    Aucune valeur n'est imprimée, seulement sa longueur.
    """
    for var, val in ALWAYS_ENV.get(cli, {}).items():
        env[var] = val
        print(f"[env] {cli}: {var}={val}", flush=True)

    besoin = SECRET_ENV.get(cli, {})
    if not besoin:
        return
    try:
        import sys as _sys
        if str(ROOT / "app") not in _sys.path:
            _sys.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_secrets import get_secret
    except Exception as e:  # noqa: BLE001
        print(f"[env] coffre illisible ({type(e).__name__}) — secrets non injectés", flush=True)
        return

    for var, cle in besoin.items():
        if env.get(var):
            print(f"[env] {var} déjà dans l'environnement — laissé tel quel", flush=True)
            continue
        try:
            val = get_secret(cle) or ""
        except Exception:  # noqa: BLE001
            val = ""
        if val:
            env[var] = val
            print(f"[env] {var} <- coffre ({len(val)} car)", flush=True)
        else:
            print(f"[env] {var} ABSENT du coffre — le CLI le signalera", flush=True)


def cmd_isolate(on: bool, target: str) -> int:
    """Active/desactive l'isolation worktree par CLI (create au lancement). Defaut OFF."""
    st = _load()
    st.setdefault("isolate", {c: False for c in ALL})
    if target in ("all", "", None):
        for c in ALL:
            st["isolate"][c] = on
    elif target in INGRESS:
        st["isolate"][target] = on
    else:
        print(f"cli inconnu: {target} (attendu: {', '.join(ALL)}|all)")
        return 2
    _save(st)
    print(f"isolation worktree {'ON' if on else 'OFF'} pour {target or 'all'} -> {STATE}")
    return 0


def cmd_launch(cli: str, args: list) -> int:
    if cli not in INGRESS:
        print(f"cli inconnu: {cli} (attendu: {', '.join(ALL)})")
        return 2
    st = _load()
    env = dict(os.environ)
    _inject_env(cli, env)
    route = _routing_active(st, cli)
    var, val, extra = INGRESS[cli]

    if route and var is None:
        print(f"[route] {cli} : pas de mapping env -> lancement natif.", flush=True)
        route = False

    if route:
        if not _hub_up():
            print(f"[route] hub :8766 INJOIGNABLE -> {cli} lancé en NATIF (fallback, pas de casse).", flush=True)
            route = False
        else:
            env[var] = val
            env.update(extra)
            print(f"[route] {cli} -> Nokido ({var}={val})", flush=True)
    else:
        print(f"[route] {cli} -> NATIF (toggle off / non routable)", flush=True)

    exe = shutil.which(cli) or shutil.which(cli + ".cmd") or shutil.which(cli + ".exe") or cli
    # Brique 1 isolation : si l'isolation est ACTIVEE pour ce CLI autonome, s'assurer
    # que son worktree existe (create idempotent) AVANT d'y router (point B). Defaut
    # OFF -> aucun worktree cree -> effet nul ; activable par `isolate on <cli>`.
    try:
        from nokido_agent.tools.forge_worktree import create as _wt_create, AUTONOMOUS as _AUTO
        if cli in _AUTO and st.get("isolate", {}).get(cli):
            _wr = _wt_create(cli)
            if _wr.get("status") in ("created", "exists"):
                print(f"[route] worktree {cli} : {_wr['status']}", flush=True)
            elif _wr.get("error"):
                print(f"[route] worktree {cli} KO (reste canonique) : {_wr['error']}", flush=True)
    except Exception:
        pass
    # Point B isolation (worktree) : si un worktree existe pour ce CLI, l'y lancer
    # (isolation PHYSIQUE par agent = fin du clobber multi-surface, cf forge_worktree).
    # route() retombe sur le canonique tant qu'aucun worktree n'a ete cree -> effet
    # STRICTEMENT NUL et reversible tant que forge_worktree.create(<cli>) n'a pas tourne.
    wt_cwd = None
    try:
        from nokido_agent.tools.forge_worktree import route as _wt_route, ROOT as _WT_CANON
        _r = _wt_route(cli)
        if _r and _r != str(_WT_CANON):
            wt_cwd = _r
            print(f"[route] {cli} -> worktree isole {wt_cwd}", flush=True)
    except Exception:
        pass
    try:
        return subprocess.run([exe, *args], env=env, cwd=wt_cwd).returncode
    except FileNotFoundError:
        print(f"[route] binaire '{cli}' introuvable dans le PATH.", flush=True)
        return 127


def main() -> int:
    a = sys.argv[1:]
    if not a or a[0] in ("status", "-h", "--help"):
        return cmd_status()
    cmd = a[0]
    if cmd == "on":
        return cmd_toggle(True, a[1] if len(a) > 1 else "all")
    if cmd == "off":
        return cmd_toggle(False, a[1] if len(a) > 1 else "all")
    if cmd == "isolate" and len(a) >= 2 and a[1] in ("on", "off"):
        return cmd_isolate(a[1] == "on", a[2] if len(a) > 2 else "all")
    if cmd == "launch" and len(a) >= 2:
        return cmd_launch(a[1], a[2:])
    print("usage: status | on|off [cli|all] | isolate on|off [cli|all] | launch <cli> [args...]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
