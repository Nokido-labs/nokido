#!/usr/bin/env python
"""tools/index_cve_rag.py — Indexe CVEs dans RAG domain=cve_oracle.

Source: data/cve_feed.json (format NVD) ou 5 exemples demo.
"""

import hashlib
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
CVE_FILE = ROOT / "data" / "cve_feed.json"

_DEMO_CVES = [
    (
        "CVE-2024-3094",
        "XZ Utils backdoor: malicious code injected in liblzma 5.6.0/5.6.1 via build system (supply chain). CVSS 10.0.",
    ),
    (
        "CVE-2024-21626",
        "runc container escape via /proc/self/fd leak — attacker gains host FS write from container.",
    ),
    (
        "CVE-2024-6387",
        "OpenSSH regreSSHion: race condition in signal handler allows unauthenticated RCE as root (glibc Linux).",
    ),
    (
        "CVE-2023-44487",
        "HTTP/2 Rapid Reset: stream cancellation loop causes server-side DoS — affects most HTTP/2 stacks.",
    ),
    (
        "CVE-2021-44228",
        "Log4Shell: JNDI injection in Log4j2 message lookup — unauthenticated RCE, CVSS 10.0.",
    ),
]


def _load_cves() -> list[tuple[str, str]]:
    """Retourne liste (cve_id, description)."""
    if CVE_FILE.exists():
        data = json.loads(CVE_FILE.read_text("utf-8", errors="replace"))
        items = data.get("CVE_Items") or data.get("items") or []
        result = []
        for item in items:
            try:
                cve_id = item["cve"]["CVE_data_meta"]["ID"]
                descs = item.get("cve", {}).get("description", {}).get("description_data", [])
                desc = next((d["value"] for d in descs if d.get("lang") == "en"), "no description")
                result.append((cve_id, desc))
            except (KeyError, StopIteration):
                continue
        if result:
            return result
    return _DEMO_CVES


def main() -> None:
    cves = _load_cves()
    conn = sqlite3.connect(str(DB), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    count = 0

    for cve_id, description in cves:
        text = f"{cve_id}: {description}"
        source = f"cve:{cve_id}"
        chunk_id = hashlib.sha256((source + text).encode()).hexdigest()[:16]
        conn.execute(
            "INSERT OR REPLACE INTO rag_chunks "
            "(id, text, source, domain, role_hint, embedding, quality_score, ingested_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (chunk_id, text, source, "cve_oracle", "reference", None, 0.9, now),
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"[cve_oracle] inserted/updated {count} CVEs in {DB}")


if __name__ == "__main__":
    main()
