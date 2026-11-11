"""NR -- une perte du hub par un agent se voit (mesure du 6/11).

AGY a perdu tout le hub a 11:33 (famille OAuth revoquee) et a tourne jusqu'a 15:10 sans aucun outil MCP, sans alerte ni
marque. Deux signaux : une alerte a la revocation, et `[HUB ABSENT]` dans l'effet quand l'agent dit ne pas avoir le hub.
La marque ne change pas le verdict. Les phrases positives sont les vraies reponses d'AGY du 6/11.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app import forge_oauth_clients as C
from app import forge_signature_hub as S

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
RES = "http://127.0.0.1:8766/mcp"
ISS = "http://127.0.0.1:8766"
VERIF = "v" * 50
DEFI = base64.urlsafe_b64encode(hashlib.sha256(VERIF.encode()).digest()).rstrip(b"=").decode()
REDIR = "http://127.0.0.1:40123/callback"


@pytest.fixture(scope="module")
def executeur():
    spec = importlib.util.spec_from_file_location("hub_absent_executeur_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["hub_absent_executeur_nr"] = m
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("texte", [
    "Je n'ai aucun outil du hub Nokido dans cette session.",
    "Dossier du débat non lu : cette session n'a aucun outil du hub, et lire C:/tmp aurait arrêté la session.",
    "Je n'ai pas pu lire le dossier : je n'ai pas d'outil `read` du hub, et la lecture hors du worktree est refusée.",
    "Serveurs MCP visibles : aucun.",
])
def test_vraies_reponses_sans_hub_sont_reconnues(executeur, texte):
    assert executeur.hub_absent_dans_rendu(texte)


@pytest.mark.parametrize("texte", [
    "J'ai appelé `hub` et `read` par le hub : nokido-oauth connecté.",
    "Le hub n'a aucun outil non listé dans la table, c'est le défaut à corriger.",
    "Un outil absent de la table passe par défaut.",
    "",
])
def test_un_rendu_qui_parle_du_hub_ne_declenche_pas(executeur, texte):
    assert not executeur.hub_absent_dans_rendu(texte)


def test_la_marque_ne_change_pas_le_verdict(executeur):
    effet = "[effet observe] commits produits : 1 (a..b) ; fichiers non commites : 0 ; " + executeur.MARQUE_HUB_ABSENT
    assert executeur._statut_livraison(True, effet) == "SUCCESS"


def test_la_marque_precede_la_finalisation_de_l_effet():
    """Posee apres `_finaliser_effet`, elle n'atteindrait jamais le resultat de la tache."""
    src = (RACINE / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    f = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_delegate_to_agy")
    corps = "\n".join(src.splitlines()[f.lineno - 1:f.end_lineno])
    assert corps.index("hub_absent_dans_rendu(") < corps.index("_finaliser_effet(")


class Horloge:
    t = 1_800_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def autorite(tmp_path):
    coffre = {}
    sig = S.obtenir_signataire(nom_cle="test-hub-absent", tpm=False, lire=coffre.get, ecrire=coffre.__setitem__)
    return C.AutoriteClientsHub(tmp_path, sig, RES, ISS, horloge=Horloge())


def _rejeu_hors_fenetre(a):
    c, err = a.inscrire({"redirect_uris": ["http://127.0.0.1:1/callback"], "client_name": "Google Antigravity"})
    assert err is None
    did, err, _, _ = a.demander_autorisation({
        "response_type": "code", "client_id": c["client_id"], "redirect_uri": REDIR, "code_challenge": DEFI,
        "code_challenge_method": "S256", "resource": RES, "scope": "mcp:hub", "state": "s"})
    assert err is None
    code = parse_qs(urlsplit(a.accorder(did, identite="OAUTH_AGY", ring=1)).query)["code"][0]
    _, c1 = a.jeton({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIR, "client_id": c["client_id"],
                     "code_verifier": VERIF, "resource": RES})
    st, _c2 = a.jeton({"grant_type": "refresh_token", "refresh_token": c1["refresh_token"], "client_id": c["client_id"]})
    assert st == 200
    return a.jeton({"grant_type": "refresh_token", "refresh_token": c1["refresh_token"], "client_id": c["client_id"]}), c1


def test_un_magasin_hors_production_n_alerte_jamais_l_owner(autorite, monkeypatch):
    """Paye le 6/11 : les NR OAuth ont envoye a l'owner « famille revoquee pour VS Code », client de fixture, a 15:19."""
    vues = []
    monkeypatch.setattr(C, "_emettre_alerte", lambda *a: vues.append(a) or "ok")
    (st, _e), _c1 = _rejeu_hors_fenetre(autorite)
    assert st == 400 and vues == []


def test_revocation_alerte_avec_le_nom_du_client_sans_jeton(autorite, monkeypatch, tmp_path):
    vues = []
    monkeypatch.setattr(C, "dossier_defaut", lambda: tmp_path)
    monkeypatch.setattr(C, "_emettre_alerte", lambda *a: vues.append(a) or "ok")
    (st, e), c1 = _rejeu_hors_fenetre(autorite)
    assert st == 400 and e["error"] == "invalid_grant"
    assert len(vues) == 1 and "Google Antigravity" in vues[0][2]
    assert vues[0][1] == "high"
    assert c1["refresh_token"] not in repr(vues)


def test_une_panne_d_alerte_ne_casse_pas_l_oauth(autorite, monkeypatch, tmp_path):
    def casse(*_a):
        raise RuntimeError("alerte en panne")
    monkeypatch.setattr(C, "dossier_defaut", lambda: tmp_path)
    monkeypatch.setattr(C, "_emettre_alerte", casse)
    (st, e), _c1 = _rejeu_hors_fenetre(autorite)
    assert st == 400 and e["error"] == "invalid_grant"


def test_le_canal_d_alerte_existe():
    from app import forge_critical_events as ce
    assert callable(ce.alerter_owner)
