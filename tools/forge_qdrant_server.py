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

# Le dossier vient de ${QDRANT_BIN} (services.toml, 2026-10-09) : sur une machine neuve, nokido-doctor --ecrire-vars
# le pose sur runtime/qdrant (build epinglee dans distribution/packs/local-llm.toml). Le defaut reste celui du poste
# de reference. Binaire sans `.exe` hors Windows, et journal dans logs/ quand C:\tmp n'a pas de sens.
BIN_DIR = Path(os.environ.get("LAFORGE_QDRANT_BIN", r"C:\tmp\qdrant_bin"))
EXE = BIN_DIR / ("qdrant.exe" if os.name == "nt" else "qdrant")
CONFIG = BIN_DIR / "config.yaml"
_LOG_DEFAUT = (r"C:\tmp\qdrant_server.log" if os.name == "nt"
               else str(Path(__file__).resolve().parents[1] / "logs" / "qdrant_server.log"))
LOG = Path(os.environ.get("LAFORGE_QDRANT_LOG", _LOG_DEFAUT))


def env_sans_config() -> dict:
    """Machine neuve, sans config.yaml : Qdrant ecouterait sur TOUTES les interfaces et enverrait sa telemetrie. On
    impose par variables (la source la plus prioritaire de Qdrant) les choix du config.yaml du poste de reference --
    loopback, telemetrie coupee -- et un stockage dans sandbox/ (donnees et etat : sandbox/, jamais le dossier du
    binaire). Avec un config.yaml, rien n'est impose : le fichier decide, comme chez l'owner."""
    racine = Path(__file__).resolve().parents[1]
    return {"QDRANT__SERVICE__HOST": "127.0.0.1", "QDRANT__TELEMETRY_DISABLED": "true",
            "QDRANT__STORAGE__STORAGE_PATH": str(racine / "sandbox" / "qdrant_storage")}


def main() -> int:
    if not EXE.exists():
        sys.stderr.write(f"[qdrant] binaire absent: {EXE} (set LAFORGE_QDRANT_BIN)\n")
        return 2
    # Mesure 3 de l'organisme (VM Windows neuve) : C:\tmp n'existe pas, open() tuait le lanceur.
    LOG.parent.mkdir(parents=True, exist_ok=True)
    args = [str(EXE)]
    env = None
    if CONFIG.exists():
        args += ["--config-path", str(CONFIG)]
    else:
        env = dict(os.environ, **env_sans_config())
    with open(LOG, "a", buffering=1, encoding="utf-8") as log:
        if env is not None:
            log.write("[qdrant] sans config.yaml : loopback, telemetrie coupee, stockage %s\n"
                      % env["QDRANT__STORAGE__STORAGE_PATH"])
        proc = subprocess.run(args, stdout=log, stderr=log, cwd=str(BIN_DIR), env=env)
        log.write(f"\n=== {EXE.name} exited rc={proc.returncode} ===\n")
        return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
