# -*- coding: utf-8 -*-
"""
tools/forge_cli_hygiene_session_prototype.py
Prototype for Async Session Resume registry and CLI Output Hygiene pipeline.
"""
from __future__ import annotations

import re
import time
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "RAG" / "session_registry_proto.db"

class SessionRegistry:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_registry (
                session_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                status TEXT NOT NULL,
                checkpoint_json TEXT,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def create_session(self, session_id: str, agent_id: str, checkpoint: dict) -> dict:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO session_registry VALUES (?, ?, ?, ?, ?)",
            (session_id, agent_id, "active", json.dumps(checkpoint), time.time())
        )
        conn.commit()
        conn.close()
        return {"session_id": session_id, "status": "active"}

    def mark_stale(self, session_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE session_registry SET status='stale', updated_at=? WHERE session_id=?", (time.time(), session_id))
        conn.commit()
        conn.close()

    def resume_session(self, session_id: str) -> dict | None:
        conn = sqlite3.connect(self.db_path)
        r = conn.execute("SELECT agent_id, status, checkpoint_json FROM session_registry WHERE session_id=?", (session_id,)).fetchone()
        conn.close()
        if not r:
            return None
        return {
            "agent_id": r[0],
            "previous_status": r[1],
            "checkpoint": json.loads(r[2])
        }


class CLIHygiene:
    ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    @classmethod
    def strip_ansi(cls, text: str) -> str:
        """Removes terminal ANSI color/style escape codes."""
        return cls.ANSI_ESCAPE.sub('', text)

    @classmethod
    def collapse_progress_bars(cls, text: str) -> str:
        """Collapses carriage-return (\r) progress bars keeping only the last state."""
        lines = text.split('\r')
        if not lines:
            return text
        # If carriage returns exist, clean them up by taking the last state in groups
        output_lines = []
        for l in lines:
            cleaned = l.strip()
            if cleaned:
                # Simple check to see if it looks like a progress bar
                if '[' in cleaned and ']' in cleaned and ('=' in cleaned or '#' in cleaned or '%' in cleaned):
                    # Keep only if it's the last progress update or has a status
                    if '100%' in cleaned or 'done' in cleaned or l == lines[-1]:
                        output_lines.append(cleaned)
                else:
                    output_lines.append(l)
        return '\n'.join(output_lines)

    @classmethod
    def summarize_errors(cls, text: str) -> str:
        """Extracts and summarizes standard Python/Node error tracebacks."""
        if "Traceback (most recent call last):" in text:
            lines = text.split('\n')
            tb_index = -1
            for idx, l in enumerate(lines):
                if "Traceback (most recent call last):" in l:
                    tb_index = idx
                    break
            if tb_index != -1:
                # The actual error line is usually the last line of the traceback
                err_lines = [l.strip() for l in lines[tb_index:] if l.strip()]
                if err_lines:
                    return f"[TRUNCATED TRACEBACK] Summary: {err_lines[-1]}"
        return text

    @classmethod
    def truncate_output(cls, text: str, max_chars: int = 1000) -> str:
        """Truncates very long output preserving head and tail."""
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        head = text[:half]
        tail = text[-half:]
        omitted_lines = text[half:-half].count('\n')
        return f"{head}\n\n... [TRUNCATED: Omitted {omitted_lines} lines / {len(text) - max_chars} chars] ...\n\n{tail}"

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Runs the complete hygiene pipeline."""
        t = cls.strip_ansi(text)
        t = cls.collapse_progress_bars(t)
        t = cls.summarize_errors(t)
        t = cls.truncate_output(t)
        return t


def main():
    print("=== Nokido Hub CLI Hygiene & Session Resume Prototype ===")
    
    # 1. Test Session Registry
    reg = SessionRegistry()
    sess_id = "sess_test_123"
    print(f"\n1. Creating Session {sess_id}...")
    reg.create_session(sess_id, "wrk_laforge", {"current_step": 3, "target_file": "app/core.py"})
    
    print("Simulating agent crash / marking session as stale...")
    reg.mark_stale(sess_id)
    
    print("Resuming session...")
    restored = reg.resume_session(sess_id)
    print(f"Restored session state: {restored}")

    # 2. Test CLI Output Hygiene
    dirty_output = (
        "\x1b[32m[INFO] Starting pip install...\x1b[0m\r"
        "Downloading package [===>                      ] 15%\r"
        "Downloading package [=========>                ] 45%\r"
        "Downloading package [==========================] 100% (done)\n"
        "\x1b[31m[ERROR] Installation failed with traceback:\x1b[0m\n"
        "Traceback (most recent call last):\n"
        "  File \"setup.py\", line 12, in <module>\n"
        "    import missing_package\n"
        "ModuleNotFoundError: No module named 'missing_package'\n"
        + "A" * 1200 # simulate long output
    )
    
    print("\n2. Sanitizing Dirty CLI Output...")
    print("--- RAW OUTPUT (truncated view) ---")
    print(dirty_output[:300] + "\n...")
    
    print("\n--- SANITIZED OUTPUT ---")
    sanitized = CLIHygiene.sanitize(dirty_output)
    print(sanitized)

if __name__ == "__main__":
    main()
