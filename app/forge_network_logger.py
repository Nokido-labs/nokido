"""
forge_network_logger.py — Bus de logging centralisé Nokido v2.0
================================================================
v2.0 : Utilise forge_mcp_security.audit() comme backend natif
       (mcp_audit.log — append-only, non modifiable par l'IA)
       plutôt qu'une table SQLite séparée.

Avantage : évite les enregistrements côté Electron (pas de tool_search
dans les sessions de monitoring → pas de store sérialisé → pas d'injection).

Canaux loggués :
  STDIO    → échanges Claude Desktop ↔ nokido_mcp_server.py
  HUB      → requêtes HTTP ↔ nokido_hub.py (port 8766)
  CLOUD    → appels LLM sortants (ask_claude, ask_gemini, providers)
  INTERNAL → EventBus, SecretGuard, Sentinel, mode changes

Format ligne mcp_audit.log étendu :
  TIMESTAMP | CHANNEL:TOOL | ARGS_JSON | STATUS
"""

from __future__ import annotations

import ast
import json
import logging
import queue
import re
import threading
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Nokido.NetworkLogger")

ROOT = Path(__file__).resolve().parent.parent

# SSE clients (broadcast en mémoire — pas de DOM Electron)
_SSE_CLIENTS: List[queue.Queue] = []
_SSE_LOCK = threading.Lock()
_HISTORY: List[dict] = []
_HISTORY_LOCK = threading.Lock()
MAX_HISTORY = 500


class NetworkChannel(str, Enum):
    # Canaux entrants (qui appelle le hub)
    STDIO_CLAUDE = "STDIO_CLAUDE"  # Claude Desktop via mcp_stdio_bridge
    HTTP_CLAUDE = "HTTP_CLAUDE"  # Claude Code CLI via MCP Streamable HTTP (owner 29/10 : n'est PAS du stdio)
    GEMINI_OAUTH = "GEMINI_OAUTH"  # Gemini CLI authentifie OAuth Google
    GEMINI_API = "GEMINI_API"  # Gemini via cle API (forge_agent_proxy)
    CLINE_MCP = "CLINE_MCP"  # Cline VS Code extension
    HTTP_DIRECT = "HTTP_DIRECT"  # curl/script direct sans agent identifie
    INTERNAL_HUB = "INTERNAL_HUB"  # Taches internes hub (cron, janitor, inspector)
    # Canaux sortants (hub appelle un provider externe)
    CLOUD_ANTHROPIC = "CLOUD_ANTHROPIC"  # api.anthropic.com
    CLOUD_GEMINI = "CLOUD_GEMINI"  # api.generativelanguage.googleapis.com
    CLOUD_MISTRAL = "CLOUD_MISTRAL"  # api.mistral.ai
    CLOUD_GROQ = "CLOUD_GROQ"  # api.groq.com
    CLOUD_OPENAI = "CLOUD_OPENAI"  # api.openai.com / github models
    CLOUD_OTHER = "CLOUD_OTHER"  # autres providers
    # Legacy (retrocompat)
    STDIO = "STDIO"
    HUB = "HUB"
    CLOUD = "CLOUD"
    INTERNAL = "INTERNAL"


class Direction(str, Enum):
    IN = "IN"
    OUT = "OUT"


def _get_audit():
    """Import lazy de forge_mcp_security.audit (backend natif)."""
    try:
        from nokido_agent.app.forge_mcp_security import audit as _native_audit

        return _native_audit
    except Exception:
        return None


# ── Journal des ACTES (2026-09-25) ──────────────────────────────────────────────────────────
# MESURE : la commande qu'OPENCODE (ring 3) a executee par `run` etait ILLISIBLE partout -- ici
# la charge est coupee a 200 caracteres (l'enveloppe JSON-RPC, AVANT les arguments), puis
# forge_mcp_security.audit coupe chaque valeur a 80 et la ligne a 120 ; execution_traces herite
# de la meme coupe. Le format de l'audit (4 consommateurs) ne bouge pas : pour les seuls outils
# qui AGISSENT, une ligne lisible -- agent, ring, action, extrait CAVIARDE, borne, troncature DITE.
_JOURNAL_ACTES = ROOT / "logs" / "actes_agents.jsonl"
EXTRAIT_ACTE_MAX = 2000
_OUTILS_ACTES = {"run", "governed_edit", "github", "docker_action", "agy_run", "task",
                 "manage_forge_lifecycle", "nokido_ensure_service", "oracle_python_repl",
                 "forge_call_dynamic", "trigger_autonomous_evolution", "dyn_orchestrate"}


_CHAMP_BRUT = r'["\']%s["\']\s*:\s*["\']([^"\']{1,300})'
_CHARGE_ANALYSABLE_MAX = 200_000


def _arguments_appel(charge) -> Optional[dict]:
    """Arguments d'un appel d'outil quelle que soit la forme recue ; None = charge NON analysable.

    Formes REELLES (mesure 2026-09-25) : le hub HTTP passe l'enveloppe JSON-RPC coupee a 800 car.,
    le serveur stdio les arguments NUS coupes a 400, d'autres un repr Python. Une coupe en amont
    rend le JSON incomplet : l'appelant garde alors le texte recu plutot qu'un `{}` muet."""
    if isinstance(charge, str):
        try:
            charge = json.loads(charge)
        except ValueError:
            if len(charge) > _CHARGE_ANALYSABLE_MAX:
                return None
            try:
                charge = ast.literal_eval(charge)
            except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                return None
    if not isinstance(charge, dict):
        return None
    params = charge.get("params") if isinstance(charge.get("params"), dict) else charge
    if isinstance(params.get("arguments"), dict):
        return params["arguments"]
    return {} if ("jsonrpc" in charge or "method" in charge) else charge


def _champ_brut(texte: str, cle: str) -> Optional[str]:
    trouve = re.search(_CHAMP_BRUT % re.escape(cle), texte)
    return trouve.group(1) if trouve else None


def _caviarder(texte: str, outil: str) -> str:
    """Les DEUX jeux de motifs (infrastructure + clefs d'API), fail-closed.

    MESURE 2026-09-25 : `redact_for_log` n'applique que l'infrastructure ; une clef `gsk_` a la forme
    reelle le traversait intacte (et il rend le texte INTACT sur exception). `redact_tool_output` est
    le porteur des deux moities (cf. sa docstring). Sans les motifs de clefs, rien ne s'ecrit en clair."""
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_tool_output
        propre, bilan = redact_tool_output(texte, outil=outil)
    except Exception as exc:  # noqa: BLE001 - un texte non caviarde ne s'ecrit PAS en clair
        return "[CAVIARDAGE INDISPONIBLE : %s -- texte non ecrit]" % type(exc).__name__
    if bilan.get("longueur") and not bilan.get("motifs_clefs_charges", False):
        return "[CAVIARDAGE PARTIEL : motifs de clefs indisponibles -- texte non ecrit]"
    return propre


def _journaliser_acte(tool: str, agent, ring, charge, status) -> None:
    arguments = _arguments_appel(charge)
    forme = "ARGUMENTS"
    if arguments is None:
        # JSON coupe en amont : le texte RECU (caviarde plus bas), jamais un `{}` muet ;
        # governed_edit garde sa regle -- le chemin, jamais le contenu.
        forme, texte = "TEXTE_NON_ANALYSABLE", str(charge)
        arguments = {"action": _champ_brut(texte, "action")}
        if tool == "governed_edit":
            brut = "path=%s (charge non analysable, %d car. recus)" % (_champ_brut(texte, "path"), len(texte))
        else:
            brut = texte
    elif tool == "governed_edit":
        corps = arguments.get("content") or arguments.get("blocks") or ""
        brut = "path=%s (%d car. %s)" % (arguments.get("path"), len(str(corps)),
                                         "blocs" if arguments.get("blocks") else "contenu")
    else:
        cles = ("action", "code", "commands", "script", "path", "script_args", "service",
                "desired_state", "job_id")
        brut = json.dumps({k: arguments[k] for k in cles if k in arguments} or arguments,
                          ensure_ascii=False, default=str)
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_for_log as _scrub
        brut = _caviarder(_scrub(brut, reversible=True), tool)
    except Exception as exc:  # noqa: BLE001 - un acte non caviarde ne s'ecrit PAS en clair
        brut = "[CAVIARDAGE INDISPONIBLE : %s -- extrait non ecrit]" % type(exc).__name__
    _ecrire_acte({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "sens": "APPEL", "agent": agent or "?",
                  "ring": ring, "outil": tool, "action": arguments.get("action"), "statut": status or "OK",
                  "forme": forme, "extrait": brut[:EXTRAIT_ACTE_MAX], "longueur_totale": len(brut),
                  "tronque": len(brut) > EXTRAIT_ACTE_MAX})


def _journaliser_reponse(tool: str, agent, ring, reponse, status, latence_ms) -> None:
    """Ce que le hub a REPONDU a un outil qui agit : caviarde, borne, la coupe DITE.

    La reponse arrive deja coupee par l'appelant (hub HTTP : 800 car.) : `longueur_recue` dit ce qui
    est arrive ICI, jamais la longueur d'origine."""
    brut = str(reponse)
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_for_log as _scrub
        brut = _caviarder(_scrub(brut, reversible=True), tool)
    except Exception as exc:  # noqa: BLE001 - une reponse non caviardee ne s'ecrit PAS en clair
        brut = "[CAVIARDAGE INDISPONIBLE : %s -- reponse non ecrite]" % type(exc).__name__
    _ecrire_acte({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "sens": "REPONSE", "agent": agent or "?",
                  "ring": ring, "outil": tool, "statut": status or "OK", "latence_ms": latence_ms,
                  "reponse": brut[:EXTRAIT_ACTE_MAX], "longueur_recue": len(brut),
                  "tronque": len(brut) > EXTRAIT_ACTE_MAX})


_ACTES_MAX_OCTETS = 20 * 1024 * 1024
# Lectures journalisees (owner 31/10) : la carte d'attention lisait un journal qui ne portait AUCUNE lecture,
# donc elle restait vide en production. Chemin + symbole seulement, jamais le contenu ni la reponse.
_OUTILS_LECTURES_ACTES = {"read", "read_function_body", "get_file_skeleton"}


def _ecrire_acte(acte: dict) -> None:
    """Ajoute une ligne au journal des actes ; un echec d'ecriture est DIT, jamais avale.

    ROTATION (31/10) : le journal pesait 49,6 Mo sans aucune rotation. Au-dela de _ACTES_MAX_OCTETS il passe en
    `.1` (une generation gardee) ; les lecteurs bornes (_dernieres_lignes) n'en lisent que la fin."""
    try:
        _JOURNAL_ACTES.parent.mkdir(parents=True, exist_ok=True)
        try:
            if _JOURNAL_ACTES.stat().st_size > _ACTES_MAX_OCTETS:
                import os as _os  # noqa: PLC0415

                _os.replace(_JOURNAL_ACTES, _JOURNAL_ACTES.with_name(_JOURNAL_ACTES.name + ".1"))
        except OSError:  # muet-ok : journal absent (premiere ligne) ou rotation impossible -> on continue d'ajouter
            pass
        with open(_JOURNAL_ACTES, "a", encoding="utf-8") as f:
            f.write(json.dumps(acte, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("[net_log] acte NON journalise (%s) : %s %s", type(exc).__name__,
                       acte.get("agent"), acte.get("outil"))


def _journaliser_lecture(tool: str, agent, ring, charge) -> None:
    """Une LECTURE (owner 31/10) : chemin + symbole seulement, pour la carte d'attention.

    Jamais le contenu, jamais la reponse (~250 octets par lecture). Charge HTTP coupee en amont (JSON
    incomplet) : les champs sont repris du texte, sinon l'extrait reste vide -- jamais une lecture inventee."""
    arguments = _arguments_appel(charge)
    forme = "ARGUMENTS"
    if arguments is None:
        forme, texte = "TEXTE_NON_ANALYSABLE", str(charge)
        arguments = {k: v for k in ("action", "path", "file_path", "function_name")
                     if (v := _champ_brut(texte, k))}
    extrait = json.dumps({k: arguments[k] for k in ("action", "path", "file_path", "function_name")
                          if k in arguments}, ensure_ascii=False, default=str)
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_for_log as _scrub
        extrait = _caviarder(_scrub(extrait, reversible=True), tool)
    except Exception as exc:  # noqa: BLE001 - une lecture non caviardee ne s'ecrit PAS en clair
        extrait = "[CAVIARDAGE INDISPONIBLE : %s -- extrait non ecrit]" % type(exc).__name__
    _ecrire_acte({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "sens": "LECTURE", "agent": agent or "?",
                  "ring": ring, "outil": tool, "action": arguments.get("action"), "statut": "OK",
                  "forme": forme, "extrait": extrait[:EXTRAIT_ACTE_MAX]})


def net_log(
    channel: NetworkChannel,
    direction,
    *,
    tool: Optional[str] = None,
    method: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    agent: Optional[str] = None,
    ring: Optional[int] = None,
    latency_ms: Optional[float] = None,
    status: Optional[str] = None,
    payload_in: Optional[str] = None,
    payload_out: Optional[str] = None,
    meta: Optional[dict] = None,
    client_ip: Optional[str] = None,
    session_id: Optional[str] = None,
    principal: Optional[str] = None,
    declared: Optional[str] = None,
) -> dict:
    """Log un event réseau via forge_mcp_security.audit() (backend natif).

    `agent` garde son sens (nom de surface) ; `principal` (identite authentifiee) et
    `declared` (en-tete declare) s'y ajoutent, lus de l'acteur courant si non fournis."""
    # Filtre keepalive : poll local = bruit pur, 61% du volume, info nulle
    if agent in ("local", None) and tool == "poll" and (latency_ms or 0) < 5:
        return {}

    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    tool_key = f"{channel}:{tool or method or provider or '?'}"

    try:
        from nokido_agent.app.forge_trace_context import get_trace_id

        _tid = get_trace_id()
    except Exception:
        _tid = "system"

    try:
        from nokido_agent.app.forge_trace_context import get_actor
        _actor = get_actor()
    except Exception:
        _actor = {}
    _principal = principal or _actor.get("principal") or agent or "UNKNOWN"
    _declared = declared or _actor.get("declared") or "UNKNOWN"
    args = {
        "direction": str(direction),
        "trace_id": _tid,  # tôt dans le payload -> survit à la troncature ~180c
        "agent": agent or "?",
        "principal": _principal,
        "declared": _declared,
        "ring": ring,
        "latency_ms": latency_ms,
        "provider": provider,
        "model": model,
        "session_id": session_id,
    }
    # DLP log Tier 1 : scrub PII/secrets AVANT persist (mcp_audit.log en clair).
    # reversible=True : net_log est le sink upstream qui voit les valeurs brutes ;
    # il alimente le vault DPAPI (tags déterministes) -> tout le downstream
    # (execution_traces) devient déanonymisable <7j via deanonymize_log.
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_for_log as _scrub
    except Exception:
        _scrub = lambda x, **k: x  # noqa: E731
    # Ajouter previews payload (scrubbés + réversibles <7j)
    # Deux jeux de motifs (cf. _caviarder) : redact_for_log seul laissait passer les clefs d'API.
    # Calcule UNE fois, reutilise par l'audit, l'historique memoire et le flux SSE (qui portaient
    # la charge BRUTE). Coupe APRES caviardage : couper avant trancherait une clef, et le morceau
    # restant, trop court pour son motif, sortirait en clair. Fenetre de 20 000 car. = borne CPU.
    apercu_in = _caviarder(_scrub(str(payload_in)[:20000], reversible=True), tool or "?")[:500] if payload_in else ""
    apercu_out = _caviarder(_scrub(str(payload_out)[:20000], reversible=True), tool or "?")[:500] if payload_out else ""
    if payload_in:
        args["in"] = apercu_in[:200]
    if payload_out:
        args["out"] = apercu_out[:200]
    if meta:
        _meta = _scrub(meta, reversible=True)
        if isinstance(_meta, dict):
            # Cles courtes du canal mesure : placees juste APRES ring (jamais avant : 22/10
            # 17 h 39, placees apres trace_id elles chassaient agent/ring hors de la ligne
            # tronquee de TOUT l'audit) ; la coupe de forge_mcp_security.audit est a 160 car.
            _tot = {k: _meta.pop(k) for k in ("transport_signale", "canal_contradictoire") if k in _meta}
            _args = {}
            for k, v in args.items():
                _args[k] = v
                if k == "ring":
                    _args.update(_tot)
            args = _args
        if _meta:
            args["meta"] = _meta

    # Acte d'un agent (outil qui AGIT, requete entrante) : trace lisible a cote de l'audit.
    if payload_in and tool in _OUTILS_ACTES and str(direction).endswith("IN"):
        _journaliser_acte(tool, agent, ring, payload_in, status)
    elif payload_out and tool in _OUTILS_ACTES and str(direction).endswith("OUT"):
        _journaliser_reponse(tool, agent, ring, payload_out, status, latency_ms)
    elif payload_in and tool in _OUTILS_LECTURES_ACTES and str(direction).endswith("IN"):
        _journaliser_lecture(tool, agent, ring, payload_in)

    # Écriture dans mcp_audit.log via le backend natif
    native = _get_audit()
    if native:
        try:
            native(tool_key, {k: v for k, v in args.items() if v is not None}, status or "OK")
        except Exception as e:
            logger.debug(f"audit backend: {e}")

    # Event dict pour SSE et historique mémoire
    event = {
        "ts": ts,
        "channel": str(channel),
        "direction": str(direction),
        "tool": tool,
        "method": method,
        "provider": provider,
        "model": model,
        "agent": agent,
        "principal": _principal,
        "declared": _declared,
        "ring": ring,
        "latency_ms": latency_ms,
        "status": status or "OK",
        "payload_in": apercu_in,
        "payload_out": apercu_out,
        "client_ip": client_ip,
        "session_id": session_id,
    }

    # Historique mémoire (non-Electron, pur Python)
    with _HISTORY_LOCK:
        _HISTORY.append(event)
        if len(_HISTORY) > MAX_HISTORY:
            _HISTORY.pop(0)

    # SSE broadcast (thread daemon, non-bloquant)
    threading.Thread(target=_broadcast, args=(event,), daemon=True).start()

    return event


def _broadcast(event: dict):
    data = f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
    dead = []
    with _SSE_LOCK:
        for q in _SSE_CLIENTS:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            try:
                _SSE_CLIENTS.remove(q)
            except ValueError:  # muet-ok : client deja retire par un desabonnement concurrent
                pass


def net_subscribe_sse() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=200)
    with _SSE_LOCK:
        _SSE_CLIENTS.append(q)
    # Replay historique récent
    with _HISTORY_LOCK:
        recent = list(_HISTORY[-50:])
    for ev in recent:
        try:
            q.put_nowait(f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n")
        except queue.Full:
            break
    return q


def net_unsubscribe_sse(q: queue.Queue):
    with _SSE_LOCK:
        try:
            _SSE_CLIENTS.remove(q)
        except ValueError:  # muet-ok : client deja retire (file pleine, purge par _broadcast)
            pass


def _dernieres_lignes(chemin, limit: int, octets_max: int = 2_000_000) -> List[str]:
    """Les `limit` dernieres lignes, SANS charger le fichier entier.

    MESURE DU 2026-09-22. `mcp_audit.log` pesait **107 840 003 octets**
    (102,8 Mo). L'ancien code faisait :

        lines = AUDIT_LOG.read_text(...).splitlines()
        for line in lines[-limit:]:

    Le fichier etait lu EN ENTIER, le `[-limit:]` s'appliquant apres.

        LA BORNE PROTEGEAIT LA SORTIE, JAMAIS LA LECTURE

    Et le declencheur est une route NUE : `GET /api/network/history` (aucune
    garde, 200 sans jeton) retombe ici des que l'historique en memoire est
    vide -- c'est-a-dire APRES CHAQUE REDEMARRAGE du hub.

    Meme motif que l'incident 47 Go surveille par `forge_firehose_guard`
    (« readTextFile-whole ») -- mais ce garde ne regarde que les `.ts`.

    LA BORNE DIT COMBIEN : on lit au plus `octets_max` depuis la FIN. Si le
    fichier est plus gros, les lignes anterieures ne sont pas rendues -- et
    c'est exactement ce qu'on veut, puisqu'on demande les DERNIERES.
    """
    try:
        taille = chemin.stat().st_size
    except OSError:
        return []
    debut = max(0, taille - octets_max)
    with chemin.open("rb") as f:
        if debut:
            f.seek(debut)
        brut = f.read()
    texte = brut.decode("utf-8", "replace")
    if debut:
        # la premiere ligne lue est probablement coupee : on la jette plutot
        # que de rendre un fragment qui se lirait comme une entree complete.
        _, _, texte = texte.partition("\n")
    return texte.splitlines()[-limit:] if limit > 0 else []


def net_history_from_audit(limit: int = 100) -> List[dict]:
    """
    Lit l'historique depuis mcp_audit.log (source de vérité native).
    Évite tout contact avec le DOM Electron.
    """
    try:
        from nokido_agent.app.forge_mcp_security import AUDIT_LOG

        if not AUDIT_LOG.exists():
            return []
        lines = _dernieres_lignes(AUDIT_LOG, limit)
        result = []
        for line in lines[-limit:]:
            parts = line.split(" | ")
            if len(parts) >= 3:
                channel_tool = parts[1].strip() if len(parts) > 1 else "?"
                chan, _, tool = channel_tool.partition(":")
                result.append(
                    {
                        "ts": parts[0].strip(),
                        "channel": chan if chan in ("STDIO", "HUB", "CLOUD", "INTERNAL") else "HUB",
                        "tool": tool or channel_tool,
                        "status": parts[-1].strip() if len(parts) >= 3 else "?",
                        "raw": line[:200],
                    }
                )
        return result
    except Exception as e:
        logger.debug(f"audit read: {e}")
        return list(_HISTORY[-limit:])


def net_history(limit: int = 100, **kwargs) -> List[dict]:
    """Historique depuis mémoire (rapide) ou mcp_audit.log."""
    with _HISTORY_LOCK:
        h = list(_HISTORY[-limit:])
    return h if h else net_history_from_audit(limit)


def net_stats() -> dict:
    with _HISTORY_LOCK:
        h = list(_HISTORY)
    by_channel = {}
    by_agent = {}
    errors = 0
    latencies = []
    for ev in h:
        c = ev.get("channel", "?")
        by_channel[c] = by_channel.get(c, 0) + 1
        a = ev.get("agent", "?")
        by_agent[a] = by_agent.get(a, 0) + 1
        if (ev.get("status") or "").startswith(("ERR", "SECURITY", "SECRET")):
            errors += 1
        if ev.get("latency_ms"):
            latencies.append(ev["latency_ms"])
    return {
        "total": len(h),
        "errors": errors,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "by_channel": by_channel,
        "by_agent": by_agent,
        "sse_clients": len(_SSE_CLIENTS),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT MANAGER — latence automatique
# ─────────────────────────────────────────────────────────────────────────────


class _NetLogContext:
    def __init__(self, channel, direction, kwargs):
        self._channel = channel
        self._direction = direction
        self._kwargs = kwargs
        self._t0 = None
        self._result = None
        self._status = "OK"

    def set_result(self, result: Any, status: str = "OK"):
        self._result = str(result)[:500]
        self._status = status

    def set_error(self, err: Exception):
        self._result = f"ERR: {type(err).__name__}: {err}"[:500]
        self._status = f"ERR:{type(err).__name__}"

    def __enter__(self):
        self._t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency = round((time.monotonic() - self._t0) * 1000, 1)
        if exc_type is not None:
            self.set_error(exc_val)
        net_log(
            self._channel,
            self._direction,
            latency_ms=latency,
            status=self._status,
            payload_out=self._result,
            **self._kwargs,
        )
        return False


@contextmanager
def net_log_call(channel: NetworkChannel, direction, **kwargs):
    ctx = _NetLogContext(channel, direction, kwargs)
    with ctx:
        yield ctx


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS SPÉCIALISÉS
# ─────────────────────────────────────────────────────────────────────────────


def log_stdio_in(tool: str, agent: str, ring: int, args: dict):
    return net_log(
        NetworkChannel.STDIO,
        Direction.IN,
        tool=tool,
        agent=agent,
        ring=ring,
        payload_in=json.dumps(args, ensure_ascii=False)[:400],
        status="CALL",
    )


def log_stdio_out(tool: str, agent: str, ring: int, result: str, latency_ms: float):
    is_err = str(result).startswith(("ERR", "SECURITY", "SECRET GUARD", "FAIL"))
    return net_log(
        NetworkChannel.STDIO,
        Direction.OUT,
        tool=tool,
        agent=agent,
        ring=ring,
        latency_ms=latency_ms,
        status="ERR" if is_err else "OK",
        payload_out=str(result)[:400],
    )


def log_cloud_out(provider: str, model: str, agent: str, message: str, session_id: Optional[str] = None,
                  *, principal: str = "", declared: str = ""):
    return net_log(
        NetworkChannel.CLOUD,
        Direction.OUT,
        provider=provider,
        model=model,
        agent=agent,
        principal=principal or None,
        declared=declared or None,
        session_id=session_id,
        payload_in=str(message)[:400],
        status="CALL",
    )


# `(?![\d.])` : jamais le premier octet d'une adresse (`http://127.0.0.1` n'est pas un code 127).
_CODE_HTTP = re.compile(r"(?:error code|http|status(?:_code)?|code)\D{0,4}([1-5]\d\d)(?![\d.])", re.IGNORECASE)
_CAUSES_TEXTE = (("insufficient balance", "402"), ("quota", "429"), ("rate limit", "429"),
                 ("rate_limit", "429"), ("timed out", "timeout"), ("timeout", "timeout"),
                 ("connection", "connexion"), ("indisponible", "indisponible"), ("unavailable", "indisponible"))


def statut_erreur_cloud(response: str) -> str:
    """`ERR:<classe>` d'un echec cloud -- 402, 403, 429, 5xx, timeout, connexion, indisponible ; `ERR` seul
    si la cause est illisible.

    Mesure 2026-10-13 : 3 fournisseurs a 0 % de succes (credit epuise 402, modele hors palier 403) etaient
    traces `ERR` SANS cause : le motif vit dans la charge, que le journal d'audit tronque vers 150 car.
    avant le statut. Le statut, lui, survit, et le capteur de traces lit deja `ERR:<code>` -- c'est la que
    la cause doit vivre pour qu'une boucle (tri RSI, routeur) puisse la traiter.
    """
    texte = str(response or "")
    m = _CODE_HTTP.search(texte)
    if m:
        return "ERR:" + m.group(1)
    bas = texte.lower()
    for mot, classe in _CAUSES_TEXTE:
        if mot in bas:
            return "ERR:" + classe
    return "ERR"


def log_cloud_in(
    provider: str,
    model: str,
    agent: str,
    response: str,
    latency_ms: float,
    tokens: Optional[int] = None,
    session_id: Optional[str] = None,
    *, principal: str = "", declared: str = "",
):
    is_err = str(response).startswith(("ERR", "Error"))
    return net_log(
        NetworkChannel.CLOUD,
        Direction.IN,
        provider=provider,
        model=model,
        agent=agent,
        latency_ms=latency_ms,
        status=statut_erreur_cloud(response) if is_err else "OK",
        payload_out=str(response)[:400],
        meta={"tokens": tokens} if tokens else None,
        principal=principal or None,
        declared=declared or None,
        session_id=session_id,
    )


def log_internal(event_type: str, agent: str, data: dict, status: str = "OK"):
    return net_log(
        NetworkChannel.INTERNAL,
        Direction.IN,
        tool=event_type,
        agent=agent,
        status=status,
        payload_in=json.dumps(data, ensure_ascii=False)[:400],
    )


# ── Carte d'attention DERIVEE (symbiose Licklider, owner 31/10) ─────────────────────────────────────────────────
_OUTILS_LECTURE = {"read", "read_function_body", "get_file_skeleton", "get_function_dependencies"}
_OUTILS_ECRITURE = {"governed_edit", "write"}
_RE_CHEMIN_ACTE = re.compile(r'"?(?:path|file_path)"?\s*[:=]\s*"?([^",)\s]+)')
_RE_SYMBOLE_ACTE = re.compile(r'"function_name"\s*:\s*"([^"]+)"')
COLLISION_S = 120              # une ecriture plus recente = fichier « en chirurgie »
_ETAG_PAR_STAT: Dict[str, tuple] = {}   # chemin -> (mtime_ns, taille, etag) : relu seulement s'il a change


def carte_attention(fenetre_s: int = 1800, n: int = 7, maintenant: Optional[float] = None,
                    lignes_max: int = 4000, octets_max: int = 1_000_000, racine=None) -> dict:
    """Les `n` fichiers les plus chauds des `fenetre_s` dernieres secondes, lus dans le JOURNAL D'ACTES.

    Zero ecriture nouvelle : une carte ecrite apres chaque lecture aurait multiplie les ecritures du tableau noir
    (mono-ecrivain, chaque fait journalise). La matiere existe deja ici, caviardee. La BORNE DIT COMBIEN : au plus
    `lignes_max` lignes et `octets_max` octets depuis la fin (le journal d'audit a pese 107 Mo). Un acte sans chemin
    lisible est COMPTE (`actes_sans_chemin`), jamais devine. L'etag est celui du fichier au moment de la carte : un
    delegue relit par `si_etag` / `depuis_etag` au lieu de tout recharger.
    """
    from datetime import datetime
    now = time.time() if maintenant is None else maintenant
    fichiers: Dict[str, dict] = {}
    sans_chemin = illisibles = 0
    for ligne in _dernieres_lignes(_JOURNAL_ACTES, lignes_max, octets_max):
        try:
            acte = json.loads(ligne)
            t = datetime.strptime(acte.get("ts", ""), "%Y-%m-%dT%H:%M:%S").timestamp()
        except (ValueError, TypeError, AttributeError):
            illisibles += 1          # COMPTEE, jamais tue : une ligne d'acte illisible n'est pas une ligne absente
            continue
        outil = acte.get("outil")
        if now - t > fenetre_s or outil not in (_OUTILS_LECTURE | _OUTILS_ECRITURE):
            continue
        extrait = str(acte.get("extrait") or "")
        m = _RE_CHEMIN_ACTE.search(extrait)
        if not m:
            sans_chemin += 1
            continue
        chemin = m.group(1).replace("\\", "/")
        f = fichiers.setdefault(chemin, {"chemin": chemin, "dernier": t, "lectures": 0, "ecritures": 0,
                                          "agents": [], "symboles": [], "derniere_ecriture": None})
        f["dernier"] = max(f["dernier"], t)
        f["ecritures" if outil in _OUTILS_ECRITURE else "lectures"] += 1
        if outil in _OUTILS_ECRITURE:
            f["derniere_ecriture"] = max(t, f["derniere_ecriture"] or t)
            f["ecrivain"] = str(acte.get("agent") or "?")
        agent = str(acte.get("agent") or "?")
        if agent not in f["agents"]:
            f["agents"].append(agent)
        s = _RE_SYMBOLE_ACTE.search(extrait)
        if s and s.group(1) not in f["symboles"]:
            f["symboles"] = (f["symboles"] + [s.group(1)])[-5:]
    chauds = sorted(fichiers.values(), key=lambda f: -f["dernier"])[:n]
    racine = Path(racine) if racine else Path(__file__).resolve().parents[1]   # les actes portent des chemins relatifs
    for f in chauds:
        f["age_s"] = int(now - f.pop("dernier"))
        ecrit = f.pop("derniere_ecriture")
        # MULTI-AGENTS (31/10) : un fichier ecrit il y a moins de COLLISION_S est « en chirurgie » -- un delegue
        # relit par si_etag AVANT tout governed_edit, au lieu d'ecraser l'edition d'un pair.
        f["risque_collision"] = ecrit is not None and now - ecrit < COLLISION_S
        if ecrit is None:
            f.pop("ecrivain", None)
        p = Path(f["chemin"]) if Path(f["chemin"]).is_absolute() else racine / f["chemin"]
        try:
            st = p.stat()
            cle = (st.st_mtime_ns, st.st_size)
            connu = _ETAG_PAR_STAT.get(str(p))
            if connu and connu[:2] == cle:
                f["etag"] = connu[2]          # inchange a la nanoseconde : pas de relecture
            else:
                from nokido_agent.app.forge_token_cache import etag as _etag
                f["etag"] = _etag(p.read_text(encoding="utf-8", errors="replace"))
                _ETAG_PAR_STAT[str(p)] = cle + (f["etag"],)
        except (OSError, ImportError) as exc:
            f["etag"] = "ILLISIBLE (%s)" % type(exc).__name__
    return {"fenetre_s": fenetre_s, "fichiers": chauds, "fichiers_vus": len(fichiers),
            "lectures_totales": sum(v["lectures"] for v in fichiers.values()),
            "actes_sans_chemin": sans_chemin, "lignes_illisibles": illisibles,
            "borne": "%d lignes / %d octets depuis la fin" % (lignes_max, octets_max)}


def consigne_attention(n: int = 5, **kw) -> str:
    """La carte d'attention en LIGNES IMPERATIVES, pour l'en-tete d'une consigne deleguee : les petits modeles
    (7B/8B) suivent une regle courte mieux qu'un JSON. Collision en tete. Carte vide ou indisponible = "" : la
    consigne part inchangee, l'en-tete est un confort, jamais une condition. L'etag est celui de l'ARBRE PARTAGE :
    un delegue dans son worktree peut lire un autre contenu -- la relecture complete reste alors correcte, c'est dit."""
    try:
        c = carte_attention(n=n, **kw)
    except Exception as exc:  # noqa: BLE001 - un en-tete facultatif ne casse jamais une delegation
        logger.debug("[attention] carte indisponible pour la consigne (%s)", type(exc).__name__)
        return ""
    fichiers = c.get("fichiers") or []
    if not fichiers:
        return ""
    lignes = ["[CARTE D'ATTENTION %d min : fichiers chauds de l'arbre partage]" % (c["fenetre_s"] // 60)]
    for f in sorted(fichiers, key=lambda f: not f.get("risque_collision")):
        if f.get("risque_collision"):
            lignes.append("- %s | ECRIT tres recemment par %s : RISQUE DE COLLISION, relire juste avant governed_edit"
                          % (f["chemin"], f.get("ecrivain", "?")))
        elif str(f.get("etag", "")).startswith("ILLISIBLE"):
            lignes.append("- %s | lu par %s" % (f["chemin"], ", ".join(f.get("agents") or ["?"])))
        else:
            lignes.append('- %s | etag=%s | relire par si_etag="%s"' % (f["chemin"], f["etag"], f["etag"]))
    lignes.append("(etag de l'arbre partage : si ton worktree differe, la relecture complete reste correcte)")
    return "\n".join(lignes) + "\n\n"
