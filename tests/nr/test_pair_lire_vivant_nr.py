# -*- coding: utf-8 -*-
"""NR — un pair web lit le VIVANT de Nokido (owner 17/10 : « tout »), pas le dist public perime.

Mesure 17/10 : la relecture claude.ai des clotures R7/R8 a ete faite sur le dist PUBLIC 0.20.12 ; 12 objections
ont du etre contre-verifiees sur alpha. Contrat de `lire_vivant(client, chemin, page)` :
- ring du pair <= 2 (config/pairs_rings.json) ; ring INCONNU = refus DIT ;
- seulement un fichier SUIVI d'alpha : jamais non suivi, jamais hors depot, jamais `..` ni chemin absolu, et le
  confinement est verifie AVANT toute lecture git ;
- exclusions meme si suivi : coffre, .env, secrets, cles, .mcp.json, settings, RAG ;
- pages bornees (chaque reponse passe sous MAX_SORTIE) et sha COURT d'alpha (un sha de 40 hex serait redige par
  _EN_PLUS_DU_PARE_FEU) ;
- l'outil est expose par le serveur et passe par `rediger`, comme les autres.
"""
import importlib.util
import inspect
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SUIVIS = {
    "tools/forge_exemple.py": "def f():\n    return 1\n" * 400,   # > MAX_SORTIE : plusieurs pages
    "app/court.py": "X = 1\n",
    "Nokido.env": "A=1\n",
    "config/secrets_policy.json": "{}",
    ".mcp.json": "{}",
    "RAG/notes.md": "x",
    "keys/server.pem": "x",
    ".claude/settings.json": "{}",
}


def _charger(nom):
    spec = importlib.util.spec_from_file_location(nom, ROOT / "tools" / "forge_pair_mcp.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def pair(monkeypatch):
    m = _charger("forge_pair_mcp_nr_lire_vivant")
    lus = []

    def contenu(chemin):
        lus.append(chemin)
        return ("8a10f34da", SUIVIS[chemin]) if chemin in SUIVIS else None

    monkeypatch.setattr(m, "_ring_du_pair", lambda client: {"claude": 2, "intrus": 3}.get(client))
    monkeypatch.setattr(m, "_contenu_suivi", contenu)
    return m, lus


def test_un_fichier_suivi_se_lit_par_pages_avec_le_sha_court(pair):
    m, _lus = pair
    r = m.lire_vivant("claude", "tools/forge_exemple.py", 0)
    assert r["ok"] is True, r
    assert r["pages"] >= 2
    assert r["sha"] == "8a10f34da" and len(r["sha"]) < 40
    assert r["contenu"].startswith("def f()")
    for p in range(r["pages"]):
        page = m.lire_vivant("claude", "tools/forge_exemple.py", p)
        assert page["ok"] is True
        assert len(json.dumps(page, ensure_ascii=False)) <= m.MAX_SORTIE
    hors = m.lire_vivant("claude", "tools/forge_exemple.py", r["pages"])
    assert hors["ok"] is False and "borne" in hors["erreur"]


def test_ring_inconnu_ou_superieur_a_2_est_refuse_et_le_dit(pair):
    m, _lus = pair
    for client in ("anonyme", "intrus"):
        r = m.lire_vivant(client, "app/court.py", 0)
        assert r["ok"] is False and "ring" in r["erreur"].lower(), (client, r)


def test_un_fichier_non_suivi_est_refuse_et_le_dit(pair):
    m, _lus = pair
    r = m.lire_vivant("claude", "app/absent.py", 0)
    assert r["ok"] is False and "suivi" in r["erreur"].lower(), r


def test_traversee_et_chemin_absolu_refuses_avant_toute_lecture(pair):
    m, lus = pair
    for chemin in ("../x.py", "C:/Windows/win.ini", "/etc/passwd", "tools\\..\\x.py", "app/../../x.py", ""):
        r = m.lire_vivant("claude", chemin, 0)
        assert r["ok"] is False, (chemin, r)
    assert lus == [], "le confinement doit refuser AVANT de demander le contenu a git : %r" % lus


def test_les_exclusions_tombent_meme_quand_le_fichier_est_suivi(pair):
    m, _lus = pair
    for chemin in ("Nokido.env", "config/secrets_policy.json", ".mcp.json", "RAG/notes.md", "keys/server.pem",
                   ".claude/settings.json"):
        r = m.lire_vivant("claude", chemin, 0)
        assert r["ok"] is False and "exclu" in r["erreur"].lower(), (chemin, r)


def test_le_serveur_expose_lire_vivant_par_le_redacteur():
    m = _charger("forge_pair_mcp_nr_lire_vivant_srv")
    source = inspect.getsource(m.construire_serveur)
    assert 'name="lire_vivant"' in source
    assert '_au_nom_du_pair("lire_vivant"' in source


def test_le_vrai_seam_lit_alpha_et_rend_none_pour_un_absent():
    m = _charger("forge_pair_mcp_nr_lire_vivant_reel")
    res = m._contenu_suivi("tools/forge_pair_mcp.py")
    assert res is not None, "tools/forge_pair_mcp.py est suivi sur alpha"
    sha, texte = res
    assert 7 <= len(sha) < 40
    assert "def lire_annexe" in texte
    assert m._contenu_suivi("n_existe_pas/zzz_absent.py") is None
