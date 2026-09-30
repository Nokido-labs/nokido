#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""wired_routes.py — cable les routes GUI MORTES vers les vrais backends hub.

Pattern = proxy vers hub :8766 /mcp (tools/call), identique a mcp_lab (prouve).
Tue les 404 releves par tools/audit_ui_endpoints sur :
  rag_dashboard (/api/rag/stats, /api/rag/tokenize), graph_viz (/api/graph/proprioception),
  recon_demo (/api/recon/run), swarm (/api/swarm/run + /api/swarm/stream SSE), postal (/api/agents).
Monte AUSSI transitivement le router epistemic (deja pret dans epistemic.py, jamais
monte) sous /epistemic -> evite d'editer app.py (CRITICAL_FILE).
Defensif : renvoie toujours du JSON (jamais 404/500 silencieux) = backend reel invoque.
Auth : identite WEBHUB (ring 2, config/agent_identities.json) + Bearer FORGE_MCP_TOKEN
(env -> vault) ; sans token le hub repond ring<0 Unauthorized, sans identite ring 4.
Lecture seule locale (tokenize, graph proprioception, swarm stream) = in-process / tail
fichier, pas de gate ring.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()


def _armer_sentinelle_de_boucle() -> None:
    """La sentinelle de boucle existait deja ; le webhub ne l'armait pas.

    `forge_loop_sentinel` detecte le gel de la boucle asyncio et DUMPE la
    traceback du bloqueur — c'est elle qui a nomme `_load_dense_cache mid-block`
    et un `subprocess.run mid-block` ailleurs dans le corps. Mais `start()`
    n'etait appelee QUE dans `nokido_hub.py` : le hub :8766 etait couvert, et le
    webhub :7400 — celui qui sert les flux SSE et qui reste en LISTENING muet —
    ne l'etait pas. Un garde juste, branche sur un seul organe.

    Mesure 2026-08-29 : cinq sockets en CLOSE_WAIT sur :7400, /health qui expire,
    douze routes declarees non jugees derriere, et AUCUN journal pour instruire.
    Les trois flux SSE du depot demandent pourtant bien `is_disconnected` depuis
    le 26/08 : la cause reste illisible, ce qui n'est pas la meme chose qu'absente.

    Le volet KILL reste DESARME ici (`LAFORGE_LOOP_KILL_S` force a 0 par defaut
    cote webhub) : redemarrer d'autorite une interface que l'owner regarde est
    une decision qui se prend, elle ne s'obtient pas en effet de bord. Poser la
    variable a une valeur non nulle l'active. Le diagnostic, lui, ne coutait rien
    et manquait depuis vingt-cinq jours."""
    import datetime
    import logging
    import os

    _log = logging.getLogger("web_hub.sentinelle")

    # IDEMPOTENT. Mesure 2026-08-29 : au premier vrai demarrage, la trace est
    # apparue DEUX fois au meme horodatage et pour le meme pid — le handler est
    # enregistre deux fois (module atteint par deux chemins d'import, ou router
    # inclus deux fois). Deux appels a start() = DEUX monitors sur la meme boucle,
    # donc deux dumps par gel et deux fois le cout de surveillance. Le drapeau vit
    # dans l'environnement du PROCESS, pas dans une globale de module : une globale
    # ne protege pas d'un module charge sous deux noms.
    _cle = "LAFORGE_WEBHUB_SENTINELLE_PID"
    if os.environ.get(_cle) == str(os.getpid()):
        _log.info("[webhub] sentinelle deja armee dans ce process — second appel ignore")
        return
    os.environ[_cle] = str(os.getpid())
    os.environ.setdefault("LAFORGE_LOOP_KILL_S", "0")

    def _tracer(ligne: str) -> None:
        """La trace va dans un FICHIER, pas seulement dans un logger.

        Le webhub n'a aucun journal : un `logging.warning` y part dans une sortie
        que personne ne collecte, et « garde arme » resterait invérifiable du
        dehors — c'est-a-dire exactement le motif qu'on corrige ici. On ecrit dans
        `logs/loop_lag.log`, la ou la sentinelle depose deja ses dumps, pour que
        l'armement et les gels se lisent au meme endroit."""
        _log.warning(ligne)
        racine = Path(__file__).resolve().parents[2]
        marque = "--- [webhub] %s pid=%s %s\n" % (
            datetime.datetime.now().isoformat(timespec="seconds"), os.getpid(), ligne)
        # DEUX cibles, pour distinguer « le handler n'a pas tourne » de « le compte
        # du service ne peut pas ecrire la ». `sandbox/` recoit deja les heartbeats
        # de quarante-cinq daemons : l'acces y est prouve, `logs/` ne l'est pas pour
        # ce compte. Sans les deux, un silence resterait ambigu.
        for cible in (racine / "sandbox" / "webhub_sentinelle.log",
                      racine / "logs" / "loop_lag.log"):
            try:
                cible.parent.mkdir(parents=True, exist_ok=True)
                with open(cible, "a", encoding="utf-8") as fh:
                    fh.write(marque)
            except OSError as ex:  # noqa: BLE001 — une cible refusee n'empeche ni l'autre ni le service
                _log.warning("[webhub] trace non ecrite dans %s : %s",
                             cible.name, type(ex).__name__)

    try:
        from nokido_agent.app.forge_loop_sentinel import start as _start

        _start(threshold_ms=float(os.environ.get("LAFORGE_WEBHUB_LAG_MS", "1000")))
        _tracer("sentinelle de boucle ARMEE (diagnostic ; kill_s=%s ; seuil=%sms)"
                % (os.environ.get("LAFORGE_LOOP_KILL_S"),
                   os.environ.get("LAFORGE_WEBHUB_LAG_MS", "1000")))
    except Exception as ex:  # noqa: BLE001 — un diagnostic absent ne doit pas empecher le service
        _tracer("sentinelle de boucle NON armee : %s: %s" % (type(ex).__name__, ex))


router.add_event_handler("startup", _armer_sentinelle_de_boucle)

_HUB = "http://127.0.0.1:8766/mcp"
_TOKEN_CACHE = {"t": None}
# Miroir cross-process du bus swarm (forge_swarm_bus._REFLEX_LOG). Le swarm tourne
# dans le process HUB ; le web_hub est un AUTRE process -> on suit ce JSONL, pas le
# ring in-process (qui serait vide ici).
_REFLEX_LOG = Path(__file__).resolve().parents[2] / "sandbox" / "reflexion.jsonl"


def _hub_token() -> str:
    """Credential de l'interface web vers le hub — le SIEN d'abord, le maitre en repli.

    SOURCE UNIQUE des deux appelants : `mcp_lab` importe cette fonction, et ne
    retombe sur sa copie locale que si l'import echoue. Corriger ici corrige les
    deux, ce qui est le point : le defaut venait justement d'un credential
    eparpille.

    REVUE DE SECURITE 2026-09-18. Cette fonction ne rendait que le jeton MAITRE,
    pendant que les appels declarent `X-Agent-Name: WEBHUB`. Or le porteur du
    maitre CONSERVE l'agent du header ET son ring (`via=master_token`) : c'est un
    passe-partout d'identite. Tout appel d'outil passe par l'interface web
    s'executait donc avec l'autorite du routeur, et non celle de l'utilisateur —
    le CONFUSED DEPUTY ferme le 2026-09-02 pour OPENAI_PROXY et DENOHUBMCP.

    L'interface web avait ete OUBLIEE par cette campagne. Mesure du 2026-09-18 :
    `FORGE_TOKEN_DENOHUBMCP` et `FORGE_TOKEN_OPENAI_PROXY` etaient PRESENTS au
    coffre, `FORGE_TOKEN_WEBHUB` ABSENT — et ce n'etait pas le filtre de ring qui
    l'ecartait (`ring_max=3`, WEBHUB est ring 2), seulement un semis jamais
    relance. Le jeton a ete seme le jour meme, et `config/agent_identities.json`
    porte desormais sa regle de delegation (`ring_min_delegue: 1`).

    LE REPLI EST VOULU, et il ne masque rien : sur une machine dont le coffre n'a
    pas encore ce jeton, on garde le comportement d'avant plutot que de rendre
    l'interface muette — mais on le DIT dans le journal, une fois, avec le geste
    qui le corrige. Un repli silencieux se lirait comme un succes.
    """
    if _TOKEN_CACHE["t"] is not None:
        return _TOKEN_CACHE["t"]
    import os
    # NOM LIE APRES USAGE (pyflakes 2026-08-20) : `_gs` etait importe ligne ~46,
    # soit APRES cet appel -> NameError a chaque passage.
    try:
        from nokido_agent.app.forge_secrets import get_secret as _gs
    except Exception:  # noqa: BLE001 — repli env, le fallback vault suit plus bas
        _gs = os.environ.get

    t = _gs("FORGE_TOKEN_WEBHUB") or ""
    if not t:
        t = _gs("FORGE_MCP_TOKEN") or ""
        if t:
            try:
                import logging as _lg
                _lg.getLogger("forge.webhub").warning(
                    "[identite] FORGE_TOKEN_WEBHUB absent du coffre : repli sur le "
                    "jeton MAITRE, qui est un passe-partout d'identite. "
                    "Consequence : les appels d'outils de l'interface portent "
                    "l'autorite du routeur, pas celle de l'utilisateur. "
                    "Geste : LAFORGE_PYTHON tools/forge_vault_seed_agent_tokens.py "
                    "--generate-missing --from-registre --agents WEBHUB")
            except Exception:  # noqa: BLE001
                pass  # muet-ok : journaliser ne doit jamais casser l'authentification
        # ON NE MET PAS EN CACHE UN RESULTAT DEGRADE.
        #
        # MESURE DU 2026-09-22, sur trafic reel. Le jeton propre a ete seme le
        # 2026-09-18 (ce docstring le dit : « seme le jour meme »). Quatre jours
        # plus tard, sur une fenetre d'audit homogene :
        #
        #     WEBHUB   master_token 4 378   token 1 072
        #
        # 80 % du trafic de l'interface portait encore le PASSE-PARTOUT alors
        # que son credential propre etait PRESENT au coffre. La cause n'etait
        # pas une cle manquante : c'etait CE CACHE. Un process demarre avant le
        # semis avait fige le maitre et ne relisait plus jamais.
        #
        #     LE REPLI ETAIT JUSTE, SA MISE EN CACHE L'A RENDU DEFINITIF
        #
        # Meme faute que la fuite du 2026-09-21 (cle revoquee -> repli -> cache
        # jamais purge) : cacher un resultat DEGRADE avec la meme duree qu'un
        # resultat NOMINAL. Le repli reste une tolerance ; il cesse d'etre un
        # etat permanent, et le service bascule des que la cle apparait -- sans
        # redemarrage.
        #
        # Le coffre VIDE n'est pas cache non plus : une absence momentanee
        # n'est pas une absence definitive.
        return t
    _TOKEN_CACHE["t"] = t
    return t


async def _call(tool: str, arguments: dict | None = None, timeout: float = 120.0) -> dict:
    """tools/call vers le hub (gere JSON et text/event-stream).

    `timeout` : 120 s par defaut, valeur historique conservee pour les appels de TRAVAIL
    (ingestion, swarm) qui peuvent legitimement etre longs. Une route d'AFFICHAGE doit
    passer bien moins : mesure 2026-08-26, `/api/agents` a depasse 25 s parce que
    `list_providers` sonde les backends LLM et qu'ollama etait fige. Faire attendre deux
    minutes devant une page n'est jamais la bonne reponse -- mieux vaut dire qu'on n'a
    pas pu savoir.
    """
    payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4())[:8],
               "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}}
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream",
               "X-Agent-Name": "WEBHUB", "X-Transport": "web_hub/1.0"}
    _tok = _hub_token()
    if _tok:
        headers["Authorization"] = f"Bearer {_tok}"
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(_HUB, json=payload, headers=headers)
        if "text/event-stream" in r.headers.get("content-type", ""):
            last = None
            async for line in r.aiter_lines():
                line = line.strip()
                if line.startswith("data: ") and line[6:].startswith("{"):
                    last = line[6:]
            return json.loads(last) if last else {}
        return r.json()


def _content(resp: dict) -> Any:
    """Extrait le payload utile d'une reponse JSON-RPC tools/call."""
    if not isinstance(resp, dict):
        return resp
    res = resp.get("result", resp)
    cont = res.get("content") if isinstance(res, dict) else None
    if isinstance(cont, list) and cont and isinstance(cont[0], dict):
        txt = cont[0].get("text")
        if txt:
            try:
                return json.loads(txt)
            except Exception:
                return txt
    return res


async def _safe(tool: str, args: dict | None = None):
    try:
        return JSONResponse({"ok": True, "data": _content(await _call(tool, args))})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=502)


def _rag_db_stats() -> dict:
    """Stats RAG DIRECT sur embeddings.db (read-only). Count-only ~0.8s ;
    SUM(LENGTH(text)) evite VOLONTAIREMENT (~11s de scan sur 20Go)."""
    import sqlite3
    from pathlib import Path as _P
    db = _P(__file__).resolve().parent.parent.parent / "RAG" / "embeddings.db"
    con = sqlite3.connect(str(db), timeout=8)
    try:
        total = con.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        no_emb = con.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL").fetchone()[0]
        rows = con.execute(
            "SELECT COALESCE(domain,'(aucun)'), COUNT(*) FROM rag_chunks "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 40").fetchall()
    finally:
        con.close()
    try:
        import tiktoken  # noqa: F401
        tk = True
    except Exception:
        tk = False
    return {"total": total, "no_embedding": no_emb, "tiktoken_ok": tk,
            "domains": [{"name": r[0], "chunks": r[1]} for r in rows]}


# Instantane ecrit par la phase health (app/forge_health_diagnostic.py : OUT_JSON). NR :
# test_rag_stats_instantane_nr verifie que ce chemin EST celui du producteur.
_INSTANTANE_HEALTH = Path(__file__).resolve().parent.parent.parent / "sandbox" / "health_diagnostic.json"


def _rag_stats_instantane() -> dict | None:
    """Stats RAG depuis l'instantane de la phase health, avec sa SOURCE et son AGE.

    Mesure 2026-09-25 : `_rag_db_stats` coutait ~17 s A CHAQUE chargement de /rag (COUNT sans
    vecteur 6,7 s sur un index partiel de 6,6 M lignes, GROUP BY domaine 10,7 s) -- la page
    n'affichait rien avant, et la campagne ui-acceptance la jugeait VIOLEE. La phase health
    calcule deja ces valeurs : on lit son instantane (meme correctif que /api/hub/overview
    le 18/09). Une valeur dont on ignore la fraicheur se lirait comme une mesure de l'instant :
    l'age est donc rendu, et None si l'instantane est absent ou illisible (repli declare).
    """
    from datetime import datetime

    try:
        d = json.loads(_INSTANTANE_HEALTH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rc = d.get("rag_chunks") or {}
    if rc.get("total") is None or rc.get("non_vectorized") is None:
        return None
    age = None
    try:
        age = round((datetime.now() - datetime.fromisoformat(str(d.get("ts")))).total_seconds())
    except (TypeError, ValueError):
        pass
    return {"total": rc["total"], "no_embedding": rc["non_vectorized"],
            "domains": [{"name": x.get("domain"), "chunks": x.get("count")}
                        for x in (rc.get("top_domains") or [])],
            "domaines_partiels": True, "source": "instantane phase health", "age_s": age}


@router.get("/api/rag/stats")
async def rag_stats():
    """RAG stats reelles (embeddings.db). forge_stats = observabilite runtime
    (GOAP/cpu), PAS des stats RAG -> etait la cause du d.total undefined.
    Deporte en thread : SQL bloquant en async wedge l'event-loop unique.
    Instantane de la phase health d'abord ; comptage direct seulement en REPLI, et dit."""
    import asyncio
    try:
        snap = await asyncio.to_thread(_rag_stats_instantane)
        if snap is not None:
            try:
                import tiktoken  # noqa: F401
                snap["tiktoken_ok"] = True
            except Exception:  # noqa: BLE001 — absence = False, dite dans la reponse
                snap["tiktoken_ok"] = False
            return JSONResponse(snap)
        direct = await asyncio.to_thread(_rag_db_stats)
        direct.update({"source": "comptage direct (instantane health absent)", "age_s": 0})
        return JSONResponse(direct)
    except Exception as e:
        return JSONResponse(
            {"total": 0, "no_embedding": 0, "domains": [], "tiktoken_ok": False,
             "error": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=200)


@router.post("/api/rag/tokenize")
async def rag_tokenize(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = (body or {}).get("text", "") or ""
    try:
        import tiktoken
        n = len(tiktoken.get_encoding("cl100k_base").encode(text))
        method = "tiktoken/cl100k"
    except Exception:
        n = int(len(text.split()) * 1.3)
        method = "approx(words*1.3)"
    return JSONResponse({"ok": True, "tokens": n, "chars": len(text), "method": method})


@router.post("/api/rag/search")
async def rag_search(request: Request):
    """Recherche RAG REELLE, par le hub — le seul process qui porte le RAGEngine.

    Le tableau de bord RAG n'exposait aucune recherche : l'organe de recuperation
    sans sa fonction centrale. Aucun nouveau chemin invente ici — c'est exactement
    celui que le TUI emprunte depuis toujours (`cmd_rag` -> hub `rag action=search`),
    par le proxy `_call` deja present dans ce module.

    Timeout court (30 s) : c'est une route d'AFFICHAGE. Faire attendre deux minutes
    devant une page n'est jamais la bonne reponse — mieux vaut dire qu'on n'a pas su.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — corps absent/illisible : on repond au lieu de 500
        body = {}
    topic = str((body or {}).get("q") or (body or {}).get("topic") or "").strip()
    if not topic:
        return JSONResponse({"ok": False, "raison": "requete_vide"}, status_code=400)
    try:
        limite = max(1, min(20, int((body or {}).get("limit") or 8)))
    except (TypeError, ValueError):
        limite = 8
    try:
        r = await _call("rag", {"action": "search", "topic": topic, "limit": limite},
                        timeout=30.0)
    except Exception as e:  # noqa: BLE001
        # Le hub injoignable est une INDISPONIBILITE, pas « zero resultat » : un
        # tableau de bord qui affiche une liste vide dans ce cas ment a son lecteur.
        return JSONResponse(
            {"ok": False, "raison": "hub_injoignable", "erreur": f"{type(e).__name__}: {str(e)[:160]}"},
            status_code=503)
    texte = ""
    try:
        contenu = ((r or {}).get("result") or {}).get("content")
        if isinstance(contenu, list) and contenu:
            texte = str(contenu[0].get("text") or "")
        elif isinstance((r or {}).get("result"), str):
            texte = r["result"]
    except Exception:  # noqa: BLE001 — forme inattendue : on rend le brut, pas du vide
        texte = ""
    if not texte and (r or {}).get("error"):
        return JSONResponse({"ok": False, "raison": "hub_erreur",
                             "erreur": str(r["error"])[:200]}, status_code=502)
    return JSONResponse({"ok": True, "q": topic, "limit": limite,
                         "texte": texte or "(aucun extrait rendu par le hub)"})


@router.get("/api/graph/proprioception")
def graph_proprio(request: Request):
    """Proprioception du CODE : imports / imported-by / call-graph par fichier.

    RECABLAGE 2026-08-20. Cette route rendait `forge_graph_search.stats()`,
    c'est-a-dire les stats du knowledge-graph -- pas la proprioception. Le
    README promettait pourtant « imports / imported-by / call-graph per file »,
    et ce graphe existe bel et bien : `forge_ast_index`. La capacite etait
    presente, la surface mal cablee -- exactement le genre d'ecart qu'un audit
    declaration/implementation existe pour trouver.

    Contrat :
      - defaut            -> `forge_ast_index.summary()` (fichiers, aretes, age)
      - `?file=<chemin>`  -> `forge_ast_index.ego(file, depth)` (voisinage)
      - `?source=graph`   -> l'ANCIEN comportement, conserve pour qui en depend
    La reponse NOMME sa source : un consommateur ne doit jamais avoir a deviner
    quel graphe il regarde.
    """
    params = request.query_params
    if params.get("source") == "graph":
        try:
            from nokido_agent.app.forge_graph_search import stats as _gstats
            return JSONResponse({"ok": True, "source": "graph_search", "data": _gstats()})
        except Exception as e:
            return JSONResponse({"ok": False, "source": "graph_search",
                                 "error": f"{type(e).__name__}: {str(e)[:200]}"},
                                status_code=502)
    try:
        from nokido_agent.app import forge_ast_index as _ast_idx

        cible = params.get("file")
        if cible:
            try:
                profondeur = max(1, min(3, int(params.get("depth", "1"))))
            except ValueError:
                profondeur = 1
            data = _ast_idx.ego(cible, profondeur)
        else:
            data = _ast_idx.summary()
        return JSONResponse({"ok": True, "source": "ast_index", "data": data})
    except Exception as e:
        return JSONResponse({"ok": False, "source": "ast_index",
                             "error": f"{type(e).__name__}: {str(e)[:200]}"},
                            status_code=502)


@router.post("/api/recon/run")
async def recon_run(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    intent = (body or {}).get("intent") or (body or {}).get("obj") or (body or {}).get("objective") or ""
    if not intent:
        return JSONResponse({"ok": False, "error": "intent/obj requis"}, status_code=400)
    target = (body or {}).get("target")
    args = {"intent": intent}
    if target:
        args["target"] = target
    return await _safe("forge_deep_explore", args)


@router.post("/api/swarm/run")
async def swarm_run(request: Request):
    """ForgeSwarm code-edit (forge_spawn_swarm) : plan = liste de taches DICT
    {task_id, op: edit_sr|create|delete|rename|noop, targets:[file], deps?, prompt?}.
    dry_run defaut True (apercu sur, n'ecrit rien) ; passer dry_run=false pour appliquer.
    UI interactive complete = hub :8766 /forge/swarm (events live)."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    tasks = (body or {}).get("tasks")
    if tasks is None:
        tasks = (body or {}).get("plan")
    if isinstance(tasks, dict):
        tasks = [tasks]
    if not isinstance(tasks, list) or not tasks:
        return JSONResponse({"ok": False, "error": (
            "tasks/plan requis : liste non vide de taches. Schema tache = "
            "{task_id, op: edit_sr|create|delete|rename|noop, targets:[file], deps?, prompt?}")},
            status_code=400)
    if not all(isinstance(t, dict) for t in tasks):
        return JSONResponse({"ok": False, "error": (
            "chaque tache doit etre un dict (plan d'essaim code-edit), pas une chaine. "
            "Schema = {task_id, op, targets:[file], prompt}. UI complete: hub :8766 /forge/swarm")},
            status_code=400)
    dry = bool((body or {}).get("dry_run", True))
    return await _safe("forge_spawn_swarm", {"tasks": tasks, "dry_run": dry})


@router.get("/api/swarm/stream")
async def swarm_stream(request: Request):
    """Flux SSE LIVE de la collaboration swarm. Suit sandbox/reflexion.jsonl (miroir
    cross-process de forge_swarm_bus) : marche meme si le swarm tourne dans le hub.
    Late-join = rejoue les 40 derniers events, puis follow (keepalive ~15s idle)."""
    import asyncio

    async def gen():
        log = _REFLEX_LOG
        pos = 0
        try:
            if log.exists():
                tail = log.read_text("utf-8", "replace").splitlines()[-40:]
                for ln in tail:
                    if ln.strip():
                        yield f"data: {ln}\n\n"
                pos = log.stat().st_size
        except Exception:
            pos = 0
        idle = 0
        while True:
            await asyncio.sleep(1.0)
            # Mesure 2026-08-26, motif partage par les trois flux du portail : un SSE ne
            # s'arrete jamais de lui-meme, et tant qu'on n'ecrit pas dans une socket
            # fermee on ne sait pas que le client est parti. Celui-ci boucle a la
            # SECONDE : sans cette demande, un onglet ferme laisse un reveil par seconde,
            # pour personne, indefiniment.
            if await request.is_disconnected():
                break
            emitted = False
            try:
                if log.exists():
                    sz = log.stat().st_size
                    if sz < pos:
                        pos = 0  # rotation/trim
                    if sz > pos:
                        with open(log, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(pos)
                            chunk = f.read()
                            pos = f.tell()
                        for ln in chunk.splitlines():
                            if ln.strip():
                                yield f"data: {ln}\n\n"
                                emitted = True
            except Exception:
                pass
            idle = 0 if emitted else idle + 1
            if idle >= 15:
                yield ": keepalive\n\n"
                idle = 0

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/agents")
async def agents():
    """Registre LIVE des providers/agents (remplace le AGENTS hardcode de postal).

    Borne a 10 s : `list_providers` interroge les backends LLM, donc cette route herite
    de leur etat. Un backend fige ne doit pas figer la page qui l'affiche."""
    try:
        data = _content(await _call("hub", {"action": "list_providers"}, timeout=10.0))
    except Exception as e:
        # TROIS etats : on distingue « le hub a refuse » de « le hub n'a pas repondu a
        # temps ». Le second n'est pas une panne du registre, c'est un backend qui tarde
        # — et le dire evite d'aller chercher un bug la ou il n'y en a pas.
        _lent = "Timeout" in type(e).__name__ or "Timeout" in str(e)
        return JSONResponse(
            {"ok": False, "agents": {},
             "error": ("le hub n'a pas repondu en 10 s — list_providers sonde les "
                       "backends LLM, l'un d'eux est probablement fige"
                       if _lent else str(e)[:200]),
             "cause": "backend_lent" if _lent else "appel_refuse"},
            status_code=503 if _lent else 502)
    agents_map: dict[str, dict] = {}
    items = data if isinstance(data, list) else (data.get("providers") if isinstance(data, dict) else None)
    if isinstance(items, list):
        for p in items:
            if isinstance(p, dict):
                name = (p.get("name") or p.get("id") or p.get("role") or "?").upper()
                agents_map[name] = {"ring": p.get("ring", "?"), "channel": p.get("channel") or p.get("transport") or "",
                                    "transport": p.get("transport") or p.get("kind") or "provider"}
    elif isinstance(data, dict):
        agents_map = {k.upper(): (v if isinstance(v, dict) else {"info": v}) for k, v in data.items()}
    return JSONResponse({"ok": True, "agents": agents_map, "raw": data})


@router.post("/api/ingest")
async def ingest(request: Request):
    """Ingestion sidebar. URL -> file de veille REELLE (hub /ingest/url, table
    biblio_raw status=unverified). Le hub n'a PAS de classifieur domain/tags a
    l'ingestion : on rend un statut HONNETE (queued), jamais un domain/tags
    fabrique. Texte libre = pas de backend -> refus explicite, pas un faux OK."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    data = (body or {}).get("data") or {}
    url = str(data.get("url") or "").strip()
    text = str(data.get("text") or "").strip()
    if not url:
        msg = ("ingestion texte non branchee — fournir une URL" if text else "url requise")
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    if not url.startswith("http"):
        return JSONResponse({"ok": False, "error": "url invalide (http/https)"}, status_code=400)
    payload = {"url": url, "title": str(data.get("title") or url)[:200], "source": "sidebar"}
    headers = {"Content-Type": "application/json", "X-Agent-Name": "WEBHUB"}
    tok = _hub_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post("http://127.0.0.1:8766/ingest/url", json=payload, headers=headers)
        d = r.json()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}, status_code=502)
    if d.get("ok"):
        return JSONResponse({"ok": True, "queued": True, "id": d.get("id"),
                             "note": "en file de veille (biblio_raw, unverified)"})
    return JSONResponse({"ok": False, "error": d.get("error", "hub refus")}, status_code=502)


# ── Epistemic dashboard : router DEJA PRET dans epistemic.py mais jamais monte.
# On l'attache transitivement (router.include_router) -> il herite du mount de
# wired_router dans app.py, sans toucher app.py (CRITICAL_FILE). Best-effort.
# Page: /epistemic/{topic} · API: /epistemic/api/trajectory|conflicts|heatmap/{topic}.
try:
    from app.web_hub.epistemic import router as _epistemic_router
    if _epistemic_router is not None:
        router.include_router(_epistemic_router, prefix="/epistemic")
except Exception:
    pass


# ── GET UIs /rag, /swarm, /postal : pages orphelines de la wave 1.
# On les expose directement sur le router de wired_routes pour les rendre fonctionnelles
# sur le portail :7400, sans toucher à app.py (CRITICAL_FILE).
@router.get("/rag")
async def rag_page():
    """Page RAG dashboard."""
    from fastapi.responses import HTMLResponse
    p = Path(__file__).resolve().parent / "rag_dashboard.html"
    return HTMLResponse(p.read_text(encoding="utf-8"))


@router.get("/swarm")
async def swarm_page():
    """Page Swarm specialist runner."""
    from fastapi.responses import HTMLResponse
    p = Path(__file__).resolve().parent / "swarm.html"
    return HTMLResponse(p.read_text(encoding="utf-8"))


@router.get("/postal")
async def postal_page():
    """Page Postal mailbox interface."""
    from fastapi.responses import HTMLResponse
    p = Path(__file__).resolve().parent / "postal.html"
    return HTMLResponse(p.read_text(encoding="utf-8"))


# ── Maison — rubrique dashboard flotte edge domotique (portail :7400).
# Logique dans app/forge_edge_fleet.py (organe fleet) ; routes fines ici.
# Protegees par le middleware auth web_hub. ADB = lecture seule allowlist.
@router.get("/maison")
async def maison_page():
    """Dashboard Maison — flotte edge domotique (reel, pas demo)."""
    from fastapi.responses import HTMLResponse
    p = Path(__file__).resolve().parent / "edge_maison.html"
    return HTMLResponse(p.read_text(encoding="utf-8"))


@router.get("/api/edge/fleet")
async def edge_fleet_api():
    """Liste des devices edge (reel). Rafraichit le heartbeat host au passage, et celui des
    noeuds edge http passifs (heartbeat TIRE : ils ne poussent rien)."""
    from app.forge_edge_fleet import list_edges, heartbeat_self, sonder_noeuds_http
    try:
        await asyncio.to_thread(heartbeat_self)  # sync (psutil + ollama probe) hors event-loop
    except Exception:
        pass
    try:
        await asyncio.to_thread(sonder_noeuds_http)
    except Exception:  # muet-ok : un noeud injoignable vieillit en STALE, la liste le montre
        pass
    edges = await asyncio.to_thread(list_edges)
    return JSONResponse(edges)


@router.get("/api/edge/stats")
async def edge_stats_api():
    """Statistiques agregees. Rafraichit le heartbeat host d'abord pour que le
    compteur EN LIGNE colle aux badges de /api/edge/fleet (coherence tuiles/table)."""
    from app.forge_edge_fleet import fleet_stats, heartbeat_self, sonder_noeuds_http
    try:
        await asyncio.to_thread(heartbeat_self)  # meme refresh que /fleet -> statut coherent
    except Exception:
        pass
    try:
        await asyncio.to_thread(sonder_noeuds_http)
    except Exception:  # muet-ok : un noeud injoignable vieillit en STALE, la liste le montre
        pass
    return JSONResponse(await asyncio.to_thread(fleet_stats))


@router.post("/api/edge/heartbeat")
async def edge_heartbeat_api(request: Request):
    """Ingestion heartbeat depuis un device edge externe."""
    from app.forge_edge_fleet import heartbeat_from_http
    try:
        body = await request.json()
        eid = heartbeat_from_http(body)
        return JSONResponse({"ok": True, "edge_id": eid})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/edge/scan")
async def edge_scan_api():
    """Scan ADB : enregistre les devices Android connectes comme edges reels."""
    from app.forge_edge_fleet import scan_adb_into_fleet
    try:
        found = await asyncio.to_thread(scan_adb_into_fleet)
        return JSONResponse({"ok": True, "found": found, "count": len(found)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/edge/adb")
async def edge_adb_api(request: Request):
    """Commande ADB lecture seule (allowlist) sur le device actif."""
    from app.forge_edge_fleet import adb_readonly
    body = await request.json()
    res = await asyncio.to_thread(adb_readonly, body.get("cmd", ""))
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@router.post("/api/edge/adb/control")
async def edge_adb_control_api(request: Request):
    """Controle ADB gouverne (Phase 2) : destructif exige confirm=true.
    Renvoie toujours 200 ; l'etat (ok / needs_confirm / error) est dans le corps.
    """
    from app.forge_edge_fleet import adb_control
    body = await request.json()
    res = await asyncio.to_thread(adb_control, body.get("cmd", ""), bool(body.get("confirm")))
    return JSONResponse(res)


@router.get("/api/edge/ota/files")
async def edge_ota_files_api():
    """Fichiers distribuables depuis le staging OTA (Phase 3)."""
    from app.forge_edge_fleet import list_ota_files
    return JSONResponse(list_ota_files())


@router.post("/api/edge/push")
async def edge_push_api(request: Request):
    """Distribue un fichier OTA vers un edge (Phase 3, checksum verifie)."""
    from app.forge_edge_fleet import push_to_edge
    body = await request.json()
    res = await asyncio.to_thread(push_to_edge, body.get("edge_id", ""),
                                  body.get("filename", ""), body.get("remote_path"))
    return JSONResponse(res)


@router.get("/forge/debate")
async def debate_page():
    """Debat inter-agents — mode LATENT self-model local (RecursiveMAS, ~-60% tokens) ou
    texte-cloud. Page servie ici ; le run tourne en subprocess deporte (torch isole)."""
    from fastapi.responses import HTMLResponse
    here = Path(__file__).resolve().parent
    for cand in (here / "forge_debate.html", here / "templates" / "forge_debate.html"):
        if cand.is_file():
            return HTMLResponse(cand.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<h1>Debat inter-agents</h1><p>GUI en cours de livraison. "
        "API prete : POST /api/debate/run {objective, constraint, rounds, latent}.</p>")


@router.post("/api/debate/run")
async def debate_run_api(request: Request):
    """Lance un debat multi-tour. latent=true -> relais self-model LOCAL (RecursiveMAS,
    ~-60% tokens d'input, CPU ~30-90s) ; sinon texte-cloud. Le debat tourne en SUBPROCESS
    deporte (forge_debate_run_job) : torch/modele JAMAIS charge dans web_hub :7400."""
    import subprocess
    import sys as _sys
    import tempfile
    try:
        body = await request.json()
    except Exception:
        body = {}
    objective = str((body or {}).get("objective") or "").strip()
    if not objective:
        return JSONResponse({"ok": False, "error": "objective requis"}, status_code=400)
    constraint = str((body or {}).get("constraint") or "Repondre concis.").strip()
    try:
        rounds = max(1, min(3, int((body or {}).get("rounds") or 1)))
    except Exception:
        rounds = 1
    latent = bool((body or {}).get("latent"))

    rid = uuid.uuid4().hex[:12]
    work = Path(tempfile.gettempdir()) / "nokido_debate"
    work.mkdir(parents=True, exist_ok=True)
    req_f = work / f"{rid}.req.json"
    out_f = work / f"{rid}.out.json"
    req_f.write_text(json.dumps({"objective": objective, "constraint": constraint,
                                 "rounds": rounds, "latent": latent}), encoding="utf-8")
    launcher = Path(__file__).resolve().parents[2] / "tools" / "forge_debate_run_job.py"
    timeout_s = 150 if latent else 90

    def _run():
        return subprocess.run(
            [_sys.executable, str(launcher), "--params", str(req_f), "--out", str(out_f)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)

    try:
        r = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return JSONResponse({"ok": False, "error": f"debat timeout >{timeout_s}s"}, status_code=504)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=500)
    finally:
        try:
            req_f.unlink()
        except Exception:
            pass

    if r.returncode != 0:
        try:
            out_f.unlink()
        except Exception:
            pass
        return JSONResponse(
            {"ok": False, "error": f"debat rc={r.returncode}: {(r.stderr or '')[-400:]}"},
            status_code=500)
    try:
        res = json.loads(out_f.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"resultat illisible: {e!r}"}, status_code=500)
    finally:
        try:
            out_f.unlink()
        except Exception:
            pass
    res["ok"] = True
    return JSONResponse(res)
