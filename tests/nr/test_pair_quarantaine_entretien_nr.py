"""NR -- l'entretien AUTOMATIQUE de la quarantaine des pairs ferme ce qui est prouve traite et expire
l'orphelin, sans jamais livrer un texte externe (owner 2026-10-01 : « il faut l'automatiser »).

Vecu : un rendu de claude.ai lu et APPLIQUE (cinq commits) restait « quarantaine » -- l'etat mentait.
Contrat de `entretenir()` :
  - quarantaine + trailer « Traite-pair: <id> » dans un commit d'alpha -> `done`, « traite HORS
    CANAL », verdict ACCEPTED (pas ACHIEVED : l'owner n'a rien autorise). Ni un sha ni une simple
    MENTION ne prouvent : faux positif mesure au premier passage reel (une tache du 29/09 citait sa
    BASE de lecture alpha@54b641e, un changelog citant la plage 54b641efa..64cd9e692 l'a « close »),
    et le commit qui rouvre un depot le nomme aussi ;
  - approuve + cite -> la copie livree est marquee lue, le depot `done` ;
  - quarantaine depuis JOURS_EXPIRATION sans decision -> `rejete` (DENY, rien livre) ;
  - git illisible -> aucune cloture (on ne conclut pas d'une source muette) ; l'expiration reste ;
  - jamais une livraison : l'approbation reste un geste owner.
Bases temporaires (fixture du NR test_pair_quarantaine_nr), commits INJECTES (aucun git reel).
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, ROOT / "tools" / fichier)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def q(tmp_path, monkeypatch):
    pair = _charger("nr_pqe_pair", "forge_pair_mcp.py")
    quar = _charger("nr_pqe_quar", "forge_pair_quarantaine.py")
    m2m = tmp_path / "m2m.db"
    c = sqlite3.connect(m2m)
    c.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
              "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    c.commit()
    c.close()
    for mod in (pair, quar):
        monkeypatch.setattr(mod, "chemin_m2m", lambda: str(m2m))
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app import forge_postal
    monkeypatch.setattr(forge_postal, "DB", tmp_path / "postal.db")
    monkeypatch.setattr(quar, "dossier_capsules", lambda: tmp_path / "capsules_pair")
    monkeypatch.setattr(quar, "geste_owner", lambda: (True, ""))
    monkeypatch.setattr(quar, "_commits_alpha_depuis", lambda iso: pytest.fail("git reel appele"))
    return pair, quar, m2m


def _etat(m2m, ident):
    c = sqlite3.connect(m2m)
    try:
        statut, charge = c.execute("SELECT status, payload FROM agent_messages WHERE id=?", (ident,)).fetchone()
        livres = c.execute("SELECT status FROM agent_messages WHERE correlation_id=? AND id<>?",
                           (ident, ident)).fetchall()
    finally:
        c.close()
    return statut, json.loads(charge), [r[0] for r in livres]


def test_un_depot_dont_l_id_est_cite_est_clos_hors_canal_sans_livraison(q):
    pair, quar, m2m = q
    ident = pair.deposer_fait("client-a", "rendu complet : branche claude/x, commit 938f2d5", "roadmap")["id"]
    commits = [("aaaaaaa1111", "fix(soif): revue claude.ai, branche claude/x, 938f2d59c\n\nTraite-pair: %s\n" % ident),
               ("bbbbbbb2222", "chore: rien a voir 20261001")]
    bilan = quar.entretenir(commits=commits)
    assert bilan["clotures"] == [{"id": ident, "commits": ["aaaaaaa1111"]}]
    statut, charge, livres = _etat(m2m, ident)
    assert statut == "done" and livres == [], "un depot non approuve ne doit JAMAIS etre livre"
    assert "HORS CANAL" in charge["etape"]["observation"]["retour"]
    assert charge["verdict"]["statut"] == "ACCEPTED", "l'owner n'a rien autorise : pas ACHIEVED"


def test_un_sha_seul_ne_prouve_rien_meme_s_il_est_pointe(q):
    """Cas reel du 01/10 : la BASE de lecture citee par une plage de changelog n'est pas un rendu."""
    pair, quar, m2m = q
    ident = pair.deposer_fait("client-a", "reprise en LECTURE SEULE, source alpha@54b641e ; rendu 938f2d5",
                              "roadmap")["id"]
    commits = [("f9e438d8954", "docs(changelog): section du push etendue a 54b641efa..64cd9e692"),
               ("ccccccc3333", "fix: applique 938f2d59c"),
               ("ddddddd4444", "fix(pairs): rouvre %s, clos a tort" % ident)]      # une MENTION n'est pas une preuve
    bilan = quar.entretenir(commits=commits)
    assert bilan["clotures"] == [] and bilan["en_attente"] == [ident]


def test_sans_citation_le_depot_attend(q):
    pair, quar, m2m = q
    ident = pair.deposer_fait("client-a", "commit 938f2d5", "roadmap")["id"]
    bilan = quar.entretenir(commits=[("ddddddd4444", "fix: 12345678 sans lettre ; 9f9f9f9 autre sha")])
    assert bilan["en_attente"] == [ident] and _etat(m2m, ident)[0] == "quarantaine"


def test_un_depot_approuve_puis_cite_est_lu_et_clos(q):
    pair, quar, m2m = q
    ident = pair.deposer_fait("client-a", "NEXT: tester", "roadmap")["id"]
    assert quar.approuver(ident)["ok"]
    bilan = quar.entretenir(commits=[("eeeeeee5555", "feat: applique\n\nTraite-pair: %s" % ident)])
    assert bilan["lus"] == [ident]
    statut, _c, livres = _etat(m2m, ident)
    assert statut == "done" and livres == ["read"]


def test_l_orphelin_expire_apres_le_delai_et_pas_avant(q):
    pair, quar, m2m = q
    ident = pair.deposer_fait("client-a", "sans suite", "roadmap")["id"]
    plus_tard = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=quar.JOURS_EXPIRATION - 1)
    assert quar.entretenir(maintenant=plus_tard, commits=[])["expires"] == []
    bien_plus_tard = plus_tard + datetime.timedelta(days=2)
    assert quar.entretenir(maintenant=bien_plus_tard, commits=[])["expires"] == [ident]
    statut, charge, livres = _etat(m2m, ident)
    assert statut == "rejete" and livres == [] and charge["verdict"]["statut"] == "REFUSED"


def test_git_illisible_ne_clot_rien_mais_l_expiration_tient(q, monkeypatch):
    pair, quar, m2m = q
    ident = pair.deposer_fait("client-a", "commit 938f2d5", "roadmap")["id"]
    monkeypatch.setattr(quar, "_commits_alpha_depuis", lambda iso: None)
    bilan = quar.entretenir()
    assert bilan["clotures"] == [] and bilan["git"].startswith("ILLISIBLE")
    tard = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=quar.JOURS_EXPIRATION + 1)
    assert quar.entretenir(maintenant=tard)["expires"] == [ident]
