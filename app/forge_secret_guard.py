"""
forge_secret_guard.py — Garde-fou centralise contre l'exfiltration de secrets
==============================================================================
Cree le 2026-04-25 suite a l'audit qui a revele :
  - 18 acces a Nokido.env via MCP read/python depuis le 2026-03-24
  - Pas de blocage car ring 0 = admin, contournement trivial via run.python
  - 13+ cles API en plain text exposees a chaque acces

Ce module pose la barriere generique :
  - is_protected_path(path) : detecte fichiers sensibles par patterns
  - assert_can_read(path, agent, ring) : leve SecretGuardViolation si bloque
  - sanitize_python_code(code) : detecte tentatives de lecture .env/secrets dans du code arbitraire
  - sanitize_sql(sql) : detecte SELECT sur tables sensibles (event_log payload, etc.)
  - log_breach_attempt(...) : enregistre dans event_log avec topic 'security.breach.*'

CONVENTION
----------
Le bypass officiel est UNIQUEMENT via la variable d'env :
  attestation dev-mode : tools/forge_dev_mode.py arm  (console ADMIN)
posee EXPLICITEMENT par l'utilisateur humain au lancement, jamais par defaut.
Ring 0 ne suffit plus.
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from typing import Optional, Tuple
from nokido_agent.app.forge_secrets import get_secret

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.SecretGuard")


# =============================================================================
# PATTERNS SENSIBLES — listes deliberement larges
# =============================================================================

SENSITIVE_FILENAME_PATTERNS = [
    # Env files
    r".*\.env$",
    r".*\.env\.[^.]+$",
    r"^\.env$",
    # Cles SSH
    r".*\.openssh$",
    r"id_rsa(\..*)?$",
    r"id_ed25519(\..*)?$",
    r"id_ecdsa(\..*)?$",
    r"id_dsa(\..*)?$",
    # Certificats / cles privees
    r".*\.pem$",
    r".*\.key$",
    r".*\.p12$",
    r".*\.pfx$",
    r".*\.crt$",
    # Secrets explicites
    r".*secret.*",
    r".*credential.*",
    r".*\.token$",
    # Coffres
    r".*\.kdbx$",
    r".*\.kdb$",
    r".*\.1p.*$",
    # Tokens git
    r"\.gh_token",
    r"\.codeberg_token",
    r"\.gitconfig",
    # Etat MCP / authority
    r"bridge_state\.json$",
    r"authority_state\.json$",
    # Bases de donnees
    r".*embeddings\.db$",
    r".*\.sqlite3?$",
]

_SENSITIVE_RE = re.compile("|".join(f"(?:{p})" for p in SENSITIVE_FILENAME_PATTERNS), re.IGNORECASE)


# Patterns code Python suspect
SUSPICIOUS_PYTHON_PATTERNS = [
    r"\.env['\"]\s*\)\s*\.read",
    r"open\s*\(\s*['\"][^'\"]*\.env",
    r"Path\s*\(\s*['\"][^'\"]*\.env",
    r"\.openssh['\"]\s*\)",
    r"\bid_rsa\b",
    r"\bid_ed25519\b",
    # credential_manager: retiré — faux positifs
    r"\bwin32cred\b",
    r"os\.environ\[['\"](?:GITHUB_TOKEN|OPENROUTER_API_KEY|GEMINI_API_KEY|XAI_API_KEY|"
    r"DEEPSEEK_API_KEY|ANTHROPIC_API_KEY|HF_TOKEN|GROQ_API_KEY|FORGE_MCP_TOKEN|"
    r"LAFORGE_ADMIN_TOKEN|MCP_DEV_SECRET|CODEBERG_TOKEN|SMITHERY_API|GITHUB_MODELS_TOKEN)",
    r"load_dotenv\s*\(",
    # Decoupe la litterale "secret" en patternes de retrievement
    # get_secret: retiré — appel légitime forge_secrets
]
_SUSPICIOUS_PY_RE = re.compile("|".join(SUSPICIOUS_PYTHON_PATTERNS), re.IGNORECASE)


# Patterns shell suspects (Anti-Bucheron Phase 1.3)
SUSPICIOUS_SHELL_PATTERNS = [
    # PowerShell — lecture .env / secrets
    r"Get-Content[\s'\"-]+[^\s]*\.env",
    r"Get-Content[\s'\"-]+[^\s]*secret",
    r"Get-Content[\s'\"-]+[^\s]*credential",
    r"Get-Content[\s'\"-]+[^\s]*token",
    r"Get-Content[\s'\"-]+[^\s]*\.pem",
    r"Get-Content[\s'\"-]+[^\s]*id_rsa",
    r"Get-ChildItem[\s'\"-]+.*\.env",
    r"\$env:.*TOKEN",
    r"\$env:.*KEY",
    r"\$env:.*SECRET",
    # PowerShell — Credential / WCM exfil
    r"Get-Credential",
    r"Export-PfxCertificate",
    r"ConvertFrom-SecureString",
    r"Get-StoredCredential",
    # PowerShell — Mimikatz / dump
    r"Invoke-Mimikatz",
    r"sekurlsa::",
    r"lsadump::",
    r"DumpCreds",
    # CMD findstr / type sur secrets
    r"findstr.*\.env",
    r"findstr.*password",
    r"findstr.*secret",
    r"\btype\s+[^\s]*\.env",
    r"\btype\s+[^\s]*\.pem",
    # Linux cat / grep / less sur secrets
    r"\bcat\s+[^\s]*\.env",
    r"\bcat\s+/etc/passwd",
    r"\bcat\s+/etc/shadow",
    r"\bcat\s+[^\s]*id_rsa",
    r"\bcat\s+[^\s]*\.pem",
    r"\bgrep\s+.*[Pp]assword",
    r"\bgrep\s+.*[Ss]ecret",
    r"\bless\s+[^\s]*\.env",
    r"\bless\s+/etc/shadow",
    # WMI / wmic / lsass dump
    r"\bwmic\b.*creden",
    r"\blsass\b",
    r"comsvcs\.dll.*MiniDump",
    # SSH key extraction
    r"~/\.ssh/id_",
    r"\.ssh/authorized_keys",
    r"~/\.aws/credentials",
    r"\.docker/config\.json",
    # rm -rf destructeur (anti-bucheron literal)
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"rm\s+-rf\s+\$HOME",
    r"sudo\s+rm\s+-rf",
    r"Remove-Item.*-Recurse.*-Force.*[Cc]:",
    # Curl/wget post exfil credentials
    r"curl[^|]*\|[^|]*sh",
    r"wget[^|]*\|[^|]*sh",
    r"curl.*-d.*\$\(",
    r"curl.*-d.*\$env",
    # netcat reverse shell
    r"\bnc\b\s+-l\s+-p\s+\d+",
    r"\bncat\b.*-e\s+/bin/",
    r"bash\s+-i\s+>&\s*/dev/tcp/",
    # base64 obfuscation autour de secrets
    r"echo\s+[A-Za-z0-9+/=]{40,}\s*\|\s*base64\s+-d",
]
_SUSPICIOUS_SHELL_RE = re.compile("|".join(f"(?:{p})" for p in SUSPICIOUS_SHELL_PATTERNS), re.IGNORECASE)


# Patterns SQL suspects
SENSITIVE_SQL_TABLES = {
    "event_log",
    "shared_prompt_log",
    "system_rules",
    "promotion_queue",
}
# Un nom de table peut etre CITE — `"t"`, `[t]`, `` `t` `` sont tous valides en
# SQLite. Mesure du 2026-09-18 : `SELECT * FROM "system_rules"` FRANCHISSAIT le
# garde, qui n'acceptait qu'un `\w+` nu. Le contournement ne demandait pas une
# injection, juste une paire de guillemets — un garde qu'on franchit en
# re-orthographiant son intention ne garde rien.
_IDENT = r"[\"\[`]?(\w+)[\"\]`]?"

_SQL_SELECT_RE = re.compile(
    r"\bSELECT\b.*?\bFROM\b\s+" + _IDENT, re.IGNORECASE | re.DOTALL)

# Les litteraux de CHAINE sont neutralises avant tout scan : le verbe d'une
# requete ne peut pas vivre dans une chaine, donc un mot-clef qu'on y trouve est
# du TEXTE et non une intention. Sans cela, `SELECT 'update system_rules'`
# declenchait un refus — et un garde qui crie a faux se fait desarmer.
# Seules les quotes SIMPLES sont videes : en SQLite `"..."` designe un
# IDENTIFIANT, pas une chaine ; les vider rouvrirait le contournement ci-dessus.
_SQL_CHAINE_RE = re.compile(r"'[^']*(?:''[^']*)*'")


def _hors_chaines(sql: str) -> str:
    """Rend le SQL prive de ses litteraux de chaine, longueurs preservees."""
    return _SQL_CHAINE_RE.sub(lambda m: " " * len(m.group(0)), sql)


# Les verbes d'ECRITURE, et la table qu'ils visent.
#
# AUDIT SECURITE 2026-09-18. Le garde ci-dessus ne voit QUE les SELECT : sa
# docstring le disait, et personne n'avait tire le fil. Mesure sur le chemin
# reel, sans modifier une seule ligne :
#
#     SELECT rowid FROM system_rules LIMIT 1        -> SECRET GUARD: SQL bloque
#     UPDATE system_rules SET rowid=rowid WHERE 0=1 -> Mutation OK
#
# Autrement dit LIRE une table sensible etait interdit et l'ECRIRE etait permis,
# `event_log` compris — le journal d'audit lui-meme. Une protection qui couvre
# la confidentialite et laisse l'integrite ouverte protege le secret d'une
# donnee que n'importe qui peut effacer.
#
# PORTEE, dite franchement : ces motifs lisent du TEXTE. Ils attrapent les
# formes courantes, pas un SQL deguise (commentaire `/* */` insere au milieu
# d'un verbe, requete construite par concatenation). Ce n'est pas le garde
# ultime de l'integrite — c'est la fin d'une INVERSION. Le jour ou l'ecriture
# par cette route doit etre gouvernee pour de bon, cela se fait par l'autorite
# de l'appelant (ring, agent), pas par un motif plus long.
_SQL_WRITE_RES = (
    re.compile(r"\bUPDATE\b\s+" + _IDENT, re.IGNORECASE),
    re.compile(r"\bDELETE\b\s+FROM\s+" + _IDENT, re.IGNORECASE),
    re.compile(r"\bINSERT\b(?:\s+OR\s+\w+)?\s+INTO\s+" + _IDENT, re.IGNORECASE),
    re.compile(r"\bREPLACE\b\s+INTO\s+" + _IDENT, re.IGNORECASE),
    re.compile(
        r"\bDROP\b\s+(?:TABLE|INDEX|VIEW|TRIGGER)\s+(?:IF\s+EXISTS\s+)?" + _IDENT,
        re.IGNORECASE),
    re.compile(r"\bALTER\b\s+TABLE\s+" + _IDENT, re.IGNORECASE),
    re.compile(
        r"\bCREATE\b\s+(?:TEMP\s+|TEMPORARY\s+)?(?:TABLE|INDEX|VIEW|TRIGGER)\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?" + _IDENT,
        re.IGNORECASE),
)


# =============================================================================
# EXCEPTIONS
# =============================================================================


class SecretGuardViolation(Exception):
    """Levee quand un acces aux secrets est bloque."""

    pass


# =============================================================================
# CHECKS
# =============================================================================


def is_protected_path(path) -> bool:
    """True si le path matche un pattern sensible (full path OU basename)."""
    if path is None:
        return False
    p = str(path)
    if not p:
        return False
    if _SENSITIVE_RE.search(p):
        return True
    basename = os.path.basename(p)
    if basename and _SENSITIVE_RE.match(basename):
        return True
    return False


def is_breakglass_active() -> bool:
    """True si une ATTESTATION dev-mode valide est armee.

    Ne lit PLUS `LAFORGE_ALLOW_SECRETS_READ`. Une variable d'environnement est
    posable par n'importe quel process du meme compte, sans trace, sans
    expiration et sans privilege : elle ne peut pas commander cinq gardes
    (`assert_can_read`, `sanitize_python_code`, `sanitize_shell_command`,
    `sanitize_sql`, `assert_can_write`).

    MESURE QUI A TRANCHE (2026-09-20, directive owner) : 2416 interventions du
    garde journalisees, ZERO usage du breakglass. Le « 0 » vaut parce que la
    source parle -- 57 journaux sandbox et 9154 logs sont lisibles a cote. Un
    filet jamais emprunte en 2416 occasions n'est pas un filet.

    Defaut supplementaire mesure le meme jour : mis en cache par `get_secret`,
    la bascule SURVIVAIT au retrait de la variable -- le garde restait ouvert
    apres que l'operateur l'avait referme. 15 NR du garde SQL l'ont dit.

    FAIL-CLOSED : toute incertitude REFUSE. Le cout des deux erreurs n'est pas
    symetrique -- refuser a tort gene un operateur qui peut re-armer ; autoriser
    a tort ouvre cinq gardes en silence.

    GESTE QUI ARME, en console ADMINISTRATEUR hors agent :
        LAFORGE_PYTHON tools/forge_dev_mode.py arm
    (etat : `... forge_dev_mode.py status` ; fermeture : `... disarm`)
    Le CLI prend une ACTION NUE, sans tirets : `--arm` n'est pas reconnu et
    tombe dans l'aide. Mesure du 2026-09-21 -- j'avais ecrit `--arm` dans six
    messages de refus, dans le commit meme ou je corrigeais ce defaut ailleurs.
    Depuis le compte du hub (non admin) le breakglass est donc INATTEIGNABLE.
    C'est voulu, et c'est le meme choix que pour `ps_clm` depuis le 2026-09-19 :
    un interrupteur a portee de ce qu'il contraint ne garde rien.
    """
    try:
        from nokido_agent.tools.forge_dev_mode import is_armed
        arme, restant = is_armed()
    except Exception:          # noqa: BLE001 — attestation illisible = REFUS
        return False
    return bool(arme) and restant > 0


def is_dev_mode() -> bool:
    """True si LAFORGE_ENV=dev ou LAFORGE_MCP_DEV=true.
    En mode dev : warn au lieu de block (comme Sentinel ring 1-2).
    """
    return os.environ.get("LAFORGE_ENV", "prod").lower() == "dev" or os.environ.get(
        "LAFORGE_MCP_DEV", "false"
    ).lower() in ("true", "1")


def assert_can_read(path, agent: str, ring: int) -> None:
    """Leve SecretGuardViolation si la lecture est bloquee."""
    if not is_protected_path(path):
        return
    if is_breakglass_active():
        logger.warning(f"[BREAKGLASS] Secret read autorise: agent={agent} ring={ring} path={path}")
        log_breach_attempt("breakglass_read", agent, ring, str(path), blocked=False)
        return
    log_breach_attempt("protected_read", agent, ring, str(path), blocked=True)
    raise SecretGuardViolation(
        f"SECRET GUARD: Acces refuse a '{path}'. "
        f"Deblocage : attestation dev-mode -- 'tools/forge_dev_mode.py arm', en console ADMIN."
    )


def sanitize_python_code(code: str, agent: str, ring: int) -> Optional[str]:
    """None si OK, message d'erreur si violation."""
    if not code:
        return None
    code = code[:_MAX_SCAN_LEN]  # DoS bound
    matches = _SUSPICIOUS_PY_RE.findall(code)
    if not matches:
        return None
    if is_breakglass_active():
        logger.warning(f"[BREAKGLASS] Code Python suspect autorise: agent={agent} matches={matches[:3]}")
        log_breach_attempt(
            "breakglass_python",
            agent,
            ring,
            None,
            blocked=False,
            extra={"matches": matches[:5], "code_preview": code[:200]},
        )
        return None
    if is_dev_mode():
        logger.warning(f"[DEV_MODE] Code Python suspect warn only: agent={agent} matches={matches[:3]}")
        log_breach_attempt(
            "dev_python_warn",
            agent,
            ring,
            None,
            blocked=False,
            extra={"matches": matches[:5], "code_preview": code[:200]},
        )
        return None
    log_breach_attempt(
        "suspicious_python", agent, ring, None, blocked=True, extra={"matches": matches[:5], "code_preview": code[:200]}
    )
    return (
        f"SECRET GUARD: Code Python bloque (acces secret detecte: {matches[:3]}). "
        f"Deblocage : 'tools/forge_dev_mode.py arm' (console ADMIN)."
    )


def sanitize_shell_command(cmd: str, agent: str, ring: int) -> Optional[str]:
    """Anti-Bucheron Phase 1.3 — None si OK, message si shell command suspect.

    Bloque : Get-Content .env, findstr/cat secrets, mimikatz, lsass dump,
    rm -rf /, ssh key exfil, reverse shells, base64 obfusc.
    """
    if not cmd:
        return None
    cmd = cmd[:_MAX_SCAN_LEN]  # DoS bound
    matches = _SUSPICIOUS_SHELL_RE.findall(cmd)
    if not matches:
        return None
    if is_breakglass_active():
        logger.warning(f"[BREAKGLASS] Shell command suspect autorise: agent={agent} matches={matches[:3]}")
        log_breach_attempt(
            "breakglass_shell",
            agent,
            ring,
            None,
            blocked=False,
            extra={"matches": matches[:5], "cmd_preview": cmd[:200]},
        )
        return None
    if is_dev_mode():
        logger.warning(f"[DEV_MODE] Shell suspect warn only: agent={agent} matches={matches[:3]}")
        log_breach_attempt(
            "dev_shell_warn", agent, ring, None, blocked=False, extra={"matches": matches[:5], "cmd_preview": cmd[:200]}
        )
        return None
    log_breach_attempt(
        "suspicious_shell", agent, ring, None, blocked=True, extra={"matches": matches[:5], "cmd_preview": cmd[:200]}
    )
    return (
        f"SECRET GUARD: Shell command bloquee (pattern dangereux: {matches[:3]}). "
        f"Deblocage : 'tools/forge_dev_mode.py arm' (console ADMIN)."
    )


def sanitize_sql(sql: str, agent: str, ring: int) -> Optional[str]:
    """None si OK, message d'erreur si LECTURE **ou ECRITURE** sur table sensible.

    L'ecriture a ete ajoutee le 2026-09-18 : jusque-la seuls les SELECT etaient
    inspectes, si bien qu'une table protegee en lecture restait librement
    modifiable et effacable (cf. `_SQL_WRITE_RES` pour la mesure).
    """
    if not sql:
        return None
    sql = sql[:_MAX_SCAN_LEN]  # DoS bound
    _scan = _hors_chaines(sql)
    lus = [t for t in _SQL_SELECT_RE.findall(_scan) if t.lower() in SENSITIVE_SQL_TABLES]
    ecrits = [
        t
        for motif in _SQL_WRITE_RES
        for t in motif.findall(_scan)
        if t.lower() in SENSITIVE_SQL_TABLES
    ]
    sensible_hits = sorted(set(lus) | set(ecrits))
    if not sensible_hits:
        return None
    # Le VERBE est nomme : un refus qui ne distingue pas une lecture d'un
    # effacement laisse croire a une gene de confort. Ce n'en est pas une.
    acces = "ECRITURE" if ecrits else "lecture"
    if is_breakglass_active():
        logger.warning(
            f"[BREAKGLASS] SQL table sensible autorise ({acces}): agent={agent} tables={sensible_hits}")
        return None
    log_breach_attempt(
        "sensitive_sql", agent, ring, None, blocked=True,
        extra={"tables": sensible_hits, "acces": acces, "sql_preview": sql[:200]},
    )
    return (
        f"SECRET GUARD: SQL bloque ({acces} sur table sensible: {sensible_hits}). "
        f"Tables protegees : {sorted(SENSITIVE_SQL_TABLES)}."
    )


def assert_can_write(path, agent: str, ring: int) -> None:
    """Leve SecretGuardViolation si on tente d'ecrire sur un path sensible."""
    if not is_protected_path(path):
        return
    if is_breakglass_active():
        logger.warning(f"[BREAKGLASS] Secret write autorise: agent={agent} path={path}")
        log_breach_attempt("breakglass_write", agent, ring, str(path), blocked=False)
        return
    log_breach_attempt("protected_write", agent, ring, str(path), blocked=True)
    raise SecretGuardViolation(
        f"SECRET GUARD: Ecriture refusee sur '{path}'. "
        f"Deblocage : 'tools/forge_dev_mode.py arm' (console ADMIN)."
    )


# =============================================================================
# LOGGING DES TENTATIVES
# =============================================================================


def log_breach_attempt(
    kind: str,
    agent: str,
    ring: int,
    path: Optional[str] = None,
    blocked: bool = True,
    extra: Optional[dict] = None,
) -> None:
    """Enregistre une tentative d'acces sensible dans event_log + add_notification."""
    if agent in {"TEST", "SELFTEST", "PYTEST"}:
        return
    try:
        from nokido_agent.app.forge_state_manager import get_state_manager, EventBus

        sm = get_state_manager()
        eb = EventBus(sm)
        data = {
            "kind": kind,
            "agent": agent,
            "ring": ring,
            "path": path,
            "blocked": blocked,
        }
        if extra:
            data["extra"] = extra
        eb.publish(
            topic=f"security.breach.{kind}",
            kind="security_alert",
            data=data,
            agent="SECRET_GUARD",
            trusted=True,
        )
        sm.add_notification(
            f"[SECRET_GUARD {'BLOCK' if blocked else 'ALLOW'}] {agent} ring={ring} kind={kind} path={path}",
            source="SECRET_GUARD",
        )
        # ── network_log SQLite (visible dashboard /forge/network) ─────
        try:
            import sqlite3 as _sq, pathlib as _pl

            _db = _pl.Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
            _st = "BLOCKED" if blocked else "ALLOWED"
            _cn = _sq.connect(str(_db), timeout=3)
            _cn.execute("PRAGMA journal_mode=WAL")
            _cn.execute(
                "INSERT INTO network_log (ts,direction,method,tool,agent,ring,status,channel,meta) "
                "VALUES (datetime('now'),'IN','security.breach',?,?,?,?,'SECURITY',?)",
                (kind, agent, ring, _st, f"{{kind={kind},path={str(path)[:80]},blocked={blocked}}}"),
            )
            _cn.commit()
            _cn.close()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[SECRET_GUARD] Echec log_breach_attempt: {e}")


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    cases_path = [
        ("Nokido.env", True),
        ("sample.env", True),
        ("docs/CONTRIBUTING.md", False),
        ("/home/user/.env", True),
        ("C:/Users/Example/secret.openssh", True),
        ("RAG/embeddings.db", True),
        ("bridge_state.json", True),
        ("sandbox/random_data.json", False),
        ("id_rsa", True),
        ("id_ed25519.pub", True),
        ("logs/mcp_service.log", False),
        ("config/secrets.json", True),
        ("my_credentials.txt", True),
        ("base.kdbx", True),
    ]
    print("=== Self-test is_protected_path ===")
    ok = fail = 0
    for path, expected in cases_path:
        actual = is_protected_path(path)
        marker = "OK" if actual == expected else "FAIL"
        if actual == expected:
            ok += 1
        else:
            fail += 1
        print(f"  [{marker}] {path:40} -> {actual} (expected {expected})")
    print(f"path: {ok} OK / {fail} FAIL\n")

    print("=== Self-test sanitize_python_code ===")
    suspects = [
        ("print('hello')", False),
        ("Path('Nokido.env').read_text()", True),
        ("import os; print(os.environ['GITHUB_TOKEN'])", True),
        ("from dotenv import load_dotenv", True),
        ("# innocent comment about Nokido.env", False),  # commentaire OK
        ("x = 1 + 1", False),
        ("import dotenv", True),
        ("a = my_func(id_rsa=True)", True),  # variable name id_rsa = mauvais signal
        ("subprocess.run([cmd], env=os.environ)", True),
    ]
    ok2 = fail2 = 0
    for code, expected_block in suspects:
        result = sanitize_python_code(code, "TEST", 0)
        blocked = result is not None
        marker = "OK" if blocked == expected_block else "FAIL"
        if blocked == expected_block:
            ok2 += 1
        else:
            fail2 += 1
        print(f"  [{marker}] expected={expected_block} actual_blocked={blocked} : {code[:55]}")
    print(f"py: {ok2} OK / {fail2} FAIL\n")

    print("=== Self-test sanitize_sql ===")
    sql_cases = [
        ("SELECT * FROM rag_chunks LIMIT 5", False),
        ("SELECT * FROM event_log", True),
        ("SELECT payload FROM event_log WHERE id > 1", True),
        ("SELECT name FROM sqlite_master", False),
        ("DROP TABLE event_log", False),  # pas un SELECT, blocage par autre garde a faire
        ("select content from shared_prompt_log", True),  # case-insensitive
    ]
    ok3 = fail3 = 0
    for sql, expected_block in sql_cases:
        result = sanitize_sql(sql, "TEST", 0)
        blocked = result is not None
        marker = "OK" if blocked == expected_block else "FAIL"
        if blocked == expected_block:
            ok3 += 1
        else:
            fail3 += 1
        print(f"  [{marker}] expected={expected_block} actual_blocked={blocked} : {sql[:55]}")
    print(f"sql: {ok3} OK / {fail3} FAIL\n")

    total_ok = ok + ok2 + ok3
    total_fail = fail + fail2 + fail3
    print(f"=== TOTAL: {total_ok} OK / {total_fail} FAIL ===")


# =============================================================================
# SCAN OUTBOUND — bloque les secrets dans les prompts avant envoi cloud
# Session 5 — 2026-04-27
# =============================================================================

import re as _re

_OUTBOUND_PATTERNS = [
    (_re.compile(r"sk-[A-Za-z0-9]{32,}"), "OpenAI/Anthropic key"),
    (_re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "Google API key"),
    (_re.compile(r"gsk_[A-Za-z0-9]{50,}"), "Groq key"),
    (_re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}"), "GitHub token"),
    # 2026-09-24 — MESURE sur des cles fictives a la forme reelle : ces formes passaient
    # EN CLAIR par les deux redacteurs. `sk-[A-Za-z0-9]{32,}` ne couvre ni `sk-ant-`,
    # ni `sk-proj-`, ni `sk-or-v1-` (le tiret casse la classe) : le blocage des prompts
    # sortants ne voyait donc pas les cles Anthropic, OpenAI projet et OpenRouter.
    (_re.compile(r"github_pat_[A-Za-z0-9_]{50,}"), "GitHub fine-grained token"),
    (_re.compile(r"sk-ant-[a-z]+\d*-[A-Za-z0-9_\-]{60,}"), "Anthropic key"),
    (_re.compile(r"sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{40,}"), "OpenAI project key"),
    (_re.compile(r"sk-or-v1-[A-Za-z0-9]{32,}"), "OpenRouter key"),
    (_re.compile(r"\bhf_[A-Za-z0-9]{30,}"), "Hugging Face token"),
    (_re.compile(r"(?:xoxb|xoxp)-[0-9A-Za-z\-]{50,}"), "Slack token"),
    (_re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (_re.compile(r"[Mm]istral[_\-]?[Kk]ey[\s:=]+[A-Za-z0-9]{20,}"), "Mistral key"),
    (_re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.]{30,}"), "Bearer token"),
    (_re.compile(r"FORGE_MCP_TOKEN\s*=\s*[A-Za-z0-9]{20,}"), "Nokido token"),
    (_re.compile(r"[A-Za-z0-9]{64}"), "Hex-64 secret (possible token)"),
]


class SecretLeakBlocked(RuntimeError):
    """Levée quand un secret est détecté dans un prompt outbound."""

    def __init__(self, label: str, snippet: str):
        self.label = label
        self.snippet = snippet
        super().__init__(f"[SecretGuard.outbound] BLOQUE — {label} dans prompt: {snippet!r}")


# DoS bound (regex-DoS via payload forge) : on borne la taille scannee.
# Un secret legitime tient largement dans 256KB ; au-dela = anomalie, on tronque pour scanner.
_MAX_SCAN_LEN = int(os.environ.get("LAFORGE_MAX_SCAN_LEN", "262144"))


def scan_outbound(prompt: str, provider: str = "unknown", local_only: bool = False) -> None:
    """
    Scanner le prompt AVANT envoi vers un provider cloud.
    - Si local_only=True : bypass (Ollama/llama.cpp — rien ne quitte la machine)
    - Lève SecretLeakBlocked si un pattern secret est trouvé
    - Log WARN dans tous les cas de détection
    """
    if local_only:
        return  # local — rien ne quitte la machine

    prompt = prompt[:_MAX_SCAN_LEN]  # DoS bound : borne la taille scannee
    for pattern, label in _OUTBOUND_PATTERNS:
        m = pattern.search(prompt)
        if m:
            snippet = m.group(0)[:12] + "***"
            logger.critical(
                "[SecretGuard.outbound] SECRET detecte avant envoi %s — %s — snippet: %s", provider, label, snippet
            )
            raise SecretLeakBlocked(label, snippet)

    logger.debug("[SecretGuard.outbound] OK prompt propre vers %s (%d chars)", provider, len(prompt))
