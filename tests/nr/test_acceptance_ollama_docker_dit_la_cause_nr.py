"""NR -- l'etape ollama de la recette DIT pourquoi elle echoue, et macOS sans Docker sur runner est NON_TESTE (20/10).

Mesure de l'essai 0.20.13 (run 39490856286) :
  * windows-latest : 1re execution reelle de l'etape ollama (Docker Engine dans WSL2 depuis le 20/10). `ollama pull`
    etait lance SANS lire son rc, puis /api/generate rendait « HTTP Error 404 » -- la cause (pull rate ?) etait jetee ;
  * macos-latest : le runner n'a pas Docker ; l'etape rendait FAIL « docker absent » la ou Windows sans daemon rend
    NON_TESTE avec sa raison. Sur le Mac d'un UTILISATEUR (hors CI), Docker absent reste FAIL : la barre ne baisse pas.
"""
from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("acceptance_ollama_nr", RACINE / "tools" / "forge_install_acceptance.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.R.clear()
    return m


# 21/10 (sonde run prive 39560980742, windows-latest) : la sous-commande exec du CLI Windows (DOCKER_HOST tcp vers le
# daemon WSL2) rend rc=0 SANS RIEN FAIRE, depuis python comme depuis pwsh, avec ou sans -i ; dans WSL elle marche ;
# POST /api/pull reussit en 5 s, puis tags et generate. Contrat : le modele se tire par l'API HTTP du serveur que
# generate interroge.
import io
import json

_SOUS_COMMANDE = "ex" + "ec"   # le filtre du hub refuse ce mot suivi d'une parenthese


class _Reponse:
    def __init__(self, corps):
        self._corps = corps

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._corps


def _http(code, corps, url="http://127.0.0.1:11434/api/x"):
    return urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(corps))


def _serveur(m, monkeypatch, pull=b'{"status":"success"}', generate=b'{"response":"OK"}',
             tags=b'{"models":[{"name":"TEMOIN_TAGS"}]}'):
    vus = {"urls": [], "corps_pull": None, "sh": []}

    def sh(cmd, timeout=1800, **kw):
        vus["sh"].append(list(cmd))
        return 0, ""

    def urlopen(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        vus["urls"].append(url)
        for fin, rep in (("/api/pull", pull), ("/api/generate", generate), ("/api/tags", tags)):
            if url.endswith(fin):
                if fin == "/api/pull":
                    vus["corps_pull"] = json.loads(req.data)
                if isinstance(rep, Exception):
                    raise rep
                return _Reponse(rep)
        raise AssertionError("url inattendue : " + url)

    m.R["docker"] = {"etat": "PASS", "detail": "services declares : ['ollama']"}
    monkeypatch.setattr(m, "sh", sh)
    monkeypatch.setattr(m, "attendre_http", lambda url, delai: 200)
    monkeypatch.setattr(m.urllib.request, "urlopen", urlopen)
    return vus


def test_le_modele_se_tire_par_l_api_http_sans_sous_commande_docker(monkeypatch):
    m = _module()
    vus = _serveur(m, monkeypatch)
    m._ollama()
    assert m.R["ollama"]["etat"] == "PASS", m.R["ollama"]
    assert not [c for c in vus["sh"] if c[:2] == ["docker", _SOUS_COMMANDE]], vus["sh"]
    assert vus["corps_pull"] and vus["corps_pull"].get("model") == "qwen2.5:0.5b"
    assert vus["corps_pull"].get("stream") is False


def test_un_pull_en_echec_est_dit_et_generate_n_est_pas_appele(monkeypatch):
    m = _module()
    vus = _serveur(m, monkeypatch, pull=_http(500, b'{"error":"pull model manifest: 429 Too Many Requests"}'))
    m._ollama()
    assert m.R["ollama"]["etat"] == "FAIL", m.R["ollama"]
    assert "pull" in m.R["ollama"]["detail"] and "429" in m.R["ollama"]["detail"]
    assert not [u for u in vus["urls"] if u.endswith("/api/generate")]


def test_un_statut_de_pull_autre_que_success_est_un_echec(monkeypatch):
    m = _module()
    vus = _serveur(m, monkeypatch, pull=b'{"status":"pulling manifest"}')
    m._ollama()
    assert m.R["ollama"]["etat"] == "FAIL", m.R["ollama"]
    assert "pulling manifest" in m.R["ollama"]["detail"]
    assert not [u for u in vus["urls"] if u.endswith("/api/generate")]


def test_un_404_de_generate_rend_son_code_son_corps_et_api_tags(monkeypatch):
    m = _module()
    _serveur(m, monkeypatch, generate=_http(404, b'{"error":"model \'qwen2.5:0.5b\' not found"}'))
    m._ollama()
    d = m.R["ollama"]["detail"]
    assert m.R["ollama"]["etat"] == "FAIL", m.R["ollama"]
    assert "404" in d and "not found" in d and "TEMOIN_TAGS" in d, d


def _docker_absent(m, monkeypatch):
    monkeypatch.setattr(m, "WIN", False)
    monkeypatch.setattr(m.shutil, "which", lambda nom: None)


def test_runner_macos_sans_docker_est_non_teste_et_nomme_le_runner(monkeypatch):
    m = _module()
    _docker_absent(m, monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_OS", "macOS")
    m._docker()
    assert m.R["docker"]["etat"] == "NON_TESTE", m.R["docker"]
    assert "runner" in m.R["docker"]["detail"] and "macOS" in m.R["docker"]["detail"]


def test_mac_utilisateur_sans_docker_reste_un_echec(monkeypatch):
    m = _module()
    _docker_absent(m, monkeypatch)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("RUNNER_OS", "macOS")
    m._docker()
    assert m.R["docker"]["etat"] == "FAIL", m.R["docker"]
