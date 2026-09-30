"""forge_cve_nvd_download.py — Download NVD CVE 2.0 feed and ingest into RAG embeddings.db.

NVD 1.1 gz feeds removed Dec 2023. Uses NVD 2.0 REST API with pagination.
Rate limit: 5 req/30s unauthenticated, 50 req/30s with API key (NVD_API_KEY env).
"""

import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAG_DB = ROOT / "RAG" / "embeddings.db"

NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
PAGE_SIZE = 2000
RATE_DELAY = 6.5  # seconds between requests (unauthenticated: 5req/30s)


def _nvd_request(params: dict) -> dict:
    api_key = os.getenv("NVD_API_KEY", "")
    headers = {"User-Agent": "LaForge/1.0"}
    if api_key:
        headers["apiKey"] = api_key
    url = NVD_API + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    return {}


def fetch_recent(days: int = 30) -> list[dict]:
    """Fetch CVEs published/modified in last N days."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    fmt = "%Y-%m-%dT%H:%M:%S"
    params = {
        "lastModStartDate": start.strftime(fmt),
        "lastModEndDate": end.strftime(fmt),
        "resultsPerPage": PAGE_SIZE,
        "startIndex": 0,
    }
    entries = []
    total = None
    with tqdm(desc="NVD recent", unit="cve") as pbar:
        while True:
            data = _nvd_request(params)
            vulns = data.get("vulnerabilities", [])
            entries.extend(vulns)
            if total is None:
                total = data.get("totalResults", 0)
                pbar.total = total
            pbar.update(len(vulns))
            params["startIndex"] += len(vulns)
            if params["startIndex"] >= total or not vulns:
                break
            time.sleep(RATE_DELAY)
    return entries


def fetch_year(year: int) -> list[dict]:
    """Fetch all CVEs published in a given year."""
    params = {
        "pubStartDate": f"{year}-01-01T00:00:00",
        "pubEndDate": f"{year}-12-31T23:59:59",
        "resultsPerPage": PAGE_SIZE,
        "startIndex": 0,
    }
    entries = []
    total = None
    with tqdm(desc=f"NVD {year}", unit="cve") as pbar:
        while True:
            data = _nvd_request(params)
            vulns = data.get("vulnerabilities", [])
            entries.extend(vulns)
            if total is None:
                total = data.get("totalResults", 0)
                pbar.total = total
            pbar.update(len(vulns))
            params["startIndex"] += len(vulns)
            if params["startIndex"] >= total or not vulns:
                break
            time.sleep(RATE_DELAY)
    return entries


def parse_vulns(vulns: list[dict]) -> list[dict]:
    """Normalize NVD 2.0 vulnerability objects into flat dicts."""
    entries = []
    for v in vulns:
        cve = v.get("cve", {})
        cve_id = cve.get("id", "")
        published = cve.get("published", "")
        year = published[:4] if published else "0000"
        descs = cve.get("descriptions", [])
        desc = next((d["value"] for d in descs if d.get("lang") == "en"), "")
        # CVSS score: prefer v3.1 > v3.0 > v2
        score = "N/A"
        metrics = cve.get("metrics", {})
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            m = metrics.get(key, [])
            if m:
                score = m[0].get("cvssData", {}).get("baseScore", "N/A")
                break
        cpes = []
        for cfg in cve.get("configurations", []):
            for node in cfg.get("nodes", []):
                for cm in node.get("cpeMatch", []):
                    cpes.append(cm.get("criteria", ""))
        entries.append(
            {
                "cve_id": cve_id,
                "description": desc,
                "cvss_score": score,
                "published_date": published,
                "year": year,
                "cpe_list": cpes,
            }
        )
    return entries


def ingest_to_rag(entries: list[dict], db_path: Path = RAG_DB) -> int:
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE IF NOT EXISTS rag_chunks "
        "(id TEXT PRIMARY KEY, source TEXT, text TEXT, embedding BLOB)"
    )
    inserted = 0
    for e in tqdm(entries, desc="Ingest RAG", unit="chunk"):
        source = f"cve/nvd/{e['year']}"
        text = f"{e['cve_id']} [cvss={e['cvss_score']}] {e['description']}"
        chunk_id = sha256((source + text).encode()).hexdigest()[:16]
        cur = con.execute(
            "INSERT OR IGNORE INTO rag_chunks (id, source, text) VALUES (?, ?, ?)",
            (chunk_id, source, text),
        )
        inserted += cur.rowcount
    con.commit()
    con.close()
    return inserted


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Ingest NVD CVE feed into RAG")
    ap.add_argument("--year", type=int, default=0, help="specific year (0=recent 30d)")
    ap.add_argument("--days", type=int, default=30, help="days back for recent mode")
    args = ap.parse_args()

    if args.year:
        print(f"Fetching NVD {args.year}...")
        vulns = fetch_year(args.year)
    else:
        print(f"Fetching NVD recent ({args.days}d)...")
        vulns = fetch_recent(args.days)

    entries = parse_vulns(vulns)
    print(f"Parsed {len(entries)} CVEs")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    label = str(args.year) if args.year else "recent"
    out = DATA_DIR / f"cve_feed_{label}.json"
    out.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    inserted = ingest_to_rag(entries)
    print(f"Inserted {inserted} new chunks into RAG")
