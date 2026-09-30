
    async def handle_memory(self, args: dict, agent: str, ring: int) -> str:
        """
        Accès lecture à la mémoire et l intelligence de Nokido.
        
        Point d entrée unique pour onboarder un agent collaborateur.
        Droits :
          Ring 0 : toutes les actions
          Ring 1 : context, rules, adr, search, tasks, providers
          Ring 2 : context, search uniquement
        
        Actions :
          context      : briefing projet (ADR + rules + sprint + agents actifs)
          rules        : system_rules (filtre par tag optionnel)
          adr          : adr_records (filtre par status optionnel)
          instructions : system prompts agents dans instruction_library
          providers    : état des providers LLM + scores qualité
          tasks        : tâches agents récentes
          search       : recherche sémantique dans rag_chunks (FTS)
          status       : état système (inspector + network_log récent)
        """
        import sqlite3, json as _json
        
        action = args.get("action", "context")
        
        # Contrôle d accès par action
        ring1_allowed = {"context", "rules", "adr", "search", "tasks", "providers"}
        ring2_allowed = {"context", "search"}
        
        if ring >= 2 and action not in ring2_allowed:
            return _json.dumps({"error": f"Ring {ring} : action '{action}' réservée Ring <= 1"})
        if ring >= 1 and action not in ring1_allowed:
            return _json.dumps({"error": f"Ring {ring} : action '{action}' réservée Ring 0"})
        
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        
        try:
            # ACTION : context (briefing agent - 1 appel pour tout comprendre)
            if action == "context":
                # Sprint actif depuis system_rules tag=sprint
                sprint_rows = conn.execute(
                    "SELECT content FROM system_rules WHERE tag LIKE '%sprint%' OR tag LIKE '%biblio%' LIMIT 3"
                ).fetchall()
                sprint = sprint_rows[0]["content"][:200] if sprint_rows else "Aucun sprint actif trouvé"
                
                # ADR récents
                adr_rows = conn.execute(
                    "SELECT adr_id, title, status FROM adr_records ORDER BY id DESC LIMIT 5"
                ).fetchall()
                
                # Providers UP
                prov_rows = conn.execute(
                    "SELECT provider_id, quality_tier, last_status FROM provider_scores WHERE last_status='ok' ORDER BY calls_total DESC"
                ).fetchall()
                
                # Agents actifs (heartbeats récents)
                fleet = conn.execute(
                    "SELECT agent_id, status FROM fleet_heartbeats ORDER BY last_seen DESC LIMIT 5"
                ).fetchall()
                
                # Stats mémoire
                n_rag = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
                n_adr = conn.execute("SELECT COUNT(*) FROM adr_records").fetchone()[0]
                n_rules = conn.execute("SELECT COUNT(*) FROM system_rules").fetchone()[0]
                n_tasks = conn.execute("SELECT COUNT(*) FROM agent_tasks").fetchone()[0]
                
                # Rules critiques (top 3)
                rules = conn.execute(
                    "SELECT content FROM system_rules ORDER BY id DESC LIMIT 3"
                ).fetchall()
                
                context = {
                    "project": "Nokido Sovereign Hub v18.5",
                    "owner": "user",
                    "hub_url": "http://127.0.0.1:8766/mcp",
                    "active_sprint": sprint[:200],
                    "recent_adr": [{"id": r["adr_id"], "title": r["title"], "status": r["status"]} 
                                   for r in adr_rows],
                    "key_rules": [r["content"][:150] for r in rules],
                    "providers_up": [r["provider_id"] for r in prov_rows],
                    "active_agents": [{"id": r["agent_id"], "status": r["status"]} for r in fleet],
                    "memory_stats": {
                        "rag_chunks": n_rag,
                        "adr_records": n_adr,
                        "system_rules": n_rules,
                        "agent_tasks": n_tasks,
                    },
                    "tools_available": [
                        "memory(context|rules|adr|search|tasks|providers)",
                        "rag(search|index)",
                        "query(sql)",
                        "read(file|tail_logs)",
                        "hub(notify|poll|get_mode)",
                        "task(assign|claim|result|status)",
                        "event(publish|history)",
                    ],
                }
                return _json.dumps(context, ensure_ascii=False, indent=2)
            
            # ACTION : rules
            elif action == "rules":
                tag = args.get("tag")
                limit = min(int(args.get("limit", 20)), 50)
                if tag:
                    rows = conn.execute(
                        "SELECT id, tag, content FROM system_rules WHERE tag=? LIMIT ?", (tag, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, tag, content FROM system_rules LIMIT ?", (limit,)
                    ).fetchall()
                return _json.dumps([{"id": r["id"], "tag": r["tag"], "content": r["content"]} 
                                    for r in rows], ensure_ascii=False, indent=2)
            
            # ACTION : adr
            elif action == "adr":
                status_filter = args.get("status")
                limit = min(int(args.get("limit", 20)), 50)
                if status_filter:
                    rows = conn.execute(
                        "SELECT adr_id, title, status, decision, consequences_pos, consequences_neg, tags "
                        "FROM adr_records WHERE status=? ORDER BY id DESC LIMIT ?", (status_filter, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT adr_id, title, status, decision, consequences_pos, tags "
                        "FROM adr_records ORDER BY id DESC LIMIT ?", (limit,)
                    ).fetchall()
                return _json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)
            
            # ACTION : instructions (system prompts agents)
            elif action == "instructions":
                agent_id = args.get("agent_id")
                if agent_id:
                    row = conn.execute(
                        "SELECT * FROM instruction_library WHERE id=?", (agent_id,)
                    ).fetchone()
                    return _json.dumps(dict(row) if row else {}, ensure_ascii=False, indent=2)
                else:
                    rows = conn.execute(
                        "SELECT id, name, version FROM instruction_library"
                    ).fetchall()
                    return _json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)
            
            # ACTION : providers
            elif action == "providers":
                prov = conn.execute(
                    "SELECT provider_id, agent_id, calls_total, quality_tier, last_status "
                    "FROM provider_scores ORDER BY calls_total DESC"
                ).fetchall()
                fleet = conn.execute(
                    "SELECT agent_id, role, status, last_seen FROM fleet_heartbeats"
                ).fetchall()
                return _json.dumps({
                    "providers": [dict(r) for r in prov],
                    "fleet": [dict(r) for r in fleet],
                }, ensure_ascii=False, indent=2)
            
            # ACTION : tasks
            elif action == "tasks":
                limit = min(int(args.get("limit", 10)), 30)
                status = args.get("status")
                if status:
                    rows = conn.execute(
                        "SELECT task_id, agent_id, description, status, created_at FROM agent_tasks "
                        "WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT task_id, agent_id, description, status, created_at FROM agent_tasks "
                        "ORDER BY created_at DESC LIMIT ?", (limit,)
                    ).fetchall()
                return _json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)
            
            # ACTION : search (FTS dans rag_chunks)
            elif action == "search":
                query = args.get("query", "")
                limit = min(int(args.get("limit", 10)), 30)
                domain = args.get("domain")
                if not query:
                    return _json.dumps({"error": "query obligatoire"})
                # FTS search
                try:
                    if domain:
                        rows = conn.execute(
                            """SELECT rc.id, rc.source, rc.domain, rc.content
                               FROM rag_chunks rc
                               JOIN rag_chunks_fts fts ON rc.id = fts.rowid
                               WHERE rag_chunks_fts MATCH ? AND rc.domain=?
                               ORDER BY rank LIMIT ?""",
                            (query, domain, limit)
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """SELECT rc.id, rc.source, rc.domain, rc.content
                               FROM rag_chunks rc
                               JOIN rag_chunks_fts fts ON rc.id = fts.rowid
                               WHERE rag_chunks_fts MATCH ?
                               ORDER BY rank LIMIT ?""",
                            (query, limit)
                        ).fetchall()
                    results = [{"id": r["id"], "source": r["source"], 
                                "domain": r["domain"],
                                "content": r["content"][:500]} for r in rows]
                except Exception as e:
                    # Fallback LIKE
                    rows = conn.execute(
                        "SELECT id, source, domain, content FROM rag_chunks "
                        "WHERE content LIKE ? LIMIT ?", (f"%{query}%", limit)
                    ).fetchall()
                    results = [{"id": r["id"], "source": r["source"],
                                "domain": r["domain"],
                                "content": r["content"][:500]} for r in rows]
                return _json.dumps({"query": query, "results": results, "count": len(results)},
                                   ensure_ascii=False, indent=2)
            
            # ACTION : status (Ring 0 only)
            elif action == "status":
                inspector = conn.execute(
                    "SELECT created_at, level, payload FROM inspector_log ORDER BY id DESC LIMIT 5"
                ).fetchall()
                network = conn.execute(
                    "SELECT ts, channel, agent, tool, status FROM network_log ORDER BY id DESC LIMIT 10"
                ).fetchall()
                return _json.dumps({
                    "inspector_recent": [dict(r) for r in inspector],
                    "network_recent": [dict(r) for r in network],
                }, ensure_ascii=False, indent=2)
            
            else:
                return _json.dumps({"error": f"action inconnue: {action}"})
        
        finally:
            conn.close()

