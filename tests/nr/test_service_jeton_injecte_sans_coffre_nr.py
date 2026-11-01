"""NR 31/10 (COF-1) -- un SERVICE qui a recu un jeton court de son lanceur ne lit plus le coffre au chargement.

Mesure journal du coffre 07:46 -> 08:13 : NokidoRSSWatcher (compte LaForgeSbxOnline) lit FORGE_TOKEN_SERVICES via
forge_hub_client a l'IMPORT (_TOKEN resolu au chargement) et FORGE_TOKEN_RSS_WATCHER via forge_agent_credential. Deux
causes : (1) services.toml declarait NOKIDO_IDENTITE = "SERVICES" alors que le service demande RSS_WATCHER -- l'injection
ne correspondait pas ; (2) le client resolvait un jeton du coffre au chargement meme quand le lanceur en avait injecte un.
"""
from __future__ import annotations

from nokido_agent.app import forge_hub_client as HC


def test_injection_du_lanceur_pas_de_lecture_au_chargement(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("le coffre a ete lu")
    monkeypatch.setattr(HC, "_resoudre_jeton", interdit)
    env = {"NOKIDO_JETON_COURT": "x", "NOKIDO_IDENTITE": "RSS_WATCHER"}
    assert HC._resolution_au_chargement(env) == ("", "injecte_lanceur")


def test_sans_injection_comportement_d_avant(monkeypatch):
    monkeypatch.setattr(HC, "_resoudre_jeton", lambda agent: ("t", "coffre:FORGE_TOKEN_SERVICES"))
    monkeypatch.setattr(HC, "_echange_arme", lambda: False)
    assert HC._resolution_au_chargement({}) == ("t", "coffre:FORGE_TOKEN_SERVICES")


def test_client_de_l_identite_injectee_ne_lit_pas_le_coffre(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("le coffre a ete lu")
    monkeypatch.setattr(HC, "_resoudre_jeton", interdit)
    monkeypatch.setenv("NOKIDO_IDENTITE", "RSS_WATCHER")
    monkeypatch.setenv("NOKIDO_JETON_COURT", "x")
    c = HC.HubClient(agent="RSS_WATCHER")
    assert c.token_src == "injecte_lanceur"


def test_repli_malgre_identite_declaree_se_dit(monkeypatch, caplog):
    """31/10 08:56:32 : NokidoRSSWatcher, demarre AVEC un jeton RSS_WATCHER injecte (journal du lanceur), a quand meme lu
    FORGE_TOKEN_SERVICES au chargement -- cause ILLISIBLE. Le repli sur le coffre alors qu'une identite injectee est
    declaree s'ECRIT avec ses raisons (noms seulement) : la prochaine occurrence sera lisible."""
    import logging
    monkeypatch.setattr(HC, "_resoudre_jeton", lambda agent: ("t", "coffre:FORGE_TOKEN_SERVICES"))
    monkeypatch.setattr(HC, "_echange_arme", lambda: False)
    with caplog.at_level(logging.WARNING):
        HC._resolution_au_chargement({"NOKIDO_IDENTITE": "RSS_WATCHER"})
    txt = caplog.text
    assert "RSS_WATCHER" in txt and "jeton_env=False" in txt and "injectes=" in txt


def test_ecart_d_identite_garde_le_chemin_d_avant(monkeypatch):
    """Injection au nom d'une AUTRE identite : on ne la prete pas -- chemin d'avant, inchange."""
    monkeypatch.setattr(HC, "_resoudre_jeton", lambda agent: ("t", "coffre:FORGE_TOKEN_%s" % agent))
    monkeypatch.setenv("NOKIDO_IDENTITE", "SERVICES")
    monkeypatch.setenv("NOKIDO_JETON_COURT", "x")
    monkeypatch.delenv("NOKIDO_JOB_SUBJECT_TOKEN", raising=False)
    c = HC.HubClient(agent="RSS_WATCHER")
    assert c.token_src == "coffre:FORGE_TOKEN_RSS_WATCHER"
