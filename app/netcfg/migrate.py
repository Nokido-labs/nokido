import sqlite3
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "recon_silo" / "recon_data" / "recon.db"


def migrate():
    print(f"[*] Starting netcfg migration on {DB_PATH}")

    if not DB_PATH.parent.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # 1. netcfg_equipment
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS netcfg_equipment (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_mgmt         TEXT NOT NULL UNIQUE,
        hostname        TEXT NOT NULL,
        vendor_key      TEXT NOT NULL,
        model           TEXT,
        os_version      TEXT,
        location        TEXT,
        visio_shape_id  TEXT,
        keepass_entry   TEXT,
        first_seen      TEXT NOT NULL,
        last_verified   TEXT NOT NULL,
        status          TEXT DEFAULT 'active'
    )
    """)

    # 2. netcfg_config_backup
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS netcfg_config_backup (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        equipment_id    INTEGER NOT NULL REFERENCES netcfg_equipment(id),
        taken_at        TEXT NOT NULL,
        config_type     TEXT NOT NULL,
        config_text     TEXT NOT NULL,
        sha256          TEXT NOT NULL,
        size_bytes      INTEGER NOT NULL,
        triggered_by    TEXT NOT NULL
    )
    """)

    # 3. netcfg_deploy_log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS netcfg_deploy_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          TEXT NOT NULL,
        equipment_id    INTEGER NOT NULL REFERENCES netcfg_equipment(id),
        step_index      INTEGER NOT NULL,
        gate            TEXT NOT NULL,
        operator        TEXT NOT NULL,
        commands        TEXT,
        stdout          TEXT,
        stderr          TEXT,
        dry_run         INTEGER NOT NULL,
        validated       INTEGER NOT NULL,
        ts              TEXT NOT NULL,
        hash_prev       TEXT,
        hash_current    TEXT NOT NULL
    )
    """)

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_deploy_log_run ON netcfg_deploy_log(run_id, step_index)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_equipment_mgmt ON netcfg_equipment(ip_mgmt)")

    conn.commit()
    conn.close()
    print("[+] Migration completed successfully.")


if __name__ == "__main__":
    migrate()
