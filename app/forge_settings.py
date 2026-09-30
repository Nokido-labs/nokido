# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_settings
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
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
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_settings.py — Configuration et utilitaires système (v16.5)
=================================================================
Contient : _purge_pycache, _acquire_instance_lock, _release_instance_lock,
           debug_log, _cast, _load_env_file, Settings, create_settings
"""

import json, logging, os, sys
from datetime import datetime
from pathlib import Path
from typing import Any, List

logger = logging.getLogger(__name__)

# ── Chemins racine ────────────────────────────────────────────────────────────
_APP_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _APP_DIR.parent
_DATA_DIR = _ROOT_DIR / "data"
_LOGS_DIR = _ROOT_DIR / "logs"
_DATA_DIR.mkdir(exist_ok=True)
_LOGS_DIR.mkdir(exist_ok=True)

_REQUIRED = object()
_LOCK_FILE = _ROOT_DIR / "nokido.lock"
DEBUG_LOG_PATH = _LOGS_DIR / "debug-93c5ee.log"
DEBUG_ROUTE_PATH = _LOGS_DIR / "debug-routing.log"
_LOCK_FH = None

_SETTINGS_FIELDS = [
    ("ssh_host", "SSH_HOST", str, ""),
    ("ssh_port", "SSH_PORT", int, 22),
    ("ssh_user", "SSH_USER", str, ""),
    ("private_key_path", "PRIVATE_KEY_PATH", Path, ""),
    ("ollama_model_default", "OLLAMA_MODEL_DEFAULT", str, ""),
    ("ollama_url", "OLLAMA_URL", str, "http://localhost:11434/api/chat"),
    ("ollama_tags_url", "OLLAMA_TAGS_URL", str, "http://localhost:11434/api/tags"),
    ("ollama_embeddings_url", "OLLAMA_EMBEDDINGS_URL", str, "http://localhost:11434/api/embed"),
    ("ollama_embeddings_model", "OLLAMA_EMBEDDINGS_MODEL", str, "bge-m3"),
    ("verbose", "VERBOSE", bool, False),
    ("max_concurrent_tasks", "MAX_CONCURRENT_OLLAMA", int, 4),
    ("chunk_overlap_words", "CHUNK_OVERLAP_WORDS", int, 30),
    ("embed_batch_size", "EMBED_BATCH_SIZE", int, 16),
    ("use_rag", "USE_RAG", bool, True),
    ("rag_docs_topk", "RAG_DOCS_TOPK", int, 5),
    ("rag_dir", "RAG_DIR", Path, ""),
    ("max_command_retries", "MAX_COMMAND_RETRIES", int, 2),
    ("command_retry_delay", "COMMAND_RETRY_DELAY", int, 2),
    ("auto_switch_agent", "AUTO_SWITCH_AGENT", bool, True),
    ("slack_webhook_url", "SLACK_WEBHOOK_URL", str, None),
    ("loop_automerge", "LOOP_AUTOMERGE", bool, False),
    ("loop_automerge_min_delta", "LOOP_AUTOMERGE_MIN_DELTA", int, 1),
    ("loop_automerge_min_quality", "LOOP_AUTOMERGE_MIN_QUALITY", int, 60),
    ("tz_offset", "TZ_OFFSET", int, 1),
    ("nokido_env", "LAFORGE_ENV", str, "prod"),
    # Chemin DB SQLite — surchargeable via Nokido.env
    # Défaut historique : RAG/embeddings.db
    # Recommandé : data/laforge.db (hors dossier .continue)
    ("db_path", "LAFORGE_DB_PATH", Path, ""),
]


# Context:


def _purge_pycache() -> None:
    """Purge pycache."""
    pass  # no-op : Python gère les .pyc automatiquement via hash


# =============================================================================
# LOCK INSTANCE — protection double lancement + nettoyage orphelin
# =============================================================================


def _acquire_instance_lock() -> object:
    """
    Lock intelligent multi-processus Nokido.
    1. TUI seule = lock exclusif. MCP/Brain/Lanceur = pas de lock.
    2. Nettoie les locks orphelins auto.
    3. Nomme tous les processus dans le gestionnaire de taches.
    4. Lock JSON PID+timestamp+role pour diagnostic.
    5. Mode dev (--dev) : warn mais ne bloque pas.
    """
    global _LOCK_FH
    import os, sys
    from datetime import timezone

    _devmode = "--dev" in sys.argv or "--no-lock" in sys.argv or os.environ.get("LF_DEV", "") == "1"

    def _name_proc(role="TUI") -> None:
        """Name proc.

        Args:
            role: Description.
        """
        try:
            from nokido_agent.app.forge_version import full_label as _fl

            ver = _fl()
        except Exception:
            ver = "v?"
        t = {
            "TUI": "Nokido " + ver,
            "MCP": "Nokido MCP " + ver,
            "BRAIN": "Nokido Brain " + ver,
            "LANCEUR": "Nokido Lanceur " + ver,
        }.get(role, "Nokido " + role + " " + ver)
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(t)
            # Coupe le bip système Windows (déclenché par certains titres)
            try:
                ctypes.windll.kernel32.Beep(0, 0)
            except Exception:
                pass
        except Exception:
            pass
        try:
            import setproctitle

            setproctitle.setproctitle(t)
        except ImportError:
            pass
        try:
            sys.argv[0] = t
        except Exception:
            pass

    _argv = " ".join(sys.argv)
    _role = (
        "MCP"
        if "nokido_mcp_server" in _argv
        else "BRAIN"
        if "brain_worker" in _argv
        else "LANCEUR"
        if "Nokido_Lanceur" in _argv
        else "TUI"
    )
    _name_proc(_role)

    if _role != "TUI":
        return  # seul la TUI prend le lock exclusif

    def _alive(pid) -> bool:
        """Alive.

        Args:
            pid: Description.
        """
        try:
            pid = int(str(pid).strip())
            if pid <= 0:
                return False
            try:
                import psutil

                return psutil.pid_exists(pid)
            except ImportError:
                pass
            if sys.platform == "win32":
                import subprocess

                # `errors="replace"` OBLIGATOIRE : capture en mode texte sans lui, le
                # thread lecteur casse des que la sortie contient un octet non
                # decodable — et `tasklist` sort des accents en cp1252 sur une machine
                # francaise. C'est la signature de l'incident 47 Go, que le gate
                # anti-regression signalait ici depuis un moment.
                r = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True, text=True, timeout=2,
                    encoding="utf-8", errors="replace",
                )
                return str(pid) in r.stdout
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def _read() -> dict:
        """Read."""
        try:
            _LOCK_FH.seek(0)
            raw = _LOCK_FH.read().strip()
            if raw.startswith("{"):
                return json.loads(raw)
            return {"pid": int(raw), "role": "TUI", "ts": "?"} if raw.isdigit() else {}
        except Exception:
            return {}

    def _write() -> None:
        """Write."""
        try:
            _LOCK_FH.seek(0)
            _LOCK_FH.truncate()
            _LOCK_FH.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "role": _role,
                        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "argv": sys.argv[0],
                    }
                )
            )
            _LOCK_FH.flush()
        except Exception:
            pass

    def _clear() -> None:
        """Clear."""
        global _LOCK_FH
        try:
            if _LOCK_FH and not _LOCK_FH.closed:
                _LOCK_FH.close()
        except Exception:
            pass
        try:
            _LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            _LOCK_FH = open(str(_LOCK_FILE), "a+", encoding="utf-8")
        except Exception:
            pass

    try:
        _LOCK_FH = open(str(_LOCK_FILE), "a+", encoding="utf-8")
    except Exception:
        return

    d = _read()
    if d.get("pid") and not _alive(d["pid"]):
        logger.info(f"[lock] Orphelin PID={d['pid']} mort -> nettoyage")
        _clear()
        d = {}

    if _devmode and d.get("pid") and _alive(d["pid"]):
        logger.warning(f"[lock] --dev : TUI PID={d['pid']} active, demarrage force")
        _write()
        return

    try:
        if sys.platform == "win32":
            import msvcrt

            _LOCK_FH.seek(0)
            try:
                msvcrt.locking(_LOCK_FH.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                d2 = _read()
                pid2 = d2.get("pid", "?")
                if not _alive(pid2):
                    logger.warning(f"[lock] Zombie PID={pid2} -> force_clear")
                    _clear()
                    try:
                        msvcrt.locking(_LOCK_FH.fileno(), msvcrt.LK_NBLCK, 1)
                    except OSError:
                        pass
                else:
                    print(
                        f"\n[Nokido] TUI deja active"
                        f" (PID {pid2}, {d2.get('ts', '?')}).\n"
                        f"  Ferme la fenetre existante ou relance avec --dev.\n"
                        f"  Lock : {_LOCK_FILE}\n"
                    )
                    _LOCK_FH.close()
                    sys.exit(1)
        else:
            import fcntl

            try:
                fcntl.flock(_LOCK_FH.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                d2 = _read()
                pid2 = d2.get("pid", "?")
                if not _alive(pid2):
                    _clear()
                    try:
                        fcntl.flock(_LOCK_FH.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except OSError:
                        pass
                else:
                    print(f"\n[Nokido] TUI deja active (PID {pid2}).\n  Utilise --dev pour ignorer.\n")
                    _LOCK_FH.close()
                    sys.exit(1)
    except ImportError:
        pass

    _write()


def _release_instance_lock() -> None:
    """Libère le lock fichier et supprime nokido.lock."""
    global _LOCK_FH
    import sys

    try:
        if _LOCK_FH and not _LOCK_FH.closed:
            if sys.platform == "win32":
                import msvcrt

                try:
                    _LOCK_FH.seek(0)
                    msvcrt.locking(_LOCK_FH.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(_LOCK_FH.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
            _LOCK_FH.close()
    except Exception:
        pass
    try:
        if _LOCK_FILE.exists():
            _LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# =============================================================================
# UTILITAIRES
# =============================================================================


def debug_log(caller: str, module: str, message: str, level: str = "DEBUG") -> None:
    """Log de debug — version locale forge_settings (évite import circulaire)."""
    import logging as _lg

    _lg.getLogger(f"Nokido.{module}").log(getattr(_lg, level.upper(), _lg.DEBUG), f"[{caller}] {message}")


def _cast(value: str, type_) -> Any:
    """Convertit une string env vers le type Python cible."""
    if type_ is bool:
        return value.lower() in ("1", "true", "yes", "oui", "on")
    if type_ is int:
        return int(value)
    if type_ is Path:
        return Path(value)
    return value


def _load_env_file(path: str = "Nokido.env") -> None:
    """Charge un fichier .env dans os.environ (ne surcharge pas les vars existantes).
    Cherche d'abord dans le dossier du script, puis dans le CWD.
    """
    _script_dir = Path(__file__).resolve().parent
    _candidates = [
        _script_dir / path,  # app/LaForge.env
        _script_dir.parent / path,  # LaForge/LaForge.env  ← correct
        Path(path),  # CWD fallback
    ]
    _resolved = next((p for p in _candidates if p.exists()), None)
    if _resolved is None:
        return
    try:
        with open(str(_resolved), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    v = v.strip().strip('"').strip("'")
                    os.environ.setdefault(k.strip(), v)
    except Exception as e:
        print(f"  ⚠ Lecture {_resolved} : {e}", flush=True)


# =============================================================================
# SETTINGS
# =============================================================================


# Acces SSH : lus au COFFRE d'abord (forge_secrets.get_secret : coffre DPAPI, WCM, Nokido.env,
# environnement). Owner 2026-09-25 : « il ne faut pas mettre en dur mes acces SSH sur la version
# dist ». Sans coffre, le comportement d'avant est conserve ; un coffre qui leve ne casse rien.
_CLES_DU_COFFRE = frozenset({"SSH_HOST", "SSH_PORT", "SSH_USER", "PRIVATE_KEY_PATH"})


def _valeur_de_reglage(env_key: str):
    """Valeur brute d'un reglage : le coffre pour les acces SSH, l'environnement sinon."""
    if env_key in _CLES_DU_COFFRE:
        try:
            from nokido_agent.app import forge_secrets as _fsec

            v = _fsec.get_secret(env_key)
            if v:
                return v
        except Exception as e:  # noqa: BLE001 - un coffre illisible le DIT, puis on lit l'environnement
            print(f"  ⚠ coffre illisible pour {env_key} ({type(e).__name__}) — lecture de l'environnement",
                  flush=True)
    return os.environ.get(env_key)


class Settings:
    """
    Configuration de l'application.
    Lit Nokido.env + os.environ. Compatible Python 3.8→3.14+, zéro dépendance.
    """

    def __init__(self) -> None:
        # ── 1. Déchiffrement secrets (.env.secrets / keyring) ────────────────
        # Inject FORGE_MCP_TOKEN, GEMINI_API_KEY etc. depuis le stockage chiffré
        # AVANT la lecture des settings — transparent pour forge_settings
        """Init."""
        try:
            from nokido_agent.app.forge_env_crypt import inject_into_environ as _inject_sec

            _n_sec = _inject_sec()
            if _n_sec:
                pass  # silencieux au boot
        except Exception:
            pass

        # ── 2. Enrichissement dynamique depuis l'environnement hôte ─────────────────
        # Injecte dans Nokido.env les variables présentes sur l'hôte
        # mais absentes du fichier. N'écrase jamais les valeurs existantes.
        try:
            from nokido_agent.app.forge_env_sync import sync_env as _sync

            _injected = [r for r in _sync() if r.get("action") == "injected"]
            if _injected:
                # Recharger os.environ après injection dans .env
                from pathlib import Path as _P

                env_p = _P(__file__).resolve().parent.parent / "Nokido.env"
                for line in env_p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.split("#")[0].strip()
                    if k and v and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass
        missing = []
        for attr, env_key, type_, default in _SETTINGS_FIELDS:
            raw = _valeur_de_reglage(env_key)
            if raw is not None and raw.strip() != "":
                try:
                    setattr(self, attr, _cast(raw, type_))
                except (ValueError, TypeError) as e:
                    print(f"  ⚠ {env_key}={raw!r} invalide ({e}) — défaut utilisé", flush=True)
                    setattr(self, attr, default)
            elif default is _REQUIRED:
                setattr(self, attr, None)
                missing.append(env_key)
            else:
                setattr(self, attr, default)

        if missing:
            raise ValueError(
                f"Variables manquantes dans Nokido.env : {', '.join(missing)}\n"
                "  Créez Nokido.env avec SSH_HOST, SSH_USER, PRIVATE_KEY_PATH."
            )

        for _attr, _label in [("ssh_host", "SSH_HOST"), ("ssh_user", "SSH_USER")]:
            _v = getattr(self, _attr, "") or ""
            if isinstance(_v, str) and _v.startswith("<") and _v.endswith(">"):
                print(f"  ⚠  {_label} placeholder ignoré", flush=True)
                setattr(self, _attr, "")

        self.ollama_model = self.ollama_model_default

    def validate_all(self) -> List[str]:
        """Valide les règles métier, retourne la liste des erreurs."""
        errors = []
        if self.use_rag and self.rag_dir and not Path(str(self.rag_dir)).exists():
            try:
                Path(str(self.rag_dir)).mkdir(parents=True, exist_ok=True)
            except Exception:
                errors.append(f"Impossible de créer le répertoire RAG : {self.rag_dir}")
        if self.private_key_path and str(self.private_key_path):
            _pk = str(self.private_key_path)
            if _pk.startswith("<") and _pk.endswith(">"):
                errors.append(f"PRIVATE_KEY_PATH est un placeholder : {_pk}")
            else:
                # ILLISIBLE n'est pas ABSENT : sous un compte qui ne lit pas le profil de l'owner,
                # Path.exists() LEVE PermissionError (mesure 2026-09-25) -- on le dit, sans planter.
                try:
                    _existe = Path(_pk).exists()
                except OSError as _e:
                    errors.append(f"Clé privée ILLISIBLE par ce compte ({type(_e).__name__}) : {_pk}")
                else:
                    if not _existe:
                        errors.append(f"Clé privée introuvable : {_pk}")
        if self.max_concurrent_tasks and not (1 <= self.max_concurrent_tasks <= 50):
            errors.append("MAX_CONCURRENT_OLLAMA doit être entre 1 et 50")
        if self.rag_docs_topk and not (1 <= self.rag_docs_topk <= 20):
            errors.append("RAG_DOCS_TOPK doit être entre 1 et 20")
        return errors


def _ssh_setup_wizard() -> bool:
    """Wizard console SSH si variables absentes. Retourne True si configuré."""
    print()
    print("  ╔══════════════════════════════════════════════════╗")
    print("  ║   ⚒  La Forge — Configuration SSH requise       ║")
    print("  ╚══════════════════════════════════════════════════╝")
    print()

    def _ask(prompt: str, default: str = "") -> str:
        """Ask.

        Args:
            prompt: Description.
            default: Description.
        """
        try:
            val = input(f"  {prompt}" + (f" [{default}]" if default else "") + " : ").strip()
            return val or default
        except (EOFError, KeyboardInterrupt):
            return default

    host = ""
    # MESURE 2026-07-28 : le garde `isatty` ci-dessous est INOPERANT sous `run_job` —
    # stdin y est HERITE et se declare TTY alors qu'il ne rend rien. Trois jobs ont
    # boucle a l'infini ici (pid 15776, 16072, 16952), satures de « SSH_HOST
    # obligatoire », et ont du etre tues a la main. Un capteur de NATURE peut mentir ;
    # une BORNE, non. Toute boucle de saisie est bornee, quelle que soit la nature
    # declaree de stdin. (Le meme correctif a ete porte sur app/forge_ssh.py.)
    _essais = 0

    def _borne() -> bool:
        """True quand il faut renoncer : plus aucune saisie ne viendra."""
        nonlocal _essais
        _essais += 1
        return _essais >= 3

    while not host:
        host = _ask("SSH_HOST")
        if not host:
            if _borne() or not sys.stdin.isatty():
                print("  aucune saisie possible - assistant SSH abandonne")
                return False
            print("  ⚠  SSH_HOST obligatoire.")

    port = _ask("SSH_PORT", "22")
    try:
        port = str(int(port))
    except ValueError:
        port = "22"

    user = ""
    while not user:
        user = _ask("SSH_USER")
        if not user:
            if _borne():
                print("  aucune saisie possible - assistant SSH abandonne")
                return False
            print("  ⚠  SSH_USER obligatoire.")

    key_path = ""
    while not key_path:
        key_path = _ask("PRIVATE_KEY_PATH")
        if not key_path:
            if _borne():
                print("  aucune saisie possible - assistant SSH abandonne")
                return False
            print("  ⚠  PRIVATE_KEY_PATH obligatoire.")
        elif not Path(key_path).exists():
            print(f"  ⚠  Fichier introuvable : {key_path}")
            if _ask("Continuer ? (o/N)", "N").lower() not in ("o", "oui", "y", "yes"):
                key_path = ""

    print()
    print("  [1] Session uniquement   [2] Enregistrer dans Nokido.env   [0] Annuler")
    choice = _ask("Choix", "1")

    if choice == "0":
        print("  Annulé.")
        return False

    os.environ["SSH_HOST"] = host
    os.environ["SSH_PORT"] = port
    os.environ["SSH_USER"] = user
    os.environ["PRIVATE_KEY_PATH"] = key_path

    if choice == "2":
        env_path = _ROOT_DIR / "Nokido.env"
        try:
            existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""

            def _set_var(content: str, key: str, value: str) -> str:
                """Set var.

                Args:
                    content: Description.
                    key: Description.
                    value: Description.
                """
                import re as _re

                pattern = _re.compile(rf"^{key}=.*$", _re.MULTILINE)
                line = f"{key}={value}"
                if pattern.search(content):
                    return pattern.sub(line, content)
                return content.rstrip("\n") + f"\n{line}\n"

            content = existing
            for k, v in [("SSH_HOST", host), ("SSH_PORT", port), ("SSH_USER", user), ("PRIVATE_KEY_PATH", key_path)]:
                content = _set_var(content, k, v)
            env_path.write_text(content, encoding="utf-8")
            print(f"  ✅ Enregistré dans {env_path.resolve()}")
        except Exception as e:
            print(f"  ⚠  Impossible d'écrire Nokido.env : {e}")
    else:
        print("  ✅ Paramètres SSH actifs pour cette session.")

    print()
    return True


def get_db_path() -> Path:
    """
    Retourne le chemin canonique de la DB SQLite Nokido.
    Priorité :
      1. LAFORGE_DB_PATH dans Nokido.env / os.environ
      2. _ROOT_DIR / 'data' / 'laforge.db'  (nouvel emplacement recommandé)
      3. _ROOT_DIR / 'RAG' / 'embeddings.db'  (legacy fallback)
    Crée le dossier parent si nécessaire.
    """
    override = os.environ.get("LAFORGE_DB_PATH", "").strip()
    if override:
        p = Path(override)
    elif (_ROOT_DIR / "RAG" / "embeddings.db").exists():
        # Legacy : DB existante dans .continue — on garde la référence
        p = _ROOT_DIR / "RAG" / "embeddings.db"
    else:
        # Nouvel emplacement par défaut
        p = _ROOT_DIR / "data" / "laforge.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def create_settings() -> "Settings":
    """Create settings."""
    try:
        _ssh_vars = ("SSH_HOST", "SSH_USER", "PRIVATE_KEY_PATH")
        _missing = [k for k in _ssh_vars if not (_valeur_de_reglage(k) or "").strip()]
        # Guard: never run interactive wizard from async context (hub/service)
        # or when stdin is not a real terminal
        try:
            import asyncio as _asyncio

            _asyncio.get_running_loop()  # raises RuntimeError if no running loop
            _real_tty = False  # inside async event loop — skip wizard
        except RuntimeError:
            try:
                _real_tty = sys.stdin.isatty() and os.isatty(sys.stdin.fileno())
            except Exception:
                _real_tty = False
        if _missing and _real_tty:
            _ssh_setup_wizard()

        s = Settings()
        errors = s.validate_all()
        if errors:
            for e in errors:
                logger.warning(f"[settings] {e}")
        return s
    except Exception as e:
        print(f"\n❌ Erreur de configuration : {e}")
        print("Vérifiez Nokido.env (SSH_HOST, SSH_USER, PRIVATE_KEY_PATH)")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# API CENTRALISÉE — remplace _forge_settings() et _g() dans les modules
# ═══════════════════════════════════════════════════════════════════════════

import sys as _sys_fg
import threading as _threading_fg

# Singleton thread-safe -- Double-Checked Locking (anti-split-brain migration)
_settings_instance = None
_settings_lock = _threading_fg.Lock()


def get_settings() -> "Settings":
    """
    Singleton thread-safe. Remplace _forge_settings() dans les modules migres.
    Double-Checked Locking : safe Python 3.12+ avec GIL.
    Fallback : sys.modules["__main__"].settings (retrocompatibilite).
    """
    global _settings_instance
    if _settings_instance is None:  # check 1 sans lock
        with _settings_lock:
            if _settings_instance is None:  # check 2 avec lock
                # Priorité 1 : instance déjà dans __main__ (Nokido TUI)
                m = _sys_fg.modules.get("__main__")
                existing = getattr(m, "settings", None)
                if existing is not None:
                    _settings_instance = existing
                else:
                    _settings_instance = create_settings()
    return _settings_instance


def get_app_attr(name: str, default=None) -> object:
    """
    Résout un attribut de l'instance Nokido active via sys.modules.
    Remplace le pattern _g() dupliqué dans 15 modules.

    Usage :
        from forge_settings import get_app_attr
        model = get_app_attr("model_chat", "llama3")
        chat  = get_app_attr("_chat_log", lambda: None)()
    """
    for mod_name in ("__main__", "Nokido", "app.Nokido"):
        m = _sys_fg.modules.get(mod_name)
        if m is not None:
            val = getattr(m, name, None)
            if val is not None:
                return val
    return default


# Alias _load_env pour compatibilite forge_*_bridge
# ATTENTION : _load_env_file retourne None, les bridges font _load_env().get()
# On retourne os.environ comme dict apres avoir charge le fichier
def _load_env(path: str = "Nokido.env") -> dict:
    """Load env.

    Args:
        path: Description.
    """
    _load_env_file(path)
    import os as _os

    return dict(_os.environ)


# Alias courts pour compatibilité
g = get_app_attr
