"""NR -- instrument KPI des methodes de dev (decision owner 16/10 : « c'est la mesure qui devra decider »).

Piste 6 de la synthese des methodes (First Pass Yield) : part des CI de reference vertes au premier passage, et
part des correctifs dont le commit cite le RED observe. Classement par liste BLANCHE (constitution) : n'est VERT que
ce qui est PROUVE vert sur tous ses champs ; un journal sans ligne de preuve est ILLISIBLE, jamais vert ni rouge.
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_kpi_methode as K  # noqa: E402

PREUVE_VERTE = ("  [preuve] sha=67dd185dab72  executes=15062  skipped=26  echecs=0  erreurs=0  timeouts=0  "
                "blocs_sans_preuve=0  declares_absents=0  etat=SUITE_COMPLETE")
GATES_OK = "\x1b[1;32mTous les gates bloquants passent\x1b[0m \x1b[1;33m(1 non mesure(s), tous supplees)\x1b[0m"


def test_journal_prouve_vert_sur_tous_ses_champs():
    assert K.verdict_journal("\n".join(["x", PREUVE_VERTE, GATES_OK])) == "VERT"


def test_un_echec_rend_rouge():
    assert K.verdict_journal("\n".join([PREUVE_VERTE.replace("echecs=0", "echecs=1"), GATES_OK])) == "ROUGE"


def test_suite_incomplete_rend_rouge():
    assert K.verdict_journal("\n".join([PREUVE_VERTE.replace("SUITE_COMPLETE", "SUITE_INCOMPLETE"),
                                        GATES_OK])) == "ROUGE"


def test_preuve_verte_sans_gates_apres_elle_rend_rouge():
    assert K.verdict_journal("\n".join([GATES_OK, PREUVE_VERTE])) == "ROUGE"


def test_preuve_sans_tous_ses_champs_rend_illisible():
    """Un champ absent n'est pas un zero : sans lui on ne PROUVE ni vert ni rouge."""
    assert K.verdict_journal("\n".join([PREUVE_VERTE.replace("erreurs=0  ", ""), GATES_OK])) == "ILLISIBLE"


def test_sans_ligne_de_preuve_rend_illisible():
    assert K.verdict_journal("Tous les gates bloquants passent") == "ILLISIBLE"


def test_le_listing_source_du_journal_n_est_pas_un_verdict():
    """Les journaux recopient du code (`68 |  "tous les gates bloquants passent" ...`) : il ne compte pas."""
    listing = '68 |             "Tous les gates bloquants passent" if rc == 0 else ...'
    assert K.verdict_journal("\n".join([PREUVE_VERTE, listing])) == "ROUGE"


def test_lots_premier_passage():
    """Un lot = passages consecutifs jusqu'au premier VERT inclus ; FPY = lots verts du premier coup / lots clos."""
    r = K.lots_premier_passage(["VERT", "ROUGE", "ROUGE", "VERT", "VERT", "ROUGE"])
    assert (r["lots_clos"], r["verts_premier_passage"], r["lot_ouvert"]) == (3, 2, 1)


def test_un_illisible_ne_compte_ni_vert_ni_rouge():
    r = K.lots_premier_passage(["ROUGE", "ILLISIBLE", "VERT"])
    assert (r["lots_clos"], r["verts_premier_passage"], r["illisibles"]) == (1, 0, 1)


def test_le_point_d_entree_ecrit_le_rapport(tmp_path, monkeypatch):
    import json

    (tmp_path / "ci_complete_aaa.txt").write_text("\n".join([PREUVE_VERTE, GATES_OK]), encoding="utf-8")
    (tmp_path / "ci_complete_bbb.txt").write_text("rien", encoding="utf-8")
    monkeypatch.setattr(K, "_commits", lambda depuis: [("fix(a): x", "RED observe : assert")])
    sortie = tmp_path / "kpi.json"
    assert K.main(["--journaux", str(tmp_path), "--sortie", str(sortie)]) == 0
    r = json.loads(sortie.read_text(encoding="utf-8"))
    assert (r["ci"]["verts"], r["ci"]["illisibles"], r["red"]["red_cite"]) == (1, 1, 1)


def test_part_des_correctifs_qui_citent_leur_red():
    commits = [("fix(a): x", "RED observe : assert 0 == 1"), ("feat(b): y", "corps sans preuve"),
               ("docs(c): z", "rien"), ("fix(d): w", "red OBSERVÉ -> None")]
    assert K.part_red_cite(commits) == {"correctifs": 3, "red_cite": 2}
