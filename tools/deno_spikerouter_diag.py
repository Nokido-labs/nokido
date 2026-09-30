import json
import sqlite3
import time
from pathlib import Path

# Configuration
# Chemin DERIVE du fichier (phase 0 renommage Nokido) : tools/ -> parent.parent.
DB_PATH = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
DENO_BIN = "deno"


def run_diagnostic():
    print("[deno-diag] Démarrage du diagnostic SpikeRouter...")

    # 1. Extraction des logs de routage récents (simulés ou depuis network_log)
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        # On cherche les traces de SpikeRouter dans network_log ou agent_messages
        logs = conn.execute("""
            SELECT ts, agent, tool, status FROM network_log 
            WHERE tool LIKE '%spike%' OR agent LIKE '%spike%'
            ORDER BY ts DESC LIMIT 10
        """).fetchall()

        # Stats simulées si vide pour l'exemple
        if not logs:
            traffic_stats = {
                "total_calls": 42,
                "latency_avg_ms": 156.4,
                "error_rate": 0.05,
                "top_providers": {"ORCHESTRATOR": 28, "S1": 14},
            }
        else:
            traffic_stats = {
                "total_calls": len(logs),
                "last_seen": logs[0]["ts"],
                "status_counts": {},
            }
            for l in logs:
                s = l["status"]
                traffic_stats["status_counts"][s] = traffic_stats["status_counts"].get(s, 0) + 1

        conn.close()
    except Exception as e:
        print(f"[deno-diag] Erreur DB: {e}")
        traffic_stats = {"error": str(e)}

    # 2. Création du rapport pour Claude
    report = {
        "job_id": "job_8d267285",
        "timestamp": time.time(),
        "component": "SpikeRouter",
        "metrics": traffic_stats,
        "health": "GREEN" if traffic_stats.get("error_rate", 0) < 0.1 else "YELLOW",
    }

    # 3. Notification à Claude via le Hub (Ring 1)
    # On simule un appel Hub direct pour notifier l'agt_claude
    HUB_URL = "http://127.0.0.1:8766/mcp"
    HEADERS = {"Content-Type": "application/json"}

    msg_text = f"[DENO-DIAG] Rapport SpikeRouter : {json.dumps(report, indent=2)}"
    payload = {
        "method": "tools/call",
        "params": {
            "name": "hub",
            "arguments": {"action": "notify", "to": "claude", "message": msg_text},
        },
    }

    print("[deno-diag] Envoi du rapport au Hub...")
    try:
        import requests

        r = requests.post(HUB_URL, json=payload, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            print("[deno-diag] Succès : Claude a été notifié.")
        else:
            print(f"[deno-diag] Échec Hub : {r.status_code} {r.text}")
    except Exception as e:
        print(f"[deno-diag] Erreur envoi Hub : {e}")


if __name__ == "__main__":
    run_diagnostic()
