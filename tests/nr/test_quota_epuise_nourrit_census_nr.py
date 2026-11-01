"""NR 29/10 (owner : « une info de fin de quota devrait nourrir le census pour eviter des mesures inutiles ensuite » ;
« executeurs gratuits ») -- un quota epuise CONSTATE par l'executeur s'ecrit au census avec une ECHEANCE ; le couple est
hors quota jusqu'a elle, puis redevient eligible ; un census illisible n'est jamais ecrase (UNKNOWN n'est pas NO) ; et
sous l'interrupteur « repli gratuit seul », la reaffectation ne choisit jamais une surface payante.

Mesure : 4 taches OpenCode retombees sur leur repli apres un quota que personne n'avait consigne, puis DEFAUT3
reaffectee a CLAUDE_HEADLESS (payant) contre le choix de l'owner.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "app"), str(ROOT)]

import forge_free_tier_census as C  # noqa: E402
import forge_task_executor as E  # noqa: E402
import pytest  # noqa: E402

T0 = 1_800_000_000.0


@pytest.fixture()
def census(tmp_path):
    p = tmp_path / "free_tier_census.json"
    p.write_text(json.dumps({"horodatage": "x", "verdicts": {
        "openrouter:nvidia/nemotron": {"joignable": True, "mesure_le": "2026-10-21T16:08:34", "outils": True}}}),
        encoding="utf-8")
    return p


def _minuit_utc(t):
    from datetime import datetime, timezone
    import forge_provider_catalogue as cat
    return datetime.fromisoformat(cat.echeance_quota(datetime.fromtimestamp(t, timezone.utc))).timestamp()


def test_quota_consigne_hors_quota_jusqu_a_l_echeance_puis_eligible(census):
    fin = C.consigner_quota_epuise("openrouter", "nvidia/nemotron", "Rate limit exceeded: free-models-per-day",
                                   maintenant=T0, chemin=census)
    assert fin == _minuit_utc(T0)   # quota JOURNALIER : l'echeance du catalogue (prochain minuit UTC), pas un defaut
    assert E._modele_hors_quota("openrouter", "nvidia/nemotron", chemin=census, maintenant=T0 + 60)
    assert E._modele_hors_quota("openrouter", "nvidia/nemotron", chemin=census, maintenant=fin + 1) is None


def test_echeance_lue_dans_le_message():
    assert C.echeance_quota("429 Rate limit exceeded, retry after 120 seconds", T0) == T0 + 120
    assert C.echeance_quota("quota exceeded, please try again in 15m", T0) == T0 + 900
    assert C.echeance_quota("Insufficient balance", T0) == T0 + C.QUOTA_REPOS_DEFAUT_S


def test_quota_mensuel_echeance_au_premier_du_mois_suivant():
    """29/10 soir, mesure : Ollama Cloud « you (...) have reached your monthly usage limit » -- non reconnu, donc non
    consigne : le census aurait continue d'envoyer des taches a un fournisseur mort jusqu'au mois suivant."""
    from datetime import datetime, timezone
    t = datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc).timestamp()
    fin = C.echeance_quota("AI_RetryError: you have reached your monthly usage limit, upgrade for higher limits", t)
    assert fin == datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()


def test_l_executeur_reconnait_le_quota_mensuel():
    assert E._RE_QUOTA.search("you (x) have reached your monthly usage limit, upgrade for higher limits")


def test_le_repli_est_verifie_au_census(census, monkeypatch):
    """29/10 soir : 3 taches ont brule leur tentative sur le repli ollama_cloud/gpt-oss:120b deja consigne hors quota
    (mensuel) -- seul le principal etait verifie. Le repli l'est aussi."""
    monkeypatch.setattr(C, "SORTIE", census)
    cfg = {"modele": "groq/openai/gpt-oss-120b", "repli_ollama_cloud": "gpt-oss:120b"}
    assert E._repli_hors_quota(cfg) is None
    C.consigner_quota_epuise("ollama_cloud", "gpt-oss:120b", "you have reached your monthly usage limit")
    assert E._repli_hors_quota(cfg)
    assert E._repli_hors_quota({"modele": "groq/openai/gpt-oss-120b"}) is None   # sans repli : rien a dire


def test_l_epuisement_d_un_autre_fournisseur_n_est_pas_impute_au_principal(census, monkeypatch):
    """29/10 soir, FAUSSE PANNE mesuree : une erreur « quota exceeded » venue d'un AUTRE fournisseur (providerID=opencode,
    repli ou modele par defaut) a ete consignee sous mistral:codestral-latest (le principal) -- Vibe, qui porte ce
    modele, a ete refuse « MODELE HORS QUOTA » jusqu'a 23 h 56. On ne consigne que l'epuisement du fournisseur CITE."""
    monkeypatch.setattr(C, "SORTIE", census)
    autre = ('level=ERROR run=71814f17 message="stream error" providerID=opencode modelID=big-pickle '
             'error.error="AI_APICallError: quota exceeded"')
    assert E._consigner_quota_principal("mistral/codestral-latest", autre) is None
    assert E._modele_hors_quota("mistral", "codestral-latest", chemin=census) is None
    meme = 'providerID=mistral modelID=codestral-latest error.error="quota exceeded"'
    assert E._consigner_quota_principal("mistral/codestral-latest", meme)


def test_opencode_recoit_la_cle_mistral():
    """29/10 soir : mistral/codestral-latest echouait AVANT tout appel (aucune trace providerID=mistral au journal
    OpenCode) -- _CLE_PAR_FOURNISSEUR n'avait pas d'entree mistral, la cle n'etait jamais passee a l'instance (meme
    motif que le « model not found » du 17/10)."""
    assert E._env_cle_fournisseur("mistral/codestral-latest") == "MISTRAL_API_KEY"


def test_simple_debit_429_n_est_pas_un_epuisement(census):
    avant = census.read_text(encoding="utf-8")
    assert C.echeance_quota("429 Too Many Requests", T0) is None
    assert C.consigner_quota_epuise("groq", "m", "429 Too Many Requests", maintenant=T0, chemin=census) is None
    assert census.read_text(encoding="utf-8") == avant


def test_verdict_existant_preserve(census):
    C.consigner_quota_epuise("openrouter", "nvidia/nemotron", "quota exceeded", maintenant=T0, chemin=census)
    v = json.loads(census.read_text(encoding="utf-8"))["verdicts"]["openrouter:nvidia/nemotron"]
    assert v["joignable"] is True and v["outils"] is True and v["mesure_le"] == "2026-10-21T16:08:34"
    assert v["quota_epuise_jusqu_a"] > T0 and "quota exceeded" in v["quota_motif"]


def test_census_illisible_jamais_ecrase(tmp_path):
    p = tmp_path / "free_tier_census.json"
    p.write_text("{ pas du json", encoding="utf-8")
    assert C.consigner_quota_epuise("groq", "m", "quota exceeded", maintenant=T0, chemin=p) is None
    assert p.read_text(encoding="utf-8") == "{ pas du json"
    assert E._modele_hors_quota("groq", "m", chemin=p, maintenant=T0) is None


def test_couple_inconnu_du_census_reste_eligible(census):
    assert E._modele_hors_quota("zai", "glm-4.6", chemin=census, maintenant=T0) is None


def test_opencode_consigne_le_principal_puis_le_saute(census, monkeypatch):
    monkeypatch.setattr(C, "SORTIE", census)
    cfg = {"modele": "openrouter/nvidia/nemotron", "repli_ollama_cloud": "gpt-oss:120b"}
    assert E._principal_hors_quota(cfg["modele"], cfg) is None
    assert E._consigner_quota_principal(cfg["modele"], "Rate limit exceeded: free-models-per-day")
    assert E._principal_hors_quota(cfg["modele"], cfg)              # tache suivante : principal saute -> repli direct
    assert E._principal_hors_quota(cfg["modele"], {"modele": cfg["modele"]}) is None   # sans repli : on ne saute pas


def test_modele_sans_fournisseur_inconnu_jamais_consigne(census, monkeypatch):
    monkeypatch.setattr(C, "SORTIE", census)
    assert E._consigner_quota_principal("nemotron", "quota exceeded") is None


@pytest.fixture()
def bus(tmp_path, monkeypatch):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, reaffectations TEXT)")
    c.execute("INSERT INTO tasks VALUES ('t1', 'OPENCODE_DEFAUT3', 'running', 'audit lot 3', NULL)")
    c.commit()
    c.close()
    monkeypatch.setattr(E, "_db", lambda: sqlite3.connect(db))
    monkeypatch.setattr(E, "_executeur_bat", lambda a, max_age_s=None: True)
    monkeypatch.setattr(E, "_executeur_suspendu", lambda a: None)
    monkeypatch.setattr(E, "_FICHIER_REPLI_GRATUIT", tmp_path / "repli_gratuit_seul.switch")
    return db


def test_repli_gratuit_seul_jamais_vers_le_payant(bus, tmp_path):
    (tmp_path / "repli_gratuit_seul.switch").write_text("owner 29/10", encoding="utf-8")
    t = {"id": "t1", "agent": "OPENCODE_DEFAUT3", "description": "audit lot 3"}
    assert E._reaffecter(t, "NON LIVRE", ordre=("CLAUDE_HEADLESS", "MISTRAL")) == "MISTRAL"


def test_repli_gratuit_seul_tout_payant_laissee_sur_place(bus, tmp_path):
    (tmp_path / "repli_gratuit_seul.switch").write_text("owner 29/10", encoding="utf-8")
    t = {"id": "t1", "agent": "OPENCODE_DEFAUT3", "description": "audit lot 3"}
    assert E._reaffecter(t, "NON LIVRE", ordre=("CLAUDE_HEADLESS",)) is None


def test_sans_interrupteur_le_payant_reste_eligible(bus):
    t = {"id": "t1", "agent": "OPENCODE_DEFAUT3", "description": "audit lot 3"}
    assert E._reaffecter(t, "NON LIVRE", ordre=("CLAUDE_HEADLESS",)) == "CLAUDE_HEADLESS"
