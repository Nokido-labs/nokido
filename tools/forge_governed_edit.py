#!/usr/bin/env python3
"""forge_governed_edit.py — écriture/édition de fichier GOUVERNÉE (cœur du futur tool MCP `edit`).

Intercepter proprement le WRITE des CLI = NE PAS faire `open('w')` brut (le bypass de gouvernance
qu'on refuse). Ce module COMPOSE la gouvernance EXISTANTE (anti-dup — miroir de forge_git_gate)
AVANT d'écrire :
  1. AST (.py)   : ast.parse -> BLOCK sur SyntaxError (empêche le .py cassé sur disque = la cause
                   du fail-close au reboot, incident 2026-06-16). C'est la valeur #1 d'un write d'agent.
  2. secrets     : regex haut-signal -> BLOCK (le scan complet reste au git-gate commit = défense
                   en profondeur ; ici on coupe la fuite évidente avant qu'elle touche le disque).
  3. tree_locks  : forge_swarm_blackboard -> WARN si un AUTRE agent claim le fichier (anti-clobber)
                   puis claim pour l'agent courant. JAMAIS bloquant (protocole coopératif).
  4. write atomique (tmp + replace).

Destiné à être enregistré comme tool MCP `edit` du hub : TOUS les CLI (gemini/codex/…) écrivent par
CE chemin unique gouverné (excludeTools du write_file natif -> ce tool). Source unique = zéro drift,
même gouvernance que l'Edit natif de Claude (validé par hook PostToolUse). Anti-perte respecté :
on ne bloque QUE syntaxe cassée + secret (jamais une sauvegarde humaine légitime), le reste = warn.
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "immunitaire/guard : ecriture et edition de fichier gouvernees"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# secrets haut-signal (le scan exhaustif = scripts/precommit_secret_scan.py au commit)
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                 # OpenAI-style
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),           # GitHub token
    re.compile(r"AKIA[0-9A-Z]{16}"),                      # AWS access key
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),               # Google API key
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),          # Slack
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{24,}['\"]"),
]


def _scan_secrets(content: str) -> list[str]:
    hits = []
    for pat in _SECRET_PATTERNS:
        m = pat.search(content)
        if m:
            hits.append(pat.pattern[:30])
    return hits


def _ast_check(path: str, content: str) -> str | None:
    if not path.endswith(".py"):
        return None
    try:
        # `compile` et NON `ast.parse` : ce dernier accepte des fichiers que
        # Python REFUSE d'executer -- typiquement `from __future__ import ...`
        # precede d'une autre instruction. Mesure 2026-08-29 : deux fichiers ont
        # ete ecrits avec « AST+secret OK » alors qu'ils ne compilaient pas, et
        # l'erreur n'est apparue qu'a l'execution. Un garde qui valide moins que
        # l'interpreteur laisse passer exactement ce qu'il pretend arreter.
        compile(content, path, "exec")
        return None
    except SyntaxError as e:
        return f"{path}:{e.lineno}: {e.msg}"


# ── Validation NON-Python : le depot n'est pas qu'en .py ─────────────────────
# `forge_git_gate` porte deja `_ps1_parse_gate` et `_ts_parse_gate` -- mais ils
# jugent les fichiers STAGES, au commit. Or un `.ts` casse tue le superviseur et
# un `.ps1` casse tue le demarrage de la flotte AVANT qu'on committe : c'est la
# raison meme pour laquelle l'ecriture des .py etait deja gardee ici.
# Principe repris du gate : outil absent -> skip ANNONCE, jamais silencieux.
_ASCII_STRICT = (".ps1", ".psm1")


def _check_json(path: str, content: str) -> str | None:
    import json as _j
    try:
        _j.loads(content)
    except ValueError as e:
        return f"{path}: JSON invalide -- {e}"
    return None


def _check_yaml(path: str, content: str) -> str | None:
    try:
        import yaml
    except ImportError:
        return None  # skip annonce par _verifier_format
    try:
        list(yaml.safe_load_all(content))
    except Exception as e:  # noqa: BLE001 - toute erreur de parse yaml
        return f"{path}: YAML invalide -- {str(e)[:160]}"
    return None


def _check_toml(path: str, content: str) -> str | None:
    try:
        import tomllib
    except ImportError:
        return None
    try:
        tomllib.loads(content)
    except Exception as e:  # noqa: BLE001
        return f"{path}: TOML invalide -- {str(e)[:160]}"
    return None


def _check_ascii(path: str, content: str) -> str | None:
    """Un .ps1 doit rester ASCII PUR.

    Mesure owner : des tirets cadratins ajoutes dans `nokido_start.ps1` l'ont rendu
    non parsable sous PS 5.1, et ce fichier amorce les 55 services. Le caractere
    fautif est NOMME : sans cela on cherche a l'oeil dans un fichier de 500 lignes.
    """
    for i, ligne in enumerate(content.splitlines(), 1):
        for j, car in enumerate(ligne, 1):
            if ord(car) > 127:
                return (f"{path}:{i}:{j}: caractere non-ASCII U+{ord(car):04X} "
                        f"-- un .ps1 non ASCII casse le demarrage sous PS 5.1")
    return None


_VALIDATEURS = {
    ".json": _check_json, ".yml": _check_yaml, ".yaml": _check_yaml,
    ".toml": _check_toml,
}


def _verifier_format(path: str, content: str) -> str | None:
    """Dispatche vers le validateur du FORMAT. Rend un motif, ou None."""
    bas = (path or "").lower()
    if bas.endswith(".py"):
        return _ast_check(path, content)
    if bas.endswith(_ASCII_STRICT):
        return _check_ascii(path, content)
    for suffixe, valideur in _VALIDATEURS.items():
        if bas.endswith(suffixe):
            return valideur(path, content)
    return None


def _tree_lock_check_and_claim(rel_path: str, agent: str) -> list[str]:
    """Best-effort, JAMAIS bloquant. Warn si un autre agent claim le fichier, puis claim."""
    warns: list[str] = []
    try:
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_swarm_blackboard import apply_fact, read_zone  # type: ignore

        agent_u = (agent or "UNKNOWN").upper()
        try:
            z = read_zone("tree_locks")
            facts = z.get("facts", []) if isinstance(z, dict) else []
        except Exception:
            facts = []
        for f in facts:
            owner = str(f.get("worker_id", "")).upper()
            if owner and owner != agent_u and rel_path in str(f.get("value", "")):
                warns.append(f"{rel_path} déjà claim par {owner} -> collision possible (coordonner)")
        try:
            import asyncio

            asyncio.run(apply_fact(
                "tree_locks", f"{agent_u} edit: {rel_path}",
                key=agent_u.lower(), category="edit_claim", worker_id=agent_u,
            ))
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_governed_edit.py', 179, exc_info=True)
    except Exception as e:  # noqa: BLE001
        warns.append(f"tree_locks indisponible: {str(e)[:60]}")
    return warns


# no_self_score_edit (invariant alignement) : modules-JUGES qui scorent les agents.
# Un agent LLM ne peut pas les editer via governed_edit -> bloque le reward-tampering
# (un agent qui s'auto-favorise en editant son propre score). Override owner :
# LAFORGE_ALLOW_JUDGE_WRITE=1. Source: docs/ALIGNMENT_HOMEOSTAT_ROADMAP.md.
JUDGE_MODULES = (
    "app/forge_trust_score.py",
    "tools/forge_pool_registry.py",
    "app/forge_agents.py",
    "tools/forge_evolutionary_stack.py",
    "app/forge_orchestration_gate.py",
)


#: Registre des tests vus en ECHEC (plugin de tests/conftest.py) et fenetre ou un rouge vaut preuve.
TDD_ROUGES_DEFAUT = ROOT / "sandbox" / "workspace" / "tdd_rouges.jsonl"
TDD_FENETRE_S = 3600.0


def avertissement_tdd(rel: str) -> str | None:
    """Garde TDD « rouge d'abord » (owner 2026-10-16, derogation sur ce fichier « en attendant mieux ») : signale une
    ecriture de code sans test ROUGE recent sur le module. Non bloquante (mesurer son bruit avant d'enforcer).
    Un rouge vaut preuve s'il date de moins de TDD_FENETRE_S et si le fichier de son test NOMME le module."""
    import json as _j
    import time as _t

    chemin = Path(str(rel).replace("\\", "/"))
    if chemin.suffix != ".py" or not ({"app", "tools"} & set(chemin.parts)) or "tests" in chemin.parts:
        return None     # ecrire le TEST est l'etape RED elle-meme ; docs et workflows ne sont pas du code de prod
    module = chemin.stem
    registre = Path(os.environ.get("LAFORGE_TDD_ROUGES") or TDD_ROUGES_DEFAUT)
    try:
        lignes = registre.read_text(encoding="utf-8").splitlines()
    except OSError:  # muet-ok : registre absent ou illisible = aucun rouge connu, donc l'avertissement est LEVE
        lignes = []
    for ligne in reversed(lignes):
        try:
            r = _j.loads(ligne)
            if _t.time() - float(r.get("ts", 0)) > TDD_FENETRE_S:
                continue
            if module in Path(r.get("fichier", "")).read_text(encoding="utf-8", errors="replace"):
                return None
        except (ValueError, OSError):  # muet-ok : ligne ou fichier de test illisible = ce rouge ne prouve rien
            continue
    return "TDD : aucun test ROUGE observe sur %s -- ecrire le test, le voir echouer, puis le code" % rel


# Executeurs qui n'ecrivent JAMAIS l'arbre partage par governed_edit (owner 19/10, vague 0) : OPENCODE_GLM y a
# ecrase forge_token_monitor (681 -> 71 lignes) et forge_llm_usage_adapters (215 -> 22) ; governed_edit vise le
# depot PRINCIPAL alors qu'un executeur ecrit en NATIF dans son worktree. Perimetre owner : OPENCODE_* et
# WORKER_CODE ; les *_DAEMON / *_HEADLESS / HANDOFF_WORKER restent permis tant que leur usage n'est pas verifie.
_EXECUTEURS_HORS_ARBRE_PREFIXES = ("OPENCODE_",)
_EXECUTEURS_HORS_ARBRE = frozenset({"WORKER_CODE"})


def _identites_agents():
    """config/agent_identities.json, ou None s'il est ILLISIBLE (jamais un dict vide pris pour « personne »)."""
    import json as _j

    try:
        return _j.loads((ROOT / "config" / "agent_identities.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        __import__("logging").getLogger(__name__).warning(
            "identites agents ILLISIBLES (%s) : garde arbre partage inoperant", type(e).__name__)
        return None


def _executeur_autonome(agent) -> bool:
    """Vrai si `agent` (nom ou alias, casse ignoree) est un executeur du perimetre owner ET porte
    surface == "autonomous". Identites illisibles -> False : on ne refuse pas sans preuve."""
    idents = _identites_agents()
    if not isinstance(idents, dict) or not agent:
        return False
    cible = str(agent).strip().lower()
    for nom, fiche in (idents.get("agents") or {}).items():
        if not isinstance(fiche, dict):
            continue
        noms = {str(nom).lower()} | {str(a).lower() for a in (fiche.get("aliases") or [])}
        if cible not in noms:
            continue
        canon = str(nom).upper()
        dans_perimetre = canon in _EXECUTEURS_HORS_ARBRE or canon.startswith(_EXECUTEURS_HORS_ARBRE_PREFIXES)
        return dans_perimetre and fiche.get("surface") == "autonomous"
    return False


def governed_write(path: str, content: str, agent: str = "UNKNOWN",
                   allow_create: bool = True, allow_critical: bool = False) -> dict:
    """Écrit `content` dans `path` après gouvernance. Retourne un verdict structuré.

    BLOCK (ok=False) seulement sur : syntaxe .py cassée OU secret détecté. tree_locks = warn.
    """
    p = Path(path)
    if not p.is_absolute():
        p = (ROOT / path)
    try:
        rel = str(p.relative_to(ROOT))
    except ValueError:
        rel = str(p)

    if _executeur_autonome(agent):
        return {"ok": False, "blocked": "arbre_partage", "path": rel,
                "reason": f"executeur autonome ({agent}) : ecris en NATIF dans TON worktree, governed_edit vise "
                          "l'arbre PARTAGE (ecrasements du 19/10) -- ta livraison passe par ta branche"}

    if p.exists() is False and not allow_create:
        return {"ok": False, "blocked": "not_found", "reason": f"{rel} absent et allow_create=False"}

    secrets = _scan_secrets(content)
    if secrets:
        return {"ok": False, "blocked": "secret", "reason": f"secret détecté ({', '.join(secrets)}) -> écriture refusée", "path": rel}

    ast_err = _verifier_format(str(p), content)
    if ast_err:
        return {"ok": False, "blocked": "syntax", "reason": f"format invalide -> écriture refusée (anti fail-close reboot): {ast_err}", "path": rel}

    # CRITICAL_FILES : meme gouverne, le coeur (hub/rbac/mcp_security/web_hub auth/.env) n'est
    # PAS reecrit sans bypass owner explicite. Ferme le trou : governed_edit contournait la
    # protection du tool write (forge_mcp_security.assert_can_write). Source unique = _is_critical ;
    # fail-CLOSED sur la liste connue si l'import casse (un attaquant ne contourne pas en cassant l'import).
    # `allow_critical` est un PARAMETRE, pas seulement une variable d'env.
    # Mesure 2026-08-16 : l'owner a autorise explicitement une ecriture critique et
    # cette autorisation n'avait AUCUN canal — l'env est lue dans le process hub,
    # qu'aucun appel client ne modifie (et la relire ne redescend pas dans un
    # process vivant). Resultat : le correctif d'un incident a du etre applique
    # hors gouvernance, en rejouant AST + ancre + relecture a la main. Un garde
    # dont la seule derogation est inatteignable ne protege pas, il deporte.
    # Le parametre est filtre par le RING cote handler (voir handle_governed_edit) :
    # ici on le tient pour deja autorise, et on le TRACE.
    if allow_critical:
        # Trace dans un JOURNAL fichier, plus sur stderr (2026-09-28). `governed_write`
        # tourne SUR la boucle du hub ; son stderr est un pipe vers le superviseur, qui
        # peut ne pas etre vide : ce `print(flush=True)` a BLOQUE la boucle 60 s et le garde
        # anti-gel a tue le hub (WEDGE KILL 06:23:08, pile dans logs/loop_lag.log). Une
        # derogation qu'on ne peut pas tracer n'est pas accordee.
        try:
            import json as _json_trace
            import time as _time_trace

            with (ROOT / "sandbox" / "governed_edit_critique.jsonl").open(
                    "a", encoding="utf-8") as _f_trace:
                _f_trace.write(_json_trace.dumps(
                    {"ts": _time_trace.time(), "path": rel, "agent": agent,
                     "derogation": "allow_critical"}) + "\n")
        except Exception as _e_trace:  # noqa: BLE001
            return {"ok": False, "blocked": "critical", "path": rel,
                    "reason": f"derogation critique NON tracee ({type(_e_trace).__name__}) "
                              "-> refusee"}
    if not allow_critical and os.environ.get("LAFORGE_ALLOW_CRITICAL_WRITE", "0") not in ("1", "true", "yes"):
        _is_crit = False
        try:
            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_mcp_security import _is_critical as _ic

            _is_crit = bool(_ic(rel))
        except Exception:  # noqa: BLE001 - fail-closed sur la liste connue
            _rn = rel.replace("\\", "/").lower()
            # DUPLICATION DELIBEREE de CRITICAL_FILES : ce repli n'agit que si
            # l'import de `_is_critical` casse — un attaquant ne doit pas
            # ouvrir la porte en cassant l'import. La synchronisation des deux
            # listes est verrouillee par
            # tests/nr/test_critical_files_suit_l_autorite_nr.py.
            _is_crit = any(_rn.endswith(c) for c in (
                "tools/nokido_hub.py", "app/forge_mcp_registry.py", "app/forge_mcp_security.py",
                "app/forge_rbac.py", "app/forge_mcp_rbac.py", "app/forge_opsec.py",
                "app/forge_corrigibility.py", "tools/forge_governed_edit.py",
                "app/web_hub/auth.py", "app/web_hub/app.py", ".env", "nokido.env",
            ))
        if _is_crit:
            return {"ok": False, "blocked": "critical", "path": rel,
                    "reason": f"{rel} est CRITICAL_FILE -> governed_edit refuse "
                              f"(maintenance owner : rappeler avec allow_critical=true, "
                              f"reserve au ring <= 1 et trace)"}

    # no_self_score_edit : aucun agent n'edite un module-juge (anti reward-tampering).
    if os.environ.get("LAFORGE_ALLOW_JUDGE_WRITE", "0") not in ("1", "true", "yes"):
        _jn = rel.replace("\\", "/").lower()
        if any(_jn.endswith(j) for j in JUDGE_MODULES):
            try:
                from nokido_agent.tools.forge_alignment_trace import emit as _atrace
                _atrace(agent, "no_self_score_edit", "deny", rel, "judge module edit blocked")
            except Exception:
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_governed_edit.py', 322, exc_info=True)
            return {"ok": False, "blocked": "judge_module", "path": rel,
                    "reason": f"{rel} = module-JUGE -> no_self_score_edit: agent '{agent}' refuse "
                              f"(anti reward-tampering ; LAFORGE_ALLOW_JUDGE_WRITE=1 pour owner)"}

    warns = _tree_lock_check_and_claim(rel, agent)

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp_gov")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "blocked": "io", "reason": f"écriture échouée: {str(e)[:120]}", "path": rel}

    # RELECTURE OBLIGATOIRE — le verdict porte sur le DISQUE, jamais sur l'intention.
    # Mesure 2026-07-25 : cette fonction a rendu ok avec bytes=5422 sur un original de
    # 5561 alors que `git diff` etait VIDE — l'ecriture avait disparu et `bytes`, calcule
    # depuis `content`, la confirmait faussement. Un rapport qui mesure ce qu'on VOULAIT
    # ecrire ne peut pas detecter une ecriture perdue. On relit et on compare.
    try:
        relu = p.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "blocked": "unverifiable", "path": rel,
                "reason": f"ecrit mais RELECTURE IMPOSSIBLE ({type(e).__name__}) — "
                          f"etat indetermine, ne pas croire au succes: {str(e)[:100]}"}
    if relu != content:
        return {"ok": False, "blocked": "lost_write", "path": rel,
                "reason": f"le disque ne porte PAS le contenu ecrit "
                          f"(attendu {len(content)} car., relu {len(relu)}) — "
                          f"ecriture perdue ou concurrente, RIEN n'est acquis"}

    try:
        from nokido_agent.tools.forge_alignment_trace import emit_introspection
        emit_introspection(
            actor=agent,
            action="governed_write",
            target_module=rel,
            execution_tier="local",
            tokens={"prompt": 0, "completion": 0, "total": 0},
            cost_usd=0.0
        )
    except Exception:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_governed_edit.py', 365, exc_info=True)

    verdict = {"ok": True, "path": rel, "bytes": len(relu.encode("utf-8")), "warnings": warns,
               "verified": "relecture disque identique",
               "note": "AST+secret OK ; tree_lock claim ; contenu RELU verifie ; le git-gate re-scanne au commit"}
    try:  # garde TDD (owner 16/10) : un avertissement, jamais un echec de l'ecriture
        _tdd = avertissement_tdd(rel)
        if _tdd:
            verdict["avertissement_tdd"] = _tdd
    except Exception as _e_tdd:  # noqa: BLE001
        verdict["avertissement_tdd_indisponible"] = type(_e_tdd).__name__
    return verdict


def main(argv: list[str]) -> int:
    import json
    # CLI test : forge_governed_edit.py <path> <agent>  (contenu sur stdin)
    if not argv:
        print("usage: forge_governed_edit.py <path> [agent]   (contenu via stdin)")
        return 0
    path = argv[0]
    agent = argv[1] if len(argv) > 1 else "CLI"
    content = sys.stdin.read()
    print(json.dumps(governed_write(path, content, agent), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
