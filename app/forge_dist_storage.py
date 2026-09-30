"""forge_dist_storage.py — Distribution storage R2/HF/OneDrive + sanitize pipeline.

Source roadmap_distribution_storage. Pipeline sanitize OBLIGATOIRE :
- Phase A : drop PII (emails, phones, IPs internes)
- Phase B : anonymize (hash author, replace path home dir, etc.)
- Phase C : whitelist (only public-tier sources/domains)

Then upload to choice of :
- Cloudflare R2 (S3-compat, free 10 GB)
- Hugging Face datasets (free public)
- OneDrive (5 GB free perso)

API :
- sanitize_chunk(chunk: dict) -> chunk_clean
- export_sanitized(output_path, max_chunks=10000)
- upload_r2(file_path, bucket)
- upload_hf(file_path, dataset_repo)
"""

from __future__ import annotations
import argparse, json, os, re, sqlite3, sys
from pathlib import Path
from nokido_agent.app.forge_secrets import get_secret
from nokido_agent.app.forge_git_egress import identites_privees

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


# --- Phase A : PII drop ---

PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"\b(?:\+33|0)[1-9](?:[\s.-]?\d{2}){4}\b"), "[PHONE_FR]"),
    (re.compile(r"\b(?:192\.168|10\.|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"), "[IP_PRIV]"),
    (re.compile(r"\b[A-Z]{2}\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}\b"), "[IBAN]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{30,}"), "[API_KEY]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{30,}"), "[GH_TOKEN]"),
]

# --- Phase B : anonymize ---

HOME_DIRS = (
    re.compile(r"C:\\Users\\[^\\]+\\"),  # Windows home
    re.compile(r"/home/[^/]+/"),  # Linux home
    re.compile(r"/Users/[^/]+/"),  # macOS home
)
# Pseudonymes publics ici ; l'identite CIVILE vient de la liste privee, jamais du
# code publie (decision owner 2026-09-30 : le motif la citait en clair).
USERNAME_PATTERNS = (re.compile(r"\b(?:naarobb|user)\b", re.IGNORECASE), *identites_privees())

# --- Phase C : whitelist sources ---

WHITELIST_DOMAINS = (
    "arxiv.org",
    "openalex.org",
    "doi.org",
    "github.com",
    "stackoverflow.com",
    "semanticscholar.org",
    "biorxiv.org",
    "medrxiv.org",
    "openreview.net",
    "papers.nips.cc",
    "aclanthology.org",
    "proceedings.mlr.press",
    "wikipedia.org",
    "developer.mozilla.org",
)


def sanitize_text(text: str) -> str:
    """Apply Phase A + B sanitization to text."""
    if not text:
        return text
    # Phase A : PII drop
    for pattern, replacement in PII_PATTERNS:
        text = pattern.sub(replacement, text)
    # Phase B : anonymize home dirs + usernames
    for p in HOME_DIRS:
        text = p.sub("/HOME/", text)
    for p in USERNAME_PATTERNS:
        text = p.sub("[USER]", text)
    return text


def is_whitelisted_source(source: str | None) -> bool:
    """Phase C : check source URL belongs to whitelist."""
    if not source:
        return False
    src_low = source.lower()
    return any(domain in src_low for domain in WHITELIST_DOMAINS)


def sanitize_chunk(chunk: dict) -> dict | None:
    """Sanitize 1 chunk. Returns None if rejected by whitelist."""
    source = chunk.get("source") or ""
    if source.startswith("http") and not is_whitelisted_source(source):
        return None  # reject non-whitelisted public source

    return {
        "id": chunk.get("id"),
        "text": sanitize_text(chunk.get("text") or ""),
        "source": source if is_whitelisted_source(source) else "[INTERNAL]",
        "domain": chunk.get("domain"),
        "ingested_at": chunk.get("ingested_at"),
        "embedding_model": chunk.get("embedding_model"),
    }


def export_sanitized(output_path: Path, max_chunks: int = 10000, domain_filter: str = None) -> dict:
    """Export sanitized chunks to JSONL."""
    if not DB.exists():
        return {"error": "DB missing"}

    con = sqlite3.connect(str(DB), timeout=10)
    where = f"WHERE domain='{domain_filter}'" if domain_filter else ""
    rows = con.execute(
        f"SELECT id, text, source, domain, ingested_at, embedding_model FROM rag_chunks {where} LIMIT ?", (max_chunks,)
    ).fetchall()
    con.close()

    output_path.parent.mkdir(exist_ok=True, parents=True)
    n_total = 0
    n_kept = 0
    n_rejected = 0
    n_sanitized = 0

    with open(output_path, "w", encoding="utf-8") as f:
        for r in rows:
            n_total += 1
            chunk = {
                "id": r[0],
                "text": r[1],
                "source": r[2],
                "domain": r[3],
                "ingested_at": r[4],
                "embedding_model": r[5],
            }
            original_text = chunk["text"] or ""
            clean = sanitize_chunk(chunk)
            if clean is None:
                n_rejected += 1
                continue
            if clean["text"] != original_text:
                n_sanitized += 1
            f.write(json.dumps(clean, ensure_ascii=False) + "\n")
            n_kept += 1

    return {
        "output": str(output_path),
        "total_chunks": n_total,
        "kept": n_kept,
        "rejected_whitelist": n_rejected,
        "sanitized_pii": n_sanitized,
    }


def upload_r2(file_path: Path, bucket: str, key: str = None) -> dict:
    """Upload to Cloudflare R2 (requires R2_ACCESS_KEY + R2_SECRET_KEY env)."""
    access = get_secret("R2_ACCESS_KEY")
    secret = get_secret("R2_SECRET_KEY")
    account = os.environ.get("R2_ACCOUNT_ID")
    if not (access and secret and account):
        return {"error": "R2 credentials missing (R2_ACCESS_KEY / R2_SECRET_KEY / R2_ACCOUNT_ID)"}

    try:
        import boto3
    except ImportError:
        return {"error": "pip install boto3 required"}

    key = key or file_path.name
    endpoint = f"https://{account}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
    )
    s3.upload_file(str(file_path), bucket, key)
    return {
        "ok": True,
        "url": f"{endpoint}/{bucket}/{key}",
        "size_mb": round(file_path.stat().st_size / 1024 / 1024, 2),
    }


def upload_hf(file_path: Path, dataset_repo: str) -> dict:
    """Upload to HuggingFace datasets (requires HF_TOKEN env)."""
    token = get_secret("HF_TOKEN")
    if not token:
        return {"error": "HF_TOKEN missing"}
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return {"error": "pip install huggingface_hub required"}

    api = HfApi(token=token)
    api.upload_file(
        path_or_fileobj=str(file_path),
        path_in_repo=file_path.name,
        repo_id=dataset_repo,
        repo_type="dataset",
    )
    return {"ok": True, "repo": dataset_repo, "file": file_path.name}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    exp = sub.add_parser("export")
    exp.add_argument("--output", type=str, required=True)
    exp.add_argument("--max-chunks", type=int, default=10000)
    exp.add_argument("--domain", type=str)
    r2 = sub.add_parser("upload-r2")
    r2.add_argument("--file", type=str, required=True)
    r2.add_argument("--bucket", type=str, required=True)
    hf = sub.add_parser("upload-hf")
    hf.add_argument("--file", type=str, required=True)
    hf.add_argument("--repo", type=str, required=True)
    args = ap.parse_args()

    if args.cmd == "export":
        result = export_sanitized(Path(args.output), args.max_chunks, args.domain)
    elif args.cmd == "upload-r2":
        result = upload_r2(Path(args.file), args.bucket)
    elif args.cmd == "upload-hf":
        result = upload_hf(Path(args.file), args.repo)
    else:
        ap.print_help()
        return
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
