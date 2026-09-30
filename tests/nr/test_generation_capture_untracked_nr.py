# -*- coding: utf-8 -*-
"""NR — la capture de génération ne compte pas les fichiers NON SUIVIS.

__FORGE_COLOR__ = "qualite/gate : non-regression de la capture d etat de reference"

CE QUI A ÉTÉ PAYÉ (2026-09-07). `_inscrire_generation` refusait de capturer un sha dès
que `git status --porcelain` rendait quoi que ce soit — **y compris des fichiers non
suivis**. Or le dépôt en porte des dizaines en permanence, par conception :
`docs/gitingest_*.manifest.json`, artefacts de `sandbox/`, rapports qu'un simple
`--audit` régénère.

Le critère était donc **INATTEIGNABLE PAR CONSTRUCTION**. Quatre CI vertes d'affilée
n'ont capturé aucun sha, et le critère de sortie de la phase 0 — *« un statut FERMÉ PAR
COMMIT »* — ne pouvait pas être atteint, quoi qu'on fasse. On a cherché la cause du côté
de l'arbre pendant deux runs avant de la trouver dans le juge.

**Le raisonnement du gate était juste, sa traduction était fausse.** Ce qui rend un sha
non représentatif, ce sont les modifications de fichiers **suivis** : eux seuls auraient
dû être commités. Un fichier non suivi n'a jamais fait partie d'un commit — il ne
contredit pas le sha, il doit être **dit**.

D'où la règle de la maison appliquée ici : *une borne doit dire COMBIEN, pas seulement
TROP*. Le nombre de non-suivis est imprimé avec la capture, pour que la trace dise ce
qu'elle n'inclut pas.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / "tools" / "ci_local.py"


def _bloc_generation() -> str:
    """Le corps de `_inscrire_generation`, isolé — on ne lit pas tout le fichier :
    `ci_local.py` cite `git status` ailleurs, et un test qui lirait tout se prononcerait
    sur le mauvais appel."""
    src = CI.read_text(encoding="utf-8", errors="replace")
    i = src.find("def _inscrire_generation")
    assert i > 0, "la fonction de capture a disparu"
    j = src.find("\ndef ", i + 10)
    return src[i: j if j > 0 else len(src)]


# --- 2026-09-09 : DOMAINE DE VALIDITE CORRIGE, force INCHANGEE ---------------------
#
# Ces trois tests visaient la STRUCTURE du juge (`--untracked-files=no`, `if sale:`).
# Le juge a change de forme le 2026-09-09 : il classe desormais chaque entree de
# `git status` en PRODUIT / PREUVE / INATTENDU, parce que le critere d'alors avait
# encore un angle mort -- un fichier SUIVI que la CI ecrit ELLE-MEME
# (`tests/nr/vitalite_gardes.json`) rendait la capture impossible, exactement comme
# les non-suivis en 2026-09-07. Meme defaut, autre bout.
#
# Deux contrats se sont alors heurtes, et l'arbitrage (owner) a ete de les
# ORTHOGONALISER plutot que d'en sacrifier un :
#
#     PRODUIT     modification d'un fichier suivi non declare  -> REFUS
#     INATTENDU   fichier non suivi non declare                -> REFUS
#     PREUVE      sortie declaree du protocole                 -> AUTORISE
#
# Ce que ce fichier garde reste donc le meme : *une modification NON DECLAREE
# interdit la capture*. Ce qu'il cesse d'affirmer, c'est que TOUTE modification
# l'interdit -- c'etait vrai du juge d'alors, pas du contrat.
#
# ⚠️ CONSEQUENCE ASSUMEE, a ne pas redecouvrir : sur l'arbre PARTAGE, les dizaines de
# non-suivis que le depot porte en permanence (docs/gitingest_*.manifest.json,
# rapports d'audit) sont desormais INATTENDU, donc bloquants. La capture n'a plus
# lieu que dans un worktree de reference isole -- ce qui est precisement ce que T0
# exige : la CI ne tient pas un arbre, elle tient un SHA.

def _ci():
    """`ci_local` importe depuis tools/ — ce fichier n'inserait que app/."""
    import importlib  # noqa: PLC0415
    import sys  # noqa: PLC0415
    chemin = str(ROOT / "tools")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    return importlib.import_module("ci_local")


def test_une_sortie_de_preuve_declaree_n_empeche_pas_la_capture() -> None:
    """L'intention du 2026-09-07, portee par le contrat et non plus par une option."""
    C = _ci()
    ok, motif = C.capture_autorisee([
        ("??", "docs/generations/GEN-00013.json"),
        (" M", "tests/nr/vitalite_gardes.json"),
        ("??", "sandbox/ci_LaForgeSbxOffline/"),
    ])
    assert ok is True, (
        "les sorties que la mesure produit elle-meme ne doivent pas lui interdire "
        "de conclure : %s" % motif)


def test_une_modification_NON_DECLAREE_bloque_toujours() -> None:
    """Le garde ne doit pas avoir ete affaibli pour obtenir la capture.

    Les deux natures interdites sont testees : un fichier du produit MODIFIE, et un
    fichier non suivi qui n'appartient a aucune sortie declaree. La seconde est la
    contre-epreuve -- sans elle, le juge accepterait n'importe quel intrus pourvu
    qu'il ne soit pas suivi.
    """
    C = _ci()
    ok, motif = C.capture_autorisee([(" M", "app/forge_rag_engine.py")])
    assert ok is False, "un fichier SUIVI modifie doit interdire la capture"
    assert "forge_rag_engine" in motif, "le refus doit NOMMER le fichier"

    ok2, motif2 = C.capture_autorisee([("??", "app/intrus.py")])
    assert ok2 is False, "un non-suivi hors sortie declaree doit interdire la capture"
    assert "intrus.py" in motif2

    assert C.classer_modification(" M", "app/forge_rag_engine.py") == "PRODUIT"
    assert C.classer_modification("??", "app/intrus.py") == "INATTENDU"


def test_la_capture_dit_ce_qu_elle_n_inclut_pas() -> None:
    """Une borne dit COMBIEN, pas seulement TROP."""
    bloc = _bloc_generation()
    assert "non suivi" in bloc, "le nombre de non-suivis doit etre rendu a l'appelant"


def test_la_capture_ne_rougit_jamais_un_run_vert() -> None:
    """Contrat d'origine, a preserver : la capture est best-effort."""
    bloc = _bloc_generation()
    assert "Ne bloque JAMAIS la CI" in bloc or "ne doit pas rougir" in bloc


def test_un_run_partiel_ne_pretend_pas_au_stable() -> None:
    bloc = _bloc_generation()
    assert "if partiel:" in bloc, (
        "une reference batie sur une mesure partielle est un faux point sur")


# --- 2026-09-07, seconde moitie : l'ACL, et l'echec qui ne se nommait pas -----------
#
# Le critere corrige ci-dessus a laisse apparaitre la cause SUIVANTE, distincte :
# `docs/generations/` est un artefact SUIVI par git, donc il vit dans le depot -- et
# aucun compte sandbox n'y a l'ecriture (mesure : docs/ NON, tests/nr/ NON, sandbox/
# OUI). La CI tourne detachee sous l'un d'eux et ne peut pas deleguer au hub non plus,
# un run_job ne voyant pas le loopback. Trois causes successives pour un meme critere.

def _module_generation():
    import importlib
    import sys
    chemin = str(ROOT / "app")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    return importlib.import_module("forge_generation")


def test_l_echec_de_capture_nomme_le_fichier() -> None:
    """Un echec se NOMME : type, chemin, errno.

    Paye le 2026-09-07 : le gestionnaire n'imprimait que `type(_e).__name__`. Trois
    runs ont donc repete « PermissionError » sans jamais dire QUEL fichier etait
    inaccessible -- on sait qu'il y a eu echec, pas ce qui a echoue."""
    bloc = _bloc_generation()
    i = bloc.find("except Exception as _e")
    assert i > 0, "le gestionnaire best-effort a disparu"
    queue = bloc[i:]
    for champ in ("filename", "errno"):
        assert champ in queue, (
            "le type seul ne dit pas ce qui etait inaccessible : exposer %s" % champ)


def test_l_inscription_differee_a_sa_branche_et_ne_se_dit_pas_inscrite() -> None:
    """MESUREE mais NON INSCRITE est un troisieme etat, ni succes ni echec."""
    bloc = _bloc_generation()
    i = bloc.find("inscription_differee")
    assert i > 0, "le cas differe doit etre traite explicitement, pas confondu"
    branche = bloc[i:i + 900]
    assert "NON INSCRITE" in branche, "l'affichage doit dire que rien n'est inscrit"
    assert "inscrite\\033" not in branche, (
        "la branche differee ne doit jamais emprunter le message de succes")


def test_capturer_ne_compte_pas_les_non_suivis_pour_propre() -> None:
    """Le champ `depot.propre` portait le MEME defaut que le critere de la CI.

    Sans cette correction, toute generation s'inscrirait avec `propre: false` a jamais,
    et se relirait comme batie sur un arbre sale."""
    src = (ROOT / "app" / "forge_generation.py").read_text(encoding="utf-8",
                                                           errors="replace")
    i = src.find('"propre"')
    assert i > 0, "le champ propre a disparu de la generation"
    assert "--untracked-files=no" in src[i - 400:i + 200], (
        "propre doit se juger sur les fichiers SUIVIS seulement")
    assert '"non_suivis"' in src, "une borne dit COMBIEN, pas seulement TROP"


def test_l_acl_differe_l_inscription_et_ne_perd_pas_la_mesure(tmp_path,
                                                              monkeypatch) -> None:
    """Une ecriture refusee DIFFERE l'inscription ; elle ne perd pas la mesure.

    C'est la difference entre « je n'ai pas pu ecrire » et « il ne s'est rien passe »."""
    fg = _module_generation()
    cible = tmp_path / "generations"
    cible.mkdir()
    attente = tmp_path / "en_attente"
    monkeypatch.setattr(fg, "DOSSIER", cible)
    monkeypatch.setattr(fg, "DOSSIER_ATTENTE", attente)
    vus = []
    monkeypatch.setattr(fg, "_append_oplog", lambda *a, **k: vus.append(a))

    ecrire = Path.write_text

    def refuse(self, *args, **kwargs):
        if self.parent == cible:
            raise PermissionError(13, "Permission denied", str(self))
        return ecrire(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse)
    gen = fg.capturer(tests={"pure": "PASS"}, agent="NR")

    differe = gen.get("inscription_differee")
    assert differe, "une ACL doit DIFFERER l'inscription, jamais l'effacer"
    assert differe["errno"] == 13, "le motif systeme doit remonter tel quel"
    assert "GEN-" in differe["cible"], "la cible refusee doit etre nommee"

    depose = attente / ("%s.json" % gen["generation"])
    assert depose.is_file(), "la mesure doit survivre au refus d'ecriture"
    relu = json.loads(depose.read_text(encoding="utf-8"))
    assert relu["depot"]["sha"] == gen["depot"]["sha"], (
        "le depot doit porter la MEME mesure, pas un resume")
    assert not vus, "l'oplog ne consigne pas un gain qui n'a pas ete inscrit"


# --------------------------------------------------------------------------
# Le NUMERO doit rester unique quand l'inscription est DIFFEREE
# --------------------------------------------------------------------------
#
# MESURE DU 2026-09-14. Deux generations DIFFERENTES portaient le meme numero :
#
#   sandbox/generations_en_attente/GEN-00013.json   sha b55857a799...  (14/09 04:45)
#   <preuve>/artefacts/generations/GEN-00013.json   sha 37739da46a...  (14/09 12:xx)
#
# `_prochain_numero()` lit l'union de `DOSSIER` et `DOSSIER_SEQUENCE`, mais PAS
# `DOSSIER_ATTENTE`. Or c'est precisement la que vont les captures quand l'ACL
# refuse l'ecriture dans `docs/generations` -- ce que le correctif du 2026-09-07
# a rendu possible pour ne pas PERDRE la mesure. Les deux briques sont justes ;
# c'est leur croisement qui manquait.
#
# Consequence mesuree : `docs/generations` s'arrete a GEN-00012 (09/09), donc
# depuis cinq jours CHAQUE capture rejoue le numero 13. L'historique devient
# ambigu sans que rien ne le signale -- et une generation est justement ce qui
# doit permettre de revenir a un etat NOMME.


def test_le_compteur_compte_les_generations_DIFFEREES(tmp_path, monkeypatch) -> None:
    """Une generation en attente EXISTE : elle consomme son numero."""
    fg = _module_generation()
    cible = tmp_path / "generations"
    cible.mkdir()
    attente = tmp_path / "en_attente"
    attente.mkdir()
    monkeypatch.setattr(fg, "DOSSIER", cible)
    monkeypatch.setattr(fg, "DOSSIER_SEQUENCE", cible)
    monkeypatch.setattr(fg, "DOSSIER_ATTENTE", attente)
    (cible / "GEN-00012.json").write_text("{}", encoding="utf-8")
    (attente / "GEN-00013.json").write_text("{}", encoding="utf-8")
    assert fg._prochain_numero() == 14, (
        "le compteur ignore les inscriptions differees : GEN-00013 serait reattribue")


def test_deux_captures_DIFFEREES_ne_portent_pas_le_meme_numero(tmp_path,
                                                               monkeypatch) -> None:
    """LE cas reel, sur le chemin de production.

    Deux captures successives dont l'inscription est refusee doivent recevoir DEUX
    numeros. Sinon le second ecrase le premier dans le dossier d'attente, et la
    mesure qu'on croyait sauvee est perdue -- ce que le correctif du 2026-09-07
    voulait justement empecher."""
    fg = _module_generation()
    cible = tmp_path / "generations"
    cible.mkdir()
    attente = tmp_path / "en_attente"
    monkeypatch.setattr(fg, "DOSSIER", cible)
    monkeypatch.setattr(fg, "DOSSIER_SEQUENCE", cible)
    monkeypatch.setattr(fg, "DOSSIER_ATTENTE", attente)
    monkeypatch.setattr(fg, "_append_oplog", lambda *a, **k: None)

    ecrire = Path.write_text

    def refuse(self, *args, **kwargs):
        if self.parent == cible:
            raise PermissionError(13, "Permission denied", str(self))
        return ecrire(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", refuse)
    g1 = fg.capturer(tests={"pure": "PASS"}, agent="NR")
    g2 = fg.capturer(tests={"pure": "PASS"}, agent="NR")

    assert g1["generation"] != g2["generation"], (
        "deux captures differees portent le meme numero : la premiere est ecrasee")
    restants = sorted(p.name for p in attente.glob("GEN-*.json"))
    assert len(restants) == 2, (
        "une mesure differee a disparu : %s" % restants)


def test_une_inscription_reussie_reste_le_chemin_normal(tmp_path, monkeypatch) -> None:
    """Le repli ne doit pas devenir le chemin ordinaire : sans refus, on ecrit la cible."""
    fg = _module_generation()
    cible = tmp_path / "generations"
    cible.mkdir()
    attente = tmp_path / "en_attente"
    monkeypatch.setattr(fg, "DOSSIER", cible)
    monkeypatch.setattr(fg, "DOSSIER_ATTENTE", attente)
    monkeypatch.setattr(fg, "_append_oplog", lambda *a, **k: None)

    gen = fg.capturer(tests={"pure": "PASS"}, agent="NR")
    assert "inscription_differee" not in gen, "aucun refus : rien a differer"
    assert (cible / ("%s.json" % gen["generation"])).is_file()
    assert not attente.exists(), "le depot de repli ne se cree que sur refus"
