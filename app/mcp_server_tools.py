"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_mcp_server_tools
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/mcp_server_tools.py
========================
Serveur MCP Nokido — normalisé MCP Specification 2025.

Expose les capacités Nokido comme tools MCP consommables par :
  - OneMCP (One Model Context Protocol hub)
  - Claude Desktop (via mcp.json)
  - Cline / Continue / Cursor
  - forge_desktop (MCPWorker QThread)
  - Tout client MCP v1.x compatible

Transport : stdio (défaut) + SSE optionnel
Port SSE   : LAFORGE_MCP_PORT (env) ou 9999

Tools exposés (18) :
  Catégorie RAG   : rag_search, rag_ingest_text, rag_stats
  Catégorie Swarm : swarm_status, swarm_set_thinking, swarm_force_idle
  Catégorie ADR   : adr_list, adr_create, adr_check_drift
  Catégorie Sys   : services_status, service_start, service_stop
  Catégorie LLM   : llm_generate, mermaid_generate
  Catégorie Code  : code_run_python, code_py_compile
  Catégorie Events: events_recent
  Catégorie Lab   : capacité déportée (lab isolé) — non exposée par défaut

Chaque tool est :
  - Typé (inputSchema JSON Schema)
  - Documenté (description pour le LLM)
  - Ring-aware (ring 0 = protégé, ring 5 = fire&forget)
  - Idempotent autant que possible
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# ═══════════════════════════════════════════════════════════════
# GOUVERNANCE — Agent Authority (ring=10)
# ═══════════════════════════════════════════════════════════════


def _check_authority(caller_agent_id: str) -> dict:
    """
    Vérifie si l'agent appelant a le droit d'écrire/exécuter.
    Fallback d'urgence : LAFORGE_AUTHORITY_BYPASS=true dans .env
    désactive le garde-fou (breakglass).
    """
    if os.environ.get("LAFORGE_AUTHORITY_BYPASS", "").lower() == "true":
        # BREAKGLASS BRUYANT ET CONDITIONNEL (2026-09-02).
        #
        # Il etait SILENCIEUX : un `return ok` sans trace. On l'a decouvert par
        # audit, c'est-a-dire trop tard -- un contournement qu'il faut chercher
        # pour voir n'est pas un contournement surveille.
        #
        # Trois changements, et aucun ne retire la porte de secours :
        #   1. il JOURNALISE a chaque appel (qui, quel tool) ;
        #   2. il est REFUSE hors loopback : une porte de secours locale n'a
        #      aucune raison d'exister sur un hub expose ;
        #   3. il ne franchit QUE `_check_authority`. `_require_capability`
        #      (jeton HMAC) reste intact -- les arguments nomment, le token
        #      decide, et un breakglass ne renverse pas cette regle.
        try:
            from nokido_agent.app.forge_bind_guard import verdict as _bind_verdict

            _expo = _bind_verdict(int(os.environ.get("LAFORGE_HUB_PORT", "8766")))
        except Exception as _e:  # noqa: BLE001
            # Etat d'exposition ILLISIBLE : on ne l'interprete pas comme « local ».
            _expo = {"etat": "INCONNU", "raison": str(_e)[:80]}
        if _expo.get("etat") == "EXPOSE":
            _authority_log("BREAKGLASS_REFUSE", caller_agent_id or "UNKNOWN",
                           "hub expose hors loopback: %s" % _expo.get("adresses"))
            return {"ok": False, "level": "BYPASS_REFUSE",
                    "reason": "breakglass interdit quand le hub ecoute hors "
                              "loopback (%s)" % _expo.get("adresses")}
        _authority_log("BREAKGLASS_ACTIF", caller_agent_id or "UNKNOWN",
                       "LAFORGE_AUTHORITY_BYPASS=true ; exposition=%s"
                       % _expo.get("etat"))
        return {"ok": True, "level": "BYPASS",
                "reason": "breakglass .env actif (journalise ; la capability HMAC "
                          "reste exigee la ou elle s'applique)"}
    try:
        from nokido_agent.app.forge_agent_authority import check_write_permission

        return check_write_permission(caller_agent_id or "UNKNOWN")
    except Exception as e:
        # Si le module n'est pas chargeable → fail-open en dev, fail-closed en prod
        if os.environ.get("LAFORGE_ENV", "prod") == "dev":
            return {"ok": True, "level": "DEV_FAILOPEN", "reason": str(e)[:60]}
        return {"ok": False, "level": "ERROR", "reason": "authority module indisponible: " + str(e)[:60]}


# DEBUG_CAPABILITY: helper IntegrityManager (2026-04-16, opt-in)
# Verification capability HMAC pour les tools sensibles (en complement de _check_authority)
def _require_capability(token: str, scope: str, action: str, agent_id: str = "") -> dict:
    """Verifie un capability token HMAC pour scope+action.

    Args:
        token: Capability token serialise (format payload_b64.hmac_hex)
        scope: 'fs' | 'rag' | 'sql' | 'tasks' | 'system' | 'master'
        action: action specifique ('read', 'write', 'exec', etc.)
        agent_id: ID agent pour audit (optionnel)

    Returns:
        {"ok": bool, "reason": str, "ring": str (si ok)}
    """
    # Fallback fail-open en dev si pas de token (compatible workflow actuel)
    if not token:
        if os.environ.get("LAFORGE_ENV", "prod") == "dev":
            return {"ok": True, "reason": "DEV_NO_TOKEN", "ring": "DEV"}
        return {"ok": False, "reason": "Token capability requis (scope=" + scope + ", action=" + action + ")"}

    try:
        _main = sys.modules.get("__main__")
        mgr = getattr(_main, "_integrity_manager", None) if _main else None
        if mgr is None:
            # Pas de manager initialise -> on tente d'importer bootstrap
            try:
                from nokido_agent.app import bootstrap as _bs

                mgr = _bs.integrity_manager_instance
            except Exception:
                pass
        if mgr is None:
            return {"ok": False, "reason": "IntegrityManager non initialise"}

        ok, ctx_or_reason = mgr.verify(scope, action, token)
        if ok:
            return {
                "ok": True,
                "reason": "OK",
                "ring": ctx_or_reason.ring.label() if hasattr(ctx_or_reason, "ring") else "?",
            }
        return {"ok": False, "reason": str(ctx_or_reason)[:200]}
    except Exception as e:
        return {"ok": False, "reason": "verify error: " + str(e)[:120]}


try:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("Nokido")  # kwarg version removed (incompatible recent SDK)
except ImportError:
    raise SystemExit("mcp SDK requis: pip install mcp")


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE RAG
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def rag_search(query: str, top_k: int = 5, domain: str = "") -> str:
    """
    Recherche sémantique dans la base de connaissance Nokido.
    Utilise le NPU DML (minilm_int8) pour les embeddings.
    Retourne les top_k chunks les plus similaires.
    """
    try:
        from nokido_agent.app.forge_npu_embedder import NPUEmbedder

        emb = NPUEmbedder()
        hits = emb.search_db(query, top_k=min(top_k, 20))
        if not hits:
            return json.dumps({"results": [], "query": query})
        conn = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"), timeout=5)
        results = []
        for h in hits[:top_k]:
            fp = h.get("file_path", "")
            score = h.get("score", 0)
            row = conn.execute(
                "SELECT text, source, domain FROM rag_chunks WHERE source LIKE ? LIMIT 1", ("%" + Path(fp).name + "%",)
            ).fetchone()
            if row and (not domain or row[2] == domain):
                results.append(
                    {
                        "score": round(float(score), 4),
                        "source": row[1],
                        "domain": row[2],
                        "text": row[0][:400],
                    }
                )
        conn.close()
        return json.dumps({"results": results, "query": query, "count": len(results)})
    except Exception as e:
        return json.dumps({"error": str(e)[:120], "results": []})


@mcp.tool()
async def rag_ingest_text(
    text: str, source: str, domain: str = "general", caller_agent_id: str = "", token: str = ""
) -> str:
    """
    Ingère un texte directement dans le RAG (ring 2 — TRUSTED).
    Source est un identifiant (ex: 'adr-007', 'doc-arch-2026').
    Requiert MASTER_DEV ou ORCHESTRATOR.

    Sécurité (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='rag', action='ingest'
      - opt-in : token absent + LAFORGE_ENV=dev -> pass
      - prod sans token -> rejet avec message clair
    """
    # Capability check (opt-in, complement de _check_authority)
    cap = _require_capability(token, "rag", "ingest", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    # Authority check existant (compat)
    auth = _check_authority(caller_agent_id)
    if not auth["ok"] and auth.get("level") == "READ_ONLY":
        return json.dumps({"ok": False, "error": "AUTORISATION REFUSÉE", "reason": auth["reason"]})
    try:
        conn = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        # 2026-09-12 : ce site cumulait les deux defauts mesures — `text[:2000]`
        # amputait en silence (13 896 chunks coupes pile a 2000 en base, ratio
        # 159,7 contre les longueurs voisines) et l'INSERT omettait `id`, qui est
        # un TEXT PRIMARY KEY, laissant la clef NULLE. Le helper porte les deux.
        from nokido_agent.app.forge_db_path import ecrire_chunk  # type: ignore

        ecrire_chunk(conn, source, domain, text)
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE source=?", (source,)).fetchone()[0]
        conn.close()
        return json.dumps({"ok": True, "source": source, "chunks": count})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def rag_stats() -> str:
    """Statistiques de la base RAG : total chunks, distribution par domaine, entropie."""
    import math

    try:
        conn = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"), timeout=5)
        total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        domains = conn.execute(
            "SELECT domain, COUNT(*) FROM rag_chunks GROUP BY domain ORDER BY COUNT(*) DESC"
        ).fetchall()
        conn.close()
        dt = sum(c for _, c in domains)
        H = -sum((c / dt) * math.log2(c / dt) for _, c in domains if c > 0) if dt > 0 else 0
        return json.dumps(
            {
                "total": total,
                "entropy_bits": round(H, 3),
                "domains": [{"name": d, "count": c} for d, c in domains[:12]],
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)[:120]})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE SWARM
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def swarm_status() -> str:
    """État actuel de la state machine swarm (IDLE/THINKING/STREAMING/SYNCING_RAG)."""
    try:
        from nokido_agent.app.forge_swarm import swarm

        st = swarm.swarm_status()
        return json.dumps(st)
    except Exception as e:
        return json.dumps({"state": "UNKNOWN", "error": str(e)[:80]})


@mcp.tool()
async def swarm_set_thinking(agent_id: str, task: str = "", token: str = "", caller_agent_id: str = "") -> str:
    """
    Positionne la state machine en THINKING pour un agent.
    Utilise par les agents externes pour signaler leur activite.

    Securite : capability scope=tasks, action=review (modifie state machine)
    """
    cap = _require_capability(token, "tasks", "review", caller_agent_id or agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_swarm import swarm

        swarm.sm.set_thinking(agent_id, task[:80])
        return json.dumps({"ok": True, "state": "THINKING", "agent": agent_id})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:80]})


@mcp.tool()
async def swarm_force_idle(token: str = "", caller_agent_id: str = "") -> str:
    """Remet la state machine swarm en IDLE (reset d'urgence).

    Securite : capability scope=tasks, action=review (reset state machine = sensible)
    """
    cap = _require_capability(token, "tasks", "review", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_swarm import swarm

        swarm.sm.force_idle()
        return json.dumps({"ok": True, "state": "IDLE"})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:80]})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE ADR
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def adr_list(status: str = "Accepté") -> str:
    """Liste les ADR par statut (Accepté/Proposé/Obsolète/tous)."""
    try:
        conn = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"), timeout=5)
        q = "SELECT adr_id, title, status, ring FROM adr_records"
        q += "" if status == "tous" else f" WHERE status='{status}'"
        q += " ORDER BY ring, id"
        rows = conn.execute(q).fetchall()
        conn.close()
        return json.dumps(
            {
                "adrs": [{"id": r[0], "title": r[1], "status": r[2], "ring": r[3]} for r in rows],
                "count": len(rows),
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)[:80], "adrs": []})


@mcp.tool()
async def adr_create(
    title: str,
    context: str,
    decision: str,
    cons_pos: str = "",
    cons_neg: str = "",
    tags: str = "",
    ring: int = 1,
    token: str = "",
    caller_agent_id: str = "",
) -> str:
    """Cree un nouvel ADR et l'ingere dans le RAG. Tags separes par virgules.

    Securite : capability scope=rag, action=ingest (creation ADR persistante)
    """
    cap = _require_capability(token, "rag", "ingest", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_resonance_filter import create_adr

        tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        adr_id = create_adr(
            title=title,
            context=context,
            decision=decision,
            consequences_pos=cons_pos,
            consequences_neg=cons_neg,
            tags=tags_list,
            ring=ring,
        )
        return json.dumps({"ok": True, "adr_id": adr_id, "title": title})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def adr_check_drift(proposal: str, agent_id: str = "external") -> str:
    """
    Vérifie si une proposition dérive des ADR acceptés.
    Retourne l'action recommandée : pass / warn / correct / block.
    """
    try:
        from nokido_agent.app.forge_resonance_filter import resonance_check

        result = resonance_check(agent_id=agent_id, proposal=proposal)
        return json.dumps(
            {
                "action": result["action"],
                "drift_score": result["drift_score"],
                "repeat_score": result["repeat_score"],
                "correction": result["correction"][:300] if result["correction"] else "",
                "elapsed_ms": result["elapsed_ms"],
            }
        )
    except Exception as e:
        return json.dumps({"action": "pass", "error": str(e)[:80]})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE SERVICES
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def services_status() -> str:
    """Etat des services NSSM Nokido (Hub, Streamlit, MCP).

    Fix 2026-04-16 : encoding cp1252 (sc query renvoie du cp1252 sur Windows FR,
    pas utf-8). Sans ca le subprocess crashait avec NoneType ou UnicodeDecodeError.
    """
    import subprocess as _sp

    services = {}
    for name in ["NokidoHub", "NokidoStreamlit", "NokidoMCP"]:
        try:
            # Windows FR : sc.exe utilise codepage 1252, pas utf-8
            r = _sp.run(
                ["sc", "query", name], capture_output=True, text=True, timeout=3, encoding="cp1252", errors="replace"
            )
            stdout = r.stdout or ""  # protection NoneType
            state = next((l.strip() for l in stdout.splitlines() if "STATE" in l), "UNKNOWN")
            services[name] = {"running": "RUNNING" in state, "state": state}
        except Exception as e:
            services[name] = {"running": False, "error": str(e)[:60]}
    return json.dumps(services)


@mcp.tool()
async def service_start(name: str, token: str = "", caller_agent_id: str = "") -> str:
    """Démarre un service NSSM (NokidoHub, NokidoStreamlit, NokidoMCP).

    Sécurité (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='system', action='sentinel_bypass' (controle NSSM = sensible)
      - opt-in : token absent + LAFORGE_ENV=dev -> pass
    """
    # Capability check (opt-in)
    cap = _require_capability(token, "system", "sentinel_bypass", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    allowed = {"NokidoHub", "NokidoStreamlit", "NokidoMCP"}
    if name not in allowed:
        return json.dumps({"ok": False, "error": "Service non autorisé: " + name})
    try:
        r = subprocess.run(
            ["sc", "start", name], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )
        return json.dumps({"ok": r.returncode == 0, "output": r.stdout.strip()[:80]})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:80]})


@mcp.tool()
async def service_stop(name: str, token: str = "", caller_agent_id: str = "") -> str:
    """Arrête un service NSSM.

    Sécurité (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='system', action='sentinel_bypass' (arret service = critique)
    """
    # Capability check (opt-in)
    cap = _require_capability(token, "system", "sentinel_bypass", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    allowed = {"NokidoHub", "NokidoStreamlit", "NokidoMCP"}
    if name not in allowed:
        return json.dumps({"ok": False, "error": "Service non autorisé: " + name})
    try:
        r = subprocess.run(
            ["sc", "stop", name], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )
        return json.dumps({"ok": r.returncode == 0, "output": r.stdout.strip()[:80]})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:80]})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE LLM
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def llm_generate(
    prompt: str, agent_id: str = "laforge", max_tokens: int = 400, token: str = "", caller_agent_id: str = ""
) -> str:
    """
    Génère une réponse LLM via l'agent spécifié.
    agent_id : nokido (Ollama), llamacpp (local), gemini (remote)
    Passe par le filtre de résonance automatiquement.
    """
    cap = _require_capability(token, "system", "audit_view", caller_agent_id or agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_resonance_filter import resonance_check

        check = resonance_check(agent_id, prompt)
        if check["action"] == "block":
            return json.dumps(
                {
                    "ok": False,
                    "blocked": True,
                    "correction": check["correction"][:300],
                }
            )
        enriched = check["enriched_prompt"]

        if agent_id in ("laforge", "ollama"):
            from nokido_agent.app.forge_ollama import ollama_call

            response = ollama_call(enriched, max_tokens=max_tokens)
        elif agent_id == "llamacpp":
            from nokido_agent.app.forge_llamacpp import llamacpp_call

            response = llamacpp_call(enriched, max_tokens=max_tokens)
        else:
            response = f"[agent {agent_id} non disponible en MCP direct]"

        return json.dumps(
            {
                "ok": True,
                "response": response[:1000],
                "agent": agent_id,
                "resonance_action": check["action"],
            }
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


# ═══════════════════════════════════════════════════════════════
# CAPACITÉ DÉPORTÉE — lab borné isolé, NON exposée au catalogue par défaut
# La fonction reste DEFINIE (gel, pas suppression : règle owner « ne rien
# enterrer ») mais n'entre dans le catalogue MCP que si le lab borné est
# explicitement activé. Interrupteur absent -> list_tools() ne la présente
# jamais au client : la surface déportée n'est pas un déclencheur par défaut.
# ═══════════════════════════════════════════════════════════════


async def cyber_ai_task(prompt: str, model: str = "ollama/qwen2.5-coder:7b") -> str:
    """Passerelle vers la capacité déportée du lab borné (non exposée par défaut)."""
    try:
        # Corps déporté hors du cœur (dépôt privé laforge-redteam). Import nu depuis
        # redteam/laforge_redteam/ (sibling superrepo), jamais nokido_agent.app.
        # Home absent du checkout (dépôt séparé) -> ImportError -> erreur gracieuse.
        import sys as _sys
        import pathlib as _pl

        _rtd = os.environ.get("LAFORGE_REDTEAM_DIR") or str(
            _pl.Path(__file__).resolve().parents[2] / "redteam" / "laforge_redteam"
        )
        if os.path.isdir(_rtd) and _rtd not in _sys.path:
            _sys.path.insert(0, _rtd)
        import forge_cai_bridge

        return await forge_cai_bridge.cai_task(prompt, model=model)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Erreur chargement passerelle lab: {e}"})


# Exposition conditionnée au lab borné : même interrupteur que les intents
# déportés (NOKIDO_REDTEAM_INTENTS_JSON). Absent -> jamais dans le catalogue.
if os.environ.get("NOKIDO_REDTEAM_INTENTS_JSON"):
    mcp.tool()(cyber_ai_task)


@mcp.tool()
async def mermaid_generate(
    prompt: str, diagram_type: str = "flowchart", token: str = "", caller_agent_id: str = ""
) -> str:
    """
    Génère un diagramme Mermaid via Qwen2.5-Coder (llamacpp).
    diagram_type : flowchart | sequence | class | er | state | c4 | git | mind
    """
    cap = _require_capability(token, "rag", "ingest", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_mermaid_gen import generate_mermaid

        result = generate_mermaid(prompt, diagram_type)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120], "code": ""})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE CODE
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def code_py_compile(code: str, token: str = "", caller_agent_id: str = "") -> str:
    """
    Compile du code Python et retourne les erreurs syntaxiques.
    Zero execution - sur pour ring 0.

    Securite : capability scope=fs, action=read (compilation = parse, pas exec)
    """
    cap = _require_capability(token, "fs", "read", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    import py_compile, tempfile, os

    tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w")
    tmp.write(code)
    tmp.close()
    try:
        py_compile.compile(tmp.name, doraise=True)
        return json.dumps({"ok": True, "lines": len(code.splitlines())})
    except py_compile.PyCompileError as e:
        return json.dumps({"ok": False, "error": str(e)[:200]})
    finally:
        os.unlink(tmp.name)


@mcp.tool()
async def code_run_python(
    code: str,
    timeout: int = 10,
    caller_agent_id: str = "",
    token: str = "",
) -> str:
    """
    Exécute du code Python dans un subprocess isolé.
    Max 50 lignes de code, timeout configurable (max 30s).
    Résultat tronqué à 2000 chars.
    Requiert MASTER_DEV. Passer caller_agent_id="CLAUDE" (ou autre agent désigné).

    Sécurité (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='fs', action='exec'
      - opt-in : token absent + LAFORGE_ENV=dev -> pass
      - prod sans token -> rejet
    """
    # Capability check (opt-in)
    cap = _require_capability(token, "fs", "exec", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    auth = _check_authority(caller_agent_id)
    if not auth["ok"]:
        return json.dumps(
            {"ok": False, "error": "AUTORISATION REFUSÉE", "reason": auth["reason"], "holder": auth.get("holder")}
        )
    # Sécurité : limiter la taille + timeout
    if len(code.splitlines()) > 50:
        return json.dumps({"ok": False, "error": "Max 50 lignes"})
    timeout = min(timeout, 30)

    DETACHED = 0  # pas DETACHED — on veut le résultat
    try:
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(ROOT),
        )
        return json.dumps(
            {
                "ok": r.returncode == 0,
                "stdout": r.stdout[:2000],
                "stderr": r.stderr[:500],
                "rc": r.returncode,
            }
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"ok": False, "error": f"Timeout {timeout}s"})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE EVENTS
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def events_recent(n: int = 10, agent_id: str = "") -> str:
    """
    Retourne les N derniers events depuis events.db.
    Filtrable par agent_id.
    """
    try:
        db = ROOT / "sandbox" / "events.db"
        conn = sqlite3.connect(str(db), timeout=5)
        if agent_id:
            rows = conn.execute(
                "SELECT timecode,sequence_id,agent_id,event_type,target FROM event_log "
                "WHERE agent_id=? ORDER BY sequence_id DESC LIMIT ?",
                (agent_id, min(n, 50)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT timecode,sequence_id,agent_id,event_type,target FROM event_log "
                "ORDER BY sequence_id DESC LIMIT ?",
                (min(n, 50),),
            ).fetchall()
        conn.close()
        return json.dumps(
            {
                "events": [{"ts": r[0], "seq": r[1], "agent": r[2], "type": r[3], "target": r[4]} for r in rows],
                "count": len(rows),
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)[:80], "events": []})


# ═══════════════════════════════════════════════════════════════
# LANCEMENT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Nokido MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse"], help="Transport MCP (stdio ou sse)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("LAFORGE_MCP_PORT", "9999")))
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="stdio")


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE SENTINEL + INSPECTOR (Ring 2-4)
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def sentinel_check(instruction: str, tool_name: str = "", agent_id: str = "external") -> str:
    """
    Valide une instruction via la Sentinelle Ring 2-3.
    Dev mode (LAFORGE_ENV=dev) : warn au lieu de block sur ring 1-2.
    Ring 0 : toujours bloqué.
    """
    try:
        from nokido_agent.app.forge_sentinel import validate_action

        result = validate_action(instruction, tool_name, agent_id)
        return json.dumps(result.to_dict())
    except Exception as e:
        return json.dumps({"allowed": True, "action": "pass", "error": str(e)[:80]})


@mcp.tool()
async def sentinel_status() -> str:
    """État de la Sentinelle — mode dev, strict, patterns actifs."""
    try:
        from nokido_agent.app.forge_sentinel import sentinel_status as ss

        return json.dumps(ss())
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def inspector_add_response(
    session_id: str, agent_id: str, response: str, token: str = "", caller_agent_id: str = ""
) -> str:
    """
    Soumet une réponse agent à l'Inspecteur Ring 4.
    Analyse la dérive sémantique et les boucles.
    Retourne : status (ok/drift), entropy, drift, action (pass/warn/rollback).
    """
    cap = _require_capability(token, "tasks", "review", caller_agent_id or agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_inspector import get_inspector

        insp = get_inspector(session_id)
        result = insp.add_response(agent_id, response)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"status": "ok", "action": "pass", "error": str(e)[:80]})


@mcp.tool()
async def context_rollback(session_id: str, reason: str = "", token: str = "", caller_agent_id: str = "") -> str:
    """
    Nettoie le contexte sémantique si un pourrissement est détecté.
    1. Archive le contexte corrompu
    2. Purge les chunks RAG de la session
    3. Réinitialise la mémoire courte des agents
    4. Broadcast RESET_SWARM_MEMORY dans mmap
    Dev mode : rollback simulé sans purge réelle.
    """
    cap = _require_capability(token, "tasks", "review", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_inspector import get_inspector

        insp = get_inspector(session_id)
        result = insp.context_rollback(reason)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def inspector_status() -> str:
    """État de l'Inspecteur — sessions actives, seuils, mode dev."""
    try:
        from nokido_agent.app.forge_inspector import inspector_status as ins

        return json.dumps(ins())
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE MESH + AUTOPILOT (Ring 5.5-6)
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def mesh_archive_synthesis(
    title: str, synthesis: str, ring: int = 2, token: str = "", caller_agent_id: str = ""
) -> str:
    """
    Archive une synthese validee dans LanceDB (Ring 6).
    Cree un point de version immuable. Declenche auto-ADR si ring=2.

    Securite (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='rag', action='ingest' (admin LanceDB = sensible)
    """
    cap = _require_capability(token, "rag", "ingest", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_mesh_memory import get_mesh

        result = get_mesh().archive_synthesis(title, synthesis, ring)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def mesh_rollback(table_name: str, version: int, token: str = "", caller_agent_id: str = "") -> str:
    """
    Rollback LanceDB vers une version anterieure (Inspecteur R4).
    Utilise table.restore(version) - API correcte LanceDB.

    Securite (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='system', action='sentinel_bypass' (rollback destructif)
    """
    cap = _require_capability(token, "system", "sentinel_bypass", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_mesh_memory import get_mesh

        result = get_mesh().rollback_to_version(table_name, version)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def mesh_status() -> str:
    """État du Mesh Ring 6 — LanceDB, tables, sync P2P."""
    try:
        from nokido_agent.app.forge_mesh_memory import mesh_status

        return json.dumps(mesh_status())
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def mesh_sync_remote(dry_run: bool = True, token: str = "", caller_agent_id: str = "") -> str:
    """
    Synchronise LanceDB vers SSH_HOST via rsync DETACHED.
    dry_run=True : affiche la commande sans exécuter.
    En dev (LAFORGE_ENV=dev) : simulation seulement.
    """
    # Sync remote = action sensible meme si dry_run par defaut
    cap = _require_capability(token, "system", "audit_view", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_mesh_memory import get_mesh

        result = get_mesh().sync_to_remote(dry_run=dry_run)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def autopilot_status() -> str:
    """État de l'AutoPilote Ring 5.5 — running, thresholds, dev_mode."""
    try:
        from nokido_agent.app.forge_auto_pilot import autopilot_status as aps

        return json.dumps(aps())
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def autopilot_trigger(action: str, reason: str = "", caller_agent_id: str = "", token: str = "") -> str:
    """
    Declenche manuellement une action AutoPilot.
    actions : heal_hub | context_rollback | flush_context | force_idle
    Requiert MASTER_DEV.

    Securite : capability scope=system, action=sentinel_bypass (action systeme)
    """
    cap = _require_capability(token, "system", "sentinel_bypass", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    auth = _check_authority(caller_agent_id)
    if not auth["ok"]:
        return json.dumps({"ok": False, "error": "AUTORISATION REFUSÉE", "reason": auth["reason"]})
    allowed = {"heal_hub", "context_rollback", "flush_context", "force_idle"}
    if action not in allowed:
        return json.dumps({"ok": False, "error": f"Action inconnue: {action}"})
    try:
        from nokido_agent.app.forge_auto_pilot import AutoPilot

        pilot = AutoPilot()
        T = {
            "heartbeat_stale_s": 0,
            "drift_rollback": 0,
            "entropy_flush": 999,
            "vram_pct_max": 0,
            "swarm_stuck_s": 0,
            "poll_interval_s": 5,
        }
        fn_map = {
            "heal_hub": pilot._action_heal_hub,
            "context_rollback": pilot._action_context_rollback,
            "flush_context": pilot._action_flush_context,
            "force_idle": pilot._action_force_idle,
        }
        await fn_map[action]()
        return json.dumps(
            {
                "ok": True,
                "action": action,
                "reason": reason,
                "dev": pilot._is_dev() if hasattr(pilot, "_is_dev") else None,
            }
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE KAGGLE (Ring 5)
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def kaggle_search(
    query: str, max_results: int = 8, max_size_mb: int = 200, token: str = "", caller_agent_id: str = ""
) -> str:
    """
    Recherche des datasets publics Kaggle.
    Lit KAGGLE_API_TOKEN depuis Nokido.env (token Bearer KGAT_*).

    Securite : capability scope=system, action=audit_view (lecture API externe)
    """
    cap = _require_capability(token, "system", "audit_view", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_kaggle_bridge import get_bridge

        results = get_bridge().search_datasets(query, max_results, max_size_mb)
        return json.dumps({"ok": True, "results": results, "count": len(results)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def kaggle_download(
    ref: str, ingest_rag: bool = False, force: bool = False, token: str = "", caller_agent_id: str = ""
) -> str:
    """
    Télécharge un dataset Kaggle (ref=username/dataset-name).
    ingest_rag=True : ingère automatiquement dans le RAG ring 5.
    En dev (LAFORGE_ENV=dev) : simulation sauf force=True.
    """
    cap = _require_capability(token, "fs", "exec", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_kaggle_bridge import get_bridge

        b = get_bridge()
        if ingest_rag:
            result = b.ingest_to_rag(ref)
        else:
            result = b.download_dataset(ref, force=force)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def kaggle_competitions(query: str = "") -> str:
    """Liste les compétitions Kaggle actives."""
    try:
        from nokido_agent.app.forge_kaggle_bridge import get_bridge

        results = get_bridge().search_competitions(query)
        return json.dumps({"ok": True, "competitions": results})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def kaggle_status() -> str:
    """État du connecteur Kaggle — token, SDK auth, dev mode."""
    try:
        from nokido_agent.app.forge_kaggle_bridge import kaggle_status as ks

        return json.dumps(ks())
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE GITHUB MCP (Remote + REST)
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def github_status() -> str:
    """
    État du connecteur GitHub MCP.
    Token type (classic/fine-grained), login, scopes, expiry, remote MCP URL.
    """
    try:
        from nokido_agent.app.forge_github_mcp_connector import github_mcp_status

        return json.dumps(github_mcp_status())
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def github_list_repos(per_page: int = 10) -> str:
    """Liste les dépôts GitHub de l'utilisateur authentifié."""
    try:
        from nokido_agent.app.forge_github_mcp_connector import get_bridge

        repos = get_bridge().list_repos(per_page)
        return json.dumps(
            {
                "repos": [
                    {
                        "name": r.get("full_name", ""),
                        "private": r.get("private", False),
                        "pushed": r.get("pushed_at", "")[:10],
                        "stars": r.get("stargazers_count", 0),
                    }
                    for r in repos
                    if isinstance(r, dict) and "error" not in r
                ],
                "count": len(repos),
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def github_list_issues(owner: str, repo: str, state: str = "open", limit: int = 10) -> str:
    """Liste les issues d'un dépôt GitHub (owner/repo)."""
    try:
        from nokido_agent.app.forge_github_mcp_connector import get_bridge

        issues = get_bridge().list_issues(owner, repo, state, limit)
        return json.dumps(
            {
                "issues": [
                    {
                        "number": i.get("number"),
                        "title": i.get("title", ""),
                        "state": i.get("state", ""),
                        "labels": [l.get("name") for l in i.get("labels", [])],
                        "url": i.get("html_url", ""),
                    }
                    for i in issues
                    if isinstance(i, dict) and "error" not in i
                ],
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def github_search_code(query: str, limit: int = 5) -> str:
    """Recherche dans le code GitHub (query = 'term repo:owner/repo')."""
    try:
        from nokido_agent.app.forge_github_mcp_connector import get_bridge

        results = get_bridge().search_code(query, limit)
        return json.dumps({"results": results, "count": len(results)})
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def github_mcp_tools() -> str:
    """
    Liste les tools disponibles sur le Remote GitHub MCP Server.
    Utilise SSE Bearer selon policies-and-governance.md.

    Fix 2026-04-16 : mcp_list_tools() est sync (retourne une list directement),
    pas une coroutine. Retirer le 'await' qui causait TypeError.
    """
    try:
        from nokido_agent.app.forge_github_mcp_connector import get_bridge

        tools = get_bridge().mcp_list_tools()  # sync, pas async
        return json.dumps({"tools": tools, "count": len(tools)})
    except Exception as e:
        return json.dumps({"error": str(e)[:80], "tools": []})


@mcp.tool()
async def github_mcp_call(tool_name: str, arguments: str = "{}", token: str = "", caller_agent_id: str = "") -> str:
    """
    Appelle un tool du Remote GitHub MCP Server via SSE.
    arguments : JSON string des paramètres.
    Auth : Bearer ghp_* (Classic PAT — migrer vers fine-grained recommandé).
    """
    cap = _require_capability(token, "system", "audit_view", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_github_mcp_connector import get_bridge

        args = json.loads(arguments) if arguments else {}
        result = await get_bridge().mcp_call(tool_name, args)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


# ═══════════════════════════════════════════════════════════════
# CATÉGORIE LLM ROUTER + CODEBERG (Ring 8 + Ring 7)
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
async def llm_router_call(
    prompt: str, use_case: str = "general", max_tokens: int = 500, token: str = "", caller_agent_id: str = ""
) -> str:
    """
    Appelle le LLMRouter Ring 8 - cascade automatique entre providers.
    use_cases: speed, collab, debate, code, mermaid, sentinel,
               inspect, context, reasoning, eu, mesh, general

    Securite : capability scope=system, action=audit_view (envoi prompt vers cloud LLM)
    """
    cap = _require_capability(token, "system", "audit_view", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_llm_router import router_call

        # CHEMIN LE PLUS EXPOSE : c'est un tool MCP, donc atteignable directement par
        # n'importe quel agent connecte. Il portait zero information de politique.
        # Instrumente sans etre classe -- UNKNOWN, jamais une valeur permissive.
        from nokido_agent.app.forge_share_policy import contexte_legacy as _ctx_legacy

        result = router_call(prompt, use_case=use_case, max_tokens=max_tokens,
                             context=_ctx_legacy(provenance="mcp_server_tools.llm_router_call"))
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def llm_router_status() -> str:
    """État de tous les providers LLM Ring 8 — quota, disponibilité, latence."""
    try:
        from nokido_agent.app.forge_llm_router import router_status

        return json.dumps(router_status())
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def llm_router_add_key(provider_name: str, api_key: str, token: str = "", caller_agent_id: str = "") -> str:
    """
    Ajoute une cle API a chaud sans redemarrer Nokido.
    provider_name: gemini_flash | groq_fast | deepseek_chat |
                   mistral_small | hf_qwen_coder | openrouter_*
    Ecrit dans Nokido.env (persist=True).

    Securite (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='system', action='audit_view'
      - opt-in : token absent + LAFORGE_ENV=dev -> pass
      - prod sans token -> rejet (cle API = secret a proteger)
    """
    cap = _require_capability(token, "system", "audit_view", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_llm_router import get_router

        ok = get_router().add_key(provider_name, api_key, persist=True)
        return json.dumps({"ok": ok, "provider": provider_name})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:80]})


@mcp.tool()
async def codeberg_sync(branch: str = "alpha", force: bool = False, token: str = "", caller_agent_id: str = "") -> str:
    """
    Pousse la branche vers Codeberg (mirror souverain EU).
    En dev (LAFORGE_ENV=dev) : simulation sauf force=True.
    Lit CODEBERG_TOKEN depuis Nokido.env.

    Securite (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='system', action='audit_view'
      - opt-in : token absent + LAFORGE_ENV=dev -> pass
      - prod sans token -> rejet (push externe = sensible)
    """
    cap = _require_capability(token, "system", "audit_view", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_codeberg_sync import sync_now

        result = sync_now(branch=branch, force=force)
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def codeberg_status() -> str:
    """État du remote Codeberg — token, URL, dernier sync, auto-sync."""
    try:
        from nokido_agent.app.forge_codeberg_sync import status

        return json.dumps(status())
    except Exception as e:
        return json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def codeberg_setup(token: str = "", caller_agent_id: str = "") -> str:
    """Configure le git remote 'codeberg' dans le dépôt local."""
    cap = _require_capability(token, "system", "audit_view", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    try:
        from nokido_agent.app.forge_codeberg_sync import setup_remote

        return json.dumps(setup_remote())
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)[:80]})


# ═══════════════════════════════════════════════════════════════
# CATEGORIE AUTHORITY — Gouvernance MASTER_DEV
# ═══════════════════════════════════════════════════════════════


@mcp.tool()
def _authority_log(event: str, agent_id: str, detail: str = "") -> None:
    """Log standardise pour les evenements authority (fichier config/authority.log)."""
    import time

    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    log_line = f"[{ts}] {event} agent={agent_id} {detail}\n"
    try:
        log_path = ROOT / "config" / "authority.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass  # fail-silent pour ne pas bloquer les operations authority


async def authority_status() -> str:
    """
    Retourne l etat d autorite actuel : qui est MASTER_DEV,
    TTL restant, liste des ORCHESTRATORS.
    Accessible en READ_ONLY — aucune restriction.
    """
    import json as _json
    from pathlib import Path as _Path

    state_path = _Path(__file__).resolve().parent.parent / "config" / "authority_state.json"
    try:
        state = _json.loads(state_path.read_text(encoding="utf-8"))
        md = state.get("master_dev", {})
        now = time.time()
        last = md.get("last_beat") or md.get("acquired_at") or 0
        ttl = md.get("ttl", 1800)
        remaining = max(0, int(ttl - (now - last))) if md.get("agent_id") else None
        expired = (now - last) > ttl if md.get("agent_id") else True
        return _json.dumps(
            {
                "master_dev": md.get("agent_id"),
                "expired": expired,
                "ttl_remaining": remaining,
                "orchestrators": state.get("orchestrators", []),
                "last_history": state.get("history", [])[-3:],
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return _json.dumps({"error": str(e)[:80]})


@mcp.tool()
async def authority_acquire(agent_id: str, ttl: int = 1800, token: str = "", caller_agent_id: str = "") -> str:
    """
    Tente d acquerir le token MASTER_DEV pour agent_id.
    Reussit si : slot libre OU token expire (inactivite > TTL).
    Echoue si un autre agent est actif et dans son TTL.
    Exemple : authority_acquire(agent_id="GEMINI")
    """
    # Capability check (DEBUG_CAPABILITY_ADOPT 2026-04-16)
    _cap = _require_capability(token, "tasks", "review", caller_agent_id or agent_id)
    if not _cap["ok"]:
        import json as _j

        return _j.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": _cap["reason"]})
    import json as _json
    from pathlib import Path as _Path

    state_path = _Path(__file__).resolve().parent.parent / "config" / "authority_state.json"
    try:
        state = _json.loads(state_path.read_text(encoding="utf-8"))
        md = state["master_dev"]
        now = time.time()
        last = md.get("last_beat") or md.get("acquired_at") or 0
        holder = md.get("agent_id")
        expired = (now - last) > md.get("ttl", 1800) if holder else True

        if holder and holder != agent_id and not expired:
            remaining = max(0, int(md.get("ttl", 1800) - (now - last)))
            return _json.dumps(
                {
                    "ok": False,
                    "reason": f"Token detenu par {holder} (expire dans {remaining}s)",
                    "holder": holder,
                    "ttl_remaining": remaining,
                }
            )

        # Acquisition
        md["agent_id"] = agent_id
        md["acquired_at"] = now
        md["last_beat"] = now
        md["ttl"] = ttl
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        state["history"].append({"ts": ts, "event": "ACQUIRED", "agent": agent_id, "detail": f"TTL={ttl}s"})
        state["history"] = state["history"][-20:]
        state_path.write_text(_json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        _authority_log("ACQUIRED", agent_id, f"TTL={ttl}s")
        return _json.dumps({"ok": True, "master_dev": agent_id, "ttl": ttl})
    except Exception as e:
        return _json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def authority_release(agent_id: str, token: str = "", caller_agent_id: str = "") -> str:
    """
    Libere volontairement le token MASTER_DEV.
    Seul le holder actuel peut le faire.
    Exemple : authority_release(agent_id="CLAUDE")

    Securite (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='tasks', action='review'
    """
    cap = _require_capability(token, "tasks", "review", caller_agent_id or agent_id)
    if not cap["ok"]:
        import json as _json

        return _json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    import json as _json
    from pathlib import Path as _Path

    state_path = _Path(__file__).resolve().parent.parent / "config" / "authority_state.json"
    try:
        state = _json.loads(state_path.read_text(encoding="utf-8"))
        md = state["master_dev"]
        if md.get("agent_id") != agent_id:
            return _json.dumps({"ok": False, "reason": f"Tu n es pas MASTER_DEV (holder={md.get('agent_id')})"})
        md["agent_id"] = None
        md["acquired_at"] = None
        md["last_beat"] = None
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        state["history"].append({"ts": ts, "event": "RELEASED", "agent": agent_id, "detail": "liberation volontaire"})
        state["history"] = state["history"][-20:]
        state_path.write_text(_json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        _authority_log("RELEASED", agent_id)
        return _json.dumps({"ok": True, "released": agent_id, "slot": "libre"})
    except Exception as e:
        return _json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def authority_transfer(
    new_agent_id: str, reason: str = "transfert humain", token: str = "", caller_agent_id: str = ""
) -> str:
    """
    Force le transfert du token MASTER_DEV vers un nouvel agent.
    Preemption humaine - pas de verification du holder actuel.
    A utiliser depuis le chat pour changer de LLM dev actif.
    Exemple : authority_transfer(new_agent_id="GEMINI")

    Securite (DEBUG_CAPABILITY_ADOPT 2026-04-16) :
      - capability check : scope='tasks', action='review' (transfert admin = sensible)
    """
    cap = _require_capability(token, "tasks", "review", caller_agent_id)
    if not cap["ok"]:
        import json as _json

        return _json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    import json as _json
    from pathlib import Path as _Path

    state_path = _Path(__file__).resolve().parent.parent / "config" / "authority_state.json"
    try:
        state = _json.loads(state_path.read_text(encoding="utf-8"))
        md = state["master_dev"]
        old = md.get("agent_id") or "none"
        now = time.time()
        md["agent_id"] = new_agent_id
        md["acquired_at"] = now
        md["last_beat"] = now
        md["ttl"] = 1800
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        state["history"].append(
            {"ts": ts, "event": "PREEMPTED", "agent": new_agent_id, "detail": f"old={old} reason={reason}"}
        )
        state["history"] = state["history"][-20:]
        state_path.write_text(_json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        _authority_log("TRANSFER", new_agent_id, f"old={old} reason={reason}")
        return _json.dumps({"ok": True, "old_holder": old, "new_holder": new_agent_id, "reason": reason})
    except Exception as e:
        return _json.dumps({"ok": False, "error": str(e)[:120]})


@mcp.tool()
async def check_job_status(job_id: str, caller_agent_id: str = "") -> str:
    """
    Consulte le statut d'un Job ID asynchrone dans le Système Nerveux Nokido.
    Utile pour suivre les tâches lourdes (indexation, crawl, etc.) déléguées
    au proxy Deno/WASM.
    """
    db_path = ROOT / "data" / "nervous_system.db"
    if not db_path.exists():
        return json.dumps({"ok": False, "error": "Base de données du Système Nerveux introuvable."})

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE jobId = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return json.dumps({"ok": False, "error": f"Job {job_id} inconnu."})

        job_data = dict(row)
        # Parse JSON fields
        for field in ["payload", "result"]:
            if job_data.get(field):
                try:
                    job_data[field] = json.loads(job_data[field])
                except:
                    pass

        return json.dumps({"ok": True, "job": job_data})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
async def get_project_state_snapshot(
    include_skills: bool = True,
    include_rag: bool = True,
    include_pipeline: bool = True,
    max_rag_chunks: int = 8,
    token: str = "",
    caller_agent_id: str = "",
) -> str:
    """
    Génère un snapshot complet de l'état Nokido pour injection inter-clients.

    Retourne un bloc JSON prêt à être injecté dans le system prompt d'un
    nouveau client (Roo Code, Cursor, script custom) pour reprendre sans
    friction : skills actifs, derniers findings RAG, état pipeline réseau,
    raisonnements CoT récents.

    Args:
        include_skills: Inclure l'état du SkillLearner (défaut True).
        include_rag: Inclure les derniers chunks security du RAG (défaut True).
        include_pipeline: Inclure state.json du pipeline pentest (défaut True).
        max_rag_chunks: Nombre max de chunks RAG à inclure (défaut 8).

    Returns:
        JSON avec clés: state_id, skills, rag_findings, pipeline, cot_traces, ts.
    """
    cap = _require_capability(token, "system", "audit_view", caller_agent_id)
    if not cap["ok"]:
        return json.dumps({"ok": False, "error": "CAPABILITY REFUSEE", "reason": cap["reason"]})
    import json as _json
    import hashlib as _hash
    from datetime import datetime as _dt
    from pathlib import Path as _P

    _root = _P(__file__).resolve().parent.parent
    _db = _root / "RAG" / "embeddings.db"
    _snap = {}

    # ── 1. Skills ──────────────────────────────────────────────────────────
    if include_skills:
        try:
            import sys as _sys, unittest.mock as _m

            for _mod in ["textual", "textual.containers", "textual.widgets", "textual.reactive"]:
                if _mod not in _sys.modules:
                    _sys.modules[_mod] = _m.MagicMock()
            _app = str(_root / "app")
            if _app not in _sys.path:
                _sys.path.insert(0, _app)
            from nokido_agent.app.skilltree import SkillLearner as _SL, SKILL_TREE as _ST

            _reg = _root / "RAG" / "skill_registry.json"
            _learner = _SL(_reg)
            _learner.sync_from_rag(str(_db))
            _verified = {
                sid: {
                    "label": _ST.get(sid, {}).get("label", sid),
                    "status": _learner.get(sid).status,
                    "successes": _learner.get(sid).successes,
                }
                for sid in _ST
                if _learner.get(sid).successes > 0
            }
            _snap["skills"] = _verified
            _snap["skills_summary"] = (
                f"{sum(1 for v in _verified.values() if v['status'] == 'mastered')} mastered, "
                f"{sum(1 for v in _verified.values() if v['status'] == 'verified')} verified"
            )
        except Exception as _e:
            _snap["skills"] = {"error": str(_e)[:120]}

    # ── 2. RAG findings ────────────────────────────────────────────────────
    if include_rag and _db.exists():
        try:
            import sqlite3 as _sq

            _conn = _sq.connect(str(_db), timeout=5)
            _rows = _conn.execute(
                "SELECT text, meta FROM rag_chunks WHERE domain='security' ORDER BY rowid DESC LIMIT ?",
                (max_rag_chunks,),
            ).fetchall()
            _conn.close()
            _snap["rag_findings"] = [{"text": r[0][:200], "meta": _json.loads(r[1] or "{}")} for r in _rows]
        except Exception as _e:
            _snap["rag_findings"] = [{"error": str(_e)[:80]}]

    # ── 3. Pipeline state ──────────────────────────────────────────────────
    if include_pipeline:
        _state_f = _P(__import__("os").path.expanduser(r"~\.exegol\workspaces\tapple\scan_results\state.json"))
        if _state_f.exists():
            try:
                _pstate = _json.loads(_state_f.read_text())
                _snap["pipeline"] = {
                    "phase": _pstate.get("phase", 0),
                    "phase_name": _pstate.get("phase_name", "idle"),
                    "updated": _pstate.get("updated"),
                    "findings": len(_pstate.get("findings", [])),
                    "nodes": len(_pstate.get("nodes", {})),
                    "key_findings": [f for f in _pstate.get("findings", []) if f.get("level") in ("high", "medium")][
                        -5:
                    ],
                }
            except Exception as _e:
                _snap["pipeline"] = {"error": str(_e)[:80]}
        else:
            _snap["pipeline"] = {"status": "no state.json found"}

    # ── 4. CoT traces (shadow_mutation/thoughts/) ──────────────────────────
    _thoughts_dir = _root / "shadow_mutation" / "thoughts"
    _cot = []
    if _thoughts_dir.exists():
        for _tf in sorted(_thoughts_dir.glob("*.json"), reverse=True)[:3]:
            try:
                _t = _json.loads(_tf.read_text())
                _cot.append(
                    {
                        "file": _tf.name,
                        "summary": _t.get("summary", "")[:200],
                        "conclusion": _t.get("conclusion", "")[:200],
                        "ts": _t.get("ts", ""),
                    }
                )
            except Exception:
                pass
    _snap["cot_traces"] = _cot if _cot else ["no CoT traces yet"]

    # ── 5. SITUATION.md résumé ─────────────────────────────────────────────
    _sit = _root / "SITUATION.md"
    if _sit.exists():
        _lines = _sit.read_text(encoding="utf-8", errors="replace").splitlines()
        _snap["situation_excerpt"] = "\n".join(_lines[:25])

    # ── 6. State ID (hash reproductible) ──────────────────────────────────
    _key = _json.dumps(
        {
            "skills_summary": _snap.get("skills_summary", ""),
            "pipeline_phase": _snap.get("pipeline", {}).get("phase", 0),
            "rag_count": len(_snap.get("rag_findings", [])),
        },
        sort_keys=True,
    )
    _state_id = "LF-" + _hash.sha256(_key.encode()).hexdigest()[:8].upper()

    _snap["state_id"] = _state_id
    _snap["ts"] = _dt.now().isoformat()
    _snap["inject_hint"] = (
        f"Inject this snapshot as context prefix. "
        f"State: {_state_id}. "
        f"Skills: {_snap.get('skills_summary', '')}. "
        f"Pipeline phase: {_snap.get('pipeline', {}).get('phase_name', 'idle')}. "
        f"Use rag_search() to retrieve detailed findings."
    )

    return _json.dumps(_snap, indent=2, ensure_ascii=False, default=str)
