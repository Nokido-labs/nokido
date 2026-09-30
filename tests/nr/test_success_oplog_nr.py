"""NR — la memoire des corrections enregistre des FAITS, jamais des preuves.

`tools/forge_success_oplog.py` repond a un constat owner du 2026-08-31 : la
documentation dit « ce module DEVRAIT faire X », alors qu'un reflexe a besoin de
« X A ETE FAIT, avec cette procedure, et ca a reussi ». Nokido indexait deja ses
ECHECS (`forge_symptom_index` : symptomes + aveux d'erreur) et pas ses
reussites.

Ce que ces tests protegent :

  1. l'etat epistemique. On ecrit CONSTATE — « un correctif a ete committe pour
     ce symptome » — et JAMAIS PROUVE. Ecrire PROUVE a l'ecriture reviendrait a
     enregistrer une intention deguisee en mesure, le defaut meme qu'on corrige.
  2. le denominateur. « 197 corrections enregistrees » ne veut rien dire sans
     « sur 400 commits examines ».
  3. l'idempotence. Le hook post-commit rejoue ; une memoire qui double ses
     entrees fabrique un consensus a partir d'un seul evenement.

HERMETIQUE : `git` est simule, le journal vit dans `tmp_path`. Aucun test ne
depend de l'historique reel du depot, qui changerait a chaque commit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import forge_success_oplog as op  # noqa: E402


def _git_simule(monkeypatch, sujet, corps="", fichiers=("app/x.py",),
                sha="abc123def456789", date="2026-08-31"):
    def faux(*args, **kw):
        if "-s" in args:
            return "%s\n%s\n%s\n%s" % (sha, date, sujet, corps)
        if "--name-only" in args:
            return "\n".join(fichiers)
        if "log" in args:
            return sha
        return ""
    monkeypatch.setattr(op, "_git", faux)


# ── ce qui compte comme correction ──────────────────────────────────────────
def test_un_feat_n_est_PAS_une_correction(monkeypatch):
    """Creer une capacite n'est pas constater la disparition d'un symptome."""
    _git_simule(monkeypatch, "feat(core): ajouter le verbe introspect")
    assert op.analyser_commit("HEAD") is None


def test_un_fix_est_une_correction_et_son_symptome_est_extrait(monkeypatch):
    _git_simule(monkeypatch, "fix(rag): database is locked sur ecriture concurrente")
    e = op.analyser_commit("HEAD")
    assert e is not None
    assert e["symptome"] == "database is locked sur ecriture concurrente"
    assert e["scope"] == "rag"


def test_un_sujet_sans_prefixe_conventionnel_est_ignore(monkeypatch):
    _git_simule(monkeypatch, "correction du bug de verrou")
    assert op.analyser_commit("HEAD") is None


# ── l'etat epistemique ──────────────────────────────────────────────────────
def test_on_ecrit_CONSTATE_jamais_PROUVE(monkeypatch, tmp_path):
    """Le coeur du contrat : un commit atteste qu'on a REPARE, pas que ca MARCHE."""
    _git_simule(monkeypatch, "fix(hub): le port reste ouvert apres arret")
    e = op.enregistrer("HEAD", log=tmp_path / "log.jsonl")
    assert e["etat"] == op.CONSTATE
    assert e["etat"] != op.PROUVE


def test_un_correctif_sans_test_est_signale_moins_reutilisable(monkeypatch, tmp_path):
    _git_simule(monkeypatch, "fix(core): un truc", fichiers=("app/x.py",))
    assert op.enregistrer("HEAD", log=tmp_path / "a.jsonl")["reutilisable"] is False


def test_un_correctif_avec_test_est_reutilisable(monkeypatch, tmp_path):
    _git_simule(monkeypatch, "fix(core): un truc",
                fichiers=("app/x.py", "tests/nr/test_x_nr.py"))
    e = op.enregistrer("HEAD", log=tmp_path / "b.jsonl")
    assert e["reutilisable"] is True
    assert e["procedure"]["tests_dans_le_commit"] == ["tests/nr/test_x_nr.py"]


# ── idempotence : le hook rejoue ────────────────────────────────────────────
def test_enregistrer_deux_fois_n_ecrit_qu_une_ligne(monkeypatch, tmp_path):
    log = tmp_path / "log.jsonl"
    _git_simule(monkeypatch, "fix(core): symptome unique")
    op.enregistrer("HEAD", log=log)
    op.enregistrer("HEAD", log=log)
    assert len(log.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_une_ligne_corrompue_ne_tue_pas_la_lecture(tmp_path):
    """Un journal append-only finit toujours par contenir une ligne coupee."""
    log = tmp_path / "log.jsonl"
    log.write_text('{"commit":"aaa","jetons":["verrou"],"symptome":"x","date":"d",'
                   '"etat":"CONSTATE"}\n{ceci n est pas du json\n', encoding="utf-8")
    assert op.chercher("verrou", log=log)


# ── le matcher ──────────────────────────────────────────────────────────────
def test_le_matcher_retrouve_par_jetons_communs(monkeypatch, tmp_path):
    log = tmp_path / "log.jsonl"
    _git_simule(monkeypatch, "fix(rag): database is locked sur ecriture concurrente")
    op.enregistrer("HEAD", log=log)
    r = op.chercher("probleme database locked pendant une ecriture", log=log)
    assert r and r[0]["commit"].startswith("abc123")
    assert "database" in r[0]["termes_communs"]


def test_un_verbe_francais_courant_ne_fait_PAS_matcher(tmp_path):
    """Mesure du 2026-08-31 sur le journal reel : sur « le hub REND database is
    locked... », QUATRE des cinq procedures remontees matchaient sur le seul
    jeton « rend ». Le bruit en tete de reponse coute plus cher qu'une reponse
    vide : il fait ouvrir des pistes mortes.
    """
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({
        "commit": "aaa1", "date": "2026-08-01", "etat": "CONSTATE",
        "symptome": "la generation rend le denominateur",
        "jetons": ["generation", "rend", "denominateur"]}) + "\n", encoding="utf-8")
    assert op.chercher("le hub rend une erreur", log=log) == []
    # ... mais un terme de FOND matche toujours.
    assert op.chercher("probleme de generation", log=log)


def test_le_matcher_ne_rend_rien_plutot_que_du_bruit(monkeypatch, tmp_path):
    log = tmp_path / "log.jsonl"
    _git_simule(monkeypatch, "fix(rag): database is locked")
    op.enregistrer("HEAD", log=log)
    assert op.chercher("couleur des boutons du tableau de bord", log=log) == []


def test_journal_absent_rend_une_liste_vide_sans_lever(tmp_path):
    assert op.chercher("quoi que ce soit", log=tmp_path / "jamais.jsonl") == []


# ── le denominateur ─────────────────────────────────────────────────────────
def test_le_backfill_rend_son_denominateur(monkeypatch, tmp_path):
    """« 197 corrections » ne dit rien sans « sur 400 commits examines »."""
    _git_simule(monkeypatch, "fix(core): quelque chose")
    r = op.backfill(1, log=tmp_path / "log.jsonl")
    assert set(r) == {"commits_examines", "correctifs", "non_correctifs"}
    assert r["commits_examines"] == r["correctifs"] + r["non_correctifs"]


# ── promotion d'etat : la colonne PROUVE doit avoir un emetteur ─────────────
def _entree(commit, symptome, jetons, fichiers, tests=(), date="2026-08-01",
            etat=None):
    return {"commit": commit, "date": date, "symptome": symptome,
            "jetons": list(jetons), "etat": etat or op.CONSTATE,
            "procedure": {"fichiers": list(fichiers),
                          "tests_dans_le_commit": list(tests)},
            "reutilisable": bool(tests)}


def _ecrire(chemin, entrees):
    chemin.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entrees),
                      encoding="utf-8")
    return chemin


def test_le_journal_replie_garde_le_DERNIER_etat(tmp_path):
    """Append-only : une promotion s'ajoute, elle ne reecrit pas. La LECTURE
    replie, sinon un meme correctif rendrait deux verdicts contradictoires."""
    log = _ecrire(tmp_path / "log.jsonl", [_entree("aaa", "verrou", ["verrou"], ["a.py"])])
    op.promouvoir("aaa", op.PROUVE, {"tests": ["t.py"]}, log=log)
    e = op.entrees(log)
    assert len(e) == 1
    assert e[0]["etat"] == op.PROUVE
    assert e[0]["symptome"] == "verrou", "la promotion complete, elle n'efface pas"


def test_une_absence_de_recidive_ne_PROMEUT_PAS(tmp_path):
    """Le coeur du contrat. Ne pas avoir revu un defaut ne prouve pas qu'il a
    disparu, seulement qu'on ne l'a pas croise. Une preuve doit etre POSITIVE.
    """
    log = _ecrire(tmp_path / "log.jsonl",
                  [_entree("aaa", "verrou sqlite", ["verrou", "sqlite"], ["a.py"])])
    bilan = op.evaluer(log=log, root=tmp_path, lanceur=lambda t: True)
    assert bilan["prouvees"] == 0
    assert bilan["sans_test"] == 1
    assert op.entrees(log)[0]["etat"] == op.CONSTATE


def test_un_test_VERT_et_gate_en_CI_promeut(tmp_path, monkeypatch):
    log = _ecrire(tmp_path / "log.jsonl",
                  [_entree("aaa", "verrou", ["verrou"], ["a.py"],
                           tests=["tests/nr/test_x_nr.py"])])
    monkeypatch.setattr(op, "_tests_gates", lambda root: {"tests/nr/test_x_nr.py"})
    bilan = op.evaluer(log=log, root=tmp_path, lanceur=lambda t: True)
    assert bilan["prouvees"] == 1
    assert op.entrees(log)[0]["etat"] == op.PROUVE


def test_un_test_ROUGE_ne_promeut_pas(tmp_path, monkeypatch):
    log = _ecrire(tmp_path / "log.jsonl",
                  [_entree("aaa", "verrou", ["verrou"], ["a.py"],
                           tests=["tests/nr/test_x_nr.py"])])
    monkeypatch.setattr(op, "_tests_gates", lambda root: {"tests/nr/test_x_nr.py"})
    bilan = op.evaluer(log=log, root=tmp_path, lanceur=lambda t: False)
    assert bilan["prouvees"] == 0
    assert op.entrees(log)[0]["etat"] == op.CONSTATE


def test_un_test_HORS_whitelist_CI_ne_prouve_rien(tmp_path, monkeypatch):
    """Un test qui ne tourne pas en CI ne protege aucune surface : il ne peut
    donc pas servir de preuve posterieure."""
    log = _ecrire(tmp_path / "log.jsonl",
                  [_entree("aaa", "verrou", ["verrou"], ["a.py"],
                           tests=["tests/nr/test_hors_ci_nr.py"])])
    monkeypatch.setattr(op, "_tests_gates", lambda root: set())
    bilan = op.evaluer(log=log, root=tmp_path, lanceur=lambda t: True)
    assert bilan["tests_hors_ci"] == 1 and bilan["prouvees"] == 0


def test_le_symptome_qui_revient_INFIRME(tmp_path):
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "verrou sqlite sur ecriture", ["verrou", "sqlite"],
                ["app/x.py"], date="2026-08-01"),
        _entree("bbb", "encore un verrou sqlite", ["verrou", "sqlite"],
                ["app/x.py"], date="2026-08-20"),
    ])
    bilan = op.evaluer(log=log, root=tmp_path, lanceur=lambda t: True)
    assert bilan["infirmees"] >= 1
    etats = {e["commit"]: e["etat"] for e in op.entrees(log)}
    assert etats["aaa"] == op.INFIRME


def test_un_seul_jeton_commun_ne_suffit_PAS_a_infirmer(tmp_path):
    """Accuser a tort retire une procedure des propositions : le cout des deux
    erreurs n'est pas symetrique, le critere reste exigeant."""
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "verrou sqlite", ["verrou", "sqlite"], ["app/x.py"],
                date="2026-08-01"),
        _entree("bbb", "verrou de lane", ["verrou"], ["app/x.py"], date="2026-08-20"),
    ])
    assert op.recidive(op.entrees(log)[0], op.entrees(log)) is None


def test_deux_commits_du_MEME_JOUR_ne_s_infirment_pas_mutuellement(tmp_path):
    """Faux positif mesure sur le journal reel : avec une comparaison de dates
    au jour, A infirmait B et B infirmait A. Deux verdicts contradictoires."""
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "un pointeur se lit", ["pointeur", "boite"],
                ["tools/x.py"], date="2026-08-31"),
        _entree("bbb", "ne pas fabriquer de reponses", ["pointeur", "boite"],
                ["tools/x.py"], date="2026-08-31"),
    ])
    toutes = op.entrees(log)
    assert op.recidive(toutes[0], toutes) is None
    assert op.recidive(toutes[1], toutes) is None


def test_une_ITERATION_le_lendemain_n_est_pas_une_recidive(tmp_path):
    """Ameliorer un fichier deux jours de suite est du travail en cours. Un
    defaut n'est REVENU que s'il reapparait apres que le correctif a tenu."""
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "separer le dump du clone", ["clone", "veille"],
                ["tools/v.py"], date="2026-08-30"),
        _entree("bbb", "brancher la voie clone", ["clone", "veille"],
                ["tools/v.py"], date="2026-08-31"),
    ])
    toutes = op.entrees(log)
    assert op.recidive(toutes[0], toutes) is None


def test_la_revision_rend_a_CONSTATE_sans_effacer_le_verdict(tmp_path):
    """Append-only : un verdict errone n'est pas supprime, il est CORRIGE.
    Supprimer le rendrait invisible ; le corriger le laisse instructif."""
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "un pointeur", ["pointeur", "boite"], ["tools/x.py"],
                date="2026-08-31"),
        _entree("bbb", "autre pointeur", ["pointeur", "boite"], ["tools/x.py"],
                date="2026-08-31"),
    ])
    op.promouvoir("aaa", op.INFIRME, {"recidive": {"commit": "bbb"}}, log=log)
    assert op.entrees(log)[0]["etat"] == op.INFIRME
    bilan = op.reviser_infirmations(log=log)
    assert bilan["rendus_a_constate"] == 1
    e = {x["commit"]: x for x in op.entrees(log)}["aaa"]
    assert e["etat"] == op.CONSTATE
    assert "ancienne_preuve" in e["preuve"], "le verdict retire doit rester lisible"


def test_un_correctif_ANTERIEUR_n_infirme_pas(tmp_path):
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "verrou sqlite", ["verrou", "sqlite"], ["app/x.py"],
                date="2026-08-20"),
        _entree("bbb", "verrou sqlite", ["verrou", "sqlite"], ["app/x.py"],
                date="2026-08-01"),
    ])
    assert op.recidive(op.entrees(log)[0], op.entrees(log)) is None


def test_l_execution_des_tests_est_BORNEE(tmp_path, monkeypatch):
    """Une boucle autonome qui lance des suites sans plafond devient un pompage."""
    monkeypatch.setattr(op, "_tests_gates", lambda root: {"tests/nr/test_x_nr.py"})
    log = _ecrire(tmp_path / "log.jsonl",
                  [_entree("c%d" % i, "sujet %d" % i, ["jeton%d" % i], ["a%d.py" % i],
                           tests=["tests/nr/test_x_nr.py"]) for i in range(8)])
    appels = []
    op.evaluer(log=log, root=tmp_path, max_execution=2,
               lanceur=lambda t: appels.append(t) or True)
    assert len(appels) == 2


# ── Q3 : une capacite PROUVEE est un invariant historique ──────────────────
def test_toucher_le_perimetre_d_une_capacite_PROUVEE_est_signale(tmp_path):
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "le verrou tient", ["verrou"], ["app/x.py"],
                tests=["tests/nr/test_x_nr.py"], etat=op.PROUVE)])
    # `tests` ne porte que les fichiers PRESENTS sous `root` (5c0044003) : le test cite
    # doit exister. Sans `root`, ce NR lisait le depot reel et rougissait depuis ce commit.
    (tmp_path / "tests" / "nr").mkdir(parents=True)
    (tmp_path / "tests" / "nr" / "test_x_nr.py").write_text("", encoding="utf-8")
    r = op.capacites_touchees(["app/x.py"], log=log, root=tmp_path)
    assert len(r) == 1
    assert r[0]["tests"] == ["tests/nr/test_x_nr.py"]
    assert r[0]["tests_absents"] == []
    assert r[0]["fichiers_communs"] == ["app/x.py"]


def test_un_test_cite_mais_disparu_est_DIT_absent_pas_rejoue(tmp_path):
    """Vecu le 2026-09-27 : un test renomme restait cite, et l'avertissement faisait
    rejouer un fichier qui n'existait plus. Il sort de `tests`, et il est DIT."""
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "le verrou tient", ["verrou"], ["app/x.py"],
                tests=["tests/nr/test_x_nr.py"], etat=op.PROUVE)])
    r = op.capacites_touchees(["app/x.py"], log=log, root=tmp_path)
    assert len(r) == 1
    assert r[0]["tests"] == []
    assert r[0]["tests_absents"] == ["tests/nr/test_x_nr.py"]


def test_un_CONSTATE_ne_declenche_PAS_le_garde(tmp_path):
    """195 entrees sur 199 sont CONSTATE : avertir sur elles ferait crier le
    garde presque a chaque ecriture, et un garde qui crie a faux se fait
    desarmer. Seule une mesure posterieure protege quelque chose."""
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "peut-etre repare", ["verrou"], ["app/x.py"],
                tests=["tests/nr/test_x_nr.py"])])
    assert op.capacites_touchees(["app/x.py"], log=log) == []


def test_un_fichier_hors_perimetre_ne_declenche_rien(tmp_path):
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "le verrou tient", ["verrou"], ["app/x.py"],
                tests=["tests/nr/test_x_nr.py"], etat=op.PROUVE)])
    assert op.capacites_touchees(["app/tout_autre.py"], log=log) == []


def test_aucun_fichier_donne_ne_rend_rien(tmp_path):
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "x", ["verrou"], ["app/x.py"], etat=op.PROUVE)])
    assert op.capacites_touchees([], log=log) == []


def test_le_chemin_absolu_reconnait_le_perimetre_relatif(tmp_path):
    """governed_edit passe un chemin ABSOLU ; le journal stocke du relatif.
    Sans rapprochement des deux, le garde ne se declencherait jamais."""
    log = _ecrire(tmp_path / "log.jsonl", [
        _entree("aaa", "x", ["verrou"], ["app/x.py"], etat=op.PROUVE)])
    assert op.capacites_touchees(["C:/Users/n/Nokido/app/x.py"], log=log)


def test_les_trois_etats_existent_et_sont_distincts():
    assert len({op.CONSTATE, op.PROUVE, op.INFIRME}) == 3


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
