# -*- coding: utf-8 -*-
"""Non-regression — une sonde ne condamne pas une cle sur un refus de BORD.

Mesure 2026-08-28 (cause trouvee par ANTIGRAVITY). `forge_endpoint_monitor.probe()`
n'envoyait pas de User-Agent : Cloudflare repondait **403**, et `_HTTP` traduit tout 403
en `bad_key/forbidden` avant d'appeler `forge_key_rotation.mark_http`. La cle SAINE
partait donc en quarantaine pour des heures, et le corps entier se retrouvait sans
provider — d'ou un « Tous providers echoue: [groq, mistral] » sur une tache deleguee,
alors que `groq` repondait 200 avec 14 modeles des que la sonde etait corrigee.

Pourquoi ca ne se voit pas : le message d'erreur est EXACT (« cle ecartee par la
rotation, http403 ») et pointe la cle. Rien dans ce texte ne dit que le 403 n'a jamais
atteint l'API. Un capteur qui fabrique la panne qu'il signale se lit comme un capteur
qui la constate.

Le garde porte sur le CHEMIN, pas sur l'en-tete du jour : ajouter un User-Agent corrige
l'occurrence, mais tout autre refus de bord (geo-blocage, rate-limit edge, challenge)
rebannirait une cle saine. Ce qui est teste ici, c'est qu'un 401/403 venu d'un
intermediaire n'alimente PAS la sante des cles.

Hermetique : `urlopen` et `_feed` sont remplaces, aucun reseau, aucune cle lue.
"""

from __future__ import annotations

import ast
import email.message
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_endpoint_monitor as mon  # noqa: E402


def _entetes(**kv) -> email.message.Message:
    m = email.message.Message()
    for k, v in kv.items():
        m[k.replace("_", "-")] = v
    return m


def _probe_avec(monkeypatch, code: int, entetes: email.message.Message):
    """Joue un probe() dont la reponse HTTP est imposee. Rend (resultat, cles_jugees)."""
    juges: list = []

    def _faux_urlopen(*_a, **_k):
        raise urllib.error.HTTPError("https://x/v1/models", code, "refus", entetes, None)

    monkeypatch.setattr(mon.urllib.request, "urlopen", _faux_urlopen)
    monkeypatch.setattr(mon, "_key", lambda env: ("cle-factice", "cle...ice"))
    monkeypatch.setattr(mon, "_feed", lambda env, key, status: juges.append((env, status)))
    res = mon.probe("cible", "https://x/v1/models", "UNE_CLE_ENV")
    return res, juges


# ------------------------------------------------- le garde sait MORDRE

def test_403_cloudflare_ne_juge_pas_la_cle(monkeypatch):
    """LE cas paye : cf-ray present => refus de bord, la cle n'est pas en cause."""
    res, juges = _probe_avec(monkeypatch, 403, _entetes(cf_ray="8a1b2c3d", server="cloudflare"))
    assert juges == [], "la sante des cles a ete alimentee par un refus de Cloudflare"
    assert "bloque_au_bord" in res["health"], res


def test_403_html_ne_juge_pas_la_cle(monkeypatch):
    """Sans cf-ray : une API d'authentification rend du JSON, pas du HTML."""
    res, juges = _probe_avec(monkeypatch, 403, _entetes(content_type="text/html; charset=utf-8"))
    assert juges == []
    assert "bloque_au_bord" in res["health"]


# ------------------------------------- ... et le garde ne crie PAS a faux

def test_401_json_juge_bien_la_cle(monkeypatch):
    """Un refus de l'API elle-meme DOIT continuer d'alimenter la rotation, sinon
    une cle reellement morte ne serait jamais ecartee."""
    res, juges = _probe_avec(monkeypatch, 401, _entetes(content_type="application/json"))
    assert juges == [("UNE_CLE_ENV", 401)], "une cle morte n'est plus ecartee"
    assert "bloque_au_bord" not in res["health"]


def test_429_quota_juge_toujours(monkeypatch):
    """Le quota n'est pas un refus de bord : il vient de l'API et doit compter."""
    _res, juges = _probe_avec(monkeypatch, 429, _entetes(content_type="application/json"))
    assert juges == [("UNE_CLE_ENV", 429)]


def test_content_type_absent_ne_tranche_pas(monkeypatch):
    """Trois etats : sans en-tete exploitable on ne DECIDE pas que c'est le bord."""
    _res, juges = _probe_avec(monkeypatch, 403, _entetes())
    assert juges == [("UNE_CLE_ENV", 403)], (
        "sans indice de bord, le 403 doit rester un verdict d'API — presumer le "
        "contraire rendrait toute cle morte indetectable")


def test_user_agent_toujours_envoye(monkeypatch):
    """L'en-tete qui a cause l'incident : son absence relance Cloudflare."""
    vus: dict = {}

    class _Rep:
        status = 200

        def read(self):
            return b'{"data": []}'

    def _faux_urlopen(req, *_a, **_k):
        vus.update({k.lower(): v for k, v in req.headers.items()})
        return _Rep()

    monkeypatch.setattr(mon.urllib.request, "urlopen", _faux_urlopen)
    monkeypatch.setattr(mon, "_key", lambda env: (None, "local"))
    monkeypatch.setattr(mon, "_feed", lambda *a: None)
    mon.probe("cible", "https://x/v1/models", None)
    assert "user-agent" in vus, "sonde sans User-Agent : Cloudflare rendra 403"


# ------------------------- garde d'alignement : le mangling qui masque un defaut

def _identifiants_mangles(source: str, nom: str = "<src>") -> list:
    """Noms `__x` utilises DANS une classe sans y etre definis.

    Python les mange en `_<Classe>__x` : l'erreur accuse alors un attribut prive
    inexistant au lieu de dire « nom non defini ». Mesure 2026-08-28 :
    `NameError: name '_Parallax__fs' is not defined` sur trois sites de
    forge_agent_proxy — ca se lit « fournisseur en panne » alors que c'est un
    defaut de code, et ca privait ces providers de la rotation des cles.
    """
    arbre = ast.parse(source, filename=nom)
    globaux = set()
    for n in arbre.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                globaux.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.Assign):
            globaux.update(c.id for c in n.targets if isinstance(c, ast.Name))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            globaux.add(n.name)
    out = []
    for cls in [n for n in ast.walk(arbre) if isinstance(n, ast.ClassDef)]:
        locaux = {c.id for a in ast.walk(cls) if isinstance(a, ast.Assign)
                  for c in a.targets if isinstance(c, ast.Name)}
        for n in ast.walk(cls):
            if not isinstance(n, ast.Name) or not isinstance(n.ctx, ast.Load):
                continue
            if not n.id.startswith("__") or n.id.endswith("__"):
                continue
            if n.id in globaux or n.id in locaux:
                continue
            out.append("%s::%s (ligne %d)" % (cls.name, n.id, n.lineno))
    return out


def test_mangling_detecte_le_cas_reel():
    src = ("class Parallax:\n"
           "    def ask(self):\n"
           "        return __fs.get_secret('X')\n")
    assert _identifiants_mangles(src) == ["Parallax::__fs (ligne 3)"]


def test_mangling_ignore_un_nom_importe():
    """Contre-epreuve : si le module l'importe, il n'y a pas de defaut."""
    src = ("import forge_secrets as __fs\n"
           "class P:\n"
           "    def ask(self):\n"
           "        return __fs.get_secret('X')\n")
    assert _identifiants_mangles(src) == []


def test_mangling_ignore_les_dunders():
    src = "class P:\n    def f(self):\n        return __name__\n"
    assert _identifiants_mangles(src) == []


def test_aucun_identifiant_mangle_dans_les_providers():
    """LE test : attrape le PROCHAIN `__x` glisse dans une classe, pas les trois corriges."""
    cibles = sorted((ROOT / "app").glob("forge_agent_proxy.py")) + \
        sorted((ROOT / "app").glob("forge_llm_router.py"))
    assert cibles, "modules providers introuvables — le garde ne garderait rien"
    fautifs: list = []
    for f in cibles:
        src = f.read_text(encoding="utf-8", errors="replace")
        try:
            fautifs += ["%s: %s" % (f.name, x) for x in _identifiants_mangles(src, str(f))]
        except SyntaxError as exc:
            pytest.fail("%s illisible : %s" % (f.name, exc))
    assert not fautifs, (
        "identifiants `__x` utilises dans une classe sans y etre definis : Python les "
        "mange en `_<Classe>__x` et le NameError accusera un attribut prive inexistant "
        "-- %s" % fautifs)
