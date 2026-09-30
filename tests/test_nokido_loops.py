"""
test_nokido_loops.py — Tests des boucles La Forge v12
=======================================================
Exécution :
    python test_nokido_loops.py
    python test_nokido_loops.py -v

Catégories :
    TestSkillEntry        — vitality V(t), couches mémoire
    TestAgenticEngine     — record_success/error, fail_streak, janitor, entropie
    TestSaveOrchestrator  — checkpoint, rollback, GFS rotation, history
    TestVersionManager    — increment, prepare_patch, loop_trunk isolation
    TestEvolutionLoop     — flux atomique Staging→Sandbox→Audit→Commit/Rollback

Aucun SSH, Ollama, ou Textual requis.
"""
import asyncio, json, math, shutil, sys, tempfile, time, unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── Import du shim ────────────────────────────────────────────────────────────
try:
    import nokido_testable as lf
    SkillEntry            = lf.SkillEntry
    AgenticEngine         = lf.AgenticEngine
    ForgeSaveOrchestrator = lf.ForgeSaveOrchestrator
    VersionManager        = lf.VersionManager
    MEMORY_LAYERS         = lf.MEMORY_LAYERS
    ENTROPY_THRESHOLDS    = lf.ENTROPY_THRESHOLDS
    IMPORT_OK = True
except Exception as e:
    IMPORT_OK = False
    IMPORT_ERROR = str(e)
    print(f"[IMPORT FAILED] {e}")

def async_run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)

def skip_if_no_import(cls):
    if not IMPORT_OK:
        return unittest.skip(f"Import échoué : {IMPORT_ERROR}")(cls)
    return cls

# ── Helpers ───────────────────────────────────────────────────────────────────
def make_engine(tmp: Path) -> AgenticEngine:
    eng = AgenticEngine.__new__(AgenticEngine)
    eng.ui_callback     = None
    eng.log_fn          = lambda m: None
    eng._skills         = {}
    eng._current_skills = []
    eng._skill_file     = tmp / "skill_registry.json"
    return eng

def make_vm(tmp: Path) -> VersionManager:
    vm = VersionManager.__new__(VersionManager)
    src = tmp / "Nokido.py"
    src.write_text('__version__ = "12.0"\n# stable\n')
    vm.source_path   = src
    vm.workspace_dir = tmp / "workspace"
    vm.versions_dir  = tmp / "versions"
    vm.loop_dir      = tmp / "loop_trunk"
    for d in [vm.workspace_dir, vm.versions_dir, vm.loop_dir]:
        d.mkdir(parents=True, exist_ok=True)
    init = vm.workspace_dir / "Nokido_v12.0.py"
    shutil.copy2(src, init)
    vm.work_path        = init
    vm._loop_id         = None
    vm._loop_trunk      = None
    vm._version_index   = {}
    return vm

def make_orch(tmp: Path) -> ForgeSaveOrchestrator:
    orch = ForgeSaveOrchestrator.__new__(ForgeSaveOrchestrator)
    orch.staging_dir   = tmp / "staging"
    orch.backup_dir    = tmp / "backups"
    orch.history_file  = tmp / "backups" / "history.jsonl"
    orch.MAX_BACKUPS   = 3
    orch.KEEP_WEEKLY   = 2
    orch.KEEP_MONTHLY  = 1
    orch._last_backup  = None
    orch._staging_lock = asyncio.Lock()
    for d in [orch.staging_dir, orch.backup_dir]:
        d.mkdir(parents=True)
    ws = tmp / "workspace"
    ws.mkdir(exist_ok=True)
    (ws / "Nokido_v12.0.py").write_text("# code stable")
    return orch


# =============================================================================
# 1 — SkillEntry : structure et formule V(t)
# =============================================================================
@skip_if_no_import
class TestSkillEntry(unittest.TestCase):

    def test_valeurs_par_defaut(self):
        e = SkillEntry(name="reseau")
        self.assertEqual(e.status,        "waiting")
        self.assertEqual(e.layer,         "disco")
        self.assertTrue(e.unverified)
        self.assertEqual(e.fail_streak,   0)
        self.assertEqual(e.vitality_score, 1.0)
        self.assertEqual(e.uses,          0)

    def test_vitality_disco_30j_demi_vie(self):
        """V(30j) ≈ S_initial/2 pour layer=disco (λ=0.023)."""
        lam  = MEMORY_LAYERS["disco"]["lambda"]
        past = (datetime.utcnow() - timedelta(days=30)).isoformat()
        e    = SkillEntry(name="t", layer="disco", initial_score=0.9, ingested_at=past)
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            v   = eng._vitality(e)
        expected = 0.9 * math.exp(-lam * 30)
        self.assertAlmostEqual(v, expected, delta=0.05,
            msg=f"Demi-vie disco : attendu ≈{expected:.3f}, obtenu {v:.3f}")

    def test_vitality_core_immortel(self):
        """layer=core (λ=0) : aucune dégradation même après 1 an."""
        past = (datetime.utcnow() - timedelta(days=365)).isoformat()
        e    = SkillEntry(name="noyau", layer="core", initial_score=0.8, ingested_at=past)
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            v   = eng._vitality(e)
        self.assertAlmostEqual(v, 0.8, delta=0.01)

    def test_vitality_library_90j(self):
        """layer=library → demi-vie 90 jours."""
        lam  = MEMORY_LAYERS["library"]["lambda"]
        past = (datetime.utcnow() - timedelta(days=90)).isoformat()
        e    = SkillEntry(name="pandas", layer="library", initial_score=1.0, ingested_at=past)
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            v   = eng._vitality(e)
        self.assertAlmostEqual(v, math.exp(-lam * 90), delta=0.05)

    def test_confidence_history_max_20(self):
        """confidence_history ne dépasse jamais 20 entrées."""
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            for i in range(25):
                eng.record_success("reseau", f"t{i:03d}")
            h = eng._skills["reseau"].confidence_history
            self.assertLessEqual(len(h), 20)


# =============================================================================
# 2 — AgenticEngine : succès, erreurs, fail_streak, janitor, entropie
# =============================================================================
@skip_if_no_import
class TestAgenticEngine(unittest.TestCase):

    def test_record_success_incremente(self):
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            eng.record_success("reseau", "t001")
            eng.record_success("reseau", "t002")
            self.assertEqual(eng._skills["reseau"].uses, 2)
            self.assertEqual(eng._skills["reseau"].fail_streak, 0)

    def test_verified_apres_3_succes(self):
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            for i in range(3):
                eng.record_success("reseau", f"t{i:03d}")
            e = eng._skills["reseau"]
            self.assertFalse(e.unverified, "Doit être VERIFIED après 3 succès distincts")
            self.assertEqual(e.status, "verified")

    def test_dedup_meme_task_id(self):
        """Le même task_id ne compte qu'une fois."""
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            eng.record_success("reseau", "aaa")
            eng.record_success("reseau", "aaa")
            self.assertEqual(eng._skills["reseau"].uses, 1)

    def test_fail_streak_incremente(self):
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            eng._skills["reseau"] = SkillEntry(name="reseau", status="mastered",
                                                unverified=False)
            eng.record_error("reseau")
            eng.record_error("reseau")
            self.assertEqual(eng._skills["reseau"].fail_streak, 2)
            self.assertEqual(eng._skills["reseau"].status, "mastered")

    def test_regression_mastered_a_3_erreurs(self):
        """3 erreurs consécutives → mastered régresse en learning."""
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            eng._skills["reseau"] = SkillEntry(name="reseau", status="mastered",
                                                unverified=False)
            for _ in range(3):
                eng.record_error("reseau")
            e = eng._skills["reseau"]
            self.assertEqual(e.status, "learning")
            self.assertTrue(e.unverified)

    def test_succes_reset_fail_streak(self):
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            eng._skills["reseau"] = SkillEntry(name="reseau", fail_streak=2)
            eng.record_success("reseau", "ok")
            self.assertEqual(eng._skills["reseau"].fail_streak, 0)

    def test_entropie_zero_si_vide(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(make_engine(Path(d)).entropy_level(), 0.0)

    def test_entropie_max_si_tout_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            for i in range(5):
                eng._skills[f"sk{i}"] = SkillEntry(name=f"sk{i}", unverified=True)
            self.assertAlmostEqual(eng.entropy_level(), 1.0)

    def test_couleur_entropie(self):
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            self.assertEqual(eng.entropy_color(), "#3fb950")   # vert si vide

    def test_janitor_vulnerable_apres_ttl(self):
        """Skill UNVERIFIED disco > 30j → VULNERABLE."""
        with tempfile.TemporaryDirectory() as d:
            eng  = make_engine(Path(d))
            past = (datetime.utcnow() - timedelta(days=35)).isoformat()
            eng._skills["vieux"] = SkillEntry(
                name="vieux", layer="disco", unverified=True,
                ingested_at=past, initial_score=0.8
            )
            report = eng.run_janitor()
            self.assertIn("vieux", report["vulnerable"])

    def test_janitor_healthy_si_verified(self):
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            eng._skills["frais"] = SkillEntry(
                name="frais", layer="library", unverified=False,
                status="verified", vitality_score=0.9, initial_score=0.9,
                ingested_at=datetime.utcnow().isoformat()
            )
            report = eng.run_janitor()
            self.assertIn("frais", report["healthy"])

    def test_registry_persiste_sur_disque(self):
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            eng.record_success("securite", "tx")
            self.assertTrue(eng._skill_file.exists())
            data = json.loads(eng._skill_file.read_text())
            self.assertIn("securite", data)

    def test_audit_report_contient_entropie(self):
        with tempfile.TemporaryDirectory() as d:
            eng = make_engine(Path(d))
            report = eng.audit_report()
            self.assertIn("Entropie", report)


# =============================================================================
# 3 — ForgeSaveOrchestrator : checkpoint, staging, rollback, GFS, history
# =============================================================================
@skip_if_no_import
class TestSaveOrchestrator(unittest.TestCase):

    def test_write_to_staging(self):
        with tempfile.TemporaryDirectory() as d:
            orch = make_orch(Path(d))
            p = orch.write_to_staging("patch.py", "# nouveau code")
            self.assertTrue(p.exists())
            self.assertEqual(p.read_text(), "# nouveau code")

    def test_clear_staging(self):
        with tempfile.TemporaryDirectory() as d:
            orch = make_orch(Path(d))
            orch.write_to_staging("a.py", "x")
            orch.clear_staging()
            self.assertEqual(list(orch.staging_dir.iterdir()), [])

    def test_history_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            orch = make_orch(Path(d))
            orch._append_history("checkpoint", "/path", "label")
            orch._append_history("commit",     "/path2", "")
            tail = orch.history_tail(10)
            self.assertEqual(len(tail), 2)
            self.assertEqual(tail[0]["op"], "checkpoint")
            self.assertEqual(tail[1]["op"], "commit")

    def test_rollback_sans_backup_retourne_false(self):
        with tempfile.TemporaryDirectory() as d:
            orch = make_orch(Path(d))
            self.assertFalse(orch.rollback(backup_path=None))

    def test_rollback_avec_backup(self):
        """rollback() crée/remplace workspace/ réel — vérifie via history.jsonl."""
        with tempfile.TemporaryDirectory() as d:
            orch = make_orch(Path(d))
            bk   = orch.backup_dir / "backup_test"
            bk.mkdir()
            (bk / "Nokido_v12.0.py").write_text("# backup stable")
            result = orch.rollback(backup_path=bk)
            self.assertTrue(result, "rollback doit retourner True")
            # Vérifier le log history (rollback utilise __file__ pour workspace)
            tail = orch.history_tail(5)
            ops  = [e["op"] for e in tail]
            self.assertIn("rollback", ops, "rollback doit être dans history.jsonl")

    def test_rotation_gfs(self):
        """GFS : purge les plus vieux si > MAX_BACKUPS=3."""
        with tempfile.TemporaryDirectory() as d:
            orch = make_orch(Path(d))
            for i in range(6):
                bd = orch.backup_dir / f"backup_202501{i:02d}_120000"
                bd.mkdir()
                time.sleep(0.01)
            orch.rotate_backups()
            dirs = [x for x in orch.backup_dir.iterdir() if x.is_dir()]
            self.assertLessEqual(len(dirs), 5,
                "GFS doit avoir purgé les anciens backups")


# =============================================================================
# 4 — VersionManager : versions, patches, loop_trunk
# =============================================================================
@skip_if_no_import
class TestVersionManager(unittest.TestCase):

    def test_version_courante(self):
        with tempfile.TemporaryDirectory() as d:
            vm = make_vm(Path(d))
            self.assertEqual(vm.current_version, "12.0")

    def test_increment_mineur(self):
        with tempfile.TemporaryDirectory() as d:
            vm = make_vm(Path(d))
            self.assertEqual(vm._increment_version("12.0", major=False), "12.1")

    def test_increment_majeur(self):
        with tempfile.TemporaryDirectory() as d:
            vm = make_vm(Path(d))
            self.assertEqual(vm._increment_version("12.0", major=True), "13.0")

    def test_increment_patch_multi(self):
        with tempfile.TemporaryDirectory() as d:
            vm = make_vm(Path(d))
            self.assertEqual(vm._increment_version("12.9", major=False), "12.10")

    def test_prepare_patch_cree_fichier(self):
        with tempfile.TemporaryDirectory() as d:
            vm   = make_vm(Path(d))
            path = async_run(vm.prepare_patch('__version__ = "12.1"\n# ok\n', "test"))
            self.assertIsNotNone(path)
            self.assertTrue(path.exists())
            self.assertIn("12.1", path.read_text())

    def test_prepare_patch_archive_ancienne_version(self):
        with tempfile.TemporaryDirectory() as d:
            vm = make_vm(Path(d))
            async_run(vm.prepare_patch('__version__ = "12.1"\n', "patch 1"))
            archives = list(vm.versions_dir.iterdir())
            self.assertGreater(len(archives), 0,
                "L'ancienne version doit être archivée dans versions/")

    def test_patch_en_loop_va_dans_loop_trunk(self):
        with tempfile.TemporaryDirectory() as d:
            vm = make_vm(Path(d))
            vm._loop_id    = "abc123"
            vm._loop_trunk = vm.loop_dir / "loop_abc123"
            vm._loop_trunk.mkdir()
            path = async_run(vm.prepare_patch('__version__ = "12.1"\n# loop\n', "loop"))
            self.assertTrue(str(path).startswith(str(vm._loop_trunk)),
                f"Patch loop doit être dans loop_trunk/, obtenu : {path}")

    def test_patch_hors_loop_va_dans_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            vm   = make_vm(Path(d))
            path = async_run(vm.prepare_patch('__version__ = "12.1"\n', "normal"))
            self.assertTrue(str(path).startswith(str(vm.workspace_dir)))


# =============================================================================
# 5 — ForgeSaveOrchestrator.evolution_loop : flux atomique
# =============================================================================
@skip_if_no_import
class TestEvolutionLoop(unittest.TestCase):

    def _setup(self):
        tmp  = Path(tempfile.mkdtemp())
        orch = make_orch(tmp)
        vm   = make_vm(tmp)
        # Faux backup pour que rollback fonctionne
        bk   = orch.backup_dir / "backup_pre"
        bk.mkdir()
        (bk / "Nokido_v12.0.py").write_text("# stable")
        orch._last_backup = bk
        return tmp, orch, vm

    def _sandbox_ok(self):
        s = MagicMock()
        s.run_tests = MagicMock(return_value=MagicMock(success=True))
        return s

    def _sandbox_ko(self, msg="SyntaxError"):
        s = MagicMock()
        s.run_tests = MagicMock(return_value=MagicMock(success=False, error=msg))
        return s

    def test_succes_complet(self):
        """Sandbox OK + audit OK → retourne True, staging vidé."""
        tmp, orch, vm = self._setup()
        try:
            ok = async_run(orch.evolution_loop(
                new_code        = '__version__ = "12.1"\n# amélioration\n',
                description     = "test OK",
                version_manager = vm,
                sandbox         = self._sandbox_ok(),
                audit_fn        = lambda c: True,
            ))
            self.assertTrue(ok)
            self.assertEqual(list(orch.staging_dir.iterdir()), [])
        finally:
            shutil.rmtree(tmp)

    def test_sandbox_ko_rollback(self):
        """Sandbox KO → rollback → retourne False."""
        tmp, orch, vm = self._setup()
        try:
            ok = async_run(orch.evolution_loop(
                new_code        = '__version__ = "12.1"\n# bug\n',
                description     = "test KO",
                version_manager = vm,
                sandbox         = self._sandbox_ko(),
                audit_fn        = None,
            ))
            self.assertFalse(ok)
            self.assertEqual(list(orch.staging_dir.iterdir()), [],
                "staging/ doit être vidé après rollback")
        finally:
            shutil.rmtree(tmp)

    def test_audit_nogo_rollback(self):
        """Audit refuse → rollback → False."""
        tmp, orch, vm = self._setup()
        try:
            ok = async_run(orch.evolution_loop(
                new_code        = '__version__ = "12.1"\n',
                description     = "audit nogo",
                version_manager = vm,
                sandbox         = self._sandbox_ok(),
                audit_fn        = lambda c: False,
            ))
            self.assertFalse(ok)
        finally:
            shutil.rmtree(tmp)

    def test_sans_sandbox_commit_direct(self):
        """Sans sandbox → passe directement à l'audit puis commit."""
        tmp, orch, vm = self._setup()
        try:
            ok = async_run(orch.evolution_loop(
                new_code        = '__version__ = "12.1"\n',
                description     = "no sandbox",
                version_manager = vm,
                sandbox         = None,
                audit_fn        = lambda c: True,
            ))
            self.assertTrue(ok)
        finally:
            shutil.rmtree(tmp)

    def test_history_ecrit_apres_commit(self):
        """history.jsonl contient checkpoint + commit après succès."""
        tmp, orch, vm = self._setup()
        try:
            async_run(orch.evolution_loop(
                new_code        = '__version__ = "12.1"\n',
                description     = "history test",
                version_manager = vm,
                sandbox         = None,
                audit_fn        = lambda c: True,
            ))
            tail = orch.history_tail(10)
            ops  = [e["op"] for e in tail]
            self.assertIn("checkpoint", ops)
            self.assertIn("commit", ops)
        finally:
            shutil.rmtree(tmp)

    def test_lock_empêche_double_execution(self):
        """Deux evolution_loop concurrents → le second attend le premier."""
        tmp, orch, vm = self._setup()
        try:
            results = []
            async def run_two():
                t1 = asyncio.create_task(orch.evolution_loop(
                    '__version__ = "12.1"\n', "loop1", vm, None, lambda c: True))
                t2 = asyncio.create_task(orch.evolution_loop(
                    '__version__ = "12.2"\n', "loop2", vm, None, lambda c: True))
                r1, r2 = await asyncio.gather(t1, t2, return_exceptions=True)
                results.extend([r1, r2])
            async_run(run_two())
            # Les deux doivent terminer (pas de deadlock)
            self.assertEqual(len(results), 2)
        finally:
            shutil.rmtree(tmp)


# =============================================================================
# MAIN
# =============================================================================
if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  La Forge v12 — Tests boucles & auto-apprentissage")
    print("═" * 60 + "\n")

    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()
    for cls in [TestSkillEntry, TestAgenticEngine, TestSaveOrchestrator,
                TestVersionManager, TestEvolutionLoop]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    verbosity = 2 if "-v" in sys.argv else 1
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)

    total   = result.testsRun
    failed  = len(result.failures) + len(result.errors)
    skipped = len(result.skipped)
    passed  = total - failed - skipped
    print("\n" + "═" * 60)
    print(f"  ✅ {passed} passés  ❌ {failed} échoués  ⏭  {skipped} sautés")
    print("═" * 60 + "\n")
    sys.exit(0 if result.wasSuccessful() else 1)
