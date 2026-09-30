import time
import pytest
from app import forge_endocrine_system as fes


@pytest.fixture(autouse=True)
def reset_endocrine_state():
    """Reset le rythme à NORMAL avant et après chaque test."""
    try:
        fes.set_rhythm("NORMAL", reason="test_setup", source="pytest")
    except Exception:
        pass
    yield
    try:
        fes.set_rhythm("NORMAL", reason="test_teardown", source="pytest")
    except Exception:
        pass


def test_default_normal_rhythm():
    status = fes.get_rhythm_status()
    assert status.rhythm == "NORMAL"
    assert status.delay_multiplier == 1.0
    assert not fes.should_pause_worker("forge_watch_agent", "background")
    assert not fes.should_pause_worker("rss_watcher", "background")


def test_set_conserve_rhythm():
    res = fes.set_rhythm("CONSERVE", ttl_s=1800, reason="dev_focus", source="pytest")
    assert res["rhythm"] == "CONSERVE"
    assert res["delay_multiplier"] == 4.0

    # En mode CONSERVE, les tâches de fond doivent être en pause
    assert fes.should_pause_worker("forge_watch_agent", "background")
    assert fes.should_pause_worker("rss_watcher", "background")
    assert fes.should_pause_worker("random_worker", "searxng")
    
    # Mais un watchdog vital ne l'est pas
    assert not fes.should_pause_worker("forge_token_watchdog", "vital")


def test_set_boost_rhythm():
    fes.set_rhythm("BOOST", ttl_s=600, reason="high_load", source="pytest")
    assert fes.get_rhythm() == "BOOST"
    assert fes.get_delay_multiplier("any") == 0.5
    assert not fes.should_pause_worker("forge_watch_agent", "background")


def test_rhythm_ttl_expiration():
    # Définir un TTL très court (ex: 1 seconde pour le test) via SQL ou en forçant age_s
    # On fixe un TTL de 60s (minimum imposé par set_rhythm), puis on modifie la date en BD
    fes.set_rhythm("CONSERVE", ttl_s=60, reason="test_ttl", source="pytest")
    
    conn = fes._conn()
    # Reculer le timestamp set_at de 120 secondes dans la BD pour simuler l'expiration
    conn.execute("UPDATE endocrine_rhythm_state SET set_at = datetime('now', '-120 seconds') WHERE id = 1")
    conn.commit()
    conn.close()

    # À la lecture, le système doit détecter l'expiration et revenir à NORMAL
    status = fes.get_rhythm_status()
    assert status.rhythm == "NORMAL"
    assert not status.expired  # Le revert remet à un état NORMAL propre non expiré


def test_invalid_rhythm():
    with pytest.raises(ValueError):
        fes.set_rhythm("HYPER_SPEED")
