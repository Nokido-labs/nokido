# -*- coding: utf-8 -*-
"""forge_hf.py — Client Hugging Face SOUVERAIN Nokido.

Token lu du coffre DPAPI (forge_secrets.get_secret("HF_TOKEN")), JAMAIS du .env.
Trois surfaces :
  - FREE  : whoami, hosting datasets/models (create_repo + upload), download (hf_hub_download).
  - JOBS  : run_job GPU (submit/logs/status/list) — pay-as-you-go (credits requis ; 402 sinon).
  - (CI/CD OIDC = cote GitHub Actions, cf docs/, hors de ce module.)

Composeable par les organes (embed_router, rag_engine, recursivemas). CLI en bas.

Selftest : LAFORGE_PYTHON tools/forge_hf.py whoami
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "metabolisme/provider : client Hugging Face souverain (token du coffre)"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import sys
import json
import argparse


def _token() -> str | None:
    """Token HF : coffre DPAPI d'abord (souverain), env en secours. Jamais imprime."""
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        _app = os.path.join(os.path.dirname(_here), "app")
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app.forge_secrets import get_secret
        t = get_secret("HF_TOKEN")
        if t:
            return t
    except Exception:
        pass
    return get_secret("HF_TOKEN") or get_secret("HUGGINGFACE_TOKEN")


# --------------------------------------------------------------------- FREE tier
def whoami() -> dict:
    from huggingface_hub import whoami as _w
    w = _w(token=_token())
    # champs non-sensibles utiles
    return {k: w.get(k) for k in ("name", "type", "isPro", "canPay", "periodEnd") if k in w}


def upload(path: str, repo_id: str, repo_type: str = "dataset",
           path_in_repo: str | None = None, private: bool = True) -> str:
    """Cree le repo si absent + upload un fichier OU un dossier. FREE (hosting)."""
    from huggingface_hub import HfApi
    api = HfApi(token=_token())
    api.create_repo(repo_id, repo_type=repo_type, private=private, exist_ok=True)
    if os.path.isdir(path):
        api.upload_folder(folder_path=path, repo_id=repo_id, repo_type=repo_type)
    else:
        api.upload_file(path_or_fileobj=path,
                        path_in_repo=path_in_repo or os.path.basename(path),
                        repo_id=repo_id, repo_type=repo_type)
    return "https://huggingface.co/%s/%s" % (
        repo_type + "s" if repo_type in ("dataset", "model") else repo_type, repo_id)


def download(repo_id: str, filename: str, repo_type: str = "dataset",
             local_dir: str | None = None) -> str:
    from huggingface_hub import hf_hub_download
    return hf_hub_download(repo_id=repo_id, filename=filename, repo_type=repo_type,
                           local_dir=local_dir, token=_token())


# --------------------------------------------------------------------- JOBS (pay-as-you-go)
def submit_job(image: str, command, flavor: str = "t4-small",
               env: dict | None = None, secrets: dict | None = None,
               timeout: int | None = None) -> str:
    """Soumet un Job HF (GPU). Requiert des credits pre-payes (sinon 402)."""
    from huggingface_hub import run_job
    if isinstance(command, str):
        command = ["bash", "-c", command]
    job = run_job(image=image, command=command, flavor=flavor,
                  env=env or {}, secrets=secrets or {}, timeout=timeout, token=_token())
    return getattr(job, "id", None) or str(job)


def job_logs(job_id: str) -> str:
    from huggingface_hub import fetch_job_logs
    return "\n".join(fetch_job_logs(job_id=job_id, token=_token()))


def job_status(job_id: str) -> str:
    from huggingface_hub import inspect_job
    j = inspect_job(job_id=job_id, token=_token())
    st = getattr(j, "status", None)
    return getattr(st, "stage", None) or str(st) or str(j)


def list_jobs_() -> list:
    from huggingface_hub import list_jobs
    return [getattr(j, "id", str(j)) for j in list_jobs(token=_token())]


# --------------------------------------------------------------------- CLI
def main() -> int:
    p = argparse.ArgumentParser(prog="forge_hf", description="Client HF souverain Nokido")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami")

    up = sub.add_parser("upload")
    up.add_argument("path")
    up.add_argument("repo_id")
    up.add_argument("--type", default="dataset", dest="repo_type")
    up.add_argument("--in-repo", default=None, dest="path_in_repo")
    up.add_argument("--public", action="store_true")

    dl = sub.add_parser("download")
    dl.add_argument("repo_id")
    dl.add_argument("filename")
    dl.add_argument("--type", default="dataset", dest="repo_type")
    dl.add_argument("--dir", default=None, dest="local_dir")

    sj = sub.add_parser("submit")
    sj.add_argument("--image", default="ubuntu")
    sj.add_argument("--flavor", default="t4-small")
    sj.add_argument("--cmd", required=True, help="commande bash (string)")
    sj.add_argument("--timeout", type=int, default=None)

    lg = sub.add_parser("logs")
    lg.add_argument("job_id")
    st = sub.add_parser("status")
    st.add_argument("job_id")
    sub.add_parser("jobs")

    a = p.parse_args()
    if a.cmd == "whoami":
        print(json.dumps(whoami(), ensure_ascii=False))
    elif a.cmd == "upload":
        print(upload(a.path, a.repo_id, a.repo_type, a.path_in_repo, private=not a.public))
    elif a.cmd == "download":
        print(download(a.repo_id, a.filename, a.repo_type, a.local_dir))
    elif a.cmd == "submit":
        print(submit_job(a.image, a.cmd, a.flavor, timeout=a.timeout))
    elif a.cmd == "logs":
        print(job_logs(a.job_id))
    elif a.cmd == "status":
        print(job_status(a.job_id))
    elif a.cmd == "jobs":
        print(json.dumps(list_jobs_(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
