"""
forge_opsec.py — Rules of Engagement (OPSEC Levels)

Bouclier OPSEC dynamique 3 niveaux :
- PARANOID (default) : membrane HMAC full + NoiseGuardian + SecretGuard
- STANDARD           : SecretGuard only (passwords/tokens), garde IPs/paths lisibles
- CTF                : bypass complet — flags/hashes/creds en clair pour résolution

Switch à chaud via JSON-RPC `set_opsec_level` (forge_trajectory).
État persisté SQLite pour cross-session.

Réutilise :
- forge_sovereign_membrane.SovereignMembrane (wrap/unwrap HMAC alias)
- forge_silo_fragmenter.NoiseGuardian (neutralize IPs/MACs/CVEs/magic)
- forge_secret_guard (SUSPICIOUS patterns + .env / tokens)

Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:opsec|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
_DB_HISTORIQUE = ROOT / "RAG" / "embeddings.db"


class _BaseAutorite:
    """Chemin de la base portant `opsec_state`, resolu A CHAQUE `str()`.

    Pourquoi pas une constante (2026-09-13). `opsec_state` est le kill-switch
    humain de dernier recours, et il vivait dans la base RAG -- que le compte
    client ecrit. Le deplacer exige de rediriger TOUS ses lecteurs d'un coup :
    un site qui bascule seul donne un hub qui ECRIT d'un cote et LIT de
    l'autre, donc un kill-switch qui parait pose sans proteger quoi que ce soit.

    Ce module lit `DEFAULT_DB` a neuf endroits, tous via `str(DEFAULT_DB)`.
    Rendre la RESOLUTION dynamique les redirige tous ensemble, sans toucher
    neuf sites dans un fichier critique. Une constante figee a l'import ne se
    redirige pas -- defaut paye le 2026-09-10 puis repaye le 2026-09-12.

    Tant que l'interrupteur `etat_protege/authority.switch` est absent,
    `authority_path()` rend la base RAG : le comportement est INCHANGE.
    """

    def __str__(self) -> str:
        try:
            from nokido_agent.app.forge_db_path import authority_path

            return authority_path()
        except Exception:  # noqa: BLE001 - fail-safe vers l'historique, jamais vers rien
            return str(_DB_HISTORIQUE)

    def __fspath__(self) -> str:
        return str(self)

    def __repr__(self) -> str:
        return "_BaseAutorite(%r)" % str(self)

    def __getattr__(self, nom):
        # Delegue a Path pour tout usage non prevu (.exists(), .parent, ...) :
        # un futur appelant ne doit pas tomber sur un AttributeError.
        return getattr(Path(str(self)), nom)


DEFAULT_DB = _BaseAutorite()

# ── Bind mount mirror (Centaure persistence layer) ────────────────────────────
# Cf nokido_persist/README.md : double-écriture SQLite + JSON sur volume Windows
# natif (hors VHDX) → compatible VSS / Historique de fichiers Windows.
_PERSIST_DIR = Path(__import__("os").environ.get("LAFORGE_PERSIST_DIR") or str(ROOT / "nokido_persist"))
_STATE_MIRROR = _PERSIST_DIR / "state.json"


def _write_state_mirror(level: "OpsecLevel", locked: bool, set_by: str, reason: str) -> None:
    """Écrit miroir JSON de l état OPSEC. Best-effort, ne lève jamais."""
    try:
        _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "opsec_level": level.name,
            "level_int": int(level),
            "human_locked": bool(locked),
            "network_kill": is_network_kill(),
            "last_change_ts": time.time(),
            "last_change_by": set_by,
            "last_reason": reason[:500],
            "schema": "nokido.opsec.state.v2",
        }
        tmp = _STATE_MIRROR.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(_STATE_MIRROR)
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # « best-effort » ne veut pas dire « sans consequence » : ce miroir est ce qui
        # RESTAURE le niveau opsec au boot quand SQLite revient vide. Un miroir jamais
        # ecrit, c'est un filet dont on ne decouvre l'absence qu'au moment de tomber.
        _lg.getLogger(__name__).warning(
            "[opsec] miroir d'etat NON ecrit (%s: %s) | consequence: en cas de base "
            "vide au prochain boot, il n'y aura rien a restaurer",
            type(e).__name__, str(e)[:100])


def _read_state_mirror() -> Optional[Dict[str, Any]]:
    """Lit miroir JSON si SQLite indisponible (cas conteneur ré-instancié)."""
    try:
        if _STATE_MIRROR.exists():
            return json.loads(_STATE_MIRROR.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _restore_from_mirror_if_db_empty() -> None:
    """Boot helper : si SQLite n a pas de state mais miroir JSON existe, restaure."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        row = conn.execute("SELECT value FROM opsec_state WHERE key='current_level'").fetchone()
        if row:
            conn.close()
            return  # SQLite déjà peuplée → rien à faire
        mirror = _read_state_mirror()
        if not mirror:
            conn.close()
            return
        try:
            lvl = OpsecLevel[mirror["opsec_level"]]
        except (KeyError, ValueError):
            conn.close()
            return
        now = time.time()
        conn.execute(
            "INSERT OR REPLACE INTO opsec_state (key, value, set_by, reason, updated_at) VALUES (?,?,?,?,?)",
            ("current_level", str(int(lvl)), "boot_restore", "from JSON mirror", now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO opsec_state (key, value, set_by, reason, updated_at) VALUES (?,?,?,?,?)",
            ("human_locked", "1" if mirror.get("human_locked") else "0", "boot_restore", "from JSON mirror", now),
        )
        conn.execute(
            "INSERT INTO opsec_audit_log (action, old_level, new_level, set_by, reason, ts) VALUES (?,?,?,?,?,?)",
            ("RESTORE_FROM_MIRROR", "", lvl.name, "boot_restore", "SQLite empty, JSON mirror present", now),
        )
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        # POSTURE DE SECURITE. Si la restauration echoue, le niveau opsec reste a son
        # DEFAUT alors qu'un niveau superieur avait ete choisi : le systeme se relit
        # comme configure, il ne l'est pas. Un silence ici est un abaissement de
        # protection invisible.
        _lg.getLogger(__name__).error(
            "[opsec] restauration depuis le miroir ECHOUEE (%s: %s) | consequence: le "
            "niveau opsec reste au DEFAUT alors qu'un niveau avait ete enregistre — "
            "verifier avant de considerer la posture comme appliquee",
            type(e).__name__, str(e)[:100])


class OpsecLevel(IntEnum):
    CTF = 0  # bypass complet (HackTheBox, Root-Me, lab)
    STANDARD = 1  # masque secrets vitaux uniquement
    PARANOID = 2  # masque tout (default — audit entreprise, cible réelle)


# Default = PARANOID au boot
_DEFAULT_LEVEL = OpsecLevel.PARANOID

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opsec_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    set_by TEXT,
    reason TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS opsec_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    old_level TEXT,
    new_level TEXT,
    set_by TEXT,
    reason TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opsec_audit_ts ON opsec_audit_log(ts);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in _SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)
    conn.commit()


# ============================================================
# State management (persisté + cache RAM)
# ============================================================
_cached_level: Optional[OpsecLevel] = None
_cached_at: float = 0.0
_CACHE_TTL = 30.0  # 30s cache RAM


def get_opsec_level() -> OpsecLevel:
    """Niveau OPSEC courant (cache 30s + fallback DB + default PARANOID)."""
    global _cached_level, _cached_at
    now = time.time()
    if _cached_level is not None and (now - _cached_at) < _CACHE_TTL:
        return _cached_level
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        row = conn.execute("SELECT value FROM opsec_state WHERE key='current_level'").fetchone()
        conn.close()
        if row:
            try:
                lvl = OpsecLevel(int(row[0]))
                _cached_level = lvl
                _cached_at = now
                return lvl
            except ValueError:
                pass
    except Exception:
        pass
    _cached_level = _DEFAULT_LEVEL
    _cached_at = now
    return _DEFAULT_LEVEL


ETAT_VERROUILLE = "VERROUILLE"
ETAT_NON_VERROUILLE = "NON_VERROUILLE"
ETAT_ILLISIBLE = "ILLISIBLE"

# Une marque par couple (cle, motif) : journaliser a CHAQUE appel noierait le
# signal (le dispatch MCP consulte a chaque tool), ne jamais journaliser rend la
# panne d'un interrupteur d'arret indetectable. Le compromis est un cri par cause.
_ILLISIBLE_DEJA_DIT: set = set()


def _dire_illisible(cle: str, motif: str) -> None:
    """Un capteur d'ARRET qui echoue doit s'entendre."""
    marque = "%s|%s" % (cle, motif[:120])
    if marque in _ILLISIBLE_DEJA_DIT:
        return
    _ILLISIBLE_DEJA_DIT.add(marque)
    try:
        import logging as _lg
        _lg.getLogger("Nokido.Security").critical(
            "[OPSEC] drapeau '%s' ILLISIBLE (%s) - l'etat de l'interrupteur "
            "d'arret ne peut pas etre constate ; les tools mutants sont refuses",
            cle, motif)
    except Exception:  # noqa: BLE001 - le journal ne casse jamais un capteur d'arret
        pass


def _etat_drapeau(cle: str) -> Tuple[str, str]:
    """Lit un drapeau opsec en TROIS etats : verrouille / non / illisible.

    MESURE DU 2026-09-12 qui a impose cette forme. `is_human_locked` rendait
    `False` pour « pas verrouille » ET pour « je n'ai pas pu lire », en silence.
    Rendre la base illisible desarmait donc l'interrupteur d'arret humain sans
    laisser de trace : UNKNOWN valait AUTORISE sur le garde ou cette direction
    coute le plus cher. Un appelant qui doit REFUSER sur l'incertitude lit cette
    fonction ; ceux qui veulent un bool gardent `is_human_locked`.

    Ce que cette fonction NE corrige PAS : l'etat vit dans `RAG/embeddings.db`,
    que le compte client peut ecrire (verrou d'ecriture obtenu le 2026-09-12,
    aucun trigger sur `opsec_state`). Elle ferme le desarmement par ILLISIBILITE,
    pas le desarmement par ECRITURE.
    """
    try:
        conn = sqlite3.connect(str(DEFAULT_DB), timeout=5.0)
        try:
            _ensure_schema(conn)
            row = conn.execute(
                "SELECT value FROM opsec_state WHERE key=?", (cle,)).fetchone()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - toute panne de lecture = ILLISIBLE, jamais NON
        motif = "%s: %s" % (type(e).__name__, str(e)[:160])
        _dire_illisible(cle, motif)
        return (ETAT_ILLISIBLE, motif)
    if row and row[0] == "1":
        return (ETAT_VERROUILLE, "")
    return (ETAT_NON_VERROUILLE,
            "ligne absente" if row is None else "valeur=%r" % (row[0],))


def human_lock_state() -> Tuple[str, str]:
    """Etat de l'off-switch HUMAIN, en trois valeurs. (etat, motif)."""
    return _etat_drapeau("human_locked")


def network_kill_state() -> Tuple[str, str]:
    """Etat du kill-switch RESEAU, en trois valeurs. (etat, motif)."""
    return _etat_drapeau("network_kill")


def is_human_locked() -> bool:
    """True si l'humain a verrouillé via l'UI.

    CONTRAT BOOLÉEN PRÉSERVÉ pour les huit appelants existants (forge_circadian,
    forge_docker_monitor, forge_service_watchdog, forge_skill_policy,
    forge_corrigibility, et trois usages internes) : un état ILLISIBLE rend
    toujours `False` ici — mais il est désormais JOURNALISÉ en CRITICAL par le
    capteur. Un garde qui doit refuser sur l'incertitude appelle
    `human_lock_state()` et lit les trois états.

    ⚠️ L'ancienne docstring affirmait « IA ne peut plus changer ». C'est une
    DÉCLARATION que la mesure du 2026-09-12 contredit : l'état est une ligne de
    `opsec_state` dans `RAG/embeddings.db`, base sur laquelle le compte client
    obtient le verrou d'écriture, sans trigger ni ACL séparée. Le verrou protège
    contre une IA qui respecte le contrat, pas contre une qui écrit la table.
    """
    return human_lock_state()[0] == ETAT_VERROUILLE


def is_network_kill() -> bool:
    """True si le Kill Switch Sémantique est actif — bloque TOUS outbounds cloud.

    Même contrat que `is_human_locked` : bool pour les appelants existants,
    `network_kill_state()` pour qui doit refuser sur l'incertitude.
    """
    return network_kill_state()[0] == ETAT_VERROUILLE


def trigger_kill_switch(reason: str = "human emergency") -> dict:
    """KILL SWITCH SÉMANTIQUE — atomic : PARANOID + LOCK + network_kill=true.

    Action irréversible par AI. Seul humain peut désactiver via release_kill_switch().
    """
    try:
        now = time.time()
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        for k, v in [
            ("current_level", str(int(OpsecLevel.PARANOID))),
            ("human_locked", "1"),
            ("network_kill", "1"),
        ]:
            conn.execute(
                "INSERT OR REPLACE INTO opsec_state (key, value, set_by, reason, updated_at) VALUES (?,?,?,?,?)",
                (k, v, "kill_switch", reason[:500], now),
            )
        conn.execute(
            "INSERT INTO opsec_audit_log (action, old_level, new_level, set_by, reason, ts) VALUES (?,?,?,?,?,?)",
            ("KILL_SWITCH_TRIGGERED", "", OpsecLevel.PARANOID.name, "human_emergency", reason[:500], now),
        )
        conn.commit()
        conn.close()
        # Cache invalidation
        global _cached_level, _cached_at
        _cached_level = OpsecLevel.PARANOID
        _cached_at = now
        # Mirror JSON
        _write_state_mirror_kill(OpsecLevel.PARANOID, True, True, "kill_switch", reason)
        return {
            "ok": True,
            "kill_switch": True,
            "level": "PARANOID",
            "human_locked": True,
            "network_kill": True,
            "reason": reason,
            "ts": now,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def release_kill_switch(set_by: str = "human", reason: str = "manual release") -> dict:
    """Désactive Kill Switch (humain only — pas via AI).

    Garde lock human + level PARANOID, lève seulement le network_kill.
    """
    try:
        now = time.time()
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO opsec_state (key, value, set_by, reason, updated_at) VALUES (?,?,?,?,?)",
            ("network_kill", "0", set_by, reason[:500], now),
        )
        conn.execute(
            "INSERT INTO opsec_audit_log (action, old_level, new_level, set_by, reason, ts) VALUES (?,?,?,?,?,?)",
            ("KILL_SWITCH_RELEASED", "", "", set_by, reason[:500], now),
        )
        conn.commit()
        conn.close()
        _write_state_mirror_kill(get_opsec_level(), is_human_locked(), False, set_by, reason)
        return {"ok": True, "network_kill": False, "set_by": set_by, "reason": reason}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _write_state_mirror_kill(level, locked, kill, set_by, reason):
    """Variant of _write_state_mirror with network_kill field."""
    try:
        _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "opsec_level": level.name,
            "level_int": int(level),
            "human_locked": bool(locked),
            "network_kill": bool(kill),
            "last_change_ts": time.time(),
            "last_change_by": set_by,
            "last_reason": reason[:500],
            "schema": "nokido.opsec.state.v2",
        }
        tmp = _STATE_MIRROR.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(_STATE_MIRROR)
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[opsec] miroir d'etat (kill switch) NON ecrit (%s: %s) | consequence: "
            "l'etat du coupe-circuit ne survivra pas a une base vide",
            type(e).__name__, str(e)[:100])


def set_opsec_level(
    level: OpsecLevel | int | str,
    set_by: str = "system",
    reason: str = "",
    lock: Optional[bool] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Switch niveau OPSEC à chaud + audit log + human lock check.

    Args:
        level: target level
        set_by: actor (human|ai|system|cli)
        reason: justification
        lock: si humain pose verrou (set True) ou retire (set False), None=pas changement lock
        force: bypass human_lock check (réservé human/system)
    """
    if isinstance(level, str):
        try:
            level = OpsecLevel[level.upper()]
        except KeyError:
            return {"ok": False, "error": f"unknown level '{level}'. Use CTF|STANDARD|PARANOID"}
    if isinstance(level, int):
        try:
            level = OpsecLevel(level)
        except ValueError:
            return {"ok": False, "error": f"invalid level int {level}"}

    # 🔒 Human Lock check : si IA tente changer alors que verrou actif → REJECT
    actor = (set_by or "").lower()
    is_ai_actor = any(x in actor for x in ["ai", "agent", "trajectory", "claude", "gemini", "llm"])
    if not force and is_ai_actor and is_human_locked():
        old = get_opsec_level()
        # Audit attempt rejected
        try:
            conn = sqlite3.connect(str(DEFAULT_DB))
            _ensure_schema(conn)
            conn.execute(
                "INSERT INTO opsec_audit_log (action, old_level, new_level, set_by, reason, ts) VALUES (?,?,?,?,?,?)",
                ("AI_REJECTED_BY_HUMAN_LOCK", old.name, level.name, set_by, reason[:500], time.time()),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
        return {
            "ok": False,
            "rejected": True,
            "reason_rejection": "Human override active. AI cannot modify OPSEC level. Use UI or set_by=human to unlock.",
            "current_level": old.name,
            "human_locked": True,
        }

    old = get_opsec_level()
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO opsec_state (key, value, set_by, reason, updated_at) VALUES (?,?,?,?,?)",
            ("current_level", str(int(level)), set_by, reason[:500], time.time()),
        )
        if lock is not None:
            conn.execute(
                "INSERT OR REPLACE INTO opsec_state (key, value, set_by, reason, updated_at) VALUES (?,?,?,?,?)",
                ("human_locked", "1" if lock else "0", set_by, reason[:500], time.time()),
            )
        conn.execute(
            "INSERT INTO opsec_audit_log (action, old_level, new_level, set_by, reason, ts) VALUES (?,?,?,?,?,?)",
            (
                "level_change" + ("_LOCKED" if lock else ("_UNLOCKED" if lock is False else "")),
                old.name,
                level.name,
                set_by,
                reason[:500],
                time.time(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": f"persist failed: {e}"}

    global _cached_level, _cached_at
    _cached_level = level
    _cached_at = time.time()

    # Mirror JSON (bind mount Windows VSS-friendly)
    final_locked = is_human_locked() if lock is None else bool(lock)
    _write_state_mirror(level, final_locked, set_by, reason)

    return {
        "ok": True,
        "old_level": old.name,
        "new_level": level.name,
        "set_by": set_by,
        "reason": reason,
        "human_locked": final_locked,
        "warnings": _level_warnings(level),
    }


def set_human_lock(locked: bool, set_by: str = "human", reason: str = "") -> Dict[str, Any]:
    """Pose ou retire verrou humain (sans changer niveau)."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO opsec_state (key, value, set_by, reason, updated_at) VALUES (?,?,?,?,?)",
            ("human_locked", "1" if locked else "0", set_by, reason[:500], time.time()),
        )
        conn.execute(
            "INSERT INTO opsec_audit_log (action, old_level, new_level, set_by, reason, ts) VALUES (?,?,?,?,?,?)",
            ("LOCK_SET" if locked else "LOCK_RELEASED", "", "", set_by, reason[:500], time.time()),
        )
        conn.commit()
        conn.close()
        # Mirror JSON
        _write_state_mirror(get_opsec_level(), locked, set_by, reason)
        return {"ok": True, "human_locked": locked, "set_by": set_by, "reason": reason}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _level_warnings(level: OpsecLevel) -> list:
    if level == OpsecLevel.CTF:
        return [
            "⚠ CTF mode active — TOUS les filtres bypassed",
            "⚠ Flags / hashes / credentials envoyés en clair au LLM",
            "⚠ Usage : labs CTF (HTB, Root-Me, TryHackMe). PAS audit prod.",
        ]
    if level == OpsecLevel.STANDARD:
        return [
            "ℹ Standard mode : passwords/tokens masqués, IPs/paths lisibles",
            "ℹ Approprié pentest contrôlé avec consentement client",
        ]
    if level == OpsecLevel.PARANOID:
        return ["✓ Paranoid mode (default) : protection maximale activée"]
    return []


# ============================================================
# Sanitize per-level
# ============================================================
# Patterns secrets vitaux (toujours masqués sauf CTF)
_SECRET_PATTERNS = [
    r"(?i)(api[_\s]?key|apikey)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{16,})",
    r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?([^\s'\"]{6,})",
    r"(?i)(secret|token)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-]{12,})",
    r"(?i)(authorization)\s*[:=]\s*['\"]?(bearer\s+[a-zA-Z0-9_\-\.]{20,})",
    r"(?i)\b(sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{20,}|xoxb-[a-zA-Z0-9\-]{20,})",
    r"(?i)(?:flag|FLAG)\s*[{=:]\s*['\"]?([^\s'\"\}]{4,})",
]

_IP_PATTERN = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
_PATH_PATTERN = re.compile(r"(?:[A-Z]:[\\/]|/)[\w\\/.\-]{4,}")
_HASH_PATTERN = re.compile(r"\b[a-fA-F0-9]{32,}\b")  # MD5/SHA*


def sanitize_for_archive(
    raw_text: str, agent: str = "system", explicit_level: Optional[OpsecLevel] = None
) -> Dict[str, Any]:
    """Masque selon niveau OPSEC courant.

    Returns:
        {sanitized, level, redactions: [count_per_type], original_size}
    """
    level = explicit_level if explicit_level is not None else get_opsec_level()
    if not raw_text:
        return {"sanitized": "", "level": level.name, "redactions": {}, "original_size": 0}

    # 🟢 CTF : bypass total
    if level == OpsecLevel.CTF:
        return {
            "sanitized": raw_text,
            "level": "CTF",
            "redactions": {"_bypass": True},
            "original_size": len(raw_text),
        }

    sanitized = raw_text
    redactions = {"secrets": 0, "ips": 0, "paths": 0, "hashes": 0}

    # 🟡 STANDARD + 🔴 PARANOID : masque secrets vitaux
    for pattern in _SECRET_PATTERNS:
        compiled = re.compile(pattern)

        def repl(m):
            redactions["secrets"] += 1
            groups = m.groups()
            label = groups[0] if groups else "SECRET"
            return f"{label}=[VAULT_SECRET_{redactions['secrets']:03d}]"

        sanitized = compiled.sub(repl, sanitized)

    # 🔴 PARANOID seulement : masque topologie réseau
    if level == OpsecLevel.PARANOID:
        # IPs
        def ip_repl(m):
            redactions["ips"] += 1
            return f"[IP_{redactions['ips']:03d}]"

        sanitized = _IP_PATTERN.sub(ip_repl, sanitized)

        # Hashes
        def hash_repl(m):
            redactions["hashes"] += 1
            return f"[HASH_{redactions['hashes']:03d}]"

        sanitized = _HASH_PATTERN.sub(hash_repl, sanitized)

        # NoiseGuardian (MACs, CVEs, signatures)
        try:
            from nokido_agent.app.forge_silo_fragmenter import NoiseGuardian

            ng = NoiseGuardian()
            sanitized, _ = ng.neutralize_signatures(sanitized)
        except Exception:
            pass

    return {
        "sanitized": sanitized,
        "level": level.name,
        "redactions": redactions,
        "original_size": len(raw_text),
        "delta": len(raw_text) - len(sanitized),
    }


def is_bypass() -> bool:
    """True si OPSEC = CTF (bypass total)."""
    return get_opsec_level() == OpsecLevel.CTF


# ============================================================
# Audit + history
# ============================================================
def audit_log(limit: int = 20) -> list:
    """Historique des changements de niveau."""
    try:
        conn = sqlite3.connect(str(DEFAULT_DB))
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT action, old_level, new_level, set_by, reason, ts FROM opsec_audit_log ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [{"action": r[0], "old": r[1], "new": r[2], "by": r[3], "reason": r[4], "ts": r[5]} for r in rows]
    except Exception:
        return []


def status() -> Dict[str, Any]:
    """État courant + warnings + human lock + network_kill."""
    level = get_opsec_level()
    return {
        "current_level": level.name,
        "level_int": int(level),
        "human_locked": is_human_locked(),
        "network_kill": is_network_kill(),
        "warnings": _level_warnings(level),
        "default_level": _DEFAULT_LEVEL.name,
        "audit_log_recent": audit_log(5),
    }


# ============================================================
# Detect lab signals (bannieres CTF) → AI can request CTF
# ============================================================
_LAB_SIGNATURES = [
    r"hack\s*the\s*box",
    r"\bhtb\b",
    r"root[\-\s]?me",
    r"try\s*hack\s*me",
    r"\btryhackme\b",
    r"vulnhub",
    r"hacker[\-\s]?one",
    r"capture\s+the\s+flag",
    r"\bctf\b",
    r"flag\{[^\}]+\}",
    r"htb\{[^\}]+\}",
    r"thm\{[^\}]+\}",
    r"\bpwnable\b",
    r"\boverthewire\b",
    r"\bpicoctf\b",
    r"vulnerable.{0,20}intentionally",
    r"training\s+(?:lab|environment|machine)",
]
_LAB_RE = re.compile("|".join(_LAB_SIGNATURES), re.IGNORECASE)


def detect_lab_environment(text: str) -> Dict[str, Any]:
    """Scan text pour signatures CTF/lab. Retourne confidence 0-1."""
    if not text:
        return {"is_lab": False, "confidence": 0.0, "matches": []}
    matches = _LAB_RE.findall(text)
    confidence = min(1.0, len(matches) * 0.25)
    return {
        "is_lab": confidence >= 0.5,
        "confidence": confidence,
        "matches": list(set(matches))[:8],
        "recommendation": (
            "Suggérer CTF mode si is_lab=True et opérateur consent. "
            "AI doit appeler set_opsec_level si human_locked=False."
        ),
    }


# ============================================================
# Boot : restore from JSON mirror si SQLite vide (conteneur ré-instancié)
# ============================================================
try:
    _restore_from_mirror_if_db_empty()
except Exception:
    pass


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys, argparse

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--set", choices=["CTF", "STANDARD", "PARANOID"])
    ap.add_argument("--reason", default="cli")
    ap.add_argument("--sanitize", help="text to sanitize")
    ap.add_argument("--audit", action="store_true")
    args = ap.parse_args()
    if args.status:
        print(json.dumps(status(), indent=2))
    elif args.set:
        print(json.dumps(set_opsec_level(args.set, set_by="cli", reason=args.reason), indent=2))
    elif args.sanitize:
        print(json.dumps(sanitize_for_archive(args.sanitize), indent=2))
    elif args.audit:
        print(json.dumps(audit_log(20), indent=2))
    else:
        ap.print_help()
