"""forge_cve_rag_ingest.py — GELÉ le 2026-09-27. Ne plus appeler, ne pas rebrancher.

Il téléchargeait le flux NVD « 1.1 » et l'indexait dans RAG/embeddings.db. Ce flux rend 403 : mesuré le
27/09 (sandbox/workspace/mesure_nvd_flux_2026-09-27.json), quand l'API 2.0 rend 200. Successeur, déjà en
place : tools/forge_cve_nvd_download.py (API 2.0, fetch_recent / fetch_year / ingest_to_rag).

Geler, pas supprimer : run() refuse EN LE DISANT, avant tout accès réseau et toute écriture en base
(NR tests/nr/test_cve_ingest_nvd11_gele_nr.py). _download et _parse restent pour lecture ; le corps
d'ingestion d'avant le gel se relit dans l'historique git de ce fichier.
"""

import gzip
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
NVD_URL = "https://nvd.nist.gov/feeds/json/cve/1.1/nvdcve-1.1-recent.json.gz"

GELE = (
    "forge_cve_rag_ingest est GELÉ depuis le 2026-09-27 : le flux NVD 1.1 qu'il vise rend 403 "
    "(mesuré le 27/09, sandbox/workspace/mesure_nvd_flux_2026-09-27.json). Successeur : "
    "tools/forge_cve_nvd_download.py (API 2.0). Rien n'a été téléchargé ni écrit."
)


class OutilGele(RuntimeError):
    """Refus d'un outil gelé : jamais un échec muet ni un zéro silencieux."""


def _download():
    req = urllib.request.Request(NVD_URL, headers={"User-Agent": "LaForge/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return gzip.decompress(resp.read())


def _parse(data: bytes) -> list:
    items = json.loads(data).get("CVE_Items", [])
    entries = []
    for item in items:
        cve_id = item["cve"]["CVE_data_meta"]["ID"]
        desc_list = item["cve"]["description"]["description_data"]
        description = desc_list[0]["value"] if desc_list else ""
        year = item.get("publishedDate", "0000")[:4]
        try:
            severity = item["impact"]["baseMetricV3"]["cvssV3"]["baseScore"]
        except (KeyError, TypeError):
            severity = "N/A"
        text = f"{cve_id} [cvss={severity}] {description}"
        entries.append((cve_id, year, text))
    return entries


def run(db_path: Path = DB) -> int:
    raise OutilGele(GELE)


if __name__ == "__main__":
    try:
        run()
    except OutilGele as e:
        print(e, file=sys.stderr)
        sys.exit(2)
