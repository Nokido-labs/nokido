"""NR -- le recenseur des offres gratuites sait SONDER des modeles NOMMES (owner 16/10).

RED ecrit par Claude. Vecu 16/10 : Gemini web affirmait que llama-3.3-70b-versatile, gpt-oss-120b, qwen3-32b (Groq) et
Devstral 2 / Codestral (Mistral) sont gratuits ; le recensement n'echantillonne que les PLUS PETITS modeles (preuve
rapide) et filtre le catalogue -- il ne pouvait ni confirmer ni infirmer. `--cible fournisseur:modele,...` rend, pour
chaque modele nomme : DECLARE au catalogue de notre cle, JOIGNABLE (completion reelle), quota expose. Trois etats :
un fournisseur inconnu ou un catalogue illisible n'est jamais lu « absent ».
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_free_tier_census as C  # noqa: E402


def _faux(monkeypatch, catalogue_code=200):
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: "cle-de-test")
    monkeypatch.setattr(C, "catalogue", lambda base, cle: (catalogue_code, [{"id": "a"}], {}))
    monkeypatch.setattr(C, "sonder", lambda base, cle, m, outils=False: {
        "joignable": m == "a", "motif": "OK" if m == "a" else "HTTP 404", "limites": {}, "outils": True})


def test_un_modele_declare_et_joignable(monkeypatch):
    _faux(monkeypatch)
    (r,) = C.cibler([("groq", "a")])
    assert (r["declare"], r["joignable"]) == (True, True), r


def test_un_modele_absent_du_catalogue_est_quand_meme_sonde(monkeypatch):
    _faux(monkeypatch)
    (r,) = C.cibler([("groq", "b")])
    assert r["declare"] is False and r["joignable"] is False and r["motif"] == "HTTP 404", r


def test_un_catalogue_illisible_ne_dit_pas_absent(monkeypatch):
    _faux(monkeypatch, catalogue_code=401)
    (r,) = C.cibler([("groq", "a")])
    assert r["declare"] is None, r


def test_un_fournisseur_inconnu_le_dit(monkeypatch):
    _faux(monkeypatch)
    (r,) = C.cibler([("inexistant", "a")])
    assert r.get("etat") == "FOURNISSEUR_INCONNU", r


class _Rep:
    def __init__(self, corps):
        self._c = corps

    def read(self):
        import json
        return json.dumps(self._c).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_le_quota_openrouter_dit_le_palier_et_le_debit(monkeypatch):
    """Owner 16/10 : OpenRouter EXPOSE ses limites (/api/v1/key) ; le recenseur n'en lisait que usage/limite/restant."""
    corps = {"data": {"usage": 0.0, "limit": None, "limit_remaining": None, "is_free_tier": True,
                      "rate_limit": {"requests": 20, "interval": "10s"}}}
    monkeypatch.setattr(C.urllib.request, "urlopen", lambda req, timeout=0: _Rep(corps))
    q = C.quota("openrouter", "cle-de-test", {})
    assert "palier_gratuit=True" in q and "debit=20/10s" in q, q


def test_un_debit_absent_se_dit_non_expose(monkeypatch):
    monkeypatch.setattr(C.urllib.request, "urlopen", lambda req, timeout=0: _Rep({"data": {"usage": 1.0}}))
    q = C.quota("openrouter", "cle-de-test", {})
    assert "debit=NON EXPOSE" in q and "palier_gratuit=INCONNU" in q, q


def _completion(monkeypatch, message, fin="stop"):
    corps = {"choices": [{"message": message, "finish_reason": fin}]}
    monkeypatch.setattr(C.urllib.request, "urlopen", lambda req, timeout=0: _Rep(corps))
    return C.joignable("https://x/v1", "cle-de-test", "m")


def test_un_modele_de_raisonnement_qui_repond_est_joignable(monkeypatch):
    """Vecu 16/10 : openrouter/free, nemotron-3-super:free, gpt-oss (Groq) lus « reponse vide » -- max_tokens=8 consomme
    par le raisonnement, `content` vide. Le fournisseur a REPONDU : c'est joignable, et le motif le dit."""
    ok, motif = _completion(monkeypatch, {"content": "", "reasoning": "Je reflechis..."})
    assert ok is True and "raisonnement" in motif, motif


def test_une_reponse_coupee_par_le_budget_est_joignable(monkeypatch):
    ok, motif = _completion(monkeypatch, {"content": None}, fin="length")
    assert ok is True and "budget" in motif, motif


def test_une_reponse_vraiment_vide_reste_injoignable(monkeypatch):
    ok, motif = _completion(monkeypatch, {"content": ""}, fin="stop")
    assert (ok, motif) == (False, "reponse vide")


class _RepEntetes(_Rep):
    def __init__(self, corps, entetes):
        super().__init__(corps)
        self.headers = entetes

    def getheaders(self):
        return list(self.headers.items())


def test_la_sonde_rend_les_entetes_de_limite_de_la_completion(monkeypatch):
    """Mesure 16/10 : quotas Groq/Mistral « NON MESURE » -- quota() lisait les en-tetes du CATALOGUE, or ces fournisseurs
    envoient x-ratelimit-* sur la COMPLETION. Tous sont rendus (pas seulement le premier)."""
    corps = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    entetes = {"x-ratelimit-remaining-requests": "999", "x-ratelimit-remaining-tokens": "5000",
               "retry-after": "2", "content-type": "application/json"}
    monkeypatch.setattr(C.urllib.request, "urlopen", lambda req, timeout=0: _RepEntetes(corps, entetes))
    d = C.sonder("https://x/v1", "cle-de-test", "m")
    assert d["joignable"] is True, d
    assert d["limites"] == {"x-ratelimit-remaining-requests": "999", "x-ratelimit-remaining-tokens": "5000",
                            "retry-after": "2"}, d


def test_la_sonde_dit_si_le_modele_accepte_les_outils(monkeypatch):
    """Exigence du swarm/MCP : un modele qui refuse `tools` (400) n'est pas utilisable par le swarm, meme gratuit."""
    vus = []

    def _ouvrir(req, timeout=0):
        import json as _j
        charge = _j.loads(req.data.decode())
        vus.append("tools" in charge)
        if "tools" in charge:
            raise C.urllib.error.HTTPError(req.full_url, 400, "no tool support", {}, None)
        return _RepEntetes({"choices": [{"message": {"content": "ok"}}]}, {})

    monkeypatch.setattr(C.urllib.request, "urlopen", _ouvrir)
    d = C.sonder("https://x/v1", "cle-de-test", "m", outils=True)
    assert d["outils"] is False and d["joignable"] is True, d
    assert vus == [True, False], vus


def test_un_modele_absent_ne_dit_rien_des_outils(monkeypatch):
    """Vecu 16/10 : Cerebras/NVIDIA en 404 avec ET sans `tools` etaient affiches « outils REFUSES ». Un modele ABSENT
    ne dit rien de son support des outils : INDETERMINE (None), seul un succes SANS outils prouve le refus."""
    def _ouvrir(req, timeout=0):
        raise C.urllib.error.HTTPError(req.full_url, 404, "model not found", {}, None)

    monkeypatch.setattr(C.urllib.request, "urlopen", _ouvrir)
    d = C.sonder("https://x/v1", "cle-de-test", "m", outils=True)
    assert d["outils"] is None and d["joignable"] is False and d["motif"] == "HTTP 404", d


def test_le_recensement_distingue_declares_bruts_et_utiles(monkeypatch, tmp_path):
    """RED 3 du plan AGY (certifie 16/10) : « Groq : 6 modeles » etait compte APRES le filtre _INADAPTES -- le registre
    doit dire combien le fournisseur declare (bruts), combien restent (utiles), et LESQUELS sont ecartes."""
    import json as _j
    from nokido_agent.app import forge_secrets as s

    monkeypatch.setattr(s, "get_secret", lambda k: "cle-de-test")
    monkeypatch.setattr(C, "SURFACES", [("faux", "FAUX_KEY", "https://x/v1")])
    monkeypatch.setattr(C, "SORTIE", tmp_path / "census.json")
    monkeypatch.setattr(C, "catalogue", lambda base, cle: (200, [{"id": "llama-x"}, {"id": "whisper-large"},
                                                                 {"id": "llama-guard-3"}], {}))
    monkeypatch.setattr(C, "sonder", lambda *a, **k: {"joignable": True, "motif": "", "limites": {}, "outils": None})
    monkeypatch.setattr(C, "quota", lambda *a, **k: "NON MESURE")
    monkeypatch.setattr(C.sys, "argv", ["forge_free_tier_census.py"])
    assert C.main() == 0
    (f,) = _j.loads((tmp_path / "census.json").read_text(encoding="utf-8"))["fournisseurs"]
    assert (f["declares_bruts"], f["declares_utiles"]) == (3, 1), f
    assert sorted(f["ecartes"]) == ["llama-guard-3", "whisper-large"], f


def test_l_option_se_lit_sur_la_ligne_de_commande():
    assert C.lire_cibles(["--cible", "groq:llama-3.3-70b-versatile,mistral:devstral-2"]) == [
        ("groq", "llama-3.3-70b-versatile"), ("mistral", "devstral-2")]


# --- RED 4 du plan AGY (16/10) : un verdict MESURE se GARDE ---------------------------------------------------------
# Owner 16/10 : « y en a marre de refaire ces enquetes a chaque fois ». `--cible` imprimait ses verdicts et n'en gardait
# aucun : chaque session re-sondait. Ils vont au registre deja ecrit par le recensement (un seul registre, pas deux),
# par fournisseur:modele, horodates -- et une passe ne jette jamais ce qu'une autre a mesure.
import json as _json  # noqa: E402


def _registre(monkeypatch, tmp_path, contenu=None):
    chemin = tmp_path / "census.json"
    if contenu is not None:
        chemin.write_text(_json.dumps(contenu), encoding="utf-8")
    monkeypatch.setattr(C, "SORTIE", chemin)
    monkeypatch.setattr(C, "quota", lambda *a, **k: "NON MESURE")
    monkeypatch.setattr(C, "PAUSE_S", 0)
    return chemin


def _cibler(monkeypatch, cibles):
    monkeypatch.setattr(C.sys, "argv", ["forge_free_tier_census.py", "--cible", cibles])
    assert C.main() == 0


def test_une_passe_ciblee_garde_ses_verdicts(monkeypatch, tmp_path):
    _faux(monkeypatch)
    chemin = _registre(monkeypatch, tmp_path)
    _cibler(monkeypatch, "groq:a,groq:b,inconnu:q")
    v = _json.loads(chemin.read_text(encoding="utf-8"))["verdicts"]
    assert v["groq:a"]["joignable"] is True and v["groq:a"]["mesure_le"], v
    assert v["groq:b"]["joignable"] is False and v["groq:b"]["motif"] == "HTTP 404", v
    # UNKNOWN n'est pas NO : un fournisseur inconnu garde son etat, sans « joignable: false » fabrique
    assert v["inconnu:q"]["etat"] == "FOURNISSEUR_INCONNU" and "joignable" not in v["inconnu:q"], v


def test_une_passe_ciblee_ne_jette_ni_les_autres_verdicts_ni_le_recensement(monkeypatch, tmp_path):
    _faux(monkeypatch)
    avant = {"horodatage": "h", "fournisseurs": [{"fournisseur": "groq"}],
             "verdicts": {"mistral:codestral-latest": {"joignable": True}, "groq:a": {"joignable": False}}}
    chemin = _registre(monkeypatch, tmp_path, avant)
    _cibler(monkeypatch, "groq:a")
    d = _json.loads(chemin.read_text(encoding="utf-8"))
    assert d["fournisseurs"] == [{"fournisseur": "groq"}], d
    assert d["verdicts"]["mistral:codestral-latest"] == {"joignable": True}, d
    assert d["verdicts"]["groq:a"]["joignable"] is True, "la mesure la plus recente remplace l'ancienne"


def test_la_passe_complete_ne_jette_pas_les_verdicts(monkeypatch, tmp_path):
    from nokido_agent.app import forge_secrets as s

    monkeypatch.setattr(s, "get_secret", lambda k: "")
    monkeypatch.setattr(C, "SURFACES", [])
    chemin = _registre(monkeypatch, tmp_path, {"verdicts": {"groq:a": {"joignable": True}}})
    monkeypatch.setattr(C.sys, "argv", ["forge_free_tier_census.py"])
    assert C.main() == 0
    assert _json.loads(chemin.read_text(encoding="utf-8"))["verdicts"] == {"groq:a": {"joignable": True}}
