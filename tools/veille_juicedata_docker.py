#!/usr/bin/env python3
"""Veille docker-ISOLEE sur github.com/juicedata (JuiceFS).

Clone les repos phares dans un conteneur alpine/git (contenu externe NON-FIABLE
CONTENU en sandbox docker, cf risque injection indirecte GitLost), extrait .md/.go,
depose des dumps dans data/gitingest/ -> auto-ingest RAG (pattern repo_ingestion
d'autonomous_loops). Lancer via run action=trusted_script (docker = privilege trusted).
"""
import os
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent
GI = REPO / "data" / "gitingest"
GI.mkdir(parents=True, exist_ok=True)
WORK = pathlib.Path("C:/tmp/veille_juicedata_repos")
WORK.mkdir(parents=True, exist_ok=True)
# Bypass du credential helper docker casse (image publique, aucune auth requise)
_CFG = pathlib.Path("C:/tmp/dockercfg_clean")
_CFG.mkdir(parents=True, exist_ok=True)
(_CFG / "config.json").write_text("{}", encoding="utf-8")
_ENV = {**os.environ, "DOCKER_CONFIG": str(_CFG)}
REPOS = ["juicefs", "juicefs-csi-driver", "juicesync", "juicefs-operator"]


def main():
    mount = str(WORK).replace("\\", "/")
    for r in REPOS:
        dst = WORK / r
        if not (dst.exists() and any(dst.iterdir())):
            try:
                rc = subprocess.run(
                    ["docker", "run", "--rm", "-v", f"{mount}:/out", "alpine/git",
                     "clone", "--depth", "1",
                     f"https://github.com/juicedata/{r}", f"/out/{r}"],
                    capture_output=True, text=True, errors="replace", timeout=200, env=_ENV)
                if rc.returncode != 0:
                    print(f"clone FAIL {r}: {(rc.stderr or '')[:120]}")
                    continue
            except Exception as e:
                print(f"clone ERR {r}: {e}")
                continue
        parts = []
        for ext in ("*.md", "*.go"):
            for p in list(dst.rglob(ext))[:100]:
                try:
                    parts.append(f"===== juicedata/{r}/{p.relative_to(dst)} =====\n"
                                 + p.read_text(encoding="utf-8", errors="ignore")[:5000])
                except Exception:
                    pass
        if parts:
            (GI / f"juicedata_{r}.txt").write_text(
                "\n\n".join(parts)[:400000], encoding="utf-8")
            print(f"dump {r}: {len(parts)} fichiers -> data/gitingest/")
        else:
            print(f"{r}: 0 texte extrait")
    print("DONE - dumps deposes, auto-ingeres par repo_ingestion")


if __name__ == "__main__":
    main()
