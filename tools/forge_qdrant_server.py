"""forge_qdrant_server.py — Lanceur du serveur Qdrant natif (:6333 REST / :6334 gRPC).

Promu depuis C:\\tmp (chantier RAG 2026-07-06 — savoir souverain, pas C:\\tmp). Le binaire
qdrant.exe + config vivent dans LAFORGE_QDRANT_BIN (defaut C:\\tmp\\qdrant_bin — A RELOCALISER
hors tmp, ex C:\\nokido\\bin ; cf memory chantier_qdrant_rag_2026-07-06). Storage sur V:
(%NOKIDO_DATA%\\qdrant_server, defini dans config.yaml). Collection nokido_sovereign_rag ~544k pts INT8,
HNSW Rust. Declare comme service NokidoQdrantServer (services.toml) pour survivre au reboot ;
le sidecar :8098 (NokidoQdrantSidecar) en depend.
"""

__FORGE_COLOR__ = "memoire/rag : lanceur du serveur Qdrant natif (:6333)"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(os.environ.get("LAFORGE_QDRANT_BIN", r"C:\tmp\qdrant_bin"))
EXE = BIN_DIR / "qdrant.exe"
CONFIG = BIN_DIR / "config.yaml"
LOG = Path(os.environ.get("LAFORGE_QDRANT_LOG", r"C:\tmp\qdrant_server.log"))


def main() -> int:
    if not EXE.exists():
        sys.stderr.write(f"[qdrant] binaire absent: {EXE} (set LAFORGE_QDRANT_BIN)\n")
        return 2
    args = [str(EXE)]
    if CONFIG.exists():
        args += ["--config-path", str(CONFIG)]
    with open(LOG, "a", buffering=1, encoding="utf-8") as log:
        proc = subprocess.run(args, stdout=log, stderr=log, cwd=str(BIN_DIR))
        log.write(f"\n=== qdrant.exe exited rc={proc.returncode} ===\n")
        return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
