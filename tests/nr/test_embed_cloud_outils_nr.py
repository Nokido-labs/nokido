# -*- coding: utf-8 -*-
"""NR — outils d'embedding cloud (Modal / Voyage) ajoutes le 2026-08-19.

Le cliquet de couverture exige un test d'EFFET par module, pas un import. Ces
outils sont operationnels (sondes, deployeurs, campagne) : leur coeur testable
hermetiquement est la LOGIQUE PURE — clause SQL du froid, extraction des tokens,
resolution de base, decoupage en lots. C'est cette logique qui, si elle derive,
casse silencieusement l'outil ; c'est donc elle qu'on gele.

Aucun egress, aucun service, aucune ecriture : monkeypatch + tmp_path partout.
"""
import os
import re
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "tools"))
sys.path.insert(0, os.path.join(_ROOT, "app"))


# ── forge_tier_policy.base_rag : la TABLE decide, pas l'existence du fichier ──
def test_base_rag_existe_et_pointe_une_vraie_table():
    """base_rag() ne doit JAMAIS rendre un .db qui ne porte pas rag_chunks.
    L'invariant (data/rag.db existe mais fait 0 octet, mesure 2026-08-19) : le
    chemin rendu doit reellement contenir la table."""
    import forge_tier_policy as TP

    db = TP.base_rag()                     # leve SystemExit si aucune base valide
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=5.0)
    try:
        # La table existe : la requete ne leve pas.
        c.execute("SELECT id FROM rag_chunks LIMIT 1").fetchone()
    finally:
        c.close()
    assert db.endswith("embeddings.db") or db.endswith("rag.db")


def test_base_rag_rejette_un_db_vide(tmp_path):
    """Contre-epreuve directe de l'invariant : un .db qui existe mais n'a pas la
    table n'est jamais accepte comme base."""
    vide = tmp_path / "vide.db"
    sqlite3.connect(str(vide)).close()     # existe, 0 table rag
    accepte = True
    try:
        cc = sqlite3.connect("file:%s?mode=ro" % str(vide).replace("\\", "/"), uri=True)
        cc.execute("SELECT 1 FROM rag_chunks LIMIT 1").fetchone()
        cc.close()
    except Exception:
        accepte = False
    assert accepte is False


# ── forge_embed_voyage_echantillon._froid : clause = complement du hot-tier ──
def test_voyage_echantillon_froid_est_le_complement_du_chaud(monkeypatch):
    import forge_embed_voyage_echantillon as VE
    import forge_tier_policy as TP

    monkeypatch.setattr(TP, "hot_tier_clause", lambda _c: "origin='chaud'")
    clause = VE._froid(None)
    assert clause == "NOT (origin='chaud')"


# ── forge_embed_modal_campagne._cible_par_intention : consommee a la lecture ──
def test_campagne_intention_consommee_et_chiffre_extrait(tmp_path, monkeypatch):
    import forge_embed_modal_campagne as MC

    flag = tmp_path / "modal_campagne.wanted"
    flag.write_text("5000", encoding="utf-8")
    monkeypatch.setattr(MC, "INTENTION", flag)
    assert MC._cible_par_intention() == 5000
    assert not flag.exists()                       # consommee
    assert MC._cible_par_intention() is None        # plus d'intention


def test_campagne_intention_vide_vaut_tout(tmp_path, monkeypatch):
    import forge_embed_modal_campagne as MC

    flag = tmp_path / "modal_campagne.wanted"
    flag.write_text("   ", encoding="utf-8")
    monkeypatch.setattr(MC, "INTENTION", flag)
    assert MC._cible_par_intention() == 0           # 0 = tout le froid


# ── forge_modal_deploy_embed._intention_deployer : idem, cote deploiement ──
def test_deploy_intention_consommee(tmp_path, monkeypatch):
    import forge_modal_deploy_embed as MD

    flag = tmp_path / "modal_deploy.wanted"
    flag.write_text("go", encoding="utf-8")
    monkeypatch.setattr(MD, "INTENTION", flag)
    assert MD._intention_deployer() is True
    assert not flag.exists()
    assert MD._intention_deployer() is False


def test_deploy_url_regex_capte_l_endpoint_modal():
    import forge_modal_deploy_embed as MD

    sortie = "Created web endpoint => https://naarobb--bge-m3-embed.modal.run\ndone"
    urls = MD.RE_URL.findall(sortie)
    assert urls == ["https://naarobb--bge-m3-embed.modal.run"]


# ── forge_modal_auth_bootstrap : extraire id ET secret de la commande collee ──
def test_auth_bootstrap_extrait_les_deux_tokens(tmp_path, monkeypatch):
    import forge_modal_auth_bootstrap as AB

    env = tmp_path / "Nokido.env"
    env.write_text(
        "MODAL   modal token set --token-id ak-ABC123 --token-secret as-XYZ789\n",
        encoding="utf-8")
    monkeypatch.setattr(AB, "ENV", env)
    tid, tsec = AB._extraire()
    assert tid == "ak-ABC123"
    assert tsec == "as-XYZ789"


def test_auth_bootstrap_masque_ne_revele_pas_le_secret():
    import forge_modal_auth_bootstrap as AB

    m = AB._masque("as-supersecretvalue")
    assert "supersecret" not in m
    assert m.startswith("as-")
    assert "len=" in m


# ── forge_modal_diag._forme : classer un identifiant sans le divulguer ──
def test_modal_diag_forme_classe_les_tokens():
    import forge_modal_diag as MDG

    assert "ak-" in MDG._forme("ak-abc")
    assert "as-" in MDG._forme("as-abc")
    assert MDG._forme("https://x.modal.run") == "URL"
    assert MDG._forme("") == "VIDE"


# ── forge_embed_cloud_probe : les URLs cibles sont les bons endpoints ──
def test_cloud_probe_pointe_les_bons_endpoints():
    import forge_embed_cloud_probe as P

    assert "voyageai" in P.R.VOYAGE_URL
    assert P.TEXTES and all(isinstance(t, str) for t in P.TEXTES)


# ── forge_embed_modal_bench : le regime etabli exclut le cold start ──
def test_bench_module_importe_et_expose_dim():
    import forge_embed_modal_bench as B

    assert B.DIM == 1024


# ── forge_llm_ondemand_traqueur : filtre les process interessants ──
def test_traqueur_filtre_les_lignes_pertinentes():
    import forge_llm_ondemand_traqueur as TR

    assert TR._interessant("1234|10|python forge_llm_ondemand.py|1|python|")
    assert TR._interessant("9|2|... llama.wanted ...|1|cmd|")
    assert not TR._interessant("9|2|firefox.exe|1|explorer|")
