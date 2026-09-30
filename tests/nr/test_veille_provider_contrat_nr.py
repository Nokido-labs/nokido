"""NR — contrat provider du digest (Groq primaire, openrouter_free cloud gratuit
de repli, Ollama secondaire local) + curseur.

Ce que ces tests VERROUILLENT, et pourquoi chacun existe :

1. `"-"` dans le releve de sante vaut INCONNU, jamais INDISPONIBLE. C'est la
   regression mesuree du 2026-08-31 : sept abstentions consecutives de
   `veille_digest_auto` sur un Ollama vivant, parce que le lecteur comptait comme
   panne ce que sa propre sonde n'avait PAS PU mesurer.
2. SERVICE_UP / API_READY / MODEL_READY sont separes. Le meme jour : service
   lance, port ouvert, `/api/tags` a 200 -- et `laforge-qwen` absent des douze
   modeles servis. Trois signaux verts pour un chemin mort.
3. Le repli n'est jamais silencieux : `essais` porte le verdict de CHAQUE
   fournisseur consulte.
4. Le curseur `digested_at` n'avance que sur un lot qui a ABOUTI.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_veille_digest as vd  # noqa: E402


# --------------------------------------------------------------------------
# etat_provider — fournisseur distant
# --------------------------------------------------------------------------

def test_1_groq_200_est_ready_avec_son_modele():
    etat, modele, _ = vd.etat_provider("groq", {"par_statut": {"200": ["groq"]}})
    assert etat == "READY"
    assert modele == vd.MODELE_GROQ


def test_2_tiret_vaut_INCONNU_et_pas_indisponible():
    """LA regression. `probe` ne rend "-" que depuis son except generique."""
    etat, _, raison = vd.etat_provider("groq", {"par_statut": {"-": ["groq"]}})
    assert etat == "UNKNOWN"
    assert etat != "API_UNAVAILABLE"
    assert "NON SONDE" in raison


def test_3_un_code_http_reel_vaut_indisponible():
    etat, _, _ = vd.etat_provider("groq", {"par_statut": {"401": ["groq"]}})
    assert etat == "API_UNAVAILABLE"


def test_4_absent_du_releve_vaut_INCONNU():
    etat, _, raison = vd.etat_provider("groq", {"par_statut": {"200": ["cerebras"]}})
    assert etat == "UNKNOWN"
    assert "absent du releve" in raison


def test_5_releve_absent_vaut_INCONNU():
    assert vd.etat_provider("groq", None)[0] == "UNKNOWN"


# --------------------------------------------------------------------------
# etat_provider — Ollama : SERVICE_UP / API_READY / MODEL_READY separes
# --------------------------------------------------------------------------

def test_6_api_non_sondee_vaut_INCONNU():
    etat, _, _ = vd.etat_provider("ollama", None, sonde_locale={"api": None},
                                  modele_local="qwen2.5:latest")
    assert etat == "UNKNOWN"


def test_7_api_injoignable_vaut_API_UNAVAILABLE():
    etat, _, raison = vd.etat_provider(
        "ollama", None, sonde_locale={"api": False, "raison": "URLError"},
        modele_local="qwen2.5:latest")
    assert etat == "API_UNAVAILABLE"
    assert "URLError" in raison


def test_8_catalogue_illisible_vaut_INCONNU():
    etat, _, _ = vd.etat_provider(
        "ollama", None, sonde_locale={"api": True, "catalogue": None},
        modele_local="qwen2.5:latest")
    assert etat == "UNKNOWN"


def test_9_modele_absent_du_catalogue_vaut_MODEL_UNAVAILABLE():
    """Le cas `laforge-qwen` : API a 200, modele fantome."""
    etat, _, raison = vd.etat_provider(
        "ollama", None,
        sonde_locale={"api": True, "catalogue": ["qwen2.5:latest", "llava:7b"],
                      "residents": []},
        modele_local="laforge-qwen")
    assert etat == "MODEL_UNAVAILABLE"
    assert "laforge-qwen" in raison


@pytest.mark.parametrize("voulu,catalogue,resident,attendu", [
    # La config omet `:latest`, le catalogue le porte : MEME modele.
    ("laforge-qwen", ["laforge-qwen:latest"], ["laforge-qwen:latest"], "READY"),
    # L'inverse : config taguee, catalogue nu.
    ("qwen2.5:latest", ["qwen2.5"], ["qwen2.5"], "READY"),
    # Present mais non resident, malgre la difference de tag.
    ("laforge-qwen", ["laforge-qwen:latest"], [], "MODEL_COLD"),
    # Un tag EXPLICITE different reste un autre modele : on ne normalise que
    # `:latest`, jamais deux versions distinctes.
    ("qwen2.5-coder:1.5b", ["qwen2.5-coder:7b"], ["qwen2.5-coder:7b"],
     "MODEL_UNAVAILABLE"),
])
def test_9bis_le_tag_latest_ne_fabrique_pas_un_modele_ABSENT(
        voulu, catalogue, resident, attendu):
    """Erreur payee le 2026-08-31 : `laforge-qwen` juge ABSENT alors que le
    catalogue servait `laforge-qwen:latest`. Chez ollama c'est le meme modele ;
    une comparaison de chaines exactes fabrique un MODEL_UNAVAILABLE faux."""
    etat, _, _ = vd.etat_provider(
        "ollama", None,
        sonde_locale={"api": True, "catalogue": catalogue, "residents": resident},
        modele_local=voulu)
    assert etat == attendu


def test_10_residents_illisibles_valent_INCONNU():
    etat, _, _ = vd.etat_provider(
        "ollama", None,
        sonde_locale={"api": True, "catalogue": ["qwen2.5:latest"], "residents": None},
        modele_local="qwen2.5:latest")
    assert etat == "UNKNOWN"


def test_11_present_mais_non_charge_vaut_MODEL_COLD():
    """PRESENT n'est pas PRET : un 7B froid coute >55 s, le tick vaut 60 s."""
    etat, _, raison = vd.etat_provider(
        "ollama", None,
        sonde_locale={"api": True, "catalogue": ["qwen2.5:latest"], "residents": []},
        modele_local="qwen2.5:latest")
    assert etat == "MODEL_COLD"
    assert "NON CHARGE" in raison


def test_12_resident_vaut_READY():
    etat, modele, _ = vd.etat_provider(
        "ollama", None,
        sonde_locale={"api": True, "catalogue": ["qwen2.5:latest"],
                      "residents": ["qwen2.5:latest"]},
        modele_local="qwen2.5:latest")
    assert etat == "READY"
    assert modele == "qwen2.5:latest"


# --------------------------------------------------------------------------
# choisir_provider — ordre explicite, repli trace, sonde paresseuse
# --------------------------------------------------------------------------

_SONDE_PRETE = {"api": True, "catalogue": ["qwen2.5:latest"],
                "residents": ["qwen2.5:latest"]}


def test_13_groq_prioritaire_quand_il_est_pret():
    prov, modele, etat, essais = vd.choisir_provider(
        {"par_statut": {"200": ["groq"]}}, _SONDE_PRETE, modele_local="qwen2.5:latest")
    assert (prov, etat) == ("groq", "READY")
    assert modele == vd.MODELE_GROQ
    assert len(essais) == 1, "on n'a pas consulte le secondaire pour rien"


def test_14_repli_sur_ollama_TRACE_jamais_silencieux():
    # groq 401 + endpoint openrouter ABSENT du releve -> le repli descend
    # jusqu'a ollama, en TRAcant chaque palier consulte (aucun silencieux).
    prov, modele, etat, essais = vd.choisir_provider(
        {"par_statut": {"401": ["groq"]}}, _SONDE_PRETE, modele_local="qwen2.5:latest")
    assert (prov, etat) == ("ollama", "READY")
    assert [e["provider"] for e in essais] == ["groq", "openrouter_free", "ollama"]
    assert essais[0]["etat"] == "API_UNAVAILABLE"
    assert essais[0]["raison"], "le refus du primaire doit rester lisible"
    assert essais[1]["etat"] == "UNKNOWN", "openrouter absent du releve = INCONNU, pas panne"


def test_14b_cloud_gratuit_prefere_au_local_quand_groq_tombe():
    # Le palier GRATUIT openrouter_free passe AVANT ollama : quand groq est 429
    # et que l'endpoint openrouter repond, on prend le cloud gratuit rapide
    # plutot que le local lent. C'est tout l'interet du palier.
    prov, modele, etat, essais = vd.choisir_provider(
        {"par_statut": {"401": ["groq"], "200": ["openrouter"]}},
        _SONDE_PRETE, modele_local="qwen2.5:latest")
    assert (prov, etat) == ("openrouter_free", "READY")
    assert modele == "openrouter/free"
    assert [e["provider"] for e in essais] == ["groq", "openrouter_free"]
    assert essais[0]["etat"] == "API_UNAVAILABLE"


def test_15_aucun_pret_rend_provider_vide_et_TOUS_les_refus():
    prov, _, _, essais = vd.choisir_provider(
        {"par_statut": {"401": ["groq"]}},
        {"api": True, "catalogue": ["qwen2.5:latest"], "residents": []},
        modele_local="qwen2.5:latest")
    assert prov == ""
    assert [e["provider"] for e in essais] == ["groq", "openrouter_free", "ollama"]
    assert {e["etat"] for e in essais} == {"API_UNAVAILABLE", "UNKNOWN", "MODEL_COLD"}


def test_16_sonde_locale_NON_payee_si_le_primaire_repond():
    """Une sonde qu'on paie sans s'en servir est du temps pris au tick."""
    appels = []

    def _sonde():
        appels.append(1)
        return _SONDE_PRETE

    vd.choisir_provider({"par_statut": {"200": ["groq"]}}, _sonde,
                        modele_local="qwen2.5:latest")
    assert appels == [], "le callable ne doit pas etre evalue"


def test_17_sonde_locale_payee_UNE_fois_si_le_primaire_refuse():
    appels = []

    def _sonde():
        appels.append(1)
        return _SONDE_PRETE

    prov, _, _, _ = vd.choisir_provider({"par_statut": {"-": ["groq"]}}, _sonde,
                                        modele_local="qwen2.5:latest")
    assert prov == "ollama"
    assert appels == [1]


# --------------------------------------------------------------------------
# statuts
# --------------------------------------------------------------------------

@pytest.mark.parametrize("etats,attendu", [
    (["MODEL_COLD"], "SKIPPED_MODEL_UNAVAILABLE"),
    (["MODEL_UNAVAILABLE"], "SKIPPED_MODEL_UNAVAILABLE"),
    (["API_UNAVAILABLE", "MODEL_COLD"], "SKIPPED_MODEL_UNAVAILABLE"),
    (["API_UNAVAILABLE"], "SKIPPED_PROVIDER_UNAVAILABLE"),
    (["UNKNOWN", "UNKNOWN"], "SKIPPED_PROVIDER_UNAVAILABLE"),
])
def test_18_statut_abstention_nomme_la_cause_la_plus_specifique(etats, attendu):
    assert vd.statut_abstention([{"etat": e} for e in etats]) == attendu


@pytest.mark.parametrize("ok,ko,attendu", [
    (3, 0, "DIGEST_OK"),
    (0, 0, "DIGEST_OK"),
    (2, 1, "DIGEST_PARTIAL"),
    (0, 3, "DIGEST_FAILED"),
])
def test_19_statut_digest_porte_sur_les_LOTS(ok, ko, attendu):
    assert vd.statut_digest(ok, ko) == attendu


def test_20_releve_perime_vaut_INCONNU(tmp_path):
    p = tmp_path / "sante.json"
    p.write_text(json.dumps({"ts": time.time() - 5000, "par_statut": {"200": ["groq"]}}))
    assert vd.sante_endpoints(p, ttl=900.0) is None
    p.write_text(json.dumps({"ts": time.time(), "par_statut": {"200": ["groq"]}}))
    assert vd.sante_endpoints(p, ttl=900.0) is not None


def test_21_releve_illisible_vaut_INCONNU(tmp_path):
    p = tmp_path / "casse.json"
    p.write_text("{ pas du json")
    assert vd.sante_endpoints(p) is None
    assert vd.sante_endpoints(tmp_path / "absent.json") is None


# --------------------------------------------------------------------------
# curseur `digested_at`
# --------------------------------------------------------------------------

def _base(tmp_path: Path, docs: list) -> Path:
    db = tmp_path / "veille.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE biblio_raw (id TEXT PRIMARY KEY, title TEXT, "
                 "description TEXT, status TEXT, url TEXT, created_at TEXT)")
    for i, titre in enumerate(docs):
        conn.execute("INSERT INTO biblio_raw VALUES (?,?,?,?,?,?)",
                     ("blr_%02d" % i, titre, "desc " + titre, "promoted",
                      "http://x/%d" % i, "2026-08-%02d" % (i + 1)))
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def digest(tmp_path, monkeypatch):
    """Le module cable sur une base jetable, un rapport jetable, un LLM factice."""
    monkeypatch.setattr(vd, "REPORT", tmp_path / "rapport.md")
    monkeypatch.setattr(vd, "BATCH", 1)          # un document par lot = un verdict par document
    monkeypatch.setattr(vd, "_organs", lambda: "rag")
    monkeypatch.setattr(vd, "_roadmap", lambda: "-")

    def _faux(entries, organs, roadmap, extrait_max=180, provider="", modele=""):
        titre = (entries[0].get("title") or "")
        if "KO" in titre:
            vd._LLM_FAILS += 1     # un lot en echec, exactement comme le vrai
            return []
        return [{"suggestion": "amelioration tiree de %s" % titre, "organe": "rag",
                 "prio": "P1", "src": titre}]

    monkeypatch.setattr(vd, "digest_batch", _faux)
    return vd


def test_22_ensure_curseur_pose_la_colonne_et_est_idempotent(tmp_path):
    db = _base(tmp_path, ["A"])
    conn = sqlite3.connect(db)
    assert "digested_at" not in {r[1] for r in conn.execute("PRAGMA table_info(biblio_raw)")}
    assert vd._ensure_curseur(conn) is True
    assert "digested_at" in {r[1] for r in conn.execute("PRAGMA table_info(biblio_raw)")}
    assert vd._ensure_curseur(conn) is True      # rejoue sans erreur
    conn.close()


def test_23_le_contrat_owner_succes_puis_echec(tmp_path, monkeypatch, digest):
    """A digere -> plus selectionne. B en echec -> toujours selectionnable."""
    db = _base(tmp_path, ["doc A", "doc B KO"])
    monkeypatch.setattr(vd, "DB_PATH", str(db))

    r1 = vd.backfill(limit=10, provider="faux", modele="m")
    assert r1["statut"] == "DIGEST_PARTIAL", r1
    assert (r1["success"], r1["failure"]) == (1, 1)
    assert r1["docs_marques"] == 1, "seul le lot abouti marque son document"

    conn = sqlite3.connect(db)
    marques = dict(conn.execute("SELECT title, digested_at FROM biblio_raw"))
    conn.close()
    assert marques["doc A"] is not None
    assert marques["doc B KO"] is None, "un echec ne doit JAMAIS marquer digested"

    # Tour suivant : A a disparu de la selection, B est repris.
    r2 = vd.backfill(limit=10, provider="faux", modele="m")
    assert r2["documents"] == 1, "le curseur a retire A"
    assert r2["failure"] == 1 and r2["docs_marques"] == 0


def test_24_le_backlog_se_VIDE_quand_tout_reussit(tmp_path, monkeypatch, digest):
    db = _base(tmp_path, ["a", "b", "c"])
    monkeypatch.setattr(vd, "DB_PATH", str(db))
    assert vd.backfill(limit=10, provider="faux", modele="m")["docs_marques"] == 3
    r = vd.backfill(limit=10, provider="faux", modele="m")
    assert (r["documents"], r["batches"]) == (0, 0)
    assert r["statut"] == "DIGEST_OK"


def test_25_marquer_False_mesure_sans_avancer_le_curseur(tmp_path, monkeypatch, digest):
    db = _base(tmp_path, ["a"])
    monkeypatch.setattr(vd, "DB_PATH", str(db))
    r = vd.backfill(limit=10, provider="faux", modele="m", marquer=False)
    assert r["success"] == 1 and r["docs_marques"] == 0
    assert vd.backfill(limit=10, provider="faux", modele="m",
                       marquer=False)["documents"] == 1


def test_26_abstention_ne_touche_NI_la_base_NI_le_LLM(tmp_path, monkeypatch):
    """provider KO -> pas d'appel aveugle, pas de marquage, matiere intacte."""
    db = _base(tmp_path, ["a", "b"])
    monkeypatch.setattr(vd, "DB_PATH", str(db))
    monkeypatch.setattr(vd, "REPORT", tmp_path / "r.md")
    monkeypatch.setattr(vd, "sante_endpoints", lambda *a, **k: {"par_statut": {"401": ["groq"]}})
    monkeypatch.setattr(vd, "sonde_ollama",
                        lambda *a, **k: {"api": True, "catalogue": [], "residents": []})

    def _interdit(*a, **k):
        raise AssertionError("appel LLM alors qu'aucun provider n'est pret")

    monkeypatch.setattr(vd, "digest_batch", _interdit)
    r = vd.backfill(limit=10)
    assert r["statut"] == "SKIPPED_MODEL_UNAVAILABLE"
    assert r["documents"] == 0 and r["docs_marques"] == 0
    conn = sqlite3.connect(db)
    cols = {c[1] for c in conn.execute("PRAGMA table_info(biblio_raw)")}
    assert conn.execute("SELECT COUNT(*) FROM biblio_raw").fetchone()[0] == 2
    conn.close()
    assert "digested_at" not in cols, "abstention avant meme d'ouvrir la base"


def test_27_le_resultat_porte_toute_la_tracabilite(tmp_path, monkeypatch, digest):
    db = _base(tmp_path, ["a"])
    monkeypatch.setattr(vd, "DB_PATH", str(db))
    r = vd.backfill(limit=10, provider="groq", modele=vd.MODELE_GROQ)
    for champ in ("provider", "model", "provider_state", "documents", "batches",
                  "success", "failure", "statut", "suggestions_generated"):
        assert champ in r, champ
    assert (r["provider"], r["model"]) == ("groq", vd.MODELE_GROQ)


def test_28_suggestions_generated_ne_pretend_pas_mesurer_la_connaissance(
        tmp_path, monkeypatch, digest):
    """Deux passes sur la MEME matiere : le compteur ne doit rien promettre.

    Mesure 2026-08-31 : neuf fichiers digeres deux fois ont rendu 9 + 9 lignes,
    dont cinq paires portant la meme idee sur la meme source. La dedup md5 ne
    voit pas une reformulation -- d'ou le nom `suggestions_generated`, qui compte
    des LIGNES, et l'absence de tout champ `knowledge_new`.
    """
    db = _base(tmp_path, ["a"])
    monkeypatch.setattr(vd, "DB_PATH", str(db))
    r = vd.backfill(limit=10, provider="faux", modele="m")
    assert r["suggestions_generated"] == 1
    assert "knowledge_new" not in r
    assert "new_knowledge" not in r


def test_29_la_cause_de_l_echec_remonte_au_resultat(tmp_path, monkeypatch, digest):
    """Un compteur dit COMBIEN d'echecs ; il faut aussi POURQUOI.

    Mesure 2026-08-31 : les appels du digest biblio n'echouaient pas sur le
    modele mais sur le pare-feu de Nokido -- `[FIREWALL] envoi cloud bloque
    (groq) : DLP: 2 donnees sensibles detectees` -- dont le refus etait recu
    comme une reponse ordinaire sans JSON, puis avale lot par lot. Quarante
    jours de « la veille ne produit rien » pour une chaine jamais affichee.
    """
    db = _base(tmp_path, ["doc quelconque"])
    monkeypatch.setattr(vd, "DB_PATH", str(db))
    monkeypatch.setattr(vd, "_LLM_DERNIERE_ERREUR", "")

    def _refus(entries, organs, roadmap, extrait_max=180, provider="", modele=""):
        vd._LLM_FAILS += 1
        vd._LLM_DERNIERE_ERREUR = ("ValueError: pas de JSON dans la reponse groq "
                                   "(132 chars) : '[FIREWALL] envoi cloud bloque'")
        return []

    monkeypatch.setattr(vd, "digest_batch", _refus)
    r = vd.backfill(limit=10, provider="faux", modele="m")
    assert r["statut"] == "DIGEST_FAILED"
    assert "FIREWALL" in r["raison_echec"], "la cause doit etre LISIBLE au resultat"
    assert r["docs_marques"] == 0, "un refus ne marque rien comme digere"
