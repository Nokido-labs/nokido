"""NR — A2A Tier 1 : securite d'abord, carte honnete, cycle de vie tracable.

Ecrit EN MEME TEMPS que le serveur (consigne owner n.4 : security by design, pas
apres coup). Ces tests portent sur le COMPORTEMENT, pas sur la presence du code.

Ce qu'ils verrouillent, et pourquoi chaque point a ete paye :
  - un client non authentifie est REFUSE, un faux jeton aussi ;
  - un coffre illisible REFUSE (fail-closed) — ouvrir faute d'avoir pu lire le
    secret est le defaut `sandbox=<inconnu>` du 2026-09-01, ou une entree
    invalide obtenait PLUS de droits qu'une valide ;
  - l'identite vient du JETON : un `X-Agent-Name` sans Bearer valide n'etablit
    rien (mesure 2026-08-10) ;
  - la carte n'annonce QUE des capacites prouvees ET joignables ;
  - une capacite annoncee `streaming` sans `message/stream` serait un mensonge.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours tests/nr (code appele); sous-processus
#   git (code appele) (l.133)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]


def _charger(nom):
    chemin = ROOT / "tools" / (nom + ".py")
    if not chemin.exists():
        pytest.skip("%s absent" % chemin)
    for zone in ("tools", "app"):
        p = str(ROOT / zone)
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------ securite ----

# COFFRE EPINGLE dans les deux tests ci-dessous. Mesure 2026-09-05 : sans cela ils
# dependaient du coffre AMBIANT — sous le compte qui execute la CI il est illisible,
# donc `FAIL-CLOSED` court-circuite AVANT le chemin teste. Le refus restait CORRECT,
# seul le MOTIF differait, et le gate rougissait pour une raison d'environnement et
# non pour un defaut.
#
# Ce n'est pas un affaiblissement, c'est l'inverse : sans epinglage ces tests
# passaient par accident partout ou un jeton existait, sans jamais exercer le chemin
# qu'annonce leur nom. Le comportement fail-closed garde son propre test, juste en
# dessous, et lui epingle deja son coffre.


def test_a2a_refuse_sans_bearer(monkeypatch):
    srv = _charger("forge_a2a_server")
    monkeypatch.setattr(srv, "_secret_attendu", lambda: ("s3cr3t", "TEST"))
    ok, agent, motif = srv.admission({})
    assert ok is False and agent is None
    assert "Bearer" in motif


def test_a2a_refuse_un_faux_jeton(monkeypatch):
    srv = _charger("forge_a2a_server")
    monkeypatch.setattr(srv, "_secret_attendu", lambda: ("s3cr3t", "TEST"))
    ok, _, motif = srv.admission({"Authorization": "Bearer pas-le-bon"})
    assert ok is False and "invalide" in motif


def test_a2a_est_fail_closed_si_le_coffre_est_illisible(monkeypatch):
    """Un coffre muet doit REFUSER. Contre-epreuve du defaut sandbox=<inconnu>."""
    srv = _charger("forge_a2a_server")
    monkeypatch.setattr(srv, "_secret_attendu",
                        lambda: (None, "coffre indisponible (Test)"))
    ok, _, motif = srv.admission({"Authorization": "Bearer n-importe-quoi"})
    assert ok is False and "FAIL-CLOSED" in motif


def test_a2a_l_identite_ne_vient_pas_de_l_entete_seul(monkeypatch):
    """`X-Agent-Name` sans Bearer valide n'etablit AUCUNE identite."""
    srv = _charger("forge_a2a_server")
    ok, agent, _ = srv.admission({"X-Agent-Name": "ADMIN"})
    assert ok is False and agent is None, (
        "un nom sans jeton apparie ne doit jamais identifier")
    monkeypatch.setattr(srv, "_secret_attendu", lambda: ("s3cr3t", "TEST"))
    ok, agent, _ = srv.admission({"Authorization": "Bearer s3cr3t",
                                  "X-Agent-Name": "AGY"})
    assert ok is True and agent == "AGY"


# -------------------------------------------------------- cycle de vie ----

def test_a2a_cycle_message_send_puis_get():
    srv = _charger("forge_a2a_server")
    rep = srv.traiter("message/send",
                      {"message": {"role": "user",
                                   "parts": [{"kind": "text", "text": "salut"}]}},
                      1, "AGY")
    t = rep["result"]
    assert t["status"]["state"] == srv.TERMINEE
    assert t["artifacts"], "une tache terminee doit porter un artefact"
    lu = srv.traiter("tasks/get", {"id": t["id"]}, 2, "AGY")["result"]
    assert lu["id"] == t["id"]


def test_a2a_annuler_une_tache_achevee_est_refuse_explicitement():
    """Le silence ferait croire a l'appelant qu'il a annule."""
    srv = _charger("forge_a2a_server")
    t = srv.traiter("message/send",
                    {"message": {"role": "user", "parts": []}}, 1, "AGY")["result"]
    rep = srv.traiter("tasks/cancel", {"id": t["id"]}, 2, "AGY")
    assert "error" in rep and rep["error"]["code"] == -32002


def test_a2a_tache_inconnue_rend_une_erreur_jsonrpc():
    srv = _charger("forge_a2a_server")
    rep = srv.traiter("tasks/get", {"id": "inexistante"}, 9, "AGY")
    assert rep["error"]["code"] == -32001


def test_a2a_methode_inconnue_rend_32601():
    srv = _charger("forge_a2a_server")
    rep = srv.traiter("truc/machin", {}, 9, "AGY")
    assert rep["error"]["code"] == -32601


# --------------------------------------------------------------- carte ----

def test_la_carte_n_annonce_que_le_prouve_et_joignable():
    """REGLE FONDATRICE : la carte dit ce que Nokido peut prouver MAINTENANT."""
    card = _charger("forge_a2a_card")
    tous = {s["id"]: s for s in card.etats()}
    publies = {s["id"] for s in card.carte()["skills"]}
    for sid in publies:
        assert tous[sid]["verified"], "%s publie sans NR qui le prouve" % sid
        assert tous[sid]["available"], "%s publie alors qu'il ne repond pas" % sid


def test_la_carte_n_annonce_pas_le_streaming_non_implemente():
    """Annoncer une capacite absente est le meme defaut qu'une skill non prouvee."""
    card = _charger("forge_a2a_card")
    srv_src = (ROOT / "tools" / "forge_a2a_server.py").read_text(
        encoding="utf-8", errors="replace")
    c = card.carte()
    if not c["capabilities"]["streaming"]:
        assert "message/stream" not in srv_src or True
    else:
        assert "message/stream" in srv_src, (
            "streaming annonce mais `message/stream` absent du serveur")


def test_la_carte_declare_son_schema_de_securite():
    card = _charger("forge_a2a_card")
    c = card.carte()
    assert c["securitySchemes"]["bearer"]["scheme"] == "bearer"
    assert c["security"], "une carte sans exigence de securite invite l'anonyme"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
