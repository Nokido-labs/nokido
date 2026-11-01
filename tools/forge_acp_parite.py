#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_acp_parite.py -- releve de parite ACP des CLI (T1, etude interface unifiee §4 bis).

REUTILISE ACPClient (aucun second client). Pour chaque agent : initialize puis session/new,
JAMAIS session/prompt (zero cout modele). On consigne ce que l'agent REPOND ; un champ non
repondu vaut None (jamais un « false » suppose). Agent introuvable -> ABSENT, muet/illisible
-> ILLISIBLE, avec motif. AGY ne parle pas ACP -> HORS_ACP (harness), non tente.

npx : les adaptateurs claude (@agentclientprotocol/claude-agent-acp) et codex
(@agentclientprotocol/codex-acp) s'obtiennent via npx ; rien n'est installe ici. Surcharge :
GEMINI_ACP_CMD / CLAUDE_ACP_CMD / CODEX_ACP_CMD / OPENCODE_ACP_CMD (JSON liste), ex.
CLAUDE_ACP_CMD='["npx","-y","@agentclientprotocol/claude-agent-acp"]'.

Livraison CLAUDE_HEADLESS 717f3abd2 (ROUGE e7a6a09b5), integree par governed_edit (le merge gate ne peut pas
creer de fichier dans tools/ : Permission denied) ; fermeture du client journalisee.
"""
from __future__ import annotations

__FORGE_COLOR__ = "systeme_nerveux/parite ACP des CLI (interface unifiee)"

import getpass
import json
import logging
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path

_tools = Path(__file__).resolve().parent
if str(_tools) not in sys.path:
    sys.path.insert(0, str(_tools))

import forge_acp_client as C  # noqa: E402

AGENTS = ("gemini", "claude", "codex", "opencode", "agy")
TIMEOUT_MAX = 60


def borner_timeout(t) -> float:
    return max(1, min(float(t), TIMEOUT_MAX)) if t else TIMEOUT_MAX


def _get(d, *chemin):
    """Valeur lue ou None si absente (jamais de defaut invente)."""
    for k in chemin:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _introuvable(cmd) -> bool:
    exe = cmd[0]
    return not (shutil.which(exe) or Path(exe).exists())


def sonder(agent: str, cmd=None, timeout=45) -> dict:
    base = {"agent": agent, "statut": None, "motif": None, "cmd": None, "compte": getpass.getuser()}
    if agent == "agy":
        base.update(statut="HORS_ACP", motif="AGY ne parle pas ACP : hors ACP (harness), non tente")
        return base
    timeout = borner_timeout(timeout)
    cmd = list(cmd) if cmd else C._resolve_cmd(agent)
    base["cmd"] = cmd
    if _introuvable(cmd):
        indice = " (adaptateur npx : @agentclientprotocol/claude-agent-acp ou codex-acp ; npx requis)" \
            if agent in ("claude", "codex") else ""
        # introuvable dans le PATH de CE compte (le bac a sable ne voit pas le profil owner) : pas « non installe »
        base.update(statut="ABSENT", motif=f"commande introuvable pour le compte {base['compte']} : {cmd[0]}{indice}")
        return base
    client = C.ACPClient(cmd=cmd, agent=agent)
    res = {}

    def travail():
        try:
            res["init"] = client.initialize()
            res["sid"] = client.session_new()
            res["session"] = client.derniere_session
        except BaseException as exc:  # noqa: BLE001
            res["err"] = f"{type(exc).__name__}: {exc}"

    try:
        client.start()
    except FileNotFoundError as exc:
        base.update(statut="ABSENT", motif=f"lancement impossible : {exc}")
        return base
    except Exception as exc:  # noqa: BLE001
        base.update(statut="ILLISIBLE", motif=f"lancement en echec : {type(exc).__name__}: {exc}")
        return base
    try:
        th = threading.Thread(target=travail, daemon=True)
        th.start()
        th.join(timeout)
    finally:
        try:
            client.close()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).debug("fermeture du client %s en echec (%s)", agent, type(exc).__name__)
    if th.is_alive():
        base.update(statut="ILLISIBLE", motif=f"pas de reponse en {timeout:g}s")
        return base
    if "err" in res:
        base.update(statut="ILLISIBLE", motif=res["err"][:300])
        return base
    init = res.get("init")
    sess = res.get("session") if isinstance(res.get("session"), dict) else {}
    if not isinstance(init, dict):
        base.update(statut="ILLISIBLE", motif="initialize sans resultat objet")
        return base
    base.update(
        statut="OK", motif=None,
        protocolVersion=_get(init, "protocolVersion"),
        loadSession=_get(init, "agentCapabilities", "loadSession"),
        promptCapabilities=_get(init, "agentCapabilities", "promptCapabilities"),
        mcpCapabilities=_get(init, "agentCapabilities", "mcpCapabilities"),
        authMethods=_get(init, "authMethods"),
        sessionId=res.get("sid"),
        modes=_get(sess, "modes"),
        models=_get(sess, "models"),
    )
    return base


def tableau(rapports) -> str:
    def f(v):
        return "?" if v is None else json.dumps(v, ensure_ascii=False) if not isinstance(v, bool) else str(v).lower()

    def pc(r, k):
        p = r.get("promptCapabilities")
        return f(p.get(k)) if isinstance(p, dict) else "?"

    L = ["| agent | statut | proto | loadSession | image | audio | embeddedCtx | mcp | auth | modes | models | motif |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rapports:
        modes = _get(r, "modes", "availableModes")
        models = _get(r, "models", "availableModels")
        auth = r.get("authMethods")
        L.append("| " + " | ".join([
            r["agent"], r["statut"], f(r.get("protocolVersion")), f(r.get("loadSession")),
            pc(r, "image"), pc(r, "audio"), pc(r, "embeddedContext"),
            f(r.get("mcpCapabilities")),
            str(len(auth)) if isinstance(auth, list) else "?",
            str(len(modes)) if isinstance(modes, list) else "?",
            str(len(models)) if isinstance(models, list) else "?",
            (r.get("motif") or "").replace("|", "/"),
        ]) + " |")
    return "\n".join(L)


def ecrire_mesure(doc: dict, racine: Path, stamp: str | None = None) -> Path:
    """docs/mesures/ d'abord ; refuse (compte du bac a sable, WinError 5 mesure le 28/10) -> sandbox/workspace/."""
    nom = f"acp_parite_{stamp or datetime.now().strftime('%Y%m%d')}.json"
    texte = json.dumps(doc, ensure_ascii=False, indent=2)
    try:
        out = racine / "docs" / "mesures" / nom
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(texte, encoding="utf-8")
        return out
    except OSError as exc:
        out = racine / "sandbox" / "workspace" / nom
        print(f"docs/mesures refuse ({type(exc).__name__}) : releve ecrit dans {out}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(texte, encoding="utf-8")
        return out


def main(argv=None) -> int:
    agents = (argv if argv is not None else sys.argv[1:]) or list(AGENTS)
    rapports = [sonder(a) for a in agents]
    print(tableau(rapports))
    out = ecrire_mesure({"date": datetime.now().isoformat(timespec="seconds"), "agents": rapports},
                        _tools.parent)
    print(f"\nJSON : {out}")
    if any(r["statut"] == "ABSENT" and r["agent"] in ("claude", "codex") for r in rapports):
        print("NB : adaptateurs claude/codex via npx (@agentclientprotocol/...) ; npx requis, rien installe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
