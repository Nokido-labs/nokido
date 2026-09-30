#!/usr/bin/env python3
"""forge_tool_gate.py — gate UNIFIÉ des appels d'outils, partagé cross-CLI (Claude/Gemini/Codex).

UN seul cœur de décision pour TOUS les CLI (fin des hooks dupliqués + de la rupture de parité :
Claude était gouverné au tool-call par bash_guard, Gemini PAS du tout). Compose l'existant
(anti-dup) : forge_orchestration_gate.classify (routing dynamique native/local/deport/cloud) +
forge_videur.resolve_identity (ring) + denylist secrets/destructif (façon bash_guard L1).

GOUVERNANCE GRADUÉE (directive user : « affiner SANS bloquer les flux ni baisser l'intelligence,
mode dynamique, perf locale > tokens ») :
  - block   : SEULEMENT secrets exfil / destructif (rm -rf, format…). Fail-closed minimal, partout.
  - deport  : router vers l'équivalent HUB (gouverné + RAG warm + SearXNG souverain). Enforcement
              gradué par le shim : Gemini = excludeTools (dur) ; Claude = nudge additionalContext
              (NON bloquant — préserve le flux + l'intelligence).
  - native  : défaut. Le CLI le fait (rapide, local, 0 token). On ne déporte QUE si gain clair.

DYNAMIQUE : web/search -> deport souverain (toujours, SearXNG ≠ Google). read/grep -> deport si la
cible est du code Nokido OU gros (gain gouvernance+RAG), sinon natif (perf — pas de latence pour un
read trivial). shell -> natif + denylist. write -> natif (jusqu'à l'edit MCP gouverné) + denylist.

Résilient : tout import/erreur -> fallback ALLOW (jamais casser le flux d'un CLI). Hook entry: lit un
JSON stdin {cli, agent, tool_name, tool_input} -> écrit la décision au format du CLI. Exit 0 toujours.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : gate unifie des appels d'outils cross-CLI"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

# nom d'outil (toutes variantes CLI) -> kind canonique
_TOOL_KIND = {
    "google_web_search": "web", "web_fetch": "web", "websearch": "web", "webfetch": "web",
    "web_search": "web", "googlewebsearchtool": "web", "webfetchtool": "web",
    "read_file": "read", "read": "read", "readfile": "read", "list_directory": "read",
    "ls": "read", "lstool": "read", "readfolder": "read", "readfiletool": "read",
    "grep": "search", "grep_search": "search", "search_file_content": "search",
    "glob": "search", "findfiles": "search", "greptool": "search", "globtool": "search",
    "run_shell_command": "shell", "bash": "shell", "shell": "shell", "powershell": "shell",
    "shelltool": "shell",
    "write_file": "write", "write": "write", "replace": "write", "edit": "write",
    "writefiletool": "write", "edittool": "write",
    # Agent(Explore)/Task = fan-out recon CLOUD (Claude facturé) -> à capter (cf. fuite 92k tokens)
    "task": "recon_agent", "agent": "recon_agent", "dispatch_agent": "recon_agent",
    "explore": "recon_agent",
}

# DÉPORT : kind -> tool HUB équivalent (le « target »)
_DEPORT_TARGET = {
    "web": "hub:web_search/crawl (SearXNG souverain, pas Google)",
    # Audit de prompts 26/09 : le hub `read` n'a PAS de fenetre (action=file rend le fichier entier).
    "read": "hub:read_function_body (une fonction) / get_file_skeleton (la structure) ; une plage : Read offset/limit",
    "search": "hub:query (FTS5) / rag (1024D warm)",
    "recon_agent": "hub:forge_deep_explore / forge_local_explore (recon LOCALE souveraine, 0 token cloud)",
}

# BLOCK : secrets exfil + destructif (façon bash_guard L1, minimal — on ne bloque QUE le clair-danger)
# 3e membre = KINDS ou la regle s'applique. Le texte scanne est la concatenation de
# TOUS les arguments (`_args_text`), donc pour un write il inclut le CORPS ecrit :
# une regle de COMMANDE appliquee la-dessus juge de la prose. Cf. la 3e regle.
_DENY = [
    (re.compile(r"\brm\s+-rf\b|\bdel\s+/[fsq]\b|format\s+[a-z]:|mkfs|drop\s+database", re.I), "destructif",
     ("shell", "write", "read")),
    # `\b...\b` (mesure 2026-09-28) : sans bornes, le verbe se trouvait DANS un mot
    # (« catégorie », « vérification », « détail », `ModuleType`) et un nom en `_token`
    # sur la même ligne suffisait à refuser une écriture de prose. Le verbe reste
    # attrapé en chemin ou avec extension (`/bin/cat`, `cat.exe`).
    (re.compile(r"\b(cat|type|more|head|tail|get-content)\b[^\n]*(\.env|id_rsa|\.pem|credentials|_secret|_token|\.key)", re.I), "lecture secret",
     ("shell", "write", "read")),
    # `(?<![.\w])` : ne viser que la COMMANDE `env`, jamais l'EXTENSION `.env`.
    # Mesure 2026-07-24 : `\benv\b` faisait bloquer toute mention d'un chemin
    # `Nokido.env` — donc lire ou corriger un commentaire dans ce fichier devenait
    # impossible, alors qu'aucun secret n'était dumpé. La lecture réelle d'un `.env`
    # reste bloquée par la règle « lecture secret » juste au-dessus, qui exige un
    # verbe (cat/type/more/head/tail/get-content) : c'est elle qui protège, pas celle-ci.
    # Mesure 2026-08-02 : le meme motif, applique au CONTENU d'une ecriture, refusait
    # « dump secret/PAT » sur du markdown SANS aucun secret — le mot francais « env »
    # (« variable d env », « dans l env du hub ») suffisait. Ce sont des motifs de
    # COMMANDE, et un write n'execute rien : portee ramenee au shell. Le contenu ecrit
    # reste couvert par `_SECRET_CONTENT` (vraies cles) juste en dessous — c'est LUI
    # qui protege une ecriture, pas une regle ecrite pour une ligne de commande.
    (re.compile(r"(?<![.\w])(env|printenv)\b(\s|$)|gh auth token|git remote (-v|show|get-url)", re.I), "dump secret/PAT",
     ("shell",)),
    (re.compile(r"https?://[^\s/@]+:[^\s/@]*@", ), "URL avec credentials",
     ("shell", "write", "read")),
]
_SECRET_CONTENT = re.compile(r"sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def _args_text(tool_args: dict) -> str:
    if not isinstance(tool_args, dict):
        return str(tool_args)
    return " ".join(str(v) for v in tool_args.values())


def _is_nokido_target(tool_args: dict) -> bool:
    t = _args_text(tool_args).lower()
    return "laforge" in t or "forge_" in t or str(ROOT).lower() in t


# Gate PRESCRIPTIF : détecte un script JETABLE de gestion d'infra (keeper/diagnostic
# docker/searxng) que le client tente de BRICOLER au lieu de déléguer au hub.
_INFRA_HANDROLL = re.compile(
    r"docker\s+(run|start|info|compose)|docker\.wanted|_ensure_running|--ensure-daemon"
    r"|_docker_daemon_up|searxng-laforge|forge_searxng_keeper|forge_docker_agent|wsl\s+--shutdown",
    re.I,
)


def _is_infra_handroll(tool_args: dict) -> bool:
    """Write/Edit d'un script JETABLE (_*.py, tmp_*.py, C:/tmp) qui orchestre docker/
    service lifecycle. Cible le réflexe 'bricoler un keeper' — PAS les keepers canoniques."""
    if not isinstance(tool_args, dict):
        return False
    path = str(tool_args.get("file_path") or tool_args.get("path") or "").replace("\\", "/").lower()
    throwaway = bool(re.search(r"/(_|tmp_)[^/]*\.py$", path)) or "c:/tmp" in path or "/tmp/" in path
    return throwaway and bool(_INFRA_HANDROLL.search(_args_text(tool_args)))


def _is_nokido_path(tool_args: dict) -> bool:
    """Chemin cible sous le dépôt Nokido (PATH-aware, pas le contenu). Scope #4."""
    if not isinstance(tool_args, dict):
        return False
    p = str(tool_args.get("file_path") or tool_args.get("path") or "").replace("\\", "/").lower()
    # Dossier repo PHYSIQUE = "LaForge/" (le rename laforge->nokido est logique, pas le dir).
    # On garde les variantes nokido/ pour un futur rename de dir. Exempte sandbox/ (scratch).
    in_repo = ("script python ia/laforge/" in p) or ("script python ia/nokido/" in p) or ("/nokido/" in p)
    code_dir = bool(re.search(r"/(app|tools|proxy_deno)/", p)) and "/sandbox/" not in p
    return (in_repo and code_dir) or bool(re.search(r"(^|/)(app|tools)/forge_[\w]+\.py$", p))


# Fichiers qui DEFINISSENT la politique du client : câblage des hooks, agents,
# permissions. Mesure du 2026-09-13 : le gate refusait bien l'écriture native
# sur le dépôt Nokido, mais laissait passer un `Edit` natif sur
# `~/.claude/settings.json` -- c'est-à-dire sur la liste des hooks qui
# contraignent l'agent. Un agent qui peut réécrire ses propres gardes n'est pas
# gardé ; même forme que l'interrupteur de `bash_guard` posé dans une zone
# inscriptible par le compte qu'il contraint. Directive owner : « plus de
# passe-droit sur la politique mise en place ».
_POLICY_RX = re.compile(
    r"[\\/]\.claude[\\/](settings[^\\/]*\.json|hooks[\\/]|agents[\\/]|plugins[\\/])",
    re.I,
)


def _is_policy_path(tool_args: dict) -> bool:
    """Vrai si la cible définit la politique (hooks/agents/permissions)."""
    cible = str((tool_args or {}).get("file_path") or (tool_args or {}).get("path") or "")
    return bool(_POLICY_RX.search(cible.replace("/", "\\")))


def _enforce_on() -> bool:
    """#4 actif ? FAIL-CLOSED depuis le 2026-09-12 (audit adversarial, etape M1).

    AVANT, trois chemins DESARMAIENT ce gate — celui qui refuse les ecritures
    natives sur le depot :

        env absent (defaut "0")                 -> on passait a la sentinelle
        sentinelle absente                      -> False, desarme
        `except Exception: return False`        -> desarme sur support ILLISIBLE

    Le troisieme est le pire : une ACL, un volume demonte ou une I/O en echec
    n'est pas « pas arme », c'est un INCONNU — et un inconnu qui vaut ALLOW
    fabrique une autorisation a partir d'une panne de lecture. C'est l'inverse
    de l'invariant (`UNKNOWN` n'est jamais `NO`). Le second n'est pas meilleur :
    l'armement dependait d'un fichier NON VERSIONNE de `C:/tmp`, effacable par
    n'importe quel process, sans trace — meme motif que la copie figee
    `C:/tmp/wake_llama_native.py`, qui pilotait le comportement reel.

    DESORMAIS, une seule voie desarme, et elle est EXPLICITE :

        LAFORGE_THIN_CLIENT_ENFORCE=0  -> desarme, volontairement et tracable
        LAFORGE_THIN_CLIENT_ENFORCE=1  -> arme
        absent / illisible / sentinelle absente -> ARME

    La sentinelle historique n'est plus lue : elle ne pouvait qu'affaiblir.
    Fige par `tests/nr/test_tool_gate_armement_failclosed_nr.py`.
    """
    brut = os.environ.get("LAFORGE_THIN_CLIENT_ENFORCE")
    if brut is not None and brut.strip() == "0":
        return False
    return True


def _denylist(kind: str, tool_args: dict) -> str | None:
    txt = _args_text(tool_args)
    for pat, why, kinds in _DENY:
        if kind in kinds and pat.search(txt):
            return why
    if kind == "write":
        content = tool_args.get("content", "") if isinstance(tool_args, dict) else ""
        if _SECRET_CONTENT.search(str(content)):
            return "secret dans le contenu écrit"
    return None


# ---------------------------------------------------------------------------
# IDENTITE DECLAREE vs AUTORITE (P0b, 2026-09-07)
#
# CE QUI A ETE MESURE. `_resolve_ring` faisait `int(resolve_identity(agent))`,
# or `resolve_identity` rend un DICT : `int(dict)` leve TypeError, l'except
# l'avalait, et la fonction rendait 3 pour TOUT LE MONDE -- y compris un nom
# d'agent invente. Prouve a l'oracle : resolve_identity('CLAUDE') rend
# {'ring': 4, 'via': 'header'} et _resolve_ring('N_IMPORTE_QUOI') rend 3.
#
# CE QUE CE DEFAUT FAIT, ET CE QU'IL NE FAIT PAS. Il n'accorde AUCUN droit :
# aucune branche de `decide()` ne compare le ring (0 comparaison dans tout ce
# fichier). En revanche le ring part vers `forge_orchestration_gate.classify`,
# qui ne l'examine QUE pour `ring == 0` = « LOCAL OBLIGATOIRE, souverain ».
# Une source qui ne peut produire que 3 rend donc cette garantie de
# souverainete INATTEIGNABLE, et fait choisir le modele pour un ring fictif.
#
# POURQUOI ON NE « CORRIGE » PAS EN LISANT ident['ring']. Ce serait juste
# syntaxiquement et faux architecturalement : `_resolve_ring` n'a que le NOM
# declare de l'appelant, aucun credential. Le videur rendrait donc via=header
# et le plancher anti-spoof, soit 4 -- jamais 0. La souverainete resterait
# inatteignable, et on aurait en prime bascule tous les appels sur un ring
# different sans savoir lesquels sont legitimes.
#
# LA REGLE. Une identite DECLAREE ne decide jamais ; seule une identite
# ETABLIE par un credential le peut. Tant que le credential n'arrive pas
# jusqu'ici, ce ring reste un heritage NOMME, et l'ecart avec ce que le videur
# observe est MESURE en shadow au lieu d'etre invente.
_RING_DECLARE_LEGACY = 3  # NOT_AUTHORITY -- ne sert a AUCUNE decision de securite
_SHADOW_AUTORITE = "sandbox/authority_shadow.jsonl"


def _observer_identite(agent: str) -> dict:
    """OBSERVATION, jamais autorite. Rend {statut, ring_observe, via, motif}.

    Trois etats et pas deux : OBSERVE / INCONNU / ILLISIBLE. Un resolveur qui
    echoue n'est pas un resolveur qui repond 3 -- c'est precisement la
    confusion qui a produit ce defaut.
    """
    try:
        from nokido_agent.app.forge_videur import resolve_identity  # type: ignore
        ident = resolve_identity(agent or "UNKNOWN")
    except Exception as e:  # noqa: BLE001 - l'echec est NOMME, jamais avale
        return {"statut": "ILLISIBLE", "ring_observe": None, "via": None,
                "motif": "%s: %s" % (type(e).__name__, str(e)[:120])}
    if not isinstance(ident, dict):
        return {"statut": "ILLISIBLE", "ring_observe": None, "via": None,
                "motif": "resolve_identity a rendu %s, pas un dict" % type(ident).__name__}
    brut = ident.get("ring")
    if brut is None:
        return {"statut": "INCONNU", "ring_observe": None, "via": ident.get("via"),
                "motif": "reponse sans champ ring"}
    try:
        return {"statut": "OBSERVE", "ring_observe": int(brut),
                "via": ident.get("via"), "motif": ""}
    except (TypeError, ValueError) as e:
        return {"statut": "ILLISIBLE", "ring_observe": None, "via": ident.get("via"),
                "motif": "ring illisible (%s)" % type(e).__name__}


def _journal_shadow(agent: str, obs: dict) -> None:
    """Consigne l'ecart declare/observe. N'ECHOUE JAMAIS : un journal qui leve
    dans un hook casserait l'appel qu'il observe (paye le 2026-09-06 sur le
    garde RSS du wrapper de job)."""
    try:
        import json as _j
        import time as _t
        from pathlib import Path as _P
        cible = _P(__file__).resolve().parents[1] / _SHADOW_AUTORITE
        cible.parent.mkdir(parents=True, exist_ok=True)
        with cible.open("a", encoding="utf-8") as fh:
            fh.write(_j.dumps({
                "ts": _t.time(),
                "declare": agent or "UNKNOWN",
                "ring_legacy": _RING_DECLARE_LEGACY,
                "statut": obs.get("statut"),
                "ring_observe": obs.get("ring_observe"),
                "via": obs.get("via"),
                "ecart": obs.get("ring_observe") != _RING_DECLARE_LEGACY,
                "credential_recu": False,
                "motif": obs.get("motif", ""),
            }, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001  # muet-ok : l'observation ne casse jamais l'observe
        pass


def _resolve_ring(agent: str) -> int:
    """Ring LEGACY issu d'une identite DECLAREE. **NOT_AUTHORITY.**

    Ne fonde aucune decision de securite et ne doit pas en fonder. Il sera
    retire quand le credential remontera jusqu'ici et qu'une autorite reelle
    (credential -> principal -> agent_id -> policy) prendra sa place.
    """
    _journal_shadow(agent, _observer_identite(agent))
    return _RING_DECLARE_LEGACY


def decide(cli: str, agent: str, tool_name: str, tool_args: dict, ring: int | None = None,
           session: str | None = None) -> dict:
    """Décision unifiée. Retourne {action, target, reason, ring, enforce}."""
    kind = _TOOL_KIND.get((tool_name or "").lower().strip(), None)
    if ring is None:
        ring = _resolve_ring(agent)

    # 1. BLOCK : secrets/destructif (partout, fail-closed minimal)
    if kind:
        why = _denylist(kind, tool_args)
        if why:
            return {"action": "block", "target": None, "reason": f"bloqué ({why})", "ring": ring, "enforce": "hard"}

    # 1.bis GATE PRESCRIPTIF : client qui bricole un keeper/diagnostic infra jetable -> délègue.
    if kind == "write" and _is_infra_handroll(tool_args):
        return {"action": "block", "target": "hub:nokido_ensure_service", "ring": ring, "enforce": "hard",
                "reason": ("403 — gestion d'infra par script jetable refusée (profil CLIENT). "
                           "N'écris PAS de keeper/diagnostic, ne lance PAS docker. Délègue : outil MCP "
                           "`nokido_ensure_service{service, desired_state}` — le Hub gère privilèges/daemons/conteneurs.")}

    # 1.ter CASTRATION #4 (flag LAFORGE_THIN_CLIENT_ENFORCE, OFF par défaut) : deny natif
    # Write/Edit scopé au dépôt Nokido -> route gouvernée. À flipper APRÈS validation.
    if kind == "write" and _is_nokido_path(tool_args) and _enforce_on():
        return {"action": "block", "target": "hub:governed_edit / nokido_ensure_service", "ring": ring,
                "enforce": "hard",
                "reason": ("403 — écriture native sur le dépôt Nokido refusée (profil CLIENT, enforce ON). "
                           "Utilise `governed_edit{path, blocks|content}` (édition gouvernée AST+secret+lock) "
                           "pour le code, `nokido_ensure_service` pour l'infra. PAS de Write/Edit natif sur Nokido.")}

    # 1.quater POLITIQUE — la configuration des gardes n'est pas éditable par
    # l'agent qu'elle contraint. INCONDITIONNEL : pas derrière `_enforce_on()`,
    # parce qu'un garde dont la désactivation est elle-même à portée de
    # l'agent ne protège rien. Le changement de politique est un geste OWNER
    # (édition directe hors session, ou skill `update-config` sous son
    # contrôle) -- il doit rester visible et délibéré, jamais un effet de bord
    # d'une tâche en cours.
    if kind == "write" and _is_policy_path(tool_args):
        return {"action": "block", "target": "owner", "ring": ring, "enforce": "hard",
                "reason": ("403 — écriture native sur la POLITIQUE (hooks / agents / "
                           "permissions) refusée. Un agent ne réécrit pas les gardes qui "
                           "le contraignent. Demande le changement à l'owner, en nommant "
                           "le fichier, la ligne et la raison.")}

    # 2. DÉPORT souverain : web/search/read selon politique dynamique
    if kind == "web":
        return {"action": "deport", "target": _DEPORT_TARGET["web"], "ring": ring, "enforce": "hard",
                "reason": "souveraineté : SearXNG/crawl du hub au lieu de Google"}
    if kind in ("read", "search", "recon_agent"):
        if kind == "recon_agent":
            # RÈGLE OWNER DU 2026-09-06, SANS EXCEPTION : un sous-agent se déporte en JOB
            # DÉTACHÉ NOKIDO (`run action=run_job`), jamais en sous-agent Claude.
            #
            # L'ancienne règle ne captait que les sous-types de recon (explore /
            # general-purpose / plan) et laissait passer « les sous-agents spécialisés ».
            # C'était une échappatoire, et elle a été empruntée le jour même : un
            # Agent(subagent_type="claude") lancé pour une simple attente de CI suivie
            # d'un push. Refusé au premier essai en general-purpose, il est passé en
            # claude -- même travail, même coût cloud, étiquette différente. Un garde
            # qu'on franchit en renommant son intention ne garde rien.
            #
            # Ce qu'il faut faire à la place, et qui existe déjà :
            #   run action=run_job script=tools/mon_script.py     (détaché, 0 token cloud)
            #   run action=run_job script=tools/forge_job_watch_notify.py --rc le_job.rc
            #                                                    (notifie à la fin)
            # Le job survit au restart du hub, ne consomme aucun jeton de modèle, et son
            # verdict est un fichier (.rc), pas une réponse à interpréter.
            sub = str((tool_args or {}).get("subagent_type", "")).lower().strip()
            return {"action": "block", "target": "hub:run action=run_job", "ring": ring,
                    "enforce": "hard",
                    "reason": (f"sous-agent Claude '{sub or 'defaut'}' REFUSE : "
                               "un sous-agent se deporte en JOB DETACHE Nokido. "
                               "-> run action=run_job script=tools/mon_script.py "
                               "(+ forge_job_watch_notify --rc le_job.rc pour etre notifie). "
                               "Regle owner 2026-09-06, sans exception.")}
        is_lf = _is_nokido_target(tool_args)
        # Coupe-circuit comportemental : Agent(Explore) Nokido = deny direct ; read/search Nokido
        # = nudge tant qu'on est sous le seuil, DENY (hard) au-delà -> force la délégation locale.
        try:
            from nokido_agent.tools.forge_recon_breaker import verdict  # type: ignore
            v, reason, _n = verdict(session or agent, kind, is_lf)
        except Exception:
            v, reason = ("nudge" if (is_lf and kind != "recon_agent") else "allow"), ""
        if v == "deny":
            return {"action": "block", "target": _DEPORT_TARGET.get(kind), "ring": ring,
                    "enforce": "hard", "reason": reason or "recon Nokido plafonnée -> délègue en local"}
        if v == "nudge" or (is_lf and kind in ("read", "search")):
            return {"action": "deport", "target": _DEPORT_TARGET.get(kind), "ring": ring, "enforce": "nudge",
                    "reason": reason or "cible Nokido -> hub (gouverné + RAG warm)"}
        return {"action": "native", "target": None, "ring": ring, "enforce": "none",
                "reason": "recon triviale hors Nokido -> natif (perf)"}
    if kind in ("shell", "write"):
        return {"action": "native", "target": None, "ring": ring, "enforce": "none",
                "reason": f"{kind} natif (denylist OK ; write->edit gouverné quand MCP enregistré)"}

    # 3. Action non-tool / LLM / lourde -> classify() dynamique
    try:
        from nokido_agent.app.forge_orchestration_gate import Action, classify, Lane  # type: ignore
        dec = classify(Action(prompt=_args_text(tool_args), kind=kind or "llm", agent=(agent or "CLAUDE").upper(),
                              ring=ring, est_tokens=len(_args_text(tool_args)) // 4))
        act = "deport" if dec.lane in (Lane.DEPORT.value, Lane.CLOUD.value) else "native"
        return {"action": act, "target": dec.target, "reason": dec.reason, "ring": ring,
                "enforce": "nudge" if act == "deport" else "none", "lane": dec.lane}
    except Exception as e:  # noqa: BLE001 - fallback ALLOW (jamais casser le flux)
        return {"action": "native", "target": None, "ring": ring, "enforce": "none",
                "reason": f"fallback natif (gate indispo: {str(e)[:50]})"}


def _emit_claude(d: dict) -> dict:
    """Format hook PreToolUse Claude : block=deny ; deport=nudge additionalContext (NON bloquant)."""
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    if d["action"] == "block":
        out["hookSpecificOutput"]["permissionDecision"] = "deny"
        out["hookSpecificOutput"]["permissionDecisionReason"] = d["reason"]
    elif d["action"] == "deport":
        # nudge non bloquant : on injecte le conseil, on laisse passer (préserve flux+intelligence)
        out["hookSpecificOutput"]["additionalContext"] = f"[forge-tool-gate] DÉPORT conseillé -> {d['target']} ({d['reason']})"
    return out


def _emit_gemini(d: dict) -> dict:
    return {"status": "blocked" if d["action"] == "block" else "approved",
            "action": d["action"], "target": d.get("target"), "reason": d["reason"]}


# ── GEN-3 du Transient Spine : ADMETTRE, sans executer ni reserver ─────────
# Trois mesures du 2026-09-17 fixent ce perimetre, et aucune ne vient du plan :
#
#   1. `route_subtask` appelle `router_call`, donc un LLM. Ce n'est pas un
#      routeur generique de workers. Aucun appel LLM avant GEN-6 -- cette
#      fonction n'importe donc aucun routeur d'intelligence.
#   2. `forge_lane_admission.check_ressources(heavy=True)` n'est PAS une
#      lecture : en saturation il appelle `_try_reserve()`, qui peut ARRETER
#      Ollama, llama-server ou des conteneurs. Une observation ne doit jamais
#      avoir ce pouvoir -- une intention en produit deja DEUX par double
#      cablage. D'ou une abstention DECLAREE, jamais une ignorance.
#   3. `decide()` appelle `forge_recon_breaker.verdict()`, un coupe-circuit a
#      SEUIL. La rappeler pour admettre ferait avancer ce compteur une seconde
#      fois. On REUTILISE donc la decision de policy quand elle existe, et on
#      dit laquelle des deux voies on a prise.
#
# ACCEPTED signifie « admissible dans l'etat mesure a cet instant ». Cela ne
# signifie PAS qu'une ressource lui est reservee : entre cette decision et un
# futur dispatch, la capacite peut changer. La reservation appartient au
# dispatch, donc a une generation ulterieure, qui devra re-verifier.
try:  # source unique du schema ; repli litteral pour ne pas alourdir le hook
    from forge_m2m_protocol import _SCHEMA_TRANSIENT as _SCHEMA_ATTENDU
except Exception:  # noqa: BLE001
    _SCHEMA_ATTENDU = "nokido.transient.v1"


def admettre_transient(transient: dict, policy: dict | None = None) -> dict:
    """Rend une decision d'admission. **N'EXECUTE RIEN, NE RESERVE RIEN.**

    Sortie : `decision` (ACCEPTED | REJECTED | UNKNOWN), `reason`,
    `destination`, `policy_source` (FOURNIE | RECALCULEE), `policy_decision`,
    `resource_state`, `resource_reason`.

    Aucun champ n'est ajoute « parce qu'il serait utile » : chacun porte une
    information reellement disponible.

    Verrouille par tests/nr/test_transient_gen3_admission_nr.py.
    """
    if not isinstance(transient, dict) or transient.get("schema") != _SCHEMA_ATTENDU:
        return {
            "decision": "REJECTED",
            "reason": "transient invalide : schema attendu %r" % _SCHEMA_ATTENDU,
            "destination": "AUCUNE",
            "policy_source": "AUCUNE",
            "resource_state": "NON_CONSULTE",
            "resource_reason": "rien a admettre",
        }

    src = transient.get("source") or {}
    # La ressource n'est PAS consultee, et on dit pourquoi : une abstention
    # muette ne se distingue pas d'un oubli.
    ressource = {
        "resource_state": "NON_CONSULTE",
        "resource_reason": (
            "check_ressources(heavy=True) peut ARRETER des services via "
            "_try_reserve ; heavy=False n'observe rien. La capacite se verifie "
            "au dispatch, pas a l'admission."),
    }

    policy_source = "FOURNIE"
    if policy is None:
        policy_source = "RECALCULEE"
        try:
            policy = decide(
                "",                                   # `cli` n'est pas lu par decide
                str(src.get("producer") or "UNKNOWN"),
                str(src.get("method") or ""),
                transient.get("payload") or {},
                None,
                transient.get("correlation_id"),
            )
        except Exception as e:  # noqa: BLE001
            # Une policy en panne ne fabrique pas une autorisation.
            return {
                "decision": "UNKNOWN",
                "reason": "policy indisponible : %s" % str(e)[:120],
                "destination": "UNKNOWN",
                "policy_source": policy_source,
                "policy_decision": None,
                **ressource,
            }

    action = str((policy or {}).get("action") or "")
    cible = (policy or {}).get("target")
    if action == "block":
        decision, destination = "REJECTED", (cible or "AUCUNE")
    elif action == "deport":
        decision, destination = "ACCEPTED", (cible or "UNKNOWN")
    elif action == "native":
        decision, destination = "ACCEPTED", "native"
    else:
        # Verdict non reconnu : UNKNOWN, jamais un ACCEPTED par optimisme.
        decision, destination = "UNKNOWN", "UNKNOWN"

    return {
        "decision": decision,
        "reason": (policy or {}).get("reason") or "",
        "destination": destination,
        "policy_source": policy_source,
        "policy_decision": policy,
        **ressource,
    }


# ── GEN-2 du Transient Spine : OBSERVER, et rien d'autre ───────────────────
_JOURNAL_TRANSIENT_DEFAUT = os.path.join("sandbox", "transient_observations.jsonl")


def _chemin_journal_transient() -> str:
    """Surchargeable par `LAFORGE_TRANSIENT_JOURNAL`.

    Un NR doit pouvoir mesurer le CABLAGE sans dependre des ACL du compte qui
    joue les tests : sans cette surcharge, « le journal n'existe pas » ne se
    distinguerait pas de « le compte n'a pas le droit d'ecrire ».
    """
    surcharge = os.environ.get("LAFORGE_TRANSIENT_JOURNAL")
    if surcharge:
        return surcharge
    return str(Path(__file__).resolve().parents[1] / _JOURNAL_TRANSIENT_DEFAUT)


def _observer_transient(data: dict) -> None:
    """Normalise l'evenement et le journalise. **AUCUN autre effet.**

    La chaine s'arrete ICI : pas de routeur, pas de worker, pas de swarm, pas de
    reinjection. L'observation a lieu APRES la decision et ne peut pas la
    changer -- on observe un organe qui fonctionne, on ne le remplace pas pour
    apprendre a le regarder.

    N'ECHOUE JAMAIS. Un journal qui leve tuerait l'appel qu'il observe : paye le
    2026-09-06 sur le garde RSS du wrapper de job, mort en ecrivant sa propre
    trace, apres avoir tue son enfant et AVANT d'ecrire le code de retour -- le
    job est reste « running » a vie. Une observation absente laisse donc la
    decision EXACTEMENT ce qu'elle etait : l'absence d'observation n'est pas une
    permission.

    Verrouille par tests/nr/test_transient_gen2_cablage_nr.py.
    """
    try:
        racine = Path(__file__).resolve().parents[1]
        for _p in (str(racine), str(racine / "app")):
            if _p not in sys.path:
                sys.path.insert(0, _p)
        from forge_m2m_protocol import normaliser_transient
        transient = normaliser_transient(data)
        if not transient:
            return
        cible = Path(_chemin_journal_transient())
        cible.parent.mkdir(parents=True, exist_ok=True)
        with cible.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(transient, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        # muet-ok : l'observation ne casse jamais l'observe.
        pass


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # fail-open
    cli = (data.get("cli") or "claude").lower()
    session = data.get("session_id") or data.get("transcript_path") or data.get("agent")
    d = decide(cli, data.get("agent", "UNKNOWN"),
               data.get("tool_name") or data.get("tool", ""),
               data.get("tool_input") or data.get("args") or {},
               data.get("ring"), session)
    # L'observation vient APRES `decide` et AVANT l'emission : elle voit tout ce
    # qu'il faut (surface, methode, charge, session) et ne peut rien changer.
    _observer_transient(data)
    out = _emit_gemini(d) if cli == "gemini" else _emit_claude(d)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
