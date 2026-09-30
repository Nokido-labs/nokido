# -*- coding: utf-8 -*-
"""Tests unitaires pour la garde extractive du hook topics de forge_biblio_worker."""

import logging
from app.forge_biblio_worker import _extract_topics

def test_extract_topics_extractive_pass_and_reject(caplog, monkeypatch):
    entry = {
        "id": "blr_test123",
        "title": "Étude du canari et du comportement des oiseaux",
        "description": "Analyse bioacoustique et dynamique des canaris en cage.",
    }
    search_results = [
        {"title": "Ignored snippet", "content": "Canadian army troops deployed in northern regions."}
    ]

    # Mock de l'appel LLM HTTP
    class DummyResp:
        def read(self):
            return b'{"response": "{\\\"topics\\\": [{\\\"name\\\": \\\"canari\\\", \\\"weight\\\": 0.9}, {\\\"name\\\": \\\"canadian-army\\\", \\\"weight\\\": 0.8}, {\\\"name\\\": \\\"bible\\\", \\\"weight\\\": 0.5}]}"}'
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=30: DummyResp())

    with caplog.at_level(logging.INFO):
        topics = _extract_topics(entry, search_results)

    topic_names = [t[0] for t in topics]

    # Validation sens 1: Topic présent dans title+desc est conservé (normalisé)
    assert "canari" in topic_names

    # Validation sens 2: Topics absents de title+desc (même si présents dans snippets) sont rejetés
    assert "canadian-army" not in topic_names
    assert "bible" not in topic_names

    # Validation journalisation du rejet (JAMAIS un rejet muet)
    assert "topic halluciné rejeté: 'canadian-army'" in caplog.text
    assert "topic halluciné rejeté: 'bible'" in caplog.text
