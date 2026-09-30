"""forge_key_rotation — pool multi-clés + santé + skip-403 + rotation. Logique pure, sans vault."""
import importlib
import time

kr = importlib.import_module("forge_key_rotation")


def test_usable_logic():
    assert kr._usable(None) is True                                  # inconnue = optimiste
    assert kr._usable({"status": "ok"}) is True
    assert kr._usable({"status": "bad"}) is False                    # clé morte
    assert kr._usable({"status": "quota", "ts": time.time()}) is False   # quota récent
    assert kr._usable({"status": "quota", "ts": 0}) is True          # quota expiré -> réarmé


def test_resolve_rotates_and_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(kr, "_HEALTH", tmp_path / "h.json")
    monkeypatch.setattr(kr, "_pool", lambda e: [("GROQ_API_KEY", "AAAA111"), ("GROQ_API_KEY_2", "BBBB222")])
    # tout inconnu -> 1re clé, managed (pool>1)
    managed, key = kr.resolve("GROQ_API_KEY")
    assert managed is True and key == "AAAA111"
    # 1re clé 403 -> rotation vers la 2e
    kr.mark_http("GROQ_API_KEY", "AAAA111", 403)
    _m, key = kr.resolve("GROQ_API_KEY")
    assert key == "BBBB222"
    # les 2 mortes -> None (skip provider)
    kr.mark_http("GROQ_API_KEY", "BBBB222", 401)
    managed, key = kr.resolve("GROQ_API_KEY")
    assert managed is True and key is None


def test_resolve_unmanaged_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(kr, "_HEALTH", tmp_path / "h.json")
    monkeypatch.setattr(kr, "_pool", lambda e: [("X_API_KEY", "SOLO123")])
    managed, key = kr.resolve("X_API_KEY")
    assert managed is False and key == "SOLO123"   # 1 clé + 0 santé = legacy (non géré)


def test_mark_http_quota_then_expire(tmp_path, monkeypatch):
    monkeypatch.setattr(kr, "_HEALTH", tmp_path / "h.json")
    monkeypatch.setattr(kr, "_pool", lambda e: [("Q_API_KEY", "Q123456")])
    kr.mark_http("Q_API_KEY", "Q123456", 429)        # quota
    _m, key = kr.resolve("Q_API_KEY")
    assert key is None                                # quota récent -> skip
    monkeypatch.setattr(kr, "_QUOTA_TTL", 0)          # TTL expiré
    _m, key = kr.resolve("Q_API_KEY")
    assert key == "Q123456"                           # réarmé
