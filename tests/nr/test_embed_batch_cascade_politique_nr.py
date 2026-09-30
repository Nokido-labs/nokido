"""NR — la cascade BATCH d'embedding obeit a la politique des piliers, comme la single.

Mesure 2026-09-06 : `embed_batch_fast` (le chemin du drain `forge_embed_auto_trigger`)
tentait :8099, Modal, puis Voyage et Jina - d'AUTRES espaces vectoriels - sans lire
`config/pillar_policy.json`, alors que `embed()` la respecte depuis l'incident de
pollution Voyage du 2026-09-01. Et Cloudflare (meme bge-m3) n'y etait jamais tente en
lot : seulement texte par texte, 32x plus de requetes pour le meme quota.

Trois garanties, sur des espions (aucun reseau) :
  1. sous politique ["modal", "cloudflare"], Voyage/Jina/:8099 ne sont meme pas TENTES
     et l'ordre suivi est celui de la politique ;
  2. politique muette (None) -> ordre par defaut, local d'abord ;
  3. Cloudflare est appele EN LOT (une fois pour N textes), pas texte par texte.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_embed_router as er  # noqa: E402

VEC = [0.1] * 1024


def _espions(monkeypatch, repondent: set[str]):
    appels: list[tuple[str, int]] = []

    def _fab(nom):
        def _f(texts, timeout=0.0):
            appels.append((nom, len(texts)))
            return [list(VEC) for _ in texts] if nom in repondent else None
        return _f

    for nom, attr in (("llama8099", "_llama8099_call"), ("modal", "_modal_call"),
                      ("cloudflare", "_cloudflare_call"), ("voyage", "_voyage_call"),
                      ("jina", "_jina_call"), ("brain_worker", "_brain_worker_call")):
        monkeypatch.setattr(er, attr, _fab(nom))
    # la degradation single ne doit pas etre atteinte dans ces tests
    monkeypatch.setattr(er, "embed", lambda t, prefer=None: (_ for _ in ()).throw(AssertionError("embed() single atteint")))
    return appels


# ---------------------------------------------------------------------------
# LA SORTIE RESEAU DE CLOUDFLARE. Cliquet du 2026-09-16.
#
# Workers AI repondait `code 10000 Authentication error`, et la lecture naturelle
# -- celle que j'ai faite, a tort -- est « la cle est expiree ou revoquee ».
# MESURE : le token est VALIDE. C'est l'ADRESSE DE SORTIE qui est refusee.
#
#   sortie IPv6 (defaut de Python)  -> HTTP 403, code 9109,
#                                      « Cannot use the access token from location: <IPv6> »
#   sortie IPv4 FORCEE              -> HTTP 200, puis un embedding bge-m3 dim 1024
#
# Le token porte une allowlist d'adresses qui contient l'IPv4 et pas l'IPv6.
# `getaddrinfo` prefere l'IPv6 des que la box en annonce une : le jour ou cette
# IPv6 est apparue, un provider qui marchait depuis le 2026-08-20 s'est mis a
# repondre « authentification » sans que rien n'ait ete touche.
#
# LEÇON : un code d'erreur d'authentification ne nomme pas sa cause. Quatre cas
# distincts s'y ecrivent pareil -- token mort, token sans la permission, mauvais
# account, adresse source refusee -- et un seul se repare sans toucher au secret.
#
# ETAT ATTENDU : rouge tant que la sortie n'est pas forcee en IPv4.
# ---------------------------------------------------------------------------


def test_la_connexion_cloudflare_demande_explicitement_de_l_ipv4(monkeypatch):
    import socket as _s

    vu = {}

    def _espion(host, port, family=0, *a, **k):
        vu["family"] = family
        raise OSError("espion : aucune socket n'est ouverte par ce test")

    monkeypatch.setattr(_s, "getaddrinfo", _espion)
    conn = er._ConnexionIPv4("api.cloudflare.com", 443, timeout=1)
    with pytest.raises(OSError):
        conn.connect()
    assert vu.get("family") == _s.AF_INET, (
        "la connexion laisse le resolveur choisir : il prendra l'IPv6, que "
        "l'allowlist du token refuse"
    )


def test_le_resolveur_GLOBAL_n_est_jamais_patche():
    """Le hub est multi-thread. Forcer IPv4 en ecrivant `socket.getaddrinfo = ...`
    changerait la famille d'adresse des appels CONCURRENTS, qui n'ont rien
    demande. La contrainte doit rester locale a la connexion."""
    import inspect

    source = inspect.getsource(er)
    assert "socket.getaddrinfo =" not in source, (
        "patch global du resolveur : effet de bord sur tous les autres appels "
        "sortants du process"
    )


def test_l_appel_cloudflare_emprunte_l_opener_ipv4():
    """Une classe correcte que la fonction n'utilise pas ne repare rien -- c'est
    la dette de cablage deja payee par ce meme provider le 2026-08-20, ou tout
    etait ecrit et rien n'etait branche."""
    import inspect

    src = inspect.getsource(er._cloudflare_call)
    assert "_opener_ipv4" in src, (
        "_cloudflare_call n'emprunte pas la sortie IPv4 : la classe existerait "
        "sans jamais servir"
    )
    assert "_u.urlopen(" not in src, (
        "il reste un urlopen nu, qui repartira en IPv6"
    )


def test_sous_politique_seuls_les_backends_nommes_sont_tentes_dans_son_ordre(monkeypatch):
    monkeypatch.setattr(er, "_politique_embed", lambda: ["modal", "cloudflare"])
    appels = _espions(monkeypatch, repondent={"cloudflare"})
    out = er.embed_batch_fast(["a", "b", "c"], batch_size=32, max_workers=1)
    assert len(out) == 3 and all(v for v in out)
    noms = [n for n, _ in appels]
    assert noms == ["modal", "cloudflare"], noms
    assert "voyage" not in noms and "jina" not in noms and "llama8099" not in noms


def test_politique_muette_ordre_par_defaut_local_d_abord(monkeypatch):
    monkeypatch.setattr(er, "_politique_embed", lambda: None)
    appels = _espions(monkeypatch, repondent={"llama8099"})
    out = er.embed_batch_fast(["a", "b"], batch_size=32, max_workers=1)
    assert len(out) == 2 and all(out)
    assert [n for n, _ in appels] == ["llama8099"]


def test_cloudflare_est_appele_en_lot_pas_texte_par_texte(monkeypatch):
    monkeypatch.setattr(er, "_politique_embed", lambda: ["cloudflare"])
    appels = _espions(monkeypatch, repondent={"cloudflare"})
    textes = [f"t{i}" for i in range(40)]
    out = er.embed_batch_fast(textes, batch_size=20, max_workers=1)
    assert len(out) == 40 and all(out)
    assert appels == [("cloudflare", 20), ("cloudflare", 20)], appels


def test_politique_sans_aucun_backend_connu_laisse_la_cascade_intacte(monkeypatch):
    # une politique qui ne nomme aucun essai connu ne doit pas VIDER la cascade,
    # mais elle ne doit pas non plus laisser passer un backend PAYANT
    essais = er._essais_batch(["x"])
    garde = er._essais_selon_politique(essais, ["inconnu"])
    assert [n for n, _ in garde] == [n for n, _ in er._sans_payants(essais)]
    tri = er._essais_selon_politique(essais, ["jina", "modal"])
    assert [n for n, _ in tri] == ["jina", "modal"]


def test_un_backend_payant_n_est_jamais_tente_sans_politique_qui_le_nomme(monkeypatch):
    """Un backend gratuit qui echoue coute une latence ; un payant qui reussit coute de
    l'argent. La difference est portee par le CODE (`_PAYANTS`), pas par la vigilance de
    celui qui edite la politique. Mesure 2026-09-06 : OpenRouter sert `baai/bge-m3` en
    1024D (HTTP 200) -- donc utilisable, donc facturable."""
    assert "openrouter" in er._PAYANTS
    # politique muette -> retire
    monkeypatch.setattr(er, "_politique_embed", lambda: None)
    appels = _espions(monkeypatch, repondent=set())
    monkeypatch.setattr(er, "_openrouter_call", lambda texts, timeout=0.0: (_ for _ in ()).throw(
        AssertionError("openrouter tente sans politique")))
    monkeypatch.setattr(er, "embed", lambda t, prefer=None: None)
    er.embed_batch_fast(["a"], batch_size=8, max_workers=1)
    assert "openrouter" not in [n for n, _ in appels]
    # politique qui le NOMME -> tente
    monkeypatch.setattr(er, "_politique_embed", lambda: ["openrouter"])
    vus: list[int] = []
    monkeypatch.setattr(er, "_openrouter_call", lambda texts, timeout=0.0: (vus.append(len(texts)) or [list(VEC) for _ in texts]))
    out = er.embed_batch_fast(["a", "b"], batch_size=8, max_workers=1)
    assert vus == [2] and len(out) == 2 and all(out)


def test_la_cascade_unitaire_retire_aussi_les_payants_sans_politique(monkeypatch):
    noms = [n for n, _ in er.PROVIDERS]
    assert "openrouter" in noms, noms
    assert [n for n, _ in er._sans_payants(er.PROVIDERS)] == [n for n in noms if n != "openrouter"]
