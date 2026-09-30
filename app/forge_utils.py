"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_utils
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `sha256_fichier` — Empreinte SHA-256 d'un fichier, lu par blocs de 1 Mio (un fichier de plusieurs Go ne charge pas la RAM).
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
app/forge_utils.py
UTILS_CENTRAL_V1 — Fonctions utilitaires partagées
Centralise les fonctions dupliquées identifiées par GraphCodeBERT.

NR: tests/test_forge_utils_nr.py
"""


def _safe_llm_text(res: dict, fallback: str = "") -> str:
    """Extrait le texte d'une réponse LLM en évitant les valeurs vides.

    Centralisé depuis:
    - forge_handler_build.py
    - forge_handler_advanced.py
    - forge_autonomous_orchestrator.py
    - forge_recursive_debugger.py
    """
    turns = res.get("results", [])
    for turn in turns:
        text = str(turn.get("response", "")).strip()
        if text and text not in ("None", "null", "{}", "[]", "..."):
            return text
    return fallback


def contient_un_mot(texte: str | None, mots) -> bool:
    """`texte` (insensible a la casse) contient-il l'un de `mots` ?

    Factorisé le 2026-08-20 : `forge_postal._is_routine` et
    `forge_semantic_invariant._porte_une_decision` étaient le MÊME prédicat —
    le cliquet de clones les a groupés par structure AST, pas par nom. Chaque
    module garde son vocabulaire propre ; seul le test est partagé.
    """
    t = (texte or "").lower()
    return any(m in t for m in mots)


def sha256_fichier(chemin) -> str:
    """Empreinte SHA-256 d'un fichier, lu par blocs de 1 Mio (un fichier de plusieurs Go ne charge pas la RAM).

    Factorise le 2026-09-26 : `forge_edge_fleet._sha256_file` et `forge_veille_clone_ingest._sha256_fichier`
    etaient le MEME corps (cliquet clones, CI de reference f6b3613bb). Chacun garde son nom ; seul le corps
    est partage.
    """
    import hashlib

    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def safe_shell_run(cmd: list[str], cwd: str | None = None, timeout: int = 30) -> dict:
    """Exécute une commande shell de manière robuste avec gestion d'encodage.

    Retourne: {"ok": bool, "stdout": str, "stderr": str, "code": int}
    """
    import subprocess
    import sys

    # Prevent console windows when called from a windowless service/process
    _no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    # Encodages à tester par ordre de probabilité
    encodings = ["utf-8", "cp1252", "cp850"] if sys.platform == "win32" else ["utf-8", "latin-1"]

    last_err = ""
    for enc in encodings:
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding=enc,
                errors="replace",
                timeout=timeout,
                cwd=cwd,
                creationflags=_no_window,
            )
            return {"ok": r.returncode == 0, "stdout": r.stdout or "", "stderr": r.stderr or "", "code": r.returncode}
        except (UnicodeDecodeError, LookupError) as e:
            last_err = str(e)
            continue
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "Timeout expired", "code": -1}
        except Exception as e:
            return {"ok": False, "stdout": "", "stderr": str(e), "code": -1}

    return {"ok": False, "stdout": "", "stderr": f"Failed with all encodings. Last: {last_err}", "code": -1}
