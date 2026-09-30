import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def main():
    sql_file = Path(sys.argv[1] if len(sys.argv) > 1 else "migrations/004_biblio_alpha.sql")
    db_path = sys.argv[2] if len(sys.argv) > 2 else "RAG/embeddings.db"

    if not sql_file.exists():
        print(f"[ERROR] {sql_file} not found")
        sys.exit(1)

    start_time = datetime.now()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Ensure WAL mode is active
        cursor.execute("PRAGMA journal_mode=WAL;")
        journal_mode = cursor.fetchone()
        if journal_mode[0].upper() != "WAL":
            print("[ERROR] Failed to activate WAL mode")
            sys.exit(1)

        # Create _migrations table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
        """)

        # Check if migration already applied
        cursor.execute("SELECT 1 FROM _migrations WHERE filename = ?", (sql_file.name,))
        if cursor.fetchone():
            print(f"[INFO] {sql_file.name} already applied, skipping")
            sys.exit(0)

        # Apply migration
        with open(sql_file) as f:
            sql_script = f.read()
            cursor.executescript(sql_script)

        # Record migration
        cursor.execute(
            "INSERT INTO _migrations (filename, applied_at) VALUES (?, ?)",
            (sql_file.name, datetime.now().isoformat()),
        )
        conn.commit()

        duration = (datetime.now() - start_time).total_seconds() * 1000
        print(f"[INFO] OK applied {sql_file.name} in {duration:.2f} ms")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] {sql_file.name} failed: {e}")
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
