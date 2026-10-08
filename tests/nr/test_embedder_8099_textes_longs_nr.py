"""NR — l'embedder local :8099 ne doit plus refuser un texte long, ni etre ecarte pour lui.

Mesure 2026-10-08. En embedding, llama.cpp ne TRONQUE PAS : une entree de plus de `n_ubatch`
jetons rend HTTP 500 « input (N tokens) is too large to process. increase the physical batch
size (current batch size: B) ». NokidoLlamaEmbed tournait avec `--ubatch-size 512` : au journal
de l'organe, 703, 1 912 et 3 615 jetons refuses le jour meme, et chaque refus ecartait le repli
local de l'election (« ABORT : aucun provider ne repond assez vite » au drain). Le test
d'installation (4e passe, run 37753729373) l'a revele sur Linux et Windows : `rag_direct` = 500.

Garanties verrouillees ici (owner 08/10 : « adaptatif selon l'embedder ») :
  1. les TROIS portes du routeur vers :8099 bornent en JETONS ce qu'elles envoient, a la limite
     APPRISE de l'embedder (n_ctx de /props, puis le lot que nomme son refus), et le DISENT ;
  2. un refus « too large » est appris puis la requete REJOUEE une fois, bornee ; ensuite plus
     de refus ; un texte court part tel quel, sans aller-retour ;
  3. lot physique <= contexte dans le produit et dans le test d'installation.
Aucun reseau : un faux serveur ou un mot = un jeton, qui refuse au-dela de son lot physique.
"""
from __future__ import annotations

import io
import json
import logging
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_embed_router as er  # noqa: E402


class _Rep(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FauxServeur:
    """Un mot = un jeton ; refuse comme llama.cpp toute entree > lot physique (`ubatch`)."""

    def __init__(self, n_ctx: int = 2048, ubatch: int = 2048, tokenize_ok: bool = True):
        self.n_ctx, self.ubatch, self.tokenize_ok = n_ctx, ubatch, tokenize_ok
        self.envoyes: list[str] = []
        self.refus = 0
        self.tokenize_appels = 0
        self._mots: list[str] = []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/props"):
            return _Rep(json.dumps({"default_generation_settings": {"n_ctx": self.n_ctx}}).encode())
        corps = json.loads(req.data or b"{}")
        if url.endswith("/tokenize"):
            self.tokenize_appels += 1
            if not self.tokenize_ok:
                raise urllib.error.URLError("tokenize indisponible")
            self._mots = corps["content"].split()
            return _Rep(json.dumps({"tokens": list(range(len(self._mots)))}).encode())
        if url.endswith("/detokenize"):
            return _Rep(json.dumps({"content": " ".join(self._mots[:len(corps["tokens"])])}).encode())
        entrees = corps["input"] if isinstance(corps["input"], list) else [corps["input"]]
        trop = [len(t.split()) + 2 for t in entrees if len(t.split()) + 2 > self.ubatch]
        if trop:
            self.refus += 1
            msg = ('{"error":{"code":500,"message":"input (%d tokens) is too large to process. increase '
                   'the physical batch size (current batch size: %d)"}}' % (trop[0], self.ubatch))
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, io.BytesIO(msg.encode()))
        self.envoyes.extend(entrees)
        data = [{"index": i, "embedding": [0.1] * 1024} for i in range(len(entrees))]
        return _Rep(json.dumps({"data": data}).encode())


def _brancher(monkeypatch, s: _FauxServeur) -> _FauxServeur:
    monkeypatch.setattr(urllib.request, "urlopen", s)
    monkeypatch.setattr(er, "_role_embed_local_autorise", lambda: True)
    monkeypatch.setattr(er, "declare_embed_wanted", lambda *a, **k: None)
    monkeypatch.setattr(er, "embed", lambda *a, **k: (_ for _ in ()).throw(AssertionError("repli per-text atteint")))
    monkeypatch.setattr(er, "_LIMITE_8099", {"jetons": None, "le": 0.0})
    return s


PORTES = {
    "unitaire": lambda t: er._embed_llama8099(t),
    "lot": lambda t: (er._llama8099_call([t]) or [None])[0],
    "embed_batch": lambda t: (er.embed_batch([t]) or [None])[0],
}
LONG = " ".join("mot%d" % i for i in range(3615))  # la taille refusee au journal du 08/10


@pytest.mark.parametrize("porte", sorted(PORTES))
def test_les_trois_portes_bornent_un_texte_long_et_le_disent(monkeypatch, porte, caplog):
    s = _brancher(monkeypatch, _FauxServeur())
    with caplog.at_level(logging.WARNING):
        vec = PORTES[porte](LONG)
    assert vec and len(vec) == 1024, "porte %s : texte long refuse au lieu d'etre borne" % porte
    assert s.refus == 0 and all(len(t.split()) + 2 <= s.ubatch for t in s.envoyes)
    assert re.search(r"TRONQUE.*3615", caplog.text), "la troncature doit dire combien (max vu)"


@pytest.mark.parametrize("porte", sorted(PORTES))
def test_le_lot_physique_est_appris_du_refus_puis_rejoue(monkeypatch, porte, caplog):
    s = _brancher(monkeypatch, _FauxServeur(n_ctx=2048, ubatch=300))
    with caplog.at_level(logging.WARNING):
        assert PORTES[porte](LONG), "le refus « too large » doit etre appris et la requete rejouee"
        assert PORTES[porte](LONG)
    assert s.refus == 1, "un seul refus : la limite apprise sert aux appels suivants"
    assert all(len(t.split()) + 2 <= 300 for t in s.envoyes)
    assert "300" in caplog.text and "appris" in caplog.text


def test_texte_court_part_tel_quel_sans_tokenisation(monkeypatch):
    s = _brancher(monkeypatch, _FauxServeur())
    court = "bge-m3 local, texte de chunk ordinaire"
    assert er._embed_llama8099(court)
    assert s.envoyes == [court] and s.tokenize_appels == 0


def test_tokenize_indisponible_borne_par_caracteres_et_le_dit(monkeypatch, caplog):
    s = _brancher(monkeypatch, _FauxServeur(tokenize_ok=False))
    with caplog.at_level(logging.WARNING):
        assert er._llama8099_call([LONG])
    assert all(len(t) <= s.ubatch for t in s.envoyes)
    assert "caracteres" in caplog.text


def _valeur(args: list[str], *noms: str) -> int:
    i = next(i for i, a in enumerate(args) if a in noms)
    return int(args[i + 1])


def test_produit_lot_physique_au_plus_le_contexte():
    with open(ROOT / "proxy_deno" / "core" / "services.toml", "rb") as f:
        svc = [s for s in tomllib.load(f)["service"] if s.get("name") == "NokidoLlamaEmbed"]
    assert len(svc) == 1, "NokidoLlamaEmbed introuvable ou en double dans services.toml"
    args = svc[0]["args"]
    assert _valeur(args, "--ubatch-size", "-ub") <= _valeur(args, "-c", "--ctx-size")


def test_installation_lot_physique_au_plus_le_contexte():
    src = (ROOT / "tools" / "forge_install_acceptance.py").read_text(encoding="utf-8")
    appel = next(b for b in src.split("demarrer([")[1:] if "--embedding" in b[:400])
    args = re.findall(r'"([^"]+)"', appel[:600])
    assert _valeur(args, "--ubatch-size", "-ub") <= _valeur(args, "-c", "--ctx-size")
