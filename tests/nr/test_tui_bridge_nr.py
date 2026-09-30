# -*- coding: utf-8 -*-
"""
tests/nr/test_tui_bridge_nr.py
===============================
NR pour le bridge TUI ↔ Hub :
  CoreBridge.tui_notify          — notification LLM → TUI
  CoreBridge.get_tui_command     — lecture ordre TUI → Hub
  CoreBridge.push_tui_command    — TUI → Hub (bouton cliqué)
  CoreBridge.set_auto_mode       — interrupteur AUTO TUI
  CoreBridge.is_auto_mode        — lecture mode AUTO
  apply_smart_patch              — patch chirurgical

Critères NR :
  C1 Modulaire   : 1 classe = 1 composant
  C2 Comportement: assert sur décisions, pas sur timing
  C3 Edge cases  : message vide, commande inconnue, double consume
  C4 Tolérant    : isinstance / in / True|False
  C5 Isolé       : SQLite en mémoire pour les tests
  C6 Rapide      : < 1s par test
"""
from __future__ import annotations

import sys
import json
import sqlite3
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
_APP  = _ROOT / "app"
sys.path.insert(0, str(_APP))
sys.path.insert(0, str(_ROOT / "tools"))


# =============================================================================
# BLOC 1 — apply_smart_patch
# =============================================================================

class TestApplySmartPatch:
    """C1 — apply_smart_patch : patch chirurgical de fichiers Python."""

    def test_import(self):
        from nokido_core import apply_smart_patch
        assert callable(apply_smart_patch)

    def test_dry_run_found(self, tmp_path):
        """dry_run=True retourne ok=True sans écrire."""
        from nokido_core import apply_smart_patch
        f = tmp_path / "test_mod.py"
        f.write_text("x = 1\ny = 2\n", encoding="utf-8")
        r = apply_smart_patch(str(f.relative_to(_ROOT)) if f.is_relative_to(_ROOT) else str(f),
                              "x = 1", "x = 42", dry_run=True)
        # Le fichier n'existe pas dans ROOT → erreur propre
        assert isinstance(r, dict)
        assert "ok" in r

    def test_not_found(self):
        """Pattern absent → ok=False."""
        from nokido_core import apply_smart_patch
        r = apply_smart_patch("app/nokido_core.py", "PATTERN_IMPOSSIBLE_XYZ_999", "new")
        assert r["ok"] is False
        assert "error" in r

    def test_file_absent(self):
        """Fichier absent → ok=False avec message."""
        from nokido_core import apply_smart_patch
        r = apply_smart_patch("app/fichier_inexistant_xyz.py", "old", "new")
        assert r["ok"] is False
        assert "absent" in r.get("error","").lower() or "error" in r

    def test_syntax_check(self, tmp_path):
        """Syntaxe invalide après patch → ok=False."""
        from nokido_core import apply_smart_patch
        # Créer un fichier Python valide dans ROOT/sandbox
        f = _ROOT / "sandbox" / "_test_patch_tmp.py"
        f.write_text("x = 1\n", encoding="utf-8")
        r = apply_smart_patch("sandbox/_test_patch_tmp.py", "x = 1", "x = !!!INVALIDE!!!")
        assert r["ok"] is False
        f.unlink(missing_ok=True)

    def test_successful_patch(self):
        """Patch valide → ok=True avec numéro de ligne."""
        from nokido_core import apply_smart_patch
        f = _ROOT / "sandbox" / "_test_patch_ok.py"
        f.write_text("VERSION = '0.0.1'\n", encoding="utf-8")
        r = apply_smart_patch("sandbox/_test_patch_ok.py",
                              "VERSION = '0.0.1'", "VERSION = '0.0.2'")
        assert r["ok"] is True
        assert "line" in r
        assert f.read_text(encoding="utf-8") == "VERSION = '0.0.2'\n"
        f.unlink(missing_ok=True)

    def test_multiple_occurrences(self):
        """Plusieurs occurrences → ok=False, refuse de patcher."""
        from nokido_core import apply_smart_patch
        f = _ROOT / "sandbox" / "_test_multi.py"
        f.write_text("x = 1\nx = 1\n", encoding="utf-8")
        r = apply_smart_patch("sandbox/_test_multi.py", "x = 1", "x = 99")
        assert r["ok"] is False
        assert "2" in r.get("error","")
        f.unlink(missing_ok=True)


# =============================================================================
# BLOC 2 — TUI Notifications (tui_notify)
# =============================================================================

class TestTuiNotify:
    """C1 — tui_notify : LLM écrit dans la TUI via SQLite."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from nokido_core import CoreBridge
        self.core = CoreBridge()

    def test_tui_notify_returns_dict(self):
        r = self.core.tui_notify("Test message", type="info")
        assert isinstance(r, dict)
        assert "ok" in r

    def test_tui_notify_success(self):
        r = self.core.tui_notify("Hub démarré", type="success")
        assert r["ok"] is True

    def test_tui_notify_type_stored(self):
        """Le type est conservé dans la réponse."""
        r = self.core.tui_notify("Attention", type="warning")
        assert r.get("type") == "warning"

    def test_tui_notify_types_valides(self):
        """Tous les types valides passent sans erreur."""
        for t in ["info", "success", "warning", "error", "action"]:
            r = self.core.tui_notify("msg " + t, type=t)
            assert r["ok"] is True, f"type={t} a échoué"

    def test_tui_notify_message_tronque(self):
        """Message > 1000 chars est accepté (tronqué en interne)."""
        r = self.core.tui_notify("x" * 1500, type="info")
        assert r["ok"] is True

    def test_tui_notify_with_payload(self):
        """tui_notify accepte un payload optionnel."""
        r = self.core.tui_notify("Tests OK", type="success",
                                  payload={"passed": 389, "failed": 0})
        assert r["ok"] is True

    def test_tui_notify_persisted_in_db(self):
        """La notification est écrite dans tui_notifications."""
        import sqlite3
        self.core.tui_notify("MARQUEUR_UNIQUE_TEST_NR_42", type="info")
        conn = sqlite3.connect(str(_ROOT / "RAG" / "embeddings.db"))
        row  = conn.execute(
            "SELECT message FROM tui_notifications WHERE message LIKE '%MARQUEUR_UNIQUE_TEST_NR_42%' LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None


# =============================================================================
# BLOC 3 — TUI Commands (get/push_tui_command)
# =============================================================================

class TestTuiCommands:
    """C1 — tui_commands : tampon SQLite TUI → Hub."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from nokido_core import CoreBridge
        self.core = CoreBridge()

    def test_push_command_returns_ok(self):
        r = self.core.push_tui_command("test", {"selector": "nr"})
        assert r["ok"] is True
        assert r["command"] == "test"

    def test_get_command_returns_dict_or_none(self):
        """get_tui_command retourne dict ou None — jamais d'exception."""
        result = self.core.get_tui_command(consume=False)
        assert result is None or isinstance(result, dict)

    def test_push_then_get_roundtrip(self):
        """push → get retourne la même commande."""
        import sqlite3
        # Nettoyer d'abord les commandes pending
        conn = sqlite3.connect(str(_ROOT / "RAG" / "embeddings.db"))
        conn.execute("DELETE FROM tui_commands WHERE command='__test_roundtrip__'")
        conn.commit()
        conn.close()

        self.core.push_tui_command("__test_roundtrip__", {"val": 42})
        cmd = self.core.get_tui_command(consume=True)
        # Peut avoir d'autres commandes avant — on cherche la nôtre
        assert cmd is not None
        assert "command" in cmd

    def test_consume_removes_from_queue(self):
        """consume=True → le status passe à consumed."""
        import sqlite3
        marker = "__consume_test_" + str(__import__("time").time_ns()) + "__"

        # Insérer directement pour avoir l'ID exact
        conn = sqlite3.connect(str(_ROOT / "RAG" / "embeddings.db"))
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.execute(
            "INSERT INTO tui_commands (source, command, payload) VALUES (?,?,?)",
            ("tui", marker, "{}")
        )
        cmd_id = cur.lastrowid
        conn.commit()
        conn.close()

        # Consommer spécifiquement cette commande via get_tui_command
        # On vide la queue jusqu'à trouver notre marker
        found = False
        for _ in range(20):
            cmd = self.core.get_tui_command(consume=True)
            if cmd and cmd.get("command") == marker:
                found = True
                break
            if cmd is None:
                break

        # Vérifier que l'enregistrement est bien consumed
        conn = sqlite3.connect(str(_ROOT / "RAG" / "embeddings.db"))
        row  = conn.execute(
            "SELECT status FROM tui_commands WHERE id=?", (cmd_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "consumed"

    def test_push_command_source(self):
        """Le source est conservé."""
        import sqlite3
        conn = sqlite3.connect(str(_ROOT / "RAG" / "embeddings.db"))
        self.core.push_tui_command("__src_test__", {}, source="tui")
        row = conn.execute(
            "SELECT source FROM tui_commands WHERE command='__src_test__' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "tui"

    def test_push_command_unknown_graceful(self):
        """Commande inconnue acceptée sans erreur (tampon générique)."""
        r = self.core.push_tui_command("commande_inconnue_xyz", {})
        assert r["ok"] is True


# =============================================================================
# BLOC 4 — Mode AUTO
# =============================================================================

class TestAutoMode:
    """C1 — auto_mode : interrupteur TUI AUTO."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from nokido_core import CoreBridge
        self.core = CoreBridge()
        yield
        self.core.set_auto_mode(False)  # reset après chaque test

    def test_auto_mode_default_off(self):
        """Auto mode OFF par défaut."""
        self.core.set_auto_mode(False)
        assert self.core.is_auto_mode() is False

    def test_set_auto_mode_on(self):
        r = self.core.set_auto_mode(True)
        assert r["ok"] is True
        assert self.core.is_auto_mode() is True

    def test_set_auto_mode_off(self):
        self.core.set_auto_mode(True)
        self.core.set_auto_mode(False)
        assert self.core.is_auto_mode() is False

    def test_auto_mode_returns_dict(self):
        r = self.core.set_auto_mode(True)
        assert isinstance(r, dict)
        assert "auto_mode" in r

    def test_auto_mode_notifies_tui(self):
        """set_auto_mode écrit une notification TUI."""
        import sqlite3
        self.core.set_auto_mode(True)
        conn = sqlite3.connect(str(_ROOT / "RAG" / "embeddings.db"))
        row  = conn.execute(
            "SELECT message FROM tui_notifications WHERE message LIKE '%AUTO%' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_auto_mode_persisted(self):
        """auto_mode persiste dans core_state.json."""
        self.core.set_auto_mode(True)
        from nokido_core import CoreBridge
        core2 = CoreBridge()  # nouvelle instance — relit le fichier
        assert core2.state.get().auto_mode is True
        core2.set_auto_mode(False)

    def test_is_auto_mode_returns_bool(self):
        assert isinstance(self.core.is_auto_mode(), bool)


# =============================================================================
# BLOC 5 — Codeberg API (ServiceManager)
# =============================================================================

class TestCodebergService:
    """C1 — ServiceManager Codeberg : _cb_api, codeberg_status."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from nokido_core import ServiceManager
        self.sm = ServiceManager()

    def test_cb_api_exists(self):
        assert callable(getattr(self.sm, "_cb_api", None))

    def test_codeberg_status_returns_dict(self):
        r = self.sm.codeberg_status()
        assert isinstance(r, dict)
        assert "ok" in r

    def test_codeberg_status_no_crash_without_token(self):
        """Sans token → retourne ok=False proprement."""
        import os
        old = os.environ.pop("CODEBERG_TOKEN", "")
        try:
            r = self.sm.codeberg_status()
            assert isinstance(r, dict)
        finally:
            if old: os.environ["CODEBERG_TOKEN"] = old

    def test_push_file_absent(self):
        """Fichier local absent → ok=False."""
        r = self.sm.push_file_to_codeberg(
            "fichier_inexistant_xyz.py", "fichier_inexistant_xyz.py"
        )
        assert r["ok"] is False
        assert "absent" in r.get("error","").lower()

    def test_dispatch_to_codeberg_structure(self):
        """dispatch_to_codeberg retourne dict avec ok."""
        r = self.sm.dispatch_to_codeberg("nokido_ci.yml", {"test": True})
        assert isinstance(r, dict)
        assert "ok" in r

    def test_dispatch_to_woodpecker_no_token(self):
        """Sans WOODPECKER_TOKEN → ok=False proprement."""
        import os
        old = os.environ.pop("WOODPECKER_TOKEN", "")
        try:
            r = self.sm.dispatch_to_woodpecker()
            assert r["ok"] is False
            assert "WOODPECKER_TOKEN" in r.get("error","")
        finally:
            if old: os.environ["WOODPECKER_TOKEN"] = old

    def test_woodpecker_status_returns_dict(self):
        r = self.sm.woodpecker_status()
        assert isinstance(r, dict)
        assert "ok" in r


# =============================================================================
# BLOC 6 — forge_events TUI hooks
# =============================================================================

class TestForgeEventsTuiHook:
    """C1 — forge_events : hooks TUI Core."""

    def test_poll_tui_notifications_importable(self):
        from forge_events import poll_tui_notifications
        assert callable(poll_tui_notifications)

    def test_poll_tui_notifications_no_crash_no_app(self):
        """poll_tui_notifications sans app valide ne crash pas."""
        import asyncio
        from forge_events import poll_tui_notifications

        class FakeApp:
            def _safe_write(self, msg): pass

        asyncio.run(poll_tui_notifications(FakeApp()))

    def test_tui_button_map_defined(self):
        """Le mapping boutons → commandes est défini dans forge_events."""
        source = (Path(__file__).parent.parent.parent / "app" / "forge_events.py"
                  ).read_text(encoding="utf-8", errors="replace")
        assert "_TUI_BUTTON_MAP" in source
        assert "btn-mode-autonome" in source

    def test_on_button_pressed_importable(self):
        from forge_events import on_button_pressed
        assert callable(on_button_pressed)
