# -*- coding: utf-8 -*-
"""
forge_access_switches.py — Switches virtuels intelligents (RBAC→ReBAC dynamique)

PRINCIPE AUTOPOÏÉTIQUE :
  Les droits ne sont pas gravés dans le code (gène fixe) mais dans une DB
  évolutive (épigénétique). L\'admin peut les modifier sans redémarrer l\'organisme.
  Le SafeEval DSL est la membrane : expressif mais imperméable à l\'injection.

ARCHITECTURE (synthèse Mistral+GPT-4o+Groq 2026-04-28) :
  - ReBAC : "GEMINI peut écrire sandbox/ si fichier créé par lui-même"
  - Snapshot atomique (BEGIN IMMEDIATE) contre TOCTOU
  - Cache LRU en mémoire (invalidé par version_counter DB)
  - Escalade temporisée : expires_at + watchdog thread
  - DSL sandboxé : ast.NodeVisitor whitelist (pas d\'eval libre)

TABLE access_switches :
  id, agent_pattern, resource_pattern, action,
  allowed, condition_dsl, expires_at,
  granted_by, grant_reason, created_at, updated_at, version
"""

from __future__ import annotations
import ast, fnmatch, logging, os, sqlite3, threading, time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Nokido.AccessSwitches")

# DEPENDANCE CRITIQUE MESUREE (2026-09-05) — trois chutes du hub en une heure.
#
# Cette table decide de TOUTE l'autorisation : elle est lue a CHAQUE appel de tool,
# et le gate est FAIL-CLOSED. Elle vivait dans `embeddings.db`, la base de 24,9 Go
# que le RAG, l'ingestion, le backfill, l'embed daemon et pytest ecrivent tous.
# Chaine OBSERVEE, pas deduite :
#
#     verrou sur embeddings.db
#       -> GATE_DENIED sur TOUS les tools   (hub vivant, totalement inutilisable)
#       -> Unable to connect                 (hub mort, tue par son healthcheck)
#
# Disproportion : 19 regles, dans le plus gros fichier concurrent du systeme. Le
# `journal_mode=wal` n'y peut rien -- WAL protege des ecritures concurrentes, pas
# d'une transaction laissee ouverte, et `busy_timeout` attend un verrou LIBERABLE.
#
# `LAFORGE_SWITCHES_DB_PATH` permet de sortir la table vers une base DEDIEE de
# quelques kilo-octets (`tools/forge_switches_db_split.py` : copie + verification
# regle a regle). Tant que la variable n'est PAS posee, le comportement est
# strictement inchange : basculer un gate est un geste OWNER, parce qu'un gate mal
# migre ouvre ou ferme TOUT.
#
# ⚠️ AVANT DE POSER LA VARIABLE : verifier que la base cible contient bien les
# regles (`--verifier`). Le gate etant fail-closed, une base vide ne « degrade »
# pas -- elle REFUSE tout, et le hub devient inutilisable exactement comme sous
# verrou. La verification n'est pas une precaution de style.
DEFAULT_DB_PATH = os.environ.get("LAFORGE_SWITCHES_DB_PATH") or os.environ.get(
    "LAFORGE_DB_PATH", str(Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db")
)

# ── Schema SQL ───────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS access_switches (
    id              TEXT PRIMARY KEY,
    agent_pattern   TEXT NOT NULL,       -- fnmatch : 'GEMINI' | 'GEM*' | '*'
    resource_pattern TEXT NOT NULL,      -- fnmatch : 'sandbox/*' | 'app/*.py'
    action          TEXT NOT NULL,       -- write | read | run | query | *
    allowed         INTEGER NOT NULL DEFAULT 1,  -- 1=allow 0=deny
    condition_dsl   TEXT DEFAULT NULL,   -- DSL sandboxé ou NULL (pas de condition)
    expires_at      TEXT DEFAULT NULL,   -- ISO8601 UTC ou NULL (permanent)
    granted_by      TEXT NOT NULL,       -- agent ring 0 qui a accordé
    grant_reason    TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    version         INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_switches_agent ON access_switches(agent_pattern);
CREATE INDEX IF NOT EXISTS idx_switches_expires ON access_switches(expires_at)
    WHERE expires_at IS NOT NULL;
"""

# ── DSL SafeEval ─────────────────────────────────────────────────────────────
# Sous-ensemble strictement limité : comparateurs + logique + fonctions whitelist
# Jamais d\'eval() libre — uniquement ast.NodeVisitor sur un AST validé


@dataclass
class EvalContext:
    """Contexte injecté dans le DSL pour une évaluation."""

    agent: str
    resource: str
    action: str
    ring: int
    ts: float = field(default_factory=time.time)
    extra: dict = field(default_factory=dict)


class SafeEval(ast.NodeVisitor):
    """
    Interpréteur DSL minimal et sécurisé.
    Opérateurs autorisés : ==, !=, <, >, <=, >=, in, not in, and, or, not
    Fonctions autorisées : time_hour(), is_local(), ring_lte()
    Variables autorisées : agent, resource, action, ring, ts
    Tout le reste lève ValueError.
    """

    _SAFE_FUNCS = {
        "time_hour": lambda ctx: datetime.fromtimestamp(ctx.ts, tz=timezone.utc).hour,
        "is_local": lambda ctx: True,  # toujours local (127.0.0.1)
        "ring_lte": lambda ctx, n: ctx.ring <= int(n),
    }

    def __init__(self, ctx: EvalContext):
        self._ctx = ctx
        self._vars = {
            "agent": ctx.agent,
            "resource": ctx.resource,
            "action": ctx.action,
            "ring": ctx.ring,
            "ts": ctx.ts,
        }

    def evaluate(self, expr: str) -> bool:
        if not expr or not expr.strip():
            return True
        try:
            tree = ast.parse(expr.strip(), mode="eval")
        except SyntaxError as e:
            raise ValueError(f"DSL syntax error: {e}") from e
        return bool(self.visit(tree.body))

    def visit_BoolOp(self, node):
        if isinstance(node.op, ast.And):
            return all(self.visit(v) for v in node.values)
        if isinstance(node.op, ast.Or):
            return any(self.visit(v) for v in node.values)
        raise ValueError(f"BoolOp non supporté: {type(node.op)}")

    def visit_UnaryOp(self, node):
        if isinstance(node.op, ast.Not):
            return not self.visit(node.operand)
        raise ValueError(f"UnaryOp non supporté: {type(node.op)}")

    def visit_Compare(self, node):
        left = self.visit(node.left)
        for op, comp in zip(node.ops, node.comparators):
            right = self.visit(comp)
            if isinstance(op, ast.Eq):
                left = left == right
            elif isinstance(op, ast.NotEq):
                left = left != right
            elif isinstance(op, ast.Lt):
                left = left < right
            elif isinstance(op, ast.LtE):
                left = left <= right
            elif isinstance(op, ast.Gt):
                left = left > right
            elif isinstance(op, ast.GtE):
                left = left >= right
            elif isinstance(op, ast.In):
                left = left in right
            elif isinstance(op, ast.NotIn):
                left = left not in right
            else:
                raise ValueError(f"Opérateur non supporté: {type(op)}")
        return left

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Seuls les appels de fonction simples sont autorisés")
        fname = node.func.id
        if fname not in self._SAFE_FUNCS:
            raise ValueError(f"Fonction non autorisée: {fname!r}")
        fn = self._SAFE_FUNCS[fname]
        args = [self.visit(a) for a in node.args]
        return fn(self._ctx, *args)

    def visit_Name(self, node):
        if node.id not in self._vars:
            raise ValueError(f"Variable non autorisée: {node.id!r}")
        return self._vars[node.id]

    def visit_Constant(self, node):
        if not isinstance(node.value, (str, int, float, bool)):
            raise ValueError(f"Type de constante non autorisé: {type(node.value)}")
        return node.value

    def visit_List(self, node):
        return [self.visit(e) for e in node.elts]

    def generic_visit(self, node):
        raise ValueError(f"Noeud AST non autorisé: {type(node).__name__}")


# ── Cache LRU snapshot ───────────────────────────────────────────────────────

_cache_lock = threading.Lock()
_rules_cache: list = []
_cache_version: int = -1


def _get_db_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM access_switches").fetchone()
        return row[0] or 0
    except Exception:
        return 0


def _load_rules_snapshot(db_path: str) -> list:
    """Snapshot atomique BEGIN IMMEDIATE — anti-TOCTOU."""
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        now_utc = datetime.now(tz=timezone.utc).isoformat()
        rows = conn.execute(
            "SELECT * FROM access_switches WHERE (expires_at IS NULL OR expires_at > ?) ORDER BY version DESC",
            (now_utc,),
        ).fetchall()
        db_ver = _get_db_version(conn)
        conn.commit()
        return [dict(r) for r in rows], db_ver
    finally:
        conn.close()


def _get_rules(db_path: str) -> list:
    """Retourne les règles depuis le cache LRU ou recharge si version changée."""
    global _rules_cache, _cache_version
    conn = sqlite3.connect(db_path, timeout=3)
    try:
        cur_ver = _get_db_version(conn)
    finally:
        conn.close()
    with _cache_lock:
        if cur_ver != _cache_version:
            _rules_cache, _cache_version = _load_rules_snapshot(db_path)
            logger.debug(f"[Switches] cache rechargé v={_cache_version} n={len(_rules_cache)}")
        return list(_rules_cache)


# ── Évaluateur principal ─────────────────────────────────────────────────────


def check_access(
    agent: str,
    resource: str,
    action: str,
    ring: int,
    db_path: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Vérifie si agent peut effectuer action sur resource.
    Retourne (allowed: bool, reason: str).

    Ordre d\'évaluation (deny-override) :
    1. Règles DENY explicites (priorité absolue)
    2. Règles ALLOW (première match)
    3. Défaut : deny si aucune règle ne match
    """
    db = db_path or DEFAULT_DB_PATH
    rules = _get_rules(db)

    ctx = EvalContext(agent=agent, resource=resource, action=action, ring=ring)

    deny_rules = [r for r in rules if not r["allowed"]]
    allow_rules = [r for r in rules if r["allowed"]]

    # 1. Vérifier les DENY
    for rule in deny_rules:
        if _rule_matches(rule, agent, resource, action, ctx):
            return False, f"deny_switch:{rule['id']}"

    # 2. Vérifier les ALLOW
    for rule in allow_rules:
        if _rule_matches(rule, agent, resource, action, ctx):
            return True, f"allow_switch:{rule['id']}"

    # 3. Défaut : pas de règle = pas d\'accès explicite → déléguer au ring système
    return None, "no_switch_match"


def _rule_matches(rule: dict, agent: str, resource: str, action: str, ctx: EvalContext) -> bool:
    """Vérifie si une règle s\'applique à cette combinaison agent/resource/action."""
    if not fnmatch.fnmatch(agent.upper(), rule["agent_pattern"].upper()):
        return False
    if not fnmatch.fnmatch(resource, rule["resource_pattern"]):
        return False
    if rule["action"] != "*" and rule["action"] != action:
        return False
    # Évaluer condition DSL si présente
    dsl = rule.get("condition_dsl")
    if dsl:
        try:
            evaluator = SafeEval(ctx)
            if not evaluator.evaluate(dsl):
                return False
        except ValueError as e:
            logger.error(f"[Switches] DSL error rule={rule['id']}: {e}")
            return False  # DSL invalide = règle ignorée (fail-safe)
    return True


# ── Admin API ────────────────────────────────────────────────────────────────


def create_switch(
    agent_pattern: str,
    resource_pattern: str,
    action: str,
    allowed: bool,
    granted_by: str,
    condition_dsl: str = None,
    expires_in_seconds: int = None,
    grant_reason: str = "",
    db_path: str = None,
) -> dict:
    """Crée un nouveau switch. Réservé ring 0 (vérifié par le caller)."""
    import secrets

    db = db_path or DEFAULT_DB_PATH
    switch_id = "sw_" + secrets.token_hex(6)
    expires_at = None
    if expires_in_seconds:
        from datetime import timedelta

        expires_at = (datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in_seconds)).isoformat()

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.execute(
            "INSERT INTO access_switches(id,agent_pattern,resource_pattern,action,"
            "allowed,condition_dsl,expires_at,granted_by,grant_reason) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                switch_id,
                agent_pattern,
                resource_pattern,
                action,
                1 if allowed else 0,
                condition_dsl,
                expires_at,
                granted_by,
                grant_reason,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Invalider le cache
    global _cache_version
    with _cache_lock:
        _cache_version = -1

    print(
        f"[ACCESS_SWITCH] créé {switch_id} "
        f"{agent_pattern}->{resource_pattern} {action} "
        f"{'ALLOW' if allowed else 'DENY'}" + (f" expires={expires_at}" if expires_at else ""),
        flush=True,
    )
    return {"id": switch_id, "allowed": allowed, "expires_at": expires_at}


def init_db(db_path: str = None) -> None:
    """Initialise la table access_switches."""
    db = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(db)
    conn.executescript(DDL)
    conn.commit()
    conn.close()
    logger.info("[AccessSwitches] DB initialisée")


def list_switches(db_path: str = None) -> list:
    """Liste tous les switches actifs."""
    db = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    now = datetime.now(tz=timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT * FROM access_switches WHERE expires_at IS NULL OR expires_at > ? ORDER BY created_at DESC", (now,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
