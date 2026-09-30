# -*- coding: utf-8 -*-
"""NR — sonde d'inference REELLE Ollama (OllamaBridge.is_inference_alive).

Mesure 2026-08-19 : runner llama-server MANQUANT -> api/tags listait 16 modeles,
tout /api/chat rendait 500. api/tags (liste) et api/ps (residents) ne pouvaient
pas le voir ; seul un vrai POST /api/chat le prouve. Tests HERMETIQUES : urlopen
et get_available_models monkeypatches, aucun reseau.
"""
import os
import sys
import time
import urllib.request

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.abspath(_ROOT))
sys.path.insert(0, os.path.abspath(os.path.join(_ROOT, "app")))

import forge_ollama_bridge as B  # noqa: E402


class _Rep:
    def __init__(self, payload):
        self._p = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._p


def _bridge():
    br = B.OllamaBridge.__new__(B.OllamaBridge)
    br.base_url = "http://x:11434"
    return br


def test_vrai_si_chat_rend_du_contenu(monkeypatch):
    br = _bridge()
    monkeypatch.setattr(br, "get_available_models", lambda: ["qwen2.5-coder:7b"])
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _Rep(b'{"message": {"content": "ok"}}'))
    assert br.is_inference_alive(ttl=0) is True


def test_faux_si_500(monkeypatch):
    br = _bridge()
    monkeypatch.setattr(br, "get_available_models", lambda: ["qwen"])

    def _boom(*a, **k):
        raise OSError("HTTP 500 (runner manquant)")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert br.is_inference_alive(ttl=0) is False


def test_faux_si_aucun_modele(monkeypatch):
    br = _bridge()
    monkeypatch.setattr(br, "get_available_models", lambda: [])
    # urlopen ne doit meme pas etre appele : pas de modele -> pas d'inference.
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("appel reseau interdit")))
    assert br.is_inference_alive(ttl=0) is False


def test_le_cache_evite_un_second_appel_reseau(monkeypatch):
    br = _bridge()
    br._inf_alive_cache = (time.monotonic(), True)

    def _interdit():
        raise AssertionError("get_available_models ne doit pas etre rappele (cache frais)")
    monkeypatch.setattr(br, "get_available_models", _interdit)
    assert br.is_inference_alive(ttl=9999) is True


def test_choisit_un_modele_non_embedding(monkeypatch):
    br = _bridge()
    monkeypatch.setattr(br, "get_available_models",
                        lambda: ["nomic-embed-text:latest", "qwen2.5-coder:7b"])
    vus = {}

    def _cap(req, timeout=0):
        import json
        vus["body"] = json.loads(req.data.decode())
        return _Rep(b'{"message": {"content": "x"}}')
    monkeypatch.setattr(urllib.request, "urlopen", _cap)
    br.is_inference_alive(ttl=0)
    assert vus["body"]["model"] == "qwen2.5-coder:7b"  # pas l'embedding
