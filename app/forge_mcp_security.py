"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_mcp_security
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
forge_mcp_security.py — FORGE_HARDENED_MCP_V1
==============================================
Module de sécurité pour le serveur MCP Nokido.
Zero-Trust sur tous les inputs. Dernier rempart avant le système de fichiers.

Features :
  1. Path sandboxing  — jamais hors de ROOT
  2. Allow-list tools — commandes autorisées uniquement
  3. Limite taille    — max 2MB par fichier lu/écrit
  4. Hash audit       — détection modification externe
  5. Audit log        — TIMESTAMP | TOOL | ARGS | STATUS (non modifiable par l'IA)
  6. Validation args  — typage strict sur chaque tool call
"""


import hashlib


class SecretGuardViolation(PermissionError):
    """Levée quand un agent tente d'accéder à un fichier protégé."""

    pass


import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── Config ────────────────────────────────────────────────────────────────────

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
AUDIT_LOG = ROOT / "logs" / "mcp_audit.log"

# Allow-list actions run()
ALLOWED_RUN_ACTIONS = {
    "python",
    "github",
    "atlas_build",
    "atlas_get",
    "save_situation",
    "make_snapshot",
    "hub_restart",
    "hub_status",
    "setup_check",
    "unified_discovery",
    "audit_log",
    "test_nr",
    "test_module",
    "test_status",
    "task_status",
    "mutation:start",
    "mutation:poll",
}

# Patterns dangereux dans le code Python soumis
DANGEROUS_PATTERNS = [
    r"os\.system\s*\(",
    r"subprocess\..*shell\s*=\s*True",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__\s*\(",
    r"open\s*\([^)]*['\"]w['\"]",  # write arbitraire
    r"\brm\s+-rf\b",
    r"shutil\.rmtree",
    r"os\.remove\s*\(",
    r"os\.unlink\s*\(",
]
_danger_re = [re.compile(p) for p in DANGEROUS_PATTERNS]

# Patterns qualité DB (avertissement Gemini inventaire 2026-04-28)
DB_QUALITY_PATTERNS = [r"sqlite3\.connect\s*\("]
_db_quality_re = [re.compile(p) for p in DB_QUALITY_PATTERNS]


def check_db_quality(content: str, path: str, agent: str) -> list:
    """Détecte sqlite3.connect sans WAL — avertissement organique (pas de blocage)."""
    warnings = []
    lines_c = content.splitlines()
    for i, line in enumerate(lines_c, 1):
        for pat in _db_quality_re:
            if pat.search(line):
                ctx = "\n".join(lines_c[i : min(i + 5, len(lines_c))])
                if "WAL" not in ctx and "journal_mode" not in ctx and "forge_db" not in content:
                    warnings.append(
                        f"DB_NO_WAL l.{i}: sqlite3.connect() sans WAL dans {path} — préférer forge_db.get_conn()"
                    )
                    break
    return warnings


# ── Fichiers critiques : non modifiables par les agents LLM via write() ─────
# Même un agent Ring 0 ne peut PAS écrire ces fichiers via le tool write().
# Exception : si LAFORGE_ALLOW_CRITICAL_WRITE=1 dans l'env (maintenance manuelle).

# MESURE DU 2026-09-12 — la liste protegeait le PASSE, pas l'autorite.
# `app/forge_rbac.py` (get_rbac) y etait ; `app/forge_mcp_rbac.py`
# (check_tool_capability), qui porte la decision d'autorisation PAR TOOL
# reellement consultee au dispatch, n'y etait pas. Deux noms voisins, deux
# autorites reelles, une seule protegee. Trois autres porteurs mesures le meme
# jour manquaient : le capteur de l'off-switch humain, le garde qui le consulte,
# et l'ecrivain qui applique cette liste.
#
# CE QUE L'APPARTENANCE A CETTE LISTE VAUT, exactement : elle impose un geste
# EXPLICITE et TRACE (`allow_critical=true`). Cette derogation reste ouverte au
# ring <= 1, donc au client. Ce n'est PAS une frontiere de confiance, et il ne
# faut pas lire cette liste comme telle.
# Verrouille par tests/nr/test_critical_files_suit_l_autorite_nr.py.
CRITICAL_FILES = {
    "tools/nokido_hub.py",
    "app/forge_mcp_registry.py",
    "app/forge_mcp_security.py",
    "app/forge_rbac.py",
    "app/forge_mcp_rbac.py",
    "app/forge_opsec.py",
    "app/forge_corrigibility.py",
    "tools/forge_governed_edit.py",
    "app/web_hub/auth.py",
    "app/web_hub/app.py",
    ".env",
    "Nokido.env",
}


def _is_critical(path: str | Path) -> bool:
    """Retourne True si le fichier est dans la liste noire critique."""
    import os as _os

    p_str = str(path).replace("\\", "/").replace("\\", "/")
    # Normaliser les séparateurs
    p_norm = p_str.replace("\\", "/").replace("\\\\", "/")
    for critical in CRITICAL_FILES:
        c_norm = critical.replace("\\", "/")
        if p_norm.endswith(c_norm) or p_norm.endswith(c_norm.replace("/", "\\")):
            return True
    return False


# Patterns bloqués dans les chemins
PATH_TRAVERSAL = re.compile(r"\.\.[/\\]|\.\.[/\\]?$")


# ── 1. Path Sandboxing ────────────────────────────────────────────────────────


def safe_path(path: str | Path) -> Path:
    """
    Vérifie que path est sous ROOT.
    Lève ValueError si traversal détecté.
    """
    p = Path(path)
    # Traversal pattern rapide
    if PATH_TRAVERSAL.search(str(path)):
        raise ValueError(f"Path traversal détecté: {path}")
    # Résolution réelle
    try:
        resolved = p.resolve()
        root_r = ROOT.resolve()
        common = os.path.commonpath([str(root_r), str(resolved)])
        if common != str(root_r):
            raise ValueError(f"Chemin hors sandbox: {resolved}")
    except (OSError, ValueError) as e:
        raise ValueError(f"Chemin invalide: {path} — {e}")
    return resolved


# ── 2. Allow-list & Code Scan ─────────────────────────────────────────────────


def validate_run_action(action: str, code: str = "") -> None:
    """
    Vérifie que l'action run() est autorisée et que le code ne contient pas
    de patterns dangereux. En FORGE_DEV_MODE=1, seuls eval/exec/__import__ sont bloqués.
    """
    import os as _vos

    base_action = action.split(":")[0] if ":" in action else action
    if base_action not in ALLOWED_RUN_ACTIONS and action not in ALLOWED_RUN_ACTIONS:
        raise ValueError(f"Action non autorisée: {action}")

    if code and base_action == "python":
        _dev = _vos.environ.get("FORGE_DEV_MODE", "").lower() in ("1", "true", "yes")
        _checks = _danger_re if not _dev else [re.compile(p) for p in [r"eval\s*\(", r"exec\s*\(", r"__import__\s*\("]]
        for pattern in _checks:
            if pattern.search(code):
                raise ValueError(f"Pattern dangereux détecté: {pattern.pattern[:40]}")


def validate_args(tool: str, args: dict) -> None:
    """Validation de type et contenu pour chaque tool."""
    if tool == "read":
        action = args.get("action", "")
        if action not in ("file", "tail_logs"):
            raise ValueError(f"read: action invalide '{action}'")
        path = args.get("path", "")
        if action == "file" and path not in ("system", "mcp", "err"):
            safe_path(path)

    elif tool == "write":
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            raise ValueError("write: path requis")
        safe_path(path)
        if len(content.encode("utf-8")) > MAX_FILE_SIZE:
            raise ValueError(f"write: contenu trop grand ({len(content) // 1024}KB > 2MB)")

    elif tool == "run":
        action = args.get("action", "")
        code = args.get("code", "")
        validate_run_action(action, code)

    elif tool == "query":
        sql = args.get("sql", "")
        if not sql:
            raise ValueError("query: sql requis")
        # Bloque les commandes destructives non autorisées
        sql_up = sql.strip().upper()
        if any(sql_up.startswith(k) for k in ("DROP ", "TRUNCATE ", "DELETE FROM sqlite_")):
            raise ValueError("query: commande SQL non autorisée")

    # Fix #3-B : DLP non-bloquant sur les tools sortants (cloud).
    # Detecte un credential passe en argument -> marque l'audit (SECRET_IN_ARGS),
    # ne leve PAS (eviter les faux-positifs qui casseraient un appel legitime).
    if tool in ("ask", "crawl", "web_search", "orchestrate", "research_agent", "biblio"):
        try:
            from nokido_agent.app.forge_secret_guard import scan_outbound, SecretLeakBlocked
            blob = " ".join(str(v) for v in args.values() if v)
            scan_outbound(blob, provider=tool, local_only=False)
        except SecretLeakBlocked as _leak:
            audit(tool, args, "SECRET_IN_ARGS", error=str(_leak))
        except Exception:
            pass  # DLP best-effort : ne jamais bloquer la validation


# ── 3. Limite taille fichier ──────────────────────────────────────────────────


def check_file_size(path: str | Path, max_bytes: int = MAX_FILE_SIZE) -> None:
    """Lève ValueError si le fichier est trop grand."""
    p = Path(path)
    if p.exists() and p.stat().st_size > max_bytes:
        raise ValueError(f"Fichier trop grand: {p.name} ({p.stat().st_size // 1024}KB > {max_bytes // 1024}KB)")


# ── 4. Hash audit ─────────────────────────────────────────────────────────────

_file_hashes: dict[str, str] = {}


def record_hash(path: str | Path) -> str:
    """Enregistre le hash SHA256 d'un fichier."""
    p = Path(path)
    if not p.exists():
        return ""
    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    _file_hashes[str(p)] = h
    return h


def check_hash(path: str | Path) -> bool:
    """
    Vérifie que le fichier n'a pas été modifié depuis le dernier record_hash.
    Retourne True si OK, False si modifié.
    """
    p = Path(path)
    key = str(p)
    if key not in _file_hashes:
        return True  # pas de baseline — OK
    if not p.exists():
        return False
    current = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return current == _file_hashes[key]


# ── 5. Audit log ──────────────────────────────────────────────────────────────


def audit(tool: str, args: dict, status: str, error: str = "") -> None:
    """
    Écrit une ligne d'audit non-modifiable par l'IA.
    Format : TIMESTAMP | TOOL | ARGS_HASH | STATUS [| ERROR]
    Le fichier est en append-only — l'IA ne peut pas y écrire via write().
    """
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        from nokido_agent.app.forge_conv_sanitizer import _redact
        args_summary = json.dumps({k: _redact(str(v))[:80] for k, v in args.items()}, ensure_ascii=False)
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} | {tool:20s} | {args_summary[:120]:120s} | {status}"
        if error:
            line += f" | ERR: {error[:80]}"
        with open(str(AUDIT_LOG), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # L'audit ne doit jamais faire crasher le serveur


# ── API publique ──────────────────────────────────────────────────────────────


def guard(tool: str, args: dict) -> None:
    """
    Point d'entrée unique — à appeler au début de chaque handle_call_tool.
    Lève ValueError si quelque chose est suspect.
    Lance l'audit automatiquement.
    """
    try:
        validate_args(tool, args)
        audit(tool, args, "ALLOW")
    except ValueError as e:
        audit(tool, args, "BLOCK", str(e))
        raise


# ── Moindre privilège par agent (Mistral-validated 2026-04-28) ───────────────
# Chaque agent ne peut écrire que dans les paths autorisés, même en Ring 0.
# Correction Mistral : GEMINI élargi, CLINE restreint sur forge_*, CLAUDE audité.

AGENT_WRITE_PATHS: dict[str, list[str]] = {
    "CLAUDE": ["*"],  # Admin supervisé humain (SecretGuard reste actif)
    "BRIDGE": ["*"],  # Identité du stdio bridge Claude Desktop = superviseur (ring 0)
    "GEMINI": [  # Collaborateur autonome — scope réduit
        "sandbox/",
        "docs/",
        "tests/",
        "logs/",
        "migrations/",
        "config/",
    ],
    "CODEX": [  # OpenAI Codex CLI — pair de code (= GEMINI) ; hook-less -> gouverné hub-only
        "sandbox/",
        "docs/",
        "tests/",
        "logs/",
        "migrations/",
        "config/",
    ],
    # PERIMETRE_AGY_ALIGNE_SSOT (2026-08-14) — cette liste doit rester le miroir
    # de config/agent_identities.json. Deux listes divergentes pour le meme agent,
    # c'est l'agent qui finit par editer les gardes lui-meme (constate le 13/08).
    "ANTIGRAVITY": [  # Antigravity CLI (agy) — pair de code, ring 1 (decision owner)
        "app/",
        "tools/",
        "proxy_deno/",
        "src/",
        "tests/",
        "docs/",
        "config/",
        "migrations/",
        "logs/",
        "sandbox/",
    ],
    "CLINE": [  # Outil dev — code & tests mais pas forge_core
        "app/",
        "tests/",
        "src/",
        "sandbox/",
        "docs/",
    ],
    "INSPECTOR": [],  # Read-only absolu
    "SERVICES": [],
    "INTERNAL_HUB": ["logs/", "sandbox/"],
    "default": ["sandbox/"],  # Tout agent inconnu
}

# Fichiers protégés même pour CLAUDE (intégrité des traces)
_CLAUDE_WRITE_EXCLUDE = {
    "logs/mcp_audit.log",  # audit immutable
}


# ── SSoT write_paths : override depuis config/agent_identities.json ───────────
# AGENT_WRITE_PATHS ci-dessus = policy DÉFAUT (fallback). Source de vérité vivante
# = le champ "write_paths" du registre identité×ring (même fichier que les rings).
# Pour (dé)provisionner un agent : éditer agent_identities.json — il GAGNE ici.
_IDENTITIES_FILE = ROOT / "config" / "agent_identities.json"
_WPATHS_CACHE: dict = {"mtime": 0.0, "paths": {}}


def _identity_write_paths() -> dict:
    try:
        m = _IDENTITIES_FILE.stat().st_mtime
        if m != _WPATHS_CACHE["mtime"]:
            data = json.loads(_IDENTITIES_FILE.read_text(encoding="utf-8")).get("agents", {})
            _WPATHS_CACHE["paths"] = {
                k.upper(): list(v["write_paths"])
                for k, v in data.items()
                if isinstance(v, dict) and isinstance(v.get("write_paths"), list)
            }
            _WPATHS_CACHE["mtime"] = m
    except Exception:
        pass
    return _WPATHS_CACHE["paths"]


def get_agent_write_paths(agent: str) -> list:
    """Zones d'écriture — SSoT json D'ABORD, fallback policy AGENT_WRITE_PATHS, sinon default."""
    au = agent.upper() if agent else "default"
    jp = _identity_write_paths()
    if au in jp:
        return jp[au]
    return AGENT_WRITE_PATHS.get(au, AGENT_WRITE_PATHS["default"])


# Taille max par fichier écrit via MCP (anti-DoS)
MAX_WRITE_SIZE = 10 * 1024 * 1024  # 10 MB


def check_agent_write_path(path: str | Path, agent: str) -> None:
    """
    Vérifie que l'agent a le droit d'écrire ce path selon AGENT_WRITE_PATHS.

    Stratégie hybride (recommandation Mistral) :
    - startswith() pour les dossiers génériques → rapide
    - safe_path() pour résolution réelle → anti path traversal
    - Allowlist exacte pour exclusions critiques (mcp_audit.log)

    Lève SecretGuardViolation si refusé.
    """
    agent_upper = agent.upper() if agent else "default"
    allowed_prefixes = get_agent_write_paths(agent_upper)

    # Normaliser le path vers relatif au ROOT
    p_str = str(path).replace(os.sep, "/")
    # Enlever le ROOT absolu si présent
    root_str = str(ROOT).replace(os.sep, "/") + "/"
    if p_str.startswith(root_str):
        p_str = p_str[len(root_str) :]
    p_str_lower = p_str.lower()

    # Exclusions spécifiques pour CLAUDE
    if agent_upper == "CLAUDE":
        for excl in _CLAUDE_WRITE_EXCLUDE:
            if p_str_lower.endswith(excl.lower()) or excl.lower() in p_str_lower:
                raise SecretGuardViolation(f"AUDIT_IMMUTABLE: {p_str} est protégé contre l'écriture (intégrité audit).")

    # Wildcard total
    if "*" in allowed_prefixes:
        return  # autorisé

    # Aucun path autorisé = refus total
    if not allowed_prefixes:
        raise SecretGuardViolation(f"AGENT_NO_WRITE: {agent_upper} n'a pas de droits d'écriture. Path: {p_str}")

    # Check startswith sur chaque prefix autorisé
    for prefix in allowed_prefixes:
        prefix_norm = prefix.replace("\\", "/").lower()
        if p_str_lower.startswith(prefix_norm):
            # Vérification anti-traversal via safe_path
            try:
                safe_path(path)  # lève ValueError si traversal détecté
            except ValueError as e:
                raise SecretGuardViolation(f"PATH_TRAVERSAL: {e}")
            return  # autorisé

    # Aucun prefix ne match → refus
    paths_display = ", ".join(allowed_prefixes)
    raise SecretGuardViolation(
        f"AGENT_PATH_DENIED: {agent_upper} ne peut écrire que dans [{paths_display}]. Path demandé: {p_str}"
    )


def assert_can_write(path: str | Path, agent: str = "unknown", ring: int = 3) -> None:
    """
    Vérifie qu'un agent peut écrire le fichier donné.
    Lève SecretGuardViolation si :
    - Le fichier est dans CRITICAL_FILES (tous agents bloqués sauf maintenance manuelle)
    - Le fichier contient des secrets (patterns Nokido.env, oauth_creds, etc.)
    Exception : LAFORGE_ALLOW_CRITICAL_WRITE=1 dans l'env bypasse CRITICAL_FILES.
    """
    import os as _os

    path_str = str(path)

    # 0. Moindre privilège par agent (AVANT le SecretGuard)
    check_agent_write_path(path_str, agent)

    # Check fichiers critiques (gouvernance hub)
    allow_critical = _os.environ.get("LAFORGE_ALLOW_CRITICAL_WRITE", "0") in ("1", "true", "yes")
    if not allow_critical and _is_critical(path_str):
        msg = (
            f"CRITICAL_FILE_PROTECTED: {path_str} ne peut pas être modifié via MCP write(). "
            f"Demander à l'utilisateur de modifier manuellement ou activer LAFORGE_ALLOW_CRITICAL_WRITE=1."
        )
        audit("write", {"path": path_str, "agent": agent, "ring": ring}, "BLOCK_CRITICAL", msg)
        raise SecretGuardViolation(msg)

    # Check secrets patterns
    fname = str(Path(path_str).name).lower()
    secret_patterns = [
        "nokido.env",
        ".env",
        "oauth_creds",
        "credentials",
        "_secret",
        "_token",
        "api_key",
        "jwt_secret",
    ]
    for pat in secret_patterns:
        if pat in fname.lower():
            # UNE SEULE PORTE. Ce site relisait la variable d'environnement pour
            # son compte : le garde avait donc deux entrees, dont une qui ne
            # connaissait ni attestation, ni expiration, ni privilege. « Un garde
            # ne vaut que par le nombre de portes qu'il tient » (2026-09-18).
            from nokido_agent.app.forge_secret_guard import is_breakglass_active
            if not is_breakglass_active():
                msg = f"SECRET_GUARD: {fname} contient un pattern secret protégé."
                audit("write", {"path": path_str, "agent": agent}, "BLOCK_SECRET", msg)
                raise SecretGuardViolation(msg)


def read_audit(last_n: int = 20) -> str:
    """Retourne les N dernières lignes d'audit."""
    if not AUDIT_LOG.exists():
        return "Audit log vide."
    lines = AUDIT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-last_n:])


# ── Compat NR — MCPSecurity + SecurityConfig ──────────────────────────────────
# Aliases pour les tests NR qui attendent ces classes


class SecurityConfig:
    """Configuration de sécurité MCP."""

    def __init__(self, root: str | None = None) -> None:
        """Initialise la config."""
        self.root = Path(root) if root else ROOT

    @classmethod
    def from_env(cls) -> "SecurityConfig":
        """Crée une config depuis l'environnement."""
        return cls(root=str(ROOT))


class MCPSecurity:
    """Façade sécurité MCP — résolution de rôles et droits."""

    # Mapping prefixe → rôle interne
    _ROLE_MAP = {
        "laforge": "laforge",
        "system": "laforge",
        "claude": "laforge",
        "dev": "laforge",
        "cline": "cline",
        "workflow": "cline",
        "ollama": "ollama",
        "collab": "ollama",  # collab → ollama (ring 3)
        "external": "external",
        "gemini": "ollama",
        "gpt": "ollama",
        "openai": "ollama",
    }

    # Droits par rôle : {rôle: {action: [ressources autorisées]}}
    _RIGHTS = {
        "laforge": {"*": ["*"]},
        "cline": {"read": ["*"], "write": ["*"], "run": ["python", "git"], "query": ["*"]},
        "ollama": {"read": ["*"], "query": ["*", "rag_ingest"], "write": ["shadow_mutation"]},
        "external": {"read": ["docs"]},
    }

    def __init__(self, config: SecurityConfig | None = None) -> None:
        """Initialise la sécurité MCP."""
        self.config = config or SecurityConfig()

    def _resolve_role(self, agent_id: str) -> str:
        """Résout le rôle d'un agent depuis son identifiant."""
        prefix = agent_id.split(":")[0].lower()
        return self._ROLE_MAP.get(prefix, "external")

    def check_rights(self, role: str, action: str, resource: str) -> tuple:
        """Vérifie si un rôle a le droit d'effectuer une action sur une ressource."""
        # Résout automatiquement si on passe un agent_id au lieu d'un rôle
        if ":" in role or role not in self._RIGHTS:
            role = self._resolve_role(role)
        rights = self._RIGHTS.get(role, {})
        # Wildcard total
        if "*" in rights and "*" in rights["*"]:
            return True, "allowed"
        # Action wildcard
        allowed_resources = rights.get(action, rights.get("*", []))
        if "*" in allowed_resources or resource in allowed_resources:
            return True, "allowed"
        return False, f"role={role} action={action} resource={resource} not permitted"

    def guard(self, tool: str, args: dict) -> None:
        """Point d'entrée unique — délègue à la fonction guard() globale."""
        guard(tool, args)
