"""nokido_headless -- facade UNIQUE pour lancer claude / agy / opencode / vibe en sous-processus depuis n'importe quel CLI.

Usage : nokido_headless.py <claude|agy|opencode|vibe> --prompt-file F [--provenance P] [--cwd D]
                           [--timeout S] [--taille S|M|L]

POURQUOI : un point d'entree UNIQUE, appele par n'importe quel CLI (Claude Code, Gemini, Cline,
Copilot, l'executeur Nokido lui-meme), pour lancer un agent CLI en sous-processus avec une
IDENTITE et une PROVENANCE declarees.

CE QUI EST REUTILISE (anti-dup -- la facade ne REIMPLEMENTE rien) :
- la config MCP claude et les arguments `claude -p` : `forge_task_executor._config_mcp_claude`
  et `_args_claude` -- le MEME couple que l'executeur emploie (worktree TEMPORAIRE, nettoye
  apres le run : le worktree de l'agent n'est jamais pollue) ;
- la regle de provenance : `_provenance_valide` (majuscules, [A-Z0-9_] SEULEMENT) ;
- les drapeaux d'agy (`_agy_permission_args`, `_effort_agy`), de vibe (`_args_vibe`,
  `_config_mcp_vibe`) et d'opencode (`_config_opencode_instance`, `_jeton_opencode_instance`) ;
- la resolution des binaires : `_bin_agy` (LAFORGE_AGY_BIN), `_bin_vibe` (LAFORGE_VIBE_BIN),
  `_bin_opencode` (LAFORGE_OPENCODE_BIN / appdata / PATH) ;
- le cout d'un tour : `_cout_claude` ;
- le lancement, les secrets et le caviardage : `nokido_agent/app/forge_cli_harness.py`
  (`harness_for`, `jeton_mcp`). Aucun secret en argument, sur disque ni dans la sortie.

SECURITE (bloquant) : `--provenance` part dans la COMMANDE `headersHelper`, executee par un SHELL.
Un caractere hors [A-Z0-9_] (`&`, `"`, `|`, `;`, espace, backtick, `$()`, redirection) y est une
INJECTION DE COMMANDE. La provenance est donc VALIDEE a l'ENTREE (majuscules) et REFUSEE (rc 2)
sinon -- jamais « corrigee » en silence, jamais ecrite dans la commande.

SORTIE : UNE ligne JSON {agent, provenance, rc, sortie_tronquee, sortie_complete_fichier, cout_usd}.
rc : 2 = usage / agent inconnu / provenance refusee / taille inconnue ; code du CLI sinon ;
rc inconnu = 1, jamais 0.

ECARTS RESTANTS (documentes, mesures -- ils ne sont pas des defauts) :
- claude : le prompt part sur stdin (comme `claude -p`) ; la config MCP vit dans un repertoire
  TEMPORAIRE nettoye apres le run ; `--taille` porte le modele et le nombre de tours ;
- agy : la facade n'ajoute PAS la consigne « ni git add ni git commit » de l'executeur -- le
  prompt est celui du fichier fourni, mot pour mot ; `--taille` ne s'applique pas (l'executeur
  garde ses propres bornes) ;
- vibe : la config MCP est ecrite dans le `--cwd` (l'executeur l'ecrit dans SON worktree) et
  n'ecrase jamais une config ecrite a la main ; la provenance n'y est pas portee (l'en-tete
  d'identite y est fixe) ;
- opencode : l'executeur pilote OpenCode par ACP (`opencode acp`, multi-tours, repli quota,
  changement de modele) ; la facade parle le CLI `opencode run` (UN tour, modele pris dans la
  config d'instance). Meme instance, meme config MCP, meme jeton, meme binaire.
"""
from __future__ import annotations

__FORGE_COLOR__ = "interface/lanceur_client : facade unique de lancement headless claude/agy/opencode/vibe (provenance)"

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
for _p in (str(_RACINE), str(_RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

AGENTS = ("claude", "agy", "opencode", "vibe")
_IDENTITE_HARNESS = {"claude": "claude_api", "agy": "agy", "opencode": "opencode", "vibe": "vibe"}
TAILLES = ("S", "M", "L")
TAILLE_DEFAUT = "M"
TRONC = 4000
TIMEOUT_DEFAUT = 1800


def _executeur():
    """Le module EXECUTEUR -- source UNIQUE des configs MCP, des drapeaux, des binaires et du cout.

    La facade l'IMPORTE, elle ne le recopie pas : c'est ce qui garantit que la config MCP et les
    arguments `claude -p` sont les memes ici et dans l'executeur."""
    import forge_task_executor
    return forge_task_executor


def _provenance(valeur) -> str:
    """Provenance STRICTE (regle unique : celle de l'executeur). ValueError si hors [A-Z0-9_]."""
    prov = str(valeur or "").strip().upper() or "INCONNUE"
    return _executeur()._provenance_valide(prov)


def _taille(valeur) -> str:
    """Taille de tache : S|M|L (defaut M). Une taille inconnue est REFUSEE, jamais rabattue."""
    t = str(valeur or TAILLE_DEFAUT).strip().upper()
    if t not in TAILLES:
        raise ValueError("taille refusee : %r (attendu : %s)" % (valeur, "|".join(TAILLES)))
    return t


def _instance_opencode(T) -> str:
    """Instance OpenCode visee : `LAFORGE_OPENCODE_INSTANCE`, sinon la premiere configuree."""
    nom = str(os.environ.get("LAFORGE_OPENCODE_INSTANCE") or "").strip().upper()
    if nom:
        return nom
    return next(iter(T._instances_opencode()), "OPENCODE")


def _construire(agent: str, prompt: str, prompt_file: str, cwd: str, prov: str, taille: str,
                escalade=None) -> dict:
    """Le plan de lancement : identite, binaire, args, stdin, env_extra, nettoyage.

    Chaque config et chaque drapeau vient de l'EXECUTEUR (`T`) : la facade n'en reecrit aucun."""
    T = _executeur()
    # Levier A : modele + effort viennent de la table UNIQUE ; modele hors quota / escalade sans preuve = ValueError.
    try:
        from nokido_agent.tools import forge_palier_effort as P
    except ImportError:  # repli checkout : tools/ dans sys.path
        import forge_palier_effort as P
    palier =P.resoudre(agent, taille, escalade=escalade)
    if agent == "claude":
        # Worktree TEMPORAIRE : la config MCP y vit le temps du run, puis disparait (le worktree
        # de l'agent n'est jamais pollue). Meme config, meme arguments que l'executeur.
        wt = Path(tempfile.mkdtemp(prefix="nokido_headless_claude_"))
        T._config_mcp_claude(wt, provenance=prov)
        return {"identite": "claude_api", "binaire": None,
                "args": (T._args_claude(wt, taille, escalade) if escalade else T._args_claude(wt, taille)),
                "stdin": prompt,
                "env_extra": {}, "nettoyage": [wt]}
    if agent == "agy":
        return {"identite": "agy", "binaire": str(T._bin_agy()),
                "args": ["--print", prompt[:29000], "--add-dir", cwd,
                         *T._agy_permission_args(), "--output-format", "json",
                         "--effort", palier["effort"]],
                "stdin": None, "env_extra": {}, "nettoyage": []}
    if agent == "opencode":
        inst = _instance_opencode(T)
        cfg = T._config_opencode_instance(inst, None)
        entetes = cfg.setdefault("mcp", {}).setdefault("nokido", {}).setdefault("headers", {})
        entetes["LaForge-Provenance"] = prov
        env_extra = {"OPENCODE_CONFIG_CONTENT": json.dumps(cfg, ensure_ascii=False)}
        jeton = T._jeton_opencode_instance(inst)
        if jeton:
            env_extra["FORGE_TOKEN_%s" % inst] = jeton
        binaire = T._bin_opencode(inst)
        return {"identite": "opencode", "binaire": str(binaire) if binaire else None,
                # 22/10 (audit Antigravity, `opencode run --help`) : sans --auto, une permission d'outil attend une
                # confirmation INTERACTIVE -> headless bloque ; --format json = sortie structuree.
                "args": ["run", "--auto", "--format", "json", prompt[:29000]], "stdin": None,
                "env_extra": env_extra, "nettoyage": []}
    # vibe
    T._config_mcp_vibe(cwd)
    return {"identite": "vibe", "binaire": str(T._bin_vibe()),
            "args": T._args_vibe(cwd, prompt_file), "stdin": None,
            "env_extra": {}, "nettoyage": []}


def _cout(sortie: str, agent: str):
    """`total_cost_usd` d'un tour claude ; None pour les autres agents (jamais 0 = faux)."""
    T = _executeur()
    if agent != "claude":
        return None
    return T._cout_claude(sortie)


def _caviarder(texte: str, agent: str, secrets=()) -> str:
    """Masque les secrets connus dans la sortie (le caviardage est un filet, jamais un prerequis)."""
    try:
        from nokido_agent.app.forge_cli_harness import jeton_mcp
        for v in jeton_mcp(_IDENTITE_HARNESS[agent]).values():
            if v and len(v) >= 6:
                texte = texte.replace(v, "[SECRET]")
    except Exception:  # noqa: BLE001  # muet-ok : le caviardage est un filet, jamais un prerequis
        pass
    for v in secrets or ():
        if v and len(str(v)) >= 6:
            texte = texte.replace(str(v), "[SECRET]")
    return texte


def lancer(agent, prompt_file, provenance=None, cwd=None, timeout=TIMEOUT_DEFAUT,
           taille=TAILLE_DEFAUT, escalade=None) -> dict:
    """Lance l'agent headless et rend son verdict (UNE ligne JSON)."""
    from nokido_agent.app.forge_cli_harness import harness_for
    prov = _provenance(provenance)          # ValueError -> refus (rc 2), rien n'est lance
    tail = _taille(taille)
    try:
        from nokido_agent.tools import forge_palier_effort as P
    except ImportError:  # repli checkout : tools/ dans sys.path
        import forge_palier_effort as P
    P.resoudre(agent, tail, escalade=escalade)   # refus AVANT tout lancement (escalade sans preuve, modele hors quota)
    cwd = str(cwd or os.getcwd())
    prompt = Path(prompt_file).read_text(encoding="utf-8")
    os.environ["NOKIDO_PROVENANCE"] = prov   # les enfants heritent (backend: os.environ + env harness)
    plan = {"nettoyage": []}
    rc, sortie = 1, ""
    h = None
    try:
        plan = _construire(agent, prompt, str(prompt_file), cwd, prov, tail, escalade)
        h = harness_for(plan["identite"], args=plan["args"], cwd=cwd,
                        stdin_devnull=plan["stdin"] is None,
                        binaire=plan["binaire"], env_extra=plan["env_extra"]).start()
        if plan["stdin"] is not None:
            h.send(plan["stdin"], newline=False)
            h.send_eof()
        fin = time.time() + float(timeout)
        morceaux = []
        delai = True
        while time.time() < fin:
            morceaux.append(h.read(0.5))
            if not h.alive():
                morceaux.append(h.read(0.5))
                delai = False
                break
        if delai:
            morceaux.append("\n[nokido_headless] timeout")
        sortie = "".join(morceaux)
        code = getattr(getattr(getattr(h, "_b", None), "proc", None), "returncode", None)
        rc = code if isinstance(code, int) else 1     # rc inconnu = echec, jamais 0
        if delai:
            rc = rc or 124
    except Exception as e:  # noqa: BLE001
        sortie += f"\n[nokido_headless] lancement impossible : {type(e).__name__}: {e}"
        rc = 1
    finally:
        if h is not None:
            try:
                h.stop()
            except Exception:  # noqa: BLE001  # muet-ok : arret au mieux
                pass
        for dossier in plan.get("nettoyage") or []:
            shutil.rmtree(dossier, ignore_errors=True)
    sortie = _caviarder(sortie, agent, (plan.get("env_extra") or {}).values())
    fd, complet = tempfile.mkstemp(prefix=f"nokido_headless_{agent}_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(sortie)
    return {"agent": agent, "provenance": prov, "rc": rc, "sortie_tronquee": sortie[-TRONC:],
            "sortie_complete_fichier": complet, "cout_usd": _cout(sortie, agent)}


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="nokido_headless", description=__doc__)
    ap.add_argument("agent")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--provenance", default=None)
    ap.add_argument("--cwd", default=None)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_DEFAUT)
    ap.add_argument("--taille", default=TAILLE_DEFAUT, choices=list(TAILLES))
    ap.add_argument("--escalade", default=None, choices=["nr_rouge", "juge"],
                    help="effort HAUT seulement apres un echec verifie (NR rouge ou juge)")
    return ap


def main(argv=None) -> int:
    try:
        a = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) and e.code else 2
    if a.agent not in AGENTS:
        print(f"[nokido_headless] agent inconnu : {a.agent} (attendu : {'|'.join(AGENTS)})", file=sys.stderr)
        return 2
    if not Path(a.prompt_file).is_file():
        print(f"[nokido_headless] prompt introuvable : {a.prompt_file}", file=sys.stderr)
        return 2
    try:
        res = lancer(a.agent, a.prompt_file, a.provenance, a.cwd, a.timeout, a.taille, a.escalade)
    except ValueError as e:
        print(f"[nokido_headless] {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, ensure_ascii=False))
    return res["rc"] if res["rc"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
