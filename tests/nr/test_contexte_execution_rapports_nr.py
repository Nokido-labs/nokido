"""NR -- sous quel contexte une mesure tourne, et les rapports le disent (24/10).

Une meme sonde rend des resultats differents selon le compte : LaForgeSbxOffline n'a pas de reseau, LaForgeSbxOnline
ne lit ni les FORGE_TOKEN_* ni les sessions OAuth du profil owner, sous SYSTEM Path.home() vaut systemprofile. Deux
mesures incomparables ne doivent plus etre melangees sans que le rapport dise sous quel compte/profil/reseau il a ete
produit. Aucun test ne touche le reseau ni un vrai coffre.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_free_tier_census as C  # noqa: E402
import forge_process_inventory as P  # noqa: E402
import forge_provider_catalogue as CAT  # noqa: E402

CLES = {"compte", "profil_reel", "reseau", "coffre_lisible", "est_service"}
SENTINELLE = {"compte": "TEST", "profil_reel": "C:/owner", "reseau": "INCONNU",
              "coffre_lisible": "INCONNU", "est_service": False}


def _sans_reseau(monkeypatch, compte="user"):
    monkeypatch.setenv("LAFORGE_JOB_ONLINE", "0")
    monkeypatch.setattr(P.getpass, "getuser", lambda: compte)
    monkeypatch.setattr(P, "_coffre_lisible", lambda: "INCONNU")


# ---------------------------------------------------------------- forme et cles ---------------------------------------
def test_forme_et_cinq_cles(monkeypatch):
    _sans_reseau(monkeypatch)
    monkeypatch.setenv("LAFORGE_OWNER_HOME", str(Path("C:/Users/owner")))
    ctx = P.contexte_execution()
    assert set(ctx) == CLES and len(ctx) == 5
    assert ctx["compte"] == "user"
    assert ctx["profil_reel"] == str(Path("C:/Users/owner"))
    assert ctx["reseau"] is False
    assert ctx["coffre_lisible"] == "INCONNU"
    assert ctx["est_service"] is False


def test_reseau_inconnu_quand_la_sonde_ne_conclut_pas(monkeypatch):
    monkeypatch.setattr(P, "_drapeau_reseau", lambda: None)
    monkeypatch.setattr(P, "_sonde_reseau", lambda: "INCONNU")
    monkeypatch.setattr(P, "_coffre_lisible", lambda: "INCONNU")
    assert P.contexte_execution()["reseau"] == "INCONNU"


# ---------------------------------------------------------------- coffre ----------------------------------------------
def test_coffre_illisible_donne_inconnu_pas_false(monkeypatch):
    S = pytest.importorskip("nokido_agent.app.forge_secrets")
    monkeypatch.setattr(S, "get_secret", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("coffre muet")))
    assert P._coffre_lisible() == "INCONNU"


def test_coffre_temoin_present_donne_true_sans_rendre_la_valeur(monkeypatch):
    S = pytest.importorskip("nokido_agent.app.forge_secrets")
    monkeypatch.setattr(S, "get_secret", lambda *a, **k: "valeur-secrete")
    r = P._coffre_lisible()
    assert r is True
    assert "valeur-secrete" not in repr(r)


def test_coffre_temoin_absent_donne_false(monkeypatch):
    S = pytest.importorskip("nokido_agent.app.forge_secrets")
    monkeypatch.setattr(S, "get_secret", lambda *a, **k: "")
    assert P._coffre_lisible() is False


# ---------------------------------------------------------------- est_service ------------------------------------------
@pytest.mark.parametrize("compte", ["SYSTEM", r"DESKTOP-1\SYSTEM", "LaForgeSbxOffline",
                                    "LaForgeSbxOnline", "LaForgeTrusted"])
def test_compte_system_ou_laforge_est_un_service(monkeypatch, compte):
    _sans_reseau(monkeypatch, compte)
    assert P.contexte_execution()["est_service"] is True


@pytest.mark.parametrize("compte", ["user", "Administrator"])
def test_compte_ordinaire_n_est_pas_un_service(monkeypatch, compte):
    _sans_reseau(monkeypatch, compte)
    assert P.contexte_execution()["est_service"] is False


# ---------------------------------------------------------------- rapports JSON --------------------------------------
def test_sortie_census_bancs_porte_le_contexte(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "contexte_execution", lambda: dict(SENTINELLE))
    monkeypatch.setattr(C, "SORTIE", tmp_path / "registre_census.json")
    sortie = tmp_path / "bancs.json"
    code = C.main_bancs(
        ["--dimensions", "swarm:free_tier", "--bancs", "outils", "--sortie", str(sortie)],
        appel=lambda cible, modele, req: {"texte": "", "tool_calls": [], "cout_usd": 0.0},
        unites={"swarm:free_tier": ["groq:m"]}, sleep=lambda _s: None)
    assert code == 0
    doc = json.loads(sortie.read_text(encoding="utf-8"))
    assert doc["contexte_execution"] == SENTINELLE


def test_matrice_catalogue_porte_le_contexte(monkeypatch):
    monkeypatch.setattr(CAT, "contexte_execution", lambda: dict(SENTINELLE))
    monkeypatch.setattr(CAT, "construire_matrice", lambda **k: {"mesure_le": "2026-10-24T00:00:00",
                                                                "familles": {}, "fournisseurs": {}})
    vus = {}
    monkeypatch.setattr(CAT, "ecrire_matrice", lambda m: vus.update(m) or True)
    monkeypatch.setattr(CAT.sys, "argv", ["forge_provider_catalogue.py", "--matrice"])
    assert CAT.main() == 0
    assert vus["contexte_execution"] == SENTINELLE
