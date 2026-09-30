"""Scanner anatomique d'embolies : mapping points→systèmes + checks fail-safe."""
import importlib

es = importlib.import_module("forge_embolie_scanner")


def test_point_mapping_coverage():
    for pt, sysn in es.POINT_TO_SYSTEM.items():
        assert sysn in es.SYSTEMS, (pt, sysn)
    for p in ("postal_queue", "provider_health", "hooks_integrity"):
        assert p in es.POINT_TO_SYSTEM  # les 3 points neufs sont positionnés


def test_new_checks_failsafe():
    for fn in (es._check_postal_queue, es._check_provider_health, es._check_hooks_integrity):
        r = fn()
        assert isinstance(r, dict) and "status" in r and "detail" in r
        assert r["status"] in ("clear", "warn", "embolie", "unknown")


def test_hooks_integrity_detects_utf8():
    # les 2 hooks AfterModel ont été forcés UTF-8 ce tour -> le point de contrôle doit être clear
    assert es._check_hooks_integrity()["status"] == "clear"
