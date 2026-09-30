# -*- coding: utf-8 -*-
"""NR — une page de doc DIT sa date de revue, et cette date vient de GIT.

MESURE 2026-09-17. Sur `docs/wiki/`, le `mtime` annoncait 25,1 j pour presque
toutes les pages. La date GIT, elle, donne **jusqu'a 91 jours** :

    21-SSoT-Cross-CLI ........... 91 j
    06-Hub-API-Reference.fr ..... 71 j
    01-Installation, 02-Quick-Start, 09-TUI-Reference, 19-Knowledge-Pack . 70 j
    21 pages au-dela de 60 j

Le `mtime` etait la date d'un CHECKOUT, pas d'une revue. Un gate fonde dessus
aurait declare fraiche une page abandonnee depuis trois mois -- et sur le runner
GitHub, ou tout est clone le jour meme, il les aurait TOUTES declarees fraiches.
C'est la meme famille que `job_status` apres un kill externe : le registre ment,
le reel tranche.

CE QUE L'OUTIL NE FAIT PAS : juger si le contenu est juste. Ca demande une
relecture humaine. Il inscrit un fait VERIFIABLE -- la date du dernier commit --
et laisse le lecteur decider. Meme principe que la note des ports arretes : on
n'a pas reecrit les pages, on a ajoute une note de peremption.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_docs_datation as D  # noqa: E402


def test_la_date_ne_vient_PAS_du_mtime():
    """Verrou structurel : un `mtime` est reecrit par tout clone ou checkout.
    Juge sur l'AST -- chercher la chaine condamnerait le commentaire qui
    l'explique (piege paye deux fois le 2026-09-16)."""
    import ast as _ast

    src = (ROOT / "tools" / "forge_docs_datation.py").read_text(
        encoding="utf-8", errors="replace")
    fautifs = [n.lineno for n in _ast.walk(_ast.parse(src))
               if isinstance(n, _ast.Attribute) and n.attr in ("st_mtime", "st_ctime")]
    assert not fautifs, (
        "mtime/ctime utilise aux lignes %s : la date serait celle du checkout, "
        "donc toutes les pages paraitraient fraiches sur le runner" % fautifs)


def test_une_date_illisible_rend_INCONNUE_jamais_une_date_inventee(monkeypatch, tmp_path):
    """`UNKNOWN != NO` : git muet ne prouve pas que la page est fraiche."""
    monkeypatch.setattr(D.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("git absent")))
    assert D.date_du_dernier_commit(tmp_path / "x.md") is None


def test_une_sortie_git_non_datee_est_REFUSEE(monkeypatch, tmp_path):
    """Une sortie inattendue ne doit pas etre prise pour une date."""
    class _R:
        stdout, stderr = "fatal: pas un depot\n", ""

    monkeypatch.setattr(D.subprocess, "run", lambda *a, **k: _R())
    assert D.date_du_dernier_commit(tmp_path / "x.md") is None


def test_la_note_INCONNUE_ne_se_lit_pas_comme_A_JOUR():
    note = D.note(None, None)
    assert "INCONNUE" in note
    assert "NON MESURE" in note, (
        "une date absente doit etre dite NON MESUREE, pas laissee muette")


def test_la_note_porte_la_date_en_une_ligne_sans_age_qui_perime():
    """Owner 2026-09-29 : « simplement mise a jour avec la date ». L'age relatif
    n'est plus ecrit -- dans une page statique, « il y a 0 jours » ment des le
    lendemain ; c'est le gate `--check` qui le calcule a chaque passage."""
    note = D.note("2026-06-18", 91)
    visibles = [l for l in note.splitlines() if l.startswith("> ")]
    assert visibles == ["> Mise à jour : 2026-06-18"], visibles
    assert "91" not in note and "il y a" not in note
    assert D.note("2026-06-18", 91, fr=False).splitlines()[1] == "> Updated: 2026-06-18"


def test_la_datation_est_IDEMPOTENTE(tmp_path, monkeypatch):
    """Rejouer l'outil ne doit pas empiler les notes : une page datee deux fois
    porterait deux dates contradictoires."""
    monkeypatch.setattr(D, "date_du_dernier_commit", lambda *a, **k: "2026-06-18")
    p = tmp_path / "page.md"
    p.write_text("# Titre\n\ncorps\n", encoding="utf-8")
    assert D.traiter(p, True, tmp_path)[0] == "DATEE"
    assert D.traiter(p, True, tmp_path)[0] in ("INCHANGEE", "MISE_A_JOUR")
    assert p.read_text(encoding="utf-8").count(D.MARQUEUR) == 1


def test_la_datation_n_EFFACE_PAS_la_date_qu_elle_mesure(tmp_path, monkeypatch):
    """L'instrument ne doit pas modifier ce qu'il observe.

    VU LE 2026-09-17, avant de committer les 50 pages. Ecrire la note CHANGE le
    fichier, donc son dernier commit devient celui de la DATATION. Au passage
    suivant, git aurait rendu « 0 j » pour les 50 pages et le gate aurait
    declare tout frais -- un faux calme fabrique par l'outil, sur des pages
    vieilles de 70 a 91 jours. La date deja inscrite est donc CONSERVEE.
    """
    appels = []

    def _git(*a, **k):
        appels.append(a)
        return "2026-09-17"          # ce que git dirait APRES le commit de datation

    p = tmp_path / "page.md"
    p.write_text("# Titre\n\n<!-- revu-le: 2026-06-18 (91 j) -->\n"
                 "> ancienne note\n\ncorps\n", encoding="utf-8")
    monkeypatch.setattr(D, "date_du_dernier_commit", _git)
    D.traiter(p, True, tmp_path)
    t = p.read_text(encoding="utf-8")
    assert "2026-06-18" in t, (
        "la date d'origine a ete ecrasee par celle du commit de datation : "
        "le gate declarerait fraiche une page de 91 jours")
    assert "2026-09-17" not in t
    assert not appels, "git ne doit meme pas etre interroge quand une date est inscrite"


def test_la_note_se_pose_APRES_le_titre_et_ne_mange_pas_le_corps(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "date_du_dernier_commit", lambda *a, **k: "2026-06-18")
    p = tmp_path / "page.md"
    p.write_text("# Titre\n\ncorps important\n", encoding="utf-8")
    D.traiter(p, True, tmp_path)
    t = p.read_text(encoding="utf-8")
    assert t.startswith("# Titre")
    assert "corps important" in t, "le corps historique doit rester intact"


def test_une_page_ILLISIBLE_est_DITE(tmp_path, monkeypatch):
    p = tmp_path / "casse.md"
    p.write_text("# x\n", encoding="utf-8")

    def _boom(self, *a, **k):
        raise OSError("acces refuse")

    monkeypatch.setattr(Path, "read_text", _boom)
    assert D.traiter(p, False, tmp_path)[0] == "ILLISIBLE"
