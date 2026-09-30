import sqlite3
import os

def main():
    db_path = "LaForge/hub.db"
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Tables: {tables}")
        
        cursor.execute("SELECT zone_name, content FROM blackboard WHERE zone_name='audit_oauth'")
        row = cursor.fetchone()
        if row:
            print(f"Zone: {row[0]}")
            print("Content:")
            print(row[1])
        else:
            print("Zone 'audit_oauth' not found.")
            # List all zones
            cursor.execute("SELECT DISTINCT zone_name FROM blackboard")
            zones = cursor.fetchall()
            print(f"Available zones: {zones}")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
