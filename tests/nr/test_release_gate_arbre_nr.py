# -*- coding: utf-8 -*-
"""L'arbre propre juge les SOURCES, pas ce que le corps regenere.

Mesure 2026-08-30 : `tools/forge_post_commit.py` reecrit le tampon
`<!-- STATS:<sha du HEAD> -->` du README apres CHAQUE commit. Commiter le README
change le sha, donc le hook le reecrit : la boucle ne converge jamais et
`ctrl_arbre_propre` etait rouge par construction -- il s'est resali trois fois
pendant une seule session. Un controle rouge par construction finit par etre
ignore, et c'est alors le vrai defaut qu'on ne verra plus.

Ecarter n'est pas taire : le detail doit NOMMER ce qui a ete ecarte.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _status(monkeypatch, sortie: str, rc: int = 0, err: str = ""):
    """Le faux `_git` doit imiter le VRAI, y compris son `.strip()` global.

    Sans ce `.strip()`, le test fournissait une sortie idealisee que la fonction
    ne recoit jamais -- et il a donc laisse passer le bug « EADME.md » le
    2026-08-30. Un test qui n'imite pas sa source donne un faux vert.
    """
    import forge_release_gate as g

    monkeypatch.setattr(g, "_git", lambda *_a, **_kw: (rc, sortie.strip(), err))
    return g


def test_le_premier_fichier_garde_son_nom_entier(monkeypatch):
    """Regression : la sortie strippee decalait la decoupe par position.

    ` M README.md` devenait `M README.md`, donc `l[3:]` rendait « EADME.md » --
    un nom absent de la liste des derives, si bien que l'artefact passait pour une
    SOURCE sale et rougissait le gate. Le premier fichier est le seul touche, ce
    qui rend le defaut d'autant plus facile a rater.
    """
    # Assertion par NOM ENTIER, entre quotes : « EADME not in detail » ne pourrait
    # jamais passer, « EADME » etant une sous-chaine de « README ». Piege de
    # redaction paye a l'ecriture de ce test meme.
    g = _status(monkeypatch, " M README.md\n M docs/skills/nokido/SKILL.md")
    etat, detail = g.ctrl_arbre_propre()
    assert "'README.md'" in detail, "le nom du premier fichier est tronque"
    assert etat == g.VERT


def test_un_chemin_avec_espaces_reste_entier(monkeypatch):
    """La decoupe sur le premier blanc ne doit pas couper le chemin lui-meme."""
    g = _status(monkeypatch, " M app/un dossier/fichier.py")
    etat, detail = g.ctrl_arbre_propre()
    assert etat == g.ROUGE
    assert "app/un dossier/fichier.py" in detail


def test_seuls_des_artefacts_derives_ne_rougissent_pas_le_gate(monkeypatch):
    g = _status(monkeypatch, " M README.md\n M docs/skills/nokido/SKILL.md")
    etat, detail = g.ctrl_arbre_propre()
    assert etat == g.VERT
    # Ecarte, mais NOMME : sinon l'angle mort redevient un vert.
    assert "README.md" in detail and "ecarte" in detail


def test_une_source_sale_reste_rouge_et_est_nommee(monkeypatch):
    g = _status(monkeypatch, " M app/forge_chain_executor.py")
    etat, detail = g.ctrl_arbre_propre()
    assert etat == g.ROUGE
    assert "app/forge_chain_executor.py" in detail


def test_la_source_prime_sur_les_derives(monkeypatch):
    """Un derive sale ne doit jamais masquer une source en attente."""
    g = _status(monkeypatch, " M README.md\n M tools/forge_release_gate.py")
    etat, detail = g.ctrl_arbre_propre()
    assert etat == g.ROUGE
    assert "tools/forge_release_gate.py" in detail
    assert "README.md" not in detail, "le derive ne doit pas etre compte comme source"


def test_arbre_totalement_propre(monkeypatch):
    g = _status(monkeypatch, "")
    etat, detail = g.ctrl_arbre_propre()
    assert etat == g.VERT and "aucun fichier" in detail


def test_git_muet_est_illisible_jamais_vert(monkeypatch):
    """Une absence de mesure n'est pas un arbre propre."""
    g = _status(monkeypatch, "", rc=128, err="dubious ownership")
    etat, _ = g.ctrl_arbre_propre()
    assert etat == g.ILLISIBLE
