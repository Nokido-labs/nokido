"""nokido_claude -- lanceur owner d'une session Claude Code facturee sur les CREDITS API du workspace Nokido (22/10).

Usage (PowerShell, depuis la racine du depot Nokido) :
    & "$env:USERPROFILE\\miniforge3\\python.exe" tools\\nokido_claude.py [arguments de claude, ex. --resume]

Mesure 22/10 : les 100 $ de l'organisation sont des credits PROMOTIONNELS qui s'appliquent a « Agent SDK, API, API
Batch, Playground et Agents geres », pas a Claude Code connecte par `/login` Console (« Credit balance too low », solde
achete 0 $). `claude -p` lance avec la cle du workspace Nokido, lui, a ete debite sur ces credits. Ce lanceur demarre
donc `claude` avec cette cle (ANTHROPIC_API_KEY_ORG au coffre), posee dans l'environnement du SEUL processus lance :
rien sur disque, rien dans l'environnement permanent, une rotation est prise au lancement suivant. Meme table figee que
l'executeur CLAUDE_HEADLESS (forge_cli_harness, agent `claude_api`) : une seule source pour la cle.
Sans cle au coffre, le lanceur REFUSE (code 2) : `claude` partirait sur la connexion Max, ce qu'il ne faut pas confondre.
"""
from __future__ import annotations

__FORGE_COLOR__ = "interface/lanceur_client : lanceur owner de Claude Code sur les credits API du workspace Nokido"

import json
import os
import subprocess
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from nokido_agent.app.forge_cli_harness import agent_bin, jeton_mcp  # noqa: E402

CLE = "ANTHROPIC_API_KEY"


def environnement(base=None) -> dict:
    """L'environnement du processus claude : celui du lanceur, plus la cle API du workspace lue au coffre (si presente).
    Un jeton OAuth herite (ANTHROPIC_AUTH_TOKEN) est retire : il primerait sur la cle."""
    env = dict(os.environ if base is None else base)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env.update(jeton_mcp("claude_api"))
    # Economie de contexte (mesure 22/10) : sur cle API le cache tombe a 5 min (Max : 1 h) et le contexte montait a
    # 785 k tokens -- 0,31 $ de relecture par tour, ~3,90 $ de reecriture apres une pause. Un reglage explicite gagne.
    env.setdefault("ENABLE_PROMPT_CACHING_1H", "1")
    env.setdefault("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "200k")
    return env


def commande(argv) -> list:
    return [agent_bin("claude_api")] + list(argv)


def _tour(message, extra, session_id, env) -> dict:
    """Un tour : `claude -p` en JSON, repris sur la session precedente. Rend le JSON, ou un dict d'erreur.
    Livre par CLAUDE_HEADLESS (279044b7c) ; Desktop 22/10 : lecture en UTF-8 (cp1252 par defaut sous Windows)."""
    cmd = commande(["-p", message, "--output-format", "json"] + extra)
    if session_id:
        cmd += ["--resume", session_id]
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        return {"is_error": True, "result": f"lancement impossible : {e}"}
    try:
        data = json.loads(r.stdout)
    except (ValueError, TypeError):
        return {"is_error": True, "result": (r.stdout or r.stderr or f"sortie illisible (rc={r.returncode})").strip()}
    return data if isinstance(data, dict) else {"is_error": True, "result": str(data)}


def boucle(argv) -> int:
    """Boucle interactive au-dessus de `claude -p` : un tour par ligne, session reprise par --resume.
    Pourquoi (Console 22/10) : le credit promo couvre l'Agent SDK (claude -p), PAS Claude Code interactif."""
    env = environnement()
    if not env.get(CLE):
        print("[nokido_claude] cle ANTHROPIC_API_KEY_ORG introuvable au coffre : lancement REFUSE "
              "(claude partirait sur la connexion Max)", file=sys.stderr)
        return 2
    extra = list(argv)
    if "--permission-mode" not in extra:
        extra += ["--permission-mode", "acceptEdits"]
    session_id, cumul = None, 0.0
    while True:
        try:
            message = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if message == "/exit":
            return 0
        if not message:
            continue
        try:
            data = _tour(message, extra, session_id, env)
        except KeyboardInterrupt:
            print("[tour interrompu] la session continue ; /exit pour quitter")
            continue
        if data.get("is_error") or data.get("api_error_status"):
            print(data.get("result") or json.dumps(data, ensure_ascii=False))
            continue
        session_id = data.get("session_id") or session_id
        cout = float(data.get("total_cost_usd") or 0)
        cumul += cout
        print(data.get("result", ""))
        ligne = f"[cout tour {cout:.4f} $ | session {cumul:.4f} $]"
        refus = [d.get("tool_name", "?") for d in data.get("permission_denials") or [] if isinstance(d, dict)]
        if refus:
            ligne += " refus : " + ", ".join(refus)
        print(ligne)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--boucle" in args:
        args.remove("--boucle")
        return boucle(args)
    env = environnement()
    if not env.get(CLE):
        print("[nokido_claude] cle ANTHROPIC_API_KEY_ORG introuvable au coffre : lancement REFUSE "
              "(claude partirait sur la connexion Max)", file=sys.stderr)
        return 2
    print("[nokido_claude] session claude sur la cle API du workspace Nokido (credits API) ; "
          "Claude Code peut demander une fois d'approuver l'usage de la cle.", file=sys.stderr)
    return subprocess.call(commande(args), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
