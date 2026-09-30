"""forge_sovereign_mapper.py — Souverainete Symmetrique"""

from __future__ import annotations
import hashlib, re, sqlite3, threading
from pathlib import Path

_IP_PAT = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC_PAT = re.compile(r"\b(?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}\b", re.IGNORECASE)
_CRED_PAT = re.compile(r"(?:password|passwd|secret|token)\s*[=:]\s*\S+", re.IGNORECASE)
_RULES = [(_IP_PAT, "SRV_NET", "ip"), (_MAC_PAT, "MAC_DEVICE", "mac")]


class SovereignContextMapper:
    """Anonymise tokens sensibles avant envoi cloud, reconstruit apres."""

    def __init__(self, db_path: str = "", mission_id: str = "default"):
        self.mission_id = mission_id
        self._lock = threading.Lock()
        self._fwd: dict[str, str] = {}
        self._rev: dict[str, str] = {}
        self._cnt: dict[str, int] = {}
        root = Path(__file__).resolve().parent.parent
        self._db = db_path or str(root / "recon_silo" / "recon_data" / "sovereign_mapper.db")
        Path(self._db).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load()

    def _connect(self):
        return sqlite3.connect(self._db, check_same_thread=False)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS alias_map (mission_id TEXT, token TEXT, alias TEXT, type TEXT, PRIMARY KEY (mission_id, token))"
            )
            conn.commit()

    def _load(self) -> None:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT token, alias FROM alias_map WHERE mission_id=?", (self.mission_id,)
                ).fetchall()
            with self._lock:
                for tok, alias in rows:
                    self._fwd[tok] = alias
                    self._rev[alias] = tok
        except Exception:
            pass

    def _alias(self, prefix: str, token: str, typ: str) -> str:
        with self._lock:
            if token in self._fwd:
                return self._fwd[token]
        h = hashlib.sha256(token.encode()).hexdigest()[:4].upper()
        with self._lock:
            n = self._cnt.get(prefix, 0) + 1
            self._cnt[prefix] = n
            alias = prefix + "_" + h + str(n).zfill(2)
            if token not in self._fwd:
                self._fwd[token] = alias
                self._rev[alias] = token
        try:
            with self._connect() as conn:
                conn.execute("INSERT OR IGNORE INTO alias_map VALUES (?,?,?,?)", (self.mission_id, token, alias, typ))
                conn.commit()
        except Exception:
            pass
        return alias

    def wrap_input(self, data: str) -> str:
        result = data
        for pat, prefix, typ in _RULES:

            def _rep(m, _p=prefix, _t=typ):
                return self._alias(_p, m.group(0), _t)

            result = pat.sub(_rep, result)

        def _cred(m):
            key = m.group(0).split("=")[0].split(":")[0].strip()
            return key + "=CRED_REDACTED"

        return _CRED_PAT.sub(_cred, result)

    def unwrap_output(self, raw: str) -> str:
        result = raw
        with self._lock:
            rev = dict(self._rev)
        for alias, token in sorted(rev.items(), key=lambda x: -len(x[0])):
            if alias in result:
                result = result.replace(alias, token)
        return result

    def dump(self) -> dict:
        with self._lock:
            return {"fwd": dict(self._fwd), "rev": dict(self._rev)}

    def reset(self) -> None:
        with self._lock:
            self._fwd.clear()
            self._rev.clear()
            self._cnt.clear()
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM alias_map WHERE mission_id=?", (self.mission_id,))
                conn.commit()
        except Exception:
            pass
