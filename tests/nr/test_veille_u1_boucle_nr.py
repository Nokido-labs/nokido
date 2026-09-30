"""Non-regression : le pilote de cloture U1 se regule, et dit ce qu'il ne sait pas.

POURQUOI UN PILOTE. 243 depots demandes jamais ingeres, 183 restants au 2026-09-08.
Les fermer lot par lot a la main coute un aller-retour par lot pour un travail que
le corps sait faire seul. Mais un producteur SANS garde de charge est exactement ce
qui a mis la machine a 98 % et fait accuser l'embedder a tort : le pilote porte donc
sa garde, et elle est a HYSTERESIS -- un seuil unique pomperait, en repartant au
dixieme de point sous la barre.

INVARIANTS EXIGES, chacun paye ailleurs dans ce depot :
  - les seuils viennent de `forge_physiology` (HIGH / RELEASE) et ne sont JAMAIS
    reinventes ici. Le test le prouve en les DEPLACANT : un pilote qui les aurait
    recopies en dur ne suivrait pas.
  - capteur RAM illisible => ABSTENTION, jamais feu vert. Un capteur qui rend la
    meme chose pour "je ne sais pas" et pour "tout va bien" fabrique des faux
    negatifs indetectables.
  - l'abstention est ECRITE avec son motif : un drain muet ne se distingue pas d'un
    drain mort.
  - le progres porte son DENOMINATEUR (total / traites / restants). Sans lui,
    "10 traites" ne dit pas si le travail avance ou piétine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "tools", RACINE / "app"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_physiology as ph  # noqa: E402
import forge_veille_u1_boucle as b  # noqa: E402


def test_capteur_illisible_vaut_ABSTENTION_jamais_feu_vert():
    ok, motif = b.garde(None, en_pause=False)
    assert ok is False, "une RAM illisible a ete lue comme une RAM saine"
    assert "illisible" in motif.lower(), f"motif muet sur l'illisibilite : {motif!r}"


def test_au_dessus_de_HIGH_le_pilote_se_met_en_pause():
    ok, motif = b.garde(ph.HIGH + 1.0, en_pause=False)
    assert ok is False and motif, "pas de pause au-dessus du seuil haut, ou sans motif"


def test_sous_RELEASE_le_pilote_repart():
    ok, _ = b.garde(ph.RELEASE - 1.0, en_pause=True)
    assert ok is True, "le pilote ne repart pas alors que la charge est retombee"


def test_dans_la_BANDE_l_etat_courant_est_CONSERVE():
    """C'est toute la difference entre une hysteresis et un seuil : dans la bande,
    on ne re-decide pas -- sinon on pompe."""
    milieu = (ph.HIGH + ph.RELEASE) / 2.0
    assert b.garde(milieu, en_pause=True)[0] is False, "reprise prematuree dans la bande"
    assert b.garde(milieu, en_pause=False)[0] is True, "pause injustifiee dans la bande"


def test_les_seuils_sont_LUS_pas_recopies(monkeypatch):
    """Preuve par deplacement : on abaisse HIGH, le pilote doit suivre."""
    monkeypatch.setattr(ph, "HIGH", 50.0)
    monkeypatch.setattr(ph, "RELEASE", 40.0)
    assert b.garde(60.0, en_pause=False)[0] is False, (
        "le pilote n'a pas suivi le seuil deplace : il porte ses propres constantes")


def test_la_boucle_s_arrete_quand_il_ne_reste_RIEN(tmp_path):
    etats = [(243, 233, 10), (243, 243, 0)]
    faits = []

    def lire_etat():
        return etats[min(len(faits), len(etats) - 1)]

    def lancer_lot(taille):
        faits.append(taille)
        return 0

    r = b.boucle(lancer_lot=lancer_lot, lire_etat=lire_etat, taille_lot=10,
                 max_lots=50, progress=tmp_path / "p.json",
                 lire_ram=lambda: 50.0, dormir=lambda s: None)
    assert r["restants_final"] == 0
    assert r["lots_faits"] == 1, f"lots inutiles apres epuisement : {r}"


def test_le_progres_porte_son_DENOMINATEUR(tmp_path):
    p = tmp_path / "p.json"
    b.boucle(lancer_lot=lambda t: 0, lire_etat=lambda: (243, 243, 0), taille_lot=10,
             max_lots=1, progress=p, lire_ram=lambda: 50.0, dormir=lambda s: None)
    d = json.loads(p.read_text(encoding="utf-8"))
    for cle in ("total", "traites", "restants"):
        assert cle in d, f"progres sans denominateur : {cle} manquant dans {sorted(d)}"
    assert d["total"] == d["traites"] + d["restants"], f"denominateur incoherent : {d}"


def test_une_ABSTENTION_est_ECRITE_avec_son_motif(tmp_path):
    p = tmp_path / "p.json"
    r = b.boucle(lancer_lot=lambda t: 0, lire_etat=lambda: (243, 60, 183),
                 taille_lot=10, max_lots=1, progress=p,
                 lire_ram=lambda: None, dormir=lambda s: None)
    assert r["lots_faits"] == 0, "un lot a ete lance malgre un capteur illisible"
    assert r["motifs"], "abstention SILENCIEUSE : indistinguable d'un pilote mort"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d.get("motifs"), "le motif d'abstention n'atteint pas le fichier de progres"


def test_un_progres_RELATIF_est_ancre_sur_le_depot(tmp_path, monkeypatch):
    """Le repertoire de travail d'un job detache est `<depot>/sandbox/workspace` : un
    `--progress` relatif partait donc dans `sandbox/workspace/sandbox/`, et un pilote
    qui travaille se lisait comme un pilote muet. Meme defaut que celui corrige le
    meme jour dans `forge_job_watch_notify` -- une correction qui ne balaie pas la
    FAMILLE laisse le piege ailleurs."""
    monkeypatch.chdir(tmp_path)
    resolu = b._resoudre("sandbox/veille_u1_boucle.progress.json")
    assert Path(resolu).is_absolute()
    assert str(RACINE) in str(resolu), (
        f"ancre sur le repertoire courant ({tmp_path}) au lieu du depot : {resolu}")
    ailleurs = tmp_path / "ailleurs.json"
    assert Path(b._resoudre(str(ailleurs))) == ailleurs, "un chemin absolu a ete deplace"


def test_le_point_d_entree_CLI_traverse(monkeypatch, capsys, tmp_path):
    """Le chemin REEL, pas seulement les fonctions : `check()` passait ses tests
    pendant que `--check` mourait en NameError. Tout drapeau CLI a son test."""
    monkeypatch.setattr(b, "_etat", lambda: (243, 60, 183))
    monkeypatch.setattr(sys, "argv", ["forge_veille_u1_boucle", "--dry-run",
                                      "--progress", str(tmp_path / "p.json")])
    rc = b.main()
    sortie = capsys.readouterr().out
    assert rc == 0, f"le point d'entree sort en rc={rc}"
    assert "183 restants" in sortie, (
        f"le denominateur n'atteint pas la sortie du CLI : {sortie!r}")
    assert "dry-run" in sortie, "le dry-run ne se declare pas : un lot a pu partir"
    assert "progres ->" in sortie, (
        "le pilote n'annonce pas OU il ecrit son progres : une porte muette")


def test_max_lots_est_une_BORNE_qui_dit_combien(tmp_path):
    faits = []
    r = b.boucle(lancer_lot=lambda t: faits.append(t) or 0,
                 lire_etat=lambda: (243, 60, 183), taille_lot=10, max_lots=3,
                 progress=tmp_path / "p.json", lire_ram=lambda: 50.0,
                 dormir=lambda s: None)
    assert len(faits) == 3 and r["lots_faits"] == 3
    assert r["restants_final"] == 183, (
        "un arret sur borne doit RENDRE ce qui reste, sinon le rattrapage est perdu")
