"""
tools/forge_cve_osv_fallback.py — CVE search with NVD primary + OSV.dev fallback.
Caches results in sandbox/cve_cache.json. Retry with exponential backoff.
"""

import argparse
import json
import time
from pathlib import Path

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    import sys

    sys.exit("pip install requests urllib3")

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

CACHE_FILE = Path(__file__).resolve().parent.parent / "sandbox" / "cve_cache.json"
NVD_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
OSV_QUERY = "https://api.osv.dev/v1/query"
OSV_VULN = "https://api.osv.dev/v1/vulns"


def _load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


_CACHE = _load_cache()


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def _get(url: str, **kwargs) -> dict | None:
    for attempt, delay in enumerate([0, 1, 2, 4]):
        if delay:
            time.sleep(delay)
        try:
            r = _session().get(url, timeout=10, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 3:
                print(f"[WARN] GET {url}: {e}")
    return None


def _post(url: str, body: dict) -> dict | None:
    for attempt, delay in enumerate([0, 1, 2, 4]):
        if delay:
            time.sleep(delay)
        try:
            r = _session().post(url, json=body, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 3:
                print(f"[WARN] POST {url}: {e}")
    return None


def search_cve(query: str, ecosystem: str = "PyPI") -> list[dict]:
    # Primary: NVD keyword search
    data = _get(NVD_BASE, params={"keywordSearch": query})
    if data and "vulnerabilities" in data:
        return [v.get("cve", v) for v in data["vulnerabilities"]]

    # Fallback: OSV.dev
    body = {"query": {"package": {"ecosystem": ecosystem, "name": query}}}
    data = _post(OSV_QUERY, body)
    if data:
        return data.get("vulns", [])
    return []


def enrich_cve(cve_id: str) -> dict:
    if cve_id in _CACHE:
        return _CACHE[cve_id]

    # NVD
    data = _get(NVD_BASE, params={"cveId": cve_id})
    if data and data.get("vulnerabilities"):
        result = data["vulnerabilities"][0].get("cve", data["vulnerabilities"][0])
        _CACHE[cve_id] = result
        _save_cache(_CACHE)
        return result

    # OSV fallback
    data = _get(f"{OSV_VULN}/{cve_id}")
    if data:
        _CACHE[cve_id] = data
        _save_cache(_CACHE)
        return data

    return {"id": cve_id, "error": "not_found"}


def batch_enrich(cve_ids: list[str]) -> list[dict]:
    results = []
    for cve_id in tqdm(cve_ids, desc="enriching CVEs", unit="cve"):
        results.append(enrich_cve(cve_id))
    _save_cache(_CACHE)
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", help="Keyword search for CVEs")
    ap.add_argument("--enrich", help="Enrich a single CVE ID")
    ap.add_argument("--batch-file", help="Line-separated CVE IDs file")
    ap.add_argument("--ecosystem", default="PyPI")
    args = ap.parse_args()

    if args.query:
        results = search_cve(args.query, args.ecosystem)
        print(json.dumps(results, indent=2))
    elif args.enrich:
        print(json.dumps(enrich_cve(args.enrich), indent=2))
    elif args.batch_file:
        ids = [l.strip() for l in open(args.batch_file) if l.strip()]
        print(json.dumps(batch_enrich(ids), indent=2))
    else:
        ap.print_help()
