"""
forge_rbac_mapping.py — Jonction agent↔OS pour Nokido RBAC
============================================================

Surface la couche manquante de la [[roadmap-multi-cli-sandbox-rbac]] :
chaque entity (`forge_entities.entity_id`) est associée à un compte
OS d'exécution + groupe + zone fs. Le mapping est édité via la web UI
:7400 /rbac et appliqué runtime quand le hub spawne un process pour
le compte d'un agent.

Stockage : champ JSON `os_account` ajouté à `forge_entities` (migration
idempotente au boot). PAS de table séparée — la jonction est dans la
table déjà existante. Schéma :

    os_account = {
        "os_user":  "LaForgeSbxOffline" | "LaForgeSbxOnline" | "LaForgeTrusted" | None,
        "os_group": "LaForgeSandboxUsers" | "LaForgeTrustedRunners" | None,
        "zone":     "sandbox-offline" | "sandbox-online" | "trusted" | "system",
        "set_by":   "human_ui" | "system" | ...,
        "set_at":   ISO timestamp,
    }

Pas de dup avec [[forge-rbac]] (capabilities) ni [[forge-integrity]]
(tokens HMAC) — cette couche est l'EFFECTEUR OS qui matérialise le ring
en compte Windows réel.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

# Zones OS reconnues — politique RBAC dérivée du ring
ZONE_BY_RING = {
    -1: "system",  # MASTER — pas de compte distinct (TUI humaine)
    0: "system",  # SYSTEM — services NSSM (hub, supervisor)
    1: "trusted",  # DEV — LaForgeTrusted (Claude/Codex/Cursor)
    2: "trusted",  # TRUSTED — workflows TUI
    3: "sandbox-online",  # COLLAB — Gemini/cloud LLM (besoin internet)
    4: "sandbox-offline",  # UNTRUSTED — agents sans token (loopback only)
}

# OS user par zone — source de vérité (synchro avec forge_sandbox_setup.py)
USER_BY_ZONE = {
    "system": None,  # SYSTEM = service account, pas spawn
    "trusted": "LaForgeTrusted",
    "sandbox-online": "LaForgeSbxOnline",
    "sandbox-offline": "LaForgeSbxOffline",
}

GROUP_BY_ZONE = {
    "system": None,
    "trusted": "LaForgeTrustedRunners",
    "sandbox-online": "LaForgeSandboxUsers",
    "sandbox-offline": "LaForgeSandboxUsers",
}


# ── Schema migration ────────────────────────────────────────────────────────

_MIGRATED = False


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Garantit le schema dont ce module depend. Idempotent.

    LE DRAPEAU GLOBAL A ETE RETIRE (2026-09-18). `_MIGRATED` etait un booleen de
    module : une fois la base de PRODUCTION preparee, toute autre connexion
    ressortait aussitot, schema non verifie. Un test sur une base temporaire
    heritait donc du travail fait sur une base qui n'est pas la sienne, et
    echouait sur `no such table` -- mesure du jour. Un cache d'etat partage entre
    plusieurs bases ment sur toutes sauf une. Le cout evite etait un PRAGMA et
    deux CREATE IF NOT EXISTS par connexion : negligeable devant la confusion.

    `forge_entities` est desormais CREEE si elle manque. Le module en depend pour
    lire comme pour ecrire ; en production elle existe deja et le CREATE ne fait
    rien, mais un module qui ne garantit pas la table qu'il interroge n'est
    utilisable que la ou quelqu'un d'autre l'a preparee.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forge_entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            display_name TEXT NOT NULL,
            ring_level INTEGER NOT NULL DEFAULT 5,
            capabilities TEXT NOT NULL DEFAULT '[]',
            token_hash TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen TEXT DEFAULT NULL,
            meta TEXT NOT NULL DEFAULT '{}',
            os_account TEXT DEFAULT NULL
        )
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(forge_entities)").fetchall()}
    if "os_account" not in cols:
        conn.execute("ALTER TABLE forge_entities ADD COLUMN os_account TEXT DEFAULT NULL")
        logger.info("rbac_mapping: colonne os_account ajoutée à forge_entities")
    # Audit table dédiée pour traces modifs mapping
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rbac_mapping_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            entity_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            reason TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rbac_audit_ts ON rbac_mapping_audit(ts)")
    conn.commit()


# ── Dataclass ───────────────────────────────────────────────────────────────


@dataclass
class OSAccount:
    os_user: Optional[str] = None
    os_group: Optional[str] = None
    zone: str = "sandbox-offline"
    set_by: str = "system"
    set_at: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: Optional[str]) -> "OSAccount":
        if not raw:
            return cls()
        try:
            d = json.loads(raw)
            return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})
        except Exception:
            return cls()

    @classmethod
    def derive(cls, ring_level: int, set_by: str = "system") -> "OSAccount":
        """Mapping par défaut depuis le ring."""
        zone = ZONE_BY_RING.get(ring_level, "sandbox-offline")
        return cls(
            os_user=USER_BY_ZONE.get(zone),
            os_group=GROUP_BY_ZONE.get(zone),
            zone=zone,
            set_by=set_by,
            set_at=_dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )


# ── API publique ────────────────────────────────────────────────────────────


def _conn(db_path: Optional[Path] = None) -> sqlite3.Connection:
    p = db_path if db_path is not None else DB
    c = sqlite3.connect(str(p), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(c)
    return c


def get_mapping(entity_id: str, db_path: Optional[Path] = None) -> dict:
    """Retourne {entity_id, ring_level, os_account: {...}}."""
    c = _conn(db_path)
    try:
        row = c.execute(
            "SELECT entity_id, entity_type, ring_level, is_active, os_account FROM forge_entities WHERE entity_id=?",
            (entity_id,),
        ).fetchone()
    finally:
        c.close()
    if not row:
        return {}
    acc = OSAccount.from_json(row[4])
    if acc.zone == "sandbox-offline" and not acc.os_user:
        # Mapping non initialisé → dériver depuis ring (lecture seule).
        acc = OSAccount.derive(row[2])
    return {
        "entity_id": row[0],
        "entity_type": row[1],
        "ring_level": row[2],
        "is_active": bool(row[3]),
        "os_account": asdict(acc),
    }


def list_mappings(db_path: Optional[Path] = None) -> list[dict]:
    c = _conn(db_path)
    try:
        rows = c.execute(
            "SELECT entity_id, entity_type, ring_level, is_active, os_account "
            "FROM forge_entities ORDER BY ring_level, entity_id"
        ).fetchall()
    finally:
        c.close()
    out = []
    for r in rows:
        acc = OSAccount.from_json(r[4])
        if not acc.os_user and not acc.zone == "system":
            acc = OSAccount.derive(r[2])
        out.append(
            {
                "entity_id": r[0],
                "entity_type": r[1],
                "ring_level": r[2],
                "is_active": bool(r[3]),
                "os_account": asdict(acc),
            }
        )
    return out


def set_mapping(
    entity_id: str,
    *,
    zone: Optional[str] = None,
    os_user: Optional[str] = None,
    os_group: Optional[str] = None,
    actor: str = "system",
    reason: str = "",
    db_path: Optional[Path] = None,
) -> dict:
    """Update mapping. Valide cohérence zone/user/group. Audit row écrit."""
    if zone and zone not in ZONE_BY_RING.values():
        raise ValueError(f"zone inconnue: {zone}")
    c = _conn(db_path)
    try:
        row = c.execute("SELECT ring_level, os_account FROM forge_entities WHERE entity_id=?", (entity_id,)).fetchone()
        if not row:
            raise ValueError(f"entity inconnue: {entity_id}")
        ring, old_raw = row
        old_acc = OSAccount.from_json(old_raw)
        if not old_acc.os_user and old_acc.zone == "sandbox-offline":
            old_acc = OSAccount.derive(ring)

        # Si zone changée mais user/group non fourni → dériver depuis zone
        if zone and not os_user:
            os_user = USER_BY_ZONE.get(zone)
        if zone and not os_group:
            os_group = GROUP_BY_ZONE.get(zone)

        new_acc = OSAccount(
            os_user=os_user if os_user is not None else old_acc.os_user,
            os_group=os_group if os_group is not None else old_acc.os_group,
            zone=zone if zone is not None else old_acc.zone,
            set_by=actor,
            set_at=_dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        )

        # Validation cohérence : zone détermine user+group
        expected_user = USER_BY_ZONE.get(new_acc.zone)
        if expected_user is not None and new_acc.os_user != expected_user:
            raise ValueError(f"zone={new_acc.zone} exige os_user={expected_user}, reçu={new_acc.os_user}")
        expected_group = GROUP_BY_ZONE.get(new_acc.zone)
        if expected_group is not None and new_acc.os_group != expected_group:
            raise ValueError(f"zone={new_acc.zone} exige os_group={expected_group}, reçu={new_acc.os_group}")

        # Validation cohérence ring/zone — refus zone trusted pour ring>2
        warn_ring = (new_acc.zone == "trusted" and ring > 2) or (new_acc.zone == "system" and ring > 0)
        if warn_ring:
            logger.warning(f"rbac_mapping: zone={new_acc.zone} incohérente avec ring={ring} pour {entity_id}")

        c.execute("UPDATE forge_entities SET os_account=? WHERE entity_id=?", (new_acc.to_json(), entity_id))
        c.execute(
            "INSERT INTO rbac_mapping_audit(ts,entity_id,actor,old_value,new_value,reason) VALUES(?,?,?,?,?,?)",
            (_dt.datetime.utcnow().timestamp(), entity_id, actor, old_acc.to_json(), new_acc.to_json(), reason[:300]),
        )
        c.commit()
    finally:
        c.close()
    return {"entity_id": entity_id, "os_account": asdict(new_acc), "actor": actor, "reason": reason}


def _identifiant_lisible(entity_id: str) -> str:
    """Valide l'identifiant, ou dit pourquoi il est refuse.

    Il sert de cle primaire ET se retrouve dans chaque ligne d'audit : un
    identifiant qui ne se relit pas rend le journal inutilisable. On reste
    volontairement etroit -- minuscules, chiffres, tiret bas -- parce qu'un
    espace ou une barre oblique dans une cle qu'on recopie dans des URL et des
    journaux se paie plus tard, et toujours au mauvais moment.
    """
    eid = (entity_id or "").strip()
    if not 3 <= len(eid) <= 64:
        raise ValueError(
            "entity_id doit faire entre 3 et 64 caracteres (recu %d)" % len(eid))
    if not (eid[0].isascii() and eid[0].isalpha() and eid[0].islower()):
        raise ValueError("entity_id doit commencer par une lettre minuscule : %r" % eid)
    permis = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    intrus = sorted(set(eid) - permis)
    if intrus:
        raise ValueError(
            "entity_id n'accepte que minuscules, chiffres et tiret bas ; "
            "caracteres refuses : %s" % " ".join(repr(c) for c in intrus))
    return eid


def create_mapping(
    entity_id: str,
    *,
    entity_type: str = "agent",
    ring_level: int = 4,
    zone: Optional[str] = None,
    display_name: Optional[str] = None,
    actor: str = "system",
    reason: str = "",
    db_path: Optional[Path] = None,
) -> dict:
    """Cree une entite RBAC et son compte OS derive. Audit ecrit.

    DEMANDE OWNER (2026-09-18) : pouvoir ajouter un entity_id depuis l'interface
    et lui attribuer ses reglages. Il n'existait aucun chemin de creation --
    `set_mapping` refuse une entite inconnue, et la page ne savait que modifier
    ce qui existait deja.

    TROIS REFUS, et chacun evite un defaut precis :
      * identifiant illisible -> l'audit deviendrait inexploitable ;
      * entite deja connue -> re-soumettre le formulaire ecraserait en silence
        les reglages d'une entite existante, c'est-a-dire une elevation de
        privilege deguisee en faute de frappe ;
      * zone qui ne decoule pas du ring -> `USER_BY_ZONE` attache un compte a
        chaque zone ; creer une entite `trusted` avec le compte d'un bac a sable
        donnerait une autorite que rien ne porte. La zone se RESSERRE ensuite par
        `set_mapping` si besoin, elle ne s'invente pas a la naissance.
    """
    eid = _identifiant_lisible(entity_id)
    if ring_level not in ZONE_BY_RING:
        raise ValueError("ring_level inconnu : %r (attendus %s)"
                         % (ring_level, sorted(ZONE_BY_RING)))
    attendue = ZONE_BY_RING[ring_level]
    if zone is not None and zone != attendue:
        raise ValueError(
            "zone=%r incoherente avec ring=%d, qui donne %r. La zone porte un "
            "compte OS : une autorite sans son compte n'est pas une autorite."
            % (zone, ring_level, attendue))
    c = _conn(db_path)
    try:
        deja = c.execute("SELECT 1 FROM forge_entities WHERE entity_id=?", (eid,)).fetchone()
        if deja:
            raise ValueError("entity_id existe deja : %s" % eid)
        acc = OSAccount.derive(ring_level)
        acc.set_by = actor
        acc.set_at = _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
        c.execute(
            "INSERT INTO forge_entities(entity_id, entity_type, display_name, "
            "ring_level, os_account) VALUES(?,?,?,?,?)",
            (eid, entity_type, display_name or eid, int(ring_level), acc.to_json()),
        )
        c.execute(
            "INSERT INTO rbac_mapping_audit(ts,entity_id,actor,old_value,new_value,reason) "
            "VALUES(?,?,?,?,?,?)",
            (_dt.datetime.utcnow().timestamp(), eid, actor, None, acc.to_json(),
             (reason or "creation")[:300]),
        )
        c.commit()
    finally:
        c.close()
    return {"entity_id": eid, "entity_type": entity_type, "ring_level": int(ring_level),
            "os_account": asdict(acc), "actor": actor, "reason": reason}


def derive_for_ring(ring_level: int) -> OSAccount:
    """Helper public — calcule mapping par défaut depuis un ring."""
    return OSAccount.derive(ring_level)


def audit_log(limit: int = 50, db_path: Optional[Path] = None) -> list[dict]:
    c = _conn(db_path)
    try:
        rows = c.execute(
            "SELECT ts, entity_id, actor, old_value, new_value, reason "
            "FROM rbac_mapping_audit ORDER BY ts DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    finally:
        c.close()
    return [
        {
            "ts": r[0],
            "entity_id": r[1],
            "actor": r[2],
            "old": json.loads(r[3] or "{}"),
            "new": json.loads(r[4] or "{}"),
            "reason": r[5] or "",
        }
        for r in rows
    ]


# ── CLI minimal pour ops manuel ─────────────────────────────────────────────


def _cli():
    import argparse, sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Nokido RBAC mapping CLI")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--get", help="entity_id")
    ap.add_argument("--set", help="entity_id à modifier")
    ap.add_argument("--zone", choices=list(set(ZONE_BY_RING.values())))
    ap.add_argument("--actor", default="cli")
    ap.add_argument("--reason", default="")
    ap.add_argument("--audit", type=int, help="afficher N dernières entrées audit")
    args = ap.parse_args()

    if args.list:
        for m in list_mappings():
            acc = m["os_account"]
            print(f"  [{m['ring_level']}] {m['entity_id']:25} zone={acc['zone']:18} user={acc.get('os_user') or '-'}")
        return 0
    if args.get:
        print(json.dumps(get_mapping(args.get), indent=2, ensure_ascii=False))
        return 0
    if args.set and args.zone:
        r = set_mapping(args.set, zone=args.zone, actor=args.actor, reason=args.reason)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0
    if args.audit:
        for e in audit_log(args.audit):
            print(
                f"  {_dt.datetime.fromtimestamp(e['ts']).isoformat(timespec='seconds')} "
                f"{e['actor']:12} {e['entity_id']:25} "
                f"{e['old'].get('zone', '?')} -> {e['new'].get('zone', '?')}"
            )
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
