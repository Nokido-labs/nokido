import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# Lecture du fichier original
registry_path = ROOT / "app" / "forge_mcp_registry.py"
content = registry_path.read_text(encoding="utf-8")

# 1. Insertion des imports SpikeRouter au début (après les imports standards)
if "from forge_spike_router import evaluate_intent" not in content:
    content = content.replace(
        "import sqlite3", "import sqlite3\nfrom forge_spike_router import evaluate_intent"
    )

# 2. Patcher dispatch pour inclure l'évaluation sémantique SpikeRouter (Security Layer)
if 'evaluate_intent({"tools":' not in content:
    old_dispatch_start = "    async def dispatch(self, name: str, args: Dict[str, Any], agent: str, ring: int) -> Union[str, Dict[str, Any]]:"
    new_dispatch_start = (
        old_dispatch_start
        + """
        \"\"\"Dispatch avec vérification sécurité + filtre sémantique RAG + SpikeRouter.\"\"\"
        # -- SpikeRouter Semantic Security Layer --
        intent_check = evaluate_intent({"tools": [{"name": name, "arguments": args}]})
        if intent_check.get("status") == "requires_negotiation":
            import json
            return f"SECURITY: Action suspendue. Negociation requise (Human-in-the-loop). Détails: {json.dumps(intent_check)}"
        # -----------------------------------------
"""
    )
    content = content.replace(old_dispatch_start, new_dispatch_start)

# 3. Patcher handle_poll pour lire depuis agent_messages (Sync Fix pour Claude)
if "SELECT payload FROM agent_messages WHERE to_agent=" not in content:
    old_poll = """    async def handle_poll(self, args: dict, agent: str, ring: int) -> str:
        s = self.state_mgr.read_state()
        notifs = s.pop("pending_notifications", [])
        if notifs: self.state_mgr.write_state(s)
        return "\\n".join(notifs) if notifs else "Aucune notification.\""""

    new_poll = """    async def handle_poll(self, args: dict, agent: str, ring: int) -> str:
        \"\"\"Poll unifié : mémoire vive + table agent_messages (Pattern D2).\"\"\"
        # 1. Mémoire vive (volatile)
        s = self.state_mgr.read_state()
        notifs = s.pop("pending_notifications", [])
        if notifs: self.state_mgr.write_state(s)
        
        # 2. Table agent_messages (persistant)
        try:
            import sqlite3 as _sq, json as _js
            conn = _sq.connect(str(self.db_path), timeout=5)
            conn.row_factory = _sq.Row
            # On cherche les messages pour cet agent (ou agt_gemini/agt_claude si identifié)
            target = f"agt_{agent.lower()}"
            res = conn.execute(
                "SELECT id, payload FROM agent_messages WHERE to_agent=? AND status='unread' ORDER BY created_at ASC",
                (target,)
            ).fetchall()
            
            for r in res:
                p = _js.loads(r["payload"])
                txt = p.get("text", str(p))
                notifs.append(f"[{r['id']}] {txt}")
                # Marquer comme lu immédiatement pour éviter le spam au prochain poll
                conn.execute("UPDATE agent_messages SET status='read', read_at=datetime('now') WHERE id=?", (r["id"],))
            
            conn.commit()
            conn.close()
        except Exception as e:
            notifs.append(f"ERR: Poll agent_messages failed: {e}")

        return "\\n".join(notifs) if notifs else "Aucune notification.\""""

    content = content.replace(old_poll, new_poll)

# Sauvegarde — CONDITIONNELLE, et JAMAIS a l'import.
#
# Defaut mesure le 2026-09-13 : ce module reecrivait `app/forge_mcp_registry.py`
# (CRITICAL_FILE) au moment de son IMPORT, hors `governed_edit`. Son unique
# importateur est un NR qui verifie « le module se charge » : le test
# DECLENCHAIT donc une reecriture du registry a chaque passage de CI. Les trois
# patchs ci-dessus sont idempotents, mais l'ecriture, elle, ne l'etait pas.
#
# Le risque n'est pas theorique : les remplacements sont TEXTUELS. Les rejouer
# sur un registry qui a evolue peut produire un module non parsable sur disque
# pendant que le hub tourne en memoire -- meme famille que l'incident du
# 2026-09-08. Le durcissement des ACL (depot en lecture seule pour les bacs a
# sable) a rendu ce defaut visible en le faisant echouer.
if __name__ == "__main__":
    if content == registry_path.read_text(encoding="utf-8"):
        print("Patch MCP Registry : DEJA APPLIQUE, rien a ecrire.")
    else:
        registry_path.write_text(content, encoding="utf-8")
        print("Patch MCP Registry (SpikeRouter + Poll Sync) applique.")
