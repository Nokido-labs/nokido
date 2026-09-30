"""
tests/nr/test_hub_jti_persistence.py - NR persistence cache JTI (SQLite WAL).

Complete Gemini #2 : le cache in-mem est perdu au restart hub.
Avec SqlitePersister + attach_and_preload, les revocations survivent.

Coverage :
  - SqlitePersister : save/load roundtrip
  - Purge DB des entrees expirees (load_all fait la purge)
  - Write-through : revoke() via cache -> visible en DB
  - Preload : nouveau cache hydrate correctement depuis DB
  - Scenario restart simule : revoke, recreer cache+persister neuf,
    preload -> jti toujours refuse
  - Resilience : panne save() du persister ne casse pas revoke()
  - Close idempotent + flush queue
  - Desactivation via env LAFORGE_JTI_PERSIST=0
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# -------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------
@pytest.fixture
def tmp_db(tmp_path):
    """Chemin DB temporaire, unique par test."""
    return str(tmp_path / "hub_state_test.db")


@pytest.fixture
def fresh_cache():
    """Cache jti propre + module reimporte."""
    for m in list(sys.modules):
        if m.startswith("app.web_hub.jti_cache"):
            del sys.modules[m]
    from app.web_hub.jti_cache import revocation_cache
    revocation_cache.clear()
    revocation_cache.attach_persister(None)
    yield revocation_cache
    revocation_cache.clear()
    revocation_cache.attach_persister(None)


# -------------------------------------------------------------------
# SqlitePersister : unit
# -------------------------------------------------------------------
class TestSqlitePersister:
    def test_save_and_load_roundtrip(self, tmp_db):
        from app.web_hub.jti_cache import SqlitePersister
        p = SqlitePersister(tmp_db)
        try:
            exp = time.time() + 60
            p.save("jti-roundtrip-1", exp)
            p.close(flush_timeout=2.0)

            p2 = SqlitePersister(tmp_db)
            try:
                rows = list(p2.load_all())
                jtis = {r[0] for r in rows}
                assert "jti-roundtrip-1" in jtis
            finally:
                p2.close()
        finally:
            # cleanup si close deja fait
            pass

    def test_load_purges_expired(self, tmp_db):
        """Les entrees exp <= now() sont supprimees par load_all."""
        from app.web_hub.jti_cache import SqlitePersister
        p = SqlitePersister(tmp_db)
        try:
            p.save("keep", time.time() + 60)
            p.save("gone", time.time() - 10)
            p.close(flush_timeout=2.0)

            p2 = SqlitePersister(tmp_db)
            try:
                rows = list(p2.load_all())
                jtis = {r[0] for r in rows}
                assert "keep" in jtis
                assert "gone" not in jtis
                # Second load : la purge a ete persistee (gone supprimee du fichier)
                rows2 = list(p2.load_all())
                jtis2 = {r[0] for r in rows2}
                assert "gone" not in jtis2
            finally:
                p2.close()
        finally:
            pass

    def test_save_idempotent_on_same_jti(self, tmp_db):
        """INSERT OR IGNORE : un double save ne crash pas."""
        from app.web_hub.jti_cache import SqlitePersister
        p = SqlitePersister(tmp_db)
        try:
            exp = time.time() + 60
            p.save("dup", exp)
            p.save("dup", exp + 100)  # tentative de mise a jour
            p.close(flush_timeout=2.0)

            p2 = SqlitePersister(tmp_db)
            try:
                rows = list(p2.load_all())
                jtis = [r[0] for r in rows]
                assert jtis.count("dup") == 1
            finally:
                p2.close()
        finally:
            pass

    def test_batch_flush(self, tmp_db):
        """32+ saves = au moins un batch flush du worker."""
        from app.web_hub.jti_cache import SqlitePersister
        p = SqlitePersister(tmp_db)
        try:
            now = time.time()
            for i in range(50):
                p.save(f"batch-{i}", now + 60)
            p.close(flush_timeout=3.0)

            p2 = SqlitePersister(tmp_db)
            try:
                rows = list(p2.load_all())
                assert len(rows) >= 50
            finally:
                p2.close()
        finally:
            pass

    def test_close_idempotent(self, tmp_db):
        from app.web_hub.jti_cache import SqlitePersister
        p = SqlitePersister(tmp_db)
        p.close()
        # Second close : pas de crash
        p.close()

    def test_close_drains_queue(self, tmp_db):
        """Un save juste avant close doit etre persiste."""
        from app.web_hub.jti_cache import SqlitePersister
        p = SqlitePersister(tmp_db)
        p.save("last-minute", time.time() + 60)
        p.close(flush_timeout=2.0)

        p2 = SqlitePersister(tmp_db)
        try:
            rows = list(p2.load_all())
            jtis = {r[0] for r in rows}
            assert "last-minute" in jtis
        finally:
            p2.close()


# -------------------------------------------------------------------
# Integration : cache + persister write-through
# -------------------------------------------------------------------
class TestWriteThroughIntegration:
    def test_revoke_via_cache_appears_in_db(self, fresh_cache, tmp_db):
        from app.web_hub.jti_cache import SqlitePersister
        p = SqlitePersister(tmp_db)
        try:
            fresh_cache.attach_persister(p)
            fresh_cache.revoke("through-1", time.time() + 60)
            # Laisse le worker drainer
            p.close(flush_timeout=2.0)
        finally:
            pass
        # Re-ouvre : la revocation est persistee
        p2 = SqlitePersister(tmp_db)
        try:
            rows = list(p2.load_all())
            jtis = {r[0] for r in rows}
            assert "through-1" in jtis
        finally:
            p2.close()

    def test_revoke_without_persister_no_crash(self, fresh_cache):
        """Backward-compat : cache sans persister fonctionne toujours."""
        # fresh_cache arrive avec persister=None
        assert fresh_cache.revoke("no-persist", time.time() + 60) is True
        assert fresh_cache.is_revoked("no-persist") is True

    def test_persister_save_failure_does_not_break_revoke(self, fresh_cache):
        """Si save() du persister leve, revoke() retourne True quand meme.

        Principe : la persistence est best-effort. Une erreur disk NE DOIT
        PAS empecher une revocation in-mem (sinon un attaquant pourrait
        bloquer le logout en saturant le FS).
        """
        class BrokenPersister:
            def save(self, jti, exp):
                raise OSError("disk full")

            def load_all(self):
                return []

        fresh_cache.attach_persister(BrokenPersister())
        assert fresh_cache.revoke("resilient", time.time() + 60) is True
        assert fresh_cache.is_revoked("resilient") is True


# -------------------------------------------------------------------
# Preload : hydrate le cache au boot
# -------------------------------------------------------------------
class TestPreload:
    def test_attach_and_preload_hydrates_cache(self, fresh_cache, tmp_db):
        from app.web_hub.jti_cache import SqlitePersister, attach_and_preload
        # Phase 1 : seed la DB via un persister transitoire
        seed = SqlitePersister(tmp_db)
        seed.save("preloaded-1", time.time() + 60)
        seed.save("preloaded-2", time.time() + 60)
        seed.close(flush_timeout=2.0)
        # Phase 2 : cache vierge + nouveau persister + preload
        fresh_cache.clear()
        assert fresh_cache.is_revoked("preloaded-1") is False  # cache vide
        p = SqlitePersister(tmp_db)
        try:
            n = attach_and_preload(p, fresh_cache)
            assert n >= 2
            assert fresh_cache.is_revoked("preloaded-1") is True
            assert fresh_cache.is_revoked("preloaded-2") is True
        finally:
            p.close()

    def test_preload_skips_expired(self, fresh_cache, tmp_db):
        """Une entree exp <= now() ne doit pas etre preloadee."""
        from app.web_hub.jti_cache import SqlitePersister, attach_and_preload
        seed = SqlitePersister(tmp_db)
        seed.save("alive", time.time() + 60)
        seed.save("dead", time.time() - 10)
        seed.close(flush_timeout=2.0)

        fresh_cache.clear()
        p = SqlitePersister(tmp_db)
        try:
            attach_and_preload(p, fresh_cache)
            assert fresh_cache.is_revoked("alive") is True
            assert fresh_cache.is_revoked("dead") is False
        finally:
            p.close()

    def test_preload_on_empty_db_noop(self, fresh_cache, tmp_db):
        from app.web_hub.jti_cache import SqlitePersister, attach_and_preload
        p = SqlitePersister(tmp_db)
        try:
            n = attach_and_preload(p, fresh_cache)
            assert n == 0
            assert fresh_cache.size() == 0
        finally:
            p.close()


# -------------------------------------------------------------------
# Scenario phare : restart simule
# -------------------------------------------------------------------
class TestRestartScenario:
    def test_revoked_jti_still_refused_after_restart(self, fresh_cache, tmp_db):
        """Le scenario qui JUSTIFIE la persistence.

        1. logout : revoque un jti (write-through DB).
        2. restart hub simule : on detache le persister, on clear le cache.
        3. reboot : nouveau persister + preload.
        4. verify_token avec le meme jti doit TOUJOURS refuser.
        """
        from app.web_hub.jti_cache import (
            SqlitePersister, attach_and_preload, is_jti_revoked,
        )
        stolen_jti = "stolen-before-crash"
        stolen_exp = time.time() + 300

        # --- Phase 1 : hub live, user logout ---
        p1 = SqlitePersister(tmp_db)
        fresh_cache.attach_persister(p1)
        fresh_cache.revoke(stolen_jti, stolen_exp)
        assert is_jti_revoked(stolen_jti) is True
        # Simule le shutdown hub (flush + close)
        fresh_cache.attach_persister(None)
        p1.close(flush_timeout=2.0)
        fresh_cache.clear()  # restart = perte totale du cache in-mem
        assert is_jti_revoked(stolen_jti) is False  # cache vide !

        # --- Phase 2 : reboot ---
        p2 = SqlitePersister(tmp_db)
        try:
            attach_and_preload(p2, fresh_cache)
            # Le jti vole reste refuse apres restart
            assert is_jti_revoked(stolen_jti) is True
        finally:
            p2.close()


# -------------------------------------------------------------------
# Desactivation explicite via env (test, dev, ephemeral)
# -------------------------------------------------------------------
class TestEnvDisable:
    def test_jti_persist_env_zero_disables(self, monkeypatch, tmp_db):
        """LAFORGE_JTI_PERSIST=0 : le startup hook ne cree pas de persister.

        Test via le boot FastAPI TestClient : le startup est appele.
        """
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "env-disable-test-token")
        monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
        monkeypatch.setenv("LAFORGE_JTI_PERSIST", "0")
        monkeypatch.setenv("LAFORGE_JTI_DB", tmp_db)
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from fastapi.testclient import TestClient
        import app.web_hub.app as app_mod
        with TestClient(app_mod.app) as client:
            # Login + logout : revoke in-mem
            r = client.post("/auth/login",
                            data={"admin_token": "env-disable-test-token"})
            assert r.status_code == 200
            r = client.post("/auth/logout")
            assert r.status_code == 200
        # Aucune DB n'a ete creee (car persist desactivee)
        assert not os.path.exists(tmp_db)
        # Le module-level persister est None
        assert app_mod._jti_persister is None

    def test_jti_persist_default_enabled(self, monkeypatch, tmp_db):
        """Sans variable : persistence active par defaut."""
        monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", "env-default-test-token")
        monkeypatch.setenv("LAFORGE_AUTH_ENABLED", "1")
        monkeypatch.delenv("LAFORGE_JTI_PERSIST", raising=False)
        monkeypatch.setenv("LAFORGE_JTI_DB", tmp_db)
        for m in list(sys.modules):
            if m.startswith("app.web_hub"):
                del sys.modules[m]
        from fastapi.testclient import TestClient
        import app.web_hub.app as app_mod
        with TestClient(app_mod.app) as client:
            r = client.post("/auth/login",
                            data={"admin_token": "env-default-test-token"})
            assert r.status_code == 200
            token = r.json()["token"]
            r = client.post("/auth/logout")
            assert r.status_code == 200
            # Laisse le worker flusher
            time.sleep(0.3)
        # La DB existe et contient au moins une entree
        assert os.path.exists(tmp_db)
        from app.web_hub.jti_cache import SqlitePersister
        p = SqlitePersister(tmp_db)
        try:
            rows = list(p.load_all())
            assert len(rows) >= 1
        finally:
            p.close()
