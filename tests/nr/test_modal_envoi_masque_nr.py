"""NR -- le texte envoye a l'endpoint d'embedding Modal est MASQUE, et rien ne part sans masqueur.

MESURE 2026-10-01 : `forge_embed_router._modal_call` envoyait le texte BRUT des chunks au cloud,
alors que le tier vectorise est le contenu PROPRE de Nokido (laforge-memory, laforge-code :
forge_tier_policy.HOT_ORIGINS). Regle du depot : le cloud recoit peu, et filtre. Le porteur
existant `redact_tool_output` (infrastructure ET clefs d'API) est branche ; `journal=False` lui
evite un avertissement par texte sur une campagne de centaines de milliers de chunks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(30)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_embed_router as er  # noqa: E402

# Construits par morceaux : aucun motif de secret litteral dans ce fichier.
JETON = "ghp_" + "A1b2C3d4" * 4 + "Zz9Y"
IP = "10." + "20.30.40"


class _Rep:
    def __init__(self, d):
        self.d = d

    def read(self):
        return json.dumps(self.d).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_le_texte_part_masque(monkeypatch):
    envoye = {}

    def urlopen(req, timeout=None):
        envoye["corps"] = req.data.decode("utf-8")
        return _Rep({"embeddings": [[0.0] * 4, [0.0] * 4], "dim": 4})

    monkeypatch.setattr(er, "_modal_url", lambda: "https://exemple.invalid/embed")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    vecs = er._modal_call(["config du depot : jeton %s" % JETON, "le serveur ecoute sur %s:8766" % IP])
    assert vecs is not None and len(vecs) == 2
    corps = envoye["corps"]
    assert JETON not in corps, "une clef d'API est partie en clair vers le cloud"
    assert IP not in corps, "une adresse d'infrastructure est partie en clair vers le cloud"
    assert "config du depot" in corps, "le masquage ne doit pas vider le texte"


def test_sans_masqueur_rien_ne_part(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("envoi au cloud SANS masqueur")

    monkeypatch.setattr(er, "_modal_url", lambda: "https://exemple.invalid/embed")
    monkeypatch.setattr("urllib.request.urlopen", interdit)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_semantic_firewall", None)   # import -> ImportError
    assert er._modal_call(["un texte"]) is None


def test_cloudflare_aussi_part_masque(monkeypatch):
    envoye = {}

    class _Ouvreur:
        def open(self, req, timeout=None):
            envoye["corps"] = req.data.decode("utf-8")
            return _Rep({"success": True, "result": {"data": [[0.0] * 1024]}})

    from nokido_agent.app import forge_secrets as fs

    monkeypatch.setattr(fs, "get_secret", lambda k: "factice-%s" % k)   # aucune vraie clef lue
    monkeypatch.setattr(er, "_opener_ipv4", lambda: _Ouvreur())
    vecs = er._cloudflare_call(["jeton %s sur %s" % (JETON, IP)])
    assert vecs and len(vecs[0]) == 1024
    assert JETON not in envoye["corps"] and IP not in envoye["corps"]


def test_la_cause_d_un_echec_modal_est_dite(monkeypatch, caplog):
    import io
    import urllib.error

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {},
                                     io.BytesIO(b"modal-http: workspace ws-test is disabled\n"))

    monkeypatch.setattr(er, "_modal_url", lambda: "https://exemple.invalid/embed")
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with caplog.at_level("WARNING"):
        assert er._modal_call(["un texte"]) is None
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "404" in msg and "disabled" in msg, "la cause (compte desactive) n'est pas au journal : %s" % msg


def _campagne():
    import importlib.util

    spec = importlib.util.spec_from_file_location("campagne_nr", RACINE / "tools" / "forge_embed_modal_campagne.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_la_campagne_prend_le_premier_fournisseur_compatible_qui_rend():
    c = _campagne()
    appels = []

    def modal(t):
        appels.append("modal")
        return None

    def mauvaise_dim(t):
        appels.append("autre")
        return [[0.0] * 768 for _ in t]

    def cloudflare(t):
        appels.append("cloudflare")
        return [[0.0] * 1024 for _ in t]

    vecs, nom, ko = c.premier_qui_rend(["a", "b"], [("modal", modal), ("autre", mauvaise_dim),
                                                     ("cloudflare", cloudflare)], 1024)
    assert nom == "cloudflare" and len(vecs) == 2 and ko == ["modal:vide", "autre:forme"]
    appels.clear()
    c.premier_qui_rend(["a"], [("modal", modal), ("cloudflare", cloudflare)], 1024, actif="cloudflare")
    assert appels == ["cloudflare"], "le fournisseur actif doit etre essaye d'abord : %s" % appels


def test_le_masqueur_en_lot_ne_journalise_pas_par_appel(caplog):
    from nokido_agent.app.forge_semantic_firewall import redact_tool_output

    with caplog.at_level("WARNING"):
        texte, bilan = redact_tool_output("jeton %s" % JETON, outil="essai", journal=False)
    assert JETON not in texte and bilan["secrets_rediges"] >= 1
    assert not [r for r in caplog.records if "rediges dans la sortie" in r.getMessage()]
