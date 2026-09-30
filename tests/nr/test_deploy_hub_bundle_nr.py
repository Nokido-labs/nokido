"""NR — un deploiement de bundle ne REGRESSE jamais la cible en silence.

DEFAUT MESURE le 2026-09-14. `tools/deploy_hub_bundle.py` faisait, sans la
moindre verification :

    SRC = r"C:/tmp/hub-compiled.js"
    shutil.copy(SRC, DST)

Etat du disque ce jour-la :

    C:\\tmp\\hub-compiled.js                          40 279 o   20/06/26
    design_handoff_nokido/ui_kits/hub/hub-compiled.js 44 744 o   11/09/26

Le lancer aurait donc ECRASE un artefact du 11 septembre par un fichier du
20 juin : 83 jours et 4 465 octets de regression, en une copie muette.

POURQUOI C'EST IRRATTRAPABLE ICI, et pas seulement facheux. L'enquete du
2026-09-11 (session 4322ca50) a etabli que ce bundle est un « artefact
pratiquement maintenu A LA MAIN » : le compilateur qui pretend le produire vit
hors depot et ne le genere pas reellement. Ecraser la cible ne se repare donc
pas en relancant une compilation — le travail est perdu.

CE QUE CES TESTS VERROUILLENT :
  - une source PLUS ANCIENNE que la cible est refusee, en le disant ;
  - une source absente est refusee en la nommant, jamais une trace vide ;
  - le cas legitime (source plus recente) passe — on ne troque pas un risque
    contre un outil mort ;
  - le refus est CONTOURNABLE explicitement (`force`), parce qu'un operateur
    peut vouloir revenir en arriere sciemment ; ce qui est interdit, c'est de
    le faire SANS LE SAVOIR.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import deploy_hub_bundle as d  # noqa: E402


def _ecrire(chemin: Path, contenu: str, mtime: float) -> Path:
    chemin.write_text(contenu, encoding="utf-8")
    import os
    os.utime(chemin, (mtime, mtime))
    return chemin


def test_une_source_plus_ancienne_est_refusee(tmp_path: Path):
    """Le cas exact du 2026-09-14 : 20 juin ecrasant le 11 septembre."""
    src = _ecrire(tmp_path / "src.js", "vieux", 1_000_000.0)
    dst = _ecrire(tmp_path / "dst.js", "recent-et-plus-gros", 2_000_000.0)
    ok, motif = d.decider_deploiement(src, dst)
    assert ok is False, "une source plus ancienne ne doit pas ecraser la cible"
    assert "ancien" in motif.lower(), f"le refus doit dire POURQUOI : {motif!r}"


def test_le_refus_chiffre_l_ecart(tmp_path: Path):
    """« plus ancienne » ne suffit pas : de combien ? Un refus qui ne chiffre
    pas laisse l'operateur sans moyen de juger s'il doit forcer."""
    src = _ecrire(tmp_path / "src.js", "v", 1_000_000.0)
    dst = _ecrire(tmp_path / "dst.js", "vv", 1_000_000.0 + 86400 * 83)
    _ok, motif = d.decider_deploiement(src, dst)
    assert any(c.isdigit() for c in motif), f"aucun chiffre dans le motif : {motif!r}"


def test_une_source_absente_est_nommee(tmp_path: Path):
    """Trois etats, jamais deux : absent se DIT, il ne devient pas un echec muet."""
    ok, motif = d.decider_deploiement(tmp_path / "nexistepas.js", tmp_path / "dst.js")
    assert ok is False
    assert "absent" in motif.lower() or "introuvable" in motif.lower()
    assert "nexistepas" in motif, "le refus doit nommer le chemin cherche"


def test_le_cas_legitime_passe(tmp_path: Path):
    """Controle NEGATIF : on ne remplace pas un risque par un outil inutilisable."""
    src = _ecrire(tmp_path / "src.js", "neuf", 2_000_000.0)
    dst = _ecrire(tmp_path / "dst.js", "vieux", 1_000_000.0)
    ok, _motif = d.decider_deploiement(src, dst)
    assert ok is True


def test_une_cible_absente_est_un_premier_deploiement(tmp_path: Path):
    """Pas de cible = rien a regresser. Refuser ici bloquerait l'installation."""
    src = _ecrire(tmp_path / "src.js", "neuf", 2_000_000.0)
    ok, _motif = d.decider_deploiement(src, tmp_path / "pas_encore.js")
    assert ok is True


# NOTE (2026-09-14). Un test verrouillant la neutralisation de `tmp_copy_bundle`
# a ete ecrit ici, puis RETIRE : ce fichier est couvert par `.gitignore`
# (`tools/tmp_*.py` est jetable par conception). Un NR versionne qui lit un
# fichier NON versionne passe en local et ECHOUE sur le runner -- c'est le piege
# exact referme le meme jour dans `hook_recon_first`, et je l'ai failli
# reintroduire ici. Un test ne s'appuie que sur ce que le depot porte.


def test_le_retour_arriere_reste_possible_mais_explicite(tmp_path: Path):
    """Un garde qu'on ne peut pas lever se fait contourner autrement."""
    src = _ecrire(tmp_path / "src.js", "vieux", 1_000_000.0)
    dst = _ecrire(tmp_path / "dst.js", "recent", 2_000_000.0)
    ok, motif = d.decider_deploiement(src, dst, force=True)
    assert ok is True
    assert "force" in motif.lower(), "un passage en force doit rester TRACE"
