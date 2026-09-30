"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_mesh_memory
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_mesh_memory.py — Mémoire de Maillage Ring 6
======================================================
LanceDB local — versioned, nomad, P2P-ready.

Variables .env lues :
  SSH_HOST=localhost   → cible rsync P2P
  SSH_USER=freebox
  PRIVATE_KEY_PATH=...     → clé SSH pour sync
  LAFORGE_ENV=dev          → pas de sync auto en dev

Tables :
  swarm_thoughts  → tokens / réponses agents (ring 3-5)
  adr_validated   → synthèses validées → futurs ADR ring 2
  rollback_log    → historique context_rollback (Inspecteur R4)

ADR-010 : LanceDB Ring 6 — Mémoire versionnée + P2P sync.
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
MESH_DIR = ROOT / "sandbox" / "mesh_lancedb"
MESH_DIR.mkdir(parents=True, exist_ok=True)


def _acces_ssh(cle: str, defaut: str = "") -> str:
    """Acces SSH lus au COFFRE d'abord (forge_secrets : coffre, WCM, Nokido.env, environnement).

    Owner 2026-09-25 : plus d'acces en dur. Un os.environ brut n'avait aucun repli une fois la ligne
    de Nokido.env migree au coffre (forge_env_to_vault.JAMAIS_NEUTRALISER le signalait)."""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret(cle) or defaut
    except Exception as e:  # noqa: BLE001 - coffre illisible : DIT, puis repli environnement
        print(f"[mesh] coffre illisible pour {cle} ({type(e).__name__}) — repli environnement")
        return os.environ.get(cle) or defaut


def _is_dev() -> bool:
    """Is dev."""
    return (
        os.environ.get("LAFORGE_ENV", "prod").lower() == "dev"
        or os.environ.get("LAFORGE_MCP_DEV", "false").lower() == "true"
    )


# ── Import LanceDB avec fallback gracieux ─────────────────────────────────────


def _get_lancedb() -> object:
    """Import lancedb — None si non installé."""
    try:
        import lancedb

        return lancedb
    except ImportError:
        return None


def _get_pa() -> object:
    """Get pa."""
    try:
        import pyarrow as pa

        return pa
    except ImportError:
        return None


# ── Schémas PyArrow ───────────────────────────────────────────────────────────


def _schema_thoughts() -> object:
    """Schema thoughts."""
    pa = _get_pa()
    if not pa:
        return None
    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("agent", pa.string()),
            pa.field("session", pa.string()),
            pa.field("ring", pa.int32()),
            pa.field("content", pa.string()),
            pa.field("summary", pa.string()),
            pa.field("drift", pa.float32()),
            pa.field("vector", pa.list_(pa.float32(), 256)),
            pa.field("ts", pa.float64()),
            pa.field("version", pa.int64()),
        ]
    )


def _schema_adr() -> object:
    """Schema adr."""
    pa = _get_pa()
    if not pa:
        return None
    return pa.schema(
        [
            pa.field("adr_id", pa.string()),
            pa.field("title", pa.string()),
            pa.field("synthesis", pa.string()),
            pa.field("ring", pa.int32()),
            pa.field("status", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), 256)),
            pa.field("ts", pa.float64()),
            pa.field("version", pa.int64()),
        ]
    )


# ── MeshMemory ────────────────────────────────────────────────────────────────


class MeshMemory:
    """
    Mémoire de maillage Ring 6.
    Nomade : déplaçable sur USB, synchronisable P2P.
    Versionnée : checkout(version) via LanceDB natif.
    Fallback SQLite si LanceDB non installé.
    """

    def __init__(self, uri: str = None) -> None:
        """Init.

        Args:
            uri: Description.
        """
        self._uri = uri or str(MESH_DIR)
        self._db = None
        self._ldb = _get_lancedb()
        if self._ldb:
            self._db = self._ldb.connect(self._uri)

    def is_available(self) -> bool:
        """Is available."""
        return self._db is not None

    # ── Thoughts (ring 3-5) ───────────────────────────────────────────────────

    def ingest_thought(
        self,
        agent_id: str,
        content: str,
        session_id: str = "",
        ring: int = 5,
        drift: float = 0.0,
        summary: str = "",
        vector: list = None,
    ) -> dict:
        """Archive un token/réponse agent dans swarm_thoughts."""
        if not self._db:
            return self._fallback_sqlite(
                "swarm_thoughts", {"agent": agent_id, "content": content[:500], "session": session_id, "ring": ring}
            )

        pa = _get_pa()
        if not pa:
            return {"ok": False, "error": "pyarrow manquant"}

        vec = vector or [0.0] * 256
        if len(vec) < 256:
            vec = vec + [0.0] * (256 - len(vec))
        vec = vec[:256]

        row = [
            {
                "id": f"{agent_id}_{int(time.time() * 1000)}",
                "agent": agent_id,
                "session": session_id,
                "ring": ring,
                "content": content[:1000],
                "summary": summary[:200],
                "drift": float(drift),
                "vector": vec,
                "ts": time.time(),
                "version": int(time.time()),
            }
        ]

        try:
            if "swarm_thoughts" not in self._db.table_names():
                self._db.create_table("swarm_thoughts", data=row, schema=_schema_thoughts())
            else:
                tbl = self._db.open_table("swarm_thoughts")
                tbl.add(row)
            return {"ok": True, "id": row[0]["id"], "ring": ring}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    # ── ADR validés (ring 2) ──────────────────────────────────────────────────

    def archive_synthesis(
        self,
        title: str,
        synthesis: str,
        ring: int = 2,
        adr_id: str = "",
        vector: list = None,
    ) -> dict:
        """
        Archive une synthèse validée → futur ADR ring 2.
        Chaque synthèse devient un point de version LanceDB.
        """
        if not self._db:
            return self._fallback_sqlite("adr_validated", {"title": title, "synthesis": synthesis[:500], "ring": ring})

        pa = _get_pa()
        if not pa:
            return {"ok": False, "error": "pyarrow manquant"}

        vec = vector or [0.0] * 256
        vec = (vec + [0.0] * 256)[:256]
        ts = time.time()
        aid = adr_id or f"ADR-MESH-{int(ts)}"

        row = [
            {
                "adr_id": aid,
                "title": title[:200],
                "synthesis": synthesis[:2000],
                "ring": ring,
                "status": "Proposé",
                "vector": vec,
                "ts": ts,
                "version": int(ts),
            }
        ]

        try:
            if "adr_validated" not in self._db.table_names():
                self._db.create_table("adr_validated", data=row, schema=_schema_adr())
            else:
                tbl = self._db.open_table("adr_validated")
                tbl.add(row)

            # Broadcast mmap
            _broadcast_mesh(aid, title, ring)

            return {"ok": True, "adr_id": aid, "version": row[0]["version"]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    # ── Rollback versioned ────────────────────────────────────────────────────

    def rollback_to_version(self, table_name: str, version: int) -> dict:
        """
        Rollback LanceDB vers une version antérieure.
        Utilisé par l'Inspecteur R4 pour annuler un pourrissement.
        LanceDB API : table.restore(version) ou checkout.
        """
        if not self._db:
            return {"ok": False, "error": "LanceDB non disponible"}
        try:
            if table_name not in self._db.table_names():
                return {"ok": False, "error": f"Table {table_name} inexistante"}
            tbl = self._db.open_table(table_name)
            # LanceDB API correcte : restore() pas checkout()
            tbl.restore(version)
            return {"ok": True, "table": table_name, "version": version}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def get_versions(self, table_name: str) -> list:
        """Liste les versions disponibles d'une table."""
        if not self._db:
            return []
        try:
            tbl = self._db.open_table(table_name)
            return [{"version": v} for v in tbl.list_versions()]
        except Exception:
            return []

    def search_similar(self, table_name: str, vector: list, limit: int = 5) -> list:
        """Recherche vectorielle dans une table."""
        if not self._db:
            return []
        try:
            vec = (vector + [0.0] * 256)[:256]
            tbl = self._db.open_table(table_name)
            results = tbl.search(vec).limit(limit).to_list()
            return results
        except Exception:
            return []

    # ── Sync P2P ──────────────────────────────────────────────────────────────

    def sync_to_remote(self, dry_run: bool = False) -> dict:
        """
        Sync DETACHED vers SSH_HOST via rsync.
        En dev : simulation seulement.
        """
        host = _acces_ssh("SSH_HOST")
        user = _acces_ssh("SSH_USER")
        key = _acces_ssh("PRIVATE_KEY_PATH")

        if not host or not user:
            return {"ok": False, "error": "SSH_HOST/SSH_USER non définis dans .env"}

        if _is_dev() and not dry_run:
            return {"ok": True, "action": "dev_skip", "message": "Dev mode — sync simulé (LAFORGE_ENV=dev)"}

        remote = f"{user}@{host}:~/nokido_mesh/"
        cmd = [
            "rsync",
            "-avz",
            "--delete",
            "-e",
            f"ssh -i {key} -o StrictHostKeyChecking=no",
            str(MESH_DIR) + "/",
            remote,
        ]

        if dry_run:
            return {"ok": True, "action": "dry_run", "cmd": " ".join(cmd)}

        DETACHED = 0x00000008
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=DETACHED)
            return {"ok": True, "action": "sync_launched", "remote": remote}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    # ── Fallback SQLite si pas LanceDB ────────────────────────────────────────

    def _fallback_sqlite(self, table: str, data: dict) -> dict:
        """Fallback : stocke dans events.db si LanceDB manque."""
        try:
            import sqlite3

            db = ROOT / "sandbox" / "events.db"
            conn = sqlite3.connect(str(db), timeout=5)
            last = conn.execute("SELECT MAX(sequence_id) FROM event_log").fetchone()[0] or 0
            conn.execute(
                "INSERT INTO event_log(timecode,sequence_id,agent_id,"
                "event_type,target,payload,status) VALUES(?,?,?,?,?,?,?)",
                (
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                    last + 1,
                    data.get("agent", "mesh"),
                    "mesh_fallback",
                    table,
                    json.dumps(data)[:500],
                    "ok",
                ),
            )
            conn.commit()
            conn.close()
            return {"ok": True, "action": "sqlite_fallback", "table": table}
        except Exception as e:
            return {"ok": False, "error": str(e)[:80]}


# ── MMap broadcast ────────────────────────────────────────────────────────────


def _broadcast_mesh(adr_id: str, title: str, ring: int) -> None:
    """Broadcast mesh.

    Args:
        adr_id: Description.
        title: Description.
        ring: Description.
    """
    try:
        from nokido_agent.app.live_bridge import bridge

        bridge.json_set("mesh.last_adr", adr_id)
        bridge.json_set("mesh.last_title", title[:40])
        bridge.json_set("mesh.ring", ring)
        bridge.json_set("mesh.ts", time.time())
    except Exception:
        pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_mesh: Optional[MeshMemory] = None


def get_mesh() -> MeshMemory:
    """Get mesh."""
    global _mesh
    if _mesh is None:
        _mesh = MeshMemory()
    return _mesh


def mesh_status() -> dict:
    """Mesh status."""
    m = get_mesh()
    tables = []
    if m.is_available():
        try:
            tables = m._db.table_names()
        except Exception:
            pass
    return {
        "available": m.is_available(),
        "uri": str(MESH_DIR),
        "tables": tables,
        "dev_mode": _is_dev(),
        "ssh_host": _acces_ssh("SSH_HOST"),
        "lancedb": _get_lancedb() is not None,
    }
