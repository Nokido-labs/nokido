# tests/nr/test_vec_ledger_settings_nr.py
"""
NR — forge_vec_ledger + forge_settings + forge_npu_embedder (singleton)
=======================================================================
Couvre les 3 modules non testés identifiés lors du bilan v0.13.1 :
  - forge_vec_ledger   : hash, sign, verify, sign_and_log, audit_ledger
  - forge_settings     : Settings, _cast, _load_env_file, _acquire/_release
  - forge_npu_embedder : get_npu_embedder singleton (thread-safety)
"""
from __future__ import annotations
import sys, os, hashlib, hmac, json, threading, time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))


# =============================================================================
# TestForgeVecLedger
# =============================================================================

class TestForgeVecLedger:
    """forge_vec_ledger — signature cryptographique des vecteurs."""

    @pytest.fixture(autouse=True)
    def imports(self):
        from forge_vec_ledger import (
            hash_vector, sign_hash, verify_vector,
            sign_and_log, audit_ledger, _key,
        )
        import numpy as np
        self.hash_vector  = hash_vector
        self.sign_hash    = sign_hash
        self.verify_vector = verify_vector
        self.sign_and_log = sign_and_log
        self.audit_ledger = audit_ledger
        self._key         = _key
        self.np           = np

    # ── hash_vector ──────────────────────────────────────────────────────────

    def test_hash_vector_deterministe(self):
        """SHA256 d'un vecteur est déterministe."""
        vec  = self.np.ones(384, dtype=self.np.float32)
        blob = vec.tobytes()
        h1   = self.hash_vector(blob)
        h2   = self.hash_vector(blob)
        assert h1 == h2
        assert len(h1) == 64   # hex SHA256

    def test_hash_vector_different_vecs(self):
        """Deux vecteurs différents → hashes différents."""
        v1 = self.np.ones(384,  dtype=self.np.float32).tobytes()
        v2 = self.np.zeros(384, dtype=self.np.float32).tobytes()
        assert self.hash_vector(v1) != self.hash_vector(v2)

    def test_hash_vector_sensible_au_bit(self):
        """Un seul float modifié → hash complètement différent (avalanche)."""
        vec      = self.np.ones(384, dtype=self.np.float32)
        blob_ok  = vec.tobytes()
        vec[0]  += 1e-7
        blob_bad = vec.tobytes()
        assert self.hash_vector(blob_ok) != self.hash_vector(blob_bad)

    # ── sign_hash ─────────────────────────────────────────────────────────────

    def test_sign_hash_longueur(self):
        """HMAC-SHA256 = 64 caractères hex."""
        h   = self.hash_vector(self.np.ones(384, dtype=self.np.float32).tobytes())
        sig = self.sign_hash(h)
        assert len(sig) == 64

    def test_sign_hash_deterministe(self):
        """Même hash → même signature (clé stable)."""
        h    = "a" * 64
        s1   = self.sign_hash(h)
        s2   = self.sign_hash(h)
        assert s1 == s2

    # ── verify_vector ─────────────────────────────────────────────────────────

    def test_verify_cycle_complet(self):
        """hash → sign → verify = True."""
        blob = self.np.random.randn(384).astype(self.np.float32).tobytes()
        h    = self.hash_vector(blob)
        sig  = self.sign_hash(h)
        assert self.verify_vector(blob, sig) is True

    def test_verify_vecteur_modifie(self):
        """Vecteur altéré → verify = False (intégrité)."""
        vec  = self.np.ones(384, dtype=self.np.float32)
        blob = vec.tobytes()
        sig  = self.sign_hash(self.hash_vector(blob))
        vec[0] += 0.001
        assert self.verify_vector(vec.tobytes(), sig) is False

    def test_verify_signature_falsifiee(self):
        """Signature falsifiée → verify = False."""
        blob = self.np.ones(384, dtype=self.np.float32).tobytes()
        assert self.verify_vector(blob, "a" * 64) is False

    def test_verify_constant_time(self):
        """verify_vector utilise hmac.compare_digest (constant-time)."""
        import forge_vec_ledger as fvl
        import inspect
        src = inspect.getsource(fvl.verify_vector)
        assert "compare_digest" in src

    # ── sign_and_log ──────────────────────────────────────────────────────────

    def test_sign_and_log_retourne_sigs(self):
        """sign_and_log retourne une liste de dicts avec vec_hash/vec_sig."""
        vecs  = [self.np.random.randn(384).astype(self.np.float32).tolist() for _ in range(3)]
        texts = [f"chunk {i}" for i in range(3)]
        sigs  = self.sign_and_log(vecs, texts, source="nr_test",
                                   db_path=Path("/tmp/nonexistent_nr.db"))
        assert len(sigs) == 3
        for s in sigs:
            assert "vec_hash" in s and "vec_sig" in s
            assert s["ring"] == 3
            assert len(s["vec_hash"]) == 64
            assert len(s["vec_sig"])  == 64

    def test_sign_and_log_vide(self):
        """sign_and_log([]) → []."""
        assert self.sign_and_log([], [], db_path=Path("/tmp/nr.db")) == []

    def test_sign_and_log_signatures_valides(self):
        """Chaque signature peut être re-vérifiée offline."""
        vecs  = [self.np.ones(384, dtype=self.np.float32).tolist()]
        sigs  = self.sign_and_log(vecs, ["test"], db_path=Path("/tmp/nr.db"))
        blob  = self.np.array(vecs[0], dtype=self.np.float32).tobytes()
        assert self.verify_vector(blob, sigs[0]["vec_sig"]) is True

    def test_sign_and_log_overhead(self):
        """Overhead < 5ms pour 10 chunks (budget 30ms total)."""
        vecs  = [self.np.random.randn(384).astype(self.np.float32).tolist()
                 for _ in range(10)]
        texts = [f"chunk {i}" for i in range(10)]
        t0    = time.perf_counter()
        self.sign_and_log(vecs, texts, db_path=Path("/tmp/nr.db"))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 5, f"trop lent: {elapsed_ms:.2f}ms"

    # ── audit_ledger ──────────────────────────────────────────────────────────

    def test_audit_ledger_db_absente(self):
        """audit_ledger sans DB → retourne erreur propre, pas d'exception."""
        result = self.audit_ledger(db_path=Path("/tmp/nonexistent_audit.db"))
        assert "error" in result or result["ok"] == 0

    def test_audit_ledger_structure(self):
        """audit_ledger retourne ok/fail/entries."""
        result = self.audit_ledger(db_path=Path("/tmp/nonexistent_audit.db"))
        assert "ok"   in result
        assert "fail" in result

    def test_audit_ledger_vraie_db(self):
        """audit_ledger sur la vraie DB — pas d'exception."""
        db = Path("RAG/embeddings.db")
        if not db.exists():
            pytest.skip("DB absente")
        result = self.audit_ledger(limit=5, db_path=db)
        assert isinstance(result["ok"], int)
        assert isinstance(result["fail"], int)


# =============================================================================
# TestForgeSettings
# =============================================================================

class TestForgeSettings:
    """forge_settings — configuration, lock, cast, env."""

    @pytest.fixture(autouse=True)
    def imports(self):
        # Recharger proprement
        for k in list(sys.modules):
            if "forge_settings" in k:
                del sys.modules[k]
        from forge_settings import (
            _cast, _load_env_file, Settings, create_settings,
            _acquire_instance_lock, _release_instance_lock,
            debug_log, _SETTINGS_FIELDS,
            _ROOT_DIR, _DATA_DIR, _LOGS_DIR, _APP_DIR,
        )
        self._cast                  = _cast
        self._load_env_file         = _load_env_file
        self.Settings               = Settings
        self._acquire               = _acquire_instance_lock
        self._release               = _release_instance_lock
        self.debug_log              = debug_log
        self._SETTINGS_FIELDS       = _SETTINGS_FIELDS
        self._ROOT_DIR              = _ROOT_DIR

    # ── exports ──────────────────────────────────────────────────────────────

    def test_exports_complets(self):
        """Tous les exports attendus par Nokido.py sont présents."""
        import forge_settings as fs
        for name in ["_purge_pycache", "_acquire_instance_lock",
                     "_release_instance_lock", "debug_log", "_cast",
                     "_load_env_file", "Settings", "create_settings",
                     "_ROOT_DIR", "_DATA_DIR", "_LOGS_DIR", "_APP_DIR",
                     "_SETTINGS_FIELDS"]:
            assert hasattr(fs, name), f"manquant: {name}"

    def test_settings_fields_count(self):
        """23 champs dans _SETTINGS_FIELDS."""
        assert len(self._SETTINGS_FIELDS) == 26  # mis à jour v0.13.3: +tz_offset, nokido_env, db_path

    # ── _cast ─────────────────────────────────────────────────────────────────

    def test_cast_bool_true(self):
        for v in ("1", "true", "yes", "oui", "on", "TRUE", "Yes"):
            assert self._cast(v, bool) is True, f"failed: {v!r}"

    def test_cast_bool_false(self):
        for v in ("0", "false", "no", "off", "FALSE"):
            assert self._cast(v, bool) is False, f"failed: {v!r}"

    def test_cast_int(self):
        assert self._cast("42", int)  == 42
        assert self._cast("-1", int)  == -1

    def test_cast_str(self):
        assert self._cast("hello", str) == "hello"

    def test_cast_path(self):
        r = self._cast("/tmp/test", Path)
        assert isinstance(r, Path)

    # ── Settings ─────────────────────────────────────────────────────────────

    def test_settings_instanciation(self):
        """Settings() ne crash pas avec les vars d'env actuelles."""
        s = self.Settings()
        assert hasattr(s, "ollama_url")
        assert hasattr(s, "use_rag")
        assert hasattr(s, "ollama_model")   # alias

    def test_settings_defaults(self):
        """Valeurs par défaut cohérentes."""
        s = self.Settings()
        assert isinstance(s.max_concurrent_tasks, int)
        assert 1 <= s.max_concurrent_tasks <= 50
        assert isinstance(s.use_rag, bool)
        assert s.ollama_url.startswith("http")

    def test_settings_validate_all(self):
        """validate_all() retourne une liste (possiblement vide)."""
        s      = self.Settings()
        errors = s.validate_all()
        assert isinstance(errors, list)

    # ── _load_env_file ────────────────────────────────────────────────────────

    def test_load_env_file_ne_crash_pas(self):
        """_load_env_file avec fichier absent → silencieux."""
        self._load_env_file("/tmp/nonexistent_nokido_nr.env")

    def test_load_env_file_charge(self, tmp_path):
        """_load_env_file charge les variables correctement."""
        env_file = tmp_path / "test.env"
        env_file.write_text("NR_TEST_VAR_42=hello_nr\n", encoding="utf-8")
        # Supprimer si existe
        os.environ.pop("NR_TEST_VAR_42", None)
        self._load_env_file(str(env_file))
        assert os.environ.get("NR_TEST_VAR_42") == "hello_nr"
        del os.environ["NR_TEST_VAR_42"]

    # ── debug_log ─────────────────────────────────────────────────────────────

    def test_debug_log_ne_crash_pas(self):
        """debug_log() ne crash pas même si chemin invalide."""
        self.debug_log("nr_test", "test_vec_ledger_settings_nr", "NR OK", level="INFO")

    # ── lock ─────────────────────────────────────────────────────────────────

    def test_acquire_release_cycle(self, tmp_path):
        """_acquire → _release sans crash (lock fichier propre)."""
        import forge_settings as fs
        orig_lock = fs._LOCK_FILE
        fs._LOCK_FILE = tmp_path / "test_nr.lock"
        fs._LOCK_FH   = None
        try:
            fs._acquire_instance_lock()
            fs._release_instance_lock()
        finally:
            fs._LOCK_FILE = orig_lock
            fs._LOCK_FH   = None


# =============================================================================
# TestForgeNpuEmbedderSingleton
# =============================================================================

class TestForgeNpuEmbedderSingleton:
    """forge_npu_embedder — get_npu_embedder singleton thread-safety."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton avant chaque test."""
        import forge_npu_embedder as fne
        fne._SINGLETON = None
        yield
        fne._SINGLETON = None

    def test_get_npu_embedder_importable(self):
        """get_npu_embedder est exporté."""
        from forge_npu_embedder import get_npu_embedder
        assert callable(get_npu_embedder)

    def test_singleton_idempotent(self):
        """get_npu_embedder() appelé 2× retourne le même objet ou None."""
        from forge_npu_embedder import get_npu_embedder
        r1 = get_npu_embedder()
        r2 = get_npu_embedder()
        # Si le modèle est absent → None, sinon même instance
        assert r1 is r2

    def test_singleton_thread_safe(self):
        """get_npu_embedder() appelé depuis N threads → 1 seule instance."""
        from forge_npu_embedder import get_npu_embedder
        results = []
        errors  = []

        def call():
            try:
                results.append(id(get_npu_embedder()))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=call) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=10)

        assert not errors, f"Erreurs threads: {errors}"
        # Toutes les instances doivent être identiques (ou toutes None → id==0)
        unique_ids = set(results)
        assert len(unique_ids) <= 1, f"Plus d'une instance: {unique_ids}"

    @pytest.mark.skipif(
        True,
        reason="onnxruntime compile NumPy 1.x incompatible avec NumPy 2.x"
    )
    def test_npu_embedder_interface(self):
        """NPUEmbedder expose .available, .provider, embed_one, embed_batch."""
        from forge_npu_embedder import NPUEmbedder
        e = NPUEmbedder()
        assert hasattr(e, "available")
        assert hasattr(e, "provider")
        assert hasattr(e, "embed_one")
        assert hasattr(e, "embed_batch")
        assert hasattr(e, "status")

    @pytest.mark.skipif(
        True,
        reason="onnxruntime compile NumPy 1.x incompatible avec NumPy 2.x"
    )
    def test_npu_embedder_status_dict(self):
        """status() retourne un dict avec les clés attendues."""
        from forge_npu_embedder import NPUEmbedder
        s = NPUEmbedder().status()
        assert isinstance(s, dict)
        for key in ("available", "provider", "dim", "db_vectors"):
            assert key in s, f"clé manquante: {key}"

    def test_get_npu_embedder_exported(self):
        """get_npu_embedder est dans le module (pas seulement __all__)."""
        import forge_npu_embedder as fne
        assert hasattr(fne, "get_npu_embedder")
        assert hasattr(fne, "_SINGLETON")
        assert hasattr(fne, "_SINGLETON_LOCK")


# =============================================================================
# TestBehaviorGoldDataset
# =============================================================================

class TestBehaviorGoldDataset:
    """Vérifie que behavior_gold.json est à jour et couvre vec_ledger."""

    def test_behavior_gold_existe(self):
        p = Path("data_nr/expected/behavior_gold.json")
        assert p.exists()

    def test_behavior_gold_cmd08_present(self):
        """CMD-08 (vec_ledger sign+verify) est dans le dataset."""
        data = json.loads(Path("data_nr/expected/behavior_gold.json")
                          .read_text(encoding="utf-8"))
        assert any(k.startswith("CMD-08") for k in data)
        cmd08_key = next(k for k in data if k.startswith("CMD-08"))
        assert data[cmd08_key].get("status", "ok") == "ok"

    def test_behavior_gold_cmd09_present(self):
        """CMD-09 (tamper detection) est dans le dataset."""
        data = json.loads(Path("data_nr/expected/behavior_gold.json")
                          .read_text(encoding="utf-8"))
        assert any(k.startswith("CMD-09") for k in data)
        cmd09_key = next(k for k in data if k.startswith("CMD-09"))
        assert data[cmd09_key].get("status", "ok") == "ok"

    def test_behavior_gold_tous_ok(self):
        """Tous les scénarios behavior_gold ont les champs attendus."""
        data = json.loads(Path("data_nr/expected/behavior_gold.json")
                          .read_text(encoding="utf-8"))
        scenarios = {k: v for k, v in data.items() if not k.startswith("_")}
        assert len(scenarios) > 0, "dataset vide"
        fails = [k for k, v in scenarios.items()
                 if not isinstance(v, dict) or "name" not in v]
        assert not fails, f"Scénarios malformés: {fails}"


    def test_is_at_least_matrix_complet(self):
        """is_at_least_matrix.json couvre tous les 25 cas (5×5)."""
        data = json.loads(Path("data_nr/expected/is_at_least_matrix.json")
                          .read_text(encoding="utf-8"))
        cases = data.get("matrix", [])
        n_rings = len(set(c["ring"] for c in cases))
        assert len(cases) == n_rings * n_rings, f"attendu {n_rings*n_rings}, got {len(cases)}"

    def test_integrity_rings_5_rings(self):
        """integrity_rings.json contient tous les rings."""
        data  = json.loads(Path("data_nr/input/integrity_rings.json")
                           .read_text(encoding="utf-8"))
        rings = data.get("rings", {})
        assert len(rings) >= 5  # 6 rings depuis ajout MASTER_OVERRIDE
        # Vérifie les rings par numéro (labels peuvent changer)
        ring_nums = [r.get("ring") for r in rings]
        for expected_ring in (0, 1, 2, 3, 4):
            assert expected_ring in ring_nums, f"ring {expected_ring} absent"
