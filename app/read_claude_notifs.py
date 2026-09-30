import sqlite3
import os

db_path = "LaForge/RAG/embeddings.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    # On cherche les notifications destinées à Gemini
    cursor.execute(
        "SELECT id, message FROM tui_notifications WHERE message LIKE '%[CLAUDE->GEMINI]%' AND status='unread'"
    )
    rows = cursor.fetchall()

    if rows:
        for rid, msg in rows:
            print(f"--- NOTIF {rid} ---")
            print(msg)
            # On marque comme lu
            cursor.execute("UPDATE tui_notifications SET status='read' WHERE id=?", (rid,))
        conn.commit()
    else:
        print("Aucun nouveau message de Claude.")
    conn.close()
