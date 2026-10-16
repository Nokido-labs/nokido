# -*- coding: utf-8 -*-
"""NR -- matrice modele x fournisseur (owner 15/10 : « des LLM peuvent etre injoignables par un provider et
joignables par un autre »).

Mesure qui l'a motivee : glm-5.x refuse EN DIRECT chez zAI (429/1113, sans solde), mistral-large refuse EN
DIRECT chez Mistral (403/1910, hors palier) -- un meme modele peut vivre chez un autre fournisseur.
Contrat (`tools/forge_provider_catalogue.py`) :
  1. `famille_de` ramene les identifiants de fournisseurs differents a la MEME famille ;
  2. `classer_reponse` distingue SANS_SOLDE, HORS_PALIER, DEBIT (pas un refus), CLEF_REFUSEE,
     MODELE_ABSENT, INCONNU -- d'apres le code ET le detail mesures le 15/10 ;
  3. `construire_matrice` sonde par GENERATION chaque couple d'une famille utile, et la lecture par famille
     rend les voies JOIGNABLES quel que soit le fournisseur qui refuse ailleurs ;
  4. matrice absente ou perimee : INCONNU / PERIMEE, jamais « aucune voie ».
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_provider_catalogue as cat  # noqa: E402


def test_familles_communes_entre_fournisseurs():
    assert cat.famille_de("glm-5") == cat.famille_de("z-ai/glm-5:free") == "glm-5"
    assert cat.famille_de("mistral-large-latest") == cat.famille_de("mistralai/mistral-large-2411") == "mistral-large"
    assert cat.famille_de("meta-llama/Llama-3.3-70B-Instruct-Turbo") == "llama-3.3-70b"
    assert cat.famille_de("Meta-Llama-3.3-70B-Instruct") == "meta-llama-3.3-70b"   # non utile : laisse tel quel


def test_classement_des_reponses_mesurees():
    assert cat.classer_reponse(200, "") == "JOIGNABLE"
    assert cat.classer_reponse(429, '{"error":{"code":"1113","message":"Insufficient balance"}}') == "SANS_SOLDE"
    assert cat.classer_reponse(402, '{"error":{"code":"PAYMENT_METHOD_REQUIRED"}}') == "SANS_SOLDE"
    assert cat.classer_reponse(403, '{"message":"not available in your subscription tier","code":"1910"}') == "HORS_PALIER"
    assert cat.classer_reponse(429, '{"message":"Rate limit exceeded","code":"1300"}') == "DEBIT"
    assert cat.classer_reponse(401, '{"error":"invalid_api_key"}') == "CLEF_REFUSEE"
    assert cat.classer_reponse(404, "model not found") == "MODELE_ABSENT"
    assert cat.classer_reponse(-1, "TimeoutError") == "INCONNU"


def test_un_modele_refuse_ici_est_joignable_ailleurs(tmp_path, monkeypatch):
    monkeypatch.setattr(cat, "MATRICE", tmp_path / "matrice.json")
    monkeypatch.setattr(cat, "FOURNISSEURS", [("zai", "ZAI_API_KEY", "https://z/v4/models"),
                                              ("openrouter", "OPENROUTER_API_KEY", "https://or/v1/models"),
                                              ("xai", "XAI_API_KEY", "https://x/v1/models")])
    catalogues = {"https://z/v4/models": ["glm-5", "glm-4.5-flash"], "https://or/v1/models": ["z-ai/glm-5"]}
    reponses = {("https://z/v4/models", "glm-5"): (429, '{"error":{"code":"1113"}}', 300),
                ("https://or/v1/models", "z-ai/glm-5"): (200, "", 900)}
    m = cat.construire_matrice(
        familles=("glm-5",), get_secret=lambda k: "" if k == "XAI_API_KEY" else "cle",
        interroger_fn=lambda url, cle: (200, catalogues[url], ""),
        sonder_fn=lambda url, cle, mid: reponses[(url, mid)])
    assert m["fournisseurs"]["xai"] == "CLE_ABSENTE"
    etats = {(v["fournisseur"], v["etat"]) for v in m["familles"]["glm-5"]}
    assert etats == {("zai", "SANS_SOLDE"), ("openrouter", "JOIGNABLE")}
    assert cat.ecrire_matrice(m)
    r = cat.voies_joignables("z-ai/glm-5:free")
    assert r["etat"] == "MESUREE" and r["voies"] == [("openrouter", "z-ai/glm-5", 900)]


def test_matrice_absente_ou_perimee_n_est_pas_aucune_voie(tmp_path, monkeypatch):
    monkeypatch.setattr(cat, "MATRICE", tmp_path / "matrice.json")
    assert cat.voies_joignables("glm-5")["etat"] == "INCONNU"
    vieux = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 30 * 86400))
    cat.MATRICE.write_text(json.dumps({"mesure_le": vieux, "familles": {"glm-5": [
        {"fournisseur": "openrouter", "modele": "z-ai/glm-5", "etat": "JOIGNABLE", "latence_ms": 900}]}}),
        encoding="utf-8")
    r = cat.voies_joignables("glm-5")
    assert r["etat"] == "PERIMEE" and r["voies"]           # les voies restent lisibles, l'age est DIT


# ── Axe COMPETENCE (decision owner 15/10 « les deux ») : JOIGNABLE n'est pas COMPETENT ─────────────────────────
def test_correcteurs_deterministes():
    assert cat._ok_json_strict('{"a": 2, "b": [1, 2]}')
    assert not cat._ok_json_strict('```json\n{"a": 2, "b": [1, 2]}\n```')       # strict : la balise echoue
    assert cat._ok_appel_outil('```json\n{"outil": "lire_fichier", "arguments": {"chemin": "notes.txt"}}\n```')
    assert not cat._ok_appel_outil('{"outil": "lire", "arguments": {"chemin": "notes.txt"}}')
    assert cat._ok_calcul("391") and not cat._ok_calcul("17*23 = 391")
    assert cat._ok_consigne("TROIS MOTS ICI") and not cat._ok_consigne("Trois mots ici")


def test_un_transport_rate_n_est_pas_une_tache_ratee():
    reponses = iter([(200, '{"a": 2, "b": [1, 2]}', 100), (200, "390", 120), (200, "UN DEUX TROIS", 90)])
    c = cat.sonder_competence("https://p/v1/models", "cle", "m", gen_fn=lambda *a, **k: next(reponses),
                              outil_fn=lambda base, cle, mid: {"etat": "NON_MESURE", "motif": "HTTP 429"})
    assert c["taches"]["appel_outil"] is None and c["taches"]["calcul"] is False
    assert (c["reussies"], c["mesurees"], c["total"], c["score"]) == (2, 3, 4, 0.67)


def test_la_competence_ne_se_mesure_que_sur_les_couples_joignables(monkeypatch):
    monkeypatch.setattr(cat, "FOURNISSEURS", [("zai", "ZAI_API_KEY", "https://z/v4/models"),
                                              ("openrouter", "OPENROUTER_API_KEY", "https://or/v1/models")])
    vus = []
    m = cat.construire_matrice(
        familles=("glm-5",), get_secret=lambda k: "cle",
        interroger_fn=lambda url, cle: (200, ["glm-5"], ""),
        sonder_fn=lambda url, cle, mid: (200, "", 100) if "//or/" in url else (429, '{"error":{"code":"1113"}}', 50),
        competence=True, competence_fn=lambda url, cle, mid: vus.append(url) or {"score": 1.0})
    voies = {v["fournisseur"]: v for v in m["familles"]["glm-5"]}
    assert voies["openrouter"]["etat"] == "JOIGNABLE" and "competence" in voies["openrouter"]
    assert voies["zai"]["etat"] == "SANS_SOLDE" and "competence" not in voies["zai"]
    assert vus == ["https://or/v1/models"]


def test_le_drapeau_competence_traverse_le_point_d_entree(monkeypatch, capsys):
    recu = {}

    def _fausse_matrice(**kw):
        recu.update(kw)
        return {"mesure_le": "", "fournisseurs": {}, "familles": {"glm-5": [
            {"fournisseur": "openrouter", "modele": "z-ai/glm-5", "etat": "JOIGNABLE", "latence_ms": 9,
             "competence": {"reussies": 3, "mesurees": 4, "total": 4, "taches": {}, "latence_ms_mediane": 9}}]}}

    monkeypatch.setattr(cat, "construire_matrice", _fausse_matrice)
    monkeypatch.setattr(cat, "ecrire_matrice", lambda m: True)
    monkeypatch.setattr(sys, "argv", ["forge_provider_catalogue.py", "--matrice", "--competence"])
    assert cat.main() == 0 and recu == {"competence": True}
    assert "competence openrouter:z-ai/glm-5 : 3/4 mesurees (sur 4)" in capsys.readouterr().out


def test_joignable_a_16_tokens_mais_refuse_a_l_usage_est_reclasse():
    """Mesure du 15/10 : 20 couples OpenRouter payants « JOIGNABLES » rendaient 402 a l'usage reel."""
    tous_402 = {"etat": "JOIGNABLE", "competence": {"mesurees": 0, "codes_non_mesurees": {"a": 402, "b": 402}}}
    assert cat.reclasser_par_competence(tous_402)["etat"] == "SANS_SOLDE"
    assert tous_402["etat_sonde_16_tokens"] == "JOIGNABLE"
    melange = {"etat": "JOIGNABLE", "competence": {"mesurees": 0, "codes_non_mesurees": {"a": 402, "b": -1}}}
    assert cat.reclasser_par_competence(melange)["etat"] == "JOIGNABLE"          # transport : INCONNU, pas reclasse
    mesure = {"etat": "JOIGNABLE", "competence": {"mesurees": 2, "codes_non_mesurees": {"a": 402, "b": 402}}}
    assert cat.reclasser_par_competence(mesure)["etat"] == "JOIGNABLE"
    reponses = iter([(402, "", 10)] * 3)
    c = cat.sonder_competence("https://or/v1/models", "cle", "m", gen_fn=lambda *a, **k: next(reponses),
                              outil_fn=lambda base, cle, mid: {"etat": "REFUSE", "motif": "HTTP 402 — no credits"})
    assert c["codes_non_mesurees"] == {"json_strict": 402, "appel_outil": 402, "calcul": 402, "consigne": 402}


def test_l_appel_d_outil_passe_par_la_vraie_sonde():
    """Convergence P2 du 15/10 : la tache `appel_outil` delegue a forge_tool_call_probe (vrais tool_calls). Un acces
    refuse (401/402/403/404) n'est pas un echec de competence ; seul un 400 (parametre `tools` rejete) en est un."""
    def f(etat, motif=""):
        return lambda base, cle, mid: {"etat": etat, "motif": motif}

    assert cat._outil_natif("https://p/v1/models", "c", "m", f("APPELLE", "numero=7")) == (True, 200)
    assert cat._outil_natif("https://p/v1/models", "c", "m", f("IGNORE", "a repondu en texte")) == (False, 200)
    assert cat._outil_natif("https://p/v1/models", "c", "m", f("REFUSE", "HTTP 400 — tools")) == (False, 200)
    assert cat._outil_natif("https://p/v1/models", "c", "m", f("REFUSE", "HTTP 402 — credits")) == (None, 402)
    assert cat._outil_natif("https://p/v1/models", "c", "m", f("NON_MESURE", "HTTP 429")) == (None, 429)
    vu = []
    cat._outil_natif("https://p/v1/models", "c", "m", lambda base, cle, mid: vu.append(base) or {"etat": "APPELLE"})
    assert vu == ["https://p/v1"]


def test_un_cli_qui_echoue_est_note_jamais_incompetent():
    reponses = iter([{"response": '{"a": 2, "b": [1, 2]}'}, {"error": "OAuth expire"},
                     RuntimeError("binaire introuvable"), {"text": "UN DEUX TROIS"}])

    def faux_ask(provider, prompt):
        r = next(reponses)
        if isinstance(r, Exception):
            raise r
        return r

    c = cat.sonder_competence_cli("gemini_cli", ask_fn=faux_ask)
    assert c["taches"] == {"json_strict": True, "appel_outil": None, "calcul": None, "consigne": True}
    assert (c["reussies"], c["mesurees"], c["score"]) == (2, 2, 1.0)
    assert "OAuth" in c["raisons_non_mesurees"]["appel_outil"] and "introuvable" in c["raisons_non_mesurees"]["calcul"]


def test_le_drapeau_cli_traverse_le_point_d_entree(monkeypatch, capsys):
    vus = []
    monkeypatch.setattr(cat, "construire_matrice", lambda **kw: {"mesure_le": "", "fournisseurs": {}, "familles": {}})
    monkeypatch.setattr(cat, "sonder_competence_cli", lambda p: vus.append(p) or {
        "reussies": 1, "mesurees": 1, "total": 4, "taches": {}, "raisons_non_mesurees": {}})
    monkeypatch.setattr(cat, "ecrire_matrice", lambda m: vus.append(sorted(m.get("cli", {}))) or True)
    monkeypatch.setattr(sys, "argv", ["forge_provider_catalogue.py", "--matrice", "--cli", "gemini_cli,opencode"])
    assert cat.main() == 0
    assert vus == ["gemini_cli", "opencode", ["gemini_cli", "opencode"]]
