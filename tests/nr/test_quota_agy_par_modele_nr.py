# -*- coding: utf-8 -*-
"""NR -- Quota AGY par modele, lecture de l'echeance « Resets in ... », et repli intelligent (owner 6/11).

Contrat V3 :
1. Pas de groupes de modeles en dur dans l'executeur : forge_palier_effort.resoudre est la seule source.
   Replis declares dans forge_palier_effort.REPLIS.
2. Dans _noter_indisponibilite, ne jamais deviner par _modele_agy(texte) : le modele vient du parametre modele,
   ou d'un nom lu dans le message. Sinon cible = AGY entier avec mention modele inconnu.
3. surface_est_indisponible : TypeError/ValueError sur jusqu_a ne sont pas muets -> log.warning marque illisible.
4. Tracker distingue illisible et inconnu ; l'executeur les ecarte comme non disponibles prouves.
5. _fetch_agy_models_quota gere float corrompu -> status 'illisible' pour ce modele. Liste issue de la table.
6. Une tache M ne part JAMAIS sur Opus si la table dit flash.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_task_executor as te  # noqa: E402
import forge_quota_tracker as qt  # noqa: E402
import forge_palier_effort as pe  # noqa: E402

MSG_QUOTA_REEL = (
    "Individual quota reached. Please upgrade your subscription to increase your limits. "
    "Resets in 2h14m24s."
)

pytestmark = pytest.mark.timeout(60)


@pytest.fixture(autouse=True)
def clean_indispo(tmp_path, monkeypatch):
    sb = tmp_path / "sandbox"
    sb.mkdir(parents=True, exist_ok=True)
    f_indispo = sb / "surfaces_indisponibles.json"
    f_indispo.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(te, "_FICHIER_INDISPO", f_indispo)
    monkeypatch.setattr(te, "_SURFACES_INDISPONIBLES", {})
    monkeypatch.setattr(qt, "ROOT", tmp_path)
    return f_indispo


def test_point1_source_unique_table_et_tache_M_ne_part_jamais_sur_opus():
    """Point 1 : forge_palier_effort.resoudre reste la SEULE source du modele.
    Une tache M ne part JAMAIS sur Opus si la table dit flash."""
    maintenant = time.time()
    # Par defaut la table dit gemini-3.8-flash-low pour taille M
    m = te._modele_agy("taille: M", maintenant=maintenant)
    assert m == "gemini-3.8-flash-low"
    assert "opus" not in (m or "").lower()

    # Si flash est epuise, la table declare son repli vers claude-sonnet-5-5-low, toujours pas Opus
    te._noter_indisponibilite("AGY", "RIEN PRODUIT", MSG_QUOTA_REEL, modele="gemini-3.8-flash-low")
    m_repli = te._modele_agy("taille: M", maintenant=maintenant)
    assert m_repli == "claude-sonnet-5-5-low"
    assert "opus" not in (m_repli or "").lower()

    # Verification que _GROUPES_MODELES_AGY n'existe pas dans te
    assert not hasattr(te, "_GROUPES_MODELES_AGY")


def test_point1_repli_epuise_rend_none_ou_modelehorsquota():
    """Point 1 suite : Tous replis epuises -> _modele_agy rend None (qui met en pending sans reaffectation)."""
    maintenant = time.time()
    te._noter_indisponibilite("AGY", "RIEN PRODUIT", MSG_QUOTA_REEL, modele="gemini-3.8-flash-low")
    te._noter_indisponibilite("AGY", "RIEN PRODUIT", MSG_QUOTA_REEL, modele="claude-sonnet-5-5-low")
    assert te._modele_agy("taille: M", maintenant=maintenant) is None


def test_point2_noter_indisponibilite_sans_modele_agy_et_cible_agy_inconnu():
    """Point 2 : Ne jamais appeler _modele_agy(texte) dans _noter_indisponibilite.
    Si le modele n'est pas passe ou lu dans le texte, cible AGY entier avec motif modele inconnu."""
    maintenant = time.time()
    # Appel sans modele explicite et sans modele dans le message
    ok = te._noter_indisponibilite("AGY", "quota exceeded", MSG_QUOTA_REEL)
    assert ok is True

    # Cible marquee est AGY (pas un sous-modele devine a tort)
    indisp_agy = te.surface_est_indisponible("AGY", maintenant)
    assert indisp_agy is not None
    assert "[modele inconnu]" in indisp_agy

    # Avec modele passe en argument explicite
    ok2 = te._noter_indisponibilite("AGY", "quota exceeded", MSG_QUOTA_REEL, modele="gemini-3.8-flash-low")
    assert ok2 is True
    assert te.surface_est_indisponible("gemini-3.8-flash-low", maintenant) is not None


def test_point3_surface_est_indisponible_non_muet_sur_valeur_corrompue(caplog):
    """Point 3 : surface_est_indisponible ne doit pas etre muet sur TypeError/ValueError."""
    sb = qt.ROOT / "sandbox"
    f_indispo = sb / "surfaces_indisponibles.json"
    # Entree avec jusqu_a corrompu (string non convertible en float)
    f_indispo.write_text(json.dumps({"AGY:GEMINI-3.8-FLASH-LOW": {"jusqu_a": "invalide_timestamp", "motif": "err"}}), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        res = te.surface_est_indisponible("gemini-3.8-flash-low")
        assert res is None
        assert any("marque illisible dans registre indispo" in record.message for record in caplog.records)


def test_point4_tracker_et_executeur_distinguent_illisible_et_inconnu():
    """Point 4 : illisible et inconnu ne sont ni disponibles prouves ni epuises.
    L'executeur ne les considere pas comme disponibles prouves."""
    sb = qt.ROOT / "sandbox"
    f_indispo = sb / "surfaces_indisponibles.json"
    f_indispo.write_text("{corrupt_json", encoding="utf-8")

    q = qt.get_quota("agy")
    assert "models" in q
    for m, minfo in q["models"].items():
        assert minfo["status"] == "illisible"
    assert q.get("agy_status", {}).get("status") == "illisible"
    assert q.get("agy_status", {}).get("ok") is False

    # Absence de registre
    f_indispo.write_text("{}", encoding="utf-8")
    q2 = qt.get_quota("agy")
    for m, minfo in q2["models"].items():
        assert minfo["status"] == "inconnu"
    assert q2.get("agy_status", {}).get("status") == "inconnu"
    assert q2.get("agy_status", {}).get("ok") is False


def test_point5_fetch_agy_models_quota_valeur_corrompue_rend_illisible():
    """Point 5 : entry.get('jusqu_a') corrompu rend 'illisible' pour ce modele.
    La liste de modeles vient de la table."""
    sb = qt.ROOT / "sandbox"
    f_indispo = sb / "surfaces_indisponibles.json"
    f_indispo.write_text(json.dumps({
        "AGY:GEMINI-3.8-FLASH-LOW": {"jusqu_a": "pas_un_float"},
        "AGY:CLAUDE-SONNET-5-5-LOW": {"jusqu_a": time.time() + 3600, "motif": "quota"}
    }), encoding="utf-8")

    q = qt.get_quota("agy")
    models = q.get("models", {})
    assert models["gemini-3.8-flash-low"]["status"] == "illisible"
    assert models["claude-sonnet-5-5-low"]["status"] == "quota_reached"
    # Les modeles suivis proviennent bien de la table
    table_models = set(qt._modeles_suivis_agy())
    assert set(models.keys()) == table_models


def _ecrire_registre(contenu):
    (qt.ROOT / "sandbox" / "surfaces_indisponibles.json").write_text(contenu, encoding="utf-8")


def test_point6_taille_L_inconnu_ne_prend_pas_la_grosse_tache_sans_panne():
    """UNKNOWN n'est ni sain ni epuise : L attend (None = pending), sans marque d'indisponibilite."""
    maintenant = time.time()
    _ecrire_registre("{}")
    assert te._modele_agy("taille: L", maintenant=maintenant) is None
    assert te.surface_est_indisponible("AGY", maintenant) is None
    assert te.surface_est_indisponible("gemini-3.8-flash-medium", maintenant) is None
    # S et M inchanges
    assert te._modele_agy("taille: M", maintenant=maintenant) == "gemini-3.8-flash-low"


def test_point6_taille_L_illisible_ne_prend_pas_la_grosse_tache():
    maintenant = time.time()
    _ecrire_registre("{corrupt_json")
    assert te._modele_agy("taille: L", maintenant=maintenant) is None
    assert te.surface_est_indisponible("AGY", maintenant) is None


def test_point6_taille_L_ok_prouve_prend_la_grosse_tache():
    maintenant = time.time()
    _ecrire_registre(json.dumps({"AGY:GEMINI-3.8-FLASH-MEDIUM": {"status": "ok", "marque": maintenant, "jusqu_a": 0}}))
    assert te._modele_agy("taille: L", maintenant=maintenant) == "gemini-3.8-flash-medium"


# ---- etat sain `ok` : ecrivain, expiration, preuve S/M, attente L explicite ----
def test_ok_ecrit_par_le_meme_registre_et_L_part():
    maintenant = time.time()
    assert te._modele_agy("taille: L", maintenant=maintenant) is None
    assert te._noter_succes_agy("gemini-3.8-flash-medium") is True
    e = te._lire_indispo()["AGY:GEMINI-3.8-FLASH-MEDIUM"]
    assert e["status"] == "ok" and e["marque"] > 0
    assert te._modele_agy("taille: L", maintenant=maintenant) == "gemini-3.8-flash-medium"
    assert qt._fetch_agy_models_quota()["gemini-3.8-flash-medium"]["status"] == "ok"


def test_ok_expire_puis_inconnu(monkeypatch):
    te._noter_succes_agy("gemini-3.8-flash-medium")
    monkeypatch.setenv("LAFORGE_AGY_OK_TTL_S", "0")
    assert qt._fetch_agy_models_quota()["gemini-3.8-flash-medium"]["status"] == "inconnu"
    assert te._modele_agy("taille: L") is None


def test_ok_sans_horodatage_n_est_pas_une_preuve():
    _ecrire_registre(json.dumps({"AGY:GEMINI-3.8-FLASH-MEDIUM": {"status": "ok", "jusqu_a": 0}}))
    assert qt._fetch_agy_models_quota()["gemini-3.8-flash-medium"]["status"] == "inconnu"


def test_succes_S_ou_M_vaut_ok_et_quota_ulterieur_l_emporte():
    te._noter_succes_agy("gemini-3.8-flash-low")  # modele de M
    assert qt._fetch_agy_models_quota()["gemini-3.8-flash-low"]["status"] == "ok"
    te._noter_indisponibilite("AGY", "RIEN PRODUIT", MSG_QUOTA_REEL, modele="gemini-3.8-flash-low")
    assert qt._fetch_agy_models_quota()["gemini-3.8-flash-low"]["status"] == "quota_reached"


def test_succes_sans_modele_ne_note_rien():
    assert te._noter_succes_agy("") is False
    assert te._lire_indispo() == {}


def test_attente_L_longue_message_explicite(caplog, monkeypatch):
    t0 = time.time()
    monkeypatch.setattr(te, "_L_ATTENTE_DEPUIS", {})
    with caplog.at_level(logging.WARNING):
        te._modele_agy("taille: L", maintenant=t0)
        te._modele_agy("taille: L", maintenant=t0 + 4 * 3600)
    msgs = " ".join(r.message for r in caplog.records)
    assert "aucune preuve" in msgs and "tache S ou M" in msgs and "4h" in msgs


def test_L_en_attente_ni_marque_ni_reaffectee():
    _ecrire_registre("{}")
    assert te._modele_agy("taille: L") is None
    assert te._lire_indispo() == {}  # aucune panne declaree


def test_echeance_resets_in():
    maintenant = 1730910000.0
    attendu = maintenant + 8064.0
    assert te.echeance_quota(MSG_QUOTA_REEL, maintenant=maintenant) == attendu
